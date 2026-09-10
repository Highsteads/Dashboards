#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_shutdown_budget.py
# Description: shutdown() must not wait on the snapshot pool. Until 2.95.1
#              _stop_snapshot_pool called pool.shutdown(wait=True) BEFORE
#              go2rtc was signalled, so a worker blocked in a 15 s camera
#              fetch (plus a retry) held teardown — Indigo's polite-quit
#              window is ~20 s, after which the host is force-killed and
#              go2rtc is orphaned. Measured on DahuaEvents the same week:
#              "fixed" shutdowns that still took 21 s until the stopwatch
#              went on them. The order and the flags are what this locks.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

from conftest import bare_plugin


class _Pool:
    def __init__(self):
        self.calls = []

    def shutdown(self, wait=True, cancel_futures=False):
        self.calls.append((wait, cancel_futures))


def test_pool_stop_never_waits():
    p = bare_plugin()
    pool = _Pool()
    p._cam_pool = pool
    p._cam_pool_closed = False
    p._stop_snapshot_pool()
    assert pool.calls == [(False, True)]
    assert p._cam_pool is None and p._cam_pool_closed is True


def test_go2rtc_stops_before_the_pool_and_pool_is_closed_first(monkeypatch):
    from conftest import load_plugin_module
    plugin = load_plugin_module()
    p = bare_plugin()
    p.pluginDisplayName = "Dashboards"
    order = []
    p._freeze_stamp = lambda: order.append("freeze")
    monkeypatch.setattr(plugin.time, "sleep", lambda s: order.append("quiesce"))
    p._stop_stamp_thread = lambda: order.append("stamp")
    p._stop_go2rtc = lambda: order.append(("go2rtc", p._cam_pool_closed))
    p._stop_snapshot_pool = lambda: order.append("pool")
    p._stop_mjpeg_proxy = lambda: order.append("mjpeg")
    p._stop_weather_thread = lambda: order.append("weather")
    p._cam_pool_closed = False
    p.shutdown()
    assert order.index(("go2rtc", True)) < order.index("pool"), \
        "go2rtc must stop first, with the pool already closed to new work"
