#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_pv_string_sanity.py
# Description: The solarStringHours reader must reject the impossible
#              per-string watts already in the SQL Logger. SigenEnergyManager
#              read the inverter's per-string current as unsigned until
#              v5.86.0, so a string at its dawn or dusk zero-crossing logged
#              655.3 A and V*I put up to 219,667 W on a 4.275 kWp array. Those
#              rows are on 21 days of history and are never rewritten, so the
#              READER has to filter them. Runs the plugin's own SQL against
#              SQLite rather than asserting on the string, so a change that
#              still builds valid-looking SQL but stops filtering fails here.
# Author:      CliveS & Claude Opus 5
# Date:        03-09-2026
# Version:     1.0

import sqlite3

import pytest

from conftest import bare_plugin, load_plugin_module


# Real rows, straight out of device_history_1563154425. The wrapped watts fall
# with the string voltage, so both ends of the run are here: the 219,667 W dusk
# figure and the 32,832 W one at 50.1 V that a headline-sized cap would miss.
GENUINE = [1330.0, 1923.0, 2048.0, 4705.0, 0.0]
WRAPPED = [219667.0, 216980.0, 45416.0, 32832.0]


def _table(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE h ("pv3watts" REAL)')
    conn.executemany('INSERT INTO h VALUES (?)', [(r,) for r in rows])
    return conn


def _mean(rows):
    sql = bare_plugin()._sane_avg_sql("pv3watts")
    with _table(rows) as conn:
        return conn.execute(f"SELECT {sql} FROM h").fetchone()[0]


def test_the_bound_sits_in_the_measured_gap():
    """Across 383k logged rows the largest genuine per-string sample is
    4,705 W and the smallest wrapped one is 32,832 W, with nothing between."""
    cap = load_plugin_module().PV_STRING_SANE_MAX_W
    assert max(GENUINE) < cap < min(WRAPPED)


@pytest.mark.parametrize("watts", WRAPPED)
def test_every_wrapped_sample_is_excluded(watts):
    assert _mean([1000.0, watts]) == 1000.0


@pytest.mark.parametrize("watts", GENUINE)
def test_genuine_samples_are_kept(watts):
    assert _mean([watts]) == watts


def test_an_hour_keeps_the_mean_of_its_real_samples():
    """The 18:00 hour on 03-09-2026: 64 samples, a handful of them wrapped.
    The answer must be the mean of the real ones, not a clamped 15,000."""
    assert _mean([100.0, 200.0, 300.0, 219667.0]) == 200.0


def test_an_hour_of_nothing_but_wrapped_samples_is_absent_not_zero():
    """NULL, so the page draws a gap. A 0.0 would read as a measured dark
    hour and quietly subtract from the day."""
    assert _mean(WRAPPED) is None


def test_negative_watts_beyond_the_bound_are_excluded_too():
    assert _mean([1000.0, -219667.0]) == 1000.0
