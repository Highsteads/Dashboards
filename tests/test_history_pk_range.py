#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_pk_range.py
# Description: Contract test for the PK-range window helpers — the mechanism
#              that keeps a history read from full-scanning the SQL Logger DB
#              and locking the logger out of its own writes.
#
#              WHY THIS MATTERS MORE THAN IT LOOKS
#              `indigo_history.sqlite` has NO index on ts and runs
#              journal_mode=delete, so a ts-filtered query scans the whole
#              table AND holds a read lock for the duration. Measured live on
#              the 2 GB estate DB: one Timeline page load ts-scanning its 40
#              lane tables held the lock for 7.6 SECONDS. Everything in this
#              plugin — every other endpoint, every device callback — shares
#              one dispatch thread, so that is a 7.6-second freeze, and the
#              SQL Logger cannot write for the same period.
#
#              The subtle one is test_min_max_split. SQLite rewrites a LONE
#              min()/max() over an INTEGER PRIMARY KEY into a B-tree seek, but
#              asking for BOTH in one statement defeats it and the planner
#              falls back to SCAN. Measured on a 1.5M-row table: combined
#              96 ms (SCAN), each alone 0.01 ms (SEARCH). So the helper
#              written to AVOID full scans opened with one, and every caller
#              paid the cost it existed to remove. Anyone tidying those two
#              statements back into one would silently restore the fault, so
#              the test asserts the query PLAN, not just the answer.
# Author:      CliveS & Claude Opus 5
# Date:        29-07-2026
# Version:     1.0

import sqlite3
import pytest
from conftest import bare_plugin


TABLE = "device_history_77"


@pytest.fixture()
def db(tmp_path):
    """A table whose ts is monotone in id, as the SQL Logger appends it:
    one row a minute for 300 minutes from 2026-07-27 00:00."""
    path = tmp_path / "h.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute(f'CREATE TABLE "{TABLE}" (id INTEGER PRIMARY KEY, ts TEXT, v TEXT)')
    for i in range(300):
        hh, mm = divmod(i, 60)
        conn.execute(f'INSERT INTO "{TABLE}" (ts, v) VALUES (?, ?)',
                     (f"2026-07-27 {hh:02d}:{mm:02d}:00", str(i)))
    conn.commit()
    conn.close()
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def test_rowid_for_ts_finds_the_boundary(db):
    p = bare_plugin()
    # Row i has ts 00:00 + i minutes, and ids start at 1 — so the first row
    # at or after 02:00 (minute 120) is id 121.
    assert p._rowid_for_ts(db, TABLE, "2026-07-27 02:00:00") == 121
    # A timestamp before every row gives the very first id.
    assert p._rowid_for_ts(db, TABLE, "2026-01-01 00:00:00") == 1
    # After every row: max+1, so `id < bound` still selects the whole table
    # rather than excluding the last row.
    assert p._rowid_for_ts(db, TABLE, "2027-01-01 00:00:00") == 301


def test_empty_table_returns_none(db):
    p = bare_plugin()
    db.close()
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "device_history_1" (id INTEGER PRIMARY KEY, ts TEXT)')
    assert p._rowid_for_ts(conn, "device_history_1", "2026-07-27 00:00:00") is None


def test_pk_range_returns_the_same_rows_as_a_plain_ts_scan(db):
    """The whole point: faster, and identical. A window that is faster but
    drops a row is worse than the scan it replaces."""
    p = bare_plugin()
    start, end = "2026-07-27 01:00:00", "2026-07-27 03:00:00"
    scan = db.execute(
        f'SELECT count(*) FROM "{TABLE}" WHERE ts >= ? AND ts < ?',
        (start, end)).fetchone()[0]
    lo = p._rowid_for_ts(db, TABLE, start)
    hi = p._rowid_for_ts(db, TABLE, end)
    ranged = db.execute(
        f'SELECT count(*) FROM "{TABLE}" WHERE ts >= ? AND ts < ? AND id >= ? AND id < ?',
        (start, end, lo, hi)).fetchone()[0]
    assert scan == 120           # 01:00 inclusive to 03:00 exclusive
    assert ranged == scan


def test_min_max_split(db):
    """min() and max() must be SEPARATE statements.

    Combining them defeats SQLite's rowid optimisation and full-scans the
    table — the exact thing _rowid_for_ts exists to avoid. Asserted on the
    query PLAN because both forms return the same numbers, so an answer-only
    test would happily pass while the plugin scanned a 1.5M-row table.
    """
    def plan(sql):
        return " ".join(r[-1] for r in db.execute("EXPLAIN QUERY PLAN " + sql))

    assert "SCAN" in plan(f'SELECT min(id), max(id) FROM "{TABLE}"'), \
        "combined min/max is expected to SCAN — if SQLite ever learns to " \
        "optimise it, this test should be revisited, not deleted"
    assert "SEARCH" in plan(f'SELECT min(id) FROM "{TABLE}"')
    assert "SEARCH" in plan(f'SELECT max(id) FROM "{TABLE}"')

    # And the shipped helper must not reintroduce the combined form. Comments
    # are stripped first — the explanation of this very trap quotes the bad
    # form, and matching prose would fail on the fix rather than the fault.
    import inspect
    code = "\n".join(
        line for line in inspect.getsource(bare_plugin()._rowid_for_ts).splitlines()
        if not line.strip().startswith("#"))
    assert "min(id), max(id)" not in code, \
        "_rowid_for_ts must fetch min(id) and max(id) in separate statements"


def test_pk_clause_shape():
    p = bare_plugin()
    assert p._pk_clause(None, None) == ("", [])
    sql, args = p._pk_clause(10, None)
    assert sql == " AND id >= ?" and args == [10]
    sql, args = p._pk_clause(10, 20)
    assert sql == " AND id >= ? AND id < ?" and args == [10, 20]


def test_pk_window_runs_on_both_backends_and_never_raises(db):
    """Contract flipped in v2.95.1: Postgres is PK-ranged too. The old
    exemption rested on "Postgres indexes ts properly" — it does not; the SQL
    Logger creates no ts index on either engine, so every Postgres history
    query was a sequential scan inside a 10 s-capped psql subprocess on the
    plugin's one dispatch thread. The probes are PK seeks on both. And a
    probe failure must still degrade to the slow-but-correct path rather than
    costing the caller its data."""
    p = bare_plugin()

    class FakeHist:
        backend = "postgres"
    # A bare sqlite3 connection stands in for either engine here: the probe
    # SQL is identical, and with no ts_key on the connection the bound stays
    # UTC, which is what the fixture's rows are.
    assert p._pk_window(FakeHist(), db, TABLE, "2026-07-27 01:00:00") == (61, None)

    class SqliteHist:
        backend = "sqlite"

    class Exploding:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("no such table")
    assert p._pk_window(SqliteHist(), Exploding(), TABLE, "2026-07-27 01:00:00") == (None, None)
