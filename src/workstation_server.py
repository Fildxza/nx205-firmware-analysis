"""
workstation_server.py
----------------------
A tiny, dependency-free local web backend for the FILDZA MOD ROUTER
workstation. It serves the static web UI from ``webui/`` and exposes the
project's existing Python diagnostic/firmware engine as a read-only JSON API.

Design choices:
  * Standard library only (http.server + threading). No framework, no DB.
  * Binds to 127.0.0.1 by default - the API is local to this PC.
  * Diagnostic execution lives in network_diagnostics / firmware_inspector;
    this module only orchestrates and serialises. UI rendering is in webui/.
  * Every request handler is wrapped so a single failure returns a clean JSON
    error instead of crashing the server.

Safety: all router checks are read-only and unauthenticated. No credentials are
accepted or stored. No endpoint changes router configuration, flashes firmware,
or alters device identity.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import firmware_inspector
from src import (branding, connectivity_tests, evidence_log,
                 network_diagnostics)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
WEBUI_DIR = os.path.join(_ROOT, "webui")
DATA_DIR = os.path.join(_ROOT, "data")
FIRMWARE_DIR = os.path.join(
    _ROOT, "Archer_NX205(EU)_1.0_1.0.0_3.1.0_Build_250731")
EVIDENCE_PATH = os.path.join(DATA_DIR, "evidence_log.json")
CONNECTIVITY_PATH = os.path.join(DATA_DIR, "connectivity_log.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}

_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-.]{0,253}[A-Za-z0-9])?$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_target(router: str, port, scheme: str) -> Tuple[bool, list]:
    """Validate diagnostic settings. Returns (ok, [error messages])."""
    errors = []
    if not router or not str(router).strip():
        errors.append("Router target is required.")
    else:
        r = str(router).strip()
        if _IPV4_RE.match(r):
            if any(int(o) > 255 for o in r.split(".")):
                errors.append(f"'{r}' is not a valid IPv4 address (octet > 255).")
        elif not _HOST_RE.match(r):
            errors.append(f"'{r}' is not a valid IP address or hostname.")
    try:
        p = int(port)
        if not (1 <= p <= 65535):
            errors.append("Port must be between 1 and 65535.")
    except (TypeError, ValueError):
        errors.append("Port must be an integer.")
    if scheme not in ("http", "https"):
        errors.append("Scheme must be 'http' or 'https'.")
    return (not errors, errors)


class WorkstationApp:
    """Holds configuration, caches, and the engine-backed API methods."""

    def __init__(self, router: Optional[str], port: int = 80,
                 scheme: str = "http") -> None:
        self.settings = self._load_settings(router, port, scheme)
        self.gateway_detection = None   # result of the last auto-detect
        self.session_started = _now()
        self.last_diagnostics = None    # serialised snapshot of the last run
        self._firmware_lock = threading.Lock()
        self._firmware_cache = {"status": "idle", "reports": [],
                                "timestamp": None}

    # -- settings ----------------------------------------------------------
    def _load_settings(self, router, port, scheme) -> dict:
        stored = {}
        if os.path.isfile(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
            except (json.JSONDecodeError, OSError):
                stored = {}
        return {
            "router": router or stored.get("router"),
            "port": int(port or stored.get("port", 80)),
            "scheme": scheme or stored.get("scheme", "http"),
        }

    def save_settings(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        # Only non-secret diagnostic preferences are persisted.
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(self.settings, fh, indent=2)

    def update_settings(self, router, port, scheme) -> Tuple[bool, list]:
        ok, errors = validate_target(router, port, scheme)
        if ok:
            self.settings = {"router": str(router).strip(),
                             "port": int(port), "scheme": scheme}
            self.save_settings()
        return ok, errors

    # -- gateway -----------------------------------------------------------
    def detect_gateway(self) -> dict:
        result = network_diagnostics.detect_default_gateway()
        self.gateway_detection = dataclasses.asdict(result)
        if result.status == "ok" and not self.settings.get("router"):
            self.settings["router"] = result.gateway
        return self.gateway_detection

    # -- diagnostics -------------------------------------------------------
    def run_diagnostics(self, router=None, port=None, scheme=None) -> dict:
        router = router if router is not None else self.settings.get("router")
        port = int(port if port is not None else self.settings.get("port", 80))
        scheme = scheme or self.settings.get("scheme", "http")

        ok, errors = validate_target(router or "", port, scheme)
        if not ok:
            return {"ok": False, "errors": errors}

        snap = network_diagnostics.run_snapshot(
            router_ip=router, http_port=port, http_scheme=scheme)
        serialised = self._serialise_snapshot(snap)
        self.last_diagnostics = serialised
        self._record_snapshot_evidence(snap)
        return {"ok": True, "snapshot": serialised}

    def _serialise_snapshot(self, snap) -> dict:
        return {
            "router_ip": snap.router_ip,
            "http_port": snap.http_port,
            "timestamp": snap.timestamp,
            "checks": {
                "router_icmp": dataclasses.asdict(snap.router_ping),
                "internet_icmp": dataclasses.asdict(snap.internet_ping),
                "dns": dataclasses.asdict(snap.dns),
                "router_tcp": dataclasses.asdict(snap.router_tcp),
                "router_http": dataclasses.asdict(snap.router_http),
            },
        }

    @staticmethod
    def _status_word(engine_status: str) -> str:
        return {
            "ok": evidence_log.STATUS_REAL,
            "unreachable": evidence_log.STATUS_UNAVAILABLE,
            "error": evidence_log.STATUS_ERROR,
        }.get(engine_status, evidence_log.STATUS_ERROR)

    def _record_snapshot_evidence(self, snap) -> None:
        """Append one real evidence row per executed check."""
        log = evidence_log.EvidenceLog(EVIDENCE_PATH)
        rp, ip = snap.router_ping, snap.internet_ping
        dns, tcp, http = snap.dns, snap.router_tcp, snap.router_http

        def rtt(p):
            return (f"{p.loss_percent:.0f}% loss, avg {p.rtt_avg_ms} ms"
                    if p.status == "ok" else (p.detail or f"{p.loss_percent:.0f}% loss"))

        log.record("diagnostics", rp.host, "Router ICMP reachability",
                   self._status_word(rp.status), rtt(rp), "live-measurement",
                   rp.detail)
        log.record("diagnostics", ip.host, "Internet ICMP reachability",
                   self._status_word(ip.status), rtt(ip), "live-measurement",
                   ip.detail)
        log.record("diagnostics", dns.hostname, "DNS resolution",
                   self._status_word(dns.status),
                   ", ".join(dns.addresses) if dns.addresses else "no answer",
                   "live-measurement", dns.detail)
        log.record("diagnostics", f"{tcp.host}:{tcp.port}",
                   "Router TCP port reachability", self._status_word(tcp.status),
                   (f"{tcp.connect_ms} ms" if tcp.status == "ok" else "no connect"),
                   "live-measurement", tcp.detail)
        http_result = (f"HTTP {http.http_code}" if http.http_code
                       else "no HTTP response")
        log.record("diagnostics", http.url, "Router HTTP response",
                   self._status_word(http.status), http_result,
                   "live-measurement", http.detail)
        log.save()

    # -- firmware (cached; computed in the background) ---------------------
    def start_firmware_analysis(self) -> None:
        with self._firmware_lock:
            if self._firmware_cache["status"] in ("computing", "ready"):
                return
            self._firmware_cache["status"] = "computing"
        threading.Thread(target=self._compute_firmware, daemon=True).start()

    def _compute_firmware(self) -> None:
        try:
            if not os.path.isdir(FIRMWARE_DIR):
                with self._firmware_lock:
                    self._firmware_cache = {"status": "absent", "reports": [],
                                            "timestamp": _now()}
                return
            results = firmware_inspector.inspect_directory(
                FIRMWARE_DIR, device_region=branding.TARGET_REGION,
                installed_build=branding.REPORTED_INSTALLED_BUILD)
            reports = [self._serialise_report(r) for r in results]
            with self._firmware_lock:
                self._firmware_cache = {"status": "ready", "reports": reports,
                                        "timestamp": _now()}
        except Exception as exc:  # never let the worker die silently
            with self._firmware_lock:
                self._firmware_cache = {"status": "error", "reports": [],
                                        "timestamp": _now(), "error": str(exc)}

    def _serialise_report(self, res) -> dict:
        if res.error:
            return {"filename": getattr(res.report, "filename", "?"),
                    "error": res.error}
        r = res.report
        return {
            "filename": r.filename,
            "size_bytes": r.hashes.size_bytes,
            "size_human": r.hashes.size_human,
            "sha256": r.hashes.sha256,
            "md5": r.hashes.md5,
            "format": r.detection.format_name,
            "format_id": r.detection.format_id,
            "confidence": r.detection.confidence,
            "supported": r.detection.is_supported,
            "header_hex": r.detection.header_hex,
            "kernel_version": r.kernel_version,
            "entropy_bits": r.entropy_bits,
            "entropy_label": r.entropy_label,
            "build": r.filename_meta.build,
            "versions": r.filename_meta.fw_version,
            "integrity_status": r.integrity_status,
            "integrity_detail": r.integrity_detail,
            "embedded": [dataclasses.asdict(h) for h in r.embedded],
            "warnings": r.warnings,
            "notes": r.detection.notes,
        }

    def firmware_state(self) -> dict:
        with self._firmware_lock:
            return dict(self._firmware_cache)

    # -- evidence ----------------------------------------------------------
    def evidence_rows(self) -> list:
        """Merge recorded diagnostic events with manual observations."""
        rows = evidence_log.EvidenceLog(EVIDENCE_PATH).rows()
        obs_log = connectivity_tests.ConnectivityLog(CONNECTIVITY_PATH)
        for o in obs_log.observations:
            placeholder = (o.approved_by == "example")
            rows.append({
                "timestamp": o.timestamp,
                "event_type": "observation",
                "target": o.interface,
                "test_name": o.test_name,
                "status": (evidence_log.STATUS_PLACEHOLDER if placeholder
                           else evidence_log.STATUS_REAL),
                "result": o.result,
                "source": "manual" if not placeholder else "sample",
                "detail": o.detail,
            })
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return rows

    def record_observation(self, test_name, result, interface="unspecified",
                           detail="", approved_by="operator") -> Tuple[bool, str]:
        valid = {"pass", "fail", "partial", "not-tested"}
        if result not in valid:
            return False, f"result must be one of {sorted(valid)}"
        if not test_name or not str(test_name).strip():
            return False, "test_name is required"
        log = connectivity_tests.ConnectivityLog(CONNECTIVITY_PATH)
        log.record(str(test_name).strip(), result, interface=interface,
                   detail=detail, approved_by=approved_by or "operator")
        log.save()
        return True, "recorded"

    def export_evidence(self, fmt: str) -> Tuple[str, str]:
        """Return (content, content_type) for 'csv' or 'json'."""
        log = evidence_log.EvidenceLog(EVIDENCE_PATH)
        # Fold in observations so the export matches what the UI shows.
        for row in self.evidence_rows():
            if row["event_type"] == "observation":
                try:
                    log.add(evidence_log.EvidenceEvent(
                        timestamp=row["timestamp"], event_type="observation",
                        target=row["target"], test_name=row["test_name"],
                        status=row["status"], result=row["result"],
                        source=row["source"], detail=row["detail"]))
                except ValueError:
                    continue
        if fmt == "csv":
            return log.to_csv(), "text/csv; charset=utf-8"
        return log.to_json(), "application/json; charset=utf-8"

    # -- session -----------------------------------------------------------
    def session(self) -> dict:
        fw = self.firmware_state()
        return {
            "product": branding.PRODUCT_NAME,
            "subtitle": branding.PRODUCT_SUBTITLE,
            "developer": branding.DEVELOPER,
            "version": branding.VERSION,
            "device": branding.TARGET_DEVICE,
            "region": branding.TARGET_REGION,
            "hw": branding.TARGET_HW,
            "reported_build": branding.REPORTED_INSTALLED_BUILD,
            "safety": branding.SAFETY_BANNER,
            "session_started": self.session_started,
            "settings": self.settings,
            "gateway_detection": self.gateway_detection,
            "last_diagnostics": self.last_diagnostics,
            "firmware_status": fw["status"],
            "firmware_timestamp": fw["timestamp"],
            "evidence_count": len(self.evidence_rows()),
        }


class _Handler(BaseHTTPRequestHandler):
    server_version = "FildzaWorkstation/2.0"

    # Silence the default noisy logging; keep a compact one line form.
    def log_message(self, fmt, *args):
        pass

    @property
    def app(self) -> WorkstationApp:
        return self.server.app  # type: ignore[attr-defined]

    def _send(self, code, body: bytes, content_type: str,
              extra_headers: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routing -----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/"):
                return self._handle_api_get(path, parse_qs(parsed.query))
            return self._serve_static(path)
        except Exception as exc:  # pragma: no cover - defensive
            self._json({"ok": False, "error": f"server error: {exc}"}, 500)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        try:
            parsed = urlparse(self.path)
            return self._handle_api_post(parsed.path, self._read_json_body())
        except Exception as exc:  # pragma: no cover - defensive
            self._json({"ok": False, "error": f"server error: {exc}"}, 500)

    def _handle_api_get(self, path, query):
        if path == "/api/session":
            return self._json(self.app.session())
        if path == "/api/gateway":
            return self._json(self.app.detect_gateway())
        if path == "/api/firmware":
            self.app.start_firmware_analysis()
            return self._json(self.app.firmware_state())
        if path == "/api/evidence":
            return self._json({"rows": self.app.evidence_rows()})
        if path == "/api/export":
            fmt = (query.get("format", ["json"])[0]).lower()
            if fmt not in ("csv", "json"):
                return self._json({"ok": False,
                                   "error": "format must be csv or json"}, 400)
            content, ctype = self.app.export_evidence(fmt)
            fname = f"fildza_evidence.{fmt}"
            return self._send(200, content.encode("utf-8"), ctype,
                              {"Content-Disposition": f'attachment; filename="{fname}"'})
        return self._json({"ok": False, "error": "unknown endpoint"}, 404)

    def _handle_api_post(self, path, body):
        if path == "/api/diagnostics":
            result = self.app.run_diagnostics(
                router=body.get("router"), port=body.get("port"),
                scheme=body.get("scheme"))
            return self._json(result, 200 if result.get("ok") else 400)
        if path == "/api/settings":
            ok, errors = self.app.update_settings(
                body.get("router"), body.get("port", 80),
                body.get("scheme", "http"))
            return self._json({"ok": ok, "errors": errors,
                               "settings": self.app.settings},
                              200 if ok else 400)
        if path == "/api/observation":
            ok, msg = self.app.record_observation(
                body.get("test_name", ""), body.get("result", ""),
                interface=body.get("interface", "unspecified"),
                detail=body.get("detail", ""),
                approved_by=body.get("approved_by", "operator"))
            return self._json({"ok": ok, "message": msg},
                              200 if ok else 400)
        return self._json({"ok": False, "error": "unknown endpoint"}, 404)

    # -- static files ------------------------------------------------------
    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        # Prevent path traversal: resolve and confirm it stays under WEBUI_DIR.
        full = os.path.normpath(os.path.join(WEBUI_DIR, rel))
        if not full.startswith(WEBUI_DIR) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        self._send(200, body, _CONTENT_TYPES.get(ext, "application/octet-stream"))


def make_server(host: str, port: int, app: WorkstationApp) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.app = app  # type: ignore[attr-defined]
    return server
