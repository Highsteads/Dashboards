#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_review_batch11.py
# Description: Server side of the Timeline fixes from the 25/26-Nov-2026 deep
#              review (3.73.13): a day the house has not reached is refused;
#              a state carried into a day says when it was recorded; a history
#              file nobody writes to any more says so; a chart is given the
#              last value from before its range; the presence file says how
#              old it is; and the heating history... is in the .mjs suite.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026
# Version:     1.0
import json
import os
import sqlite3
import time
from datetime import datetime as _real_dt


from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import history_db as hdb       # noqa: E402
import history_mixin           # noqa: E402


class _Action:
    def __init__(self, body):
        self.props = {"request_body": json.dumps(body), "headers": {}}


def test_a_day_the_house_has_not_reached_is_refused(monkeypatch):
    class _Fixed(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return _real_dt(2026, 12, 3, 13, 0, 0)
    monkeypatch.setattr(history_mixin, "datetime", _Fixed)
    p = bare_plugin()
    p.pluginPrefs = {}
    built = []
    p._offpath_get = lambda key, producer, ttl, wait=None: built.append(key) or ("fresh", {"ok": True})
    reply = p.handleTimelineDay(_Action({"date": "2026-12-04"}))
    assert reply["status"] == 400
    assert "not started" in json.loads(reply["content"])["error"]
    assert built == [], "nothing is built for it"
    assert p.handleTimelineDay(_Action({"date": "2026-12-03"}))["status"] == 200
    assert p.handleTimelineDay(_Action({"date": "2026-12-01"}))["status"] == 200


def test_a_carried_state_says_when_it_was_recorded(tmp_path):
    path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE "device_history_88" (id INTEGER PRIMARY KEY, ts TEXT, onoffstate INTEGER, other TEXT)')
    conn.execute('INSERT INTO "device_history_88" (ts, onoffstate, other) VALUES (?, ?, ?)',
                 ("2026-08-20 21:15:00", 1, "x"))                       # switched on, then silence
    for hh in range(0, 24):
        conn.execute('INSERT INTO "device_history_88" (ts, onoffstate, other) VALUES (?, ?, ?)',
                     (f"2026-08-31 {hh:02d}:00:00", None, "x"))
        conn.execute('INSERT INTO "device_history_88" (ts, onoffstate, other) VALUES (?, ?, ?)',
                     (f"2026-09-01 {hh:02d}:00:00", None, "x"))
    conn.commit()
    conn.close()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    p = bare_plugin()
    hist = hdb.HistoryDB(backend=hdb.SQLITE, sqlite_path="unused")
    bounds = (1788220800, "2026-09-01 00:00:00", "2026-09-02 00:00:00")
    info = {}
    spans = p._timeline_active_spans(hist, ro, 88, "onoffstate", bounds, info)
    assert spans == [[0, 1440]]
    assert info["onSince"] == int(_real_dt(2026, 8, 20, 21, 15).replace(
        tzinfo=__import__("datetime").timezone.utc).timestamp())
    off = {}
    ro.close()
    conn = sqlite3.connect(str(path))
    conn.execute('INSERT INTO "device_history_88" (id, ts, onoffstate, other) VALUES (2000, ?, ?, ?)',
                 ("2026-09-03 00:00:00", 0, "x"))
    conn.commit()
    conn.close()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    later = (1788220800 + 3 * 86400, "2026-09-04 00:00:00", "2026-09-05 00:00:00")
    assert p._timeline_active_spans(hist, ro, 88, "onoffstate", later, off) == []
    assert "onSince" not in off, "a device that is off carries nothing"


def test_a_history_file_nobody_writes_to_says_so(tmp_path):
    path = tmp_path / "indigo_history.sqlite"
    sqlite3.connect(str(path)).close()
    path.write_bytes(path.read_bytes() or b"x")
    hist = hdb.HistoryDB(backend=hdb.SQLITE, sqlite_path=str(path))
    now = time.time()
    assert hist.source_age_seconds(now) < 60
    assert hist.stale_note(now) == ""
    old = now - 3 * 86400 - 100
    os.utime(str(path), (old, old))
    assert 3 * 86400 <= hist.source_age_seconds(now) < 3 * 86400 + 200
    assert "for 3 days" in hist.stale_note(now)
    # The write-ahead log is where a WAL database's newest writes are.
    wal = tmp_path / "indigo_history.sqlite-wal"
    wal.write_bytes(b"x")
    assert hist.source_age_seconds(now) < 60 and hist.stale_note(now) == ""
    assert hdb.HistoryDB(backend=hdb.SQLITE, sqlite_path=str(tmp_path / "missing")).source_age_seconds() is None
    assert hdb.HistoryDB(backend=hdb.POSTGRES, pg_config={}).source_age_seconds() is None


def test_a_chart_is_given_the_last_value_from_before_its_range(tmp_path):
    """A lamp switched on three days ago and left: nothing in the last 24 hours,
    and the chart said "Nothing recorded"."""
    db = tmp_path / "indigo_history.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE device_history_42 (id INTEGER PRIMARY KEY, ts TEXT, onoffstate TEXT, other TEXT)")
    conn.execute("INSERT INTO device_history_42 (ts, onoffstate, other) VALUES (datetime('now','-80 hours'), '0', 'x')")
    conn.execute("INSERT INTO device_history_42 (ts, onoffstate, other) VALUES (datetime('now','-72 hours'), '1', 'x')")
    for mins in (600, 300, 30):
        conn.execute(f"INSERT INTO device_history_42 (ts, onoffstate, other) VALUES (datetime('now','-{mins} minutes'), NULL, 'x')")
    conn.commit()
    conn.close()
    p = bare_plugin()
    p._history_db_path = lambda: str(db)
    out = p._history_query({"action": "series", "deviceId": 42, "state": "onoffstate", "hours": 24})
    assert out["points"] == []
    assert out["before"]["v"] == 1.0
    assert abs(out["before"]["t"] - (time.time() - 72 * 3600)) < 120
    assert abs(out["now"] - time.time()) < 5
    week = p._history_query({"action": "series", "deviceId": 42, "state": "onoffstate", "hours": 168})
    assert week["before"] is None and len(week["points"]) == 2, "inside the range there is nothing before it"


def test_the_presence_file_says_how_old_it_is(tmp_path):
    p = bare_plugin()
    install = tmp_path / "Indigo 2025.2"
    install.mkdir()
    (tmp_path / "Python Scripts").mkdir()
    plugin.indigo.server.getInstallFolderPath.return_value = str(install)
    data = tmp_path / "Python Scripts" / "presence_data.json"
    data.write_text(json.dumps({"dates": [], "rooms": {}, "_writeTs": time.time() - 3 * 86400}), encoding="utf-8")
    out = json.loads(p.handlePresenceData(None)["content"])
    assert 3 * 86400 - 5 <= out["ageSeconds"] <= 3 * 86400 + 60
    data.write_text(json.dumps({"dates": [], "rooms": {}}), encoding="utf-8")     # no stamp: the file's own time
    assert json.loads(p.handlePresenceData(None)["content"])["ageSeconds"] < 60
