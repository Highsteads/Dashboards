#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_security.py
# Description: Regression tests for the /public credential-leak fixes. The
#              go2rtc streams map carries each camera's RTSP URL with its
#              password; streams.json in the anonymous /public namespace now
#              carries only the health summary, so none of the map can reach it.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

from conftest import load_plugin_module

plugin = load_plugin_module()
camera_health = plugin.Plugin._camera_health_payload

# A realistic go2rtc /api/streams shape: producer .url carries the camera
# admin credentials (rtsp://user:pass@host) and consumers carry viewer details.
GO2RTC = {
    "front_door_mjpeg": {
        "producers": [
            {"url": "rtsp://admin:SuperSecret1@192.168.2.50:554/cam/realmonitor",
             "bytes_recv": 12345, "state": "connected"},
        ],
        "consumers": [{"type": "mjpeg", "bytes_send": 999}],
    },
    "drive_mjpeg": {
        "producers": [
            {"url": "rtsp://admin:AnotherPass2@192.168.2.51:554/Streaming/Channels/102",
             "bytes_recv": 678},
        ],
        "consumers": [],
    },
}


def _written(tmp_path, streams):
    import json
    from conftest import bare_plugin
    p = bare_plugin()
    p._public_dashboards_dir = lambda: str(tmp_path)
    p.cameras = [{"host": "192.168.2.50", "name": "Front"}]
    p._cam_state = {}
    p._write_streams_json(streams)
    return (tmp_path / "streams.json").read_text(encoding="utf-8"), json.loads(
        (tmp_path / "streams.json").read_text(encoding="utf-8"))


def test_no_part_of_the_go2rtc_map_reaches_public(tmp_path):
    """streams.json carries the health summary and nothing else: no producer
    URL, no viewer entry, no stream name, not even a field go2rtc adds later.
    (Until 24-Sep-2026 a denylist sanitiser passed any unknown field through.)"""
    raw, data = _written(tmp_path, dict(GO2RTC, drive_mjpeg=dict(
        GO2RTC["drive_mjpeg"], future_field="rtsp://admin:NewField3@x/")))
    for secret in ("SuperSecret1", "AnotherPass2", "NewField3", "rtsp://",
                   "front_door_mjpeg", "drive_mjpeg", "bytes_send"):
        assert secret not in raw, f"{secret!r} reached the anonymous streams.json"
    assert set(data) == set(plugin.Plugin.STREAMS_JSON_KEYS)


def test_the_keys_the_pages_read_are_written(tmp_path):
    _, data = _written(tmp_path, GO2RTC)
    assert data["_go2rtcUp"] is True
    assert isinstance(data["_writeTs"], float)
    assert "192.168.2.50" in data["_cameraHealth"]


def test_public_camera_health_contains_only_safe_operational_metadata():
    health = camera_health(
        [{"host": "front"}, {"host": "drive"}],
        {"front": {"fail_count": 0, "last_ok": 100.0, "last_failure": None},
         "drive": {"fail_count": 3, "last_ok": 50.0, "last_failure": 101.0}},
    )
    assert health["front"] == {"state": "ok", "consecutiveFailures": 0,
                               "lastOkTs": 100.0, "lastFailureTs": None}
    assert health["drive"]["state"] == "offline"
    assert health["drive"]["consecutiveFailures"] == 3
    assert "url" not in repr(health).lower()


if __name__ == "__main__":
    import sys
    fails = 0
    for n, fn in sorted(globals().items()):
        if n.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", n)
            except AssertionError as e:
                fails += 1
                print("FAIL", n, "-", e)
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)
