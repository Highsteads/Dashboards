#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    insights_mixin.py
# Description: Home Insights: things out of the ordinary against the house's
#              own norms — a battery falling faster than usual, a sensor gone
#              quiet, a room colder than it tends to be, a device on for far
#              longer than normal — built from the SQL Logger history. Split out
#              of plugin.py in v3.30.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import os
from datetime import datetime, timezone

from dash_util import as_bool01

try:
    import indigo
except ImportError:
    pass
try:
    import history_db as _history_db
except ImportError:
    _history_db = None


class InsightsMixin:
    # --------------------------------------------------------
    # Home Insights (v2.42.0) — auto-surface anomalies vs each device's OWN
    # norms, computed from the history the SQL Logger already keeps. Not a
    # status page (system-health owns live errors): these are "different from
    # usual" findings — a battery falling fast, a normally-chatty motion
    # sensor gone silent, a room off its usual temperature, a device on far
    # longer than its daily norm. Powers the hub's Insights card.
    # --------------------------------------------------------

    # Thresholds — deliberately conservative so the card stays quiet unless
    # something is genuinely off. Tweak here, not in the evaluators.
    _INS_BATT_WEEK_DROP   = 12     # pts fallen in 7 days before we care

    _INS_BATT_WARN_DAYS   = 21     # projected days-to-empty for a warn

    _INS_QUIET_EXPECTED   = 6.0    # events expected so far today before silence is odd

    _INS_TEMP_NOTE_DELTA  = 2.5    # degC off the same-hour norm

    _INS_TEMP_WARN_DELTA  = 4.0

    _INS_TEMP_MIN_SAMPLES = 12     # history rows needed for a meaningful norm

    _INS_ON_MIN_EXTRA     = 90.0   # minutes beyond the daily norm

    _INS_ON_RATIO         = 2.0    # and at least this multiple of the norm

    @staticmethod
    def _insight_battery_trend(name, dev_id, now_pct, week_ago_pct):
        """A battery that has fallen fast over the last week, with a
        days-to-empty projection. Returns an insight dict or None."""
        if now_pct is None or week_ago_pct is None:
            return None
        drop = week_ago_pct - now_pct
        if drop < InsightsMixin._INS_BATT_WEEK_DROP:
            return None
        per_day = drop / 7.0
        days_left = int(now_pct / per_day) if per_day > 0 else 999
        level = "warn" if (days_left <= InsightsMixin._INS_BATT_WARN_DAYS or now_pct <= 20) else "note"
        return {"kind": "battery", "level": level, "icon": "battery",
                "title": f"{name} battery falling fast",
                "detail": f"{week_ago_pct:.0f}% a week ago, {now_pct:.0f}% now — "
                          f"about {days_left} days left at this rate.",
                "deviceId": dev_id}

    @staticmethod
    def _insight_quiet_sensor(name, dev_id, today_events, daily_avg, hours_elapsed):
        """A motion/presence sensor that normally logs plenty but has logged
        NOTHING today. Expected-so-far scales the norm by the elapsed part of
        the day, so an early-morning check doesn't cry wolf."""
        if today_events > 0 or daily_avg <= 0 or hours_elapsed <= 0:
            return None
        expected_so_far = daily_avg * (min(hours_elapsed, 24.0) / 24.0)
        if expected_so_far < InsightsMixin._INS_QUIET_EXPECTED:
            return None
        return {"kind": "quiet", "level": "warn", "icon": "walk",
                "title": f"{name} has gone quiet",
                "detail": f"No events today; it normally logs about "
                          f"{daily_avg:.0f} a day. It may be stuck or offline.",
                "deviceId": dev_id}

    @staticmethod
    def _insight_room_temp(room, temp_now, usual, samples):
        """A room materially off its own same-hour-of-day fortnight norm."""
        if temp_now is None or usual is None or samples < InsightsMixin._INS_TEMP_MIN_SAMPLES:
            return None
        delta = temp_now - usual
        if abs(delta) < InsightsMixin._INS_TEMP_NOTE_DELTA:
            return None
        level = "warn" if abs(delta) >= InsightsMixin._INS_TEMP_WARN_DELTA else "note"
        word = "warmer" if delta > 0 else "colder"
        return {"kind": "temp", "level": level, "icon": "thermo",
                "title": f"{room} is {word} than usual",
                "detail": f"{temp_now:.1f}°C now against a usual "
                          f"{usual:.1f}°C at this time of day "
                          f"({abs(delta):.1f}°C {word}).",
                "room": room}

    @staticmethod
    def _insight_on_too_long(name, dev_id, on_min_today, daily_avg_min):
        """A device that is ON and has already clocked far more ON-time today
        than its daily norm. Absolute + ratio guard so a usually-off device
        needs a real stretch, not 10 minutes vs 2."""
        extra = on_min_today - daily_avg_min
        if extra < InsightsMixin._INS_ON_MIN_EXTRA:
            return None
        if daily_avg_min > 0 and on_min_today < daily_avg_min * InsightsMixin._INS_ON_RATIO:
            return None
        level = "warn" if (extra >= 180 and
                           (daily_avg_min <= 0 or on_min_today >= daily_avg_min * 3)) else "note"
        hrs = on_min_today / 60.0
        avg_h = daily_avg_min / 60.0
        return {"kind": "onlong", "level": level, "icon": "bulb",
                "title": f"{name} has been on longer than usual",
                "detail": f"On for {hrs:.1f}h so far today; "
                          f"its daily norm is {avg_h:.1f}h.",
                "deviceId": dev_id}

    @staticmethod
    def _active_minutes_per_day(initial_on, rows, days, now_min=None):
        """Total ON-minutes per fixed 1440-min day across a multi-day window.
        `rows` = [(minute_offset_from_window_start, value), ...] sorted by time;
        `initial_on` = carry-in state at the window start; `now_min` = the
        current moment as a minute offset — a still-open trailing span closes
        THERE, not at the window end, because the window's last day runs to
        tomorrow midnight and closing at the end credited a device that is ON
        NOW with hours that have not happened yet. Pure — testable without a
        database. (Fixed-length days means a DST boundary is off by an hour
        that day — fine for a norm comparison.)"""
        total = days * 1440.0
        spans = []
        open_at = 0.0 if initial_on else None
        for mn, v in rows:
            b = as_bool01(v)
            mn = max(0.0, min(total, mn))
            if b and open_at is None:
                open_at = mn
            elif not b and open_at is not None:
                if mn > open_at:
                    spans.append((open_at, mn))
                open_at = None
        if open_at is not None:
            end = total if now_min is None else max(0.0, min(total, now_min))
            if end > open_at:
                spans.append((open_at, end))
        per_day = [0.0] * days
        for s, e in spans:
            first = int(s // 1440)
            last = min(days - 1, int((e - 0.001) // 1440))
            for d in range(first, last + 1):
                lo, hi = d * 1440.0, (d + 1) * 1440.0
                per_day[d] += max(0.0, min(e, hi) - max(s, lo))
        return per_day

    def _home_insights(self):
        """Gather the data and run every evaluator. Each section is isolated —
        one failure logs and skips, never blanks the card. Returns the full
        payload dict. ALL history reads are PK-ranged via _rowid_for_ts — see
        its docstring for why a ts-filtered scan is never acceptable here."""
        import time as _t
        hist = self._history()

        now = _t.time()
        lt = datetime.now()
        midnight = datetime(lt.year, lt.month, lt.day)
        start_epoch = int(_t.mktime(midnight.timetuple()))
        hours_elapsed = (now - start_epoch) / 3600.0

        def utc(epoch):
            return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        today_utc = utc(start_epoch)
        fortnight_utc = utc(start_epoch - 14 * 86400)
        week_epoch = start_epoch - 7 * 86400
        week_utc = utc(week_epoch)

        # Device sets from the rooms map (already classified).
        try:
            with open(os.path.join(self._public_dashboards_dir(), "rooms.json"),
                      encoding="utf-8") as _f:
                rooms = json.load(_f).get("rooms", {})
        except Exception:
            rooms = (self._build_rooms_json() or {}).get("rooms", {})

        insights = []
        checked = {"batteries": 0, "sensors": 0, "rooms": 0, "devices": 0}
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            def has_col(dev_id, want):
                # Artefact-filtered — see the note in _timeline_day.
                cols = hist.column_names(conn, dev_id)
                if want in cols:
                    return want
                return next((c for c in cols if c.startswith(want)), None)

            def battery_col(dev_id):
                # Exact names first, prefix last — 'battery' prefix-matched
                # 'batterylow' before 'batterylevel' was ever tried.
                cols = hist.column_names(conn, dev_id)
                return (next((c for c in ("battery", "batterylevel") if c in cols), None)
                        or next((c for c in cols if c.startswith("battery")
                                 and c not in ("batterylow",) and not c.endswith("_ui")), None))

            def readable(dev_id):
                # A disabled device's states are frozen; an errored one's are
                # stale. Neither is evidence about the house.
                try:
                    d = indigo.devices[dev_id]
                except Exception:
                    return None
                if not getattr(d, "enabled", True) or (getattr(d, "errorState", "") or "").strip():
                    return None
                return d

            # ── batteries falling fast ──────────────────────────────────
            try:
                for d in indigo.devices:
                    pct, _alarm = self._battery_pct(d)
                    if pct is None:
                        continue
                    if readable(d.id) is None:
                        continue
                    checked["batteries"] += 1
                    col = battery_col(d.id)
                    if not col:
                        continue
                    table = f"device_history_{d.id}"
                    b_week = self._rowid_for_ts(conn, table, week_utc)
                    if b_week is None:
                        continue
                    row = conn.execute(
                        f'SELECT "{col}" FROM "{table}" '
                        f'WHERE id < ? AND "{col}" IS NOT NULL AND "{col}" != "" '
                        f'ORDER BY id DESC LIMIT 1', (b_week,)).fetchone()
                    if not row:
                        continue          # < a week of history — no trend yet
                    try:
                        week_pct = float(row[0])
                    except (TypeError, ValueError):
                        continue
                    ins = self._insight_battery_trend(d.name, d.id, float(pct), week_pct)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] battery section failed: {exc}")

            # ── motion sensors gone quiet ───────────────────────────────
            try:
                motion_ids = []
                for r in rooms.values():
                    motion_ids += (r.get("motion") or [])
                for dev_id in dict.fromkeys(motion_ids):
                    if readable(dev_id) is None:
                        continue               # disabled on purpose is not 'gone quiet'
                    col = has_col(dev_id, "onoffstate")
                    if not col:
                        continue
                    table = f"device_history_{dev_id}"
                    b_fort = self._rowid_for_ts(conn, table, fortnight_utc)
                    b_today = self._rowid_for_ts(conn, table, today_utc)
                    if b_fort is None or b_today is None:
                        continue
                    checked["sensors"] += 1
                    today_n = conn.execute(
                        f'SELECT count(*) FROM "{table}" '
                        f'WHERE id >= ? AND "{col}" IS NOT NULL',
                        (b_today,)).fetchone()[0]
                    prior_n = conn.execute(
                        f'SELECT count(*) FROM "{table}" '
                        f'WHERE id >= ? AND id < ? AND "{col}" IS NOT NULL',
                        (b_fort, b_today)).fetchone()[0]
                    ins = self._insight_quiet_sensor(
                        self._device_name(dev_id), dev_id,
                        today_n, prior_n / 14.0, hours_elapsed)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] quiet-sensor section failed: {exc}")

            # ── rooms off their usual temperature ───────────────────────
            try:
                utc_hour = datetime.fromtimestamp(now, timezone.utc).strftime("%H")
                for room, cfg in rooms.items():
                    for dev_id in (cfg.get("sensors") or []):
                        d_now = readable(dev_id)
                        if d_now is None:
                            continue
                        try:
                            temp_now = float(d_now.states.get("temperature"))
                        except Exception:
                            continue
                        col = has_col(dev_id, "temperature")
                        if not col:
                            continue
                        table = f"device_history_{dev_id}"
                        b_fort = self._rowid_for_ts(conn, table, fortnight_utc)
                        b_today = self._rowid_for_ts(conn, table, today_utc)
                        if b_fort is None or b_today is None:
                            continue
                        checked["rooms"] += 1
                        usual, samples = conn.execute(
                            f'SELECT avg(CAST("{col}" AS REAL)), count(*) '
                            f'FROM "{table}" '
                            f'WHERE id >= ? AND id < ? AND {hist.hour_of()} = ? '
                            f'  AND "{col}" IS NOT NULL AND "{col}" != ""',
                            (b_fort, b_today, utc_hour)).fetchone()
                        ins = self._insight_room_temp(room, temp_now, usual, samples or 0)
                        if ins:
                            insights.append(ins)
                        break     # one representative sensor per room
            except Exception as exc:
                self.logger.warning(f"[Insights] room-temp section failed: {exc}")

            # ── devices on longer than usual (only those ON now) ────────
            try:
                light_ids = []
                for r in rooms.values():
                    light_ids += (r.get("lights") or []) + (r.get("extras") or [])
                for dev_id in dict.fromkeys(light_ids):
                    d_now = readable(dev_id)
                    if d_now is None:
                        continue               # a lamp disabled while on is not 'on too long'
                    try:
                        if not bool(d_now.onState):
                            continue
                    except Exception:
                        continue
                    col = has_col(dev_id, "onoffstate")
                    if not col:
                        continue
                    table = f"device_history_{dev_id}"
                    b_week = self._rowid_for_ts(conn, table, week_utc)
                    if b_week is None:
                        continue
                    checked["devices"] += 1
                    carry = conn.execute(
                        f'SELECT "{col}" FROM "{table}" '
                        f'WHERE id < ? AND "{col}" IS NOT NULL '
                        f'ORDER BY id DESC LIMIT 1', (b_week,)).fetchone()
                    rows = conn.execute(
                        f'SELECT ({hist.epoch()} - {week_epoch}) / 60.0, '
                        f'       "{col}" FROM "{table}" '
                        f'WHERE id >= ? AND "{col}" IS NOT NULL '
                        f'ORDER BY id ASC', (b_week,)).fetchall()
                    per_day = self._active_minutes_per_day(
                        self._as_bool01(carry[0]) if carry else 0, rows, 8,
                        now_min=(now - week_epoch) / 60.0)
                    # Day 8 is today (partial); days 1-7 are the norm.
                    ins = self._insight_on_too_long(
                        self._device_name(dev_id), dev_id,
                        per_day[7], sum(per_day[:7]) / 7.0)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] on-too-long section failed: {exc}")
        finally:
            conn.close()

        insights.sort(key=lambda i: (0 if i["level"] == "warn" else 1, i["title"]))
        return {"ok": True, "generated": now, "insights": insights[:8],
                "checked": checked}

    def handleHomeInsights(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/homeInsights/
        Bearer-authed by IWS. Stale-while-revalidate: always answers instantly
        from the cache (15-min TTL); a stale/missing cache kicks ONE background
        rebuild and, until the first build lands, replies {building: true} so
        the page just tries again on its next poll."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        # On the shared pool (v3.27.0). A failure is remembered for five
        # minutes: without that a SQL-Logger-less install would retry the
        # build, and warn, on every 20 s poll for ever.
        return self._evo_reply(self._offpath_swr(
            "insights", self._home_insights, ttl=900, fail_ttl=300,
            placeholder={"ok": True, "building": True, "insights": [], "checked": {}},
            on_fail=lambda d: {"ok": False, "insights": [], "checked": {},
                               "error": f"insights unavailable: {d}"}))
