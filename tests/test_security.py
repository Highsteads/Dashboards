#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_security.py
# Description: Regression tests for the /public credential-leak fixes — the
#              _sanitise_streams helper that strips camera RTSP creds from the
#              go2rtc streams map before it reaches the anonymous /public
#              namespace (file write AND the /streams proxy, v2.35.0/v2.36.0).
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

from conftest import load_plugin_module

plugin = load_plugin_module()
sanitise = plugin.Plugin._sanitise_streams
camera_health = plugin.Plugin._camera_health_payload

# A realistic go2rtc /api/streams shape: producer .url carries the camera
# admin credentials (rtsp://user:pass@host), consumers/bytes_recv are the only
# fields the cameras page actually reads.
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


def test_producer_url_credentials_are_stripped():
    safe = sanitise(GO2RTC)
    blob = repr(safe)
    assert "SuperSecret1" not in blob, "camera password leaked through sanitiser"
    assert "AnotherPass2" not in blob
    assert "rtsp://" not in blob, "RTSP URL (with creds) survived sanitising"
    for name, info in safe.items():
        for prod in info.get("producers", []):
            assert "url" not in prod, f"{name}: producer url not stripped"


def test_fields_the_page_reads_survive():
    safe = sanitise(GO2RTC)
    fd = safe["front_door_mjpeg"]
    assert fd["producers"][0]["bytes_recv"] == 12345, "bytes_recv must survive for the bandwidth indicator"
    assert fd["producers"][0]["state"] == "connected"
    # v2.73.0: the consumer LIST is scrubbed to a bare count — each entry
    # carries the viewer's IP, user agent and negotiated SDP, and no shipped
    # page reads past the count (the old assertion pinned a stale comment's
    # claim, not page code).
    assert "consumers" not in fd, "raw consumer entries must not reach /public"
    assert fd["consumers_n"] == 1


def test_empty_and_malformed_inputs_are_safe():
    assert sanitise(None) == {}
    assert sanitise({}) == {}
    # non-dict stream entry passes through untouched (defensive)
    assert sanitise({"x": "not-a-dict"}) == {"x": "not-a-dict"}
    # producers not a list -> left alone, no crash
    assert sanitise({"s": {"producers": "weird"}}) == {"s": {"producers": "weird"}}


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
