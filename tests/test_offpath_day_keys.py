#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_offpath_day_keys.py
# Description: A Timeline day (and a Solar string-hours day) built while it
#              was still TODAY is a part day. The cache key was the date alone
#              and the reader picks the TTL, so after midnight that part day was
#              read with the day-long past TTL and served as the finished day
#              for up to 24 hours. Whether the day was complete is now part of
#              the key.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
from datetime import datetime as _real_dt

import pytest

from conftest import bare_plugin, load_plugin_module

load_plugin_module()
import history_mixin  # noqa: E402


class _Action:
    def __init__(self, body):
        self.props = {"request_body": json.dumps(body), "headers": {}}


def _clock(monkeypatch, today):
    class _Fixed(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return _real_dt.strptime(today, "%Y-%m-%d").replace(hour=21)
    monkeypatch.setattr(history_mixin, "datetime", _Fixed)


def _key(monkeypatch, handler, date, today):
    _clock(monkeypatch, today)
    p = bare_plugin()
    p.pluginPrefs = {}
    seen = []
    p._offpath_get = lambda key, producer, ttl, wait=None: seen.append((key, ttl)) or ("fresh", {"ok": True})
    reply = getattr(p, handler)(_Action({"date": date}))
    assert reply["status"] == 200, reply
    return seen[0]


@pytest.mark.parametrize("handler", ["handleTimelineDay", "handleSolarStringHours"])
def test_a_part_day_is_never_read_as_the_finished_day(monkeypatch, handler):
    live_key, live_ttl = _key(monkeypatch, handler, "2026-09-23", today="2026-09-23")
    final_key, final_ttl = _key(monkeypatch, handler, "2026-09-23", today="2026-09-24")
    assert live_ttl < final_ttl
    assert live_key != final_key, (
        "the entry built as today must not answer the finished-day request")


@pytest.mark.parametrize("handler", ["handleTimelineDay", "handleSolarStringHours"])
def test_a_finished_day_keeps_one_key(monkeypatch, handler):
    """Two past-day requests still share one build — the cache still works."""
    a, _ = _key(monkeypatch, handler, "2026-09-20", today="2026-09-23")
    b, _ = _key(monkeypatch, handler, "2026-09-20", today="2026-09-24")
    assert a == b
