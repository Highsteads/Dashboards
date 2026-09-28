#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_charger_mode.py
# Description: Contract test for Plugin.handleChargerMode — the Energy page's
#              car charger mode buttons (3.57.0).
#
#              WHAT IS LOCKED HERE
#              1. Only a Zappi-plugin charger and only its four modes: the
#                 handler must not become a way to fire any plugin's "setMode"
#                 at any device.
#              2. The command goes to the Zappi plugin's own setMode action,
#                 WITHOUT waiting — this runs on the web server's one dispatch
#                 thread and must never wait on another plugin.
#              3. A command that would be swallowed (device disabled, Zappi
#                 plugin stopped) is refused, not reported as sent.
#              4. The mode tokens agree in the three places they are written.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0

import json
import os
import re
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest
from conftest import bare_plugin, load_plugin_module

ZAPPI = "com.clives.indigoplugin.zappi"
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages")


class FakeAction:
    def __init__(self, body, content_type="application/json"):
        self.props = {"request_body": body, "headers": {"Content-Type": content_type}}


class _Devices:
    def __init__(self, devs):
        self._d = devs

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        return self._d[key]


def _dev(dev_id, name, plugin_id=ZAPPI, type_id="zappi", enabled=True):
    d = MagicMock()
    d.id, d.name, d.pluginId, d.deviceTypeId, d.enabled = dev_id, name, plugin_id, type_id, enabled
    return d


@pytest.fixture
def rig(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    zappi = _dev(58134337, "Zappi")
    lamp = _dev(372666822, "Living Room Lamp", plugin_id="com.clives.indigoplugin.z2mbridge", type_id="z2mLight")
    off = _dev(9, "Old Zappi", enabled=False)
    monkeypatch.setattr(plugin.indigo, "devices", _Devices({d.id: d for d in (zappi, lamp, off)}), raising=False)
    owner = MagicMock()
    owner.isInstalled.return_value = True
    owner.isRunning.return_value = True
    server = MagicMock()
    server.getPlugin.return_value = owner
    monkeypatch.setattr(plugin.indigo, "server", server, raising=False)
    p._evo_reply = lambda payload, status=200: {"status": status, "content": json.dumps(payload)}
    p.logger = MagicMock()
    return p, owner, server


def call(p, body, **kw):
    reply = p.handleChargerMode(FakeAction(json.dumps(body) if not isinstance(body, str) else body, **kw))
    return reply["status"], json.loads(reply["content"])


def test_passes_the_mode_to_the_zappi_plugin_without_waiting(rig):
    p, owner, server = rig
    status, body = call(p, {"deviceId": 58134337, "mode": "fast"})
    assert status == 202 and body["ok"] and body["mode"] == "fast"
    server.getPlugin.assert_any_call(ZAPPI)
    owner.executeAction.assert_called_once_with("setMode", deviceId=58134337,
                                                props={"mode": "fast"}, waitUntilDone=False)


@pytest.mark.parametrize("mode", ["fast", "eco", "ecoPlus", "stopped"])
def test_every_mode_is_accepted(rig, mode):
    p, owner, _ = rig
    assert call(p, {"deviceId": 58134337, "mode": mode})[0] == 202


@pytest.mark.parametrize("body, status", [
    ({"deviceId": "x", "mode": "fast"}, 400),
    ({"deviceId": 58134337, "mode": "turbo"}, 400),
    ({"deviceId": 58134337}, 400),
    ({"deviceId": 1, "mode": "fast"}, 404),
    ({"deviceId": 372666822, "mode": "fast"}, 400),      # not a charger
    ({"deviceId": 9, "mode": "fast"}, 409),              # disabled
])
def test_refuses_and_sends_nothing(rig, body, status):
    p, owner, _ = rig
    assert call(p, body)[0] == status
    owner.executeAction.assert_not_called()


def test_refused_when_the_zappi_plugin_is_stopped(rig):
    p, owner, _ = rig
    owner.isRunning.return_value = False
    status, body = call(p, {"deviceId": 58134337, "mode": "eco"})
    assert status == 503 and not body["ok"]
    owner.executeAction.assert_not_called()


def test_a_failure_to_pass_it_on_is_reported(rig):
    p, owner, _ = rig
    owner.executeAction.side_effect = RuntimeError("plugin went away")
    status, body = call(p, {"deviceId": 58134337, "mode": "eco"})
    assert status == 502 and "went away" in body["error"]


def test_a_form_post_is_refused(rig):
    p, owner, _ = rig
    assert call(p, {"deviceId": 58134337, "mode": "fast"}, content_type="text/plain")[0] == 415
    owner.executeAction.assert_not_called()


def test_mode_tokens_agree_everywhere():
    plugin = load_plugin_module()
    here = tuple(plugin.CHARGER_MODES)
    js = open(os.path.join(PAGES, "energy-calc.js"), encoding="utf-8").read()
    block = re.search(r"var CHARGER_MODES = \[(.*?)\];", js).group(1)
    assert tuple(re.findall(r"\['(\w+)',", block)) == here
    # The Zappi plugin's own setMode menu. Private repo: checked when the clone
    # is here, skipped honestly on CI rather than faked.
    actions = os.path.expanduser("~/GitHub/Zappi/Zappi.indigoPlugin/Contents/Server Plugin/Actions.xml")
    if not os.path.isfile(actions):
        pytest.skip("Zappi repo not present; checked on the development Mac")
    field = next(f for f in ET.parse(actions).getroot().iter("Field") if f.get("id") == "mode")
    assert tuple(o.get("value") for o in field.iter("Option")) == here
