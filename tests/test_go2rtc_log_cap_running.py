#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_go2rtc_log_cap_running.py
# Description: go2rtc.log was capped at 5 MB only when go2rtc STARTED. A camera
#              that stays offline makes go2rtc log a failed dial every second
#              or two (11,518 such lines measured live, about 6-9 MB a day),
#              and a healthy go2rtc runs for days, so the file grew without
#              bound between starts. The supervisor's healthy branch now caps
#              it too. These drive the real O_APPEND file the child writes to.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import os

from conftest import bare_plugin, load_plugin_module

load_plugin_module()
import cameras_mixin  # noqa: E402


class _Proc:
    returncode = None
    pid = 1

    def poll(self):
        return None                        # healthy


def _plugin(tmp_path, monkeypatch, cap=1000):
    monkeypatch.setattr(cameras_mixin, "GO2RTC_LOG_CAP_BYTES", cap)
    p = bare_plugin()
    p._go2rtc_dir = lambda: str(tmp_path)
    path = p._go2rtc_log_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    p._go2rtc_logfile = os.fdopen(fd, "ab", buffering=0)
    p._go2rtc_log_day = None
    p._go2rtc_proc = _Proc()
    p._go2rtc_wanted = True
    return p, path


def test_healthy_supervision_caps_an_oversized_log(tmp_path, monkeypatch):
    p, path = _plugin(tmp_path, monkeypatch)
    p._go2rtc_logfile.write(b"ERR dial tcp: connection refused\n" * 100)   # 3.3 KB > cap
    p._supervise_go2rtc()
    size = os.path.getsize(path)
    assert size < 1000, f"log not capped while go2rtc runs ({size} bytes)"
    assert b"date marker" in open(path, "rb").read(), "fresh file must open dated"
    p._go2rtc_logfile.close()


def test_the_writer_carries_on_at_the_start_with_no_hole(tmp_path, monkeypatch):
    """O_APPEND: after the truncate the child's next write lands at the new
    end, not at its old offset behind a run of zero bytes."""
    p, path = _plugin(tmp_path, monkeypatch)
    p._go2rtc_logfile.write(b"x" * 5000)
    p._supervise_go2rtc()
    p._go2rtc_logfile.write(b"after\n")
    data = open(path, "rb").read()
    assert b"\x00" not in data
    assert data.endswith(b"after\n") and len(data) < 200
    p._go2rtc_logfile.close()


def test_a_small_log_is_left_alone(tmp_path, monkeypatch):
    p, path = _plugin(tmp_path, monkeypatch)
    p._go2rtc_logfile.write(b"one line\n")
    p._go2rtc_log_day = "already stamped"
    before = open(path, "rb").read()
    assert p._cap_go2rtc_log() is False
    assert open(path, "rb").read() == before
    p._go2rtc_logfile.close()


def test_no_open_log_is_not_an_error(tmp_path, monkeypatch):
    p, _ = _plugin(tmp_path, monkeypatch)
    p._go2rtc_logfile.close()
    assert p._cap_go2rtc_log() is False
