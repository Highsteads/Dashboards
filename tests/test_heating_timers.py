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
                                    "boostRooms": [], "handHolds": [], "summerExpiry": stamp}


def test_expiry_and_cancellation(tmp_path, monkeypatch):
    p, path = saved(tmp_path, monkeypatch, timed_boost_active=True,
                    timed_boost_hours=1, timed_boost_expiry="2020-01-01T12:00:00+00:00",
                    summer_force_active=False)
    assert p._read_evo_timers() == {"boostExpiry": None, "boostHours": 0,
                                    "boostRooms": [], "handHolds": [], "summerExpiry": None}
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
                        "held": "it is already warm from the sun or the rest of the house",
                        "byHand": False, "until": None, "holdEnded": False, "at": None}
    assert rooms[1]["requested"] is None
    assert rooms[2]["at"] is None, "a time that cannot be read is no time, not a guess"
    assert "secret" not in rooms[2]


def test_no_boost_rooms_once_the_boost_has_ended(tmp_path, monkeypatch):
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry="2020-01-01T12:00:00+00:00",
                 timed_boost_outcome={"9": {"room": "Dining Room", "target": 22, "requested": 22}})
    assert p._read_evo_timers()["boostRooms"] == []


def test_hand_holds_are_passed_on_checked(tmp_path, monkeypatch):
    """3.72.0: rooms held by hand, from EvoHomeControl 1.29.0's hand_holds. Only a
    well-formed entry that has not run out is passed on, and nothing else from it."""
    now = 1_800_000_000.0
    monkeypatch.setattr(load_plugin_module().time, "time", lambda: now)
    p, path = saved(tmp_path, monkeypatch, timed_boost_active=False, summer_force_active=False,
                    hand_holds={
                        "7":  {"room": "En Suite", "until": now + 1800, "secret": "never returned"},
                        "3":  {"room": "Bathroom", "until": None},
                        "5":  {"room": "Run out", "until": now - 1},
                        "6":  {"room": "Rubbish", "until": "soon"},
                        "x":  {"room": "Bad id", "until": now + 60},
                        "8":  "not a dict",
                        "9":  {"room": "Flag", "until": True},
                    })
    assert p._read_evo_timers()["handHolds"] == [
        {"id": 3, "room": "Bathroom", "until": None},
        {"id": 7, "room": "En Suite", "until": now + 1800},
    ]
    path.write_text(json.dumps({"timed_boost_active": False, "summer_force_active": False,
                                "hand_holds": ["not", "a", "dict"]}))
    assert p._read_evo_timers()["handHolds"] == []
    path.write_text(json.dumps({"timed_boost_active": False, "summer_force_active": False}))
    assert p._read_evo_timers()["handHolds"] == [], "an older heating controller saves none"


def test_a_room_set_by_hand_during_a_boost_is_passed_on(tmp_path, monkeypatch):
    """3.73.0: EvoHomeControl 1.30.0 marks a room set by hand during the boost, with the
    radiator's own setting and when the hold ends. Only a real True and a real number
    are passed on."""
    expiry = "2999-01-01T12:00:00+00:00"
    # The clock is pinned before the hold's end: since 3.73.13 a hold that has
    # already ended is sent without its `until`, and this fixture's end is a
    # fixed moment in November 2026.
    monkeypatch.setattr(load_plugin_module().time, "time", lambda: 1795615000.0)
    outcome = {
        "2": {"room": "Conservatory", "target": 22.0, "requested": 20.0,
              "held": "it was set by hand", "by_hand": True, "until": 1795615348.0},
        "9": {"room": "Dining Room", "target": 22.0, "requested": 21.0,
              "held": "it was set by hand", "by_hand": "yes", "until": "soon"},
        "3": {"room": "Hall Kitchen", "target": 22.0, "requested": 22.0, "held": "",
              "by_hand": True, "until": True},
    }
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry=expiry, timed_boost_outcome=outcome)
    rooms = {r["room"]: r for r in p._read_evo_timers()["boostRooms"]}
    assert (rooms["Conservatory"]["byHand"], rooms["Conservatory"]["until"]) == (True, 1795615348.0)
    assert (rooms["Dining Room"]["byHand"], rooms["Dining Room"]["until"]) == (False, None)
    assert (rooms["Hall Kitchen"]["byHand"], rooms["Hall Kitchen"]["until"]) == (True, None)


def test_a_boost_line_carries_when_it_was_written_and_a_hold_that_has_ended(tmp_path, monkeypatch):
    """3.73.13: the page could not say how old the lines were, and quoted a
    by-hand hold as lasting "until 3:58pm" after 3:58."""
    now = 1_800_000_000.0
    monkeypatch.setattr(load_plugin_module().time, "time", lambda: now)
    outcome = {
        "2": {"room": "Conservatory", "target": 22.0, "requested": 20.0, "held": "it was set by hand",
              "by_hand": True, "until": now - 30, "at": "2027-01-15T08:00:00+00:00"},
        "3": {"room": "Hall", "target": 22.0, "requested": 21.0, "held": "it was set by hand",
              "by_hand": True, "until": now + 600, "at": "2027-01-15T08:00:00"},
    }
    p, _ = saved(tmp_path, monkeypatch, timed_boost_active=True, timed_boost_hours=1,
                 timed_boost_expiry="2999-01-01T12:00:00+00:00", timed_boost_outcome=outcome)
    rooms = {r["room"]: r for r in p._read_evo_timers()["boostRooms"]}
    assert (rooms["Conservatory"]["holdEnded"], rooms["Conservatory"]["until"]) == (True, None)
    assert rooms["Conservatory"]["at"] == 1_800_000_000.0
    assert (rooms["Hall"]["holdEnded"], rooms["Hall"]["until"]) == (False, now + 600)
    assert rooms["Hall"]["at"] is None, "a wall time with no zone is not guessed at"
