#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_levoit_control.py
# Description: Contract test for Plugin.handleLevoitControl - the Air page's
#              purifier controls (3.63.0) - and the levoitAvailable flag.
#
#              WHAT IS LOCKED HERE
#              1. Only a Levoit Purifier device, only the allow-listed commands
#                 and values: the handler must not become a way to fire any
#                 plugin's actions at any device.
#              2. The command goes to the Levoit plugin's own action, WITHOUT
#                 waiting - this runs on the web server's one dispatch thread.
#              3. A command that would be swallowed (device disabled, Levoit
#                 plugin stopped) is refused, not reported as sent.
#              4. The action ids, prop names and values agree with the Levoit
#                 plugin's Actions.xml and with the Air page.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-10-2026
# Version:     1.0

import json
import os
import re
import types
from datetime import datetime
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest
from conftest import bare_plugin, load_plugin_module

LEVOIT = "com.clives.indigoplugin.levoit"
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages")
LEVOIT_ACTIONS = os.path.expanduser("~/GitHub/Levoit/Levoit.indigoPlugin/Contents/Server Plugin/Actions.xml")


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


def _dev(dev_id, name, plugin_id=LEVOIT, type_id="levoitPurifier", enabled=True):
    d = MagicMock()
    d.id, d.name, d.pluginId, d.deviceTypeId, d.enabled = dev_id, name, plugin_id, type_id, enabled
    return d


@pytest.fixture
def rig(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    purifier = _dev(4100, "Bedroom Purifier")
    zappi = _dev(58134337, "Zappi", plugin_id="com.clives.indigoplugin.zappi", type_id="zappi")
    off = _dev(9, "Old Purifier", enabled=False)
    monkeypatch.setattr(plugin.indigo, "devices", _Devices({d.id: d for d in (purifier, zappi, off)}), raising=False)
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
    reply = p.handleLevoitControl(FakeAction(json.dumps(body) if not isinstance(body, str) else body, **kw))
    return reply["status"], json.loads(reply["content"])


def test_passes_a_fan_speed_to_the_levoit_plugin_without_waiting(rig):
    p, owner, server = rig
    status, body = call(p, {"deviceId": 4100, "command": "fanSpeed", "value": 3})
    assert status == 202 and body["ok"] and body["value"] == "3"
    server.getPlugin.assert_any_call(LEVOIT)
    owner.executeAction.assert_called_once_with("setFanSpeed", deviceId=4100,
                                                props={"speed": "3"}, waitUntilDone=False)


@pytest.mark.parametrize("command, value, action_id, props", [
    ("fanSpeed", "1", "setFanSpeed", {"speed": "1"}),
    ("mode", "sleep", "setMode", {"mode": "sleep"}),
    ("autoPreference", "quiet", "setAutoPreference", {"preference": "quiet"}),
    ("childLock", "on", "setChildLock", {"value": "on"}),
    ("display", "off", "setDisplay", {"value": "off"}),
])
def test_every_command_maps_to_its_action(rig, command, value, action_id, props):
    p, owner, _ = rig
    assert call(p, {"deviceId": 4100, "command": command, "value": value})[0] == 202
    owner.executeAction.assert_called_once_with(action_id, deviceId=4100, props=props, waitUntilDone=False)


@pytest.mark.parametrize("body, status", [
    ({"deviceId": 4100, "command": "fanSpeed", "value": 5}, 400),
    ({"deviceId": 4100, "command": "fanSpeed", "value": True}, 400),      # true is not a speed
    ({"deviceId": 4100, "command": "fanSpeed"}, 400),
    ({"deviceId": 4100, "command": "mode", "value": "turbo"}, 400),
    ({"deviceId": 4100, "command": "childLock", "value": "toggle"}, 400),
    ({"deviceId": 4100, "command": "resetFilter", "value": ""}, 400),     # not from a web page
    ({"deviceId": 4100, "command": "power", "value": "on"}, 400),         # on/off use turnOn/turnOff
    ({"deviceId": "x", "command": "mode", "value": "auto"}, 400),
    ({"deviceId": 1, "command": "mode", "value": "auto"}, 404),
    ({"deviceId": 58134337, "command": "mode", "value": "auto"}, 400),    # not a purifier
    ({"deviceId": 9, "command": "mode", "value": "auto"}, 409),           # disabled
])
def test_refuses_and_sends_nothing(rig, body, status):
    p, owner, _ = rig
    assert call(p, body)[0] == status
    owner.executeAction.assert_not_called()


def test_refused_when_the_levoit_plugin_is_stopped(rig):
    p, owner, _ = rig
    owner.isRunning.return_value = False
    status, body = call(p, {"deviceId": 4100, "command": "mode", "value": "auto"})
    assert status == 503 and not body["ok"]
    owner.executeAction.assert_not_called()


def test_a_failure_to_pass_it_on_is_reported(rig):
    p, owner, _ = rig
    owner.executeAction.side_effect = RuntimeError("plugin went away")
    status, body = call(p, {"deviceId": 4100, "command": "mode", "value": "auto"})
    assert status == 502 and "went away" in body["error"]


def test_a_form_post_is_refused(rig):
    p, owner, _ = rig
    assert call(p, {"deviceId": 4100, "command": "mode", "value": "auto"}, content_type="text/plain")[0] == 415
    owner.executeAction.assert_not_called()


def test_hidden_action_is_declared():
    root = ET.parse(os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Server Plugin",
                                 "Actions.xml")).getroot()
    action = next(a for a in root.iter("Action") if a.get("id") == "levoitControl")
    assert action.get("uiPath") == "hidden" and action.find("CallbackMethod").text == "handleLevoitControl"


def test_tokens_agree_with_the_air_page():
    plugin = load_plugin_module()
    html = open(os.path.join(PAGES, "levoit.html"), encoding="utf-8").read()
    view = open(os.path.join(PAGES, "levoit-view.js"), encoding="utf-8").read()
    sent = set(re.findall(r'data-cmd="(\w+)"', html)) | set(re.findall(r'data-switch="(\w+)"', html))
    assert sent == set(plugin.LEVOIT_COMMANDS)
    for key in plugin.LEVOIT_COMMANDS["mode"][2]:
        assert f"['{key}'," in view
    for key in plugin.LEVOIT_COMMANDS["autoPreference"][2]:
        assert f"['{key}'," in view
    assert "FAN_LEVELS = [1, 2, 3, 4]" in view
    assert "DashUI.message(\"levoitControl\"" in html


def test_tokens_agree_with_the_levoit_plugin():
    plugin = load_plugin_module()
    if not os.path.isfile(LEVOIT_ACTIONS):
        pytest.skip("Levoit repo not present; checked on the development Mac")
    root = ET.parse(LEVOIT_ACTIONS).getroot()
    actions = {a.get("id"): a for a in root.iter("Action")}
    for command, (action_id, prop, allowed) in plugin.LEVOIT_COMMANDS.items():
        assert action_id in actions, command
        field = next(f for f in actions[action_id].iter("Field") if f.get("id") == prop)
        offered = {o.get("value") for o in field.iter("Option")}
        assert set(allowed) <= offered, (command, set(allowed) - offered)
        assert actions[action_id].get("deviceFilter") == "self.levoitPurifier"


def test_levoit_flag_is_published(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    seen = []

    def present(pid):
        seen.append(pid)
        return pid == LEVOIT
    p._plugin_present = present
    p._sigen_available = lambda: False
    p._companion_scripts_installed = lambda: {}
    p._catalog_published = lambda: False
    flags = p._feature_flags()
    assert flags["levoitAvailable"] is True and LEVOIT in seen
    assert plugin.LEVOIT_PLUGIN_ID == LEVOIT


# ── power and running cost (levoitEnergy) ──
# CliveS, 24-10-2026: priced at Flux's cheap 2-5am rate only, because the house
# runs the purifier from the battery and the battery is filled at that rate.

REAL_SPANS = json.dumps([   # elec_rates_today_json as published on 24-10-2026
    {"value_inc_vat": 25.6271, "valid_from": "2026-10-23T18:00:00Z", "valid_to": "2026-10-24T01:00:00Z"},
    {"value_inc_vat": 15.473, "valid_from": "2026-10-24T01:00:00Z", "valid_to": "2026-10-24T04:00:00Z"},
    {"value_inc_vat": 25.6271, "valid_from": "2026-10-24T04:00:00Z", "valid_to": "2026-10-24T15:00:00Z"},
    {"value_inc_vat": 35.7813, "valid_from": "2026-10-24T15:00:00Z", "valid_to": "2026-10-24T18:00:00Z"},
    {"value_inc_vat": 25.6271, "valid_from": "2026-10-24T18:00:00Z", "valid_to": "2026-10-25T02:00:00Z"},
])


@pytest.fixture
def london(monkeypatch):
    import time as _t
    monkeypatch.setenv("TZ", "Europe/London")
    _t.tzset()
    yield
    monkeypatch.undo()
    _t.tzset()


def cost_module():
    load_plugin_module()                       # puts Server Plugin on sys.path
    import device_cost
    return device_cost


def test_the_cheap_rate_is_the_2_to_5am_band(london):
    C = cost_module()
    assert C.cheap_rate(REAL_SPANS) == (15.473, 120, 300)
    assert C.rate_words(C.cheap_rate(REAL_SPANS)) == "15.5p a unit, the 2am to 5am rate"


@pytest.mark.parametrize("bad", ["", "not json", "[]", json.dumps([{"valid_from": "x"}]), None])
def test_no_usable_rates_means_no_rate(bad):
    assert cost_module().cheap_rate(bad) is None


def test_energy_slices_follow_the_midnight_restart():
    C = cost_module()
    rows = [(100, 0.60), (200, 0.62), (300, 0.62), (400, 0.01), (500, 0.03)]   # midnight between 300 and 400
    assert [round(u, 4) for _, u in C.kwh_slices(rows)] == [0.02, 0.01, 0.02]
    assert C.kwh_between(C.kwh_slices(rows), 350) == 0.03


def test_a_gap_over_midnight_is_not_read_as_one_slice(london):
    C = cost_module()
    import time as _t
    day1 = _t.mktime((2026, 10, 20, 22, 0, 0, 0, 0, -1))
    day2 = _t.mktime((2026, 10, 21, 9, 0, 0, 0, 0, -1))
    rows = [(int(day1), 0.50), (int(day2), 0.60)]       # no readings overnight; 0.60 is since day 2's midnight
    assert C.kwh_slices(rows) == [(int(day2), 0.60)]


def test_cost_pence():
    C = cost_module()
    assert C.cost_pence(0.0705, 15.473) == 1.09
    assert C.cost_pence(0.0705, None) is None and C.cost_pence(None, 15.0) is None


class _Vars(dict):
    def __getitem__(self, key):
        return types.SimpleNamespace(value=dict.__getitem__(self, key))


def energy_rig(monkeypatch, plug_props=True, spans=REAL_SPANS):
    plugin = load_plugin_module()
    p = bare_plugin()
    pur = _dev(4100, "Bedroom Purifier")
    pur.globalProps = {LEVOIT: {"powerPlug": "566451865"} if plug_props else {}}
    plug = _dev(566451865, "Air Purifier Plug", plugin_id="com.clives.indigoplugin.shellydirect", type_id="shellyRelay")
    plug.states = {"energyKwhToday": 0.0705, "powerWatts": 4.2}
    monkeypatch.setattr(plugin.indigo, "devices", _Devices({d.id: d for d in (pur, plug)}), raising=False)
    monkeypatch.setattr(plugin.indigo, "variables", _Vars({"elec_rates_today_json": spans} if spans else {}),
                        raising=False)
    p._evo_reply = lambda payload, status=200: {"status": status, "content": json.dumps(payload)}
    p.logger = MagicMock()
    p._offpath_get = lambda key, producer, ttl, wait=None: ("fresh", producer())
    return p


def energy(p, body):
    reply = p.handleLevoitEnergy(FakeAction(json.dumps(body)))
    return reply["status"], json.loads(reply["content"])


def test_energy_today_and_week_at_the_cheap_rate(monkeypatch, london):
    p = energy_rig(monkeypatch)
    import time as _t
    now = _t.time()
    today0 = _t.mktime(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timetuple())
    rows = [(int(today0 - 3 * 86400), 0.10), (int(today0 - 3 * 86400 + 600), 0.20),   # 0.1 kWh three days ago
            (int(today0 - 600), 0.65), (int(today0 - 60), 0.70),                        # yesterday: 0.70 in all
            (int(now - 7200), 0.30), (int(now - 3600), 0.02), (int(now - 60), 0.07)]    # today: 0.30, plug restarts, 0.07 more
    p._energy_today_rows = lambda plug_id, start: rows
    status, body = energy(p, {"deviceId": 4100})
    assert status == 200 and body["plug"] == {"id": 566451865, "name": "Air Purifier Plug"}
    # Today from the history, not the plug's 0.0705: the plug restarted, which
    # starts its own counter again (seen live 24-10-2026), so the history's
    # 0.30 before the restart and 0.07 after it is the real figure.
    assert body["today"] == {"kwh": 0.37, "pence": round(0.37 * 15.473, 2)}
    # Yesterday's first reading after a gap is energy since ITS midnight (0.65),
    # then 0.05 more; three days ago adds 0.1.
    assert body["week"]["kwh"] == round(0.1 + 0.65 + 0.05 + 0.37, 4)
    assert body["week"]["pence"] == round(body["week"]["kwh"] * 15.473, 2)
    assert body["rate"] == {"pence": 15.47, "words": "15.5p a unit, the 2am to 5am rate"}


def test_energy_says_when_history_starts_part_way_through_the_week(monkeypatch, london):
    p = energy_rig(monkeypatch)
    import time as _t
    p._energy_today_rows = lambda plug_id, start: [(int(_t.time() - 7200), 0.05), (int(_t.time() - 60), 0.07)]
    _, body = energy(p, {"deviceId": 4100})
    assert body["week"]["since"]                     # a weekday and a date


def test_energy_without_history_uses_the_plugs_own_today(monkeypatch):
    p = energy_rig(monkeypatch)
    p._energy_today_rows = lambda plug_id, start: []
    _, body = energy(p, {"deviceId": 4100})
    assert body["today"]["kwh"] == 0.0705 and body["week"] is None


def test_energy_without_a_plug_is_not_an_error(monkeypatch):
    p = energy_rig(monkeypatch, plug_props=False)
    assert energy(p, {"deviceId": 4100}) == (200, {"ok": True, "plug": None})


def test_energy_without_prices_gives_kwh_only(monkeypatch):
    p = energy_rig(monkeypatch, spans=None)
    p._energy_today_rows = lambda plug_id, start: []
    _, body = energy(p, {"deviceId": 4100})
    assert body["today"] == {"kwh": 0.0705, "pence": None} and body["rate"] is None and body["week"] is None


def test_energy_refuses_other_devices(monkeypatch):
    p = energy_rig(monkeypatch)
    assert energy(p, {"deviceId": 566451865})[0] == 400
    assert energy(p, {"deviceId": "x"})[0] == 400
    assert energy(p, {"deviceId": 1})[0] == 404


def test_energy_action_is_declared_and_the_page_uses_it():
    root = ET.parse(os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Server Plugin",
                                 "Actions.xml")).getroot()
    action = next(a for a in root.iter("Action") if a.get("id") == "levoitEnergy")
    assert action.get("uiPath") == "hidden" and action.find("CallbackMethod").text == "handleLevoitEnergy"
    html = open(os.path.join(PAGES, "levoit.html"), encoding="utf-8").read()
    assert 'DashUI.message("levoitEnergy"' in html and "function energyBlock(v)" in html
