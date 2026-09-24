#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_list_vetted.py
# Description: The RUNNING camera list is held to the Settings-save rules
#              (review 24-09-2026 [36]). A hand-edited store or the legacy
#              import skipped them. Measured against go2rtc 1.9.14: a
#              duplicate stream name loads NO streams, and an empty one makes
#              the whole yaml unreadable, so go2rtc serves its unauthenticated
#              API on every interface. Nothing reached the Indigo log.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
from conftest import bare_plugin, load_plugin_module

load_plugin_module()
import cameras_mixin  # noqa: E402


def _cam(host, name, vendor="dahua"):
    return {"host": host, "name": name, "vendor": vendor, "room": "", "stream": "sub2"}


def test_bad_cameras_are_left_out_with_a_warning_and_the_rest_run(monkeypatch):
    said = []
    monkeypatch.setattr(cameras_mixin, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    cams = [
        _cam("192.0.2.1", "Front Door"),
        _cam("192.0.2.2", "front-door"),          # same slug: front_door
        _cam("192.0.2.3", "---"),                 # empty slug
        _cam("192.0.2.4 x\nstreams:", "Drive"),   # injection-shaped host
        _cam("192.0.2.1", "Garage"),              # host already used
        _cam("192.0.2.5", "Patio", vendor="axis"),
        _cam("cam-back.lan", "Back"),
    ]
    kept = p._vet_cameras(cams)
    assert [c["name"] for c in kept] == ["Front Door", "Back"]
    assert len(said) == 5 and all(lvl == "WARNING" for lvl, _ in said)


def test_the_yaml_gets_one_line_per_vetted_camera(monkeypatch, tmp_path):
    monkeypatch.setattr(cameras_mixin, "log", lambda *a, **k: None)
    p = bare_plugin()
    p.cam_user, p.cam_pass, p.lan_ip = "u", "p", "192.0.2.100"
    p._go2rtc_config_path = lambda: str(tmp_path / "go2rtc.yaml")
    p._activity = lambda *a, **k: None
    p.cameras = p._vet_cameras([_cam("192.0.2.1", "Front Door"), _cam("192.0.2.2", "Front-Door")])
    p._write_go2rtc_config()
    text = (tmp_path / "go2rtc.yaml").read_text(encoding="utf-8")
    streams = text.split("streams:", 1)[1].strip().splitlines()
    assert [s.split(":")[0].strip() for s in streams] == ["front_door"]


def test_the_save_and_the_load_share_one_host_rule():
    import config_mixin
    import dash_common
    assert config_mixin.CAMERA_HOST_RE is dash_common.CAMERA_HOST_RE
