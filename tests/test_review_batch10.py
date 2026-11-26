#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_review_batch10.py
# Description: Server-side camera fixes from the 25/26-Nov-2026 deep review
#              (3.73.12): a still that is fetched but cannot be stored is a
#              failed snapshot, logged once a minute and not every two
#              seconds; the health file's own write failure is throttled the
#              same way; and a camera's last good picture goes out of date.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026
# Version:     1.0
import threading

from conftest import bare_plugin, load_plugin_module

load_plugin_module()
import cameras_mixin  # noqa: E402  (importable once the plugin module is loaded)

HOST = "192.0.2.10"


def _plugin(tmp_path):
    load_plugin_module()
    p = bare_plugin()
    p._cam_state = {HOST: {"ok_count": 0, "fail_count": 0, "last_ok": None,
                           "last_failure": None, "last_log": 0}}
    p._cam_inflight_lock = threading.Lock()
    p._cam_inflight = set()
    p._thumb_broken = False
    p._fetch_one_snapshot = lambda host: (True, b"\xff\xd8full")
    p._cam_jpg_path = lambda host: str(tmp_path / f"cam-{host}.jpg")
    p._cam_thumb_path = lambda host: str(tmp_path / f"cam-{host}-thumb.jpg")
    p._make_thumb = lambda payload: None
    return p


def test_a_still_that_cannot_be_stored_is_a_failed_snapshot(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(cameras_mixin, "log", lambda msg, level="INFO": lines.append((level, msg)))
    p = _plugin(tmp_path)

    def full_disk(path, data):
        raise OSError(28, "No space left on device")
    p._write_atomic = full_disk
    cam = {"host": HOST, "name": "Drive"}
    for _ in range(5):
        p._snapshot_worker(cam)
    st = p._cam_state[HOST]
    assert st["fail_count"] == 5 and st["last_failure"] is not None
    assert st["ok_count"] == 0 and st["last_ok"] is None
    errors = [m for lvl, m in lines if lvl == "ERROR"]
    assert len(errors) == 1, "one line, then one a minute: it was one per camera every two seconds"
    health = p._camera_health_payload([cam], p._cam_state)
    assert health[HOST]["state"] == "offline", "three in a row is offline, as for a failed fetch"


def test_the_health_file_failing_to_write_warns_once_a_minute(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(cameras_mixin, "log", lambda msg, level="INFO": lines.append((level, msg)))
    load_plugin_module()
    p = bare_plugin()
    p.cameras = []
    p._cam_state = {}
    p._public_dashboards_dir = lambda: str(tmp_path)

    def refuse(path, data):
        raise OSError(13, "Permission denied")
    p._write_atomic = refuse
    for _ in range(4):
        p._write_streams_json({})
    assert len(lines) == 1 and lines[0][0] == "WARNING"


def test_a_good_picture_goes_out_of_date():
    load_plugin_module()
    p = bare_plugin()
    cam = [{"host": HOST, "name": "Drive"}]
    states = {HOST: {"fail_count": 0, "last_ok": 1000.0, "last_failure": None}}
    f = p._camera_health_payload
    assert f(cam, states)[HOST]["state"] == "ok"                       # no ageing asked for
    assert f(cam, states, now=1100.0, max_ok_age=120.0)[HOST]["state"] == "ok"
    assert f(cam, states, now=1500.0, max_ok_age=120.0)[HOST]["state"] == "unknown"
    states[HOST]["fail_count"] = 3
    assert f(cam, states, now=1500.0, max_ok_age=120.0)[HOST]["state"] == "offline"


def test_how_long_a_good_picture_counts():
    load_plugin_module()
    p = bare_plugin()
    p._stills_idle_seconds = lambda: 300
    assert p._camera_ok_max_age() == 960        # three idle checks and a minute
    p._stills_idle_seconds = lambda: 0
    assert p._camera_ok_max_age() == 120.0      # idle check off: only a watched camera is asked
