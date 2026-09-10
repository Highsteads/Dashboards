#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_history_db.py
# Description: Contract tests for history_db.py — the SQL Logger artefact
#              filter, the column-type mapping, the two SQL dialects, and the
#              parameter rule that keeps the Postgres path injection-safe.
# Author:      CliveS & Claude Opus 5
# Date:        25-07-2026
# Version:     1.0

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Dashboards.indigoPlugin", "Contents", "Server Plugin"))

import history_db as H   # noqa: E402


# ── artefact filter ──────────────────────────────────────────────────
# The SQL Logger cannot ALTER a column whose logged type changes, so it adds a
# new one suffixed with an epoch and leaves the old one behind for good. 256 of
# them here across 41 of 268 devices, 17 on the Sigen inverter alone.

@pytest.mark.parametrize("name", [
    "batterysoc_1782308459229",       # the real one, straight off our DB
    "griddailyimportkwh_1782308459229",
    "temperature_1775461714",
    "indigo_id",                      # the device's own `id` state, renamed
    "indigo_id_1775461714",
    "id", "ts",                       # table plumbing
    "1779419337710",                  # bare internal numeric key
])
def test_artefacts_are_hidden(name):
    assert H.is_artefact(name) is True


@pytest.mark.parametrize("name", [
    "batterysoc",
    "batterysoc_ui",                  # a real UI-string variant, NOT débris
    "pvpowerwatts",
    "onoffstate",
    "hvacheaterison",
    "sensorvalue",
    "battery",
    "temperature_2",                  # too few digits to be an epoch
    "state_12345",                    # 5 digits — still not an epoch
])
def test_real_states_are_kept(name):
    assert H.is_artefact(name) is False


def test_the_epoch_threshold_is_six_digits():
    # Guards the regex boundary in both directions.
    assert H.is_artefact("x_12345") is False
    assert H.is_artefact("x_123456") is True


# ── type mapping ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("BOOL", "bool"), ("boolean", "bool"),
    ("INTEGER", "int"), ("bigint", "int"), ("int8", "int"),
    ("REAL", "float"), ("double precision", "float"), ("numeric", "float"),
    ("TEXT", "text"), ("varchar", "text"), ("", "text"), (None, "text"),
])
def test_type_mapping(raw, want):
    assert H.map_type(raw) == want


# ── dialects ─────────────────────────────────────────────────────────

def test_sqlite_dialect_fragments():
    db = H.HistoryDB(backend="sqlite")
    assert db.backend == "sqlite"
    # Single-quoted SQL string literals — the double-quoted form leant on
    # SQLite's deprecated DQS misfeature (a double-quoted token is an
    # IDENTIFIER that silently falls back to a string).
    assert db.epoch() == "CAST(strftime('%s', ts) AS INTEGER)"
    assert db.hour_of() == "strftime('%H', ts)"
    assert "datetime('now', '-24.0 hours')" == db.utc_now_minus(24)


def test_postgres_dialect_fragments():
    """Contract flipped in v1.1: `ts` is session-LOCAL on Postgres (the SQL
    Logger's DDL is `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, which Postgres
    fills with local wall-clock and SQLite with UTC), so a bare
    EXTRACT(EPOCH FROM ts) was an hour out for the eight months of BST. The
    fragments now re-attach the session zone first."""
    db = H.HistoryDB(backend="postgres")
    assert db.backend == "postgres"
    assert db.epoch() == "EXTRACT(EPOCH FROM (ts AT TIME ZONE current_setting('TimeZone')))::bigint"
    assert db.hour_of() == "to_char((ts AT TIME ZONE current_setting('TimeZone')) AT TIME ZONE 'UTC', 'HH24')"
    assert "interval '24.0 hours'" in db.utc_now_minus(24)


def test_backend_name_is_forgiving():
    for spelling in ("postgres", "PostgreSQL", "POSTGRES", "postgresql"):
        assert H.HistoryDB(backend=spelling).backend == "postgres"
    for spelling in ("sqlite", "SQLite", "", None, "something else"):
        assert H.HistoryDB(backend=spelling).backend == "sqlite"


def test_quote_strips_embedded_quotes():
    assert H.HistoryDB().quote('bad"name') == '"badname"'


# ── the Postgres parameter rule ──────────────────────────────────────
# Parameters are refused rather than escaped. An escaping routine is a thing to
# get wrong; a whitelist of two provably-safe shapes is not.

@pytest.mark.parametrize("bad", [
    "'; DROP TABLE device_history_1 --",
    "2026-07-25",                     # a date is not a full timestamp
    "batterysoc",
    "14a",
    "",
])
def test_unsafe_parameters_are_refused(bad):
    psql = H._Psql({})
    with pytest.raises(H.HistoryUnavailable):
        psql.run("SELECT ?", (bad,))


@pytest.mark.parametrize("good", ["2026-07-25 20:15:17", "14", "00", "2099545"])
def test_safe_parameter_shapes_pass_validation(good):
    # Validation happens before psql is invoked; reaching the binary lookup
    # (which fails on a machine with no psql) proves the parameter was accepted.
    psql = H._Psql({})
    try:
        psql.run("SELECT ?", (good,))
    except H.HistoryUnavailable as exc:
        assert "refusing to interpolate" not in str(exc)


def test_parameter_count_must_match():
    with pytest.raises(H.HistoryUnavailable):
        H._Psql({}).run("SELECT ? , ?", (1,))


def test_floats_and_bools_are_refused():
    for bad in (1.5, True, None, [1]):
        with pytest.raises(H.HistoryUnavailable):
            H._Psql({}).run("SELECT ?", (bad,))


# ── the cursor shim ──────────────────────────────────────────────────
# The plugin's history code was written against sqlite3 cursors and calls
# .fetchone()/.fetchall() in a dozen places; the shim keeps those working.

def test_rows_behaves_as_list_and_cursor():
    r = H._Rows([(1, "a"), (2, "b")])
    assert list(r) == [(1, "a"), (2, "b")]
    assert r.fetchone() == (1, "a")
    assert r.fetchall() == [(1, "a"), (2, "b")]
    assert len(r) == 2
    assert r[1] == (2, "b")


def test_empty_rows_fetchone_is_none():
    assert H._Rows([]).fetchone() is None
    assert H._Rows([]).fetchall() == []


# ── end to end against a real SQLite file ────────────────────────────

@pytest.fixture
def db(tmp_path):
    """A miniature history DB shaped exactly like the live one, artefacts and
    all — including the batterysoc / batterysoc_ui / batterysoc_<epoch> trio
    that the Graphs picker was offering."""
    path = tmp_path / "indigo_history.sqlite"
    con = sqlite3.connect(path)
    con.execute(
        'CREATE TABLE device_history_42 ('
        ' id INTEGER PRIMARY KEY, ts TIMESTAMP, '
        ' batterysoc REAL, batterysoc_ui TEXT, '
        ' batterysoc_1782308459229 REAL, indigo_id TEXT, onoffstate BOOL)')
    con.execute('CREATE TABLE device_history_7 (id INTEGER PRIMARY KEY, ts TIMESTAMP, temperature REAL)')
    con.execute('CREATE TABLE not_a_device (id INTEGER PRIMARY KEY)')
    con.execute("INSERT INTO device_history_42 (ts, batterysoc, onoffstate) "
                "VALUES ('2020-01-02 03:04:05', 91.5, 1)")
    con.commit()
    con.close()
    return H.HistoryDB(backend="sqlite", sqlite_path=str(path))


def test_columns_drop_the_artefacts(db):
    with db.connect() as c:
        names = db.column_names(c, 42)
    assert "batterysoc" in names
    assert "batterysoc_ui" in names          # a real variant, kept
    assert "onoffstate" in names
    assert "batterysoc_1782308459229" not in names
    assert "indigo_id" not in names
    assert "id" not in names and "ts" not in names


def test_columns_can_be_asked_for_everything(db):
    with db.connect() as c:
        allc = [x["name"] for x in db.columns(c, 42, include_artefacts=True)]
    assert "batterysoc_1782308459229" in allc
    assert "indigo_id" in allc
    assert "id" not in allc and "ts" not in allc   # plumbing still excluded


def test_columns_carry_their_type(db):
    with db.connect() as c:
        types = {x["name"]: x["type"] for x in db.columns(c, 42)}
    assert types["batterysoc"] == "float"
    assert types["onoffstate"] == "bool"
    assert types["batterysoc_ui"] == "text"


def test_device_tables_finds_only_history_tables(db):
    with db.connect() as c:
        assert sorted(db.device_tables(c)) == [7, 42]


def test_connection_is_read_only(db):
    with db.connect() as c:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("INSERT INTO device_history_7 (ts) VALUES ('2026-07-25 00:00:00')")


def test_check_reports_success(db):
    ok, detail = db.check()
    assert ok is True
    assert "SQLite" in detail


def test_missing_file_is_reported_not_raised_raw():
    db = H.HistoryDB(backend="sqlite", sqlite_path="/nowhere/nothing.sqlite")
    ok, detail = db.check()
    assert ok is False
    assert "SQL Logger database not found" in detail


def test_epoch_fragment_actually_runs(db):
    """The dialect fragment has to be valid SQL, not just the right string."""
    import calendar, datetime
    want = calendar.timegm(datetime.datetime(2020, 1, 2, 3, 4, 5).timetuple())
    with db.connect() as c:
        rows = c.execute(f'SELECT {db.epoch()} FROM device_history_42')
        # ts is UTC (measured across all 245 live tables, 25-Jul-2026), so the
        # epoch is a plain UTC conversion with no local-time correction.
        assert rows.fetchone()[0] == want


def test_utc_now_minus_fragment_actually_runs(db):
    with db.connect() as c:
        rows = c.execute(
            f'SELECT count(*) FROM device_history_42 WHERE ts >= {db.utc_now_minus(1)}')
        assert rows.fetchone()[0] == 0        # the 2020 row is far outside the window


# ── the timestamp convention differs by engine (v1.1) ───────────────
# The SQL Logger's DDL is `ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP` on both
# backends. SQLite fills that with UTC; PostgreSQL fills it with the session's
# LOCAL wall-clock. v1.0 treated both as UTC, so every Postgres timestamp was
# an hour out for the eight months of BST. Callers still pass UTC and read
# back true epochs / UTC hours — the translation is this module's job.

class _FakePsql(H._Psql):
    """A _Psql whose psql answers SHOW TimeZone from a canned value and
    records every SQL it would have run — no subprocess."""

    def __init__(self, zone="Europe/London"):
        super().__init__({})
        self.zone_answer = zone
        self.ran = []

    def run(self, sql, params=()):
        if sql == "SHOW TimeZone":
            return [(self.zone_answer,)]
        # Exercise the REAL parameter path, then capture instead of executing.
        for p in params:
            if isinstance(p, str) and not (H._SAFE_TS_RE.match(p) or H._SAFE_NUM_RE.match(p)):
                raise H.HistoryUnavailable("bad param")
        parts = sql.split("?")
        out = parts[0]
        for i, p in enumerate(params):
            if isinstance(p, str) and H._SAFE_TS_RE.match(p):
                p = self.utc_to_local(p)
            out += (str(int(p)) if isinstance(p, int) else f"'{p}'") + parts[i + 1]
        self.ran.append(out)
        return []


def test_pg_utc_param_is_rendered_in_the_session_zone():
    ps = _FakePsql("Europe/London")
    assert ps.utc_to_local("2026-07-01 12:00:00") == "2026-07-01 13:00:00"   # BST
    assert ps.utc_to_local("2026-01-15 12:00:00") == "2026-01-15 12:00:00"   # GMT
    ps.run('SELECT 1 FROM t WHERE ts >= ?', ("2026-07-01 12:00:00",))
    assert ps.ran == ["SELECT 1 FROM t WHERE ts >= '2026-07-01 13:00:00'"]


def test_pg_conn_ts_key_matches_the_column_convention():
    conn = H._Conn(H.POSTGRES, pg=_FakePsql("Europe/London"))
    assert conn.ts_key("2026-07-01 12:00:00") == "2026-07-01 13:00:00"
    sq = H._Conn(H.SQLITE, sqlite_conn=sqlite3.connect(":memory:"))
    assert sq.ts_key("2026-07-01 12:00:00") == "2026-07-01 12:00:00"


def test_pg_non_zoneinfo_session_zone_is_refused_not_silently_utc():
    # "localtime" is the case that matters and the one that caught us out: it
    # RESOLVES on Linux (Debian symlinks it into the zoneinfo tree) and raises
    # on macOS, so a zoneinfo-only guard passed on the Mac and failed in CI.
    # Either way it means the server's own clock, which this machine cannot
    # know, so the name is refused by name before zoneinfo is consulted.
    for zone in ("localtime", "local", "LocalTime", "NotAZone/Nope"):
        ps = _FakePsql(zone)
        with pytest.raises(H.HistoryUnavailable):
            ps.utc_to_local("2026-07-01 12:00:00")


def test_pg_fragments_reattach_the_session_zone():
    h = H.HistoryDB(backend="postgres")
    assert "AT TIME ZONE current_setting('TimeZone')" in h.epoch()
    assert "EXTRACT(EPOCH" in h.epoch()
    assert "AT TIME ZONE 'UTC'" in h.hour_of() and "HH24" in h.hour_of()
    assert h.utc_now_minus(6) == "((now() - interval '6.0 hours')::timestamp)"


def test_sqlite_fragments_are_unchanged():
    h = H.HistoryDB(backend="sqlite")
    assert h.epoch() == "CAST(strftime('%s', ts) AS INTEGER)"
    assert h.hour_of() == "strftime('%H', ts)"
    assert h.utc_now_minus(6) == "datetime('now', '-6.0 hours')"


def test_as_real_survives_a_postgres_boolean():
    pg = H.HistoryDB(backend="postgres")
    assert pg.as_real('"onoffstate"', "bool") == '(CASE WHEN "onoffstate" THEN 1.0 ELSE 0.0 END)'
    assert pg.as_real('"temp"', "float") == 'CAST("temp" AS DOUBLE PRECISION)'
    assert H.HistoryDB(backend="sqlite").as_real('"x"', "bool") == 'CAST("x" AS REAL)'


def test_pg_boolean_cells_become_ints(monkeypatch):
    """psql prints t / f for a boolean; the SQLite backend stores 1 / 0 and
    every caller was written for that."""
    ps = H._Psql({})
    class _R:
        returncode = 0
        stdout = "t,f,,7,2.5,hello\n"
        stderr = ""
    monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(H._Psql, "_binary", staticmethod(lambda: "/bin/echo"))
    assert ps.run("SELECT 1") == [(1, 0, None, 7, 2.5, "hello")]
