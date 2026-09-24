#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    carbon_mixin.py
# Description: The Carbon page's server side: UK grid carbon intensity from
#              carbonintensity.org.uk, blended with the house's own solar and
#              tariff into "when to run a load" advice. Split out of plugin.py
#              in v3.30.0; Plugin inherits it, so every method is still
#              self.<name> and Actions.xml still names handleCarbonAdvisor.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

import json
import time

try:
    import indigo
except ImportError:
    pass


class CarbonMixin:
    # -----------------------------------------------------------------------
    # Carbon-aware advisor — combines UK grid carbon intensity (free public
    # API), the live solar surplus and the tariff into a "good time to run a
    # load" recommendation. Powers carbon.html. Carbon data is cached 10 min
    # (it only refreshes every 30 min upstream); solar/tariff are read fresh
    # each call so the advice tracks a passing cloud. Bearer-authed by IWS.
    # -----------------------------------------------------------------------
    _CARBON_API      = "https://api.carbonintensity.org.uk"

    def handleCarbonAdvisor(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/carbonAdvisor/
        Returns {carbon, solar, tariff, advice}. Each section is defensive so a
        single failure degrades to a partial answer (e.g. carbon API down still
        yields a solar-only recommendation)."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time()}
        try:
            out["carbon"] = self._carbon_intensity()
        except Exception as exc:
            self.logger.warning(f"[Carbon] intensity fetch failed: {exc}")
            out["carbon"] = {"error": str(exc)}
        try:
            out["solar"] = self._carbon_solar()
        except Exception as exc:
            self.logger.warning(f"[Carbon] solar read failed: {exc}")
            out["solar"] = {}
        try:
            out["tariff"] = self._carbon_tariff()
        except Exception:
            out["tariff"] = {}
        try:
            out["advice"] = self._carbon_advice(
                out.get("carbon") or {}, out.get("solar") or {}, out.get("tariff") or {})
        except Exception as exc:
            self.logger.warning(f"[Carbon] advice failed: {exc}")
            out["advice"] = {}
        return self._evo_reply(out)

    def _carbon_intensity(self):
        """Current + 48h regional carbon intensity, stale-while-revalidate on
        the shared pool (v3.27.0; its own thread and cache before that). The
        two 10 s API fetches never run on the dispatch thread. Cached 10 min,
        or 2 min when the API reported a failure in its reply."""
        return self._offpath_swr(
            "carbon", self._carbon_fetch,
            ttl=lambda p: 120 if isinstance(p, dict) and "error" in p else 600,
            fail_ttl=120,
            placeholder={"error": "carbon data is being fetched — try again shortly",
                         "warming": True},
            on_fail=lambda d: {"error": f"carbon refresh failed: {d}"})

    def _carbon_fetch(self):
        """One full carbon-API round trip → payload. Runs on the refresh
        worker, NEVER on the dispatch thread. Cached 10 min on success,
        2 min on failure (a down API isn't re-hit by every tab's poll)."""
        import urllib.request
        import calendar
        nowm = time.time()
        try:
            region = int(self.pluginPrefs.get("carbonRegionId", 4) or 4)
        except (TypeError, ValueError):
            region = 4
        if region <= 0:
            # "Off (not in Great Britain)" — the API covers GB only.
            return {"off": True, "error": "carbon data is switched off in Configure"}

        def _get(path):
            req = urllib.request.Request(
                f"{self._CARBON_API}{path}",
                headers={"User-Agent": f"Dashboards/{getattr(self, 'pluginVersion', '')}",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))

        try:
            cur = _get(f"/regional/regionid/{region}")["data"][0]
        except Exception as exc:
            return {"error": f"carbon API unavailable: {exc}"}
        region_name = cur.get("shortname", f"Region {region}")
        cur_block = cur["data"][0]
        current = {"intensity": cur_block["intensity"]["forecast"],
                   "index":     cur_block["intensity"]["index"]}
        mix = [{"fuel": m["fuel"], "perc": m["perc"]}
               for m in cur_block.get("generationmix", [])]

        from_iso = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
        try:
            fc_raw = _get(f"/regional/intensity/{from_iso}/fw48h/regionid/{region}")
            fdata = fc_raw["data"]
            fdata = fdata["data"] if isinstance(fdata, dict) else fdata
        except Exception:
            fdata = []          # keep the current reading even if the forecast leg fails
        forecast = [{"from": e["from"], "to": e["to"],
                     "intensity": e["intensity"]["forecast"],
                     "index": e["intensity"]["index"]}
                    for e in fdata
                    if e.get("intensity", {}).get("forecast") is not None]

        # Cleanest slot within the next 16h (an actionable "when to run" horizon).
        best = None
        horizon = nowm + 16 * 3600
        for e in forecast:
            try:
                t = calendar.timegm(time.strptime(e["from"], "%Y-%m-%dT%H:%MZ"))
            except Exception:
                continue
            if t < nowm - 1800 or t > horizon:
                continue
            if best is None or e["intensity"] < best["intensity"]:
                best = {"from": e["from"], "intensity": e["intensity"],
                        "index": e["index"],
                        "in_hours": round(max(0.0, (t - nowm) / 3600.0), 1)}

        return {"region": region_name, "region_id": region, "current": current,
                "mix": mix, "forecast": forecast, "best": best}

    def _carbon_solar(self):
        """Live solar/grid state from the Sigenergy inverter device (found by
        its pvPowerWatts state, so no hardcoded id). Empty dict if absent — the
        advisor then falls back to a carbon-only recommendation."""
        inv = self._sigen_inverter()
        if inv is None:
            return {}
        # A disabled device's states are FROZEN and an errored one's are
        # STALE (v2.95.2) — a midday freeze kept advising loads onto 4 kW of
        # export that had stopped hours before. Unknown is the honest answer,
        # and the advice already handles 'no solar data'.
        # And a stopped SigenEnergyManager or states gone quiet (review
        # 24-09-2026): the one freshness rule the Mains reference uses too.
        live, _why = self._sigen_states_live(inv)
        if not live:
            return {}
        st = inv.states

        def g(key):
            v = st.get(key)
            if v is None or str(v).strip() == "":
                return None                 # absent is not zero
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        pv = g("pvPowerWatts")
        home = g("homePowerWatts")
        grid = g("gridPowerWatts")          # negative = exporting to grid
        if pv is None or home is None or grid is None:
            return {}
        soc = g("batterySoc")
        batt = g("batteryPowerWatts")
        return {"pv_w":      round(pv),
                "home_w":    round(home),
                "grid_w":    round(grid),
                "export_w":  round(max(0.0, -grid)),
                "battery_w": round(batt) if batt is not None else None,
                "soc":       round(soc, 1) if soc is not None else None}

    def _carbon_tariff(self):
        """Current import unit rate + tariff name from the published variables."""
        rate, name = None, ""
        try:
            rate = round(float(indigo.variables["elec_unit_rate_p"].value), 2)
        except Exception:
            pass
        try:
            name = indigo.variables["elec_tariff_name"].value
        except Exception:
            pass
        return {"import_p": rate, "name": name}

    @staticmethod
    def _carbon_hhmm(iso):
        """A UTC 'YYYY-MM-DDThh:mmZ' forecast time as a local HH:MM (with a
        'tomorrow' suffix when it rolls past midnight)."""
        import calendar
        try:
            t = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%MZ"))
            lt = time.localtime(t)
            hh = time.strftime("%H:%M", lt)
            now = time.localtime()
            # Strictly LATER than today — a slot from late yesterday (the
            # fetch admits one up to 30 min old) read "23:30 tomorrow" just
            # after midnight (v2.95.4).
            if (lt.tm_year, lt.tm_yday) > (now.tm_year, now.tm_yday):
                return f"{hh} tomorrow"
            return hh
        except Exception:
            return iso

    def _carbon_advice(self, carbon, solar, tariff):
        """Rank the signals the way CliveS's self-sufficiency KPI wants: soak up
        spare solar first (free AND zero-carbon), then a genuinely clean grid,
        then wait for the cleanest window. Tariff is broadly flat on Tracker so
        it informs the wording, not the timing."""
        cur = carbon.get("current") or {}
        cur_int = cur.get("intensity")
        cur_idx = (cur.get("index") or "").lower()
        export_w = solar.get("export_w", 0) or 0
        pv_w = solar.get("pv_w", 0) or 0
        home_w = solar.get("home_w", 0) or 0
        soc = solar.get("soc")
        best = carbon.get("best") or {}
        clean_now = cur_idx in ("very low", "low")

        # 1) Exporting solar — running a load soaks up energy you'd otherwise sell.
        if export_w >= 500:
            return {"action": "run_now", "level": "good",
                    "headline": f"Run it now — exporting {export_w/1000:.1f} kW of solar",
                    "detail": "Spare solar is going to the grid. A load now runs on free, "
                              "zero-carbon energy instead of selling it and buying back later."}
        # 2) Strong solar covering the house with headroom.
        if (pv_w - home_w) >= 1000 and (soc is None or soc < 99):
            return {"action": "run_now", "level": "good",
                    "headline": f"Good time — {(pv_w - home_w)/1000:.1f} kW of spare solar",
                    "detail": "Solar is covering the house with room to spare, so a load runs "
                              "mostly on sunshine."}
        # 3) No solar spare, but the grid itself is clean right now.
        if clean_now and cur_int is not None:
            return {"action": "anytime", "level": "good",
                    "headline": f"Grid is clean now — {cur_int} gCO₂/kWh ({cur_idx})",
                    "detail": "Little solar spare, but the grid is unusually clean right now, "
                              "so it is a fine time to run a load."}
        # 4) Wait for the cleanest window ahead.
        if best and cur_int and best.get("intensity") is not None and best["intensity"] < cur_int:
            saved = round((1 - best["intensity"] / cur_int) * 100)
            when = self._carbon_hhmm(best["from"])
            return {"action": "wait_carbon", "level": "wait",
                    "headline": f"Hold off if you can — cleanest around {when}",
                    "detail": f"The grid is {cur_int} gCO₂/kWh now. Around {when} it drops to "
                              f"{best['intensity']} ({saved}% cleaner)."}
        return {"action": "anytime", "level": "neutral",
                "headline": (f"Grid at {cur_int} gCO₂/kWh" if cur_int is not None
                             else "No strong preference"),
                "detail": "No solar spare and no clearly cleaner window ahead — run whenever suits."}
