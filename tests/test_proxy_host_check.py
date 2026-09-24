#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_proxy_host_check.py
# Description: The :8177 server hands out the API key (/bootstrap) and the
#              guest token, guarded only by "is the source private" and "does
#              the Origin's host match the Host header". DNS rebinding passes
#              both: the attacker's own name is re-pointed at this Mac, so Host
#              and Origin agree. It cannot choose the Host header, only the
#              name, so every request whose Host is not one of this machine's
#              names is now refused before any route is looked at.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import ast
import inspect
import textwrap

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import cameras_mixin  # noqa: E402


@pytest.fixture
def p(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "Indigo-Mac-mini.local")
    pl = bare_plugin()
    pl.api_url = "http://indigo.example.lan:8176"
    return pl


ALLOWED = [
    "192.168.1.10",
    "192.168.1.10:8177",
    "127.0.0.1:8177",
    "100.101.102.103:8177",            # a Tailscale address
    "[::1]:8177",
    "[fe80::1]",
    "::1",
    "localhost",
    "localhost:8177",
    "LOCALHOST:8177",
    "indigo-mac-mini.local:8177",       # gethostname() as given
    "Indigo-Mac-mini.local",           # case-insensitive
    "indigo-mac-mini:8177",            # the short name
    "indigo-mac-mini.lan:8177",        # a home router's DNS name for it
    "indigo-mac-mini.home.arpa",
    "indigo-mac-mini.local.:8177",     # trailing dot
    "indigo.tail-example.ts.net:8177",
    "indigo.example.lan:8177",         # the configured Indigo URL's host
]

REFUSED = [
    "",
    "attacker.example",
    "attacker.example:8177",
    "indigo-mac-mini.attacker.example",
    "ts.net.attacker.example",
    "localhost.attacker.example",
    "192.168.1.10.nip.io:8177",
    "indigo-mac-mini.xyz",             # a public suffix anyone could register
    "someone-else.lan",                # another machine's private name
    "[::1",                            # unterminated literal
    "[::1]x",
    "192.168.1.10:port",
    ":8177",
]


@pytest.mark.parametrize("host", ALLOWED)
def test_this_machines_names_are_allowed(p, host):
    assert p._proxy_host_allowed(host) is True, host


@pytest.mark.parametrize("host", REFUSED)
def test_other_names_are_refused(p, host):
    assert p._proxy_host_allowed(host) is False, host


def test_a_blank_api_url_does_not_open_anything(p):
    p.api_url = ""
    assert p._proxy_host_allowed("attacker.example") is False
    assert p._proxy_host_allowed("192.168.1.10:8177") is True


def _handler_methods():
    src = textwrap.dedent(inspect.getsource(cameras_mixin.CamerasMixin._start_proxy))
    tree = ast.parse(src)
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("method", ["do_GET", "do_POST", "do_OPTIONS"])
def test_every_verb_checks_the_host_first(method):
    """Before ANY route — /healthz included — so no path is reached by a
    rebinding page, however it is added later."""
    fn = _handler_methods()[method]
    first = fn.body[0]
    assert isinstance(first, ast.If), ast.unparse(first)
    assert ast.unparse(first.test) == "self._host_refused()", ast.unparse(first.test)
    assert isinstance(first.body[0], ast.Return)


def test_the_refusal_sends_a_status_and_nothing_else():
    fn = _handler_methods()["_host_refused"]
    body = ast.unparse(fn)
    assert "_proxy_host_allowed" in body
    assert "send_error(421" in body
    assert "api_key" not in body and "guest_token" not in body
