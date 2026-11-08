#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugs_mixin.py
# Description: The Plugs page (3.69.0): what every plug that measures its own
#              energy costs a day, each one and all of them together, for
#              today, yesterday, the last 7 and the last 30 days.
#
#              PRICED AT THE CHEAP RATE ONLY (CliveS, 08-11-2026, as for the
#              Air page): the house runs from a battery filled in Flux's cheap
#              window, so every kWh is priced at that window's rate. Each day
#              is priced at the cheap rate published FOR that day, read from
#              the SQL Logger's history of elec_rates_today_json - the rate
#              went from 13.9p to 15.5p on 19-10-2026, and pricing October at
#              November's rate would be wrong. A day with no published list on
#              record shows its energy and no price.
#
#              Thirty days of readings is about 65,000 rows for one busy
#              Shelly, so a finished day is worked out once and kept in
#              plug_costs.json in the plugin's Preferences folder; after that
#              only today is read from the history on each request. All of it
#              runs off the dispatch path, on its own lane.
#              Plugin inherits this.
# Author:      CliveS & Claude Opus 5.5
# Date:        08-11-2026 19:45
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import device_cost as C
import history_db as _history_db

PLUGS_TTL = 300                 # the page asks every 5 minutes
PLUGS_WAIT = 0.75
PLUGS_DAYS = 30                 # today and the 29 days before it
PLUGS_LEDGER = "plug_costs.json"
PLUGS_LEDGER_VERSION = 1
PLUGS_SETTLE_S = 15 * 60        # a day is kept only once it is this long over
RATES_VARIABLE = "elec_rates_today_json"


def day_starts(today, days=PLUGS_DAYS):
    """Local-midnight epochs for the last `days` days, oldest first, the last
    one today. mktime gives each its own offset, so a clocks-change day is
    23 or 25 hours long, as it really is."""
    out = []
    for back in range(days - 1, -1, -1):
        d = today - timedelta(days=back)
        out.append(int(time.mktime(datetime(d.year, d.month, d.day).timetuple())))
    return out


def build_report(plugs, starts, rates, now):
    """The page's reply from plain data, so the tests need no database.

    plugs:  [{"id", "name", "room", "answering", "kwh": [kWh or None per day]}]
            None means nothing was recorded for the plug that day.
    starts: the day_starts the kwh lists line up with.
    rates:  [(pence, start_minute, end_minute) or None per day].
    """
    n = len(starts)

    def priced(kwhs):
        return [C.cost_pence(k, r[0]) if (k is not None and r) else None
                for k, r in zip(kwhs, rates)]

    def span(kwhs, pences, a, b):
        """kWh and pence over days a..b-1 (indexes into the day lists)."""
        ks, ps = kwhs[a:b], pences[a:b]
        used = [k for k in ks if k is not None]
        kwh = round(sum(used), 3) if used else None
        known = [p for p in ps if p is not None]
        unpriced = any(p is None and k for p, k in zip(ps, ks))
        pence = round(sum(known), 2) if known else (0.0 if kwh == 0 else None)
        return {"kwh": kwh, "pence": pence, "unpriced": unpriced}

    def spans(kwhs, pences):
        return {
            "today": span(kwhs, pences, n - 1, n),
            "yesterday": span(kwhs, pences, n - 2, n - 1) if n > 1 else None,
            "week": span(kwhs, pences, max(0, n - 7), n),
            "month": span(kwhs, pences, 0, n),
        }

    out_plugs = []
    tot_k = [None] * n
    tot_p = [None] * n
    for p in plugs:
        kwhs = list(p["kwh"])
        pences = priced(kwhs)
        for i in range(n):
            if kwhs[i] is not None:
                tot_k[i] = round((tot_k[i] or 0) + kwhs[i], 4)
            if pences[i] is not None:
                tot_p[i] = round((tot_p[i] or 0) + pences[i], 2)
        recorded = [i for i, k in enumerate(kwhs) if k is not None]
        since = None
        if recorded and recorded[0] > 0:
            since = datetime.fromtimestamp(starts[recorded[0]]).strftime("%A %-d %B")
        out_plugs.append({
            "id": p["id"], "name": p["name"], "room": p.get("room") or "",
            "answering": bool(p.get("answering", True)),
            **spans(kwhs, pences),
            "since": since,
            "days": [{"kwh": k, "pence": c} for k, c in zip(kwhs, pences)],
        })
    out_plugs.sort(key=lambda x: (-(x["month"]["kwh"] or 0), x["name"].lower()))
    totals = spans(tot_k, tot_p)
    today_rate = rates[-1] if rates else None
    return {
        "ok": True,
        "at": int(now),
        "days": [datetime.fromtimestamp(s).strftime("%Y-%m-%d") for s in starts],
        "plugs": out_plugs,
        "totals": totals,
        "daily": [{"kwh": k, "pence": c} for k, c in zip(tot_k, tot_p)],
        "rate": {"pence": round(today_rate[0], 2), "words": C.rate_words(today_rate)} if today_rate else None,
        "unpricedDays": sum(1 for r in rates if not r),
    }


class PlugsMixin:
    _plugs_lock = threading.Lock()

    def handlePlugCosts(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/plugCosts/

        Body: {} - nothing is needed.

        Reply: build_report's dictionary. Reads only."""
        _payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        state, result = self._offpath_get("plugCosts", self._plug_costs, PLUGS_TTL,
                                          wait=PLUGS_WAIT, lane="plugs")
        if state == "fresh":
            return self._evo_reply(result)
        if state == "failed":
            self.logger.warning(f"[Plugs] adding up the plugs failed: {result}")
            return self._evo_reply({"ok": False, "error": str(result)}, status=500)
        return self._evo_reply({"ok": False, "pending": True, "error": "still adding it up"}, status=503)

    # ---- the meters ------------------------------------------------------

    def _plug_meters(self):
        """[(device, (state, column, kind))] for every enabled device that
        measures its own energy."""
        out = []
        for dev in indigo.devices:
            try:
                if not dev.enabled:
                    continue
                meter = C.meter_for(dev.pluginId, dev.states.keys())
            except Exception:
                continue
            if meter:
                out.append((dev, meter))
        return out

    @staticmethod
    def _plug_room(dev):
        try:
            if dev.folderId and dev.folderId in indigo.devices.folders:
                return indigo.devices.folders[dev.folderId].name
        except Exception:
            pass
        return ""

    # ---- the ledger of finished days --------------------------------------

    def _plug_ledger_path(self):
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, PLUGS_LEDGER)

    def _plug_ledger_load(self):
        try:
            with open(self._plug_ledger_path(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("v") == PLUGS_LEDGER_VERSION \
                    and isinstance(data.get("days"), dict):
                return data
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.warning(f"[Plugs] {PLUGS_LEDGER} could not be read ({exc}); working it out again")
        return {"v": PLUGS_LEDGER_VERSION, "days": {}}

    def _plug_ledger_save(self, ledger):
        path = self._plug_ledger_path()
        tmp = f"{path}.tmp.{threading.get_ident()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(ledger, f, separators=(",", ":"))
            os.replace(tmp, path)
        except Exception as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.logger.warning(f"[Plugs] could not save {PLUGS_LEDGER} ({exc})")

    # ---- the history --------------------------------------------------------

    def _plug_rows(self, hist, conn, dev_id, col, start_epoch):
        """[(epoch, value)] for one state from start_epoch to now, led by the
        last reading before start_epoch so the first slice has a start.
        None when the plug has no history table or no such column."""
        if col not in hist.column_names(conn, dev_id):
            return None
        table = f"device_history_{int(dev_id)}"
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lo, _hi = self._pk_window(hist, conn, table, start_utc)
        pk_sql, pk_args = self._pk_clause(lo, None)
        rows = conn.execute(
            f'SELECT {hist.epoch()}, CAST("{col}" AS REAL) FROM "{table}" '
            f'WHERE ts >= ? AND "{col}" IS NOT NULL{pk_sql} ORDER BY id',
            (start_utc, *pk_args)).fetchall()
        lead = []
        if lo is not None:
            lead = conn.execute(
                f'SELECT {hist.epoch()}, CAST("{col}" AS REAL) FROM "{table}" '
                f'WHERE id < ? AND "{col}" IS NOT NULL ORDER BY id DESC LIMIT 1', (lo,)).fetchall()
        return [(int(e), float(v)) for e, v in list(lead) + list(rows) if e is not None and v is not None]

    @staticmethod
    def _plug_first_epoch(hist, conn, dev_id):
        """When the plug's history begins, or None."""
        table = f"device_history_{int(dev_id)}"
        try:
            row = conn.execute(f'SELECT {hist.epoch()} FROM "{table}" ORDER BY id LIMIT 1').fetchone()
        except Exception:
            return None
        return int(row[0]) if row and row[0] is not None else None

    @staticmethod
    def _rate_history(hist, conn, var_id, start_epoch):
        """[(epoch, rates json)] written to the rates variable since
        start_epoch, oldest first. [] when it is not on record."""
        table = f"variable_history_{int(var_id)}"
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = conn.execute(
                f'SELECT {hist.epoch()}, value FROM "{table}" WHERE ts >= ? ORDER BY id',
                (start_utc,)).fetchall()
        except Exception:
            return []
        return [(int(e), v) for e, v in rows if e is not None and v]

    # ---- the producer -----------------------------------------------------

    def _plug_costs(self):
        """Off the dispatch path: build_report for every plug."""
        with self._plugs_lock:
            return self._plug_costs_locked()

    def _plug_costs_locked(self):
        now = time.time()
        today = date.today()
        starts = day_starts(today)
        keys = [datetime.fromtimestamp(s).strftime("%Y-%m-%d") for s in starts]
        meters = self._plug_meters()
        ledger = self._plug_ledger_load()
        days = ledger["days"]

        try:
            rates_var = indigo.variables[RATES_VARIABLE]
            rates_now = C.cheap_rate(rates_var.value)
            rates_var_id = rates_var.id
        except Exception:
            rates_now, rates_var_id = None, None

        hist = conn = None
        try:
            hist = self._history()
            conn = hist.connect()
        except (ValueError, _history_db.HistoryUnavailable) as exc:
            self.logger.debug(f"[Plugs] no history ({exc}); today only, from the plugs")
            hist = conn = None

        changed = False
        try:
            # Which finished days still need working out, and for whom.
            missing = {}
            for i, key in enumerate(keys[:-1]):
                rec = days.get(key) or {}
                kwh = rec.get("kwh") or {}
                need = [dev.id for dev, _m in meters if str(dev.id) not in kwh]
                if need or "rate" not in rec:
                    missing[i] = need

            rates_by_day = {}
            if conn is not None and rates_var_id is not None and any("rate" not in (days.get(keys[i]) or {}) for i in missing):
                published = self._rate_history(hist, conn, rates_var_id, starts[min(missing)])
                for i in missing:
                    end = starts[i + 1]
                    rates_by_day[i] = C.rate_for_day(published, starts[i], end)

            per_dev = {}
            for dev, (state, col, kind) in meters:
                need_days = [i for i, need in missing.items() if dev.id in need]
                first_i = min(need_days) if need_days else len(starts) - 1
                values = [None] * len(starts)
                rows = None
                if conn is not None:
                    try:
                        rows = self._plug_rows(hist, conn, dev.id, col, starts[first_i])
                    except Exception as exc:
                        self.logger.debug(f"[Plugs] {dev.name}: history read failed ({exc})")
                        rows = None
                if rows is not None:
                    first = self._plug_first_epoch(hist, conn, dev.id)
                    got = C.daily_kwh(C.slices_for(rows, kind), starts[first_i:])
                    for j, kwh in enumerate(got):
                        i = first_i + j
                        end = starts[i + 1] if i + 1 < len(starts) else now
                        values[i] = None if (first is None or first >= end) else kwh
                if values[-1] is None and kind == "daily":
                    try:                                  # no history: the plug's own count
                        values[-1] = round(float(dev.states[state]), 4)
                    except (KeyError, TypeError, ValueError):
                        pass
                per_dev[dev.id] = values

            # Keep the finished days that have settled. Never without the
            # history: a day kept as "nothing recorded" would stay so for good.
            for i, need in missing.items():
                if conn is None or now < starts[i + 1] + PLUGS_SETTLE_S:
                    continue
                rec = days.setdefault(keys[i], {})
                rec.setdefault("kwh", {})
                for dev_id in need:
                    rec["kwh"][str(dev_id)] = per_dev[dev_id][i]
                if "rate" not in rec and i in rates_by_day:
                    r = rates_by_day[i]
                    rec["rate"] = list(r) if r else None
                changed = True
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        # Drop days that have fallen off the page.
        for key in list(days):
            if key < keys[0]:
                del days[key]
                changed = True
        if changed:
            self._plug_ledger_save(ledger)

        rates = []
        for i, key in enumerate(keys):
            if i == len(keys) - 1:
                rates.append(rates_now)
                continue
            rec = days.get(key) or {}
            if "rate" in rec:
                r = rec["rate"]
                rates.append(tuple(r) if r else None)
            else:
                rates.append(rates_by_day.get(i))

        plugs = []
        for dev, _meter in meters:
            values = []
            for i, key in enumerate(keys):
                kept = ((days.get(key) or {}).get("kwh") or {})
                if i < len(keys) - 1 and str(dev.id) in kept:
                    values.append(kept[str(dev.id)])
                else:
                    values.append(per_dev[dev.id][i])
            plugs.append({"id": dev.id, "name": dev.name, "room": self._plug_room(dev),
                          "answering": not bool(getattr(dev, "errorState", "")),
                          "kwh": values})
        return build_report(plugs, starts, rates, now)
