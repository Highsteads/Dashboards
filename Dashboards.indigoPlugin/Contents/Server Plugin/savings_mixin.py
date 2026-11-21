#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    savings_mixin.py
# Description: The Savings page (3.71.0): what the solar and battery have saved
#              against the same house with neither on the standard capped
#              tariff, in five steps (savings_model.py does the sums).
#
#              Its inputs: SigenEnergyManager's daily records (/api/daily),
#              half-hourly slots, Axle payments and free-hour credits
#              (/api/halfhourly, SEM 5.146.0), the battery size and tariff
#              codes (/api/status), and Octopus's own published prices for
#              Flexible Octopus, Outgoing Octopus and the Flux export bands,
#              read from Octopus's public price list (no account, only the
#              region letter) and kept for a day in savings_rates.json.
#
#              One build reads months of slots, so it runs on its own off-path
#              lane and the reply (every period at once) is kept 15 minutes.
#              Plugin inherits this.
# Author:      CliveS & Claude Opus 5.5
# Date:        21-11-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import json
import os
import threading
import time
import urllib.request
from datetime import date, timedelta

import savings_model as SM

SAVINGS_TTL = 15 * 60
SAVINGS_WAIT = 0.75
SAVINGS_DAYS = 800                     # what /api/daily and /api/halfhourly allow
RATES_FILE = "savings_rates.json"
RATES_MAX_AGE = 24 * 3600
OCTOPUS_API = "https://api.octopus.energy/v1/products"
# Octopus's standard products. Looked up by name first (codes change when
# Octopus relaunches a product); these are the codes in use in November 2026.
FLEXIBLE_NAME, FLEXIBLE_CODE = "Flexible Octopus", "VAR-22-11-01"
OUTGOING_NAME, OUTGOING_CODE = "Outgoing Octopus", "OUTGOING-VAR-24-10-26"

PERIODS = (("1m", 30), ("3m", 91), ("ytd", None), ("all", None))


def period_bounds(key, last):
    """(start, end) dates for a period ending on `last` ('YYYY-MM-DD')."""
    end = date.fromisoformat(last)
    if key == "all":
        return None, last
    if key == "ytd":
        return date(end.year, 1, 1).isoformat(), last
    days = dict(PERIODS)[key]
    return (end - timedelta(days=days - 1)).isoformat(), last


def region_of(tariff_code):
    """The region letter at the end of an Octopus tariff code
    ('E-1R-FLUX-IMPORT-23-02-14-F' -> 'F'), or None."""
    code = str(tariff_code or "").strip()
    if len(code) > 2 and code[-2] == "-" and code[-1].isalpha():
        return code[-1].upper()
    return None


def product_of(tariff_code):
    """'E-1R-FLUX-EXPORT-23-02-14-F' -> 'FLUX-EXPORT-23-02-14', or None."""
    code = str(tariff_code or "").strip()
    if code.startswith("E-1R-") and region_of(code):
        return code[5:-2]
    return None


def build_reply(model, settings, today, rates_note=None):
    """Everything the page draws, from a built SavingsModel. Plain data in,
    plain data out, so the tests drive it directly."""
    days = list(model.days)
    if not days:
        return {"ok": True, "empty": True,
                "reason": "There are no usable daily records from the battery manager yet."}
    last = days[-1]
    periods = {}
    for key, _n in PERIODS:
        start, end = period_bounds(key, last)
        s = model.summary(start, end)
        if not s["days"]:
            continue
        best, worst = model.best_and_worst(start, end)
        s.update({"weeks": model.weeks(start, end), "best": best, "worst": worst,
                  "extrasList": model.extras_in(start, end)})
        s["saved"] = round(s["saved"], 2)
        periods[key] = s
    allp = periods.get("all") or {}
    proj = SM.project_year(model.months(), today)
    pb = SM.payback(settings.get("systemCost"), allp.get("saved", 0.0),
                    proj["saved"] if proj else None, settings.get("installDate"), today)
    quote = None
    if any(settings.get(k) is not None for k in ("quoteAnnualSaving", "quoteAnnualKwh",
                                                  "quotePaybackYears")):
        quote = {"annualSaving": settings.get("quoteAnnualSaving"),
                 "annualKwh": settings.get("quoteAnnualKwh"),
                 "paybackYears": settings.get("quotePaybackYears")}
    install = settings.get("installDate")
    before_records = None
    if install and days and install < days[0]:
        before_records = (date.fromisoformat(days[0]) - date.fromisoformat(install)).days
    return {
        "ok": True,
        "at": int(time.time()),
        "first": days[0],
        "last": last,
        "periods": periods,
        "projection": proj,
        "payback": pb,
        "quote": quote,
        "installDate": install,
        "daysBeforeRecords": before_records,
        "missing": list(model.missing),
        "rates": rates_note or {},
    }


class SavingsMixin:
    _savings_rates_lock = threading.Lock()

    def handleSavingsReport(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/savingsReport/

        Body: {} - every period comes back at once.

        Reply: build_report's dictionary. Reads only."""
        _payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        if not self._sigen_available():
            return self._evo_reply({"ok": False, "reason": "sem_absent",
                                    "error": "SigenEnergyManager is not installed"}, status=503)
        state, result = self._offpath_get("savingsReport", self._savings_build, SAVINGS_TTL,
                                          wait=SAVINGS_WAIT, lane="savings")
        if state == "fresh":
            return self._evo_reply(result)
        if state == "failed":
            self.logger.warning(f"[Savings] working out the savings failed: {result}")
            return self._evo_reply({"ok": False, "error": str(result)}, status=500)
        return self._evo_reply({"ok": False, "pending": True, "error": "still adding it up"},
                               status=503)

    # ---- the build (off the dispatch path) ----------------------------------

    def _savings_settings(self):
        store = getattr(self, "cfg_store", None) or {}
        sav = store.get("savings")
        clean, _err = SM.clean_savings_settings(sav if isinstance(sav, dict) else {})
        return clean or {}

    def _sem_json(self, path):
        return json.loads(self._sigen_fetch(f"{self._SIGEN_API_BASE}/{path}"))

    def _savings_build(self):
        daily = self._sem_json(f"daily?days={SAVINGS_DAYS}").get("records") or []
        try:
            hh = self._sem_json(f"halfhourly?days={SAVINGS_DAYS}")
        except Exception as exc:
            if getattr(exc, "code", None) == 404:
                raise RuntimeError("SigenEnergyManager 5.146.0 or later is needed "
                                   "(it has no half-hourly records to share)") from exc
            raise
        status = self._sem_json("status")
        battery = status.get("battery") or {}
        tariff = status.get("tariff") or {}
        imp_code = (tariff.get("import_side") or {}).get("tariff_code")
        exp_code = (tariff.get("export_side") or {}).get("tariff_code")
        region = region_of(imp_code) or region_of(exp_code)
        if not region:
            raise RuntimeError("the battery manager does not say which Octopus region "
                               "this is, so the standard prices cannot be looked up")
        first = min((r.get("date") for r in daily if r.get("date")), default=None)
        if not first:
            return build_reply(SM.SavingsModel([], [], SM.RateTable([]), SM.RateTable([]),
                                               SM.RateTable([])), {}, date.today())
        flux_product = product_of(exp_code) if "FLUX" in str(exp_code or "").upper() else None
        rates, note = self._savings_rates(region, first, flux_product)
        model = SM.SavingsModel(
            daily, SM.rows_to_slots(hh.get("fields") or [], hh.get("rows") or []),
            SM.RateTable(SM.octopus_intervals(rates.get("cap_unit"))),
            SM.RateTable(SM.octopus_intervals(rates.get("cap_standing"))),
            SM.RateTable(SM.octopus_intervals(rates.get("std_export"))),
            SM.RateTable(SM.octopus_intervals(rates.get("flux_export"))),
            events=hh.get("axle_payments") or [],
            credits=hh.get("free_hour_credits") or [],
            capacity=battery.get("capacity_kwh"))
        return build_reply(model, self._savings_settings(), date.today(), note)

    # ---- Octopus's published prices -----------------------------------------

    def _savings_rates_path(self):
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, RATES_FILE)

    def _savings_rates(self, region, first_date, flux_product):
        """({table: Octopus results}, note). Fetched at most once a day; when
        Octopus cannot be reached the last copy is used and the note says how
        old it is."""
        path = self._savings_rates_path()
        want = {"region": region, "from": first_date, "flux": flux_product or ""}
        cached = None
        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.warning(f"[Savings] {RATES_FILE} could not be read ({exc}); fetching again")
        fresh = (isinstance(cached, dict) and cached.get("want") == want
                 and time.time() - float(cached.get("fetched", 0)) < RATES_MAX_AGE)
        if fresh:
            return cached["tables"], {"fetched": cached["fetched"], "stale": False,
                                      "products": cached.get("products")}
        with self._savings_rates_lock:
            try:
                tables, products = self._savings_fetch_rates(region, first_date, flux_product)
            except Exception as exc:
                if isinstance(cached, dict) and cached.get("want", {}).get("region") == region \
                        and isinstance(cached.get("tables"), dict):
                    self.logger.warning(f"[Savings] Octopus's price list could not be read "
                                        f"({exc}); using the copy from "
                                        f"{time.strftime('%d %b %H:%M', time.localtime(cached['fetched']))}")
                    return cached["tables"], {"fetched": cached["fetched"], "stale": True,
                                              "products": cached.get("products")}
                raise RuntimeError(f"Octopus's price list could not be read: {exc}") from exc
            now = time.time()
            data = {"want": want, "fetched": now, "tables": tables, "products": products}
            tmp = f"{path}.tmp.{threading.get_ident()}"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, separators=(",", ":"))
                os.replace(tmp, path)
            except Exception as exc:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self.logger.warning(f"[Savings] could not save {RATES_FILE} ({exc})")
            return tables, {"fetched": now, "stale": False, "products": products}

    def _octopus_get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "Dashboards"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _octopus_results(self, url):
        out, pages = [], 0
        while url and pages < 30:
            page = self._octopus_get(url)
            out.extend(page.get("results") or [])
            url = page.get("next")
            pages += 1
        return out

    def _octopus_product_code(self, name, direction, fallback):
        try:
            page = self._octopus_get(f"{OCTOPUS_API}/?brand=OCTOPUS_ENERGY&is_variable=true"
                                     f"&page_size=100")
            for p in page.get("results") or []:
                if p.get("display_name") == name and p.get("direction") == direction \
                        and not p.get("is_business") and not p.get("is_prepay"):
                    return p.get("code") or fallback
        except Exception as exc:
            self.logger.debug(f"[Savings] product list unreadable ({exc}); using {fallback}")
        return fallback

    def _savings_fetch_rates(self, region, first_date, flux_product):
        since = (date.fromisoformat(first_date) - timedelta(days=1)).isoformat() + "T00:00Z"
        flex = self._octopus_product_code(FLEXIBLE_NAME, "IMPORT", FLEXIBLE_CODE)
        outg = self._octopus_product_code(OUTGOING_NAME, "EXPORT", OUTGOING_CODE)

        def tariff_url(product, kind):
            return (f"{OCTOPUS_API}/{product}/electricity-tariffs/E-1R-{product}-{region}/"
                    f"{kind}/?period_from={since}&page_size=1500")

        tables = {
            "cap_unit": self._octopus_results(tariff_url(flex, "standard-unit-rates")),
            "cap_standing": self._octopus_results(tariff_url(flex, "standing-charges")),
            "std_export": self._octopus_results(tariff_url(outg, "standard-unit-rates")),
            "flux_export": (self._octopus_results(tariff_url(flux_product, "standard-unit-rates"))
                            if flux_product else []),
        }
        for k in ("cap_unit", "cap_standing", "std_export"):
            if not tables[k]:
                raise RuntimeError(f"Octopus published no {k.replace('_', ' ')} prices "
                                   f"for region {region}")
        return tables, {"standard": flex, "export": outg, "flux": flux_product, "region": region}
