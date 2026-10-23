"""
dashboard.py
------------
Generate a polished, LOCAL HTML dashboard for FILDZA MOD ROUTER.

The dashboard runs on THIS Windows PC. It is an offline analysis and
diagnostics view; it is NOT the router's web UI and it does NOT replace
http://192.168.1.1. Every data point is tagged with its provenance:

    REAL         - measured/computed on this machine right now
    UNAVAILABLE  - the check ran but the target did not respond
    PLACEHOLDER  - example/seed data, not a live reading

Usage (Windows):
    python dashboard.py                 # inspect bundled firmware + live net
    python dashboard.py --open          # also open it in the default browser
    python dashboard.py --no-firmware   # skip the slow 148 MB hash
    python dashboard.py --router 192.168.1.1
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import os
import webbrowser
from datetime import datetime, timezone
from typing import List, Optional

import firmware_inspector
from src import connectivity_tests, network_diagnostics

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FIRMWARE_DIR = os.path.join(
    _HERE, "Archer_NX205(EU)_1.0_1.0.0_3.1.0_Build_250731"
)
CONNECTIVITY_LOG = os.path.join(_HERE, "data", "connectivity_log.json")
OUTPUT_HTML = os.path.join(_HERE, "dashboard.html")

DEVICE_NAME = "TP-Link Archer NX205(EU) V1"
DEVICE_REGION = "EU"
REPORTED_INSTALLED_BUILD = "251223"

# --- Palette (charcoal / white / amber) ------------------------------------
_CSS = """
:root{
  --charcoal:#1a1c20; --charcoal-2:#23262c; --panel:#2a2e35;
  --line:#3a3f48; --white:#f3f4f6; --muted:#9aa0aa;
  --amber:#f5a623; --amber-soft:#ffcf70;
  --green:#4ec07a; --red:#e5574e; --yellow:#e8c84d;
}
*{box-sizing:border-box}
body{margin:0;background:var(--charcoal);color:var(--white);
  font:15px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
header.brand{border-bottom:2px solid var(--amber);padding:18px 0 14px;margin-bottom:8px}
header.brand h1{margin:0;font-size:26px;letter-spacing:2px;color:var(--amber);font-weight:700}
header.brand .sub{color:var(--muted);font-size:13px;letter-spacing:1px;margin-top:4px}
.disclaimer{background:#3a2e14;border:1px solid var(--amber);border-radius:8px;
  padding:12px 14px;margin:16px 0;color:var(--amber-soft);font-size:13px}
.disclaimer b{color:var(--amber)}
section{background:var(--charcoal-2);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;margin:16px 0}
section h2{margin:0 0 12px;font-size:15px;letter-spacing:1px;color:var(--amber);
  text-transform:uppercase;border-bottom:1px solid var(--line);padding-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.kv{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kv .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.kv .v{color:var(--white);font-size:14px;margin-top:3px;word-break:break-all}
.mono{font-family:"Cascadia Code",Consolas,monospace;font-size:12px}
.badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.5px;
  padding:2px 7px;border-radius:999px;vertical-align:middle;margin-left:6px}
.b-real{background:#143a24;color:var(--green);border:1px solid var(--green)}
.b-unavail{background:#3a1f1d;color:var(--red);border:1px solid var(--red)}
.b-err{background:#24282e;color:#9aa0aa;border:1px solid #4a515c}
.b-ph{background:#3a3a18;color:var(--yellow);border:1px solid var(--yellow)}
.tiles{display:flex;flex-wrap:wrap;gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px 16px;text-align:center;min-width:92px}
.tile .n{font-size:22px;font-weight:700;color:var(--amber)}
.tile .l{font-size:11px;color:var(--muted);text-transform:uppercase}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px}
.note{font-size:13px;padding:7px 10px;border-radius:6px;margin:6px 0}
.note.warn{background:#3a2e14;color:var(--amber-soft)}
.note.bad{background:#3a1f1d;color:#f3b0ab}
.note.good{background:#143a24;color:#a8e6c0}
.note.info{background:var(--panel);color:var(--muted)}
.legend{font-size:12px;color:var(--muted)}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:24px;
  border-top:1px solid var(--line);padding-top:14px}
a{color:var(--amber-soft)}
"""


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _badge(status: str) -> str:
    mapping = {
        "ok": ('b-real', 'REAL'),
        "verified": ('b-real', 'REAL'),
        "unreachable": ('b-unavail', 'UNAVAILABLE'),
        "error": ('b-err', 'ERROR'),
        "no-reference": ('b-ph', 'NO REFERENCE'),
        "mismatch": ('b-unavail', 'MISMATCH'),
        "real": ('b-real', 'REAL'),
        "placeholder": ('b-ph', 'PLACEHOLDER'),
    }
    cls, label = mapping.get(status, ('b-ph', status.upper()))
    return f'<span class="badge {cls}">{label}</span>'


def _kv(key: str, value, badge: str = "") -> str:
    return (f'<div class="kv"><div class="k">{_esc(key)}</div>'
            f'<div class="v">{_esc(value)}{badge}</div></div>')


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def _section_device() -> str:
    return (
        '<section><h2>Target Device</h2><div class="grid">'
        + _kv("Device", DEVICE_NAME)
        + _kv("Region", DEVICE_REGION)
        + _kv("Reported installed", f"Build {REPORTED_INSTALLED_BUILD}")
        + _kv("Hardware revision", "EU / 1.0 (V1)")
        + '</div></section>'
    )


def _section_firmware(reports) -> str:
    if not reports:
        return ('<section><h2>Firmware Inspection</h2>'
                '<div class="note info">Firmware inspection skipped '
                '(--no-firmware).</div></section>')
    blocks: List[str] = []
    for res in reports:
        if res.error:
            blocks.append(f'<div class="note bad">{_esc(res.report.filename)}: '
                          f'{_esc(res.error)}</div>')
            continue
        r = res.report
        grid = ['<div class="grid">']
        grid.append(_kv("File", r.filename, _badge("real")))
        grid.append(_kv("Size", r.hashes.size_human))
        grid.append(_kv("Detected format", r.detection.format_name))
        grid.append(_kv("Confidence", r.detection.confidence))
        if r.filename_meta.build:
            grid.append(_kv("Parsed build", r.filename_meta.build))
        if r.kernel_version:
            grid.append(_kv("Kernel string", r.kernel_version, _badge("real")))
        if r.entropy_bits:
            grid.append(_kv("Entropy", f"{r.entropy_bits} bits/byte"))
        grid.append('</div>')
        sha = (f'<div class="kv"><div class="k">SHA-256 '
               f'{_badge("real")}</div><div class="v mono">'
               f'{_esc(r.hashes.sha256)}</div></div>')
        integ = _badge(r.integrity_status)
        notes = [f'<div class="note info">Integrity: '
                 f'{_esc(r.integrity_status.upper())} {integ} &mdash; '
                 f'{_esc(r.integrity_detail)}</div>']
        if r.embedded:
            rows = "".join(
                f'<tr><td>{_esc(h.name)}</td><td>x{h.count}</td>'
                f'<td class="mono">{h.first_offset}</td></tr>'
                for h in r.embedded)
            notes.append(
                '<table><tr><th>Embedded component</th><th>Count</th>'
                f'<th>First offset</th></tr>{rows}</table>')
        for w in r.warnings:
            notes.append(f'<div class="note warn">{_esc(w)}</div>')
        blocks.append("".join(grid) + sha + "".join(notes) + "<hr style='border:0;"
                      "border-top:1px solid var(--line);margin:14px 0'>")
    return f'<section><h2>Firmware Inspection</h2>{"".join(blocks)}</section>'


def _fmt_ping(p: network_diagnostics.PingResult) -> str:
    if p.status == "ok":
        return (f'{p.received}/{p.sent} replies, {p.loss_percent:.0f}% loss, '
                f'avg {p.rtt_avg_ms} ms (min {p.rtt_min_ms} / max {p.rtt_max_ms})')
    return p.detail or f'{p.loss_percent:.0f}% loss'


def _section_diagnostics(snap: network_diagnostics.DiagnosticsSnapshot,
                         gateway_info: str = "") -> str:
    rp, ip = snap.router_ping, snap.internet_ping
    tiles = (
        '<div class="tiles">'
        f'<div class="tile"><div class="n">{ip.rtt_avg_ms if ip.status=="ok" else "--"}</div>'
        '<div class="l">Internet avg ms</div></div>'
        f'<div class="tile"><div class="n">{ip.loss_percent:.0f}%</div>'
        '<div class="l">Internet loss</div></div>'
        f'<div class="tile"><div class="n">{rp.loss_percent:.0f}%</div>'
        '<div class="l">Router loss</div></div>'
        f'<div class="tile"><div class="n">{len(snap.dns.addresses)}</div>'
        '<div class="l">DNS answers</div></div>'
        '</div>'
    )
    hp = snap.router_http
    if hp.status == "ok":
        http_val = f"HTTP {hp.http_code} - {hp.detail}"
        if hp.server:
            http_val += f" (Server: {hp.server})"
    else:
        http_val = hp.detail
    tcp = snap.router_tcp
    tcp_val = (f"{tcp.connect_ms} ms" if tcp.status == "ok" else tcp.detail)
    grid = (
        '<div class="grid">'
        + _kv(f"Router reachability - ICMP ({snap.router_ip})",
              _fmt_ping(rp), _badge(rp.status))
        + _kv(f"Internet reachability - ICMP ({ip.host})",
              _fmt_ping(ip), _badge(ip.status))
        + _kv(f"DNS resolution ({snap.dns.hostname})",
              ", ".join(snap.dns.addresses) or snap.dns.detail, _badge(snap.dns.status))
        + _kv(f"Admin port TCP :{snap.http_port}", tcp_val, _badge(tcp.status))
        + _kv(f"Admin page HTTP :{snap.http_port}", http_val, _badge(hp.status))
        + '</div>'
    )
    stamp = f'<div class="legend">Snapshot taken: {_esc(snap.timestamp)} (UTC)</div>'
    gw = (f'<div class="legend">Router target: {_esc(gateway_info)}</div>'
          if gateway_info else "")
    note = ('<div class="note info">These readings are from THIS PC. A reachable '
            'internet with 0% loss confirms ordinary connectivity only &mdash; it '
            'does NOT prove unrestricted hotspot/tethering access, which is governed '
            'by the carrier.</div>')
    return (f'<section><h2>Live Network Diagnostics</h2>{tiles}{grid}{gw}{stamp}'
            f'{note}</section>')


def _section_connectivity(log: connectivity_tests.ConnectivityLog) -> str:
    s = log.summary()
    tiles = (
        '<div class="tiles">'
        f'<div class="tile"><div class="n">{s["total"]}</div><div class="l">total</div></div>'
        f'<div class="tile"><div class="n">{s["pass"]}</div><div class="l">pass</div></div>'
        f'<div class="tile"><div class="n">{s["fail"]}</div><div class="l">fail</div></div>'
        f'<div class="tile"><div class="n">{s["not-tested"]}</div><div class="l">not-tested</div></div>'
        '</div>'
    )
    rows = []
    for o in log.observations:
        prov = "placeholder" if o.approved_by == "example" else "real"
        rows.append(
            f'<tr><td>{_esc(o.test_name)}</td><td>{_esc(o.interface)}</td>'
            f'<td>{_esc(o.result)}{_badge(prov)}</td><td>{_esc(o.detail)}</td></tr>')
    table = ('<table><tr><th>Observation</th><th>Interface</th><th>Result</th>'
             f'<th>Detail</th></tr>{"".join(rows)}</table>') if rows else \
            '<div class="note info">No observations recorded.</div>'
    return (f'<section><h2>Connectivity Observations (recorded, not live)</h2>'
            f'{tiles}{table}</section>')


def _section_feasibility() -> str:
    good = ('use TP-Link\'s official firmware + official upgrade procedure only, '
            'or download the GPL source to study/rebuild GPL components for '
            'research (not a flashable whole image).')
    blockers = [
        "No Archer NX205 entry exists in the OpenWrt Table of Hardware; no "
        "community port is published.",
        "TP-Link's GPL Code Center provides GPL components only (kernel, "
        "BusyBox, etc.) - not the full build system, proprietary drivers, or "
        "the packaging/signing tool needed to assemble a complete image.",
        "The .bin is a proprietary, vendor-signed wrapper (header magic "
        "03 00 00 03). The device verifies this signature; without TP-Link's "
        "private key (not public) a rebuilt image is rejected.",
        "Newer official firmware (Build 260630) is explicitly marked "
        "irreversible/no-downgrade; anti-rollback blocks installing older builds.",
    ]
    items = "".join(f'<div class="note warn">{_esc(b)}</div>' for b in blockers)
    return (
        '<section><h2>Custom Firmware Feasibility</h2>'
        '<div class="note bad"><b>NOT feasible</b> to legitimately build a '
        'flashable custom image or replace the router web UI from the available '
        'materials, for this exact hardware (NX205 V1).</div>'
        f'{items}'
        f'<div class="note good">Legitimate paths: {_esc(good)}</div>'
        '</section>'
    )


def _section_provenance() -> str:
    return (
        '<section><h2>Data Provenance</h2>'
        f'<div class="legend">{_badge("real")} measured or computed on this PC '
        f'now &nbsp; {_badge("unreachable")} check ran, target did not respond '
        f'&nbsp; {_badge("error")} check could not run (e.g. no target/gateway) '
        f'&nbsp; {_badge("placeholder")} example/seed data, not a live reading'
        '</div></section>'
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_html(reports, snap, log, gateway_info="") -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = "".join([
        '<header class="brand"><h1>FILDZA MOD ROUTER</h1>'
        '<div class="sub">NX205 Firmware &amp; Connectivity Dashboard '
        '&mdash; local, read-only</div></header>',
        '<div class="disclaimer"><b>Local tool.</b> This page runs on your PC '
        'for analysis and diagnostics. It is <b>not</b> the router firmware and '
        'does <b>not</b> replace http://192.168.1.1. It never flashes, modifies, '
        'downgrades, or reconfigures the router, and never changes device '
        'identity. The router\'s firmware is unmodified.</div>',
        _section_device(),
        _section_firmware(reports),
        _section_diagnostics(snap, gateway_info),
        _section_connectivity(log),
        _section_feasibility(),
        _section_provenance(),
        f'<footer>Generated {now} (UTC) &middot; FILDZA MOD ROUTER '
        '&middot; read-only analysis prototype</footer>',
    ])
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Fildza Mod Router</title><style>{_CSS}</style></head>'
            f'<body><div class="wrap">{body}</div></body></html>')


def generate(router_ip=None, do_firmware=True, output=OUTPUT_HTML,
             http_port=80, http_scheme="http", gateway_info="") -> str:
    """Build the dashboard. ``router_ip=None`` means 'target undetermined' and
    the router rows are rendered as ERROR (no invented IP)."""
    reports = []
    if do_firmware and os.path.isdir(DEFAULT_FIRMWARE_DIR):
        reports = firmware_inspector.inspect_directory(
            DEFAULT_FIRMWARE_DIR, device_region=DEVICE_REGION,
            installed_build=REPORTED_INSTALLED_BUILD)
    snap = network_diagnostics.run_snapshot(
        router_ip=router_ip, http_port=http_port, http_scheme=http_scheme)
    log = connectivity_tests.seed_example_log(CONNECTIVITY_LOG)
    htmltext = build_html(reports, snap, log, gateway_info=gateway_info)
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(htmltext)
    return output


def resolve_target(router_arg):
    """
    Decide which router IP to probe and how it was chosen.

    Returns (router_ip_or_None, gateway_info_string). If ``router_arg`` is
    given it is used verbatim (override preserved). Otherwise the default
    gateway is auto-detected; on failure we return None (never a guessed IP)
    and surface the manual command.
    """
    if router_arg:
        return router_arg, f"{router_arg} (manual --router override)"

    gw = network_diagnostics.detect_default_gateway()
    if gw.status == "ok":
        print(f"[+] Auto-detected default gateway: {gw.gateway} "
              f"(source: {gw.source})")
        return gw.gateway, f"{gw.gateway} (auto-detected via {gw.source})"

    # Detection failed -> explain, show the manual command, invent nothing.
    print("[!] Could not auto-detect the default gateway.")
    print(f"    Reason: {gw.detail}")
    print("    " + gw.manual_hint.replace("\n", "\n    "))
    return None, "undetermined (gateway auto-detection failed)"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the local HTML dashboard.")
    ap.add_argument("--router", default=None,
                    help="Router IP/host to probe. If omitted, the default "
                         "gateway is auto-detected (not assumed to be 192.168.1.1).")
    ap.add_argument("--port", type=int, default=80,
                    help="Admin web port to probe (e.g. 80 or 443).")
    ap.add_argument("--scheme", default="http", choices=["http", "https"],
                    help="Scheme for the admin-page probe.")
    ap.add_argument("--no-firmware", action="store_true",
                    help="Skip the firmware hash (faster).")
    ap.add_argument("--open", action="store_true",
                    help="Open the dashboard in the default browser.")
    ap.add_argument("--output", default=OUTPUT_HTML)
    args = ap.parse_args(argv)

    router_ip, gateway_info = resolve_target(args.router)
    if router_ip:
        print(f"[*] Probing {args.scheme}://{router_ip}:{args.port} "
              "(read-only, no login) and building dashboard...")
    else:
        print("[*] Building dashboard without a router target "
              "(router checks will show ERROR).")

    path = generate(router_ip=router_ip, do_firmware=not args.no_firmware,
                    output=args.output, http_port=args.port,
                    http_scheme=args.scheme, gateway_info=gateway_info)
    print(f"[+] Dashboard written to: {path}")
    if args.open:
        webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
        print("[+] Opened in default browser.")
    else:
        print("    Open it in your browser, or re-run with --open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
