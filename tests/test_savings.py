#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_savings.py
# Description: Contract test for the Savings page (3.71.0): what the solar and
#              battery have saved, in five steps (savings_model.py), and the
#              handler, settings and page that carry it (savings_mixin.py).
#
#              WHAT IS LOCKED HERE
#              1. Each step's pounds, worked by hand for a made-up day: no
#                 kit, panels only, your tariff, the battery, the extras.
#              2. The battery is a mixed pool: grid energy put in at night
#                 comes out as grid energy, not solar.
#              3. Octopus's own bill replaces the meter sums on a billed day,
#                 and the page is told how far apart the two were.
#              4. A day recorded only as totals is estimated and says so; a
#                 day that does not balance is left out and counted.
#              5. Axle payments: events by their start, top-ups on the last
#                 day of their (UTC) month, a referral listed but not counted,
#                 a payment on a day with no record not counted.
#              6. The settings: blanks dropped, junk refused by name.
#              7. Payback and the year's projection, cautious by design.
#              8. The handler, the action, the menu tile and the page agree,
#                 and a price list Octopus cannot serve falls back to the last
#                 copy kept.
# Author:      CliveS & Claude Opus 5.5
# Date:        21-11-2026
# Version:     1.0

import json
import os
import types
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import bare_plugin, load_plugin_module

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Server Plugin")
PAGES = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages")
UTC = timezone.utc


def mods():
    load_plugin_module()                    # puts Server Plugin on sys.path
    import savings_mixin
    import savings_model
    return savings_model, savings_mixin


def flat(p):
    """A RateTable charging `p` pence for all time."""
    M, _ = mods()
    return M.RateTable([(0, None, p)])


def day_slots(d, day_kw, night_kw, soc=None):
    """48 half hours on date `d`: hours 6-17 use `day_kw` (pv, home, imp, exp),
    the rest `night_kw`."""
    out = []
    t0 = datetime.fromisoformat(f"{d}T00:00:00")
    for i in range(48):
        pv, home, imp, exp = day_kw if 12 <= i < 36 else night_kw
        out.append({"start": (t0 + timedelta(minutes=30 * i)).isoformat(),
                    "pv_kwh": pv, "home_kwh": home, "import_kwh": imp, "export_kwh": exp,
                    "soc_start": soc, "soc_end": soc, "import_rate_p": 15.0})
    return out


def record(d, slots, **extra):
    tot = lambda k: round(sum(s[k] for s in slots), 3)
    r = {"date": d, "pv_kwh": tot("pv_kwh"), "home_kwh": tot("home_kwh"),
         "grid_import_kwh": tot("import_kwh"), "grid_export_kwh": tot("export_kwh"),
         "tariff": "tracker", "rate_today_p": 15.0, "export_rate_p": 12.0}
    r["battery_charge_kwh"] = max(0.0, r["pv_kwh"] + r["grid_import_kwh"] - r["grid_export_kwh"] - r["home_kwh"])
    r.update(extra)
    return r


def model(daily, slots, **kw):
    M, _ = mods()
    return M.SavingsModel(daily, slots, flat(20.0), flat(50.0), flat(10.0),
                          tz=UTC, capacity=10.0, **kw)


# ---- 1: the five steps, by hand ---------------------------------------------

# Day: panels make 1 kWh a half hour for 12 hours, the house uses 0.5 all day.
# Panels only: 12 kWh used as made, 12 bought at night, 12 sold by day.
NO_BATTERY = ((1.0, 0.5, 0.0, 0.5), (0.0, 0.5, 0.5, 0.0))
WITH_BATTERY = ((1.0, 0.5, 0.0, 0.0), (0.0, 0.5, 0.0, 0.0))


def test_each_step_by_hand_without_a_battery():
    s = day_slots("2026-06-01", *NO_BATTERY)
    m = model([record("2026-06-01", s)], s)
    out = m.summary()
    # No kit: 24 kWh at 20p + 50p standing = 5.30.
    assert out["steps"]["nokit"] == pytest.approx(5.30)
    # Panels: 12 x 20p - 12 x 10p + 50p = 1.70, so 3.60 off.
    assert out["steps"]["solar"] == pytest.approx(3.60)
    # Your tariff: 12 x 15p - 12 x 12p + 50p = 0.86, so 0.84 off.
    assert out["steps"]["tariff"] == pytest.approx(0.84)
    # No battery, so the meters match the panels-only figure.
    assert out["steps"]["battery"] == pytest.approx(0.0)
    assert out["steps"]["paid"] == pytest.approx(0.86)
    assert out["saved"] == pytest.approx(5.30 - 0.86)
    assert out["solarOnlySelfUsePct"] == 50.0


def test_the_battery_step_and_self_sufficiency():
    s = day_slots("2026-06-01", *WITH_BATTERY)
    m = model([record("2026-06-01", s)], s)
    out = m.summary()
    # The meters recorded nothing: only the 50p standing charge was paid.
    assert out["steps"]["paid"] == pytest.approx(0.50)
    assert out["steps"]["battery"] == pytest.approx(0.86 - 0.50)
    assert out["selfSufficiencyPct"] == 100.0
    assert out["energy"]["solar_stored"] == pytest.approx(12.0)
    assert out["energy"]["solar_exported"] == pytest.approx(0.0)


def test_the_steps_always_add_up_to_the_saving():
    s = day_slots("2026-06-01", *WITH_BATTERY)
    out = model([record("2026-06-01", s)], s).summary()
    st = out["steps"]
    assert st["nokit"] - st["solar"] - st["tariff"] - st["battery"] - st["extras"] == pytest.approx(st["paid"])
    assert st["nokit"] - st["paid"] == pytest.approx(out["saved"])


# ---- 2: grid energy in the battery stays grid energy ------------------------

def test_grid_energy_put_in_the_battery_comes_out_as_grid():
    # Night: buy 1 kWh a half hour, use 0.5, store 0.5. Day: no sun, the
    # battery runs the house.
    s = day_slots("2026-11-01", (0.0, 0.5, 0.0, 0.0), (0.0, 0.5, 1.0, 0.0))
    out = model([record("2026-11-01", s, tariff="flux")], s).summary()
    assert out["selfSufficiencyPct"] == 0.0
    assert out["energy"]["home_grid_battery"] == pytest.approx(12.0)


# ---- 3: Octopus's bill wins where there is one -------------------------------

def test_octopus_bill_replaces_the_meter_sum():
    s = day_slots("2026-06-01", *NO_BATTERY)
    rec = record("2026-06-01", s, cost_settled=True, elec_unit_cost_gbp=1.90,
                 export_revenue_gbp=1.40, elec_standing_gbp=0.55)
    out = model([rec], s).summary()
    assert out["steps"]["paid"] == pytest.approx(1.05)
    assert out["billedDays"] == 1
    assert out["billCheck"] == {"model": pytest.approx(0.91), "octopus": pytest.approx(1.05)}


# ---- 4: estimated and missing days -----------------------------------------

def test_a_totals_only_day_is_estimated_from_its_month():
    s = day_slots("2026-06-01", *NO_BATTERY)
    est = {"date": "2026-06-02", "pv_kwh": 24.0, "home_kwh": 24.0, "grid_import_kwh": 12.0,
           "grid_export_kwh": 12.0, "tariff": "tracker", "rate_today_p": 15.0, "export_rate_p": 12.0}
    m = model([record("2026-06-01", s), est], s)
    out = m.summary("2026-06-02", "2026-06-02")
    assert out["estimatedDays"] == 1
    # The month's half-hourly day used half of min(pv, home) as made, so the
    # estimate matches it exactly.
    assert out["steps"]["solar"] == pytest.approx(3.60)


def test_a_day_that_does_not_balance_is_left_out_and_counted():
    bad = {"date": "2026-03-26", "pv_kwh": 0.0, "home_kwh": 23.17, "grid_import_kwh": 0.01,
           "grid_export_kwh": 0.0, "battery_charge_kwh": 14.9, "battery_discharge_kwh": 14.75,
           "tariff": "tracker", "rate_today_p": 23.95, "export_rate_p": 12.0}
    m = model([bad], [])
    assert m.missing == ["2026-03-26"]
    assert m.summary()["days"] == 0


def test_a_day_with_no_rate_borrows_the_nearest():
    s = day_slots("2026-06-01", *NO_BATTERY)
    odd = {"date": "2026-06-02", "pv_kwh": 24.0, "home_kwh": 24.0, "grid_import_kwh": 12.0,
           "grid_export_kwh": 12.0, "tariff": "unknown", "rate_today_p": None, "export_rate_p": 12.0}
    m = model([record("2026-06-01", s), odd], s)
    assert m.days["2026-06-02"]["tariff_name"] == "tracker"
    assert not m.days["2026-06-02"]["unpriced"]


# ---- 5: the paid extras -----------------------------------------------------

def test_axle_payments_and_free_hours():
    s = day_slots("2026-07-31", *NO_BATTERY)
    s2 = day_slots("2026-07-30", *NO_BATTERY)
    daily = [record("2026-07-30", s2), record("2026-07-31", s)]
    axle = [
        {"type": "flex event", "start": "2026-07-30T18:00:00+00:00", "pence": 382, "kwh": -3.82},
        # Axle's July ends 23:59:59 UTC: that is 31 July, not 1 August.
        {"type": "flex period top-up", "start": "2026-07-01T00:00:00+00:00",
         "end": "2026-07-31T23:59:59.999999+00:00", "pence": 618, "kwh": None},
        {"type": "Referred Credit", "start": "2026-07-30T12:03:40+00:00", "pence": 2500},
        {"type": "flex event", "start": "2026-03-26T07:30:00+00:00", "pence": 330, "kwh": -3.3},
    ]
    m = model(daily, s2 + s, events=axle, credits=[{"date": "2026-07-31", "pence": 299}])
    out = m.summary()
    assert out["events"] == pytest.approx(3.82 + 6.18)
    assert out["credits"] == pytest.approx(2.99)
    by = {(x["date"], x["kind"]): x for x in m.extras}
    assert by[("2026-07-31", "top_up")]["counted"]
    assert not by[("2026-07-30", "other")]["counted"]
    assert by[("2026-07-30", "other")]["why"] == "not earned by the kit"
    assert not by[("2026-03-26", "grid_event")]["counted"]
    assert by[("2026-03-26", "grid_event")]["why"] == "no record that day"


# ---- 6: settings ------------------------------------------------------------

def test_settings_are_cleaned():
    M, _ = mods()
    out, err = M.clean_savings_settings({"systemCost": "£26,470", "installDate": "2026-03-12",
                                         "quoteAnnualSaving": "", "quoteAnnualKwh": 9112,
                                         "quotePaybackYears": "12"})
    assert err is None
    assert out == {"systemCost": 26470, "installDate": "2026-03-12", "quoteAnnualKwh": 9112,
                   "quotePaybackYears": 12}
    assert M.clean_savings_settings({"systemCost": "lots"})[1] == "what the system cost must be a number"
    assert M.clean_savings_settings({"systemCost": -5})[1] == "what the system cost is out of range"
    assert M.clean_savings_settings({"installDate": "12/03/2026"})[1].startswith("the date it started")
    assert M.clean_savings_settings({"systemCost": True})[1] == "what the system cost must be a number"
    assert M.clean_savings_settings([1])[1] == "the savings settings must be an object"


def test_a_settings_save_stores_them_and_refuses_junk(tmp_path):
    from unittest.mock import MagicMock
    load_plugin_module()
    p = bare_plugin()
    path = tmp_path / "dashboards_config.json"
    p._config_store_path = lambda: str(path)
    p.cfg_store = {}
    p._write_config_js = MagicMock()
    ok = p._apply_config({"savings": {"systemCost": "26470", "installDate": "2026-03-12"}})
    assert ok["status"] == 200, ok
    assert json.loads(path.read_text(encoding="utf-8"))["savings"] == {"systemCost": 26470,
                                                                        "installDate": "2026-03-12"}
    bad = p._apply_config({"savings": {"systemCost": "lots"}})
    assert bad["status"] == 400 and "must be a number" in bad["content"]


# ---- 7: payback and the year ------------------------------------------------

def test_the_year_takes_the_slowest_month_for_months_not_on_record():
    M, _ = mods()
    months = {"2026-06": {"days": 30, "saved": 300.0, "pv": 1500.0},
              "2026-10": {"days": 31, "saved": 155.0, "pv": 500.0},
              "2026-11": {"days": 5, "saved": 5.0, "pv": 20.0}}       # too few days to be the yardstick
    y = M.project_year(months, date(2026, 11, 6))
    assert y["basis"] == "2026-10"
    assert 6 not in y["filled"] and 10 not in y["filled"] and 11 in y["filled"]
    # June at 10 a day, everything else at October's 5 a day.
    assert y["saved"] == pytest.approx(30 * 10 + (365 - 30) * 5)


def test_payback():
    M, _ = mods()
    assert M.payback(None, 100, 1000, None, date(2026, 11, 21)) is None
    pb = M.payback(10000, 1000, 1000, "2026-03-12", date(2026, 11, 21))
    assert pb["pct"] == 10.0 and pb["yearsTotal"] == 10.0
    assert pb["paidOffDate"] == (date(2026, 11, 21) + timedelta(days=round(9 * 365.25))).isoformat()


def test_rate_tables_follow_octopus_intervals():
    M, _ = mods()
    rows = [{"valid_from": "2026-04-01T00:00:00Z", "valid_to": "2026-07-01T00:00:00Z", "value_inc_vat": 23.8,
             "payment_method": "DIRECT_DEBIT"},
            {"valid_from": "2026-04-01T00:00:00Z", "valid_to": "2026-07-01T00:00:00Z", "value_inc_vat": 25.1,
             "payment_method": "NON_DIRECT_DEBIT"},
            {"valid_from": "2026-07-01T00:00:00Z", "valid_to": None, "value_inc_vat": 25.2}]
    t = M.RateTable(M.octopus_intervals(rows))
    at = lambda s: t.at(datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp())
    assert at("2026-05-01T12:00:00") == 23.8
    assert at("2026-12-01T12:00:00") == 25.2
    assert at("2026-03-01T12:00:00") is None


# ---- 8: handler, rates, page --------------------------------------------------

def test_region_and_product_from_a_tariff_code():
    _, X = mods()
    assert X.region_of("E-1R-FLUX-EXPORT-23-02-14-F") == "F"
    assert X.product_of("E-1R-FLUX-EXPORT-23-02-14-F") == "FLUX-EXPORT-23-02-14"
    assert X.region_of("") is None and X.product_of("nonsense") is None


def test_periods_end_on_the_last_record():
    _, X = mods()
    assert X.period_bounds("1m", "2026-11-20") == ("2026-10-22", "2026-11-20")
    assert X.period_bounds("ytd", "2026-11-20") == ("2026-01-01", "2026-11-20")
    assert X.period_bounds("all", "2026-11-20") == (None, "2026-11-20")


def test_build_reply_carries_every_period_and_the_quote():
    M, X = mods()
    s = day_slots("2026-06-01", *WITH_BATTERY)
    m = model([record("2026-06-01", s)], s)
    r = X.build_reply(m, {"systemCost": 1000, "installDate": "2026-05-30", "quoteAnnualSaving": 500},
                      date(2026, 6, 2))
    assert set(r["periods"]) == {"1m", "3m", "ytd", "all"}
    assert r["daysBeforeRecords"] == 2
    assert r["quote"]["annualSaving"] == 500
    assert r["payback"]["cost"] == 1000
    json.dumps(r)
    assert X.build_reply(model([], []), {}, date(2026, 6, 2))["empty"]


def test_the_handler_answers_from_its_own_lane():
    mods()
    p = bare_plugin()
    seen = {}

    def offpath(key, producer, ttl, wait=None, lane=None):
        seen.update(key=key, lane=lane)
        return "fresh", {"ok": True}
    p._offpath_get = offpath
    p._sigen_available = lambda: True
    p._evo_reply = lambda payload, status=200: {"status": status, "content": json.dumps(payload)}
    action = types.SimpleNamespace(props={"request_body": "{}", "headers": {"Content-Type": "application/json"}})
    assert p.handleSavingsReport(action)["status"] == 200
    assert seen == {"key": "savingsReport", "lane": "savings"}
    assert "savings" in p.OFFPATH_LANES
    p._offpath_get = lambda *a, **k: ("pending", None)
    assert p.handleSavingsReport(action)["status"] == 503
    p._sigen_available = lambda: False
    assert json.loads(p.handleSavingsReport(action)["content"])["reason"] == "sem_absent"


def test_an_unreachable_price_list_falls_back_to_the_last_copy(tmp_path):
    mods()
    p = bare_plugin()
    p.logger = types.SimpleNamespace(warning=lambda *a: None, debug=lambda *a: None)
    p._savings_rates_path = lambda: str(tmp_path / "savings_rates.json")
    tables = {"cap_unit": [1], "cap_standing": [2], "std_export": [3], "flux_export": []}
    (tmp_path / "savings_rates.json").write_text(json.dumps(
        {"want": {"region": "F", "from": "2026-03-01", "flux": ""}, "fetched": 1.0,
         "tables": tables, "products": {}}), encoding="utf-8")

    def boom(*a):
        raise OSError("no network")
    p._savings_fetch_rates = boom
    got, note = p._savings_rates("F", "2026-03-27", None)
    assert got == tables and note["stale"]
    with pytest.raises(RuntimeError):
        p._savings_rates("A", "2026-03-27", None)      # a different region's copy is no use


def test_page_action_menu_and_settings_agree():
    root = ET.parse(os.path.join(SP, "Actions.xml")).getroot()
    action = next(a for a in root.iter("Action") if a.get("id") == "savingsReport")
    assert action.get("uiPath") == "hidden" and action.find("CallbackMethod").text == "handleSavingsReport"
    html = open(os.path.join(PAGES, "savings.html"), encoding="utf-8").read()
    assert 'DashUI.message("savingsReport"' in html and 'src="savings-view.js"' in html
    assert '["savings.html",' in open(os.path.join(PAGES, "menu.html"), encoding="utf-8").read()
    assert 'href="savings.html"' in open(os.path.join(PAGES, "cost.html"), encoding="utf-8").read()
    settings = open(os.path.join(PAGES, "settings.html"), encoding="utf-8").read()
    M, _ = mods()
    for key in list(M.SAVINGS_NUMBERS) + ["installDate"]:
        assert f"{key}:" in settings, key
