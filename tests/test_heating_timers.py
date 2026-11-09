"""Heating timers use persisted, offset-aware expiries, never button press times."""
import json
from datetime import datetime

import pytest
from conftest import bare_plugin, load_plugin_module


def saved(tmp_path, monkeypatch, **values):
    mod = load_plugin_module()
    monkeypatch.setattr(mod.indigo.server, "getInstallFolderPath", lambda: str(tmp_path))
    folder = tmp_path / "Preferences/Plugins/com.clives.indigoplugin.evohomecontrol"
    folder.mkdir(parents=True)
    path = folder / "plugin_state.json"
    path.write_text(json.dumps(values))
    return bare_plugin(), path


@pytest.mark.parametrize("offset", ["+01:00", "+00:00"])
def test_saved_timers_survive_reload(tmp_path, monkeypatch, offset):
    expiry = "2026-10-25T01:30:00" + offset
    stamp = datetime.fromisoformat(expiry).timestamp()
    monkeypatch.setattr(load_plugin_module().time, "time", lambda: stamp - 3600)
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True,
                 timed_boost_hours=2, timed_boost_expiry=expiry,
                 summer_force_active=True, summer_force_expiry=expiry,
                 private_field="never returned")
    assert p._read_evo_timers() == {"boostExpiry": stamp, "boostHours": 2,
                                    "boostRooms": [], "summerExpiry": stamp}


def test_expiry_and_cancellation(tmp_path, monkeypatch):
    p, path = saved(tmp_path, monkeypatch, timed_boost_active=True,
                    timed_boost_hours=1, timed_boost_expiry="2020-01-01T12:00:00+00:00",
                    summer_force_active=False)
    assert p._read_evo_timers() == {"boostExpiry": None, "boostHours": 0,
                                    "boostRooms": [], "summerExpiry": None}
    path.write_text(json.dumps({"timed_boost_active": False, "summer_force_active": False}))
    assert p._read_evo_timers()["boostExpiry"] is None


@pytest.mark.parametrize("expiry", ["bad", None, "2026-10-25T01:30:00"])
def test_unknown_expiry_never_looks_active(tmp_path, monkeypatch, expiry):
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry=expiry)
    with pytest.raises((ValueError, TypeError)):
        p._read_evo_timers()


def test_status_failure_is_not_an_inactive_timer():
    p = bare_plugin()
    p._request_body = lambda a: ({}, None)
    p._offpath_get = lambda *a, **k: ("failed", "private path")
    reply = p.handleEvoHomeStatus(None)
    assert reply["status"] == 502
    assert "private path" not in reply["content"]


def test_status_checks_running_controller():
    mod = load_plugin_module()
    p = bare_plugin()
    p._request_body = lambda a: ({}, None)
    from unittest.mock import patch
    with patch.object(mod.indigo.server.getPlugin.return_value, "isRunning", return_value=False):
        assert p.handleEvoHomeStatus(None)["status"] == 503


def test_boost_rooms_passed_on_checked_and_sorted(tmp_path, monkeypatch):
    expiry = "2026-11-09T16:32:00+00:00"
    stamp = datetime.fromisoformat(expiry).timestamp()
    monkeypatch.setattr(load_plugin_module().time, "time", lambda: stamp - 600)
    outcome = {
        "110516814": {"room": "Living Room Front", "target": 22.0, "requested": 22.0,
                      "held": "", "at": "x", "secret": "dropped"},
        "9": {"room": "Dining Room", "target": 22, "requested": 16,
              "held": "it is already warm from the sun or the rest of the house"},
        "3": {"room": "Hall Kitchen", "target": 22.0, "requested": None, "held": ""},
        "bad": {"room": "x", "target": 22},
        "4": {"room": "No target"},
        "5": "not a dict",
    }
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry=expiry, timed_boost_outcome=outcome)
    rooms = p._read_evo_timers()["boostRooms"]
    assert [r["room"] for r in rooms] == ["Dining Room", "Hall Kitchen", "Living Room Front"]
    assert rooms[0] == {"id": 9, "room": "Dining Room", "target": 22.0, "requested": 16.0,
                        "held": "it is already warm from the sun or the rest of the house"}
    assert rooms[1]["requested"] is None
    assert "secret" not in rooms[2]


def test_no_boost_rooms_once_the_boost_has_ended(tmp_path, monkeypatch):
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry="2020-01-01T12:00:00+00:00",
                 timed_boost_outcome={"9": {"room": "Dining Room", "target": 22, "requested": 22}})
    assert p._read_evo_timers()["boostRooms"] == []
