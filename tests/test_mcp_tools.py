#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_mcp_tools.py
# Description: Behaviour of the plugin-provided MCP tools (v3.12.0): the
#              dispatch envelope (a JSON string, an in-band error, never a
#              raised exception), the invoke callback's refusal of IWS-shaped
#              requests, every tool's arguments and reply shape, and — the
#              part that matters most — that the write tools go through
#              Plugin._apply_config with the SAVED config as their base, so
#              two edits compose and nothing the Settings page stored is lost.
#              Also pins the v3.12.0 fix to _effective_config(): once the
#              store is in force it reports the saved cameras, not the ones
#              still streaming from before the last save.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module

PLUGIN_ID = "com.clives.indigoplugin.dashboards"


class FakeAction:
    def __init__(self, props):
        self.props = props


def _folders(names):
    return [types.SimpleNamespace(name=n, id=i + 1) for i, n in enumerate(names)]


def make_plugin(monkeypatch, tmp_path, store=None, running=None,
                folders=("Kitchen", "Hall", "Garage")):
    """A bare Plugin wired the way the tools read it: a controllable config
    store (captured on save), the persist side-effects stubbed, a module
    CAMERAS list standing in for what is streaming, and a stub Indigo with
    the given device folders and a temp install folder."""
    mod = load_plugin_module()
    p = bare_plugin()
    p.pluginId      = PLUGIN_ID
    p.pluginVersion = "3.12.0"
    p.pluginPrefs   = {}
    p.api_url       = "http://127.0.0.1:8176"
    p.api_key       = "k"
    p.cam_user, p.cam_pass = "u", "p"
    p._go2rtc_proc  = None
    p._mjpeg_server = None
    p.room_extras, p.pin_required, p.favourites, p.custom_links = {}, [], [], []
    p.control_pin   = (store or {}).get("controlPin", "")
    p.main_cameras  = list((store or {}).get("mainCameras") or [])
    p._hidden_scenes = lambda: set()
    state = {"store": dict(store or {}), "saves": 0}
    p._load_config_store = lambda: dict(state["store"])

    def _save(clean):
        state["store"] = dict(clean)
        state["saves"] += 1
        return dict(clean)
    p._save_config_store = _save
    p._write_config_js   = MagicMock()
    p._build_rooms_json  = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_loaded = bool(store)

    monkeypatch.setattr(mod, "CAMERAS", mod._parse_cameras(running or []))
    monkeypatch.setattr(mod, "SWAP_OUT_HOST", "")
    ind = sys.modules["indigo"]
    ind.devices.folders = _folders(folders)
    install = tmp_path / "Indigo 2025.2"
    install.mkdir(exist_ok=True)
    ind.server.getInstallFolderPath.return_value = str(install)
    return p, state, mod


def call(p, tool, **arguments):
    import mcp_tools
    return json.loads(mcp_tools.dispatch(p, tool, arguments))


def invoke(p, props):
    return p.handle_mcp_tool_invoke(FakeAction(props))


# ── envelope + dispatch ──────────────────────────────────────────────────

def test_unknown_tool_is_not_found_and_names_the_tools(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "make_tea")
    assert out["status"] == "error" and out["error"]["type"] == "not_found"
    assert "get_status" in out["error"]["details"]["tools"]


def test_non_object_arguments_are_a_validation_error(monkeypatch, tmp_path):
    import mcp_tools
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    out = json.loads(mcp_tools.dispatch(p, "get_status", ["not", "a", "dict"]))
    assert out["status"] == "error" and out["error"]["type"] == "validation"


def test_a_handler_bug_becomes_an_internal_error_and_is_logged(monkeypatch, tmp_path):
    import mcp_tools
    p, _, _ = make_plugin(monkeypatch, tmp_path)

    def boom(plugin, args):
        raise RuntimeError("wiring fault")
    monkeypatch.setitem(mcp_tools.HANDLERS, "get_status", boom)
    out = call(p, "get_status")
    assert out["status"] == "error" and out["error"]["type"] == "internal"
    assert "wiring fault" in out["error"]["message"]
    assert p.logger.error.called


def test_every_reply_is_a_json_string(monkeypatch, tmp_path):
    import mcp_tools
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    for tool in mcp_tools.TOOLS:
        raw = mcp_tools.dispatch(p, tool, {})
        assert isinstance(raw, str), tool
        env = json.loads(raw)
        assert env["status"] in ("ok", "error"), tool


# ── the invoke callback ──────────────────────────────────────────────────

def test_iws_shaped_request_is_refused_with_a_404_reply_dict(monkeypatch, tmp_path):
    """A browser with the API key reaching the hidden action over IWS must get
    an HTTP reply IWS can send, not a tool and not a bare string."""
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    reply = invoke(p, {"incoming_request_method": "POST", "request_body": '{"tool": "get_status"}'})
    assert isinstance(reply, dict) and reply["status"] == 404
    assert json.loads(reply["content"])["error"]


def test_invoke_hands_tool_and_json_arguments_to_dispatch(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    raw = invoke(p, {"tool": "list_room_folders", "arguments": "{}"})
    assert isinstance(raw, str)
    env = json.loads(raw)
    assert env["status"] == "ok" and "configured" in env["result"]


def test_invoke_rejects_unparseable_arguments_in_band(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    env = json.loads(invoke(p, {"tool": "get_status", "arguments": "{not json"}))
    assert env["status"] == "error" and env["error"]["type"] == "validation"


def test_invoke_never_raises_even_when_the_tool_module_fails(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    broken = types.ModuleType("mcp_tools")
    broken.err = lambda *a, **k: "unused"

    def dispatch(*a, **k):
        raise RuntimeError("module fault")
    broken.dispatch = dispatch
    monkeypatch.setitem(sys.modules, "mcp_tools", broken)
    env = json.loads(invoke(p, {"tool": "get_status", "arguments": "{}"}))
    assert env["status"] == "error" and env["error"]["type"] == "internal"
    assert p.logger.error.called


def test_invoke_without_a_tool_prop_and_no_iws_markers_is_not_found(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    env = json.loads(invoke(p, {}))
    assert env["status"] == "error" and env["error"]["type"] == "not_found"


# ── get_status / run_setup_check ─────────────────────────────────────────

def test_get_status_shape(monkeypatch, tmp_path):
    p, _, mod = make_plugin(monkeypatch, tmp_path, running=[
        {"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}])
    scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    (scripts / "Presence_Watch.py").write_text("# stub", encoding="utf-8")
    out = call(p, "get_status")
    assert out["status"] == "ok"
    r = out["result"]
    assert r["version"] == "3.12.0"
    assert r["dashboardUrl"].endswith("/public/dashboards/index.html")
    assert "legacy" in r["configSource"]
    assert r["roomFolders"]["source"] == "built-in defaults"
    assert r["roomFolders"]["existInIndigo"] == 3          # Kitchen, Hall, Garage exist
    assert "Bathroom" in r["roomFolders"]["missing"]
    assert r["cameras"] == {"saved": 1, "running": 1, "credentialsSet": True,
                            "go2rtcRunning": False, "mjpegProxyRunning": False}
    assert r["history"] == {"backend": "sqlite", "sqliteFound": False}
    assert "Presence_Watch.py" in r["companionScripts"]["present"]
    assert "Log_Error_Watch.py" in r["companionScripts"]["missing"]
    assert r["pluginLog"].endswith(os.path.join("Logs", PLUGIN_ID, "plugin.log"))


def test_run_setup_check_returns_every_check_as_data(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "run_setup_check")
    assert out["status"] == "ok"
    r = out["result"]
    assert r["checks"], "the sweep must produce checks"
    assert {c["verdict"] for c in r["checks"]} <= {"PASS", "FAIL", "SKIP"}
    for c in r["checks"]:
        assert set(c) == {"label", "ok", "detail", "optional", "verdict"}
        if c["verdict"] == "SKIP":
            assert c["optional"] and not c["ok"]
    s = r["summary"]
    assert s["counted"] == s["passed"] + len(s["failed"])
    assert len(s["skipped"]) + s["counted"] == len(r["checks"])
    assert r["allPassed"] == (not s["failed"])
    assert any(c["label"] == "Room folders" for c in r["checks"])


def test_menu_and_tool_share_one_list_of_checks(monkeypatch, tmp_path):
    """The menu item logs exactly the tuples _setup_checks builds — one
    builder, so the two surfaces cannot disagree."""
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    fixed = [("Alpha", True, "", False), ("Beta", False, "broken", False),
             ("Gamma", False, "optional thing", True)]
    p._setup_checks = lambda: list(fixed)
    p.pluginDisplayName = "Dashboards"
    p.menuTestSetup()
    lines = [c.args[0] for c in p.logger.info.call_args_list + p.logger.error.call_args_list]
    assert any("PASS — Alpha" in ln for ln in lines)
    assert any("FAIL — Beta" in ln for ln in lines)
    assert any("SKIP — Gamma" in ln for ln in lines)
    assert any("1 of 2 checks passed" in ln for ln in lines)
    out = call(p, "run_setup_check")["result"]
    assert [c["verdict"] for c in out["checks"]] == ["PASS", "FAIL", "SKIP"]
    assert out["summary"] == {"counted": 2, "passed": 1, "failed": ["Beta"], "skipped": ["Gamma"]}


# ── room folders ─────────────────────────────────────────────────────────

def test_list_room_folders_reports_source_and_missing(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path, store={"roomFolders": ["Kitchen", "Loft"]})
    r = call(p, "list_room_folders")["result"]
    assert r["configured"] == ["Kitchen", "Loft"]
    assert r["source"] == "settings store"
    assert r["matching"] == ["Kitchen"] and r["missing"] == ["Loft"]
    assert r["indigoFolders"] == ["Garage", "Hall", "Kitchen"]


def test_set_room_folders_refuses_unknown_names_and_lists_the_real_ones(monkeypatch, tmp_path):
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_room_folders", folders=["Kitchen", "kitchen", "Loft"])
    assert out["status"] == "error" and out["error"]["type"] == "validation"
    assert out["error"]["details"]["unknown"] == ["kitchen", "Loft"]
    assert out["error"]["details"]["available"] == ["Garage", "Hall", "Kitchen"]
    assert state["saves"] == 0, "a refused call must not touch the store"


@pytest.mark.parametrize("bad", [{}, {"folders": []}, {"folders": "Kitchen"}, {"folders": [1]}])
def test_set_room_folders_argument_validation(monkeypatch, tmp_path, bad):
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_room_folders", **bad)
    assert out["status"] == "error" and out["error"]["type"] == "validation"
    assert state["saves"] == 0


def test_set_room_folders_saves_through_apply_config_and_keeps_everything_else(monkeypatch, tmp_path):
    store = {
        "cameras":     [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}],
        "mainCameras": ["10.0.0.5"],
        "controlPin":  "1234",
        "arrayKwp":    14.25,                 # a raw-JSON-hatch key this build does not model
        "roomFolders": ["Kitchen"],
    }
    p, state, _ = make_plugin(monkeypatch, tmp_path, store=store)
    out = call(p, "set_room_folders", folders=["Hall", "Kitchen", "Hall"])
    assert out["status"] == "ok", out
    assert out["result"]["roomFolders"] == ["Hall", "Kitchen"]      # de-duplicated, order kept
    assert out["result"]["roomsBuilt"] == 2
    saved = state["store"]
    assert saved["roomFolders"] == ["Hall", "Kitchen"]
    assert saved["cameras"][0]["host"] == "10.0.0.5", "the saved cameras must survive"
    assert saved["mainCameras"] == ["10.0.0.5"]
    assert saved["controlPin"] == "1234", "the PIN must round-trip, never be cleared"
    assert saved["arrayKwp"] == 14.25, "unknown store keys must round-trip"
    assert p._build_rooms_json.called, "rooms.json is rebuilt so the change is live"


# ── cameras ──────────────────────────────────────────────────────────────

def test_set_camera_new_needs_name_and_vendor(monkeypatch, tmp_path):
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_camera", host="10.0.0.9")
    assert out["status"] == "error" and out["error"]["type"] == "validation"
    assert "name and vendor" in out["error"]["message"]
    assert state["saves"] == 0


@pytest.mark.parametrize("args,needle", [
    ({"host": "10.0.0.9", "name": "X", "vendor": "axis"}, "vendor"),
    ({"host": "bad host!", "name": "X", "vendor": "dahua"}, "host"),
    ({"host": "10.0.0.9", "name": "X", "vendor": "dahua", "stream": "sub9"}, "stream"),
    ({"host": "10.0.0.9", "name": "X", "vendor": "dahua", "main": "yes"}, "main"),
    ({"host": "10.0.0.9", "name": "X", "vendor": "dahua", "rooms": "Hall"}, "rooms"),
])
def test_set_camera_argument_validation(monkeypatch, tmp_path, args, needle):
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "set_camera", **args)
    assert out["status"] == "error" and out["error"]["type"] == "validation"
    assert needle in out["error"]["message"]
    assert state["saves"] == 0


def test_set_camera_adds_and_a_second_add_composes(monkeypatch, tmp_path):
    p, state, _ = make_plugin(monkeypatch, tmp_path)
    a = call(p, "set_camera", host="10.0.0.5", name="Front", vendor="dahua", main=True)
    assert a["status"] == "ok" and a["result"]["action"] == "added"
    assert a["result"]["cameraRestartNeeded"] is True
    b = call(p, "set_camera", host="10.0.0.6", name="Drive", vendor="hikvision",
             stream="main", rooms=["Garage", "Hall"])
    assert b["status"] == "ok"
    hosts = [c["host"] for c in state["store"]["cameras"]]
    assert hosts == ["10.0.0.5", "10.0.0.6"], "the second add must not revert the first"
    assert state["store"]["mainCameras"] == ["10.0.0.5"]
    drive = state["store"]["cameras"][1]
    assert drive["stream"] == "main" and drive["room"] == ["Garage", "Hall"]
    assert b["result"]["camera"]["rooms"] == ["Garage", "Hall"]


def test_set_camera_updates_fields_and_main_flag_on_an_existing_host(monkeypatch, tmp_path):
    store = {"cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua", "room": "Hall"}],
             "mainCameras": ["10.0.0.5"]}
    p, state, _ = make_plugin(monkeypatch, tmp_path, store=store,
                              running=store["cameras"])
    out = call(p, "set_camera", host="10.0.0.5", name="Front Door", rooms=[], main=False)
    assert out["status"] == "ok" and out["result"]["action"] == "updated"
    cam = state["store"]["cameras"][0]
    assert cam["name"] == "Front Door" and cam["vendor"] == "dahua"
    assert "room" not in cam, "an empty rooms list takes the camera off every room page"
    assert state["store"]["mainCameras"] == []
    assert out["result"]["cameraRestartNeeded"] is True


def test_set_camera_with_nothing_changed_needs_no_restart(monkeypatch, tmp_path):
    cams = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}]
    p, _, _ = make_plugin(monkeypatch, tmp_path, store={"cameras": cams}, running=cams)
    out = call(p, "set_camera", host="10.0.0.5", name="Front")
    assert out["status"] == "ok" and out["result"]["cameraRestartNeeded"] is False


def test_remove_camera(monkeypatch, tmp_path):
    store = {"cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"},
                         {"host": "10.0.0.6", "name": "Drive", "vendor": "dahua"}],
             "mainCameras": ["10.0.0.5", "10.0.0.6"], "swapOutHost": "10.0.0.6"}
    p, state, _ = make_plugin(monkeypatch, tmp_path, store=store, running=store["cameras"])
    missing = call(p, "remove_camera", host="10.0.0.7")
    assert missing["status"] == "error" and missing["error"]["type"] == "not_found"
    assert missing["error"]["details"]["knownHosts"] == ["10.0.0.5", "10.0.0.6"]
    out = call(p, "remove_camera", host="10.0.0.6")
    assert out["status"] == "ok"
    assert [c["host"] for c in state["store"]["cameras"]] == ["10.0.0.5"]
    assert state["store"]["mainCameras"] == ["10.0.0.5"]
    assert state["store"]["swapOutHost"] == ""
    assert out["result"]["cameraRestartNeeded"] is True


def test_list_cameras_carries_no_credentials_and_flags_a_pending_restart(monkeypatch, tmp_path):
    saved = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua", "room": "Hall"},
             {"host": "10.0.0.6", "name": "Drive", "vendor": "hikvision"}]
    p, _, _ = make_plugin(monkeypatch, tmp_path,
                          store={"cameras": saved, "mainCameras": ["10.0.0.5"]},
                          running=saved[:1])
    r = call(p, "list_cameras")["result"]
    assert [c["host"] for c in r["cameras"]] == ["10.0.0.5", "10.0.0.6"]
    assert r["cameras"][0]["rooms"] == ["Hall"] and r["cameras"][1]["rooms"] == []
    assert r["cameras"][0]["stream"] == "sub2"
    assert r["mainCameras"] == ["10.0.0.5"]
    assert r["credentialsSet"] is True
    assert r["restartPending"] is True, "saved differs from running, so a restart is pending"
    blob = json.dumps(r)
    assert "u" not in r and "p" not in r and "cam_pass" not in blob


# ── read_log ─────────────────────────────────────────────────────────────

def test_read_log_tail_filter_and_bounds(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    log_dir = tmp_path / "Indigo 2025.2" / "Logs" / PLUGIN_ID
    log_dir.mkdir(parents=True)
    log = log_dir / "plugin.log"
    log.write_text("\n".join(f"line {i} {'WARNING' if i % 10 == 0 else 'INFO'}"
                             for i in range(1, 101)) + "\n", encoding="utf-8")
    r = call(p, "read_log", lines=3)["result"]
    assert r["lines"] == ["line 98 INFO", "line 99 INFO", "line 100 WARNING"]
    assert r["truncated"] is True and r["count"] == 3
    r = call(p, "read_log", contains="warning", lines=2)["result"]
    assert r["lines"] == ["line 90 WARNING", "line 100 WARNING"] and r["truncated"] is True
    for bad in ({"lines": 0}, {"lines": 401}, {"lines": "5"}, {"lines": True}):
        out = call(p, "read_log", **bad)
        assert out["status"] == "error" and out["error"]["type"] == "validation", bad


def test_read_log_missing_file_is_not_found(monkeypatch, tmp_path):
    p, _, _ = make_plugin(monkeypatch, tmp_path)
    out = call(p, "read_log")
    assert out["status"] == "error" and out["error"]["type"] == "not_found"


# ── the _effective_config fix ────────────────────────────────────────────

def test_effective_config_reports_saved_cameras_once_the_store_is_in_force(monkeypatch, tmp_path):
    """Before v3.12.0 this returned module CAMERAS — the list still streaming
    from BEFORE the last save — so a Settings page reopened after adding a
    camera showed the old list and its next Save deleted the new one."""
    running = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}]
    saved = running + [{"host": "10.0.0.6", "name": "Drive", "vendor": "dahua"}]
    p, _, _ = make_plugin(monkeypatch, tmp_path,
                          store={"cameras": saved, "swapOutHost": "10.0.0.6"}, running=running)
    cfg = p._effective_config()
    assert [c["host"] for c in cfg["cameras"]] == ["10.0.0.5", "10.0.0.6"]
    assert cfg["swapOutHost"] == "10.0.0.6"


def test_effective_config_uses_the_running_list_in_legacy_mode(monkeypatch, tmp_path):
    running = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}]
    p, _, _ = make_plugin(monkeypatch, tmp_path, store=None, running=running)
    assert [c["host"] for c in p._effective_config()["cameras"]] == ["10.0.0.5"]
