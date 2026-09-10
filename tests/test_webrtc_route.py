#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_webrtc_route.py
# Description: Contract tests for the WHEP signalling forward (v2.68.0) —
#              _forward_whep against a stub loopback "go2rtc", plus source
#              asserts on the /webrtc/<host> handler's gate ordering.
#              The upstream contract these pin was verified LIVE against
#              go2rtc 1.9.14 on 30-Jul-2026: POST /api/webrtc?src=<slug>
#              with application/sdp answers 201 + application/sdp.
# Author:      CliveS & Claude Fable 5
# Date:        30-07-2026
# Version:     1.0

import http.server
import re
import threading

from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()


# ── Stub go2rtc ────────────────────────────────────────────────
class _StubGo2rtc(http.server.BaseHTTPRequestHandler):
    """Answers like the real thing (201 + application/sdp) and records what
    it was asked, so the tests can assert the forwarded request's shape."""
    seen = []
    behaviour = {"status": 201, "body": b"v=0\r\nanswer", "ctype": "application/sdp"}

    def log_message(self, *_a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        _StubGo2rtc.seen.append({
            "path": self.path,
            "ctype": self.headers.get("Content-Type"),
            "body": body,
        })
        b = _StubGo2rtc.behaviour
        self.send_response(b["status"])
        self.send_header("Content-Type", b["ctype"])
        self.send_header("Content-Length", str(len(b["body"])))
        self.end_headers()
        self.wfile.write(b["body"])


def _with_stub(behaviour, fn):
    """Run fn(port) against a stub go2rtc configured with `behaviour`."""
    _StubGo2rtc.seen = []
    _StubGo2rtc.behaviour = behaviour
    srv = http.server.HTTPServer(("127.0.0.1", 0), _StubGo2rtc)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    old = plugin.GO2RTC_API_PORT
    plugin.GO2RTC_API_PORT = port
    try:
        return fn(port)
    finally:
        plugin.GO2RTC_API_PORT = old
        srv.shutdown()
        srv.server_close()


def test_answer_passthrough_uses_raw_slug():
    p = bare_plugin()
    status, ctype, payload = _with_stub(
        {"status": 201, "body": b"v=0\r\nanswer-sdp", "ctype": "application/sdp"},
        lambda _port: p._forward_whep("garage", b"v=0\r\noffer-sdp"))
    assert status == 200
    assert ctype == "application/sdp"
    assert payload == b"v=0\r\nanswer-sdp"
    seen = _StubGo2rtc.seen[0]
    # The RAW H.264 slug, NOT the ffmpeg MJPEG leg — the _mjpeg suffix lives
    # three lines from this code in the MJPEG route, and forwarding to it
    # would silently negotiate a transcode that cannot even carry H264.
    assert seen["path"] == "/api/webrtc?src=garage"
    assert "_mjpeg" not in seen["path"]
    assert seen["ctype"] == "application/sdp"
    assert seen["body"] == b"v=0\r\noffer-sdp"


def test_slug_is_url_quoted():
    p = bare_plugin()
    _with_stub(
        {"status": 201, "body": b"v=0", "ctype": "application/sdp"},
        lambda _port: p._forward_whep("odd slug/name", b"v=0"))
    assert _StubGo2rtc.seen[0]["path"] == "/api/webrtc?src=odd%20slug%2Fname"


def test_upstream_error_maps_to_502_with_upstream_code():
    p = bare_plugin()
    status, ctype, payload = _with_stub(
        {"status": 500, "body": b"payload type not found", "ctype": "text/plain"},
        lambda _port: p._forward_whep("garage", b"v=0"))
    assert status == 502
    assert b"500" in payload
    assert b"payload type not found" in payload


def test_empty_answer_is_an_error_not_a_success():
    p = bare_plugin()
    status, _ctype, payload = _with_stub(
        {"status": 201, "body": b"", "ctype": "application/sdp"},
        lambda _port: p._forward_whep("garage", b"v=0"))
    assert status == 502
    assert b"no SDP" in payload


def test_unreachable_go2rtc_maps_to_502():
    p = bare_plugin()
    old = plugin.GO2RTC_API_PORT
    plugin.GO2RTC_API_PORT = 1  # nothing listens on port 1
    try:
        status, _ctype, payload = p._forward_whep("garage", b"v=0")
    finally:
        plugin.GO2RTC_API_PORT = old
    assert status == 502
    assert b"unreachable" in payload


# ── Handler gate ordering (source asserts) ─────────────────────
# The /webrtc/<host> handler is a nested class inside _start_mjpeg_proxy, so
# it cannot be instantiated without the full plugin; pin its gate ORDER from
# the source instead, the way the .mjs suites pin page behaviour.
def _do_post_source():
    import inspect
    src = inspect.getsource(plugin)
    m = re.search(r"def do_POST\(self\):(.*?)def do_GET\(self\):", src, re.S)
    assert m, "do_POST not found ahead of do_GET"
    return m.group(1)


def test_handler_gates_before_reading_body():
    body = _do_post_source()
    private = body.index("_client_is_private")
    allow   = body.index("allowed_hosts")
    size    = body.index("body size out of range")
    read    = body.index("self.rfile.read(length)")
    assert private < allow < size < read, (
        "gate order must be: private source, allowlist, size cap, THEN read")


def test_handler_forwards_via_slug_map():
    body = _do_post_source()
    assert "_forward_whep(" in body
    assert "host_to_slug[host]" in body


def test_handler_answer_is_cors_readable():
    # The page origin is :8176 and the proxy :8177 — without ACAO on the
    # POST response itself the browser fetches the answer and then refuses
    # to let the page READ it, which presents as a silent signalling failure.
    body = _do_post_source()
    # Same-host echo since v2.95.1, not a wildcard: _echo_same_host_origin
    # sends Access-Control-Allow-Origin when the caller's Origin hostname
    # matches the request Host — which the :8176 page always does — and
    # nothing at all to a drive-by page from elsewhere.
    assert "Access-Control-Allow-Origin: *" not in body
    assert '"Access-Control-Allow-Origin", "*"' not in body
    assert body.index("_echo_same_host_origin()") < body.index("self.wfile.write(payload)")


def test_options_preflight_scoped_to_webrtc():
    import inspect
    src = inspect.getsource(plugin)
    m = re.search(r"def do_OPTIONS\(self\):(.*?)def do_POST\(self\):", src, re.S)
    assert m, "do_OPTIONS not found ahead of do_POST"
    body = m.group(1)
    assert '"/webrtc/"' in body
    assert "Access-Control-Allow-Methods" in body
    assert "Access-Control-Allow-Headers" in body
