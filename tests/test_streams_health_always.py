#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_streams_health_always.py
# Description: streams.json is the only carrier of _cameraHealth, and it was
#              not rewritten while go2rtc was unreachable — so the last healthy
#              summary stayed on screen through the very outage it should have
#              reported. It is now written every tick, with _go2rtcUp saying
#              which case it is and _writeTs saying how old it is.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json

from conftest import bare_plugin, load_plugin_module

load_plugin_module()

CAMS = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}]


def _plugin(tmp_path):
    p = bare_plugin()
    p._public_dashboards_dir = lambda: str(tmp_path)
    p.cameras = CAMS
    p._cam_state = {"10.0.0.5": {"fail_count": 4, "last_ok": 100.0, "last_failure": 200.0}}
    return p


def _read(tmp_path):
    return json.loads((tmp_path / "streams.json").read_text(encoding="utf-8"))


def test_written_when_go2rtc_is_unreachable(tmp_path):
    p = _plugin(tmp_path)
    p._write_streams_json(None)
    data = _read(tmp_path)
    assert data["_go2rtcUp"] is False
    assert isinstance(data["_writeTs"], float)
    assert data["_cameraHealth"]["10.0.0.5"]["state"] == "offline"


def test_written_when_go2rtc_is_up(tmp_path):
    p = _plugin(tmp_path)
    p._write_streams_json({"front": {"producers": [{"url": "rtsp://u:p@h/", "bytes_recv": 5}]}})
    data = _read(tmp_path)
    assert data["_go2rtcUp"] is True
    assert data["front"]["producers"] == [{"bytes_recv": 5}], "sanitising still happens"
    assert "_writeTs" in data and "_cameraHealth" in data


def test_an_outage_replaces_the_healthy_file(tmp_path):
    p = _plugin(tmp_path)
    p._cam_state["10.0.0.5"]["fail_count"] = 0
    p._write_streams_json({})
    assert _read(tmp_path)["_cameraHealth"]["10.0.0.5"]["state"] == "ok"
    p._cam_state["10.0.0.5"]["fail_count"] = 5
    p._write_streams_json(None)
    assert _read(tmp_path)["_cameraHealth"]["10.0.0.5"]["state"] == "offline"
