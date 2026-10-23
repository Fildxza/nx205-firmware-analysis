"""
Unit tests for src/network_diagnostics.py.

The ping-output parser is tested offline against captured real output (Windows
and Unix wording) so the tests do not depend on the network. DNS/TCP are tested
against safe, well-defined local conditions only.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import network_diagnostics as nd

# Real Windows output captured during development (router unreachable).
_WIN_LOSS = """
Pinging 192.168.1.1 with 32 bytes of data:
Request timed out.
Request timed out.

Ping statistics for 192.168.1.1:
    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),
"""

# Real Windows output captured during development (internet reachable).
_WIN_OK = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=54ms TTL=116
Reply from 8.8.8.8: bytes=32 time=21ms TTL=116

Ping statistics for 8.8.8.8:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 21ms, Maximum = 54ms, Average = 31ms
"""

_UNIX_OK = """
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=116 time=22.1 ms

--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3004ms
rtt min/avg/max/mdev = 21.0/31.0/54.0/1.0 ms
"""


class TestPingParser(unittest.TestCase):
    def test_windows_loss(self):
        r = nd._parse_ping_output("192.168.1.1", _WIN_LOSS, 4)
        self.assertEqual(r.status, "unreachable")
        self.assertEqual(r.sent, 4)
        self.assertEqual(r.received, 0)
        self.assertEqual(r.loss_percent, 100.0)
        self.assertIsNone(r.rtt_avg_ms)

    def test_windows_ok(self):
        r = nd._parse_ping_output("8.8.8.8", _WIN_OK, 4)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.received, 4)
        self.assertEqual(r.loss_percent, 0.0)
        self.assertEqual(r.rtt_min_ms, 21.0)
        self.assertEqual(r.rtt_avg_ms, 31.0)
        self.assertEqual(r.rtt_max_ms, 54.0)

    def test_unix_ok(self):
        r = nd._parse_ping_output("8.8.8.8", _UNIX_OK, 4)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.received, 4)
        self.assertEqual(r.rtt_avg_ms, 31.0)

    def test_unparseable(self):
        r = nd._parse_ping_output("x", "garbage with no numbers", 4)
        self.assertEqual(r.status, "error")


class TestDnsAndTcp(unittest.TestCase):
    def test_dns_localhost(self):
        r = nd.resolve_dns("localhost")
        self.assertEqual(r.status, "ok")
        self.assertTrue(any(a.startswith("127.") or a == "::1" for a in r.addresses))

    def test_dns_invalid(self):
        r = nd.resolve_dns("no-such-host.invalid")
        self.assertIn(r.status, {"unreachable", "error"})

    def test_tcp_unreachable_port(self):
        # Port 1 on localhost is almost never open -> fast, deterministic fail.
        r = nd.tcp_connect("127.0.0.1", 1, timeout=1.0)
        self.assertEqual(r.status, "unreachable")


class TestHttpProbe(unittest.TestCase):
    def test_http_unreachable(self):
        # Nothing listens on 127.0.0.1:1 -> unreachable, no credentials involved.
        r = nd.http_probe("127.0.0.1", 1, timeout=1.0)
        self.assertEqual(r.status, "unreachable")
        self.assertFalse(r.responded)
        self.assertIsNone(r.http_code)

    def test_http_probe_against_local_server(self):
        # Spin up a throwaway HTTP server that returns 401, to prove that an
        # error status is still correctly reported as a responding admin page
        # (auth required) rather than "unreachable". No credentials are sent.
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            # send_response() auto-emits a Server header from these attrs, so
            # set them here rather than calling send_header("Server", ...),
            # which would be overridden.
            server_version = "TestServer/1.0"
            sys_version = ""

            def do_GET(self):  # noqa: N802
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="x"')
                self.end_headers()

            def log_message(self, *args):  # silence test output
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            r = nd.http_probe("127.0.0.1", port, timeout=3.0)
            self.assertEqual(r.status, "ok")
            self.assertTrue(r.responded)
            self.assertEqual(r.http_code, 401)
            self.assertTrue(r.auth_required)
            self.assertEqual(r.server.strip(), "TestServer/1.0")
        finally:
            srv.server_close()

    def test_snapshot_shape(self):
        # A snapshot must expose all five dimensions separately.
        snap = nd.run_snapshot(router_ip="127.0.0.1", internet_host="127.0.0.1",
                               dns_host="localhost", http_port=1, count=1)
        self.assertTrue(hasattr(snap, "router_ping"))
        self.assertTrue(hasattr(snap, "internet_ping"))
        self.assertTrue(hasattr(snap, "dns"))
        self.assertTrue(hasattr(snap, "router_http"))
        self.assertTrue(hasattr(snap, "router_tcp"))


# Captured real `ipconfig` output (trimmed), used to test the parser offline.
_IPCONFIG_OK = r"""
Windows IP Configuration

Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . :
   Link-local IPv6 Address . . . . . : fe80::1234:5678:9abc:def0%12
   IPv4 Address. . . . . . . . . . . : 192.168.1.23
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%12
                                       192.168.1.1
"""

# An adapter with no gateway (blank) followed by the real one further down.
_IPCONFIG_MULTI = r"""
Ethernet adapter Ethernet:

   Media State . . . . . . . . . . . : Media disconnected
   Default Gateway . . . . . . . . . :

Wireless LAN adapter Wi-Fi:

   IPv4 Address. . . . . . . . . . . : 10.0.0.42
   Default Gateway . . . . . . . . . : 10.0.0.1
"""

_IPCONFIG_NONE = r"""
Ethernet adapter Ethernet:

   Media State . . . . . . . . . . . : Media disconnected
   Default Gateway . . . . . . . . . :
"""


class TestGatewayDetection(unittest.TestCase):
    def test_parse_simple(self):
        self.assertEqual(nd._parse_gateway_from_ipconfig(_IPCONFIG_OK),
                         "192.168.1.1")

    def test_parse_skips_blank_adapter(self):
        # Must skip the disconnected adapter's empty gateway and find 10.0.0.1.
        self.assertEqual(nd._parse_gateway_from_ipconfig(_IPCONFIG_MULTI),
                         "10.0.0.1")

    def test_parse_none_when_no_gateway(self):
        self.assertIsNone(nd._parse_gateway_from_ipconfig(_IPCONFIG_NONE))

    def test_parse_ignores_zero_gateway(self):
        self.assertIsNone(nd._parse_gateway_from_ipconfig(
            "   Default Gateway . . . . . . . . . : 0.0.0.0"))

    def test_detect_returns_result_with_status(self):
        # Runs the real detector on this machine; we only assert it returns a
        # well-formed result (ok with an IP, or error with a manual hint) and
        # never a guessed address.
        r = nd.detect_default_gateway()
        self.assertIn(r.status, {"ok", "error"})
        if r.status == "ok":
            self.assertRegex(r.gateway, r"^\d{1,3}(\.\d{1,3}){3}$")
        else:
            self.assertTrue(r.manual_hint)
            self.assertIsNone(r.gateway)

    def test_snapshot_with_no_target_is_error_not_invented(self):
        # router_ip=None must produce ERROR router rows, not probe a made-up IP.
        snap = nd.run_snapshot(router_ip=None, internet_host="127.0.0.1",
                               dns_host="localhost", count=1)
        self.assertEqual(snap.router_ping.status, "error")
        self.assertEqual(snap.router_http.status, "error")
        self.assertEqual(snap.router_tcp.status, "error")
        self.assertEqual(snap.router_ip, "(undetermined)")


if __name__ == "__main__":
    unittest.main()
