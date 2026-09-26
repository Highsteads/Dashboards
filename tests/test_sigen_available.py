#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_sigen_available.py
# Description: The server half of "the Sigenergy pages hide themselves when
#              the plugin is absent" (v3.13.0). Pins the ONE question
#              (_sigen_available: installed AND enabled, never merely running,
#              never a raised exception), the flag reaching config.js beside
#              heatingControls from one builder, the tick rewriting config.js
#              only when a flag flips, the sigenApi proxy answering 503 at once
#              without dialling out, the laundry endpoint and scheduler standing
#              down, the setup check reporting an optional SKIP, and the MCP
#              status tool carrying the flags.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import json
import re
import sys
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module
from test_mcp_tools import make_plugin as make_tool_plugin

SEM = "com.clives.indigoplugin.sigenergy-energy-manager"
EVO = "com.clives.indigoplugin.evohomecontrol"


class FakeAction:
    def __init__(self, body=""):
        self.props = {"request_body": body}


def _pi(installed, enabled):
    p = MagicMock()
    p.isInstalled.return_value = installed
    p.isEnabled.return_value = enabled
    p.isRunning.return_value = enabled
    return p


def wire_plugins(sem=(True, True), evo=(True, True), raise_for=()):
    """Route indigo.server.getPlugin by id: (installed, enabled) per plugin,
    everything else absent, and an optional set of ids that raise."""
    def gp(pid):
        if pid in raise_for:
            raise RuntimeError("server away")
        if pid == SEM:
            return _pi(*sem)
        if pid == EVO:
            return _pi(*evo)
        return _pi(False, False)
    sys.modules["indigo"].server.getPlugin.side_effect = gp


@pytest.fixture(autouse=True)
def _reset_getplugin():
    load_plugin_module()
    yield
    sys.modules["indigo"].server.getPlugin.side_effect = None


def config_plugin(tmp_path):
    """A bare plugin with what _write_config_js reads (mirrors
    test_config_js_no_secrets), writing into tmp_path."""
    p = bare_plugin()
    p.api_url = "http://192.168.1.10:8176"
    p.api_key = "k"
    p.cam_user = p.cam_pass = ""
    p.control_pin = ""
    p.pin_required = []
    p.favourites = []
    p.custom_links = []
    p.guest_token = "g"
    p.main_cameras = []
    p.lan_ip = "192.168.1.10"
    p.pluginVersion = "0.0.0-test"
    p._load_config_store = lambda: {}
    p._public_dashboards_dir = lambda: str(tmp_path)
    return p


def _config(tmp_path):
    js = (tmp_path / "config.js").read_text(encoding="utf-8")
    m = re.search(r"window\.INDIGO_CONFIG\s*=\s*(\{.*?\});", js, re.S)
    assert m, js[:200]
    return json.loads(m.group(1))


# ── the one question ─────────────────────────────────────────────────────

@pytest.mark.parametrize("state,expected", [
    ((True, True), True),
    ((True, False), False),      # installed but disabled: nothing can answer
    ((False, False), False),
])
def test_sigen_available_needs_installed_and_enabled(state, expected):
    wire_plugins(sem=state)
    assert bare_plugin()._sigen_available() is expected


def test_sigen_available_is_false_not_an_exception_when_the_server_cannot_answer():
    wire_plugins(raise_for={SEM})
    assert bare_plugin()._sigen_available() is False


def test_feature_flags_come_from_one_builder():
    wire_plugins(sem=(True, True), evo=(True, False))
    p = bare_plugin()
    flags = p._feature_flags()
    assert {k: flags[k] for k in ("heatingControls", "sigenAvailable")} == {"heatingControls": False, "sigenAvailable": True}
    assert set(flags["scripts"]) == {"presence", "laundry"}


# ── config.js ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sem,expected", [((True, True), True), ((False, False), False)])
def test_config_js_publishes_the_flag(tmp_path, sem, expected):
    wire_plugins(sem=sem)
    p = config_plugin(tmp_path)
    p._write_config_js()
    cfg = _config(tmp_path)
    assert cfg["sigenAvailable"] is expected
    assert cfg["heatingControls"] is True
    assert {k: p._config_js_flags[k] for k in ("heatingControls", "sigenAvailable")} == {"heatingControls": True, "sigenAvailable": expected}


def test_tick_rewrites_config_js_only_when_a_flag_flips(tmp_path):
    wire_plugins(sem=(True, True))
    p = config_plugin(tmp_path)
    p._write_config_js()
    writes = []
    real = p._write_config_js
    p._write_config_js = lambda: (writes.append(1), real())[1]
    assert p._refresh_feature_flags() is False and writes == [], "unchanged: no rewrite"
    wire_plugins(sem=(False, False))                  # the plugin is removed
    assert p._refresh_feature_flags() is True and writes == [1]
    assert _config(tmp_path)["sigenAvailable"] is False
    assert any("SigenEnergyManager is now absent" in c.args[0] for c in p.logger.info.call_args_list)
    assert p._refresh_feature_flags() is False and writes == [1], "settled again"


def test_tick_does_nothing_before_startup_has_written_config_js():
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._write_config_js = MagicMock()
    assert p._refresh_feature_flags() is False
    p._write_config_js.assert_not_called()


def test_the_tick_loop_runs_the_flag_check(tmp_path):
    """Structural: the 30 s housekeeping block calls _refresh_feature_flags."""
    plugin = load_plugin_module()
    import inspect
    src = inspect.getsource(plugin.Plugin.runConcurrentThread)
    block = src[src.index('if t0 - last["link"] > 30.0:'):src.index('last["link"] = t0')]
    assert 'step("feature flags", self._refresh_feature_flags)' in block


# ── the proxy, the laundry endpoint, the scheduler ───────────────────────

def test_sigen_proxy_answers_503_at_once_and_never_dials_out(monkeypatch):
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._refuse_reflector = lambda a: None
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("must not open a connection without the plugin")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    reply = p.handleSigenApi(FakeAction('{"path": "status"}'))
    assert reply["status"] == 503
    assert json.loads(reply["content"]) == {"error": "SigenEnergyManager is not installed",
                                            "reason": "sem_absent"}
    assert not p.logger.warning.called, "an install without the plugin must not warn every poll"


def test_laundry_plan_says_why_when_the_plugin_is_absent():
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._read_laundry_plan = lambda: {"plans": []}
    body = json.loads(p.handleLaundryPlan(FakeAction())["content"])
    assert body["ok"] is False and body["reason"] == "sem_absent"
    assert "SigenEnergyManager" in body["error"]


def test_solar_string_hours_stand_down_without_the_plugin():
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    def boom(*a, **k):
        raise AssertionError("must not query the history without the plugin")
    p._offpath_get = boom
    p._solar_string_hours = boom
    reply = p.handleSolarStringHours(FakeAction('{"date": "2026-09-26"}'))
    assert reply.get("status", 200) == 200, "a 503 would read as 'still building' and be polled"
    body = json.loads(reply["content"])
    assert body == {"ok": False, "reason": "sem_absent", "error": "SigenEnergyManager is not installed"}


def test_solar_string_hours_are_built_when_the_plugin_is_present():
    wire_plugins(sem=(True, True))
    p = bare_plugin()
    p._offpath_get = lambda key, producer, ttl, wait=None: ("fresh", {"ok": True, "hours": {}})
    body = json.loads(p.handleSolarStringHours(FakeAction('{"date": "2026-09-26"}'))["content"])
    assert body["ok"] is True


def test_mains_has_no_reference_without_the_plugin():
    """3.48.4: an inverter device can outlive its plugin; without the plugin it
    is never the Mains reference, so the page has no frozen figure to explain."""
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._sigen_inverter = lambda: pytest.fail("must not look for an inverter without the plugin")
    assert p._mains_reference() is None


def test_mains_offsets_are_never_built_without_the_plugin():
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._mains_offsets_cached = lambda: pytest.fail("must not start the week-long offsets sweep")
    assert p._mains_offsets_if_sigen() is None


def test_mains_offsets_are_built_with_the_plugin():
    wire_plugins(sem=(True, True))
    p = bare_plugin()
    p._mains_offsets_cached = lambda: {"ok": True, "meters": {}}
    assert p._mains_offsets_if_sigen() == {"ok": True, "meters": {}}


def test_mains_endpoint_serves_the_meters_without_the_plugin():
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._refuse_reflector = lambda action: None
    p._mains_live = lambda: ([{"id": 1, "name": "Kettle", "watts": 2000.0}], 2000.0)
    p._mains_offsets_cached = lambda: pytest.fail("must not start the offsets sweep")
    body = json.loads(p.handleMainsMeters(FakeAction())["content"])
    assert body["ok"] is True and body["meters"][0]["name"] == "Kettle"
    assert body["reference"] is None and body["offsets"] is None


def test_carbon_advice_makes_no_lookup_without_the_plugin():
    """3.48.5: the advice is only shown on the Energy page, which is left out
    without SigenEnergyManager, so the Carbon Intensity API is never called."""
    wire_plugins(sem=(False, False))
    p = bare_plugin()
    p._refuse_reflector = lambda action: None
    p._carbon_intensity = lambda: pytest.fail("must not call the Carbon Intensity API")
    reply = p.handleCarbonAdvisor(FakeAction())
    assert reply.get("status", 200) == 200, "a 503 would read as 'still building' and be polled"
    assert json.loads(reply["content"]) == {"ok": False, "reason": "sem_absent",
                                            "error": "SigenEnergyManager is not installed"}


def test_carbon_advice_is_given_with_the_plugin():
    wire_plugins(sem=(True, True))
    p = bare_plugin()
    p._refuse_reflector = lambda action: None
    p._carbon_intensity = lambda: {"current": {"intensity": 120}}
    p._carbon_solar = lambda: {}
    p._carbon_tariff = lambda: {}
    p._carbon_advice = lambda c, s, t: {"action": "run_now"}
    body = json.loads(p.handleCarbonAdvisor(FakeAction())["content"])
    assert body["ok"] is True and body["carbon"]["current"]["intensity"] == 120


def test_laundry_plan_is_served_when_the_plugin_is_present():
    wire_plugins(sem=(True, True))
    p = bare_plugin()
    p._read_laundry_plan = lambda: {"plans": [{"appliance": "washing_machine"}]}
    body = json.loads(p.handleLaundryPlan(FakeAction())["content"])
    assert body["ok"] is True and body["plans"]


@pytest.mark.parametrize("sem,runs", [((True, True), True), ((False, False), False)])
def test_scheduler_tick_stands_down_without_the_plugin(sem, runs):
    wire_plugins(sem=sem)
    p = bare_plugin()
    p._tick_script = MagicMock()
    p._run_appliance_scheduler()
    assert p._tick_script.called is runs


# ── setup check + status tool ────────────────────────────────────────────

@pytest.mark.parametrize("sem,verdict", [((True, True), "PASS"), ((False, False), "SKIP")])
def test_setup_check_reports_the_plugin_as_optional(monkeypatch, tmp_path, sem, verdict):
    p, _, _ = make_tool_plugin(monkeypatch, tmp_path)
    wire_plugins(sem=sem)
    import mcp_tools
    out = json.loads(mcp_tools.dispatch(p, "run_setup_check", {}))["result"]
    row = next(c for c in out["checks"] if c["label"] == "SigenEnergyManager")
    assert row["verdict"] == verdict and row["optional"] is True
    assert "Energy and Cost pages" in row["detail"]


def test_status_tool_carries_the_feature_flags(monkeypatch, tmp_path):
    p, _, _ = make_tool_plugin(monkeypatch, tmp_path)
    wire_plugins(sem=(False, False), evo=(True, True))
    import mcp_tools
    out = json.loads(mcp_tools.dispatch(p, "get_status", {}))["result"]
    assert {k: out["features"][k] for k in ("heatingControls", "sigenAvailable")} == {"heatingControls": True, "sigenAvailable": False}
    assert set(out["features"]["scripts"]) == {"presence", "laundry"}


# ── companion scripts (v3.33.0) ──────────────────────────────────────────

def test_script_flags_follow_the_files(tmp_path):
    p = bare_plugin()
    p._scripts_dir = lambda: str(tmp_path)
    assert p._companion_scripts_installed() == {"presence": False, "laundry": False}
    (tmp_path / "Presence_Watch.py").write_text("# x", encoding="utf-8")
    assert p._companion_scripts_installed() == {"presence": True, "laundry": False}


def test_script_flags_never_hide_when_the_folder_cannot_be_found():
    p = bare_plugin()

    def boom():
        raise RuntimeError("no indigo")
    p._scripts_dir = boom
    assert p._companion_scripts_installed() == {"presence": True, "laundry": True}


def test_a_failed_config_js_write_is_retried_by_the_tick(tmp_path, monkeypatch):
    """Review 24-09-2026 [34]: the flags were recorded BEFORE the write, so a
    failed write read as published and the tick, seeing no change, never
    rewrote config.js until a flag flipped or the plugin restarted."""
    import publish_mixin
    monkeypatch.setattr(publish_mixin, "log", lambda *a, **k: None)
    wire_plugins(sem=(True, True))
    p = config_plugin(tmp_path)
    real = p._write_atomic
    def failing(path, data):
        raise OSError("disk full")
    p._write_atomic = failing
    p._write_config_js()
    assert not (tmp_path / "config.js").exists()
    p._write_atomic = real
    assert p._refresh_feature_flags() is True
    assert _config(tmp_path)["sigenAvailable"] is True
    assert p._refresh_feature_flags() is False, "settled once written"


def test_a_bad_favourite_or_link_cannot_stop_config_js(tmp_path):
    """Review 24-09-2026 [35]: a hand-edited entry that is not an object made
    dict() raise in the unguarded build, which startup() calls first."""
    wire_plugins(sem=(True, True))
    p = config_plugin(tmp_path)
    p.favourites = [{"type": "device", "id": 1, "label": "Lamp"}, 123, "abc"]
    p.custom_links = ["x", {"title": "Router", "url": "http://192.168.1.1"}]
    p._write_config_js()
    cfg = _config(tmp_path)
    assert cfg["favourites"] == [{"type": "device", "id": 1, "label": "Lamp"}]
    assert [l["title"] for l in cfg["customLinks"]] == ["Router"]


def test_the_store_load_keeps_only_object_entries(monkeypatch):
    import plugin as mod
    said = []
    monkeypatch.setattr(mod, "log", lambda m, level="INFO": said.append((level, m)))
    p = bare_plugin()
    assert p._stored_dicts({"favourites": [{"id": 1}, 5, "x"]}, "favourites") == [{"id": 1}]
    assert p._stored_dicts({"customLinks": {"title": "t"}}, "customLinks") == []
    assert p._stored_dicts({}, "favourites") == []
    assert [lvl for lvl, _ in said] == ["WARNING", "WARNING"]
    assert "2 entries in 'favourites'" in said[0][1]


def test_camera_config_no_longer_publishes_the_go2rtc_port(tmp_path):
    """Review 24-09-2026 [82]: go2rtcPort was left over from the MJPEG and
    live.html retirements. No page reads it, and config.js is anonymous."""
    wire_plugins(sem=(True, True))
    p = config_plugin(tmp_path)
    p._write_config_js()
    js = (tmp_path / "config.js").read_text(encoding="utf-8")
    m = re.search(r"window\.CAMERA_CONFIG\s*=\s*(\{.*?\});", js, re.S)
    assert m and "go2rtcPort" not in json.loads(m.group(1))
    import glob
    import os
    from conftest import SP
    pages = os.path.join(SP, "..", "Resources", "static", "pages")
    readers = [f for f in glob.glob(os.path.join(pages, "*.*"))
               if f.endswith((".js", ".html")) and "go2rtcPort" in open(f, encoding="utf-8").read()]
    assert readers == []


# ── the room page's catalog (lows batch [56]) ────────────────────────────
# The bundle ships no catalog.json, and room.html asked for one on every view,
# which 404s (and IWS logs it) on every install but the one an outside tool
# had put a file on. config.js now says whether it exists.

def test_config_js_says_whether_a_catalog_is_published(tmp_path):
    wire_plugins(sem=(True, True))
    p = config_plugin(tmp_path)
    p._write_config_js()
    assert _config(tmp_path)["catalog"] is False
    (tmp_path / "catalog.json").write_text("{}")
    assert p._refresh_feature_flags() is True, "a catalog appearing rewrites config.js"
    assert _config(tmp_path)["catalog"] is True


def test_room_page_asks_for_the_catalog_only_when_published():
    from pathlib import Path
    pages = Path(__file__).resolve().parent.parent / "Dashboards.indigoPlugin" / "Contents" / "Resources" / "static" / "pages"
    page = (pages / "room.html").read_text(encoding="utf-8")
    call = page.index('Capabilities.load("catalog.json")')
    guard = page.rfind("if (", 0, call)
    assert re.search(r"INDIGO_CONFIG \|\| \{\}\)\.catalog === true", page[guard:call]), \
        "the catalog fetch must sit behind config.js's catalog flag"
