#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_login_hosts.py
# Description: The shared camera login goes only to approved addresses
#              (3.46.0). Anyone holding the API key can change a camera's
#              address, from Settings or the dashboards_set_camera MCP tool,
#              and go2rtc then dialled it with the ONE shared camera login:
#              point a camera at your own RTSP server and the household's
#              camera password arrives on the next restart. The login now
#              goes only to addresses recorded when it was last confirmed in
#              Configure (kept in pluginPrefs, which a Settings save cannot
#              write). Any other address is streamed with no login, and the
#              log, the Settings save reply and the MCP reply say why and how
#              to approve it. The first start of 3.46.0 approves what is
#              running, so an existing install keeps working.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import cameras_mixin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SECRET = "s3cret-pass"


def _cam(host, name, vendor="dahua"):
    return {"host": host, "name": name, "vendor": vendor}


@pytest.mark.parametrize("raw, want", [
    (None, None),                                     # never recorded
    ("", set()),                                      # recorded, nothing approved
    ("192.0.2.1,192.0.2.2", {"192.0.2.1", "192.0.2.2"}),
    (" 192.0.2.1 , cam.lan ", {"192.0.2.1", "cam.lan"}),
    ("192.0.2.1,bad host\nstreams:,", {"192.0.2.1"}),
    (["192.0.2.1", 7, None], {"192.0.2.1"}),
])
def test_the_recorded_list(raw, want):
    assert plugin.Plugin._parse_login_hosts(raw) == want


def _yaml(monkeypatch, tmp_path, approved):
    said = []
    monkeypatch.setattr(cameras_mixin, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    p.cam_user, p.cam_pass, p.lan_ip = "admin", SECRET, "192.0.2.100"
    p._go2rtc_config_path = lambda: str(tmp_path / "go2rtc.yaml")
    p._activity = lambda *a, **k: None
    p.cam_login_hosts = approved
    p.cameras = p._vet_cameras([_cam("192.0.2.1", "Front Door"),
                                _cam("203.0.113.66", "Drive", vendor="hikvision")])
    p._write_go2rtc_config()
    text = (tmp_path / "go2rtc.yaml").read_text(encoding="utf-8")
    streams = dict(line.strip().split(": ", 1)
                   for line in text.split("streams:", 1)[1].strip().splitlines())
    return streams, said


def test_an_approved_camera_gets_the_login_and_a_repointed_one_does_not(monkeypatch, tmp_path):
    streams, said = _yaml(monkeypatch, tmp_path, {"192.0.2.1"})
    assert SECRET in streams["front_door"] and "admin:" in streams["front_door"]
    assert SECRET not in streams["drive"] and "admin" not in streams["drive"]
    assert streams["drive"] == "rtsp://203.0.113.66:554/Streaming/Channels/102"
    warned = [m for lvl, m in said if lvl == "WARNING" and "camera login" in m]
    assert len(warned) == 1 and "Drive (203.0.113.66)" in warned[0]
    assert "Configure" in warned[0] and "Save" in warned[0], "it says how to approve it"


def test_nothing_recorded_or_nothing_approved_sends_no_login(monkeypatch, tmp_path):
    for approved in (None, set()):
        streams, _ = _yaml(monkeypatch, tmp_path, approved)
        assert not any(SECRET in v for v in streams.values()), approved


def test_every_approved_camera_quietly_gets_it(monkeypatch, tmp_path):
    streams, said = _yaml(monkeypatch, tmp_path, {"192.0.2.1", "203.0.113.66"})
    assert all(SECRET in v for v in streams.values())
    assert not [m for lvl, m in said if lvl == "WARNING" and "camera login" in m]


def _recording_plugin(monkeypatch):
    said = []
    monkeypatch.setattr(cameras_mixin, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    p.pluginPrefs = {}
    p.savePluginPrefs = MagicMock()
    return p, said


def test_recording_writes_plugin_prefs_and_names_what_is_new(monkeypatch):
    p, said = _recording_plugin(monkeypatch)
    p._record_camera_login_hosts(["192.0.2.1"], "first start")
    assert p.pluginPrefs["cameraLoginHosts"] == "192.0.2.1"
    assert p.savePluginPrefs.called
    dialog = {}
    p._record_camera_login_hosts(["192.0.2.1", "192.0.2.9", "bad host"], "Configure saved", prefs=dialog)
    assert p.cam_login_hosts == {"192.0.2.1", "192.0.2.9"}
    assert dialog["cameraLoginHosts"] == "192.0.2.1,192.0.2.9", "the dialog's own save keeps it"
    assert any("newly approved: 192.0.2.9" in m for _l, m in said), said


def test_the_list_is_kept_where_a_settings_save_cannot_reach():
    """The API key reaches the settings store; it must not reach this list."""
    src = (ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/config_mixin.py").read_text(encoding="utf-8")
    assert "cameraLoginHosts" not in src.split("def handleSaveDashboardsConfig", 1)[1].split("cameraLoginWithheld", 1)[0]
    mixin = (ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/cameras_mixin.py").read_text(encoding="utf-8")
    rec = mixin.split("def _record_camera_login_hosts", 1)[1].split("return self.cam_login_hosts", 1)[0]
    assert "cfg_store" not in rec and "_save_config_store" not in rec


def test_the_first_start_approves_what_is_running_so_nothing_breaks():
    src = (ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/plugin.py").read_text(encoding="utf-8")
    init = src.split("def __init__", 1)[1].split("def ", 1)[0]
    assert re.search(r'self\.cam_login_hosts = self\._parse_login_hosts\(pluginPrefs\.get\("cameraLoginHosts"\)\)\s*'
                     r'if self\.cam_login_hosts is None:\s*'
                     r'self\._record_camera_login_hosts\(\[c\["host"\] for c in self\.cameras\], "first start"\)', init)


def test_configure_save_approves_the_saved_and_running_cameras(monkeypatch):
    p, _said = _recording_plugin(monkeypatch)
    p.cam_user = p.cam_pass = ""
    p.indigo_log_handler = MagicMock()
    p._write_config_js = MagicMock()
    p._stop_weather_thread = MagicMock()
    p._start_weather_thread = MagicMock()
    p.cameras = [_cam("192.0.2.1", "Front")]
    p.cfg_store = {"cameras": [_cam("192.0.2.1", "Front"), _cam("192.0.2.7", "Side")]}
    p.cam_login_hosts = {"192.0.2.1"}
    dialog = {"logLevel": 20}
    p.closedPrefsConfigUi(dialog, userCancelled=False)
    assert p.cam_login_hosts == {"192.0.2.1", "192.0.2.7"}
    assert dialog["cameraLoginHosts"] == "192.0.2.1,192.0.2.7"


def test_a_cancelled_configure_approves_nothing(monkeypatch):
    p, _said = _recording_plugin(monkeypatch)
    p.cfg_store = {"cameras": [_cam("192.0.2.7", "Side")]}
    p.cam_login_hosts = set()
    p.closedPrefsConfigUi({}, userCancelled=True)
    assert p.cam_login_hosts == set()


def test_the_settings_save_says_which_cameras_are_not_approved(monkeypatch):
    p = bare_plugin()
    p._save_config_store = lambda clean: {"config": clean}
    p._write_config_js = MagicMock()
    p._build_rooms_json = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_store = {}
    p.cameras = []
    p.cam_login_hosts = {"10.0.0.5"}

    class A:
        props = {"request_body": json.dumps({"config": {"cameras": [
            {"host": "10.0.0.5", "name": "Front", "vendor": "dahua"},
            {"host": "10.0.0.66", "name": "Drive", "vendor": "dahua"}]}}),
            "headers": {"Content-Type": "application/json"}}
    reply = p.handleSaveDashboardsConfig(A())
    body = json.loads(reply["content"])
    assert reply["status"] == 200 and body["cameraLoginWithheld"] == ["10.0.0.66"]


def test_the_settings_page_shows_it():
    page = (ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages/settings.html").read_text(encoding="utf-8")
    assert "window._camLoginHosts = Array.isArray(res.cameraLoginHosts)" in page
    assert 'id="cam-login-note"' in page
    assert "res.cameraLoginWithheld" in page


def test_the_mcp_tool_says_a_new_address_is_not_approved(monkeypatch, tmp_path):
    from test_mcp_tools import call, make_plugin
    p, _state, _ = make_plugin(monkeypatch, tmp_path,
                               store={"cameras": [_cam("10.0.0.5", "Front")]},
                               running=[_cam("10.0.0.5", "Front")])
    p.cam_login_hosts = {"10.0.0.5"}
    out = call(p, "set_camera", host="198.51.100.9", name="Drive", vendor="dahua")
    assert out["status"] == "ok", out
    assert out["result"]["loginWithheld"] is True
    assert "Configure" in out["result"]["note"]
    listed = call(p, "list_cameras")["result"]
    assert listed["loginWithheld"] == ["198.51.100.9"]
