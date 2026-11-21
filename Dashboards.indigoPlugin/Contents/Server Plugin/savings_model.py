#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    savings_model.py
# Description: The Savings page's sums (3.71.0), from plain data so the tests
#              need no Indigo, no network and no database.
#
#              The question is "what has the solar and battery saved", answered
#              as five steps that each change one thing, so every pound lands in
#              exactly one place:
#
#                1. No kit      the house's own use, every kWh bought at the
#                               standard capped price (Flexible Octopus), plus
#                               its standing charge.
#                2. Solar       the same use with the panels and no battery:
#                               each half hour the house uses what the panels
#                               make, buys the shortfall at the capped price
#                               and sells the rest at the standard export
#                               price (Outgoing Octopus).
#                3. Tariff      step 2's energy priced at the tariff really in
#                               force each half hour, with its standing charge.
#                4. Battery     what the meters really recorded (import and
#                               export) at those same prices.
#                5. Extras      grid-event payments (Axle) and Octopus free-hour
#                               credits, taken off.
#
#              Saved = step 1 - step 5. Each step's difference is that step's
#              share. Nothing here is invented: a day with no usable record is
#              left out and counted, and a day priced from daily totals because
#              its half hours were not recorded is marked as estimated.
# Author:      CliveS & Claude Opus 5.5
# Date:        21-11-2026
# Version:     1.0

import bisect
import math
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

FULL_DAY_SLOTS = 44          # a day with at least this many half hours is priced slot by slot
BALANCE_LIMIT_KWH = 3.0      # a daily-only record that does not balance by more is unusable
BATTERY_FALLBACK_KWH = 35.0  # only if the battery manager does not say


# ---------------------------------------------------------------- rates ----

class RateTable:
    """Published prices over time: [(from_epoch, to_epoch_or_inf, pence)].

    at(epoch) gives the price in force then, or None outside every interval."""

    def __init__(self, intervals):
        rows = []
        for frm, to, p in intervals or []:
            try:
                f = float(frm)
                t = math.inf if to is None else float(to)
                v = float(p)
            except (TypeError, ValueError):
                continue
            if t > f and math.isfinite(v):
                rows.append((f, t, v))
        rows.sort()
        self.rows = rows
        self.starts = [r[0] for r in rows]

    def __bool__(self):
        return bool(self.rows)

    def at(self, epoch):
        i = bisect.bisect_right(self.starts, epoch) - 1
        # The latest-starting interval that covers the moment wins; one step
        # back covers an open-ended price followed by a dated one.
        for j in (i, i - 1):
            if j >= 0:
                f, t, v = self.rows[j]
                if f <= epoch < t:
                    return v
        return None


def iso_to_epoch(text):
    """Octopus's '2026-11-18T19:00:00Z' to an epoch, or None."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def octopus_intervals(results, payment_method="DIRECT_DEBIT"):
    """Octopus `results` rows to RateTable intervals (pence inc VAT). Rows for
    another payment method are skipped; rows with none apply to everyone."""
    out = []
    for r in results or []:
        pm = r.get("payment_method")
        if pm and payment_method and pm != payment_method:
            continue
        frm = iso_to_epoch(r.get("valid_from"))
        to = iso_to_epoch(r.get("valid_to"))
        if frm is None:
            continue
        out.append((frm, to, r.get("value_inc_vat")))
    return out


# ---------------------------------------------------------------- inputs ---

def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def slot_epoch(text, tz=None):
    """A slot's local naive ISO time to an epoch, in `tz` (None = this machine's
    local time, which is the battery manager's)."""
    dt = datetime.fromisoformat(str(text))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz) if tz is not None else dt.astimezone()
    return dt.timestamp()


def rows_to_slots(fields, rows):
    """/api/halfhourly's list rows to dicts."""
    out = []
    for r in rows or []:
        if isinstance(r, (list, tuple)) and len(r) == len(fields):
            out.append(dict(zip(fields, r)))
    return out


def day_is_usable(rec):
    """A daily record is usable on its own when its flows balance: what came
    in (solar and import) equals what went out (house, export) plus what the
    battery kept. Early records rebuilt from the Sigenergy app have days with
    the solar missing; those do not balance and are left out."""
    pv, imp = _num(rec.get("pv_kwh")), _num(rec.get("grid_import_kwh"))
    exp, home = _num(rec.get("grid_export_kwh")), _num(rec.get("home_kwh"))
    if None in (pv, imp, exp, home) or home <= 0:
        return False
    ch = _num(rec.get("battery_charge_kwh")) or 0.0
    dis = _num(rec.get("battery_discharge_kwh")) or 0.0
    return abs(pv + imp - exp - home - (ch - dis)) <= BALANCE_LIMIT_KWH


# ---------------------------------------------------------------- model ----

def _empty_day(d):
    return {"date": d, "home": 0.0, "pv": 0.0, "imp": 0.0, "exp": 0.0,
            "nokit": 0.0, "solar": 0.0, "tariff": 0.0, "actual": 0.0,
            "events": 0.0, "credits": 0.0,
            "direct": 0.0, "solar_stored": 0.0, "solar_exported": 0.0,
            "home_solar": 0.0, "home_grid_direct": 0.0, "home_grid_battery": 0.0,
            "batt_export": 0.0, "estimated": False, "tariff_name": "unknown",
            "unpriced": False, "billed": False, "model_actual": 0.0}


class SavingsModel:
    """Works out every day once; `summary(start, end)` then adds up any range.

    daily:     the battery manager's daily records (/api/daily).
    slots:     half-hourly dicts (rows_to_slots of /api/halfhourly).
    cap_unit / cap_standing / std_export / flux_export: RateTables, pence.
    events:    Axle payments, [{"type", "start", "end", "pence", "kwh"}] as
               /api/halfhourly's axle_payments gives them.
    credits:   [{"date": "YYYY-MM-DD", "pence": int}] free-hour credits.
    capacity:  usable battery kWh, to turn state of charge into energy.
    """

    def __init__(self, daily, slots, cap_unit, cap_standing, std_export,
                 flux_export=None, events=None, credits=None, capacity=None, tz=None):
        self.tz = tz
        self.cap_unit = cap_unit
        self.cap_standing = cap_standing
        self.std_export = std_export
        self.flux_export = flux_export or RateTable([])
        self.capacity = _num(capacity) or BATTERY_FALLBACK_KWH
        self.records = OrderedDict()
        for rec in daily or []:
            d = str(rec.get("date") or "")
            if len(d) == 10:
                self.records[d] = rec
        self.days = OrderedDict()
        self.missing = []        # dates with a record that could not be used
        self.notes = []
        self._build(slots or [], events or [], credits or [])

    # -- helpers --------------------------------------------------------------

    def _noon_epoch(self, d):
        return slot_epoch(f"{d}T12:00:00", self.tz)

    def _your_standing_gbp(self, rec, d):
        v = _num(rec.get("elec_standing_gbp"))
        if v is not None and rec.get("cost_settled"):
            return v
        p = _num(rec.get("elec_standing_p_day"))
        if p is not None:
            return p / 100.0
        cap = self.cap_standing.at(self._noon_epoch(d))
        return cap / 100.0 if cap is not None else 0.0

    def _export_rate(self, rec, epoch):
        if str(rec.get("tariff") or "").lower() == "flux":
            p = self.flux_export.at(epoch)
            if p is not None:
                return p
        p = _num(rec.get("export_rate_p"))
        if p is not None and str(rec.get("export_rate_basis") or "") != "weighted":
            return p
        q = self.std_export.at(epoch)
        return q if q is not None else (p or 0.0)

    # -- the work -------------------------------------------------------------

    def _build(self, slots, events, credits):
        by_day = OrderedDict()
        for s in slots:
            st = s.get("start")
            if not st:
                continue
            by_day.setdefault(str(st)[:10], []).append(s)

        # How much of the smaller of a day's solar and use the house really used
        # as it was made, measured on days recorded half-hourly; used to estimate
        # the days that were not. Per calendar month, nearest month otherwise.
        ratio_num, ratio_den = {}, {}

        # A few early records carry no tariff name or day rate (the manager was
        # new); borrow both from the nearest day that has them.
        known = [(d, r) for d, r in self.records.items() if _num(r.get("rate_today_p")) is not None]
        for d, rec in self.records.items():
            if _num(rec.get("rate_today_p")) is None and known:
                near = min(known, key=lambda kr: abs(_day_index(kr[0]) - _day_index(d)))[1]
                rec = dict(rec)
                rec["rate_today_p"] = near.get("rate_today_p")
                if str(rec.get("tariff") or "unknown").lower() == "unknown":
                    rec["tariff"] = near.get("tariff")
                rec["_borrowed_rate"] = True
                self.records[d] = rec

        pool = None                # [solar kWh, grid kWh] in the battery
        for d, rec in self.records.items():
            day_slots = by_day.get(d, [])
            if len(day_slots) >= FULL_DAY_SLOTS:
                day, pool = self._day_from_slots(d, rec, day_slots, pool)
                m = d[:7]
                ratio_num[m] = ratio_num.get(m, 0.0) + day["direct"]
                ratio_den[m] = ratio_den.get(m, 0.0) + min(day["pv"], day["home"])
                self.days[d] = day
            elif day_is_usable(rec):
                self.days[d] = None          # filled below, once the ratios exist
                pool = None
            else:
                self.missing.append(d)
                pool = None

        months = sorted(m for m in ratio_den if ratio_den[m] > 0)
        for d, day in list(self.days.items()):
            if day is None:
                m = d[:7]
                if m not in months and months:
                    m = min(months, key=lambda x: abs(_month_index(x) - _month_index(d[:7])))
                k = (ratio_num[m] / ratio_den[m]) if m in ratio_den and ratio_den[m] else 0.6
                self.days[d] = self._day_from_totals(d, self.records[d], min(1.0, k))

        # Where Octopus has settled the day, its own bill is the real figure
        # paid. The model's figure is kept beside it, so the page can say how
        # closely the two agree.
        for d, day in self.days.items():
            bill = octopus_bill_gbp(self.records[d])
            day["model_actual"] = day["actual"]
            if bill is not None:
                day["actual"] = bill
                day["billed"] = True

        # The paid extras, one list the page can show line by line. A payment
        # dated on a day with no usable record is listed but not counted, so
        # every pound in the totals has a day behind it.
        self.extras = []
        for e in events:
            item = axle_item(e, self.tz)
            if item:
                self.extras.append(item)
        for c in credits:
            v = _num(c.get("pence"))
            d = str(c.get("date") or "")[:10]
            if v is not None and len(d) == 10:
                self.extras.append({"date": d, "kind": "free_hour", "gbp": round(v / 100.0, 2),
                                    "kwh": None, "counted": True})
        self.extras.sort(key=lambda x: x["date"])
        for x in self.extras:
            day = self.days.get(x["date"])
            if not x["counted"]:
                continue
            if day is None:
                x["counted"] = False
                x["why"] = "no record that day"
                continue
            day["credits" if x["kind"] == "free_hour" else "events"] += x["gbp"]

    def _day_from_slots(self, d, rec, slots, pool):
        day = _empty_day(d)
        day["tariff_name"] = str(rec.get("tariff") or "unknown").lower()
        cap_std = self.cap_standing.at(self._noon_epoch(d))
        your_std = self._your_standing_gbp(rec, d)
        day_rate = _num(rec.get("rate_today_p"))
        if day_rate is None:
            # Agile days carry no single day rate: a slot with no price takes
            # the day's average half-hourly price.
            seen = [_num(s.get("import_rate_p")) for s in slots]
            seen = [v for v in seen if v is not None]
            day_rate = sum(seen) / len(seen) if seen else None
        cap = self.capacity
        for s in slots:
            pv = max(_num(s.get("pv_kwh")) or 0.0, 0.0)
            home = max(_num(s.get("home_kwh")) or 0.0, 0.0)
            imp = max(_num(s.get("import_kwh")) or 0.0, 0.0)
            exp = max(_num(s.get("export_kwh")) or 0.0, 0.0)
            try:
                ep = slot_epoch(s.get("start"), self.tz) + 900   # the slot's middle
            except (TypeError, ValueError):
                continue
            c_imp = self.cap_unit.at(ep)
            s_exp = self.std_export.at(ep)
            r_imp = _num(s.get("import_rate_p"))
            if r_imp is None:
                r_imp = day_rate
            r_exp = self._export_rate(rec, ep)
            if c_imp is None or s_exp is None or r_imp is None:
                day["unpriced"] = True
                c_imp = c_imp or 0.0
                s_exp = s_exp or 0.0
                r_imp = r_imp or 0.0

            direct = min(pv, home)
            so_imp = home - direct
            so_exp = pv - direct
            day["home"] += home
            day["pv"] += pv
            day["imp"] += imp
            day["exp"] += exp
            day["nokit"] += home * c_imp / 100.0
            day["solar"] += (so_imp * c_imp - so_exp * s_exp) / 100.0
            day["tariff"] += (so_imp * r_imp - so_exp * r_exp) / 100.0
            day["actual"] += (imp * r_imp - exp * r_exp) / 100.0

            # Where the energy went. The battery is a mixed pool of solar and
            # grid energy; what leaves it carries the mix it holds.
            net = pv + imp - exp - home              # + into the battery
            charge, dis = max(net, 0.0), max(-net, 0.0)
            surplus = pv - direct
            deficit = home - direct
            solar_ch = min(charge, surplus)
            grid_ch = charge - solar_ch
            dis_home = min(dis, deficit)
            dis_exp = dis - dis_home
            if pool is None:
                soc0 = _num(s.get("soc_start"))
                e0 = cap * soc0 / 100.0 if soc0 is not None else 0.0
                pool = [e0, 0.0, 1.0]     # what the battery held at the start: counted as solar
            held = pool[0] + pool[1]
            # An empty pool (no state of charge to reconcile against) keeps the
            # last mix it had, rather than calling whatever comes out solar.
            fs = pool[0] / held if held > 1e-9 else pool[2]
            day["direct"] += direct
            day["solar_stored"] += solar_ch
            day["solar_exported"] += max(surplus - solar_ch, 0.0)
            day["home_solar"] += direct + dis_home * fs
            day["home_grid_battery"] += dis_home * (1.0 - fs)
            day["home_grid_direct"] += max(deficit - dis_home, 0.0)
            day["batt_export"] += dis_exp
            out_s, out_g = dis * fs, dis * (1.0 - fs)
            pool = [max(pool[0] - out_s, 0.0) + solar_ch, max(pool[1] - out_g, 0.0) + grid_ch, fs]
            soc1 = _num(s.get("soc_end"))
            total = pool[0] + pool[1]
            if total > 1e-9:
                pool[2] = pool[0] / total
                if soc1 is not None:
                    scale = (cap * soc1 / 100.0) / total      # losses come off both in proportion
                    pool = [pool[0] * scale, pool[1] * scale, pool[2]]

        if cap_std is None:
            day["unpriced"] = True
            cap_std = 0.0
        day["nokit"] += cap_std / 100.0
        day["solar"] += cap_std / 100.0
        day["tariff"] += your_std
        day["actual"] += your_std
        return day, pool

    def _day_from_totals(self, d, rec, k):
        day = _empty_day(d)
        day["estimated"] = True
        day["tariff_name"] = str(rec.get("tariff") or "unknown").lower()
        ep = self._noon_epoch(d)
        pv = _num(rec.get("pv_kwh")) or 0.0
        home = _num(rec.get("home_kwh")) or 0.0
        imp = _num(rec.get("grid_import_kwh")) or 0.0
        exp = _num(rec.get("grid_export_kwh")) or 0.0
        c_imp = self.cap_unit.at(ep)
        s_exp = self.std_export.at(ep)
        cap_std = self.cap_standing.at(ep)
        r_imp = _num(rec.get("rate_today_p"))
        r_exp = _num(rec.get("export_rate_p"))
        if r_exp is None:
            r_exp = s_exp
        if None in (c_imp, s_exp, cap_std, r_imp, r_exp):
            day["unpriced"] = True
        c_imp, s_exp, cap_std = c_imp or 0.0, s_exp or 0.0, cap_std or 0.0
        r_imp, r_exp = r_imp or 0.0, r_exp or 0.0
        direct = k * min(pv, home)
        so_imp, so_exp = home - direct, pv - direct
        your_std = self._your_standing_gbp(rec, d)
        day.update({"home": home, "pv": pv, "imp": imp, "exp": exp})
        day["nokit"] = home * c_imp / 100.0 + cap_std / 100.0
        day["solar"] = (so_imp * c_imp - so_exp * s_exp + cap_std) / 100.0
        day["tariff"] = (so_imp * r_imp - so_exp * r_exp) / 100.0 + your_std
        day["actual"] = (imp * r_imp - exp * r_exp) / 100.0 + your_std
        # Sources: before Flux the battery was filled from the panels, so the
        # grid's share of the house is what was imported.
        home_grid = min(imp, home)
        day["direct"] = direct
        day["home_solar"] = home - home_grid
        day["home_grid_direct"] = home_grid
        ch = _num(rec.get("battery_charge_kwh")) or 0.0
        day["solar_stored"] = min(ch, max(pv - direct, 0.0))
        day["solar_exported"] = max(pv - direct - day["solar_stored"], 0.0)
        return day

    # -- adding up ------------------------------------------------------------

    def summary(self, start=None, end=None):
        """Totals for the days start..end inclusive ('YYYY-MM-DD'), all days by
        default."""
        keys = ("home", "pv", "imp", "exp", "nokit", "solar", "tariff", "actual",
                "events", "credits", "direct", "solar_stored", "solar_exported",
                "home_solar", "home_grid_direct", "home_grid_battery", "batt_export")
        tot = {k: 0.0 for k in keys}
        n = est = unpriced = billed = 0
        bill_model = bill_octopus = 0.0
        first = last = None
        eras = []
        for d, day in self.days.items():
            if (start and d < start) or (end and d > end):
                continue
            n += 1
            est += 1 if day["estimated"] else 0
            unpriced += 1 if day["unpriced"] else 0
            if day["billed"]:
                billed += 1
                bill_model += day["model_actual"]
                bill_octopus += day["actual"]
            first = first or d
            last = d
            for k in keys:
                tot[k] += day[k]
            # Eras run in date order, so going back to an earlier tariff
            # starts a new one rather than merging with the old.
            if not eras or eras[-1]["name"] != day["tariff_name"]:
                eras.append({"name": day["tariff_name"], "days": 0, "first": d, "last": d,
                             "saved": 0.0, "tariffEffect": 0.0, "pv": 0.0})
            era = eras[-1]
            era["days"] += 1
            era["last"] = d
            era["saved"] += day["nokit"] - (day["actual"] - day["events"] - day["credits"])
            era["tariffEffect"] += day["solar"] - day["tariff"]
            era["pv"] += day["pv"]
        missing = [d for d in self.missing if not ((start and d < start) or (end and d > end))]
        paid = tot["actual"] - tot["events"] - tot["credits"]
        steps = {
            "nokit": tot["nokit"],
            "solar": tot["nokit"] - tot["solar"],
            "tariff": tot["solar"] - tot["tariff"],
            "battery": tot["tariff"] - tot["actual"],
            "extras": tot["events"] + tot["credits"],
            "paid": paid,
        }
        home = tot["home"]
        return {
            "days": n, "estimatedDays": est, "unpricedDays": unpriced,
            "missingDays": len(missing), "first": first, "last": last,
            "saved": tot["nokit"] - paid,
            "steps": {k: round(v, 2) for k, v in steps.items()},
            "events": round(tot["events"], 2), "credits": round(tot["credits"], 2),
            "energy": {k: round(tot[k], 1) for k in
                       ("home", "pv", "imp", "exp", "direct", "solar_stored", "solar_exported",
                        "home_solar", "home_grid_direct", "home_grid_battery", "batt_export")},
            "selfSufficiencyPct": round(100.0 * tot["home_solar"] / home, 1) if home else None,
            "solarOnlySelfUsePct": round(100.0 * tot["direct"] / home, 1) if home else None,
            "pricePaidP": round(100.0 * paid / home, 1) if home else None,
            "priceNoKitP": round(100.0 * tot["nokit"] / home, 1) if home else None,
            "eras": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items()}
                     for e in eras],
            "billedDays": billed,
            "billCheck": ({"model": round(bill_model, 2), "octopus": round(bill_octopus, 2)}
                          if billed else None),
        }

    def extras_in(self, start=None, end=None):
        """The paid extras dated start..end, oldest first."""
        return [dict(x) for x in self.extras
                if not ((start and x["date"] < start) or (end and x["date"] > end))]

    def weeks(self, start=None, end=None):
        """Saved per week (Monday to Sunday) with the solar made, oldest first."""
        out = OrderedDict()
        for d, day in self.days.items():
            if (start and d < start) or (end and d > end):
                continue
            dt = date.fromisoformat(d)
            monday = (dt - timedelta(days=dt.weekday())).isoformat()
            w = out.setdefault(monday, {"week": monday, "days": 0, "saved": 0.0, "pv": 0.0,
                                        "estimated": False})
            w["days"] += 1
            w["saved"] += day["nokit"] - (day["actual"] - day["events"] - day["credits"])
            w["pv"] += day["pv"]
            w["estimated"] = w["estimated"] or day["estimated"]
        return [{**w, "saved": round(w["saved"], 2), "pv": round(w["pv"], 1)} for w in out.values()]

    def months(self):
        """{'YYYY-MM': {"days", "saved", "pv"}} for every month on record."""
        out = OrderedDict()
        for d, day in self.days.items():
            m = out.setdefault(d[:7], {"days": 0, "saved": 0.0, "pv": 0.0})
            m["days"] += 1
            m["saved"] += day["nokit"] - (day["actual"] - day["events"] - day["credits"])
            m["pv"] += day["pv"]
        return out

    def best_and_worst(self, start=None, end=None):
        best = worst = None
        for d, day in self.days.items():
            if (start and d < start) or (end and d > end):
                continue
            s = day["nokit"] - (day["actual"] - day["events"] - day["credits"])
            if best is None or s > best[1]:
                best = (d, s, day["pv"])
            if worst is None or s < worst[1]:
                worst = (d, s, day["pv"])
        f = (lambda t: {"date": t[0], "saved": round(t[1], 2), "pv": round(t[2], 1)} if t else None)
        return f(best), f(worst)


def _month_index(m):
    y, mo = m.split("-")
    return int(y) * 12 + int(mo)


def _day_index(d):
    return date.fromisoformat(d).toordinal()


def _local_date(text, tz):
    ep = iso_to_epoch(text)
    if ep is None:
        return None
    dt = datetime.fromtimestamp(ep, tz) if tz is not None else datetime.fromtimestamp(ep)
    return dt.date().isoformat()


def axle_item(t, tz=None):
    """One Axle payment as an extras line, or None if it carries no amount.

    A grid event is dated by its start. A monthly top-up is dated on the last
    day of the month it pays for. A referral credit is money for signing
    someone up, not something the kit earned, so it is listed and not
    counted."""
    pence = _num(t.get("pence"))
    if pence is None:
        return None
    kind = str(t.get("type") or "").lower()
    if kind == "flex event":
        d, k = _local_date(t.get("start"), tz), "grid_event"
    elif "top-up" in kind or "top up" in kind:
        # Axle's months run midnight to midnight UTC: read the end in UTC, or
        # July's 23:59:59 becomes 1 August in summer time.
        d, k = _local_date(t.get("end") or t.get("start"), timezone.utc), "top_up"
    else:
        d, k = _local_date(t.get("start"), tz), "other"
    if not d:
        return None
    kwh = _num(t.get("kwh"))
    item = {"date": d, "kind": k, "gbp": round(pence / 100.0, 2),
            "kwh": round(abs(kwh), 2) if kwh is not None else None,
            "counted": k != "other"}
    if k == "other":
        item["why"] = "not earned by the kit"
        item["label"] = str(t.get("type") or "")
    return item


def octopus_bill_gbp(rec):
    """The day's electricity bill as Octopus settled it (units - export +
    standing), or None when it has not settled."""
    if not rec.get("cost_settled"):
        return None
    u = _num(rec.get("elec_unit_cost_gbp"))
    x = _num(rec.get("export_revenue_gbp"))
    s = _num(rec.get("elec_standing_gbp"))
    if None in (u, x, s):
        return None
    return u - x + s


# ---------------------------------------------------------------- settings -

SAVINGS_NUMBERS = {
    "systemCost": ("what the system cost", 10_000_000),
    "quoteAnnualSaving": ("the yearly saving the quote promised", 1_000_000),
    "quoteAnnualKwh": ("the yearly solar the quote promised", 10_000_000),
    "quotePaybackYears": ("the payback the quote promised", 100),
}


def clean_savings_settings(raw):
    """The Settings page's Savings fields to the stored shape.

    Returns (dict, None) or (None, "plain-English reason"). Blank fields are
    left out; anything else must be a number in range, or a real date."""
    if not isinstance(raw, dict):
        return None, "the savings settings must be an object"
    out = {}
    for key, (words, top) in SAVINGS_NUMBERS.items():
        v = raw.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if isinstance(v, bool):
            return None, f"{words} must be a number"
        try:
            n = float(str(v).replace(",", "").replace("£", "").strip())
        except ValueError:
            return None, f"{words} must be a number"
        if not math.isfinite(n) or n < 0 or n > top:
            return None, f"{words} is out of range"
        out[key] = int(n) if n == int(n) else round(n, 2)
    d = raw.get("installDate")
    if d is not None and str(d).strip():
        try:
            out["installDate"] = date.fromisoformat(str(d).strip()).isoformat()
        except ValueError:
            return None, "the date it started working must be a date"
    return out, None


# ---------------------------------------------------------------- payback --

def project_year(months, today):
    """A year's saving and solar at the pace recorded so far.

    Each calendar month counts at its own recorded daily average. A month not
    yet on record (the dark months, for a system started in spring) counts at
    the daily average of the slowest month on record with at least two weeks
    in it, named in `basis` - deliberately cautious, since December and
    January are darker still. Returns {"saved", "pv", "filled": [month
    numbers filled in], "basis"} or None with nothing on record."""
    per = {}
    for m, v in months.items():
        if v["days"]:
            mo = int(m[5:7])
            a = per.setdefault(mo, [0, 0.0, 0.0])
            a[0] += v["days"]
            a[1] += v["saved"]
            a[2] += v["pv"]
    if not per:
        return None
    enough = [m for m, v in months.items() if v["days"] >= 14]
    pool = enough or [m for m, v in months.items() if v["days"]]
    ref = min(pool, key=lambda m: months[m]["saved"] / months[m]["days"])
    rv = months[ref]
    ref_rate = (rv["saved"] / rv["days"], rv["pv"] / rv["days"]) if rv["days"] else (0.0, 0.0)
    saved = pv = 0.0
    filled = []
    year = today.year
    for mo in range(1, 13):
        nd = (date(year + (mo == 12), mo % 12 + 1, 1) - date(year, mo, 1)).days
        if mo in per and per[mo][0] >= 7:
            saved += per[mo][1] / per[mo][0] * nd
            pv += per[mo][2] / per[mo][0] * nd
        else:
            saved += ref_rate[0] * nd
            pv += ref_rate[1] * nd
            filled.append(mo)
    return {"saved": round(saved, 2), "pv": round(pv, 1), "filled": filled, "basis": ref}


def payback(cost, saved_so_far, annual, install, today):
    """Paid back so far, and the date it is likely to be paid off at `annual`
    a year. None when the cost is not set."""
    cost = _num(cost)
    if not cost or cost <= 0:
        return None
    out = {"cost": round(cost, 2), "savedSoFar": round(saved_so_far, 2),
           "pct": round(100.0 * saved_so_far / cost, 1)}
    if annual and annual > 0:
        left = max(cost - saved_so_far, 0.0)
        years_left = left / annual
        out["yearsTotal"] = round(cost / annual, 1)
        out["paidOffDate"] = (today + timedelta(days=round(years_left * 365.25))).isoformat()
        if install:
            try:
                out["yearsFromInstall"] = round(
                    (today - date.fromisoformat(install)).days / 365.25 + years_left, 1)
            except ValueError:
                pass
    return out
