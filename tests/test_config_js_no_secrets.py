#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_config_js_no_secrets.py
# Description: Pins the plugin's single most important security invariant:
#              config.js lives in the ANONYMOUS /public namespace (served to
#              the internet over the reflector), and NO credential may ever be
#              written into it — the v1.20.0 lesson, unpinned until v2.73.0.
# Author:      CliveS & Claude Fable 5
# Date:        31-07-2026
# Version:     1.0


from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()

API_KEY  = "sk-THE-API-KEY-THAT-MUST-NEVER-LEAK"
CAM_PASS = "cam-password-must-never-leak"
PIN      = "4321"


def _write(tmp_path):
    p = bare_plugin()
    p.api_url = "http://192.168.1.10:8176"
    p.api_key = API_KEY
    p.cam_user = "admin"
    p.cam_pass = CAM_PASS
    p.control_pin = PIN
    p.pin_required = [1, 2]
    p.favourites = []
    p.custom_links = []
    p.guest_token = "guest-token-value"
    p.main_cameras = []
    p.sigen_legacy_url = ""
    p.lan_ip = "192.168.1.10"
    p.pluginVersion = "0.0.0-test"
    p._load_config_store = lambda: {"arrayKwp": 14.25}
    p._public_dashboards_dir = lambda: str(tmp_path)
    p._write_config_js()
    return (tmp_path / "config.js").read_text(encoding="utf-8")


def test_no_credential_reaches_config_js(tmp_path):
    js = _write(tmp_path)
    assert API_KEY not in js, "the API key unlocks device control — v1.20.0"
    assert CAM_PASS not in js, "camera credentials never leave the server"
    assert "admin" not in js
    assert PIN not in js.replace('"pinRequired": [1, 2]', ""), \
        "the control PIN never travels to a browser"
    assert "guest-token-value" not in js


def test_the_benign_fields_still_publish(tmp_path):
    # The invariant test must not pass by the file being empty.
    js = _write(tmp_path)
    assert "baseURL" in js and "192.168.1.10" in js
    assert "arrayKwp" in js
    assert "pinRequired" in js
