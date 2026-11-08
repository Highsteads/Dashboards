#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plug_costs.py
# Description: Contract test for the Plugs page (3.69.0): what every plug that
#              measures its own energy costs a day, priced at Flux's cheap
#              rate (CliveS, 08-11-2026).
#
#              WHAT IS LOCKED HERE
#              1. A small step back in a reading is jitter, not a restart. A
#                 Shelly's energyKwhToday steps back by a few watt-hours ~50
#                 times a day; reading each as a restart made the dehumidifier
#                 62 kWh for a day it used 2.47 (measured 08-11-2026).
#              2. A real restart, and a counter reset, are still counted in full.
#              3. Each past day is priced at the cheap rate published FOR that
#                 day (13.9p before 19-10-2026, 15.5p after), never today's.
#              4. Sums, "yesterday", "since" and the dearest-first order.
#              5. The producer against a real SQLite history: finished days are
#                 kept in the ledger only once settled, and are then read from
#                 it, not the history.
#              6. The page, the action and the menu tile agree.
# Author:      CliveS & Claude Opus 5.5
# Date:        08-11-2026 20:10
# Version:     1.0

import json
import os
import sqlite3
import time
import types
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import pytest
from conftest import bare_plugin, load_plugin_module

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Server Plugin")
PAGES = os.path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages")


@pytest.fixture
def london(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def mods():
    load_plugin_module()                    # puts Server Plugin on sys.path
    import device_cost
    import plugs_mixin
    return device_cost, plugs_mixin


def spans(cheap, day="2026-11-07"):
    """An elec_rates_today_json list whose cheapest span is `cheap`."""
    return json.dumps([
        {"value_inc_vat": 25.6271, "valid_from": f"{day}T00:00:00Z", "valid_to": f"{day}T02:00:00Z"},
        {"value_inc_vat": cheap, "valid_from": f"{day}T02:00:00Z", "valid_to": f"{day}T05:00:00Z"},
        {"value_inc_vat": 35.7813, "valid_from": f"{day}T16:00:00Z", "valid_to": f"{day}T19:00:00Z"},
    ])


# ---- 1, 2: jitter and restarts ---------------------------------------------

def test_a_small_step_back_is_jitter_not_a_restart(london):
    C, _ = mods()
    t = int(time.mktime((2026, 11, 8, 0, 3, 0, 0, 0, -1)))
    # Real readings from the dehumidifier plug, 08-11-2026 00:03-00:13.
    rows = [(t, 0.0094), (t + 24, 0.0091), (t + 300, 0.0249), (t + 312, 0.0241), (t + 610, 0.0403)]
    used = C.kwh_between(C.kwh_slices(rows), t)
    assert used == pytest.approx(0.0403 - 0.0094, abs=1e-6)


def test_a_real_restart_is_still_counted_in_full(london):
    C, _ = mods()
    t = int(time.mktime((2026, 11, 8, 9, 0, 0, 0, 0, -1)))
    rows = [(t, 0.30), (t + 60, 0.32), (t + 120, 0.01), (t + 180, 0.05)]   # the plug starts again at 0
    assert C.kwh_between(C.kwh_slices(rows), t) == pytest.approx(0.02 + 0.01 + 0.04)


def test_a_counter_that_only_goes_up():
    C, _ = mods()
    rows = [(100, 6.90), (200, 6.93), (300, 6.928), (400, 6.95),          # 6.928 is jitter
            (500, 0.02), (600, 0.05)]                                    # then the counter is reset
    assert C.kwh_between(C.counter_slices(rows), 0) == pytest.approx(0.03 + 0.02 + 0.02 + 0.03)


@pytest.mark.parametrize("plugin_id, keys, want", [
    ("com.clives.indigoplugin.shellydirect", ["energyKwhToday", "powerWatts"], ("energyKwhToday", "energykwhtoday", "daily")),
    ("com.clives.indigoplugin.z2mbridge", ["energy", "power"], ("energy", "energy", "lifetime")),
    ("com.clives.indigoplugin.esphomebridge", ["energy", "totalEnergy"], ("totalEnergy", "totalenergy", "lifetime")),
    ("com.clives.indigoplugin.z2mbridge", ["temperature"], None),
    ("com.example.other", ["energyKwhToday"], None),
])
def test_which_state_a_plug_counts_in(plugin_id, keys, want):
    C, _ = mods()
    assert C.meter_for(plugin_id, keys) == want


# ---- 3: each day at its own rate ------------------------------------------

def test_a_day_is_priced_at_the_rate_published_for_it(london):
    C, _ = mods()
    d18 = int(time.mktime((2026, 10, 18, 0, 0, 0, 0, 0, -1)))
    d19 = int(time.mktime((2026, 10, 19, 0, 0, 0, 0, 0, -1)))
    d20 = int(time.mktime((2026, 10, 20, 0, 0, 0, 0, 0, -1)))
    published = [(d18 + 540, spans(13.9223, "2026-10-18")), (d19 + 1000, spans(15.473, "2026-10-19"))]
    assert C.rate_for_day(published, d18, d19)[0] == 13.9223
    assert C.rate_for_day(published, d19, d20)[0] == 15.473
    assert C.rate_for_day(published, d20, d20 + 86400) is None       # nothing written that day: unknown


@pytest.mark.parametrize("pence, words", [(0, "0p"), (4.2, "4.2p"), (42, "42p"), (99.6, "£1.00"), (261, "£2.61")])
def test_money_words(pence, words):
    C, _ = mods()
    assert C.money_words(pence) == words


def test_clocks_change_day_has_25_hours(london):
    _, M = mods()
    starts = M.day_starts(date(2026, 10, 26), days=3)              # 24, 25 (clocks back) and 26 October
    assert starts[1] - starts[0] == 24 * 3600
    assert starts[2] - starts[1] == 25 * 3600                      # 25 October is 25 hours long


# ---- 4: the report --------------------------------------------------------

def test_the_report_adds_up(london):
    _, M = mods()
    starts = M.day_starts(date(2026, 11, 8), days=8)
    r_old, r_new = (13.9223, 120, 300), (15.473, 120, 300)
    rates = [r_old, r_old, None, r_new, r_new, r_new, r_new, r_new]
    plugs = [
        {"id": 1, "name": "Kettle Plug", "room": "Kitchen", "kwh": [1, 1, 1, 1, 1, 1, 2, 0.5]},
        {"id": 2, "name": "Lamp Plug", "room": "Hall", "answering": False,
         "kwh": [None, None, None, None, None, 0.1, 0.1, 0.1]},
        {"id": 3, "name": "Idle Plug", "room": "", "kwh": [0] * 8},
    ]
    out = M.build_report(plugs, starts, rates, time.time())
    names = [p["name"] for p in out["plugs"]]
    assert names == ["Kettle Plug", "Lamp Plug", "Idle Plug"]          # dearest over 30 days first
    kettle, lamp, idle = out["plugs"]
    assert kettle["today"] == {"kwh": 0.5, "pence": round(0.5 * 15.473, 2), "unpriced": False}
    assert kettle["yesterday"]["kwh"] == 2                              # the day before today, alone
    assert kettle["week"]["kwh"] == 7.5                                 # today and the six before
    # Day 0 and 1 at the old rate, day 2 has no rate (unpriced), the rest new.
    assert kettle["month"]["pence"] == pytest.approx(13.92 * 2 + 15.47 * 3 + 30.95 + 7.74)
    assert kettle["month"]["unpriced"] is True and kettle["week"]["unpriced"] is True
    assert kettle["today"]["unpriced"] is False and kettle["yesterday"]["unpriced"] is False
    assert lamp["since"] == datetime.fromtimestamp(starts[5]).strftime("%A %-d %B")
    assert lamp["answering"] is False
    assert idle["month"] == {"kwh": 0, "pence": 0.0, "unpriced": False}
    assert out["totals"]["today"]["kwh"] == 0.6
    assert out["daily"][-1]["kwh"] == 0.6 and out["unpricedDays"] == 1
    assert out["rate"]["words"] == "15.5p a unit, the 2am to 5am rate"


# ---- 5: the producer against a real SQLite history -------------------------

class _Hist:
    """history_db's surface the producer uses, over a plain sqlite3 file."""

    def __init__(self, path):
        self.path = path

    def connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def epoch(col="ts"):
        return f"CAST(strftime('%s', {col}) AS INTEGER)"

    @staticmethod
    def column_names(conn, dev_id):
        return [r[1] for r in conn.execute(f'PRAGMA table_info("device_history_{int(dev_id)}")')
                if r[1] not in ("id", "ts")]


def _utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class _Coll(dict):
    def __iter__(self):
        return iter(self.values())


def producer_rig(monkeypatch, tmp_path, today):
    _, M = mods()
    starts = M.day_starts(today)
    db = str(tmp_path / "h.sqlite")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE device_history_7 (id INTEGER PRIMARY KEY, ts TIMESTAMP, energykwhtoday REAL)")
    conn.execute("CREATE TABLE variable_history_9 (id INTEGER PRIMARY KEY, ts TIMESTAMP, value TEXT)")
    # 1 kWh on each of the last three days before today, 0.4 so far today.
    for back, total in ((3, 1.0), (2, 1.0), (1, 1.0), (0, 0.4)):
        s = starts[-1 - back]
        for k, frac in enumerate((0.0, 0.5, 1.0)):
            conn.execute("INSERT INTO device_history_7 (ts, energykwhtoday) VALUES (?, ?)",
                         (_utc(s + 600 + k * 3600), round(total * frac + 0.001, 4)))
        conn.execute("INSERT INTO variable_history_9 (ts, value) VALUES (?, ?)",
                     (_utc(s + 1200), spans(10.0 if back >= 2 else 20.0)))
    conn.commit()
    conn.close()

    p = bare_plugin()
    p.pluginId = "com.clives.indigoplugin.dashboards"
    p._history = lambda: _Hist(db)
    p._plug_ledger_path = lambda: str(tmp_path / "plug_costs.json")
    dev = types.SimpleNamespace(id=7, name="Kettle Plug", enabled=True, folderId=0, errorState="",
                                pluginId="com.clives.indigoplugin.shellydirect",
                                states={"energyKwhToday": 0.401})
    fake = types.SimpleNamespace(
        devices=_Coll({7: dev}),
        variables={"elec_rates_today_json": types.SimpleNamespace(id=9, value=spans(20.0))})
    fake.devices.folders = {}
    monkeypatch.setattr(M, "indigo", fake, raising=False)
    monkeypatch.setattr(M, "date", types.SimpleNamespace(today=lambda: today))
    return p, M, starts


def test_the_producer_reads_the_history_and_keeps_finished_days(monkeypatch, tmp_path, london):
    p, M, starts = producer_rig(monkeypatch, tmp_path, date(2026, 11, 8))
    out = p._plug_costs()
    kettle = out["plugs"][0]
    got = [d["kwh"] for d in kettle["days"]][-4:]
    assert got == [pytest.approx(1.0, abs=0.002), pytest.approx(1.0, abs=0.002),
                   pytest.approx(1.0, abs=0.002), pytest.approx(0.4, abs=0.002)]
    pences = [d["pence"] for d in kettle["days"]][-4:]
    assert pences[0] == pytest.approx(10.0, abs=0.05) and pences[2] == pytest.approx(20.0, abs=0.05)
    # Days before the plug's history are "not recorded", not zero.
    assert kettle["days"][0]["kwh"] is None and kettle["since"]

    ledger = json.load(open(tmp_path / "plug_costs.json"))
    yesterday = datetime.fromtimestamp(starts[-2]).strftime("%Y-%m-%d")
    assert ledger["days"][yesterday]["kwh"]["7"] == pytest.approx(1.0, abs=0.002)
    assert ledger["days"][yesterday]["rate"][0] == 20.0
    assert datetime.fromtimestamp(starts[-1]).strftime("%Y-%m-%d") not in ledger["days"]

    # A kept day is read from the ledger from then on, not from the history.
    ledger["days"][yesterday]["kwh"]["7"] = 5.0
    json.dump(ledger, open(tmp_path / "plug_costs.json", "w"))
    again = p._plug_costs()
    assert again["plugs"][0]["yesterday"]["kwh"] == 5.0


def test_without_the_history_today_comes_from_the_plug_and_nothing_is_kept(monkeypatch, tmp_path, london):
    p, M, _ = producer_rig(monkeypatch, tmp_path, date(2026, 11, 8))

    def no_history():
        raise ValueError("no SQL Logger")
    p._history = no_history
    out = p._plug_costs()
    assert out["plugs"][0]["today"]["kwh"] == 0.401
    assert out["plugs"][0]["yesterday"]["kwh"] is None
    assert not os.path.exists(tmp_path / "plug_costs.json")


# ---- 6: the page, the action and the menu ----------------------------------

def test_page_action_and_menu_agree():
    root = ET.parse(os.path.join(SP, "Actions.xml")).getroot()
    action = next(a for a in root.iter("Action") if a.get("id") == "plugCosts")
    assert action.get("uiPath") == "hidden" and action.find("CallbackMethod").text == "handlePlugCosts"
    html = open(os.path.join(PAGES, "plugs.html"), encoding="utf-8").read()
    assert 'DashUI.message("plugCosts"' in html
    menu = open(os.path.join(PAGES, "menu.html"), encoding="utf-8").read()
    assert '["plugs.html",' in menu
    assert 'href="plugs.html"' in open(os.path.join(PAGES, "cost.html"), encoding="utf-8").read()


def test_the_handler_answers_from_the_offpath_pool(monkeypatch):
    p = bare_plugin()
    seen = {}

    def offpath(key, producer, ttl, wait=None, lane=None):
        seen.update(key=key, lane=lane)
        return "fresh", {"ok": True}
    p._offpath_get = offpath
    p._evo_reply = lambda payload, status=200: {"status": status, "content": json.dumps(payload)}
    action = types.SimpleNamespace(props={"request_body": "{}", "headers": {"Content-Type": "application/json"}})
    reply = p.handlePlugCosts(action)
    assert reply["status"] == 200 and seen == {"key": "plugCosts", "lane": "plugs"}
    p._offpath_get = lambda *a, **k: ("pending", None)
    assert p.handlePlugCosts(action)["status"] == 503
