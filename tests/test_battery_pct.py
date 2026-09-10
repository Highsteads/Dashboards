#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_battery_pct.py
# Description: Truth-table test for Plugin._battery_pct — the estate's three
#              battery idioms (native batteryLevel, z2m `battery` state guarded
#              >0, boolean batteryLow alarm). Guards the documented gotcha that a
#              bool batteryLevel must fall through, and that a mains z2m device
#              reporting battery=0 is NOT a 0% reading.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import pytest
from conftest import bare_plugin, FakeDev


@pytest.fixture(scope="module")
def batt():
    return bare_plugin()._battery_pct


def test_native_battery_level(batt):
    assert batt(FakeDev(batteryLevel=55)) == (55, False)


def test_native_battery_level_float_truncates(batt):
    assert batt(FakeDev(batteryLevel=12.9)) == (12, False)


def test_bool_battery_level_falls_through_to_states(batt):
    # A True batteryLevel is not a real percentage — must not read as 1%.
    assert batt(FakeDev(batteryLevel=True, states={"battery": "88"})) == (88, False)


def test_z2m_battery_state(batt):
    assert batt(FakeDev(states={"battery": "12"})) == (12, False)


def test_z2m_mains_battery_zero_is_not_a_reading(batt):
    # Mains-powered z2m devices report battery 0 — treated as "no battery".
    assert batt(FakeDev(states={"battery": "0"})) == (None, False)


@pytest.mark.parametrize("val", ["true", "on", "yes", "1", "TRUE", " On "])
def test_battery_low_alarm_truthy(batt, val):
    assert batt(FakeDev(states={"batteryLow": val})) == (None, True)


@pytest.mark.parametrize("val", ["false", "off", "no", "0", ""])
def test_battery_low_alarm_falsey(batt, val):
    assert batt(FakeDev(states={"batteryLow": val})) == (None, False)


def test_no_battery_info_at_all(batt):
    assert batt(FakeDev()) == (None, False)


def test_states_access_raises_is_swallowed(batt):
    class Boom:
        batteryLevel = None

        @property
        def states(self):
            raise RuntimeError("no states")
    assert batt(Boom()) == (None, False)
