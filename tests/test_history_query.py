#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_query.py
# Description: Contract test for Plugin._history_query against a fixture SQL
#              Logger DB. Proves the read-only + injection-safe contract: a
#              caller-supplied state name is sanitised to [a-z0-9_] and checked
#              against the live schema (a DROP never executes), clamps on
#              hours/maxPoints hold, bad deviceId raises ValueError, and the ro
#              connection cannot write.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import sqlite3
import pytest
from conftest import bare_plugin


@pytest.fixture()
def plugin_with_db(tmp_path):
    """Bare plugin whose _history_db_path points at a fixture DB with a
    device_history_42 table (id, ts, temperature, humidity), rows in the last
    couple of hours so a 24h series returns points."""
    db = tmp_path / "indigo_history.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE device_history_42 "
                 "(id INTEGER PRIMARY KEY, ts TEXT, temperature TEXT, humidity TEXT)")
    for mins, t, h in [(90, "19.0", "50"), (60, "20.0", "51"),
                       (30, "21.0", "52"), (5, "22.0", "53")]:
        conn.execute(
            "INSERT INTO device_history_42 (ts, temperature, humidity) "
            f"VALUES (datetime('now','-{mins} minutes'), ?, ?)", (t, h))
    conn.commit()
    conn.close()

    p = bare_plugin()
    p._history_db_path = lambda: str(db)
    return p


def test_states_action_lists_columns(plugin_with_db):
    out = plugin_with_db._history_query({"action": "states", "deviceId": 42})
    assert out["ok"] is True
    assert set(out["states"]) == {"temperature", "humidity"}
    assert out["rows"] == 4


def test_series_returns_buckets(plugin_with_db):
    out = plugin_with_db._history_query(
        {"action": "series", "deviceId": 42, "state": "temperature", "hours": 24})
    assert out["ok"] is True and out["state"] == "temperature"
    assert len(out["points"]) >= 1
    assert all({"t", "avg", "min", "max", "n"} <= set(pt) for pt in out["points"])


def test_injection_state_sanitised_never_executes(plugin_with_db):
    # A DROP-laden state sanitises to a non-column and is rejected — and the
    # table is still there afterwards.
    with pytest.raises(ValueError):
        plugin_with_db._history_query(
            {"action": "series", "deviceId": 42,
             "state": "temperature\"; DROP TABLE device_history_42;--"})
    # Table survived.
    again = plugin_with_db._history_query({"action": "states", "deviceId": 42})
    assert again["rows"] == 4


def test_unknown_state_raises(plugin_with_db):
    with pytest.raises(ValueError):
        plugin_with_db._history_query(
            {"action": "series", "deviceId": 42, "state": "pressure"})


@pytest.mark.parametrize("bad", [0, -5, "abc"])
def test_bad_device_id_raises(plugin_with_db, bad):
    with pytest.raises(ValueError):
        plugin_with_db._history_query({"action": "states", "deviceId": bad})


def test_no_history_for_device_raises(plugin_with_db):
    with pytest.raises(ValueError):
        plugin_with_db._history_query({"action": "states", "deviceId": 999})


def test_hours_and_maxpoints_clamp(plugin_with_db):
    # hours 99999 -> 2160; hours 0 (falsy) -> 24; maxPoints 5 -> 20.
    out = plugin_with_db._history_query(
        {"action": "series", "deviceId": 42, "state": "temperature",
         "hours": 99999, "maxPoints": 5})
    assert out["hours"] == 2160.0
    # bucket = max(60, int(2160*3600/20)) = 388800
    assert out["bucketSeconds"] == max(60, int(2160 * 3600 / 20))

    out0 = plugin_with_db._history_query(
        {"action": "series", "deviceId": 42, "state": "temperature", "hours": 0})
    assert out0["hours"] == 24.0


def test_plugin_connection_cannot_write(plugin_with_db):
    # Through the PLUGIN's own connect path — the old version opened its own
    # mode=ro connection and so tested sqlite3, not the plugin (a tautology
    # that would stay green if the plugin ever dropped its read-only guard).
    hist = plugin_with_db._history()
    conn = hist.connect()
    try:
        with pytest.raises(Exception):
            conn.execute("INSERT INTO device_history_42 (ts) VALUES ('x')")
    finally:
        conn.close()


def test_missing_db_raises(tmp_path):
    p = bare_plugin()
    p._history_db_path = lambda: str(tmp_path / "nope.sqlite")
    with pytest.raises(ValueError):
        p._history_query({"action": "states", "deviceId": 42})
