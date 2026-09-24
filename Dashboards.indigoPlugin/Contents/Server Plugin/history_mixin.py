#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    history_mixin.py
# Description: Everything that reads the SQL Logger history database: the
#              Graphs page's series and state lists, the Timeline page's day
#              replay, the per-string solar hours, and the primary-key window
#              helpers that keep every one of those queries PK-ranged (the
#              database has no ts index; a ts scan wedged the web server for
#              minutes on 15-Jul-2026). Split out of plugin.py in v3.30.0;
#              Plugin inherits it. The cache lifetimes (HISTORY_TTL and the
#              rest) stay on Plugin beside the off-path pool they belong to.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import os
import re
import sys as _sys
from datetime import datetime, timedelta, timezone

try:
    import indigo
except ImportError:
    pass
try:
    import history_db as _history_db
except ImportError:
    _history_db = None

# Optional PostgreSQL backend credentials, per key so one missing key never
# blanks the others. plugin.py has already put the Perceptive Automation
# folder on sys.path; it is repeated here so this module stands on its own.
_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import HISTORY_PG_HOST
except ImportError:
    HISTORY_PG_HOST = ""
try:
    from IndigoSecrets import HISTORY_PG_PORT
except ImportError:
    HISTORY_PG_PORT = ""
try:
    from IndigoSecrets import HISTORY_PG_USER
except ImportError:
    HISTORY_PG_USER = ""
try:
    from IndigoSecrets import HISTORY_PG_PASSWORD
except ImportError:
    HISTORY_PG_PASSWORD = ""
try:
    from IndigoSecrets import HISTORY_PG_DATABASE
except ImportError:
    HISTORY_PG_DATABASE = ""

# Upper bound on one plausible PV string's instantaneous watts. Not a display
# clamp — a filter on what the SQL Logger already holds. SigenEnergyManager
# read the inverter's per-string CURRENT as unsigned until v5.84.0, so a
# string at its dawn or dusk zero-crossing logged 655.3 A (65534 raw = -2 as
# S16) and V*I put up to 219,667 W on a 4.275 kWp string. That is in this
# database on 21 days from 13-08-2026 and cannot be undone — rows are never
# rewritten — so the READER has to reject it. One such sample lifted an hour's
# mean by ~2 kW and took one day's South total from 9.8 kWh to 219.8 kWh.
#
# 15 kW sits in a measured gap, not a guessed one: across 383k logged rows the
# largest GENUINE per-string sample is 4,705 W and the smallest WRAPPED one is
# 32,832 W (the dusk figure falls with the string voltage, so a cap set by the
# 200 kW headline would miss the low-voltage end — 45,416 W at 69 V did slip a
# 50 kW cap). Filtering on watts rather than the current also matters: 97 of
# the bad rows have no current logged beside them, the SQL Logger writing only
# what changed. No residential string reaches 15 kW.
PV_STRING_SANE_MAX_W = 15000


class HistoryMixin:
    def _history_db_path(self):
        base = indigo.server.getInstallFolderPath()
        return os.path.join(base, "Logs", "indigo_history.sqlite")

    def _history(self):
        """The SQL Logger history, on whichever backend is configured.

        SQLite by default. A user whose SQL Logger writes to PostgreSQL sets
        the backend in Configure; credentials come from IndigoSecrets.py first
        and fall back to the dialog, per the secrets policy.
        """
        if _history_db is None:
            raise ValueError("history_db.py is missing from the plugin bundle")
        # getattr, not attribute access — this has to work before the prefs
        # dict exists (a never-configured install, and the contract tests).
        prefs = getattr(self, "pluginPrefs", None) or {}
        backend = str(prefs.get("historyBackend") or "sqlite").strip().lower()

        def _pick(secret, pref_key, default=""):
            v = secret or prefs.get(pref_key) or default
            return str(v).strip()

        port = _pick(HISTORY_PG_PORT, "pgPort", "5432")
        try:
            port = int(port)
        except (TypeError, ValueError):
            # Guard the coercion — a blank or non-numeric port must not kill
            # the page, it should fall back and say so.
            lg = getattr(self, "logger", None)
            if lg:
                lg.warning(f"[History] pgPort {port!r} is not a number — using 5432")
            port = 5432
        return _history_db.HistoryDB(
            backend=backend,
            sqlite_path=self._history_db_path(),
            pg_config={
                "host":     _pick(HISTORY_PG_HOST, "pgHost", "127.0.0.1"),
                "port":     port,
                "user":     _pick(HISTORY_PG_USER, "pgUser", "postgres"),
                "password": _pick(HISTORY_PG_PASSWORD, "pgPassword"),
                "database": _pick(HISTORY_PG_DATABASE, "pgDatabase", "indigo_history"),
            },
            logger=getattr(self, "logger", None),
        )

    def _history_query(self, params):
        """Shared core for the Bearer endpoint and the guest passthrough.
        params: {action: "states"|"series", deviceId, state?, hours?, maxPoints?}
        Returns a JSON-able dict; raises ValueError with a friendly message."""
        try:
            dev_id = int(params.get("deviceId") or 0)
        except (ValueError, TypeError):
            raise ValueError("deviceId must be an integer")
        if dev_id <= 0:
            raise ValueError("deviceId required")

        hist = self._history()
        table = hist.quote(f"device_history_{dev_id}")
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            # Real states only. The SQL Logger leaves an epoch-suffixed copy of
            # a column behind whenever a logged state changes type, so the
            # picker used to offer "batterysoc" alongside a dead
            # "batterysoc_1782308459229" — 17 such on the Sigen inverter alone.
            cols = hist.columns(conn, dev_id)
            if not cols:
                raise ValueError(f"no history recorded for device {dev_id}")
            by_name = {c["name"]: c for c in cols}

            if (params.get("action") or "series") == "states":
                # count/min/max with no ts index is a FULL TABLE SCAN — on the
                # multi-million-row inverter table that is a multi-second read
                # lock against the logger, fired from the Graphs state picker.
                # ts is monotone in id, so the PK endpoints answer first/last
                # in two B-tree seeks; the row count becomes the id-span
                # estimate (display-only, slightly high across rowid gaps).
                try:
                    first = conn.execute(
                        f'SELECT id, ts FROM {table} ORDER BY id LIMIT 1')[0]
                    last = conn.execute(
                        f'SELECT id, ts FROM {table} ORDER BY id DESC LIMIT 1')[0]
                    rows_est = int(last[0]) - int(first[0]) + 1
                    first_ts, last_ts = first[1], last[1]
                except (IndexError, TypeError, ValueError):
                    rows_est, first_ts, last_ts = 0, "", ""
                return {"ok": True, "deviceId": dev_id,
                        "states": [c["name"] for c in cols],
                        # Types let the page step a boolean instead of sloping
                        # a line between 0 and 1.
                        "types": {c["name"]: c["type"] for c in cols},
                        "backend": hist.backend,
                        "rows": rows_est, "firstTs": first_ts, "lastTs": last_ts}

            requested = str(params.get("state") or "").strip().lower()
            requested = re.sub(r"[^a-z0-9_]", "", requested)
            if requested not in by_name:
                raise ValueError(f"state {requested!r} not recorded for device {dev_id}")
            col = hist.quote(requested)
            try:
                hours = min(2160.0, max(0.25, float(params.get("hours") or 24)))
            except (ValueError, TypeError):
                hours = 24.0
            try:
                max_points = min(1000, max(20, int(params.get("maxPoints") or 240)))
            except (ValueError, TypeError):
                max_points = 240
            bucket = max(60, int(hours * 3600 / max_points))

            # PK-range the window before touching it. The ts filter stays as
            # the correctness boundary; the rowid bound is what stops the
            # query full-scanning a multi-million-row table and locking the
            # SQL Logger out of its own writes (see _pk_window).
            cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
                      - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            lo, _hi = self._pk_window(hist, conn, f"device_history_{dev_id}", cutoff)
            pk_sql, pk_args = self._pk_clause(lo, None)

            # `requested` is guaranteed to be an existing column name (checked
            # against the live column list above), so interpolating it is
            # injection-safe. Same for the bucket size, which is an int.
            num = hist.as_real(col, by_name[requested]["type"])
            rows = conn.execute(
                f'SELECT ({hist.epoch()} / {bucket}) * {bucket} AS bucket, '
                f'       avg({num}), '
                f'       min({num}), '
                f'       max({num}), count(*) '
                f'FROM {table} '
                f'WHERE ts >= {hist.utc_now_minus(hours)} '
                f"  AND {col} IS NOT NULL AND CAST({col} AS TEXT) != '' "
                f'{pk_sql} '
                f'GROUP BY bucket ORDER BY bucket', tuple(pk_args))
            def _f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            return {"ok": True, "deviceId": dev_id, "state": requested,
                    "type": by_name[requested]["type"], "backend": hist.backend,
                    "hours": hours, "bucketSeconds": bucket,
                    "points": [{"t": int(r[0]), "avg": _f(r[1]), "min": _f(r[2]),
                                "max": _f(r[3]), "n": int(r[4])} for r in rows]}
        finally:
            conn.close()

    def handleHistoryQuery(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/historyQuery/
        Body: {"action": "states"|"series", "deviceId": N, "state": "...",
        "hours": N, "maxPoints": N}. Bearer-authenticated by IWS."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        params, _reply = self._request_body(action, refuse_reflector=False)
        if _reply:
            return _reply
        # Off the dispatch path (v3.20.0). Measured 18-09-2026 with the
        # parameters the Graphs page actually sends — action=series,
        # maxPoints=240, the 720 h chip, against the biggest history table
        # (4.0 M rows): 5.2-6.1 SECONDS on every call, uncached. Three and a
        # half times what timelineDay cost before 3.19.0, and one click reaches
        # it. The SQL is not at fault: it is PK-bounded through _pk_window and
        # buckets server-side, so SQLite returns 240 rows and not a million.
        # The time is SQLite scanning ~1.3 M rows in that id range with no
        # index to help, which is inherent — so the fix is where it runs.
        #
        # The guest passthrough at /guest/history uses the same key and
        # producer (v3.27.0), with a longer wait: it runs on the :8177 proxy's
        # own threads, so waiting there holds up nothing else.
        try:
            dev_id = int(params.get("deviceId") or 0)
        except (ValueError, TypeError):
            dev_id = 0
        if dev_id <= 0:
            # Checked HERE because it is free, so a malformed request is a 400
            # the page reports rather than something a worker discovers.
            return self._evo_reply({"ok": False, "error": "deviceId required"},
                                   status=400)

        key = self._history_key(params)
        state, payload = self._offpath_get(key, lambda: self._history_producer(params),
                                           self.HISTORY_TTL, wait=self.HISTORY_WAIT)
        if state == "fresh":
            # The producer separates the two failure kinds EXPLICITLY rather
            # than leaving the handler to guess one from the text of an
            # exception — which is exactly how timelineDay's bad-date path came
            # to answer 500 while its test passed.
            if payload.get("client_error"):
                return self._evo_reply({"ok": False, "error": payload["client_error"]},
                                       status=400)
            return self._evo_reply(payload["result"])
        if state == "failed":
            self.logger.error(f"[History] query failed: {payload}")
            return self._evo_reply({"ok": False, "error": payload}, status=500)
        return self._evo_reply(
            {"ok": False, "pending": True,
             "error": "the chart is still being built — try again shortly"},
            status=503)

    @staticmethod
    def _history_key(params):
        """Cache key for one question. Every parameter that changes the answer
        is in it, normalised, so two pages asking the same thing share a build
        and two different questions never collide."""
        def _i(name, default):
            try:
                return int(params.get(name) or default)
            except (TypeError, ValueError):
                return default
        return "history:{}:{}:{}:{}:{}".format(
            str(params.get("action") or "series").strip().lower(),
            _i("deviceId", 0),
            str(params.get("state") or "").strip(),
            _i("hours", 24),
            _i("maxPoints", 240))

    def _history_producer(self, params):
        """Run the query on a worker. A ValueError from _history_query means
        the CALLER asked for something impossible — an unknown device or state,
        or a history database that is not there — and must come back as a 400,
        so it is returned as data. Anything else propagates, the pool records a
        failure, and the handler answers 500."""
        try:
            return {"result": self._history_query(params)}
        except ValueError as exc:
            return {"client_error": str(exc)}

    def _timeline_active_spans(self, hist, conn, dev_id, col, bounds):
        """Return active spans [[startMin, endMin], ...] (minutes from local
        midnight, 0-1440) for a device's boolean column on the given day.
        `bounds` = (start_epoch, start_utc, end_utc). Filters on the RAW ts
        (UTC, index-friendly) — wrapping ts in datetime(...,'localtime') in the
        WHERE would defeat the index and full-scan multi-million-row tables.
        Local minutes come from epoch arithmetic. `col` is caller-validated."""
        start_epoch, start_utc, end_utc = bounds
        table = f"device_history_{dev_id}"
        # PK-range the day before scanning it — see _pk_window. Without this
        # a timeline load full-scans every lane's table on the request thread.
        lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
        pk_sql, pk_args = self._pk_clause(lo, hi)
        # State as of the start of the day (last transition strictly before it).
        # Bounded by the rowid of the day's first row: ts is monotone in id, so
        # the newest row with id < lo IS the last one before midnight, and the
        # planner answers it with a reverse B-tree seek. Until 2.95.1 this one
        # query ran BEFORE the PK window, unbounded and ts-ordered, once per
        # lane device — the full-scan-under-read-lock shape the PK-range work
        # removed everywhere else, left on the page most likely to be scrubbed
        # through a month of days.
        if lo is not None:
            carry = conn.execute(
                f'SELECT "{col}" FROM "{table}" '
                f'WHERE id < ? AND "{col}" IS NOT NULL '
                f'ORDER BY id DESC LIMIT 1', (lo,)).fetchone()
        else:
            carry = conn.execute(
                f'SELECT "{col}" FROM "{table}" '
                f'WHERE "{col}" IS NOT NULL AND ts < ? '
                f'ORDER BY ts DESC LIMIT 1', (start_utc,)).fetchone()
        state = self._as_bool01(carry[0]) if carry else 0
        rows = conn.execute(
            f'SELECT ({hist.epoch()} - {start_epoch}) / 60.0, "{col}" '
            f'FROM "{table}" '
            f'WHERE "{col}" IS NOT NULL AND ts >= ? AND ts < ?{pk_sql} '
            f'ORDER BY ts ASC', (start_utc, end_utc, *pk_args)).fetchall()
        spans, open_at = [], (0 if state else None)
        for mn, v in rows:
            b = self._as_bool01(v)
            mn = max(0.0, min(1440.0, mn))
            if b and open_at is None:
                open_at = mn
            elif not b and open_at is not None:
                if mn > open_at:
                    spans.append([round(open_at, 1), round(mn, 1)])
                open_at = None
        if open_at is not None:
            spans.append([round(open_at, 1), 1440])   # still active at day end
        return [s for s in spans if s[1] > s[0]]

    def _timeline_day(self, date_str):
        """Build the timeline payload for one LOCAL day (YYYY-MM-DD)."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str or ""):
            raise ValueError("date must be YYYY-MM-DD")
        hist = self._history()

        # UTC bounds of the LOCAL day. time.mktime honours the DST that was in
        # force on that date, so BST/GMT is handled. We filter the raw UTC ts
        # against these (index-friendly) and derive local minutes from the
        # start_epoch offset.
        import time as _t
        naive = datetime.strptime(date_str, "%Y-%m-%d")
        start_epoch = int(_t.mktime(naive.timetuple()))
        # The NEXT local midnight, not +86400: a clock-change day is 23 or 25
        # hours long, and a fixed day put the last hour in the wrong bucket.
        end_epoch = int(_t.mktime((naive + timedelta(days=1)).timetuple()))
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = datetime.fromtimestamp(end_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        bounds = (start_epoch, start_utc, end_utc)

        # Device sets from the rooms map (already classified). Fall back to a
        # live rebuild if the file isn't there yet.
        try:
            with open(os.path.join(self._public_dashboards_dir(), "rooms.json"),
                      encoding="utf-8") as _f:
                rooms = json.load(_f).get("rooms", {})
        except Exception:
            rooms = (self._build_rooms_json() or {}).get("rooms", {})

        lanes_cfg = [
            ("presence", "Presence",       "motion",    "onoffstate",     "#34a0d6"),
            ("lights",   "Lights",         "lights",    "onoffstate",     "#ff9f0a"),
            ("doors",    "Doors & windows","windows",   "onoffstate",     "#af52de"),
            ("heating",  "Heating",        "radiators", "hvacheaterison", "#ff453a"),
        ]
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            def has_col(dev_id, want):
                # Artefact-filtered, so the prefix fallback below can no longer
                # land on a dead "<state>_<epoch>" type-change duplicate — it
                # only ever finds a real variant such as "batterysoc_ui".
                cols = hist.column_names(conn, dev_id)
                if want in cols:
                    return want
                for c in cols:
                    if c.startswith(want):
                        return c
                return None

            lanes = []
            for key, label, cat, col, colour in lanes_cfg:
                ids = []
                for r in rooms.values():
                    ids += (r.get(cat) or [])
                rows = []
                for dev_id in dict.fromkeys(ids):     # de-dup, keep order
                    real = has_col(dev_id, col)
                    if not real:
                        continue
                    spans = self._timeline_active_spans(hist, conn, dev_id, real, bounds)
                    if spans:
                        rows.append({"id": dev_id,
                                     "name": self._device_name(dev_id),
                                     "spans": spans})
                rows.sort(key=lambda x: x["name"].lower())
                lanes.append({"key": key, "label": label,
                              "colour": colour, "devices": rows})

            energy = self._timeline_energy(hist, conn, bounds)
        finally:
            conn.close()
        return {"ok": True, "date": date_str, "lanes": lanes, "energy": energy}

    def _timeline_energy(self, hist, conn, bounds):
        """Battery SOC + solar-power trace for the day, 5-min samples. Uses the
        same raw-ts / epoch approach as the lanes (index-friendly)."""
        start_epoch, start_utc, end_utc = bounds
        dev = self._sigen_inverter()
        if dev is None:
            return None
        inv = dev.id
        table = f"device_history_{inv}"
        # Artefact-filtered, so the startswith fallbacks below cannot land on a
        # dead "batterysoc_<epoch>" left behind by a logged type change.
        cols = hist.column_names(conn, inv)
        soc = "batterysoc" if "batterysoc" in cols else \
            next((c for c in cols if c.startswith("batterysoc") and not c.endswith("_ui")), None)
        pv = "pvpowerwatts" if "pvpowerwatts" in cols else \
            next((c for c in cols if c.startswith("pvpowerwatts") and not c.endswith("_ui")), None)
        if not soc:
            return None
        pv_sel = f', avg(CAST("{pv}" AS REAL))' if pv else ", NULL"
        # The inverter is the largest table in the DB — this is the single
        # worst offender for the lock-the-logger-out scan. PK-range it.
        lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
        pk_sql, pk_args = self._pk_clause(lo, hi)
        rows = conn.execute(
            f'SELECT (({hist.epoch()} - {start_epoch}) / 300) AS b5, '
            f'       avg(CAST("{soc}" AS REAL)){pv_sel} '
            f'FROM "{table}" WHERE ts >= ? AND ts < ? AND "{soc}" IS NOT NULL'
            f'{pk_sql} '
            f'GROUP BY b5 ORDER BY b5', (start_utc, end_utc, *pk_args)).fetchall()
        pts = [{"m": int(b5) * 5,
                "soc": round(soc_v, 1) if soc_v is not None else None,
                "pv": round(pv_v) if pv_v is not None else None}
               for b5, soc_v, pv_v in rows]
        return {"points": pts}

    @staticmethod
    def _hour_frac(hb, now_hour, now_frac):
        """Elapsed fraction of hour `hb`, or None when it hasn't started.

        A mean over an hour's samples only covers the part that HAS happened,
        so the current hour's energy is that mean scaled by how much of the
        hour has run. now_hour None = the day is not today, all hours whole."""
        if now_hour is None:
            return 1.0
        if hb > now_hour:
            return None                      # the future has no samples
        if hb == now_hour:
            return max(0.0, min(1.0, now_frac))
        return 1.0

    @staticmethod
    def _sane_avg_sql(col):
        """SQL for the mean of `col` over a group, ignoring impossible samples.

        Valid on both SQLite and PostgreSQL: BETWEEN, CASE and CAST are
        standard, and avg() skips NULLs on both. See PV_STRING_SANE_MAX_W for
        why a reader has to filter at all and how the bound was measured.
        """
        cast = f'CAST("{col}" AS REAL)'
        return (f'avg(CASE WHEN {cast} BETWEEN {-PV_STRING_SANE_MAX_W} '
                f'AND {PV_STRING_SANE_MAX_W} THEN {cast} END)')

    @staticmethod
    def _string_hours_payload(hour_rows, now_hour, now_frac):
        """Pure: hour-bucket rows -> (strings, site) 24-entry lists.

        hour_rows: [(hb, avg_w1..avg_w4, avg_site_w), ...] — hb is the local
        hour 0-23, avgs are mean watts over that hour's samples (None when a
        column had none). Mean power over the hour IS the hour's kWh at /1000
        — exact only if the samples are evenly spaced, which they effectively
        are while PV is moving (the logger writes on change, and PV changes
        every poll in daylight). Verified against the day's own total.

        An hour with no row stays None in BOTH lists — the page draws a gap
        rather than a fabricated zero (absent is never a reading). A row
        whose per-string columns are all absent still yields its site figure,
        which is what covers the days before per-string logging began.
        """
        strings = [None] * 24
        site = [None] * 24
        for row in hour_rows or []:
            try:
                hb = int(row[0])
            except (TypeError, ValueError):
                continue
            if not (0 <= hb <= 23):
                continue
            frac = HistoryMixin._hour_frac(hb, now_hour, now_frac)
            if frac is None:
                continue

            def _kwh(v):
                try:
                    return round(float(v) / 1000.0 * frac, 3)
                except (TypeError, ValueError):
                    return None

            parts = [_kwh(v) for v in row[1:5]]
            if all(p is not None for p in parts):
                strings[hb] = parts
            if len(row) > 5:
                s = _kwh(row[5])
                if s is not None:
                    site[hb] = s
        return strings, site

    def _solar_string_hours(self, date_str):
        """Per-string AND site-total kWh per LOCAL hour of one day, from the
        inverter's pv1watts..pv4watts + pvpowerwatts history columns.
        PK-ranged like every other read of this DB.

        The site series matters as much as the strings: it has been logged
        for years, so it covers every hour of every day including those
        before per-string logging began — which is what lets BOTH pages draw
        a full day from this ONE call, with no second history fetch and no
        slot-midpoint approximation. hours=[] only when even the site column
        is missing."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str or ""):
            raise ValueError("date must be YYYY-MM-DD")
        hist = self._history()

        import time as _t
        naive = datetime.strptime(date_str, "%Y-%m-%d")
        start_epoch = int(_t.mktime(naive.timetuple()))
        # The NEXT local midnight, not +86400: a clock-change day is 23 or 25
        # hours long, and a fixed day put the last hour in the wrong bucket.
        end_epoch = int(_t.mktime((naive + timedelta(days=1)).timetuple()))
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = datetime.fromtimestamp(end_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        dev = self._sigen_inverter()
        if dev is None:
            return {"ok": True, "date": date_str, "hours": [], "site": []}
        inv = dev.id

        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            cols = hist.column_names(conn, inv)
            if "pvpowerwatts" not in cols:
                return {"ok": True, "date": date_str, "hours": [], "site": []}
            pv_cols = [f"pv{i}watts" for i in range(1, 5)]
            have_strings = all(c in cols for c in pv_cols)
            # NULL placeholders keep the row shape fixed at 6 columns, so the
            # pure decoder never has to know whether strings are logged here.
            #
            # _sane_avg_sql nulls an implausible sample BEFORE avg(), which
            # ignores NULLs — so an hour keeps the mean of its real samples,
            # and an hour with nothing left yields NULL, which the page draws
            # as a gap rather than a fabricated figure.
            _sane_avg = self._sane_avg_sql
            sel = ", ".join(_sane_avg(c) if have_strings else "NULL"
                            for c in pv_cols)
            table = f"device_history_{inv}"
            lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
            pk_sql, pk_args = self._pk_clause(lo, hi)
            rows = conn.execute(
                f'SELECT (({hist.epoch()} - {start_epoch}) / 3600) AS hb, {sel}, '
                f'       {_sane_avg("pvpowerwatts")} '
                f'FROM "{table}" WHERE ts >= ? AND ts < ? AND "pvpowerwatts" IS NOT NULL'
                f'{pk_sql} '
                f'GROUP BY hb ORDER BY hb', (start_utc, end_utc, *pk_args)).fetchall()
        finally:
            conn.close()

        now = datetime.now()
        if date_str == now.strftime("%Y-%m-%d"):
            # Same arithmetic as the SQL bucket (epoch - local midnight), so
            # the two agree on the 25-hour October day where now.hour does not.
            since_midnight = _t.time() - start_epoch
            now_hour = int(since_midnight // 3600)
            now_frac = (since_midnight % 3600) / 3600.0
        else:
            now_hour, now_frac = None, 1.0
        strings, site = self._string_hours_payload(rows, now_hour, now_frac)
        return {"ok": True, "date": date_str, "hours": strings, "site": site}

    def handleSolarStringHours(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/solarStringHours/
        Body: {"date": "YYYY-MM-DD"} (default: today, local). Bearer-authed
        upstream by IWS like every /message route. Cached 120 s — the chart
        polls with the page's 5-min history cycle, but several open pages
        must not each pay a history query."""
        params, _reply = self._request_body(action)
        if _reply:
            return _reply
        date_str = str(params.get("date") or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        # Validated here, on the dispatch path, so a bad date is a 400 and a 503
        # can only mean "not ready yet" — the same split handleTimelineDay makes.
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return self._evo_reply(
                {"ok": False, "error": "date must be YYYY-MM-DD"}, status=400)
        # Off the dispatch path (v3.25.0), on the shared pool. It was the one
        # history read 3.19/3.20 left inline: a PK-ranged aggregate over the
        # inverter table, the biggest there is. The old one-slot cache also lost
        # today's entry whenever someone looked at another day.
        today = datetime.now().strftime("%Y-%m-%d")
        live  = date_str >= today
        ttl   = self.SOLAR_HOURS_TODAY_TTL if live else self.TIMELINE_PAST_TTL
        # Completeness is part of the key, as in handleTimelineDay: an entry
        # built while this was today holds a part day scaled to the hour it
        # was built, and must never be handed out as the finished day.
        state, payload = self._offpath_get(
            f"solarhours:{date_str}:{'live' if live else 'final'}",
            lambda: self._solar_string_hours(date_str), ttl,
            wait=self.SOLAR_HOURS_WAIT)
        if state == "fresh":
            return self._evo_reply(payload)
        if state == "failed":
            self.logger.debug(f"[SolarHours] build failed: {payload}")
            return self._evo_reply({"ok": False, "error": payload}, status=500)
        return self._evo_reply(
            {"ok": False, "pending": True,
             "error": "the solar chart is still being built — try again shortly"},
            status=503)

    def handleTimelineDay(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/timelineDay/
        Body: {"date": "YYYY-MM-DD"} (default: today, local). Bearer-authed."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        params, _reply = self._request_body(action, refuse_reflector=False)
        if _reply:
            return _reply
        date_str = str(params.get("date") or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        # Check the date HERE, not on a worker. It is a pure string test costing
        # nothing on the dispatch path, and it keeps the two failure kinds
        # apart: a malformed date is a 400 the page reports to the user, while
        # a 503 means "not ready yet" and DashUI.message polls it. Deciding
        # that from the text of the exception instead — which is what the first
        # version of this did — got it wrong, because the real message reads
        # "date must be YYYY-MM-DD" and the guess looked for the word "format".
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return self._evo_reply(
                {"ok": False, "error": "date must be YYYY-MM-DD"}, status=400)
        # Off the dispatch path (v3.19.0). Measured at 1707 ms worst of three
        # on 18-09-2026 — the slowest endpoint in the plugin, and every
        # millisecond of it was a stall of everything else IWS was serving.
        # The query itself is not the problem: _rowid_for_ts already binary-
        # searches the integer PK because the history DB has no ts index. It is
        # simply a lot of correct small queries across a whole day, so the fix
        # is where it runs, not how it is written.
        #
        # A past day cannot change, so it is cached for the session; today's is
        # still being written, so it gets a minute.
        today = datetime.now().strftime("%Y-%m-%d")
        live  = date_str >= today
        ttl   = self.TIMELINE_TODAY_TTL if live else self.TIMELINE_PAST_TTL
        # Whether the day was complete when it was built goes in the KEY. The
        # reader picks the TTL, so with the date alone an entry built at 9pm
        # as "today" was read after midnight with the day-long past TTL and
        # served as the finished day, cut off at 9pm, for up to 24 hours.
        state, payload = self._offpath_get(
            f"timeline:{date_str}:{'live' if live else 'final'}",
            lambda: self._timeline_day(date_str), ttl,
            wait=self.TIMELINE_WAIT)
        if state == "fresh":
            return self._evo_reply(payload)
        if state == "failed":
            return self._evo_reply({"ok": False, "error": payload}, status=500)
        return self._evo_reply(
            {"ok": False, "pending": True,
             "error": "the timeline is still being built — try again shortly"},
            status=503)

    def _pk_window(self, hist, conn, table, start_utc, end_utc=None):
        """Rowid bounds for a ts window, so a query can be PK-RANGED rather
        than ts-scanned. Returns (lo, hi); either may be None meaning
        "unbounded that end".

        This is not an optimisation, it is the difference between a query that
        holds a read lock for milliseconds and one that holds it for the whole
        table. `indigo_history.sqlite` has NO index on ts and runs
        journal_mode=delete, so a ts-filtered query full-scans AND blocks the
        SQL Logger's writes for the duration — that is exactly what wedged
        IWS and MCP for ~3 minutes on 15-Jul-2026. `_rowid_for_ts` was written
        then to fix it, but only Home Insights was ever moved onto it; Graphs
        and Timeline kept scanning, which is the wedge still being seen.

        Both backends (v2.95.1). This used to exempt Postgres on the belief
        that the SQL Logger indexes ts there — it does not; its Postgres DDL
        is `ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP` with no index, so every
        ts-filtered query was a sequential scan inside a 10 s-capped psql
        subprocess on the plugin's one dispatch thread. The probes here are
        PK seeks, cheap on either engine. The ONE difference is the ts
        convention: `ts` is UTC on SQLite and session-LOCAL on Postgres, so
        _rowid_for_ts asks the connection to translate the bound (ts_key).
        """
        try:
            lo = self._rowid_for_ts(conn, table, start_utc)
            hi = self._rowid_for_ts(conn, table, end_utc) if end_utc else None
            return lo, hi
        except Exception as exc:
            # A probe failure must not cost the caller its data — fall back to
            # the ts filter, which is slow but correct.
            self.logger.debug(f"[History] PK-range probe failed on {table}: {exc}")
            return None, None

    @staticmethod
    def _pk_clause(lo, hi, alias="id"):
        """SQL fragment + params for the bounds _pk_window returned."""
        parts, args = [], []
        if lo is not None:
            parts.append(f" AND {alias} >= ?")
            args.append(lo)
        if hi is not None:
            parts.append(f" AND {alias} < ?")
            args.append(hi)
        return "".join(parts), args

    @staticmethod
    def _rowid_for_ts(conn, table, ts_utc):
        """Smallest rowid whose ts >= ts_utc, found by BINARY SEARCH on the
        integer PK. The SQL Logger appends chronologically, so ts is monotone
        in id — and the history DB has NO ts index and journal_mode=delete,
        meaning any full-table scan holds a read lock that BLOCKS the logger's
        writes (live-confirmed 15-Jul-2026: the first insights build wedged
        IWS + MCP for ~3 min doing exactly that on the 1.5GB DB). Every probe
        here is a PK-ranged point query, so locks stay microscopic.
        Returns None for an empty table; max(id)+1 if every row is older.
        `ts_utc` is UTC; the Python-side comparisons use the connection's own
        ts convention (ts_key) so the same code binary-searches a Postgres
        table, whose ts is session-local, correctly. A bare sqlite3 connection
        (the tests pass one) has no ts_key and compares UTC to UTC."""
        ts_key = conn.ts_key(ts_utc) if hasattr(conn, "ts_key") else ts_utc
        # min() and max() are fetched SEPARATELY on purpose. SQLite rewrites a
        # lone min()/max() over an INTEGER PRIMARY KEY into a B-tree seek, but
        # asking for BOTH in one statement defeats that and it full-scans —
        # measured on the 1.5M-row table here: `min(id), max(id)` together is
        # a SCAN at 96 ms, each alone is a SEARCH at 0.01 ms. Since this
        # function exists precisely to avoid full scans, having one on its
        # first line made every caller pay the cost it was written to remove.
        lo_row = conn.execute(f'SELECT min(id) FROM "{table}"').fetchone()
        if not lo_row or lo_row[0] is None:
            return None
        hi_row = conn.execute(f'SELECT max(id) FROM "{table}"').fetchone()
        lo, hi = int(lo_row[0]), int(hi_row[0])

        def probe(i):
            r = conn.execute(
                f'SELECT id, ts FROM "{table}" WHERE id >= ? ORDER BY id LIMIT 1',
                (i,)).fetchone()
            return (int(r[0]), r[1]) if r else None

        first = probe(lo)
        if first and str(first[1]) >= ts_key:      # ISO strings compare chronologically
            return first[0]
        last = conn.execute(
            f'SELECT id, ts FROM "{table}" WHERE id <= ? ORDER BY id DESC LIMIT 1',
            (hi,)).fetchone()
        if not last or str(last[1]) < ts_key:
            return hi + 1
        # Invariant: ts at lo < ts_key <= ts at hi. Ids may have gaps — each
        # probe lands on the first real row at/after the midpoint.
        while hi - lo > 1:
            mid = (lo + hi) // 2
            p = probe(mid)
            if p is None or str(p[1]) >= ts_key:
                hi = p[0] if (p and p[0] < hi) else mid
            else:
                lo = p[0]
        return hi
