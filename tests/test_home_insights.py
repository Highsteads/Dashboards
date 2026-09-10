#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_home_insights.py
# Description: Contract tests for the Home Insights evaluators (v2.42.0) — the
#              pure anomaly-vs-own-norm functions behind the hub Insights card:
#              battery trend projection, quiet-sensor detection (scaled by the
#              elapsed day), room-temperature deviation, on-longer-than-usual,
#              and the per-day ON-minutes splitter they share.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import pytest
from conftest import bare_plugin


@pytest.fixture(scope="module")
def P():
    return bare_plugin()


# ── battery trend ────────────────────────────────────────────────────────────

def test_battery_fast_fall_warns_with_projection(P):
    ins = P._insight_battery_trend("Hall Sensor", 7, now_pct=30.0, week_ago_pct=58.0)
    assert ins["kind"] == "battery" and ins["level"] == "warn"
    # 28 pts / 7 days = 4/day -> 30/4 = 7 days left
    assert "7 days" in ins["detail"]


def test_battery_slow_fall_is_ignored(P):
    assert P._insight_battery_trend("X", 1, now_pct=80.0, week_ago_pct=88.0) is None


def test_battery_healthy_fall_far_from_empty_is_note(P):
    # 15-pt weekly fall from a high level: real trend, but ~40 days left -> note.
    ins = P._insight_battery_trend("X", 1, now_pct=85.0, week_ago_pct=100.0)
    assert ins["level"] == "note"


def test_battery_low_now_is_warn_even_if_days_left_moderate(P):
    ins = P._insight_battery_trend("X", 1, now_pct=18.0, week_ago_pct=31.0)
    assert ins["level"] == "warn"


def test_battery_rising_or_missing_is_none(P):
    assert P._insight_battery_trend("X", 1, now_pct=90.0, week_ago_pct=70.0) is None
    assert P._insight_battery_trend("X", 1, now_pct=None, week_ago_pct=50.0) is None
    assert P._insight_battery_trend("X", 1, now_pct=50.0, week_ago_pct=None) is None


# ── quiet sensor ─────────────────────────────────────────────────────────────

def test_chatty_sensor_silent_all_day_warns(P):
    ins = P._insight_quiet_sensor("Kitchen PIR", 3, today_events=0,
                                  daily_avg=40.0, hours_elapsed=12.0)
    assert ins["kind"] == "quiet" and ins["level"] == "warn"


def test_quiet_sensor_early_morning_does_not_cry_wolf(P):
    # avg 40/day but only 2h elapsed -> expected ~3.3 < threshold 6 -> no insight.
    assert P._insight_quiet_sensor("X", 3, 0, 40.0, 2.0) is None


def test_sensor_with_events_today_is_fine(P):
    assert P._insight_quiet_sensor("X", 3, today_events=5,
                                   daily_avg=40.0, hours_elapsed=12.0) is None


def test_rarely_active_sensor_never_flags(P):
    # avg 3/day: even a full silent day never reaches the expected-6 bar.
    assert P._insight_quiet_sensor("X", 3, 0, 3.0, 24.0) is None


# ── room temperature ─────────────────────────────────────────────────────────

def test_room_much_colder_warns(P):
    ins = P._insight_room_temp("Living Room", temp_now=15.0, usual=19.5, samples=40)
    assert ins["level"] == "warn" and "colder" in ins["title"]


def test_room_slightly_warmer_notes(P):
    ins = P._insight_room_temp("Kitchen", temp_now=24.2, usual=21.5, samples=40)
    assert ins["level"] == "note" and "warmer" in ins["title"]


def test_room_within_norm_is_none(P):
    assert P._insight_room_temp("Hall", 20.0, 21.0, 40) is None


def test_room_too_few_samples_is_none(P):
    assert P._insight_room_temp("Hall", 15.0, 20.0, samples=5) is None


# ── on longer than usual ─────────────────────────────────────────────────────

def test_light_on_triple_norm_warns(P):
    ins = P._insight_on_too_long("Garage Light", 9, on_min_today=400.0,
                                 daily_avg_min=60.0)
    assert ins["kind"] == "onlong" and ins["level"] == "warn"


def test_light_double_norm_notes(P):
    ins = P._insight_on_too_long("Hall Lamp", 9, on_min_today=260.0,
                                 daily_avg_min=120.0)
    assert ins["level"] == "note"


def test_small_absolute_extra_is_ignored(P):
    # 10 min vs a 2-min norm is 5x but trivially small — the +90 guard holds.
    assert P._insight_on_too_long("X", 9, 10.0, 2.0) is None


def test_below_ratio_is_ignored(P):
    # +100 min but under 2x its (large) norm — normal heavy day.
    assert P._insight_on_too_long("X", 9, 700.0, 600.0) is None


def test_usually_off_device_on_for_hours_flags(P):
    ins = P._insight_on_too_long("Immersion", 9, on_min_today=200.0,
                                 daily_avg_min=0.0)
    assert ins is not None and ins["level"] == "warn"


# ── per-day ON-minutes splitter ──────────────────────────────────────────────

def test_active_minutes_simple_days(P):
    # Day 0: on 60-120 (60 min). Day 1: on 1500-1560 (60 min).
    rows = [(60.0, "true"), (120.0, "false"), (1500.0, "on"), (1560.0, "off")]
    assert P._active_minutes_per_day(0, rows, 2) == [60.0, 60.0]


def test_active_minutes_span_crosses_midnight(P):
    # On at 1380 (23:00 day 0), off at 1560 (02:00 day 1): 60 + 120.
    rows = [(1380.0, "1"), (1560.0, "0")]
    assert P._active_minutes_per_day(0, rows, 2) == [60.0, 120.0]


def test_active_minutes_carry_in_and_still_on(P):
    # Carry-in ON, off at 30; on again at 2820 and never off (2-day window).
    rows = [(30.0, "false"), (2820.0, "true")]
    assert P._active_minutes_per_day(1, rows, 2) == [30.0, 60.0]


def test_active_minutes_no_rows(P):
    assert P._active_minutes_per_day(0, [], 3) == [0.0, 0.0, 0.0]
    assert P._active_minutes_per_day(1, [], 2) == [1440.0, 1440.0]


# ── PK binary search (_rowid_for_ts) ─────────────────────────────────────────
# The load-bearing guard: every history read must be PK-ranged because the
# SQL Logger DB has no ts index and journal_mode=delete — a ts-filtered scan
# holds a read lock long enough to block the logger's writes (wedged IWS for
# ~3 min when first shipped without this).

import sqlite3


@pytest.fixture()
def gap_table(tmp_path):
    """A history table with GAPS in the rowids (deletes/prunes do this):
    ids 10,20,30,40,50 at hours 01:00..05:00."""
    conn = sqlite3.connect(str(tmp_path / "h.sqlite"))
    conn.execute("CREATE TABLE device_history_1 (id INTEGER PRIMARY KEY, ts TEXT, v TEXT)")
    for i, hr in [(10, 1), (20, 2), (30, 3), (40, 4), (50, 5)]:
        conn.execute("INSERT INTO device_history_1 (id, ts, v) VALUES (?, ?, ?)",
                     (i, f"2026-07-10 0{hr}:00:00", "x"))
    conn.commit()
    yield conn
    conn.close()


def test_rowid_exact_hit(P, gap_table):
    b = P._rowid_for_ts(gap_table, "device_history_1", "2026-07-10 03:00:00")
    rows = [r[0] for r in gap_table.execute(
        "SELECT id FROM device_history_1 WHERE id >= ?", (b,))]
    assert rows == [30, 40, 50]


def test_rowid_between_rows_is_a_valid_range_bound(P, gap_table):
    # Target between the 02:00 and 03:00 rows: whatever id comes back, the
    # range semantics must hold — id >= b selects exactly ts >= target.
    b = P._rowid_for_ts(gap_table, "device_history_1", "2026-07-10 02:30:00")
    rows = [r[0] for r in gap_table.execute(
        "SELECT id FROM device_history_1 WHERE id >= ?", (b,))]
    assert rows == [30, 40, 50]
    before = [r[0] for r in gap_table.execute(
        "SELECT id FROM device_history_1 WHERE id < ?", (b,))]
    assert before == [10, 20]


def test_rowid_before_all_rows(P, gap_table):
    b = P._rowid_for_ts(gap_table, "device_history_1", "2026-07-09 00:00:00")
    assert b == 10


def test_rowid_after_all_rows(P, gap_table):
    b = P._rowid_for_ts(gap_table, "device_history_1", "2026-07-11 00:00:00")
    rows = gap_table.execute(
        "SELECT count(*) FROM device_history_1 WHERE id >= ?", (b,)).fetchone()[0]
    assert rows == 0


def test_rowid_empty_table(P, tmp_path):
    conn = sqlite3.connect(str(tmp_path / "e.sqlite"))
    conn.execute("CREATE TABLE device_history_2 (id INTEGER PRIMARY KEY, ts TEXT)")
    assert P._rowid_for_ts(conn, "device_history_2", "2026-07-10 00:00:00") is None
    conn.close()
