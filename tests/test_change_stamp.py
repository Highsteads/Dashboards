#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_change_stamp.py
# Description: Contract tests for the v2.70.0 liveness stamp — the tiny
#              /public/dashboards/changed.stamp heartbeat that lets the pages
#              stop calling /message/ BEFORE the plugin host dies (a request
#              in flight there at host-stop wedges all of IWS for ~298 s).
#              Pins: schema + atomic write, ledger high-water mark, the
#              freeze ordering (no "run" write may land after the "stopping"
#              sentinel), and shutdown() writing the sentinel before any slow
#              teardown begins.
# Author:      CliveS & Claude Fable 5
# Date:        31-07-2026
# Version:     1.0

import json
import os
import threading
import time


from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()


def _stamp_plugin(tmp_path):
    """bare_plugin + exactly the state the stamp machinery touches."""
    p = bare_plugin()
    p._stamp_stop = threading.Event()
    p._stamp_lock = threading.Lock()
    p._stamp_thread = None
    p._boot_ts = 1111.0
    p._stamp_last_write = 0.0
    p._dev_changes = {}
    p._dev_deleted = {}
    p._public_dashboards_dir = lambda: str(tmp_path)
    return p


def _read(tmp_path):
    with open(os.path.join(str(tmp_path), plugin.STAMP_FILENAME),
              encoding="utf-8") as fh:
        return json.load(fh)


def test_stamp_schema_and_atomicity(tmp_path):
    p = _stamp_plugin(tmp_path)
    p._dev_changes = {1: 50.0, 2: 60.0}
    with p._stamp_lock:
        p._write_stamp_locked("run")
    d = _read(tmp_path)
    assert d["v"] == 1
    assert d["boot"] == 1111.0
    assert d["state"] == "run"
    assert d["hwm"] == 60.0
    assert isinstance(d["ts"], float) and d["ts"] > 0
    # _write_atomic must leave no temp residue behind.
    leftovers = [f for f in os.listdir(str(tmp_path))
                 if f != plugin.STAMP_FILENAME]
    assert leftovers == []


def test_ledger_hwm_spans_both_dicts_and_empty_is_zero(tmp_path):
    p = _stamp_plugin(tmp_path)
    assert p._ledger_hwm() == 0.0
    p._dev_changes = {1: 10.0}
    p._dev_deleted = {2: 99.5}
    assert p._ledger_hwm() == 99.5


def test_note_change_respects_the_write_gap(tmp_path):
    p = _stamp_plugin(tmp_path)
    # A write happened just now: the leading-edge path must decline.
    p._stamp_last_write = time.time()
    p._stamp_note_change()
    assert not os.path.exists(os.path.join(str(tmp_path), plugin.STAMP_FILENAME))
    # Gap elapsed: it writes.
    p._stamp_last_write = 0.0
    p._stamp_note_change()
    assert _read(tmp_path)["state"] == "run"


def test_freeze_bars_every_later_run_write(tmp_path):
    p = _stamp_plugin(tmp_path)
    p._freeze_stamp()
    assert _read(tmp_path)["state"] == "stopping"
    # The two "run" writers must now both be no-ops.
    p._stamp_last_write = 0.0
    p._stamp_note_change()
    assert _read(tmp_path)["state"] == "stopping"


class _RacingLock:
    """A lock proxy that fires the stop event at the moment of acquisition —
    the exact freeze-while-waiting-for-the-lock race the inner re-check in
    _stamp_note_change exists for. Without that re-check, the write proceeds
    and a late "run" clobbers the sentinel."""

    def __init__(self, real, event):
        self._real, self._event = real, event

    def __enter__(self):
        self._event.set()
        return self._real.__enter__()

    def __exit__(self, *a):
        return self._real.__exit__(*a)


def test_note_change_re_checks_the_stop_event_inside_the_lock(tmp_path):
    p = _stamp_plugin(tmp_path)
    p._stamp_lock = _RacingLock(threading.Lock(), p._stamp_stop)
    p._stamp_note_change()   # outer check passes; freeze lands mid-acquisition
    assert not os.path.exists(os.path.join(str(tmp_path), plugin.STAMP_FILENAME)), \
        "a run write slipped in after the freeze"


def test_stamp_thread_beats_then_freeze_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin, "STAMP_PERIOD_SECONDS", 0.02)
    p = _stamp_plugin(tmp_path)
    p._start_stamp_thread()
    deadline = time.time() + 2.0
    path = os.path.join(str(tmp_path), plugin.STAMP_FILENAME)
    while not os.path.exists(path) and time.time() < deadline:
        time.sleep(0.01)
    assert _read(tmp_path)["state"] == "run", "thread never wrote a heartbeat"
    p._freeze_stamp()
    p._stamp_thread.join(timeout=1.0)
    assert not p._stamp_thread.is_alive(), "stamp thread failed to exit"
    # Give any (buggy) straggler write a chance to land, then re-check: the
    # sentinel must survive.
    time.sleep(0.1)
    assert _read(tmp_path)["state"] == "stopping"


def test_shutdown_writes_sentinel_then_quiesces_before_teardown(tmp_path, monkeypatch):
    p = _stamp_plugin(tmp_path)
    p.pluginDisplayName = "Dashboards"
    seen = {}

    def _sleep(secs):
        # The quiesce: after the sentinel, the host must stay alive long
        # enough for a gated page's ≤2 s-stale verdict window to expire —
        # a 2 s teardown beat the gate on the third verification restart.
        seen["quiesce"] = secs
        seen["state_at_quiesce"] = _read(tmp_path)["state"]
        seen["order"] = seen.get("order", []) + ["quiesce"]

    monkeypatch.setattr(plugin.time, "sleep", _sleep)

    def _pool_stop():
        seen["state_at_pool_stop"] = _read(tmp_path)["state"]
        seen["order"] = seen.get("order", []) + ["pool"]

    p._stop_snapshot_pool = _pool_stop
    p._stop_mjpeg_proxy = lambda: seen.setdefault("order", []).append("mjpeg")
    p._stop_go2rtc = lambda: seen.setdefault("order", []).append("go2rtc")
    p._stop_weather_thread = lambda: seen.setdefault("order", []).append("weather")
    p.shutdown()
    assert seen["state_at_quiesce"] == "stopping", "sentinel must precede the quiesce"
    assert seen["quiesce"] == plugin.STAMP_QUIESCE_SECONDS
    assert seen["quiesce"] > plugin.STAMP_PERIOD_SECONDS, \
        "quiesce must outlast the gate's stale-verdict window"
    assert seen["state_at_pool_stop"] == "stopping"
    # go2rtc stops BEFORE the pool (v2.95.1): a snapshot worker blocked in
    # requests.get() against go2rtc fails at once when its listener closes,
    # instead of running out a 15 s timeout while shutdown waits on it.
    assert seen["order"] == ["quiesce", "go2rtc", "pool", "mjpeg", "weather"]
