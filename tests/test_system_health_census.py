#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_system_health_census.py
# Description: System Health (review 24-09-2026):
#              [49] a DISABLED device is left out of the in-error and
#              low-battery lists, as it always was from the quiet list — it is
#              off on purpose and its states are frozen;
#              [50] the Mac-vitals subprocess calls decode as UTF-8, because
#              text=True alone uses the host locale, ASCII in an Indigo host.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import subprocess
from types import SimpleNamespace

from conftest import bare_plugin, load_plugin_module


def _dev(i, enabled, **kw):
    base = dict(id=i, name=f"Dev {i}", enabled=enabled, pluginId="x", errorState="",
                batteryLevel=None, states={}, lastChanged=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_disabled_devices_are_not_in_error_or_low_battery(monkeypatch):
    load_plugin_module()
    import health_mixin
    devs = [_dev(1, True, errorState="timeout"), _dev(2, False, errorState="timeout"),
            _dev(3, True, batteryLevel=5), _dev(4, False, batteryLevel=5),
            _dev(5, False, states={"batteryLow": "true"})]
    monkeypatch.setattr(health_mixin.indigo, "devices", devs)
    p = bare_plugin()
    p.pluginPrefs = {}
    out = p._device_health()
    assert [d["id"] for d in out["in_error"]] == [1]
    assert [d["id"] for d in out["low_battery"]] == [3]
    assert out["disabled"] == 3


def test_vitals_subprocess_output_is_decoded_as_utf8(monkeypatch):
    seen = []

    def fake_run(args, **kw):
        seen.append(kw)
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    bare_plugin()._mac_vitals()
    assert seen, "the vitals made no subprocess call"
    for kw in seen:
        assert kw.get("encoding") == "utf-8" and kw.get("errors") == "replace", kw
