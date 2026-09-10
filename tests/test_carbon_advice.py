#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_carbon_advice.py
# Description: Decision-table test for Plugin._carbon_advice — the run-a-load
#              advice ladder that encodes CliveS's self-sufficiency KPI (soak up
#              spare solar first, then a clean grid, then wait for the cleanest
#              window). Locks the rung ordering so a future tweak can't quietly
#              re-rank the signals.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import pytest
from conftest import bare_plugin


@pytest.fixture(scope="module")
def advise():
    return bare_plugin()._carbon_advice


def _carbon(index="moderate", intensity=200, best=None):
    c = {"current": {"index": index, "intensity": intensity}}
    if best is not None:
        c["best"] = best
    return c


def test_exporting_solar_runs_now_regardless_of_carbon(advise):
    # Rung 1: exporting >=500W wins even on a dirty grid.
    out = advise(_carbon(index="very high", intensity=400),
                 {"export_w": 800}, {})
    assert out["action"] == "run_now" and out["level"] == "good"


def test_spare_solar_covers_house_runs_now(advise):
    # Rung 2: pv-home >= 1000 and soc < 99.
    out = advise(_carbon(), {"export_w": 0, "pv_w": 3000, "home_w": 1500, "soc": 50}, {})
    assert out["action"] == "run_now"


def test_spare_solar_but_battery_full_does_not_trigger_rung2(advise):
    # soc=100 blocks rung 2; grid is moderate so it falls through to neutral.
    out = advise(_carbon(index="moderate", intensity=200),
                 {"export_w": 0, "pv_w": 3000, "home_w": 1500, "soc": 100}, {})
    assert out["action"] != "run_now"


def test_clean_grid_now_is_anytime_good(advise):
    # Rung 3: no solar spare but grid index is low.
    out = advise(_carbon(index="low", intensity=90),
                 {"export_w": 0, "pv_w": 0, "home_w": 0}, {})
    assert out["action"] == "anytime" and out["level"] == "good"


def test_dirty_now_cleaner_window_ahead_waits(advise):
    # Rung 4: a materially cleaner window exists later.
    out = advise(_carbon(index="high", intensity=300,
                         best={"intensity": 200, "from": "2026-07-10T14:00Z"}),
                 {"export_w": 0, "pv_w": 0, "home_w": 0}, {})
    assert out["action"] == "wait_carbon" and out["level"] == "wait"


def test_no_signals_is_neutral(advise):
    out = advise({}, {}, {})
    assert out["action"] == "anytime" and out["level"] == "neutral"


def test_empty_carbon_but_exporting_still_runs_now(advise):
    out = advise({}, {"export_w": 800}, {})
    assert out["action"] == "run_now"
