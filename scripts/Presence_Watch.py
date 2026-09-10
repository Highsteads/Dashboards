#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Presence_Watch.py
# Description: Builds presence data for the Dashboards "Presence watch" tile.
#              SQL-history timelines for the Living Room (18:00-23:00) and
#              Bedroom 1 (20:30-08:00, wraps midnight) presence-sensor pairs,
#              with a derived agreement/disagreement track, per-sensor stats,
#              dropout callouts, a PIR movement-activity strip and a bedroom
#              sleep proxy. Emits minutes-from-window-start; the card formats
#              clock times. Run on a ~10-min schedule (and once to seed).
#              v1.2: output moved OUT of the anonymous /public namespace —
#              it now lands beside this script and Dashboards serves it over
#              the Bearer-authed presenceData endpoint. All history reads are
#              PK-ranged (rowid binary search) because indigo_history.sqlite
#              has NO ts index and journal_mode=delete: a ts-filtered scan
#              full-scans the table AND holds a read lock against the SQL
#              Logger's writes. The old localtime-converted ts filters were
#              ~168 such scans every 300 s.
# Author:      CliveS & Claude Sonnet 5
# Date:        02-09-2026 + UK Time Now
# Version:     1.5
#
# v1.5 (02-09-2026): the agreement track is N-way now, not hardcoded to the
#   first two sensors. green = every reporting sensor on at once; amber = some
#   but not all, tagged with which ones held. A dropout callout can now name
#   more than one sensor on each side ("Right dropped ... while Left and
#   Centre held"). The "only compares the first two — ignoring X" notice and
#   the ignoredSensors field are gone — there is nothing left to ignore.
#   Undoes the v1.4 caveat within the hour it was written.
#
# v1.4 (02-09-2026): the living room gains its third FP300, Living Room Right
#   (1899487413). Its track and stats are drawn like the others; the agreement
#   track still compares the first two. That notice is INFO now — a third
#   sensor put there on purpose is not a fault.
#
# v1.3 (02-09-2026, Dashboards deep review): (1) a sensor's last logged state is
#   no longer carried into a night without limit — a disabled or dead sensor
#   whose last row said "present" painted every later night as occupied from
#   the first minute. A carried "present" now lapses CARRY_MAX_HOURS after the
#   row it came from. (2) Each sensor's Indigo status (ok / disabled / missing /
#   error) is published in the payload so the page can say so in place.
#   (3) A "database is locked" from the SQL Logger's commit is a skip with a
#   warning, keeping the last good file, not an ERROR with a traceback every
#   five minutes. (4) The local/UTC conversions use the system zone through
#   datetime.astimezone() instead of the deprecated utcfromtimestamp + mktime.
#   (5) A room with more than two sensors says which ones the agreement track
#   ignores, once, instead of silently dropping them.

import json
import os
import sqlite3
import traceback
from datetime import datetime, timedelta, timezone

# ---- config -----------------------------------------------------------------
NIGHTS_BACK  = 14      # nights to compute (scrollback + 7-night pattern strip)
MIN_DROP_MIN = 2.0     # ignore disagreement spans shorter than this (a callout)
CARRY_MAX_HOURS = 6.0  # a carried "present" older than this is not evidence (v1.3)
VIS_MIN      = 0.25    # fold disagreement slivers shorter than this into "both"
WAKE_GAP_MIN = 3.0     # a clear gap >= this within the in-bed span = a wakeup
BUCKETS      = 60      # PIR-activity resolution (buckets across the window)

# Install-specific: your rooms, windows and presence-sensor device ids.
ROOMS = [
    {"key": "living_room", "title": "Living room", "icon": "sofa",
     "start": (18, 0), "end": (23, 0), "wrap": False,
     "sensors": [{"id": 1496890672, "label": "Centre"},
                 {"id": 1909477979, "label": "Left"},
                 {"id": 1899487413, "label": "Right"}]},
    {"key": "bedroom_1", "title": "Bedroom 1", "icon": "bed",
     "start": (20, 30), "end": (8, 0), "wrap": True,
     "sensors": [{"id": 1881897017, "label": "Wall"},
                 {"id": 623198824,  "label": "Headboard"}]},
]

FMT = "%Y-%m-%d %H:%M:%S"

# Output filename — served by Dashboards' Bearer-authed presenceData endpoint.
# Deliberately NOT under Web Assets/public: that namespace is anonymous and
# reflector-reachable, and 14 nights of bedroom occupancy plus a sleep
# timeline must not be readable from the public internet.
OUT_FILENAME = "presence_data.json"
# The pre-v1.2 output — swept on every run so no install keeps serving it.
LEGACY_PUBLIC_RELPATH = os.path.join("Web Assets", "public", "dashboards",
                                     "presence.json")


import logging


_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=_lvl(level))


# ---- time helpers -----------------------------------------------------------
def _utc_str(dt_local):
    """Local naive datetime -> UTC 'YYYY-MM-DD HH:MM:SS' string (DST-aware).
    The SQL Logger's ts column IS UTC on SQLite (measured across all 245
    tables). astimezone() on a naive value applies the system zone, so no
    zone name is pinned and no deprecated utcfromtimestamp is needed."""
    return dt_local.astimezone(timezone.utc).strftime(FMT)


def _local_dt(ts_utc):
    """UTC ts string from the DB -> local naive datetime."""
    dt_utc = datetime.strptime(ts_utc.split(".")[0], FMT).replace(tzinfo=timezone.utc)
    return dt_utc.astimezone().replace(tzinfo=None)


# ---- sql helpers (PK-ranged — never ts-filter this DB) ----------------------
def _table_exists(cur, tid):
    tid = int(tid)
    return cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                       (f"device_history_{tid}",)).fetchone() is not None


def _has_column(cur, tid, col):
    tid = int(tid)
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info(device_history_{tid})").fetchall()]
    return col in cols


def _rowid_for_ts(cur, table, ts_utc):
    """Smallest rowid whose ts >= ts_utc, by BINARY SEARCH on the integer PK
    (ported from Dashboards plugin.py — the logger appends chronologically so
    ts is monotone in id; every probe is a PK point query, locks microscopic).
    Returns None for an empty table; max(id)+1 if every row is older."""
    # min() and max() fetched SEPARATELY: both in one statement defeats
    # SQLite's B-tree-seek rewrite and full-scans (measured in Dashboards).
    lo_row = cur.execute(f'SELECT min(id) FROM "{table}"').fetchone()
    if not lo_row or lo_row[0] is None:
        return None
    hi_row = cur.execute(f'SELECT max(id) FROM "{table}"').fetchone()
    lo, hi = int(lo_row[0]), int(hi_row[0])

    def probe(i):
        r = cur.execute(
            f'SELECT id, ts FROM "{table}" WHERE id >= ? ORDER BY id LIMIT 1',
            (i,)).fetchone()
        return (int(r[0]), r[1]) if r else None

    first = probe(lo)
    if first and first[1] >= ts_utc:      # ISO strings compare chronologically
        return first[0]
    last = cur.execute(
        f'SELECT id, ts FROM "{table}" WHERE id <= ? ORDER BY id DESC LIMIT 1',
        (hi,)).fetchone()
    if not last or last[1] < ts_utc:
        return hi + 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        p = probe(mid)
        if p is None or p[1] >= ts_utc:
            hi = p[0] if (p and p[0] < hi) else mid
        else:
            lo = p[0]
    return hi


class SensorHistory:
    """All of one sensor's rows for the whole 14-night span, loaded in ONE
    PK-ranged read and sliced per-night in Python. Replaces ~3 full-scan
    queries per sensor per night (~168 per tick) with one range read plus a
    handful of point probes per sensor per tick."""

    def __init__(self, cur, tid, span_start_local, cols):
        tid = int(tid)          # ids reach SQL as f-string table names — int only
        self.tid = tid
        self.on_rows = []      # [(local_dt, int onoffstate)] sorted by id
        self.pir_rows = []     # [(local_dt, int pirdetection)]
        self.carry_state = 0   # onoffstate just before span_start (0 unknown)
        self.carry_at = None   # local time of the row that carry_state came from
        self.has_table = _table_exists(cur, tid)
        if not self.has_table:
            return
        table = f"device_history_{tid}"
        have = {c for c in cols if _has_column(cur, tid, c)}
        if not have:
            return
        s_utc = _utc_str(span_start_local)
        lo = _rowid_for_ts(cur, table, s_utc)
        if lo is None:
            return
        sel = ", ".join(c if c in have else "NULL" for c in ("onoffstate", "pirdetection"))
        for _id, ts, on_v, pir_v in cur.execute(
                f'SELECT id, ts, {sel} FROM "{table}" WHERE id >= ? ORDER BY id',
                (lo,)):
            lt = _local_dt(ts)
            if on_v is not None:
                try:
                    self.on_rows.append((lt, int(on_v)))
                except (ValueError, TypeError):
                    pass
            if pir_v is not None:
                try:
                    self.pir_rows.append((lt, int(pir_v)))
                except (ValueError, TypeError):
                    pass
        # State carried into the span: last non-null onoffstate BEFORE lo.
        # A backwards PK walk that stops at the first hit — no temp B-tree,
        # no ts filter (presence sensors log onoffstate often, so it is near).
        if "onoffstate" in have:
            r = cur.execute(
                f'SELECT onoffstate, ts FROM "{table}" WHERE id < ? AND onoffstate '
                f'IS NOT NULL ORDER BY id DESC LIMIT 1', (lo,)).fetchone()
            try:
                self.carry_state = int(r[0]) if r and r[0] is not None else 0
                self.carry_at = _local_dt(r[1]) if r and r[1] else None
            except (ValueError, TypeError):
                self.carry_state = 0

    def has_on_data(self):
        return bool(self.on_rows)

    def carry_in(self, start_dt):
        """onoffstate immediately before start_dt (0 if unknown).

        A carried "present" LAPSES (v1.3): a sensor whose last row said 1 and
        then went silent — disabled for a battery change, off the mesh, its
        plugin stopped — used to paint every night after that as occupied
        from minute 0, with the partner blamed for a dropout it never had.
        Presence sensors log every few minutes while anyone is there, so a 1
        older than CARRY_MAX_HOURS is a frozen reading, not a person."""
        state, at = self.carry_state, self.carry_at
        for lt, v in self.on_rows:
            if lt >= start_dt:
                break
            state, at = v, lt
        if state == 1 and at is not None and (start_dt - at) > timedelta(hours=CARRY_MAX_HOURS):
            return 0
        return state

    def intervals(self, start_dt, eff_end):
        """(on, off) presence intervals in minutes-from-start, clipped to the
        window, plus the raw transition count. Carries in the pre-window state."""
        state = self.carry_in(start_dt)
        mins = lambda t: (t - start_dt).total_seconds() / 60.0
        ivs, on, nt = [], (start_dt if state == 1 else None), 0
        for lt, v in self.on_rows:
            if lt < start_dt or lt >= eff_end:
                continue
            nt += 1
            if v == 1 and on is None:
                on = lt
            elif v == 0 and on is not None:
                ivs.append((mins(on), mins(lt))); on = None
        if on is not None:
            ivs.append((mins(on), mins(eff_end)))
        ivs = [(a, b) for a, b in ivs if b - a > 0.01]
        return ivs, nt

    def pir_edges(self, start_dt, eff_end):
        """Minutes-from-start of each pirdetection rising edge in the window."""
        out, prev = [], None
        for lt, v in self.pir_rows:
            if lt >= eff_end:
                break
            if lt >= start_dt and v == 1 and prev != 1:
                out.append((lt - start_dt).total_seconds() / 60.0)
            prev = v
        return out


def _stats(ivs, span, nt):
    if not ivs:
        return {"firstOn": None, "lastOff": None, "occMin": 0, "occPct": 0,
                "transitions": nt, "longestHold": 0, "hasData": nt > 0}
    occ = sum(b - a for a, b in ivs)
    return {"firstOn": round(ivs[0][0], 1), "lastOff": round(ivs[-1][1], 1),
            "occMin": round(occ), "occPct": round(occ / span * 100) if span else 0,
            "transitions": nt, "longestHold": round(max(b - a for a, b in ivs)),
            "hasData": True}


def _agreement(interval_lists, span):
    """N-way generalisation of the old two-sensor agreement track (v1.5).

    green = EVERY reporting sensor on at once (full consensus) — merged.
    amber = some but not all on, tagged with the INDICES (into
    interval_lists) of the sensors that HELD; the complement dropped. With
    two sensors this is always a clean 1-vs-1 split. With three or more, a
    2-vs-1 split is just as real and gets the same treatment — amber, tagged
    with whichever side held. Sub-VIS_MIN slivers (edge-sync noise) fold into
    green so the track stays clean and continuous.
    """
    n = len(interval_lists)
    pts = sorted(set([0.0, float(span)] +
                      [x for ivs in interval_lists for iv in ivs for x in iv]))
    raw_green, raw_amber = [], []
    for i in range(len(pts) - 1):
        s, e = pts[i], pts[i + 1]
        if e - s <= 0.01:
            continue
        m = (s + e) / 2.0
        on = [j for j, ivs in enumerate(interval_lists)
              if any(x <= m < y for x, y in ivs)]
        if len(on) == n:
            raw_green.append((s, e))
        elif on:
            raw_amber.append([s, e, on])
    keep = []
    for s, e, on in raw_amber:
        if e - s < VIS_MIN:
            raw_green.append((s, e))
        else:
            keep.append([s, e, on])
    green = []
    for s, e in sorted(raw_green):
        if green and s <= green[-1][1] + 0.02:
            green[-1][1] = max(green[-1][1], e)
        else:
            green.append([s, e])
    amber = []
    for s, e, on in sorted(keep):
        if amber and on == amber[-1][2] and s <= amber[-1][1] + 0.02:
            amber[-1][1] = max(amber[-1][1], e)
        else:
            amber.append([s, e, on])
    return green, amber


def _join(names):
    """Plain-English join for a dropout callout's held/dropped side —
    ["Left"] -> "Left", ["Left","Centre"] -> "Left and Centre",
    ["Left","Centre","Right"] -> "Left, Centre and Right"."""
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _union(green, amber):
    segs = sorted([(a, b) for a, b in green] + [(a, b) for a, b, w in amber])
    out = []
    for a, b in segs:
        if out and a <= out[-1][1] + 0.02:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _activity_series(histories, start_dt, eff_end, span):
    """PIR movement events (pirdetection rising edges) per bucket, summed across
    the room's sensors — shows when someone was actually MOVING vs present-still.
    Returns {points:[{t,c}], max, bucketMin} or None."""
    bucket = span / BUCKETS if span else 1.0
    counts = {}
    found = False
    for h in histories:
        for mn in h.pir_edges(start_dt, eff_end):
            found = True
            bi = int(mn / bucket) if bucket else 0
            counts[bi] = counts.get(bi, 0) + 1
    if not found:
        return None
    pts = [{"t": round(bi * bucket, 1), "c": c} for bi, c in sorted(counts.items())]
    return {"points": pts, "max": max(counts.values()), "bucketMin": round(bucket, 1)}


def _sleep_proxy(union_ivs, span):
    if not union_ivs:
        return None
    longest = max(union_ivs, key=lambda iv: iv[1] - iv[0])
    settled, up = longest[0], union_ivs[-1][1]
    wake = sum(1 for (a1, b1), (a2, b2) in zip(union_ivs, union_ivs[1:])
               if a1 >= settled and (a2 - b1) >= WAKE_GAP_MIN)
    return {"settledMin": round(settled, 1), "upMin": round(up, 1),
            "inBedMin": round(up - settled), "longestPresenceMin": round(longest[1] - longest[0]),
            "wakeups": wake}


def _r2(pairs):
    return [[round(a, 1), round(b, 1)] for a, b in pairs]


# ---- build ------------------------------------------------------------------
def build():
    """Open the history DB read-only and always close it — an exception
    mid-build must not leak the connection into the plugin host, which lives
    for weeks between restarts."""
    base = indigo.server.getInstallFolderPath()
    db_path = os.path.join(base, "Logs", "indigo_history.sqlite")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return _build_with(con, base)
    finally:
        con.close()


def _cfg(name, default):
    """Read a module-level tunable defensively — a schedule/exec-run script's
    functions can execute with module constants absent from globals (the
    weekly_home_digest v1.2 lesson; Log_Error_Watch does the same)."""
    return globals().get(name, default)


def _build_with(con, base):
    cur = con.cursor()
    now = datetime.now()
    today = now.date()
    dates_seen = set()
    rooms_out = {}

    nights_back = int(_cfg("NIGHTS_BACK", 14))
    for room in _cfg("ROOMS", []):
        if not room.get("sensors"):
            # A room configured with no sensors used to IndexError on
            # ivs_list[0] and abort the ENTIRE rebuild.
            continue
        sh, sm = room["start"]; eh, em = room["end"]
        span = ((eh * 60 + em) + (1440 if room["wrap"] else 0)) - (sh * 60 + sm)
        labels = [s["label"] for s in room["sensors"]]
        # Each sensor's standing in Indigo, so the page can say why a track
        # is empty instead of drawing a confident blank (v1.3).
        status = {}
        for s in room["sensors"]:
            try:
                dev = indigo.devices[s["id"]]
            except Exception:
                status[str(s["id"])] = "missing"
                continue
            if not getattr(dev, "enabled", True):
                status[str(s["id"])] = "disabled"
            elif (getattr(dev, "errorState", "") or "").strip():
                status[str(s["id"])] = "error"
            else:
                status[str(s["id"])] = "ok"
        # Load each sensor's ENTIRE 14-night span once (PK-ranged), then
        # slice per night in Python — replaces the old per-night queries.
        oldest = today - timedelta(days=nights_back - 1)
        span_start = datetime(oldest.year, oldest.month, oldest.day, sh, sm)
        histories = {s["id"]: SensorHistory(cur, s["id"], span_start,
                                            ("onoffstate", "pirdetection"))
                     for s in room["sensors"]}
        by_date = {}
        for back in range(nights_back):
            d = today - timedelta(days=back)
            start_dt = datetime(d.year, d.month, d.day, sh, sm)
            end_dt = datetime(d.year, d.month, d.day, eh, em) + (timedelta(days=1) if room["wrap"] else timedelta())
            if now <= start_dt:
                continue
            eff_end = min(end_dt, now)
            live = now < end_dt
            tracks, stats, ivs_list = {}, {}, []
            for s in room["sensors"]:
                sid = str(s["id"])
                h = histories[s["id"]]
                if not h.has_on_data():
                    tracks[sid] = []; stats[sid] = _stats([], span, 0); ivs_list.append(([], False)); continue
                ivs, nt = h.intervals(start_dt, eff_end)
                tracks[sid] = _r2(ivs)
                stats[sid] = _stats(ivs, span, nt)
                ivs_list.append((ivs, bool(ivs) or nt > 0))
            active = [(i, labels[i], ivs) for i, (ivs, has) in enumerate(ivs_list) if has]
            if len(active) >= 2:
                green, amber = _agreement([ivs for _, _, ivs in active], span)
            elif len(active) == 1:
                green = [list(iv) for iv in sorted(active[0][2])]; amber = []
            else:
                green, amber = [], []
            all_present = len(active) == len(room["sensors"])
            union = _union(green, amber)
            occ = round(sum(b - a for a, b in union))
            dropouts = sorted(
                [{"startMin": round(a, 1), "endMin": round(b, 1), "mins": round(b - a),
                  "held": _join([active[i][1] for i in on]),
                  "dropped": _join([active[i][1] for i in range(len(active)) if i not in on])}
                 for a, b, on in amber if (b - a) >= MIN_DROP_MIN],
                key=lambda x: x["mins"], reverse=True)
            first_on = [st["firstOn"] for st in stats.values() if st["firstOn"] is not None]
            last_off = [st["lastOff"] for st in stats.values() if st["lastOff"] is not None]
            night = {
                "tracks": tracks,
                "both": {"green": _r2(green), "amber": [[round(a, 1), round(b, 1), w] for a, b, w in amber]},
                "stats": stats,
                "summary": {"firstSeenMin": min(first_on) if first_on else None,
                            "lastClearMin": max(last_off) if last_off else None,
                            "occMin": occ, "occPct": round(occ / span * 100) if span else 0,
                            "disagreeMin": round(sum(b - a for a, b, on in amber)),
                            "bothPresent": all_present,
                            "reportingCount": len(active), "sensorCount": len(room["sensors"])},
                "dropouts": dropouts[:3],
                "activity": _activity_series(list(histories.values()), start_dt, eff_end, span),
                "live": live,
                "nowMin": round((now - start_dt).total_seconds() / 60.0, 1) if live else None,
            }
            if room["key"] == "bedroom_1":
                night["sleep"] = _sleep_proxy(union, span)
            ds = d.strftime("%Y-%m-%d")
            by_date[ds] = night
            dates_seen.add(ds)
        rooms_out[room["key"]] = {
            "title": room["title"], "icon": room["icon"],
            "window": {"start": f"{sh:02d}:{sm:02d}", "end": f"{eh:02d}:{em:02d}",
                       "startMinOfDay": sh * 60 + sm, "spanMin": span, "wrap": room["wrap"]},
            "sensorLabels": {str(s["id"]): s["label"] for s in room["sensors"]},
            "sensorOrder": [str(s["id"]) for s in room["sensors"]],
            "sensorStatus": status,
            "byDate": by_date,
        }
    dates = sorted(dates_seen, reverse=True)
    date_labels = {}
    for ds in dates:
        dd = datetime.strptime(ds, "%Y-%m-%d").date()
        delta = (today - dd).days
        if delta == 0:
            date_labels[ds] = "Tonight"
        elif delta == 1:
            date_labels[ds] = "Last night"
        else:
            date_labels[ds] = f"{dd.strftime('%a')} {dd.day} {dd.strftime('%b')}"

    payload = {"_writeTs": now.timestamp(), "generatedLocal": now.strftime(FMT),
               "dates": dates, "labels": date_labels, "rooms": rooms_out}
    # v1.2: beside the script folder, NOT /public (anonymous + reflector-reachable).
    out_dir = os.path.join(os.path.dirname(base), "Python Scripts")
    path = os.path.join(out_dir, OUT_FILENAME)
    # Per-process tmp name: two overlapping runs (the plugin tick plus a
    # hand-run) sharing one ".tmp" could publish a torn or vanished file.
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    # Self-heal: remove the pre-v1.2 anonymous copy wherever this runs.
    legacy = os.path.join(base, LEGACY_PUBLIC_RELPATH)
    try:
        if os.path.isfile(legacy):
            os.remove(legacy)
            log("Presence Watch: removed the old anonymous /public presence.json")
    except OSError:
        pass
    return path, len(dates)


try:
    p, n = build()
    if not globals().get("PRESENCE_WATCH_QUIET"):    # quiet when ticked by the plugin loop
        log(f"Presence Watch: wrote {p} ({n} nights)")
except sqlite3.OperationalError as exc:
    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
        # The SQL Logger's commit outlasted the busy wait. The previous
        # presence_data.json is still on disk; the next tick is 5 min away.
        log("Presence Watch: history DB busy — keeping the last presence data", level="WARNING")
    else:
        log("Presence Watch FAILED:\n" + traceback.format_exc(), level="ERROR")
except Exception:
    log("Presence Watch FAILED:\n" + traceback.format_exc(), level="ERROR")
