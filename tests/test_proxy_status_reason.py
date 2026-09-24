#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_status_reason.py
# Description: The :8177 proxy's error replies always reach the browser
#              (review 24-09-2026 [32]). BaseHTTPRequestHandler writes the
#              reason as strict latin-1, so the em dash in the /bootstrap
#              refusal raised mid-response: the browser saw a dropped
#              connection instead of a 403, and a traceback went to stderr.
#              Exception text on a status line could also carry a newline.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import http.client
import http.server
import threading

from conftest import load_plugin_module

load_plugin_module()
import cameras_mixin  # noqa: E402


def _serve(reason):
    class H(cameras_mixin.SafeErrorMixin, http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def log_error(self, *a):
            pass

        def do_GET(self):
            self.send_error(403, reason)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    return srv


def _get(srv):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    c.request("GET", "/bootstrap")
    r = c.getresponse()
    return r.status, r.reason, r.read().decode("utf-8")


def test_a_non_latin1_reason_still_sends_the_403():
    srv = _serve("key auto-seed disabled — use a setup link")
    try:
        status, reason, body = _get(srv)
    finally:
        srv.server_close()
    assert status == 403
    assert reason.isascii()
    assert "—" in body                     # the full text survives in the body


def test_exception_text_cannot_split_the_status_line():
    srv = _serve("IWS fetch failed: line one\r\nX-Evil: 1\n" + "x" * 500)
    try:
        status, reason, _ = _get(srv)
    finally:
        srv.server_close()
    assert status == 403
    assert "\n" not in reason and "\r" not in reason and len(reason) <= 100


def test_status_reason_is_ascii_single_line_and_bounded():
    assert cameras_mixin.status_reason("a—b\nc") == "a?b c"
    assert cameras_mixin.status_reason(None) is None
    assert len(cameras_mixin.status_reason("y" * 300)) == 100


def test_the_proxy_handler_uses_the_safe_send_error():
    import ast
    tree = ast.parse(open(cameras_mixin.__file__, encoding="utf-8").read())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "_Handler"]
    assert handlers, "the proxy's _Handler class moved"
    for h in handlers:
        assert h.bases and isinstance(h.bases[0], ast.Name) and h.bases[0].id == "SafeErrorMixin"
