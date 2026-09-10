#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_verify_pin.py
# Description: handleVerifyPin — the control-PIN speed bump. Had no tests at
#              all until 2.95.1, and hmac.compare_digest on two str objects
#              raises TypeError the moment either holds a non-ASCII character,
#              so a stray "é" in the PIN box 500'd the endpoint instead of
#              answering "no". Compared as bytes now; these lock it.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import json
from types import SimpleNamespace
from conftest import bare_plugin, load_plugin_module


def _call(p, body):
    action = SimpleNamespace(props={"request_body": json.dumps(body)})
    reply = p.handleVerifyPin(action)
    # _evo_reply wraps a dict; accept either the dict or the wrapped shape.
    if isinstance(reply, dict) and "valid" in reply:
        return reply
    for k in ("content", "body"):
        v = reply.get(k) if isinstance(reply, dict) else None
        if isinstance(v, (str, bytes)):
            return json.loads(v)
    return reply


def _plugin(pin):
    plugin = load_plugin_module()
    p = bare_plugin()
    p.control_pin = pin
    p._pin_locked_until = 0
    return plugin, p


def test_no_pin_configured_is_always_valid():
    _, p = _plugin("")
    assert _call(p, {"pin": "anything"})["valid"] is True


def test_correct_pin_is_valid():
    _, p = _plugin("2468")
    assert _call(p, {"pin": "2468"})["valid"] is True


def test_wrong_pin_is_refused_and_locks_briefly(monkeypatch):
    plugin, p = _plugin("2468")
    monkeypatch.setattr(plugin.time, "time", lambda: 5000.0)
    r = _call(p, {"pin": "0000"})
    assert r["valid"] is False
    assert p._pin_locked_until > 5000.0
    # Inside the lockout even the right PIN is deferred, not accepted.
    assert _call(p, {"pin": "2468"})["valid"] is False


def test_non_ascii_pin_is_refused_not_a_traceback():
    _, p = _plugin("2468")
    r = _call(p, {"pin": "é468"})
    assert r["valid"] is False


def test_non_ascii_configured_pin_still_compares():
    _, p = _plugin("pässword")
    assert _call(p, {"pin": "pässword"})["valid"] is True
    assert _call(p, {"pin": "password"})["valid"] is False
