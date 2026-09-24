#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_mains_reference_quality.py
# Description: The Mains page's reference and offsets (review 24-09-2026):
#              [42] one blank or text voltage sample no longer fails every
#              meter's offset; [43] a power cut's near-zero reference buckets
#              no longer skew every meter's offset for a week; [44] the
#              inverter's live readings, here and in the carbon advice, are
#              used only while SigenEnergyManager is running and they are
#              current.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from conftest import bare_plugin, load_plugin_module

NOW = datetime(2026, 9, 24, 12, 0, 0)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args=()):
        return iter(self.rows)

    def close(self):
        pass


def test_a_non_numeric_voltage_sample_is_skipped_not_fatal():
    p = bare_plugin()
    p._rowid_for_ts = lambda conn, table, since: 1
    rows = [("2026-09-24 10:01:00", 240.0), ("2026-09-24 10:02:00", ""),
            ("2026-09-24 10:03:00", "n/a"), ("2026-09-24 10:04:00", 242.0),
            ("2026-09-24 10:05:00", "inf")]
    got = p._mains_bucketed_volts(_Conn(rows), None, 1, "voltage", "x")
    assert got == {"2026-09-24 10:0": 241.0}


def _offsets_plugin(ref_series, meter_series):
    p = bare_plugin()
    inv = SimpleNamespace(id=1, name="Inverter")
    p._mains_reference = lambda: {"id": 1, "name": "Inverter"}
    hist = SimpleNamespace(connect=lambda: _Conn([]),
                           column_names=lambda conn, dev_id: (["gridvoltagev"] if dev_id == 1
                                                              else ["voltage"]))
    p._history = lambda: hist
    p._mains_bucketed_volts = lambda conn, h, dev_id, col, since: (
        dict(ref_series) if dev_id == 1 else dict(meter_series))
    mod = load_plugin_module()
    return p, mod, [inv, SimpleNamespace(id=2, name="Plug")]


def test_a_power_cut_in_the_reference_does_not_move_the_offset(monkeypatch):
    keys = [f"2026-09-2{d} {h:02d}:{m}" for d in range(1, 4) for h in range(24) for m in range(6)]
    ref = {k: 240.0 for k in keys}
    meter = {k: 241.0 for k in keys}
    ref[keys[5]] = 0.0                        # the inverter during a power cut
    p, mod, devs = _offsets_plugin(ref, meter)
    monkeypatch.setattr(mod.indigo, "devices", devs)
    import mains_mixin
    monkeypatch.setattr(mains_mixin.indigo, "devices", devs, raising=False)
    out = p._mains_offsets()
    assert out["ok"], out
    assert out["meters"]["2"]["mean"] == pytest.approx(1.0)


def _inv(**kw):
    base = dict(id=1, name="Inverter", enabled=True, errorState="",
                lastSuccessfulComm=NOW - timedelta(seconds=30),
                states={"batterySoc": 80, "pvPowerWatts": 4000, "homePowerWatts": 600,
                        "gridPowerWatts": -3000, "gridVoltageV": 241.0})
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def sem(monkeypatch):
    mod = load_plugin_module()
    running = {"v": True}
    plug = SimpleNamespace(isRunning=lambda: running["v"], isInstalled=lambda: True)
    monkeypatch.setattr(mod.indigo.server, "getPlugin", lambda pid: plug)
    return running


@pytest.mark.parametrize("change,live", [
    ({}, True),
    ({"enabled": False}, False),
    ({"errorState": "timeout"}, False),
    ({"lastSuccessfulComm": NOW - timedelta(hours=3)}, False),
])
def test_one_freshness_rule_for_the_inverter(sem, change, live):
    p = bare_plugin()
    assert p._sigen_states_live(_inv(**change), now=NOW)[0] is live


def test_a_stopped_sem_makes_the_inverter_states_history(sem):
    p = bare_plugin()
    sem["v"] = False
    ok, why = p._sigen_states_live(_inv(), now=NOW)
    assert ok is False and "not running" in why


def test_the_mains_reference_gives_no_live_figures_when_stale(sem):
    p = bare_plugin()
    p._sigen_inverter = lambda: _inv(lastSuccessfulComm=datetime.now() - timedelta(hours=2))
    ref = p._mains_reference()
    assert ref["id"] == 1 and ref["houseWatts"] is None and ref["volts"] is None
    assert ref["stale"]
    p._sigen_inverter = lambda: _inv(lastSuccessfulComm=datetime.now())
    ref = p._mains_reference()
    assert ref["houseWatts"] == 600 and ref["volts"] == 241.0 and ref["stale"] is None


def test_carbon_advice_ignores_frozen_inverter_states(sem):
    p = bare_plugin()
    p._sigen_inverter = lambda: _inv(lastSuccessfulComm=datetime.now())
    assert p._carbon_solar()["export_w"] == 3000
    sem["v"] = False
    assert p._carbon_solar() == {}
