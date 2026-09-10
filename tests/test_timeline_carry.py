#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_timeline_carry.py
# Description: The Timeline page's "state at the start of the day" query must
#              be PK-bounded, never a ts-ordered scan. Until 2.95.1 it was the
#              one history query still filtering on raw ts — run BEFORE the
#              PK window was computed, once per lane device, on the plugin's
#              single dispatch thread — which is the exact full-scan-under-
#              read-lock shape that wedged IWS and MCP for ~3 minutes on
#              15-Jul-2026. Three reviewers found it independently.
#
#              The test records every SQL the lane builder issues against a
#              real SQLite table and asserts (a) the carry query carries an
#              `id <` bound and no `ts <` filter, (b) the carried state is
#              still correct: a lane that went ON before midnight and stayed
#              on is active from minute 0.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import sqlite3
import pytest
from conftest import bare_plugin, load_plugin_module


TABLE = "device_history_88"
DEV_ID = 88


class _RecordingConn:
    """A sqlite3 connection that keeps every statement it ran."""

    def __init__(self, conn):
        self._c = conn
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))
        return self._c.execute(sql, params)


@pytest.fixture()
def db(tmp_path):
    """A boolean lane: ON at 23:30 the day before, OFF at 01:00, ON at 06:00,
    one row a minute of other traffic so the table has real rows to scan."""
    path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute(f'CREATE TABLE "{TABLE}" (id INTEGER PRIMARY KEY, ts TEXT, onoffstate INTEGER, other TEXT)')
    # Day before: filler then the ON at 23:30.
    for m in range(0, 24 * 60):
        hh, mm = divmod(m, 60)
        v = 1 if (hh, mm) == (23, 30) else None
        conn.execute(f'INSERT INTO "{TABLE}" (ts, onoffstate, other) VALUES (?, ?, ?)',
                     (f"2026-08-31 {hh:02d}:{mm:02d}:00", v, "x"))
    # The day: OFF at 01:00, ON at 06:00.
    for m in range(0, 24 * 60):
        hh, mm = divmod(m, 60)
        v = 0 if (hh, mm) == (1, 0) else (1 if (hh, mm) == (6, 0) else None)
        conn.execute(f'INSERT INTO "{TABLE}" (ts, onoffstate, other) VALUES (?, ?, ?)',
                     (f"2026-09-01 {hh:02d}:{mm:02d}:00", v, "x"))
    conn.commit()
    conn.close()
    return _RecordingConn(sqlite3.connect(f"file:{path}?mode=ro", uri=True))


def _hist():
    plugin = load_plugin_module()
    hdb = plugin._history_db
    return hdb.HistoryDB(backend=hdb.SQLITE, sqlite_path="unused")


def test_carry_query_is_pk_bounded_and_correct(db):
    p = bare_plugin()
    hist = _hist()
    # A UTC day in GMT so local minutes == UTC minutes for the assertion.
    bounds = (1788220800, "2026-09-01 00:00:00", "2026-09-02 00:00:00")   # 2026-09-01 00:00 UTC
    spans = p._timeline_active_spans(hist, db, DEV_ID, "onoffstate", bounds)

    carry = [q for q in db.sql if "ORDER BY id DESC LIMIT 1" in q or "ORDER BY ts DESC LIMIT 1" in q]
    assert carry, "no carry-in query was issued"
    assert all("id <" in q for q in carry), f"carry query is not PK-bounded: {carry}"
    assert not any("ts <" in q and "ORDER BY ts DESC" in q for q in carry), \
        f"carry query still filters on raw ts: {carry}"

    # ON since 23:30 the day before -> active from minute 0 to 60 (OFF at
    # 01:00), then ON again from 06:00 (minute 360) to the end of the day.
    assert spans == [[0, 60.0], [360.0, 1440]]


def test_carry_falls_back_to_ts_only_when_no_pk_window(db, monkeypatch):
    p = bare_plugin()
    hist = _hist()
    monkeypatch.setattr(p, "_pk_window", lambda *a, **k: (None, None))
    bounds = (1788220800, "2026-09-01 00:00:00", "2026-09-02 00:00:00")
    spans = p._timeline_active_spans(hist, db, DEV_ID, "onoffstate", bounds)
    carry = [q for q in db.sql if "LIMIT 1" in q]
    assert any("ts <" in q for q in carry), "the ts fallback must still exist for a failed probe"
    assert spans == [[0, 60.0], [360.0, 1440]]
