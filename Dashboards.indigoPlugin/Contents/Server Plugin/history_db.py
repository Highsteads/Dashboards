#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    history_db.py
# Description: Read-only access to Indigo's SQL Logger history, over either
#              SQLite (the default) or PostgreSQL. Also the single place that
#              decides which columns of a device_history_<id> table are real
#              states and which are SQL Logger débris.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.2
#
# The two-backend idea and the artefact regex are borrowed from the Domio
# plugin's history_db.py (Simon's, com.simons-plugins.domio) — see the repo
# CLAUDE.md harvest note.
#
# THE TIMESTAMP CONVENTION DIFFERS BY ENGINE (settled 02-Sep-2026, v1.1).
# The SQL Logger creates `ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP` on BOTH
# backends (sqlfactory_sqlite.py:93, sqlfactory_pg.py:118, read from the
# shipped plugin). SQLite's CURRENT_TIMESTAMP is UTC; PostgreSQL's, cast into
# a `timestamp without time zone`, is the session's LOCAL wall-clock. So
# Domio's "ts is local" correction is right for Postgres and wrong for SQLite,
# and the 25-Jul-2026 measurement here (newest row +1 s behind UTC, +3601 s
# behind local, all 245 tables) was right for SQLite and said nothing about
# Postgres. v1.0 applied the SQLite answer to both, which put every Postgres
# timestamp an hour out for the eight months of BST.
#
# The contract for callers is unchanged: every timestamp PARAMETER they pass
# is UTC, every epoch they read back is a true epoch, every hour_of() is a UTC
# hour, and utc_now_minus() bounds a window in UTC. This module owns the
# translation: on Postgres the parameters are converted into the server's
# session zone before interpolation, and the dialect fragments convert `ts`
# back out of it. Nothing outside this file knows which convention it is on.

import glob
import os
import re
import subprocess
from datetime import datetime, timezone

# The SQL Logger cannot ALTER a column whose logged type changes, so it creates
# a NEW one suffixed with an epoch — "batterysoc_1782308459229" beside the live
# "batterysoc" — and never removes the old one. It also renames a device's own
# `id` state to `indigo_id` to dodge the table's primary key. All of it is dead
# weight in a state picker: 256 such columns across 41 of 268 devices here, 17
# on the Sigen inverter alone, which is the most-charted device in the house.
_ARTEFACT_RE = re.compile(r"_\d{6,}$")

SQLITE = "sqlite"
POSTGRES = "postgres"

# The only string shapes ever interpolated into Postgres SQL: a SQL Logger
# timestamp, or a short run of digits (a two-digit hour, a rowid rendered as
# text). Neither can carry a quote, a semicolon or a comment marker, so the
# substitution in _Psql.run cannot be turned into an injection. Anything else
# is refused rather than escaped — an escaping routine is a thing to get wrong.
_SAFE_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_SAFE_NUM_RE = re.compile(r"^\d{1,20}$")


class _Rows(list):
    """A result list that also answers the DB-API cursor calls.

    The plugin's history queries were written against sqlite3 cursors and use
    `.fetchone()` / `.fetchall()` in a dozen places. Returning this instead of
    a bare list means the backend swap needed no changes at those call sites,
    and iteration still works.
    """

    def fetchone(self):
        return self[0] if self else None

    def fetchall(self):
        return list(self)


def is_artefact(name):
    """True for a column that is SQL Logger débris rather than a real state."""
    if name in ("id", "ts", "indigo_id"):
        return True
    if _ARTEFACT_RE.search(name):
        return True
    # Defensive: bare internal numeric keys (e.g. "1779419337710").
    return name.lstrip("-").isdigit()


def map_type(raw):
    """Normalise a backend column type to bool / int / float / text.

    The page uses this to draw a boolean as a step rather than sloping a
    straight line between 0 and 1, which is what an on/off sensor looked like
    before.
    """
    t = (raw or "").lower()
    if t in ("bool", "boolean"):
        return "bool"
    if t in ("integer", "int", "bigint", "smallint", "int4", "int8"):
        return "int"
    if t in ("real", "float", "double precision", "numeric", "decimal", "float8"):
        return "float"
    return "text"


class HistoryUnavailable(Exception):
    """Raised when the configured backend cannot be reached, with a message
    that is safe and useful to show the user."""


class _Conn:
    """Uniform read-only cursor over either backend.

    `execute(sql, params)` returns a list of tuples. Identifiers are ALWAYS
    validated by the caller against the live column list before interpolation
    (the SQLite path has always done this); parameters are restricted to ints
    and strict `YYYY-MM-DD HH:MM:SS` timestamps so the Postgres path can
    substitute them without an escaping routine to get wrong.
    """

    def __init__(self, backend, sqlite_conn=None, pg=None):
        self.backend = backend
        self._sq = sqlite_conn
        self._pg = pg

    def ts_key(self, ts_utc):
        """A UTC `YYYY-MM-DD HH:MM:SS` rendered in the convention this
        backend stores `ts` in, for a Python-side comparison against a `ts`
        value read back (the rowid binary search does this). Identity on
        SQLite; the session-local rendering on Postgres."""
        if self.backend == SQLITE or self._pg is None:
            return ts_utc
        return self._pg.utc_to_local(ts_utc)

    def execute(self, sql, params=()):
        if self.backend == SQLITE:
            return _Rows(self._sq.execute(sql, params).fetchall())
        return _Rows(self._pg.run(sql, params))

    def close(self):
        if self._sq is not None:
            try:
                self._sq.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Psql:
    """Postgres access through the psql CLI.

    Deliberately no psycopg2: adding it to requirements.txt would make every
    SQLite user install a Postgres driver they will never load, and the plugin
    only ever READS a handful of columns.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._zone = None

    # ---- the session zone -------------------------------------------
    def session_zone(self):
        """The name of the zone the server writes `ts` in — its session
        TimeZone, which the SQL Logger's own session shares unless someone
        set a per-role override. Read once per _Psql and cached."""
        if self._zone is None:
            rows = self.run("SHOW TimeZone")
            self._zone = str(rows[0][0]) if rows and rows[0] and rows[0][0] else "UTC"
        return self._zone

    def utc_to_local(self, ts_utc):
        """UTC `YYYY-MM-DD HH:MM:SS` -> the same instant as a naive local
        string in the session zone. zoneinfo (stdlib) only — never a silent
        fall-through to UTC, which is the fault this exists to remove."""
        try:
            dt = datetime.strptime(ts_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HistoryUnavailable(f"not a UTC timestamp: {ts_utc!r}")
        zone = self.session_zone()
        # "localtime"/"local" mean "whatever the SERVER's clock is set to", and
        # the server may not be this machine. On Linux they are ALSO resolvable
        # names — Debian ships /usr/share/zoneinfo/localtime as a symlink to
        # /etc/localtime — so ZoneInfo() answers with the CLIENT's zone and the
        # wrong answer arrives looking like a right one. On macOS the same call
        # raises. That split is why this passed here and failed in CI, and the
        # CI machine was the one telling the truth: refuse the name outright.
        if zone.strip().lower() in ("localtime", "local"):
            raise HistoryUnavailable(
                f"the Postgres session TimeZone is {zone!r}, which names the server's own "
                f"clock rather than a zone — set TimeZone to an IANA name (e.g. 'Europe/London')")
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(zone)
        except Exception:
            raise HistoryUnavailable(
                f"the PostgreSQL session TimeZone {zone!r} is not a zoneinfo name — "
                f"set it to an IANA zone (e.g. Europe/London) so history timestamps "
                f"can be translated")
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _binary():
        # The plugin host's PATH omits Homebrew and Postgres.app, so an absolute
        # path is required — see the subprocess rule in the global CLAUDE.md.
        cand = "/Applications/Postgres.app/Contents/Versions/latest/bin/psql"
        if os.path.exists(cand):
            return cand
        found = sorted(glob.glob("/Applications/Postgres.app/Contents/Versions/*/bin/psql"))
        if found:
            return found[-1]
        for p in ("/opt/homebrew/bin/psql", "/usr/local/bin/psql", "/usr/bin/psql"):
            if os.path.exists(p):
                return p
        raise HistoryUnavailable(
            "psql was not found. Install Postgres.app or the postgresql client, "
            "or set the history backend back to SQLite.")

    def run(self, sql, params=()):
        for p in params:
            if isinstance(p, bool) or not isinstance(p, (int, str)):
                raise HistoryUnavailable(f"unsupported query parameter type: {type(p).__name__}")
            if isinstance(p, str) and not (_SAFE_TS_RE.match(p) or _SAFE_NUM_RE.match(p)):
                raise HistoryUnavailable(
                    f"refusing to interpolate an unrecognised parameter: {p!r}")
        if params:
            parts = sql.split("?")
            if len(parts) != len(params) + 1:
                raise HistoryUnavailable("parameter count does not match the query")
            sql = parts[0]
            for i, p in enumerate(params):
                if isinstance(p, str) and _SAFE_TS_RE.match(p):
                    # Callers pass UTC; the column holds session-local time.
                    p = self.utc_to_local(p)
                sql += (str(int(p)) if isinstance(p, int) else f"'{p}'") + parts[i + 1]
        cmd = [
            self._binary(),
            # -X: never read ~/.psqlrc — a user's rc can flip output formatting
            # (\pset, \timing) and corrupt every parsed row. -w: never prompt
            # for a password — with none available psql would sit waiting on
            # stdin until the 30 s timeout on every single query.
            "-X", "-w",
            "-h", str(self.cfg.get("host") or "127.0.0.1"),
            "-p", str(self.cfg.get("port") or 5432),
            "-U", str(self.cfg.get("user") or "postgres"),
            "-d", str(self.cfg.get("database") or "indigo_history"),
            # --csv (psql 12+) quotes embedded tabs/newlines properly — the
            # old tab-separated parse silently corrupted any text value
            # containing either.
            "--csv", "--tuples-only", "--pset", "null=", "-c", sql,
        ]
        env = os.environ.copy()
        if self.cfg.get("password"):
            env["PGPASSWORD"] = str(self.cfg["password"])
        env.setdefault("PGCONNECT_TIMEOUT", "5")
        try:
            # 10 s, not 30: this subprocess runs on the plugin's SINGLE
            # dispatch thread, so its worst case freezes every handler and
            # callback for the duration. A healthy indexed Postgres answers
            # these queries in milliseconds; ten seconds already means
            # something is wrong, and thirty tripled the damage.
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        except subprocess.TimeoutExpired:
            raise HistoryUnavailable("the PostgreSQL query timed out after 10s")
        except OSError as exc:
            raise HistoryUnavailable(f"could not run psql: {exc}")
        if r.returncode != 0:
            raise HistoryUnavailable(f"PostgreSQL error: {(r.stderr or '').strip()[:300]}")

        def _cell(c):
            # Parity with the SQLite backend, which returns NATIVE ints and
            # floats — psql emits text, and stringly-typed numbers made the
            # two backends disagree the moment a caller did arithmetic.
            if c == "":
                return None
            # psql renders a boolean column as the single letters t / f. The
            # SQLite backend stores the same state as 1 / 0, and every caller
            # (timeline lanes, the graph cast, the insights) was written for
            # that — a "t" read as 0 through _as_bool01 and every lane came
            # back empty (v1.1).
            if c == "t":
                return 1
            if c == "f":
                return 0
            try:
                return int(c)
            except ValueError:
                pass
            try:
                f = float(c)
            except ValueError:
                return c
            # 'nan' and 'inf' parse as floats and then json.dumps emits bare
            # NaN/Infinity tokens, which no browser will parse. Unknown.
            import math as _m
            return f if _m.isfinite(f) else None
        import csv as _csv
        import io as _io
        rows = []
        for rec in _csv.reader(_io.StringIO(r.stdout or "")):
            if rec:
                rows.append(tuple(_cell(c) for c in rec))
        return rows


class HistoryDB:
    """The SQL Logger history, whichever backend it lives in.

    Callers get a connection plus the few SQL fragments that differ between the
    two dialects, so the query logic itself stays in one place.
    """

    def __init__(self, backend=SQLITE, sqlite_path=None, pg_config=None, logger=None):
        self.backend = POSTGRES if str(backend).lower().startswith("post") else SQLITE
        self.sqlite_path = sqlite_path
        self.pg_config = pg_config or {}
        self.logger = logger

    # ---- availability -------------------------------------------------
    def check(self):
        """Return (ok, message). Never raises — for the Test Connection menu."""
        try:
            with self.connect() as c:
                if self.backend == SQLITE:
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
                    return True, f"SQLite history at {self.sqlite_path}"
                c.execute("SELECT 1")
                cfg = self.pg_config
                return True, (f"PostgreSQL history at {cfg.get('host')}:{cfg.get('port')}"
                              f"/{cfg.get('database')}")
        except Exception as exc:
            return False, str(exc)

    def connect(self):
        if self.backend == SQLITE:
            import sqlite3
            if not self.sqlite_path or not os.path.isfile(self.sqlite_path):
                raise HistoryUnavailable(
                    "SQL Logger database not found — is the SQL Logger plugin enabled?")
            # Read-only URI AND query_only: the first stops us writing, the
            # second stops a stray statement trying. The history DB is
            # journal_mode=delete, so a write lock here would stall the logger.
            # 1.5 s busy wait, not 5: this runs on the plugin's single dispatch
            # thread, and under journal_mode=delete a reader is locked out for
            # the whole of the logger's commit. Better to answer "busy" fast
            # than freeze every handler for five seconds waiting.
            conn = sqlite3.connect(f"file:{self.sqlite_path}?mode=ro", uri=True, timeout=1.5)
            conn.execute("PRAGMA query_only = ON")
            return _Conn(SQLITE, sqlite_conn=conn)
        return _Conn(POSTGRES, pg=_Psql(self.pg_config))

    # ---- dialect fragments --------------------------------------------
    # On Postgres `ts` is a naive session-local timestamp, so every fragment
    # first re-attaches the session zone (`ts AT TIME ZONE current_setting(
    # 'TimeZone')` yields the true instant) and works from there. On SQLite
    # `ts` is already UTC.
    _PG_TS_INSTANT = "({col} AT TIME ZONE current_setting('TimeZone'))"

    def epoch(self, col="ts"):
        """SQL for the true (UTC) epoch seconds of a timestamp column."""
        if self.backend == SQLITE:
            return f"CAST(strftime('%s', {col}) AS INTEGER)"
        return f"EXTRACT(EPOCH FROM {self._PG_TS_INSTANT.format(col=col)})::bigint"

    def hour_of(self, col="ts"):
        """SQL for the two-digit UTC hour of a timestamp column."""
        if self.backend == SQLITE:
            return f"strftime('%H', {col})"
        return f"to_char({self._PG_TS_INSTANT.format(col=col)} AT TIME ZONE 'UTC', 'HH24')"

    def utc_now_minus(self, hours):
        """SQL for 'now minus N hours' in the column's own convention — the
        WHERE bound for a trailing window."""
        if self.backend == SQLITE:
            return f"datetime('now', '-{float(hours)} hours')"
        # now() is timestamptz; the cast to a plain timestamp renders it in the
        # session zone, which is what `ts` holds.
        return f"((now() - interval '{float(hours)} hours')::timestamp)"

    def as_real(self, col, col_type=None):
        """SQL casting a state column to a float for avg/min/max. On Postgres
        a boolean column cannot be cast to a number directly ("cannot cast
        type boolean to real"), so it goes through CASE."""
        if self.backend == SQLITE:
            return f"CAST({col} AS REAL)"
        if col_type == "bool":
            return f"(CASE WHEN {col} THEN 1.0 ELSE 0.0 END)"
        return f"CAST({col} AS DOUBLE PRECISION)"

    def quote(self, ident):
        """Double-quote an identifier. Callers must already have validated it
        against the live column list — this is belt, not braces."""
        return '"' + str(ident).replace('"', '') + '"'

    # ---- schema --------------------------------------------------------
    def device_tables(self, conn):
        """Device IDs that have a history table."""
        if self.backend == SQLITE:
            sql = ("SELECT name FROM sqlite_master WHERE type='table' "
                   "AND name LIKE 'device_history_%'")
        else:
            sql = ("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                   "AND tablename LIKE 'device_history_%'")
        out = []
        for (name,) in conn.execute(sql):
            tail = str(name).split("device_history_")[-1]
            if tail.isdigit():
                out.append(int(tail))
        return out

    def columns(self, conn, dev_id, include_artefacts=False):
        """Real state columns for a device, as [{"name", "type"}].

        Drops SQL Logger débris unless asked not to — see is_artefact.
        """
        table = f"device_history_{int(dev_id)}"
        if self.backend == SQLITE:
            rows = conn.execute(f'PRAGMA table_info({self.quote(table)})')
            pairs = [(r[1], r[2]) for r in rows]
        else:
            rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='" + table + "'")
            pairs = [(r[0], r[1]) for r in rows]
        out = []
        for name, raw in pairs:
            if not include_artefacts and is_artefact(name):
                continue
            if include_artefacts and name in ("id", "ts"):
                continue
            out.append({"name": name, "type": map_type(raw)})
        return out

    def column_names(self, conn, dev_id):
        """Just the real state names — the common case."""
        return [c["name"] for c in self.columns(conn, dev_id)]
