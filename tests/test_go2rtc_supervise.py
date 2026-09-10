#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_go2rtc_supervise.py
# Description: The go2rtc supervisor must keep trying after a FAILED restart.
#              Until 2.95.1 a supervised restart that failed to bind (the old
#              instance still held the port for a moment) left the process
#              handle None, and the next sweep read None as "never started —
#              no cameras" and returned. One unlucky restart switched
#              supervision off for good: every camera function dead until a
#              manual plugin restart, which is the exact failure the
#              supervisor was written to remove.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

from conftest import bare_plugin, load_plugin_module


class _Proc:
    def __init__(self, rc=None, pid=4242):
        self._rc = rc
        self.pid = pid
        self.returncode = rc

    def poll(self):
        return self._rc


def _sup(monkeypatch, wanted, proc, t=1000.0):
    plugin = load_plugin_module()
    p = bare_plugin()
    p._go2rtc_proc = proc
    p._go2rtc_wanted = wanted
    starts = []
    p._start_go2rtc = lambda: starts.append(1)
    p._stamp_go2rtc_log = lambda *a, **k: None
    monkeypatch.setattr(plugin.time, "time", lambda: t)
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    return p, starts


def test_healthy_process_is_left_alone(monkeypatch):
    p, starts = _sup(monkeypatch, True, _Proc(rc=None))
    p._supervise_go2rtc()
    assert starts == []


def test_never_started_is_not_supervised(monkeypatch):
    p, starts = _sup(monkeypatch, False, None)
    p._supervise_go2rtc()
    assert starts == []


def test_exited_process_is_restarted(monkeypatch):
    p, starts = _sup(monkeypatch, True, _Proc(rc=1))
    p._supervise_go2rtc()
    assert starts == [1]


def test_failed_restart_is_retried_not_forgotten(monkeypatch):
    """The regression: wanted, handle None (a start failed) -> retry under
    backoff, never the 'never started' exit."""
    p, starts = _sup(monkeypatch, True, None)
    p._supervise_go2rtc()
    assert starts == [1], "a wanted-but-absent go2rtc must be restarted"


def test_backoff_holds_between_retries(monkeypatch):
    plugin = load_plugin_module()
    p, starts = _sup(monkeypatch, True, None, t=1000.0)
    p._supervise_go2rtc()                      # first retry at t=1000, backoff 30
    monkeypatch.setattr(plugin.time, "time", lambda: 1010.0)
    p._supervise_go2rtc()                      # inside the backoff window
    assert starts == [1]
    monkeypatch.setattr(plugin.time, "time", lambda: 1031.0)
    p._supervise_go2rtc()                      # window elapsed
    assert starts == [1, 1]
