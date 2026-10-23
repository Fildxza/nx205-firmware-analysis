"""
network_diagnostics.py
----------------------
Safe, read-only connectivity diagnostics for the real-device demonstration.

Everything here only *observes* the network from this Windows PC:
  * default-gateway detection (via `ipconfig`) so the router need not be
    assumed to live at 192.168.1.1,
  * ICMP ping (via the system `ping` command) -> loss and latency,
  * DNS resolution (via socket.getaddrinfo),
  * TCP reachability of a host:port (via a plain socket connect),
  * an unauthenticated HTTP admin-page probe (status code only, no login).

It does NOT log in to the router, change any router or hotspot setting, probe
carrier APNs, or touch device identity. No administrator rights are needed.

Each result carries an explicit ``status``:
  * "ok"          - the check ran and succeeded,
  * "unreachable" - the check ran and the target did not respond,
  * "error"       - the check could not run (tool missing, bad input),
so a dashboard can clearly separate real readings from unavailable data.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class PingResult:
    host: str
    status: str                       # ok | unreachable | error
    sent: int = 0
    received: int = 0
    loss_percent: float = 100.0
    rtt_min_ms: Optional[float] = None
    rtt_avg_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    detail: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class DnsResult:
    hostname: str
    status: str                       # ok | unreachable | error
    addresses: List[str] = field(default_factory=list)
    detail: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class TcpResult:
    host: str
    port: int
    status: str                       # ok | unreachable | error
    connect_ms: Optional[float] = None
    detail: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class GatewayResult:
    status: str                       # ok | error
    gateway: Optional[str] = None     # the detected default-gateway IPv4
    source: str = ""                  # how it was found, e.g. "ipconfig"
    detail: str = ""                  # human explanation (esp. on error)
    manual_hint: str = ""             # exact manual command to run on failure
    timestamp: str = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Default-gateway detection (Windows-first, read-only)
# ---------------------------------------------------------------------------
# A clear, copy-pasteable fallback shown when auto-detection fails. We never
# invent an IP address; the user reads their real gateway and passes it in.
_MANUAL_HINT = (
    "Run `ipconfig` and read your adapter's \"Default Gateway\", then run:\n"
    "    python dashboard.py --router <that-gateway>"
)


def _parse_gateway_from_ipconfig(text: str) -> Optional[str]:
    """
    Return the first non-empty IPv4 "Default Gateway" from `ipconfig` output.

    Windows prints lines like:
        Default Gateway . . . . . . . . . : 192.168.1.1
    but frequently the IPv6 gateway comes first and the IPv4 sits on an
    indented *continuation* line with no label:
        Default Gateway . . . . . . . . . : fe80::1%12
                                            192.168.1.1
    So after seeing a "Default Gateway" label we keep scanning the following
    unlabelled continuation lines for an IPv4, until the next labelled field.
    We return the first real IPv4 that is not 0.0.0.0. An adapter with a blank
    gateway is skipped. Parsing is isolated here so it is unit-testable offline.
    """
    ipv4 = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    in_gateway = False
    for line in text.splitlines():
        is_label = ":" in line  # Windows fields look like "Name . . . : value"
        if "Default Gateway" in line:
            in_gateway = True
            m = ipv4.search(line)
            if m and m.group(1) != "0.0.0.0":
                return m.group(1)
            continue
        if is_label:
            in_gateway = False  # a new labelled field ends the gateway block
            continue
        if in_gateway:          # unlabelled continuation line under a gateway
            m = ipv4.search(line)
            if m and m.group(1) != "0.0.0.0":
                return m.group(1)
    return None


def detect_default_gateway() -> GatewayResult:
    """
    Detect the active IPv4 default gateway on this machine (read-only).

    On Windows this parses `ipconfig`. On other platforms it tries
    `ip route`/`route -n` so the function is testable, but Windows is the
    supported target. On any failure it returns status "error" WITH a manual
    hint and never guesses an address.
    """
    try:
        if sys.platform == "win32":
            proc = subprocess.run(["ipconfig"], capture_output=True, text=True,
                                  timeout=15)
            gw = _parse_gateway_from_ipconfig(proc.stdout)
            if gw:
                return GatewayResult("ok", gateway=gw, source="ipconfig")
            return GatewayResult(
                "error", source="ipconfig",
                detail="No IPv4 Default Gateway found in ipconfig output. Are "
                       "you connected to the router's Wi-Fi or a LAN port?",
                manual_hint=_MANUAL_HINT,
            )
        # Non-Windows best effort (kept simple; the demo target is Windows).
        proc = subprocess.run(["ip", "route"], capture_output=True, text=True,
                              timeout=15)
        m = re.search(r"default via (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                      proc.stdout)
        if m:
            return GatewayResult("ok", gateway=m.group(1), source="ip route")
        return GatewayResult("error", source="ip route",
                             detail="No default route found.",
                             manual_hint=_MANUAL_HINT)
    except FileNotFoundError:
        return GatewayResult("error",
                             detail="Network tool not found on this system.",
                             manual_hint=_MANUAL_HINT)
    except subprocess.TimeoutExpired:
        return GatewayResult("error",
                             detail="Gateway detection timed out.",
                             manual_hint=_MANUAL_HINT)
    except OSError as exc:
        return GatewayResult("error", detail=f"Gateway detection failed: {exc}",
                             manual_hint=_MANUAL_HINT)


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------
def ping(host: str, count: int = 4, timeout_ms: int = 1000) -> PingResult:
    """
    Run the OS `ping` command against ``host`` and parse loss + latency.

    Uses the Windows flags (-n, -w) on win32 and the Unix flags (-c, -W)
    elsewhere so the module is testable on any platform.
    """
    if sys.platform == "win32":
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), host]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * (timeout_ms / 1000) + 10
        )
    except FileNotFoundError:
        return PingResult(host, "error", detail="`ping` command not found.")
    except subprocess.TimeoutExpired:
        return PingResult(host, "unreachable", sent=count, detail="ping timed out.")

    return _parse_ping_output(host, proc.stdout, count)


def _parse_ping_output(host: str, output: str, count: int) -> PingResult:
    """Parse ping stdout (Windows or Unix wording) into a PingResult."""
    sent = received = 0
    loss = 100.0
    rtt_min = rtt_avg = rtt_max = None

    # Packet counts (Windows): "Sent = 4, Received = 4, Lost = 0 (0% loss)"
    m = re.search(r"Sent\s*=\s*(\d+).*?Received\s*=\s*(\d+).*?\((\d+)%\s*loss\)",
                  output, re.DOTALL)
    if m:
        sent, received = int(m.group(1)), int(m.group(2))
        loss = float(m.group(3))
    else:
        # Unix: "4 packets transmitted, 4 received, 0% packet loss"
        m = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+received.*?(\d+(?:\.\d+)?)%\s+packet loss",
                      output, re.DOTALL)
        if m:
            sent, received = int(m.group(1)), int(m.group(2))
            loss = float(m.group(3))

    # RTT (Windows): "Minimum = 21ms, Maximum = 54ms, Average = 31ms"
    m = re.search(r"Minimum\s*=\s*(\d+)ms,\s*Maximum\s*=\s*(\d+)ms,\s*Average\s*=\s*(\d+)ms",
                  output)
    if m:
        rtt_min, rtt_max, rtt_avg = float(m.group(1)), float(m.group(2)), float(m.group(3))
    else:
        # Unix: "rtt min/avg/max/mdev = 21.0/31.0/54.0/1.0 ms"
        m = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/[\d.]+\s*ms", output)
        if m:
            rtt_min, rtt_avg, rtt_max = float(m.group(1)), float(m.group(2)), float(m.group(3))

    if sent == 0 and received == 0:
        return PingResult(host, "error", detail="Could not parse ping output.")

    status = "ok" if received > 0 else "unreachable"
    return PingResult(
        host=host, status=status, sent=sent, received=received,
        loss_percent=loss, rtt_min_ms=rtt_min, rtt_avg_ms=rtt_avg, rtt_max_ms=rtt_max,
        detail="" if status == "ok" else "No reply from host.",
    )


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------
def resolve_dns(hostname: str) -> DnsResult:
    """Resolve ``hostname`` to IP addresses using the system resolver."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return DnsResult(hostname, "unreachable", detail=f"DNS lookup failed: {exc}")
    except OSError as exc:
        return DnsResult(hostname, "error", detail=str(exc))

    addresses = sorted({info[4][0] for info in infos})
    return DnsResult(hostname, "ok", addresses=addresses)


# ---------------------------------------------------------------------------
# TCP connect (HTTP reachability without changing anything)
# ---------------------------------------------------------------------------
def tcp_connect(host: str, port: int = 80, timeout: float = 3.0) -> TcpResult:
    """Attempt a TCP connection and measure how long the handshake took."""
    import time

    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except (socket.timeout, TimeoutError):
        return TcpResult(host, port, "unreachable", detail="Connection timed out.")
    except OSError as exc:
        return TcpResult(host, port, "unreachable", detail=f"Connect failed: {exc}")
    finally:
        try:
            sock.close()
        except OSError:
            pass
    elapsed = round((time.perf_counter() - start) * 1000, 1)
    return TcpResult(host, port, "ok", connect_ms=elapsed)


# ---------------------------------------------------------------------------
# HTTP admin-page probe (credential-free)
# ---------------------------------------------------------------------------
@dataclass
class HttpResult:
    url: str
    status: str                       # ok | unreachable | error
    http_code: Optional[int] = None   # the HTTP status line code, if any
    responded: bool = False           # did an HTTP server actually answer?
    auth_required: bool = False       # 401/403 or WWW-Authenticate seen
    server: str = ""                  # Server header, if sent (not sensitive)
    latency_ms: Optional[float] = None
    detail: str = ""
    timestamp: str = field(default_factory=_now)


def http_probe(host: str, port: int = 80, scheme: str = "http",
               timeout: float = 4.0) -> HttpResult:
    """
    Check whether an HTTP admin page actually *responds* at ``host``.

    This sends a single unauthenticated GET to the root path and records only
    non-sensitive metadata: the HTTP status code, the Server header, and
    whether authentication is required. It NEVER sends, prompts for, or stores
    any username/password, and it does NOT read or keep the response body.

    An HTTP error status (e.g. 401/403/404) still means the web server
    responded, so it is reported as ``ok`` with the code -- an open, answering
    admin service -- which is different from an unreachable host.
    """
    import time
    import urllib.error
    import urllib.request

    url = f"{scheme}://{host}:{port}/"
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "ACMR-Diagnostics/1.0"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return HttpResult(
                url=url, status="ok", http_code=resp.status, responded=True,
                server=resp.headers.get("Server", ""), latency_ms=elapsed,
                detail="HTTP server responded.",
            )
    except urllib.error.HTTPError as exc:
        # The server answered with an error code -> it IS present.
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        auth = exc.code in (401, 403) or bool(exc.headers.get("WWW-Authenticate"))
        return HttpResult(
            url=url, status="ok", http_code=exc.code, responded=True,
            auth_required=auth, server=exc.headers.get("Server", ""),
            latency_ms=elapsed,
            detail=("Admin page present; authentication required."
                    if auth else f"HTTP {exc.code} from server."),
        )
    except urllib.error.URLError as exc:
        return HttpResult(url=url, status="unreachable",
                          detail=f"No HTTP response: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return HttpResult(url=url, status="unreachable",
                          detail=f"No HTTP response: {exc}")


# ---------------------------------------------------------------------------
# Convenience: a full snapshot for the demonstration
# ---------------------------------------------------------------------------
@dataclass
class DiagnosticsSnapshot:
    router_ping: PingResult          # ICMP reachability of the router
    internet_ping: PingResult        # ICMP reachability of the wider internet
    dns: DnsResult                   # name resolution working
    router_http: HttpResult          # does the admin web page actually respond
    router_tcp: TcpResult            # raw TCP reachability of the admin port
    router_ip: str
    http_port: int = 80
    timestamp: str = field(default_factory=_now)


def run_snapshot(
    router_ip: Optional[str] = "192.168.1.1",
    internet_host: str = "8.8.8.8",
    dns_host: str = "www.tp-link.com",
    http_port: int = 80,
    http_scheme: str = "http",
    count: int = 4,
) -> DiagnosticsSnapshot:
    """
    Run the standard set of checks for the real-device demo.

    Every target is configurable -- the router is not assumed to be at
    192.168.1.1. Each dimension is reported separately: router ICMP, internet
    ICMP, DNS, raw TCP to the admin port, and an actual HTTP admin-page probe.

    If ``router_ip`` is None (gateway could not be detected and no override was
    given), the router checks are marked "error" with an explanation -- we do
    NOT invent an address or run checks against a made-up IP. Internet and DNS
    are still measured so the snapshot stays useful.
    """
    if router_ip is None:
        reason = "Router target not determined (gateway auto-detection failed)."
        router_ping = PingResult("(undetermined)", "error", detail=reason)
        router_http = HttpResult(url="(undetermined)", status="error", detail=reason)
        router_tcp = TcpResult("(undetermined)", http_port, "error", detail=reason)
        router_label = "(undetermined)"
    else:
        router_ping = ping(router_ip, count=count)
        router_http = http_probe(router_ip, http_port, http_scheme)
        router_tcp = tcp_connect(router_ip, http_port)
        router_label = router_ip

    return DiagnosticsSnapshot(
        router_ping=router_ping,
        internet_ping=ping(internet_host, count=count),
        dns=resolve_dns(dns_host),
        router_http=router_http,
        router_tcp=router_tcp,
        router_ip=router_label,
        http_port=http_port,
    )
