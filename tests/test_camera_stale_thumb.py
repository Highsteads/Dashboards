#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_stale_thumb.py
# Description: A thumbnail that stops being made is removed, so the page falls
#              back to the full picture (review 24-09-2026 [33]). It used to
#              stay in the stills folder, answered 304 on every poll, and grid
#              tiles showed a frame hours old while health said ok. One bad
#              frame still keeps the last thumbnail.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import threading

from conftest import bare_plugin

HOST = "192.0.2.10"


def _plugin(tmp_path, thumbs):
    p = bare_plugin()
    p._cam_state = {HOST: {"ok_count": 0, "fail_count": 0, "last_ok": 0,
                           "last_failure": 0, "last_log": 0}}
    p._cam_inflight_lock = threading.Lock()
    p._cam_inflight = set()
    p._thumb_broken = False
    p._fetch_one_snapshot = lambda host: (True, b"\xff\xd8full")
    p._cam_jpg_path = lambda host: str(tmp_path / f"cam-{host}.jpg")
    p._cam_thumb_path = lambda host: str(tmp_path / f"cam-{host}-thumb.jpg")
    seq = iter(thumbs)
    p._make_thumb = lambda payload: next(seq)
    return p


def test_a_run_of_frames_without_a_thumb_removes_the_old_one(tmp_path):
    p = _plugin(tmp_path, [b"thumb", None, None, None])
    cam = {"host": HOST, "name": "Drive"}
    thumb = tmp_path / f"cam-{HOST}-thumb.jpg"
    p._snapshot_worker(cam)
    assert thumb.read_bytes() == b"thumb"
    p._snapshot_worker(cam)
    assert thumb.exists(), "one bad frame keeps the last thumbnail"
    p._snapshot_worker(cam)
    p._snapshot_worker(cam)
    assert not thumb.exists(), "a thumbnail nobody refreshes must not be served for ever"
    assert (tmp_path / f"cam-{HOST}.jpg").exists()


def test_pillow_gone_removes_the_thumb_at_once(tmp_path):
    p = _plugin(tmp_path, [b"thumb", None])
    cam = {"host": HOST, "name": "Drive"}
    p._snapshot_worker(cam)
    p._thumb_broken = True
    p._snapshot_worker(cam)
    assert not (tmp_path / f"cam-{HOST}-thumb.jpg").exists()


def test_a_missing_thumb_is_not_an_error(tmp_path):
    p = _plugin(tmp_path, [None] * 5)
    for _ in range(5):
        p._snapshot_worker({"host": HOST, "name": "Drive"})
    assert p._cam_state[HOST]["ok_count"] == 5
