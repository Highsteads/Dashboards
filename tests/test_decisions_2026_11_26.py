#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_decisions_2026_11_26.py
# Description: The server side of CliveS's answers to the deep review's
#              questions (3.74.0, 26-Nov-2026): a Settings save from a tab
#              older than the store is refused; the floor-probe list and the
#              silent-sensor limit are cleaned and published; the plugin times
#              each window and door opening itself; a plug that has gone
#              keeps its past days in the totals.
#              (The refusal of a command to a device whose plugin is not
#              installed is in test_command_guards.py.)
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026
# Version:     1.0
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import dash_common   # noqa: E402
import open_since    # noqa: E402
import plugs_mixin   # noqa: E402


class Action:
    def __init__(self, body):
        self.props = {"request_body": json.dumps(body), "headers": {"Content-Type": "application/json"}}


def _settings_plugin(store=None):
    p = bare_plugin()
    saved = []

    def _save(clean):
        saved.append(clean)
        out = dict(clean)
        out["_savedAt"] = 1795700000.5 + len(saved)
        return out
    p._save_config_store = _save
    p._write_config_js = MagicMock()
    p._build_rooms_json = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_store = dict(store or {})
    p.cameras = []
    p.pluginPrefs = {}
    return p, saved


def _post(p, body):
    reply = p.handleSaveDashboardsConfig(Action(body))
    return reply["status"], json.loads(reply["content"])


# ---- an old tab cannot overwrite a newer save --------------------------------

def test_a_save_must_carry_the_revision_the_page_loaded():
    p, saved = _settings_plugin({"siteName": "Home", "_savedAt": 1795700000.5})
    rev = p._config_rev()
    assert rev == repr(1795700000.5)

    status, body = _post(p, {"config": {"siteName": "Old tab"}})                  # a page from before the check
    assert status == 409 and body["stale"] is True and "Reload" in body["error"]
    status, body = _post(p, {"config": {"siteName": "Old tab"}, "rev": "1795600000.0"})
    assert status == 409
    assert saved == [], "nothing is written by a refused save"

    status, body = _post(p, {"config": {"siteName": "This tab"}, "rev": rev})
    assert status == 200 and saved[-1]["siteName"] == "This tab"
    assert p._config_rev() != rev, "the store has a new revision after a save"
    status, _ = _post(p, {"config": {"siteName": "Same tab, second save"}, "rev": rev})
    assert status == 409, "the tab must reload (the page does so after every save)"


def test_a_store_never_saved_has_an_empty_revision():
    p, saved = _settings_plugin({})
    assert p._config_rev() == ""
    assert _post(p, {"config": {"siteName": "First"}, "rev": ""})[0] == 200


def test_the_settings_page_is_given_the_revision_and_the_thermostats(monkeypatch):
    p, _ = _settings_plugin({"_savedAt": 1795700000.5})
    devs = [SimpleNamespace(id=3, name="Hall Radiator", folderId=0, states={"setpointHeat": 18}),
            SimpleNamespace(id=9, name="En Suite Floor", folderId=0, states={"setpoint": 14}),
            SimpleNamespace(id=5, name="Lamp", folderId=0, states={"onOffState": True})]
    assert p._thermostats_for_settings(devs) == [{"id": 9, "name": "En Suite Floor"},
                                                 {"id": 3, "name": "Hall Radiator"}]
    src = open(os.path.join(os.path.dirname(dash_common.__file__), "config_mixin.py"), encoding="utf-8").read()
    reply = src.split("def handleGetDashboardsConfig", 1)[1].split("def ", 1)[0]
    assert '"rev":          self._config_rev()' in reply and '"thermostats":  self._thermostats_for_settings(all_devs)' in reply


# ---- the two new settings ---------------------------------------------------

def test_the_silent_sensor_setting_is_cleaned_or_refused_by_name():
    f = dash_common.clean_contact_silent
    assert f(None) == ({"hours": 25, "byDevice": {}}, "")
    assert f({}) == ({"hours": 25, "byDevice": {}}, "")
    assert f({"hours": 13, "byDevice": {"495298132": 4, " 7 ": "4.5"}}) == (
        {"hours": 13, "byDevice": {"495298132": 4, "7": 4.5}}, "")
    assert f({"hours": 0})[0]["hours"] == 0                         # off
    assert f({"hours": ""})[0]["hours"] == 25                       # a blank field is the default
    for bad, word in (({"hours": "soon"}, "contactSilent.hours"), ({"hours": -1}, "between"),
                      ({"hours": True}, "contactSilent.hours"), ({"hours": float("nan")}, "between"),
                      ({"byDevice": []}, "byDevice"), ({"byDevice": {"x": 4}}, "not a device id"),
                      ({"byDevice": {"7": 9999}}, "between"), ("13", "must be an object")):
        out, err = f(bad)
        assert word in err, (bad, err)
        assert out == {"hours": 25, "byDevice": {}}, "a refused value leaves the default, never half of it"


def test_a_save_cleans_both_and_refuses_a_bad_one():
    p, saved = _settings_plugin({})
    status, _ = _post(p, {"config": {"notRoomTemp": ["9", 9, "x", 3], "contactSilent": {"hours": "13"}}, "rev": ""})
    assert status == 200
    assert saved[-1]["notRoomTemp"] == [3, 9]
    assert saved[-1]["contactSilent"] == {"hours": 13, "byDevice": {}}
    p2, saved2 = _settings_plugin({})
    status, body = _post(p2, {"config": {"contactSilent": {"hours": "soon"}}, "rev": ""})
    assert status == 400 and "contactSilent.hours" in body["error"] and saved2 == []
    status, body = _post(p2, {"config": {"notRoomTemp": "9"}, "rev": ""})
    assert status == 400 and "notRoomTemp" in body["error"]


def test_both_are_published_to_the_pages():
    src = open(os.path.join(os.path.dirname(dash_common.__file__), "publish_mixin.py"), encoding="utf-8").read()
    assert 'cfg["notRoomTemp"] = _safe_int_list(nrt) if isinstance(nrt, list) else []' in src
    assert 'cfg["contactSilent"] = clean_contact_silent(store.get("contactSilent"))[0]' in src


# ---- when each window and door was opened -----------------------------------

def test_an_opening_is_timed_and_a_closing_forgets_it():
    t = open_since.OpenSince()
    t.note(5, False, True, 1000.0)
    t.note(6, None, True, 1500.0)                      # first reading of a new sensor
    assert t.reply() == {"5": 1000.0, "6": 1500.0}
    t.note(5, True, True, 2000.0)                      # the same state written again is not an opening
    assert t.reply()["5"] == 1000.0
    t.note(5, True, False, 2500.0)
    assert t.reply() == {"6": 1500.0}
    t.note(7, True, False, 2600.0)                     # a closing nobody saw open: nothing to forget
    assert t.reply() == {"6": 1500.0}


def test_after_a_restart_the_kept_times_are_checked_against_the_sensors(tmp_path):
    path = str(tmp_path / "open_since.json")
    t = open_since.OpenSince()
    t.note(5, False, True, 1000.0)
    t.note(6, False, True, 1100.0)
    t.note(8, False, True, 1200.0)
    assert t.save(path) is True and t.save(path) is False        # written once, not again unchanged
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"

    back = open_since.OpenSince()
    back.load(path)
    back.reconcile({5: True, 6: False, 9: True}, trusted=True)
    assert back.reply() == {"5": 1000.0}, "6 was shut, 8 is no longer followed, 9 was not seen opening"

    away = open_since.OpenSince()
    away.load(path)
    away.reconcile({5: True, 6: True, 8: True}, trusted=False)
    assert away.reply() == {}, "the plugin was away too long: an old time is not shown as the answer"

    broken = tmp_path / "bad.json"
    broken.write_text("{not json", encoding="utf-8")
    worse = open_since.OpenSince()
    worse.load(str(broken))
    assert worse.reply() == {}


def test_the_plugin_follows_the_room_pages_contact_sensors(monkeypatch, tmp_path):
    p = bare_plugin()
    p.pluginId = "com.clives.indigoplugin.dashboards"
    p._open_since = open_since.OpenSince()
    p._open_ids = set()
    p._open_trusted = False
    p._open_since_path = lambda: str(tmp_path / "open_since.json")
    assert p._open_since_reply() == {}

    devs = {11: SimpleNamespace(id=11, onState=True), 12: SimpleNamespace(id=12, onState=False)}
    monkeypatch.setattr(plugin.indigo, "devices", devs, raising=False)
    p._open_since.since = {11: 500.0}                           # kept from before the restart
    p._open_since_follow({"Hall": {"windows": [11, 12]}, "Loft": {"windows": []}})
    assert p._open_ids == {11, 12}
    assert p._open_since_reply() == {}, "not trusted: the open window has no time until it next changes"

    p._dev_changes, p._stamp_note_change, p._alert_device_changed = {}, lambda: None, lambda a, b: None
    base = plugin.Plugin.__mro__[-2]
    monkeypatch.setattr(base, "deviceUpdated", lambda self, a, b: None, raising=False)
    mk = lambda i, on: SimpleNamespace(id=i, onState=on, pluginId="x")   # noqa: E731
    p.deviceUpdated(mk(12, False), mk(12, True))
    p.deviceUpdated(mk(99, False), mk(99, True))                # not a followed sensor
    assert list(p._open_since_reply()) == ["12"]
    p.deviceUpdated(mk(12, True), mk(12, False))
    assert p._open_since_reply() == {}

    p._boot_ts = 0.0
    p._dev_deleted = {}
    p.deviceUpdated(mk(11, False), mk(11, True))
    for since in (0, 10 ** 12):
        assert "11" in p._changed_since_payload(since)["openSince"], "every reply to the pages carries it"


# ---- a plug that has gone ----------------------------------------------------

def test_a_removed_plugs_past_days_stay_in_the_totals():
    keys = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"]
    days = {"2026-11-23": {"kwh": {"1": 1.0, "2": 0.5, "3": None}},
            "2026-11-24": {"kwh": {"1": 1.5, "2": 0.25}},
            "2026-11-25": {"kwh": {"1": 2.0}}}
    row = plugs_mixin.removed_plugs_row(days, keys, {1}, {"2": "Old Freezer", "3": "Spare"})
    assert row["kwh"] == [0.5, 0.25, None, None], "today is never in it"
    assert row["removed"] is True and row["names"] == ["Old Freezer"]
    assert plugs_mixin.removed_plugs_row(days, keys, {1, 2, 3}, {}) is None

    starts = [1795392000 + 86400 * i for i in range(4)]
    live = {"id": 1, "name": "Kettle", "room": "Kitchen", "answering": True, "kwh": [1.0, 1.5, 2.0, 0.4]}
    rep = plugs_mixin.build_report([live, row], starts, [(15.0, 120, 300)] * 4, starts[-1] + 3600)
    assert rep["totals"]["month"]["kwh"] == round(1.0 + 1.5 + 2.0 + 0.4 + 0.5 + 0.25, 3)
    assert rep["totals"]["today"]["kwh"] == 0.4
    gone = [x for x in rep["plugs"] if x["removed"]]
    assert len(gone) == 1 and gone[0]["name"] == "Plugs since removed" and gone[0]["names"] == ["Old Freezer"]
    assert rep["plugs"][-1]["removed"] is True, "it sits below the plugs that are still there"
    assert [x["removed"] for x in plugs_mixin.build_report([live], starts, [None] * 4, starts[-1])["plugs"]] == [False]
