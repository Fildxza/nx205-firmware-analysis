"""
Tests for src/workstation_server.py.

Covers input validation, the engine-backed app methods (with a fake snapshot so
no real network is needed), evidence export, and a live end-to-end server test
over an ephemeral port. Real-data files are redirected to a temp directory so
the suite never touches the project's actual logs.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import network_diagnostics as nd
from src import workstation_server as ws


def make_fake_snapshot():
    """Build a DiagnosticsSnapshot with no network calls."""
    return nd.DiagnosticsSnapshot(
        router_ping=nd.PingResult("192.168.1.1", "ok", sent=4, received=4,
                                  loss_percent=0.0, rtt_avg_ms=3.0),
        internet_ping=nd.PingResult("8.8.8.8", "ok", sent=4, received=4,
                                    loss_percent=0.0, rtt_avg_ms=25.0),
        dns=nd.DnsResult("www.tp-link.com", "ok", addresses=["1.2.3.4"]),
        router_http=nd.HttpResult(url="http://192.168.1.1:80/", status="ok",
                                  http_code=200, responded=True),
        router_tcp=nd.TcpResult("192.168.1.1", 80, "ok", connect_ms=2.0),
        router_ip="192.168.1.1", http_port=80,
    )


class _Paths:
    """Redirect the server's data-file globals to a temp dir for isolation."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="fildza_test_")
        self._saved = {}

    def __enter__(self):
        for name in ("EVIDENCE_PATH", "CONNECTIVITY_PATH", "SETTINGS_PATH"):
            self._saved[name] = getattr(ws, name)
            setattr(ws, name, os.path.join(self.dir, name.lower() + ".json"))
        self._saved["FIRMWARE_DIR"] = ws.FIRMWARE_DIR
        ws.FIRMWARE_DIR = os.path.join(self.dir, "no_firmware_here")
        return self

    def __exit__(self, *exc):
        for name, val in self._saved.items():
            setattr(ws, name, val)


class TestValidation(unittest.TestCase):
    def test_valid_ipv4(self):
        ok, errs = ws.validate_target("192.168.1.1", 80, "http")
        self.assertTrue(ok, errs)

    def test_bad_octet(self):
        ok, errs = ws.validate_target("192.168.1.999", 80, "http")
        self.assertFalse(ok)

    def test_bad_port(self):
        self.assertFalse(ws.validate_target("192.168.1.1", 70000, "http")[0])
        self.assertFalse(ws.validate_target("192.168.1.1", "abc", "http")[0])

    def test_bad_scheme(self):
        self.assertFalse(ws.validate_target("192.168.1.1", 80, "ftp")[0])

    def test_hostname_ok(self):
        self.assertTrue(ws.validate_target("tplinkmodem.net", 443, "https")[0])

    def test_empty_router(self):
        self.assertFalse(ws.validate_target("", 80, "http")[0])


class TestApp(unittest.TestCase):
    def test_run_diagnostics_invalid_target(self):
        with _Paths():
            app = ws.WorkstationApp(router="999.999.999.999")
            result = app.run_diagnostics()
            self.assertFalse(result["ok"])
            self.assertTrue(result["errors"])

    def test_run_diagnostics_records_evidence(self):
        with _Paths():
            app = ws.WorkstationApp(router="192.168.1.1")
            original = nd.run_snapshot
            nd.run_snapshot = lambda **kw: make_fake_snapshot()
            try:
                result = app.run_diagnostics()
            finally:
                nd.run_snapshot = original
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["snapshot"]["checks"]), 5)
            self.assertIsNotNone(app.last_diagnostics)
            # Five evidence rows should have been recorded (one per check).
            rows = app.evidence_rows()
            diag = [r for r in rows if r["event_type"] == "diagnostics"]
            self.assertEqual(len(diag), 5)
            self.assertTrue(all(r["status"] == "REAL" for r in diag))

    def test_update_settings_validation(self):
        with _Paths():
            app = ws.WorkstationApp(router=None)
            ok, errs = app.update_settings("10.0.0.1", 443, "https")
            self.assertTrue(ok)
            self.assertEqual(app.settings["router"], "10.0.0.1")
            ok2, errs2 = app.update_settings("bad host!!", 80, "http")
            self.assertFalse(ok2)

    def test_record_observation(self):
        with _Paths():
            app = ws.WorkstationApp(router=None)
            ok, _ = app.record_observation("LAN check", "pass",
                                           interface="LAN", detail="loaded")
            self.assertTrue(ok)
            bad, _ = app.record_observation("x", "banana")
            self.assertFalse(bad)
            rows = app.evidence_rows()
            self.assertTrue(any(r["test_name"] == "LAN check" for r in rows))

    def test_export_csv_and_json(self):
        with _Paths():
            app = ws.WorkstationApp(router="192.168.1.1")
            nd_orig = nd.run_snapshot
            nd.run_snapshot = lambda **kw: make_fake_snapshot()
            try:
                app.run_diagnostics()
            finally:
                nd.run_snapshot = nd_orig
            csv_text, ctype = app.export_evidence("csv")
            self.assertIn("timestamp", csv_text.splitlines()[0])
            self.assertIn("csv", ctype)
            json_text, jtype = app.export_evidence("json")
            parsed = json.loads(json_text)
            self.assertTrue(isinstance(parsed, list) and len(parsed) >= 5)

    def test_firmware_absent_state(self):
        with _Paths():
            app = ws.WorkstationApp(router=None)
            app._compute_firmware()  # synchronous, dir does not exist
            self.assertEqual(app.firmware_state()["status"], "absent")


class TestServer(unittest.TestCase):
    def setUp(self):
        self.paths = _Paths().__enter__()
        self.app = ws.WorkstationApp(router="192.168.1.1")
        self.server = ws.make_server("127.0.0.1", 0, self.app)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.paths.__exit__()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8"), r.headers

    def test_session_endpoint(self):
        code, body, _ = self._get("/api/session")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["product"], "FILDZA MOD ROUTER")
        self.assertIn("safety", data)

    def test_static_index_served(self):
        code, body, _ = self._get("/")
        self.assertEqual(code, 200)
        # Stable markers in the redesigned shell (brand wordmark + app bundle).
        self.assertIn("FILDZA", body)
        self.assertIn("app.js", body)

    def test_evidence_endpoint(self):
        code, body, _ = self._get("/api/evidence")
        self.assertEqual(code, 200)
        self.assertIn("rows", json.loads(body))

    def test_export_csv_endpoint(self):
        code, body, headers = self._get("/api/export?format=csv")
        self.assertEqual(code, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))

    def test_unknown_api_404(self):
        with self.assertRaises(HTTPError) as ctx:
            self._get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_path_traversal_blocked(self):
        with self.assertRaises(HTTPError) as ctx:
            self._get("/../src/workstation_server.py")
        self.assertIn(ctx.exception.code, (403, 404))


class TestPortSelection(unittest.TestCase):
    def test_port_is_free_detects_listener(self):
        import socket
        import workstation as wk

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        busy_port = listener.getsockname()[1]
        try:
            # A single probe to a live listener must report it as in use.
            self.assertFalse(wk.port_is_free("127.0.0.1", busy_port))
        finally:
            listener.close()

    def test_choose_port_skips_busy(self):
        import workstation as wk

        # Deterministic: pretend 5000 is busy and everything else is free.
        original = wk.port_is_free
        wk.port_is_free = lambda host, port, timeout=0.3: port != 5000
        try:
            self.assertEqual(wk.choose_port("127.0.0.1", 5000), 5001)
            self.assertEqual(wk.choose_port("127.0.0.1", 5001), 5001)
        finally:
            wk.port_is_free = original

    def test_choose_port_none_when_all_busy(self):
        import workstation as wk

        original = wk.port_is_free
        wk.port_is_free = lambda host, port, timeout=0.3: False  # all busy
        try:
            self.assertIsNone(wk.choose_port("127.0.0.1", 6000, attempts=5))
        finally:
            wk.port_is_free = original


if __name__ == "__main__":
    unittest.main()
