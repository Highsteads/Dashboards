#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_carbon_hhmm.py
# Description: _carbon_hhmm — a UTC forecast slot as local HH:MM, with
#              'tomorrow' only when the slot is genuinely on a later day. The
#              old test was `tm_yday != today`, so just after midnight a slot
#              from 23:30 YESTERDAY (the fetch admits one up to 30 min old)
#              read '23:30 tomorrow'.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import time
from conftest import bare_plugin, load_plugin_module


def _at(monkeypatch, local_now):
    """Pin time.localtime() (no-arg) to a fixed local moment."""
    plugin = load_plugin_module()
    real = time.localtime
    def fake(secs=None):
        return real(secs) if secs is not None else real(local_now)
    monkeypatch.setattr(plugin.time, "localtime", fake)
    return bare_plugin()


def _utc_iso(local_secs):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(local_secs))


def test_same_day_slot_has_no_suffix(monkeypatch):
    now = time.mktime(time.strptime("2026-09-02 10:00", "%Y-%m-%d %H:%M"))
    p = _at(monkeypatch, now)
    slot = time.mktime(time.strptime("2026-09-02 14:30", "%Y-%m-%d %H:%M"))
    assert p._carbon_hhmm(_utc_iso(slot)) == "14:30"


def test_next_day_slot_says_tomorrow(monkeypatch):
    now = time.mktime(time.strptime("2026-09-02 22:00", "%Y-%m-%d %H:%M"))
    p = _at(monkeypatch, now)
    slot = time.mktime(time.strptime("2026-09-03 02:00", "%Y-%m-%d %H:%M"))
    assert p._carbon_hhmm(_utc_iso(slot)) == "02:00 tomorrow"


def test_a_slot_from_yesterday_is_not_tomorrow(monkeypatch):
    now = time.mktime(time.strptime("2026-09-03 00:10", "%Y-%m-%d %H:%M"))
    p = _at(monkeypatch, now)
    slot = time.mktime(time.strptime("2026-09-02 23:30", "%Y-%m-%d %H:%M"))
    assert p._carbon_hhmm(_utc_iso(slot)) == "23:30"


def test_year_roll(monkeypatch):
    now = time.mktime(time.strptime("2026-12-31 22:00", "%Y-%m-%d %H:%M"))
    p = _at(monkeypatch, now)
    slot = time.mktime(time.strptime("2027-01-01 01:00", "%Y-%m-%d %H:%M"))
    assert p._carbon_hhmm(_utc_iso(slot)) == "01:00 tomorrow"
