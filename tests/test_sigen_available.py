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
    p.sigen_legacy_url = ""
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
    assert p._feature_flags() == {"heatingControls": False, "sigenAvailable": True}


# ── config.js ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sem,expected", [((True, True), True), ((False, False), False)])
def test_config_js_publishes_the_flag(tmp_path, sem, expected):
    wire_plugins(sem=sem)
    p = config_plugin(tmp_path)
    p._write_config_js()
    cfg = _config(tmp_path)
    assert cfg["sigenAvailable"] is expected
    assert cfg["heatingControls"] is True
    assert p._config_js_flags == {"heatingControls": True, "sigenAvailable": expected}


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
    assert "Energy, Cost and Laundry" in row["detail"]


def test_status_tool_carries_the_feature_flags(monkeypatch, tmp_path):
    p, _, _ = make_tool_plugin(monkeypatch, tmp_path)
    wire_plugins(sem=(False, False), evo=(True, True))
    import mcp_tools
    out = json.loads(mcp_tools.dispatch(p, "get_status", {}))["result"]
    assert out["features"] == {"heatingControls": True, "sigenAvailable": False}
