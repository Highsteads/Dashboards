#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_timeline_clock_change.py
# Description: On the two clock-change days the Timeline and the solar hours
#              are placed by CLOCK time, which is what the page's 0-1440 axis
#              means (review 24-09-2026 [46]). The SQL gives minutes elapsed
#              since local midnight, so on the 23-hour March day everything
#              after 01:00 sat an hour early, and on the 25-hour October day
#              an hour late with the last hour clamped away.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import os
import time
from datetime import datetime

import pytest

from conftest import bare_plugin


@pytest.fixture
def london():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/London"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _midnight(day):
    return int(time.mktime(datetime.strptime(day, "%Y-%m-%d").timetuple()))


def test_an_ordinary_day_is_unchanged(london):
    p = bare_plugin()
    start = _midnight("2026-07-10")
    assert p._clock_of(start, 450) == 450
    assert p._dst_fold(start) is None
    assert p._clock_spans(start, [[450, 480], [1430, None]]) == [[450, 480], [1430, 1440]]


def test_the_march_day_skips_an_hour(london):
    p = bare_plugin()
    start = _midnight("2026-03-29")            # clocks go forward at 01:00 GMT
    assert p._clock_of(start, 30) == 30        # 00:30
    assert p._clock_of(start, 60 + 7 * 60) == 9 * 60, "7 hours after 01:00 is 09:00 BST"
    assert p._clock_of(start, 23 * 60) == 1440
    assert p._clock_spans(start, [[420, 480]]) == [[480, 540]]


def test_the_october_day_repeats_an_hour_and_keeps_the_last_one(london):
    p = bare_plugin()
    start = _midnight("2026-10-25")            # clocks go back at 02:00 BST
    assert p._dst_fold(start) == (120, 60.0)
    assert p._clock_of(start, 20 * 60) == 19 * 60, "20 hours after midnight is 19:00 GMT"
    assert p._clock_of(start, 24 * 60 + 30) == 1410, "the 25th hour is 23:30, not clamped"
    # A span from 01:30 (first time) to 01:10 (second time) covers the whole
    # repeated hour on the clock, rather than vanishing as end < start.
    assert p._clock_spans(start, [[90, 130]]) == [[60, 120]]
    assert p._clock_spans(start, [[22 * 60, None]]) == [[1260, 1440]]
