#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_timeline.py
# Description: Contract test for the timeline-replay helpers (v2.40.0):
#              _as_bool01 (string/number → 0/1), _mins_from_midnight (local ts →
#              minutes), and _timeline_active_spans against a fixture history DB
#              (carry-in state, span open/close, still-active-at-day-end).
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import calendar
import sqlite3
import time
import pytest
from conftest import bare_plugin


# ---- pure helpers ----------------------------------------------------------

# ---- span assembly against a fixture DB ------------------------------------

def _epoch_utc(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


@pytest.fixture()
def conn(tmp_path):
    db = sqlite3.connect(str(tmp_path / "hist.sqlite"))
    # Device 99: two clean transitions inside the day, no carry-in.
    db.execute("CREATE TABLE device_history_99 (id INTEGER PRIMARY KEY, ts TEXT, onoffstate TEXT)")
    for ts, v in [("2026-07-10 07:30:00", "true"), ("2026-07-10 08:00:00", "false"),
                  ("2026-07-10 20:00:00", "on"),  ("2026-07-10 20:15:00", "off")]:
        db.execute("INSERT INTO device_history_99 (ts, onoffstate) VALUES (?, ?)", (ts, v))
    # Device 77: ON before the day starts (carry-in), turns off at 00:15,
    # then back on at 23:50 and never off (still active at day end).
    db.execute("CREATE TABLE device_history_77 (id INTEGER PRIMARY KEY, ts TEXT, onoffstate TEXT)")
    for ts, v in [("2026-07-09 22:00:00", "true"), ("2026-07-10 00:15:00", "false"),
                  ("2026-07-10 23:50:00", "true")]:
        db.execute("INSERT INTO device_history_77 (ts, onoffstate) VALUES (?, ?)", (ts, v))
    db.commit()
    yield db
    db.close()


# _timeline_active_spans now takes the HistoryDB so it can use the right SQL
# dialect (v2.47.0 added a PostgreSQL backend). A SQLite instance keeps these
# tests exercising exactly the SQL the default install runs.
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "Dashboards.indigoPlugin", "Contents", "Server Plugin"))
import history_db as _hdb                      # noqa: E402
HIST = _hdb.HistoryDB(backend="sqlite")

# Bounds where local midnight == UTC midnight (the winter/GMT case).
BOUNDS = (_epoch_utc("2026-07-10 00:00:00"),
          "2026-07-10 00:00:00", "2026-07-11 00:00:00")
# The BST case the old suite never exercised: local midnight is 23:00Z the
# night BEFORE, exactly as handleTimelineDay computes via mktime. The same
# fixture rows must land 60 minutes LATER in local-day minutes.
BST_BOUNDS = (_epoch_utc("2026-07-09 23:00:00"),
              "2026-07-09 23:00:00", "2026-07-10 23:00:00")


def test_bst_bounds_shift_the_same_rows_by_an_hour(conn):
    spans = bare_plugin()._timeline_active_spans(HIST, conn, 99, "onoffstate", BST_BOUNDS)
    assert spans == [[510.0, 540.0], [1260.0, 1275.0]], \
        "a UTC row must map to LOCAL minutes via the epoch bound, not its clock face"


def test_two_clean_spans(conn):
    spans = bare_plugin()._timeline_active_spans(HIST, conn, 99, "onoffstate", BOUNDS)
    assert spans == [[450.0, 480.0], [1200.0, 1215.0]]


def test_carry_in_and_still_active_at_day_end(conn):
    spans = bare_plugin()._timeline_active_spans(HIST, conn, 77, "onoffstate", BOUNDS)
    # Carry-in ON from previous day -> open at minute 0, closes at 00:15 (15).
    # Turns on again at 23:50 (1430) and never closes -> runs to 1440.
    assert spans == [[0, 15.0], [1430.0, 1440]]
