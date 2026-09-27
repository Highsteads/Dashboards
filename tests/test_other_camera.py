#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_other_camera.py
# Description: The "other" camera make and per-camera logins (3.52.0).
#              Before this the plugin could only stream a Dahua or Hikvision
#              camera, because it built the stream address from those two
#              makers' fixed paths, and it sent every camera one shared login.
#              An "other" camera carries the owner's own RTSP address; a
#              camera whose login differs has one of its own in Configure.
#              What these tests hold shut:
#                - the address must name the camera's own host and carry no
#                  login, so an address typed by anyone holding the API key
#                  can never send a login somewhere else;
#                - nothing in it can break go2rtc.yaml;
#                - a camera's own login goes to its host and nowhere else, and
#                  is never written into a log line or an error;
#                - the Settings save, the MCP tool and the running list
#                  answer the same.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
import json

import pytest

from conftest import bare_plugin, load_plugin_module

load_plugin_module()
import cameras_mixin  # noqa: E402
import dash_common  # noqa: E402

SECRET = "sh4red-pass"
OWN = "0wn:p@ss/word"


def _other(host="192.0.2.50", name="Porch", rtsp=None):
    return {"host": host, "name": name, "vendor": "other",
            "rtsp": rtsp if rtsp is not None else f"rtsp://{host}:554/h264Preview_01_sub"}


# ── the address rule ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "rtsp://192.0.2.50:554/h264Preview_01_sub",
    "rtsp://192.0.2.50/stream1",
    "RTSP://192.0.2.50:8554/live/ch00_1?profile=2&x=%20",
    "rtsps://192.0.2.50:322/Streaming/Channels/101",
])
def test_a_good_address_passes(url):
    assert dash_common.camera_rtsp_problem(url, "192.0.2.50") is None


def test_the_host_is_matched_whatever_its_case():
    assert dash_common.camera_rtsp_problem("rtsp://Cam-Porch.lan/s", "cam-porch.LAN") is None


@pytest.mark.parametrize("url, needle", [
    ("", "missing"),
    ("http://192.0.2.50/video.mjpg", "rtsp://"),
    ("rtsp://admin:pw@192.0.2.50/s", "user name or password"),
    ("rtsp://192.0.2.99:554/s", "own host (192.0.2.50)"),
    ("rtsp://192.0.2.50.evil.example/s", "own host"),
    ("rtsp://192.0.2.50:abc/s", "port"),
    ("rtsp://192.0.2.50/a b", "spaces"),
    ("rtsp://192.0.2.50/s'\nstreams:", "spaces"),
    ("rtsp://192.0.2.50/s#x", "spaces"),
    ("rtsp://192.0.2.50/" + "a" * 400, "longer than"),
])
def test_a_bad_address_is_refused_and_says_why(url, needle):
    why = dash_common.camera_rtsp_problem(url, "192.0.2.50")
    assert why and needle in why, why


def test_an_other_camera_needs_its_address_and_a_known_make_does_not():
    assert "RTSP address" in dash_common.camera_problem(_other(rtsp=""))
    assert dash_common.camera_problem(_other()) is None
    dahua = {"host": "192.0.2.1", "name": "Front", "vendor": "dahua"}
    assert dash_common.camera_problem(dahua) is None, "a known make needs no address"
    assert "make" in dash_common.camera_problem({"host": "192.0.2.1", "vendor": "nosuchmake"})


def test_a_typed_address_on_a_known_make_is_held_to_the_same_rule():
    """3.53.0: any make may carry an address over its standard one, for a model
    that differs. It must pass exactly what an "other" address passes."""
    base = {"host": "192.0.2.1", "name": "Front", "vendor": "reolink"}
    assert dash_common.camera_problem(dict(base, rtsp="rtsp://192.0.2.1:554/h265Preview_01_main")) is None
    assert "own host" in dash_common.camera_problem(dict(base, rtsp="rtsp://203.0.113.9/s"))
    assert "user name" in dash_common.camera_problem(dict(base, rtsp="rtsp://a:b@192.0.2.1/s"))
    assert "rtsp://" in dash_common.camera_problem(dict(base, rtsp="junk"))


def test_parsing_keeps_a_typed_address_for_any_make_and_only_when_given():
    cams = dash_common._parse_cameras([
        _other(), {"host": "192.0.2.1", "name": "Front", "vendor": "dahua", "rtsp": " rtsp://192.0.2.1/x "},
        {"host": "192.0.2.2", "name": "Drive", "vendor": "hikvision", "rtsp": ""}])
    assert cams[0]["rtsp"] == "rtsp://192.0.2.50:554/h264Preview_01_sub"
    assert cams[1]["rtsp"] == "rtsp://192.0.2.1/x"
    assert "rtsp" not in cams[2]


# ── the table of makes ───────────────────────────────────────────────────

@pytest.mark.parametrize("make", list(dash_common.CAMERA_MAKES))
@pytest.mark.parametrize("stream", ["main", "sub2"])
def test_every_standard_address_passes_the_rule_a_typed_one_must(make, stream):
    """A template the owner could not have typed would be a way round the
    rule, and a bad one would break go2rtc.yaml for every camera."""
    for host in ("192.0.2.7", "cam-porch.lan"):
        url = dash_common.camera_make_address(make, host, stream)
        assert dash_common.camera_rtsp_problem(url, host) is None, (make, stream, url)


def test_the_makes_are_the_table_then_other_and_the_old_two_are_unchanged():
    assert dash_common.CAMERA_VENDORS == tuple(dash_common.CAMERA_MAKES) + ("other",)
    assert dash_common.CAMERA_VENDORS[:2] == ("dahua", "hikvision")
    addr = dash_common.camera_make_address
    # The two makes proven on real cameras: exactly what 3.51 streamed.
    assert addr("dahua", "h", "sub2") == "rtsp://h:554/cam/realmonitor?channel=1&subtype=2"
    assert addr("dahua", "h", "main") == "rtsp://h:554/cam/realmonitor?channel=1&subtype=0"
    assert addr("hikvision", "h", "sub2") == "rtsp://h:554/Streaming/Channels/102"
    assert addr("hikvision", "h", "main") == "rtsp://h:554/Streaming/Channels/101"
    assert addr("other", "h", "main") == "" and addr("nosuchmake", "h", "main") == ""


def test_the_mcp_manifest_offers_exactly_the_plugins_makes():
    from pathlib import Path
    root = Path(dash_common.__file__).parents[1]
    m = json.loads((root / "Resources/mcp-manifest.json").read_text(encoding="utf-8"))
    tool = next(t for t in m["tools"] if t["name"] == "set_camera")
    assert tuple(tool["inputSchema"]["properties"]["vendor"]["enum"]) == dash_common.CAMERA_VENDORS
    import mcp_tools
    assert mcp_tools.VENDORS is dash_common.CAMERA_VENDORS


# ── the login ────────────────────────────────────────────────────────────

def test_a_login_written_in_cannot_change_where_the_address_points():
    url = dash_common.rtsp_with_login("rtsp://192.0.2.50/s", "ad@min", OWN)
    assert url == "rtsp://ad%40min:0wn%3Ap%40ss%2Fword@192.0.2.50/s"
    from urllib.parse import urlsplit
    assert urlsplit(url).hostname == "192.0.2.50"
    assert dash_common.rtsp_with_login("rtsp://192.0.2.50/s", "", "x") == "rtsp://192.0.2.50/s"


def test_camera_logins_parse_from_a_dict_or_json_and_never_quote_a_value():
    good = {"192.0.2.50": {"user": "admin", "password": OWN}}
    assert dash_common.parse_camera_logins(good) == ({"192.0.2.50": ("admin", OWN)}, None)
    assert dash_common.parse_camera_logins(json.dumps(good))[0] == {"192.0.2.50": ("admin", OWN)}
    assert dash_common.parse_camera_logins("") == ({}, None)
    logins, why = dash_common.parse_camera_logins('{"192.0.2.50": {"user": "a", "password": "' + OWN)
    assert logins == {} and "not valid JSON" in why and OWN not in why
    logins, why = dash_common.parse_camera_logins(
        {"192.0.2.50": {"password": OWN}, "bad host": {"user": "a"}, "192.0.2.51": {"user": "b"}})
    assert logins == {"192.0.2.51": ("b", "")}
    assert "2 camera logins were left out" in why and OWN not in why


# ── go2rtc.yaml ──────────────────────────────────────────────────────────

def _yaml(monkeypatch, tmp_path, cams, approved=(), shared=True, own=None):
    said = []
    monkeypatch.setattr(cameras_mixin, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    p.cam_user, p.cam_pass = ("admin", SECRET) if shared else ("", "")
    p.cam_logins = own or {}
    p.lan_ip = "192.0.2.100"
    p._go2rtc_config_path = lambda: str(tmp_path / "go2rtc.yaml")
    p._activity = lambda *a, **k: None
    p.cam_login_hosts = set(approved)
    p.cameras = p._vet_cameras(cams)
    p._write_go2rtc_config()
    text = (tmp_path / "go2rtc.yaml").read_text(encoding="utf-8")
    streams = dict(line.strip().split(": ", 1)
                   for line in text.split("streams:", 1)[1].strip().splitlines())
    return streams, said, p


def test_an_approved_other_camera_gets_the_shared_login_quoted(monkeypatch, tmp_path):
    streams, _, _ = _yaml(monkeypatch, tmp_path, [_other()], approved={"192.0.2.50"})
    assert streams["porch"] == f"'rtsp://admin:{SECRET}@192.0.2.50:554/h264Preview_01_sub'"


def test_an_unapproved_other_camera_gets_no_login_and_a_warning(monkeypatch, tmp_path):
    streams, said, _ = _yaml(monkeypatch, tmp_path, [_other()])
    assert streams["porch"] == "'rtsp://192.0.2.50:554/h264Preview_01_sub'"
    assert any(lvl == "WARNING" and "Porch (192.0.2.50)" in m for lvl, m in said)


def test_its_own_login_goes_to_its_host_only_and_needs_no_approval(monkeypatch, tmp_path):
    front = {"host": "192.0.2.1", "name": "Front", "vendor": "dahua"}
    streams, said, _ = _yaml(monkeypatch, tmp_path, [_other(), front],
                             approved={"192.0.2.1"}, own={"192.0.2.50": ("viewer", OWN)})
    assert "viewer:0wn%3Ap%40ss%2Fword@192.0.2.50" in streams["porch"]
    assert SECRET not in streams["porch"]
    assert "viewer" not in streams["front"] and SECRET in streams["front"]
    assert not any(OWN in m or SECRET in m for _l, m in said), "no login reaches the log"


def test_a_bad_other_camera_never_reaches_the_file(monkeypatch, tmp_path):
    bad = _other(name="Evil", rtsp="rtsp://192.0.2.50/s'\n  api:\n    listen: ':1984'")
    streams, said, _ = _yaml(monkeypatch, tmp_path, [bad, _other(host="192.0.2.51", name="Ok")])
    assert list(streams) == ["ok"]
    assert any("leaving out camera 1 (Evil)" in m for _l, m in said)
    text = (tmp_path / "go2rtc.yaml").read_text(encoding="utf-8")
    assert text.count("listen: ':1984'") == 0


@pytest.mark.parametrize("make", [m for m in dash_common.CAMERA_MAKES])
def test_each_make_streams_its_standard_address_with_the_login(monkeypatch, tmp_path, make):
    cam = {"host": "192.0.2.7", "name": "Cam", "vendor": make}
    streams, _, _ = _yaml(monkeypatch, tmp_path, [cam], approved={"192.0.2.7"})
    want = dash_common.rtsp_with_login(
        dash_common.camera_make_address(make, "192.0.2.7", "sub2"), "admin", SECRET)
    assert streams["cam"] == want


def test_a_typed_address_replaces_the_makes_own(monkeypatch, tmp_path):
    cam = {"host": "192.0.2.7", "name": "Cam", "vendor": "reolink",
           "rtsp": "rtsp://192.0.2.7:554/h265Preview_01_main"}
    streams, _, _ = _yaml(monkeypatch, tmp_path, [cam], approved={"192.0.2.7"})
    assert streams["cam"] == f"'rtsp://admin:{SECRET}@192.0.2.7:554/h265Preview_01_main'"


def test_a_known_make_with_no_login_at_all_is_named(monkeypatch, tmp_path):
    front = {"host": "192.0.2.1", "name": "Front", "vendor": "dahua"}
    streams, said, _ = _yaml(monkeypatch, tmp_path, [front, _other()], shared=False)
    assert "@" not in streams["front"]
    warned = [m for lvl, m in said if lvl == "WARNING" and "WITHOUT a login" in m]
    assert len(warned) == 1 and "Front (192.0.2.1)" in warned[0] and "Porch" not in warned[0]


@pytest.mark.parametrize("cams, own, shared, want", [
    ([], {}, True, False),
    ([{"host": "192.0.2.1", "vendor": "dahua"}], {}, True, True),
    ([{"host": "192.0.2.1", "vendor": "dahua"}], {}, False, False),
    ([{"host": "192.0.2.1", "vendor": "dahua"}], {"192.0.2.1": ("u", "p")}, False, True),
    ([{"host": "192.0.2.50", "vendor": "other"}], {}, False, True),
])
def test_what_it_takes_for_the_cameras_to_run(cams, own, shared, want):
    p = bare_plugin()
    p.cameras, p.cam_logins = cams, own
    p.cam_user, p.cam_pass = ("u", "p") if shared else ("", "")
    assert p._cameras_can_stream() is want


def test_a_camera_with_its_own_login_is_not_reported_as_withheld():
    p = bare_plugin()
    p.cam_login_hosts = {"192.0.2.1"}
    p.cam_logins = {"192.0.2.50": ("u", "p")}
    cams = [{"host": "192.0.2.1"}, {"host": "192.0.2.50"}, {"host": "192.0.2.51"}]
    assert p._camera_login_withheld(cams) == ["192.0.2.51"]


# ── the Settings save ────────────────────────────────────────────────────

def _save(cfg):
    from test_save_config import make_plugin, save
    p, cap = make_plugin()
    body, status = save(p, cfg)
    return body, status, cap


def test_the_settings_save_keeps_an_other_camera():
    body, status, cap = _save({"cameras": [_other()]})
    assert status == 200 and body["ok"], body
    assert cap["clean"]["cameras"][0]["rtsp"] == "rtsp://192.0.2.50:554/h264Preview_01_sub"


@pytest.mark.parametrize("rtsp, needle", [
    ("", "missing"),
    ("rtsp://admin:pw@192.0.2.50/s", "user name or password"),
    ("rtsp://203.0.113.9/s", "own host"),
])
def test_the_settings_save_refuses_a_bad_address(rtsp, needle):
    body, status, _ = _save({"cameras": [_other(rtsp=rtsp)]})
    assert status == 400 and needle in body["error"] and "camera 1 (Porch)" in body["error"]


# ── the plugin's own settings ────────────────────────────────────────────

def test_resolving_credentials_reads_camera_logins_and_warns_without_the_value(monkeypatch):
    import plugin as plugin_mod
    said = []
    monkeypatch.setattr(plugin_mod, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    p._resolve_credentials({"cameraLogins": json.dumps({"192.0.2.50": {"user": "v", "password": OWN}})})
    assert p.cam_logins == {"192.0.2.50": ("v", OWN)} and not said
    p._resolve_credentials({"cameraLogins": '{"192.0.2.50": {"user": "v", "password": "' + OWN})
    assert p.cam_logins == {}
    assert said and said[0][0] == "WARNING" and OWN not in said[0][1]


def test_configure_offers_the_camera_logins_field():
    from pathlib import Path
    xml = (Path(dash_common.__file__).parent / "PluginConfig.xml").read_text(encoding="utf-8")
    assert '<Field id="cameraLogins" type="textfield"' in xml
    assert "Camera Logins:" in xml


# ── the MCP tool ─────────────────────────────────────────────────────────

def test_the_mcp_tool_adds_an_other_camera_and_shows_its_address(monkeypatch, tmp_path):
    from test_mcp_tools import call, make_plugin
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_camera", host="192.0.2.50", name="Porch", vendor="other",
               rtsp="rtsp://192.0.2.50:554/stream1")
    assert out["status"] == "ok", out
    assert state["store"]["cameras"][0]["rtsp"] == "rtsp://192.0.2.50:554/stream1"
    assert out["result"]["camera"]["rtsp"] == "rtsp://192.0.2.50:554/stream1"


def test_the_mcp_tool_refuses_what_the_settings_save_refuses(monkeypatch, tmp_path):
    from test_mcp_tools import call, make_plugin
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_camera", host="192.0.2.50", name="Porch", vendor="other")
    assert out["status"] == "error" and "RTSP address is missing" in out["error"]["message"]
    out = call(p, "set_camera", host="192.0.2.50", name="Porch", vendor="other",
               rtsp="rtsp://u:p@192.0.2.50/s")
    assert out["status"] == "error" and "user name or password" in out["error"]["message"]
    assert state["saves"] == 0


def test_the_mcp_tool_drops_the_address_when_the_make_changes(monkeypatch, tmp_path):
    from test_mcp_tools import call, make_plugin
    store = {"cameras": [_other()]}
    p, state, _ = make_plugin(monkeypatch, tmp_path, store=store, running=store["cameras"])
    out = call(p, "set_camera", host="192.0.2.50", vendor="hikvision")
    assert out["status"] == "ok", out
    assert "rtsp" not in state["store"]["cameras"][0]
    assert "rtsp" not in out["result"]["camera"]
