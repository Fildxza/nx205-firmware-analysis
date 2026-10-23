"""
workstation.py
--------------
Launcher for the FILDZA MOD ROUTER workstation (NX205 Firmware Analysis &
Network Diagnostics Workstation).

It starts a local, read-only web backend (Python standard library only) that
serves the web UI and exposes the existing diagnostic/firmware engine. The
server binds to 127.0.0.1 so the interface is local to this PC.

Usage (Windows, from the project folder):
    python workstation.py                 # auto-detect gateway, open browser
    python workstation.py --router 192.168.1.1 --port 443 --scheme https
    python workstation.py --serve-port 8787 --no-open
    python workstation.py --no-detect     # skip gateway auto-detection

Existing CLI options are preserved: --router, --port, --scheme.
Safety: router checks are read-only and unauthenticated. Nothing here flashes
firmware, changes router configuration, or stores credentials.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from typing import List, Optional

from src import branding, network_diagnostics, workstation_server


def port_is_free(host: str, port: int, timeout: float = 0.3) -> bool:
    """
    True if nothing is already listening on host:port.

    On Windows, http.server would otherwise bind *alongside* an existing
    listener (SO_REUSEADDR behaves like SO_REUSEPORT), splitting requests
    between two servers. A quick connect probe avoids that.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        # connect_ex == 0 means a listener accepted the connection -> in use.
        return sock.connect_ex((host, port)) != 0


def choose_port(host: str, preferred: int, attempts: int = 12) -> Optional[int]:
    """Return the first free port at or after ``preferred`` (or None)."""
    for candidate in range(preferred, preferred + attempts):
        if port_is_free(host, candidate):
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="workstation.py",
        description=f"{branding.PRODUCT_NAME} - {branding.PRODUCT_SUBTITLE}")
    ap.add_argument("--router", default=None,
                    help="Router IP/host. If omitted, the default gateway is "
                         "auto-detected (not assumed to be 192.168.1.1).")
    ap.add_argument("--port", type=int, default=80,
                    help="Admin web port to probe (e.g. 80 or 443).")
    ap.add_argument("--scheme", default="http", choices=["http", "https"],
                    help="Scheme for the HTTP admin-page probe.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Address to bind the local UI server (default local).")
    ap.add_argument("--serve-port", type=int, default=8787,
                    help="TCP port for the local UI server.")
    ap.add_argument("--no-open", action="store_true",
                    help="Do not open the browser automatically.")
    ap.add_argument("--no-detect", action="store_true",
                    help="Do not auto-detect the gateway at startup.")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    app = workstation_server.WorkstationApp(
        router=args.router, port=args.port, scheme=args.scheme)

    # Resolve the target: explicit --router wins; otherwise auto-detect.
    if not args.router and not args.no_detect:
        gw = app.detect_gateway()
        if gw.get("status") == "ok":
            print(f"[+] Auto-detected default gateway: {gw['gateway']} "
                  f"(source: {gw['source']})")
        else:
            print("[!] Could not auto-detect the default gateway.")
            print(f"    Reason: {gw.get('detail', 'unknown')}")
            print("    Set it in the Settings tab, or relaunch with "
                  "--router <gateway-ip>.")

    # Begin the one-time firmware hash in the background so the Firmware Lab is
    # ready by the time the user opens it.
    app.start_firmware_analysis()

    chosen = choose_port(args.host, args.serve_port)
    if chosen is None:
        print(f"[x] No free port found near {args.serve_port} on {args.host}.")
        print("    Free a port or pass --serve-port <n>.")
        return 2
    if chosen != args.serve_port:
        print(f"[!] Port {args.serve_port} is already in use; "
              f"using {chosen} instead.")

    try:
        server = workstation_server.make_server(args.host, chosen, app)
    except OSError as exc:
        print(f"[x] Could not start the UI server on {args.host}:{chosen}: {exc}")
        print("    Try a different port: python workstation.py --serve-port 8080")
        return 2

    url = f"http://{args.host}:{chosen}/"
    target = app.settings.get("router") or "(set in Settings)"
    print(f"[*] {branding.PRODUCT_NAME} — {branding.PRODUCT_SUBTITLE}")
    print(f"[+] Workstation UI:  {url}")
    print(f"[+] Diagnostic target: {args.scheme}://{target}:{args.port} "
          "(read-only, no login)")
    print("[i] Press Ctrl+C to stop.")

    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Shutting down.")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
