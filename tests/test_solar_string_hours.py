#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_solar_string_hours.py
# Description: Contract tests for Plugin._string_hours_payload — the pure half
#              of the solarStringHours endpoint (v2.79.0). Hour-bucket rows of
#              mean watts become the 24-entry per-string kWh list: mean power
#              over an hour IS that hour's kWh at /1000, the CURRENT hour
#              scales by its elapsed fraction, and an hour with no row stays
#              None so the page falls back to site totals rather than
#              inventing a silent [0,0,0,0].
# Author:      CliveS & Claude Fable 5
# Date:        13-08-2026
# Version:     1.0

from conftest import bare_plugin


def payload(rows, now_hour, now_frac):
    """-> (strings, site). Rows are (hb, w1, w2, w3, w4, site_w)."""
    return bare_plugin()._string_hours_payload(rows, now_hour, now_frac)


def test_completed_hour_mean_watts_become_kwh():
    strings, site = payload([(13, 2228.0, 2687.0, 3890.0, 1775.0, 10327.0)], 15, 0.5)
    assert strings[13] == [2.228, 2.687, 3.89, 1.775]
    assert site[13] == 10.327


def test_current_hour_scales_by_elapsed_fraction():
    strings, site = payload([(15, 2000.0, 1000.0, 3000.0, 500.0, 6400.0)], 15, 0.5)
    assert strings[15] == [1.0, 0.5, 1.5, 0.25]
    assert site[15] == 3.2


def test_hours_without_rows_stay_none_never_zeroed():
    strings, site = payload([(13, 1000.0, 1000.0, 1000.0, 1000.0, 4000.0)], 15, 0.25)
    assert strings[12] is None and strings[14] is None
    assert site[12] is None and site[14] is None
    assert strings[13] is not None and site[13] is not None


def test_site_survives_when_the_strings_are_not_logged():
    """The days before per-string logging began: NULL string columns, a real
    site figure. The hour must still draw — as a plain whole-system bar."""
    strings, site = payload([(9, None, None, None, None, 3100.0)], 15, 1.0)
    assert strings[9] is None
    assert site[9] == 3.1


def test_a_partly_null_string_row_yields_site_only():
    strings, site = payload([(13, None, 2000.0, None, 1000.0, 3000.0)], 15, 1.0)
    assert strings[13] is None          # never a half-invented stack
    assert site[13] == 3.0


def test_out_of_range_and_future_buckets_are_skipped():
    strings, site = payload([(-1, 1, 1, 1, 1, 1), (24, 1, 1, 1, 1, 1),
                             (16, 9999.0, 9999.0, 9999.0, 9999.0, 9999.0),  # after "now"
                             ("junk", 1, 1, 1, 1, 1)], 15, 0.5)
    assert all(h is None for h in strings)
    assert all(h is None for h in site)


def test_past_day_has_no_current_hour_scaling():
    strings, site = payload([(23, 1200.0, 0.0, 0.0, 0.0, 1200.0)], None, 0.0)
    assert strings[23] == [1.2, 0.0, 0.0, 0.0]
    assert site[23] == 1.2


def test_hour_frac_is_the_one_place_elapsed_time_is_decided():
    p = bare_plugin()
    assert p._hour_frac(10, 15, 0.5) == 1.0      # a finished hour
    assert p._hour_frac(15, 15, 0.5) == 0.5      # the current one
    assert p._hour_frac(16, 15, 0.5) is None     # hasn't started
    assert p._hour_frac(23, None, 0.0) == 1.0    # not today: all whole
