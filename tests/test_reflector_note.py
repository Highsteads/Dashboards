#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_reflector_note.py
# Description: Contract test for Plugin._note_reflector_use (v2.96.1) — a
#              /message request that arrived through the Indigo reflector is
#              recognised from its headers, warned about ONCE an hour per
#              device with the LAN address in the line, and changedSince
#              tells the page so with via:"reflector". A LAN request is not.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0
import time
from conftest import load_plugin_module


class _Log:
    def __init__(self):
        self.warnings = []
        self.debugs = []
    def warning(self, m): self.warnings.append(m)
    def debug(self, m): self.debugs.append(m)
    def info(self, m): pass
    def error(self, m): pass


class _Action:
    def __init__(self, headers):
        self.props = {"headers": headers, "request_body": '{"since": 0}'}


def _plugin(refl="https://myhouse.indigodomo.net"):
    mod = load_plugin_module()
    p = mod.Plugin.__new__(mod.Plugin)
    p.logger = _Log()
    p.lan_ip = "192.168.1.10"
    p._reflector_host = refl.split("//", 1)[-1]
    return mod, p


def test_reflector_request_is_named_once_an_hour():
    mod, p = _plugin()
    hdrs = {"Host": "myhouse.indigodomo.net", "X-Forwarded-For": "51.0.0.1",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)"}
    assert p._note_reflector_use(_Action(hdrs)) is True
    assert len(p.logger.warnings) == 1
    line = p.logger.warnings[0]
    assert "51.0.0.1" in line and "iPhone" in line
    assert "http://192.168.1.10:8176" in line          # the way home is in the line
    # Same device again inside the hour: recognised, not repeated.
    assert p._note_reflector_use(_Action(hdrs)) is True
    assert len(p.logger.warnings) == 1
    # A different device is its own line.
    hdrs2 = dict(hdrs, **{"User-Agent": "Mozilla/5.0 (iPad; CPU OS 26_0 like Mac OS X)"})
    assert p._note_reflector_use(_Action(hdrs2)) is True
    assert len(p.logger.warnings) == 2
    # And the first one again after the hour has passed.
    p._reflector_seen[("51.0.0.1", hdrs["User-Agent"][:120])] = time.time() - p.REFLECTOR_WARN_S - 1
    assert p._note_reflector_use(_Action(hdrs)) is True
    assert len(p.logger.warnings) == 3


def test_host_alone_identifies_the_reflector():
    # No forwarded-for header, but the browser addressed the reflector name.
    mod, p = _plugin()
    assert p._note_reflector_use(_Action({"host": "myhouse.indigodomo.net", "user-agent": "x"})) is True
    assert len(p.logger.warnings) == 1
    assert "myhouse.indigodomo.net" in p.logger.warnings[0]


def test_lan_request_is_not_the_reflector():
    mod, p = _plugin()
    assert p._note_reflector_use(_Action({"Host": "192.168.1.10:8176", "User-Agent": "Safari"})) is False
    assert p.logger.warnings == []
    # No headers at all (a unit test's bare action) is not a crash either.
    class _Bare: props = {}
    assert p._note_reflector_use(_Bare()) is False
    assert p._note_reflector_use(object()) is False


def test_changed_since_reply_carries_via_reflector():
    mod, p = _plugin()
    p.CHANGED_SINCE_STALE_S = mod.Plugin.CHANGED_SINCE_STALE_S
    p._changed_since_payload = lambda since, now=None: {"ok": True, "now": 1.0, "full": True}
    captured = {}
    p._evo_reply = staticmethod(lambda obj, status=200: captured.update(obj) or obj)
    p.handleChangedSince(_Action({"X-Forwarded-For": "51.0.0.1", "User-Agent": "ua"}))
    assert captured.get("via") == "reflector"
    captured.clear()
    p.handleChangedSince(_Action({"Host": "192.168.1.10:8176"}))
    assert "via" not in captured


def test_refuse_reflector_is_off_by_default_and_403s_when_on():
    """v3.1.0 — refusing the reflector must be opt-in, and when it is on no
    dashboard data crosses it at all."""
    mod, p = _plugin()
    p.INDEX_PATH = "/public/dashboards/index.html"
    hdrs = {"X-Forwarded-For": "51.0.0.1", "User-Agent": "ua"}
    seen = {}
    p._evo_reply = staticmethod(lambda obj, status=200: seen.update(obj, status=status) or obj)

    # Off by default: an install with no other way in is not broken silently.
    p.pluginPrefs = {}
    assert p._reflector_blocked() is False
    assert p._refuse_reflector(_Action(hdrs)) is None

    # On: a reflector request is refused, and the reply names the way in.
    p.pluginPrefs = {"reflectorBlock": True}
    assert p._reflector_blocked() is True
    out = p._refuse_reflector(_Action(hdrs))
    assert out is not None
    assert seen["status"] == 403
    assert seen["reason"] == "reflector_blocked"
    assert "192.168.1.10" in seen["lanURL"]

    # On, but a LAN request: untouched.
    seen.clear()
    assert p._refuse_reflector(_Action({"Host": "192.168.1.10:8176"})) is None

    # The checkbox arrives from a saved dialog as the STRING "true".
    p.pluginPrefs = {"reflectorBlock": "true"}
    assert p._reflector_blocked() is True
    p.pluginPrefs = {"reflectorBlock": "false"}
    assert p._reflector_blocked() is False
