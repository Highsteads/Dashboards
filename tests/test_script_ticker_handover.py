#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_ticker_handover.py
# Description: v3.31.0 — while the Script Ticker plugin is RUNNING, Dashboards
#              leaves the companion scripts to it; the moment it is not, it
#              runs them itself. A laundry replan goes through the ticker's
#              runJob action so the scheduler never runs in two hosts at once.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

from unittest.mock import MagicMock

from conftest import bare_plugin, load_plugin_module


def _plugin_info(running=True, installed=True):
    info = MagicMock()
    info.isInstalled.return_value = installed
    info.isRunning.return_value = running
    return info


def test_ticker_running_asks_isrunning_not_isenabled(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    info = _plugin_info(running=False)
    info.isEnabled.return_value = True          # enabled but crashed runs nothing
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: info)
    assert p._ticker_running() is False
    info.isRunning.return_value = True
    assert p._ticker_running() is True


def test_ticker_absent_or_erroring_reads_as_not_running(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: None)
    assert p._ticker_running() is False

    def boom(pid):
        raise RuntimeError("server busy")
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", boom)
    assert p._ticker_running() is False
    info = _plugin_info(running=True, installed=False)
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: info)
    assert p._ticker_running() is False


def test_note_ticker_logs_only_changes(monkeypatch):
    plugin = load_plugin_module()
    lines = []
    monkeypatch.setattr(plugin, "log", lambda msg, **k: lines.append(msg))
    p = bare_plugin()
    state = {"running": False}
    p._ticker_running = lambda: state["running"]
    p._note_ticker()
    p._note_ticker()
    assert lines == []                          # never had it: nothing to say
    state["running"] = True
    p._note_ticker()
    p._note_ticker()
    assert len(lines) == 1 and "is leaving them to it" in lines[0]
    state["running"] = False
    p._note_ticker()
    assert len(lines) == 2 and "running the companion scripts again" in lines[1]


def _drive_loop(monkeypatch, running_by_tick, ticks=3):
    """Run the loop for `ticks` passes; running_by_tick(n) says whether the
    ticker is running on check n. Returns how often each script ran."""
    plugin = load_plugin_module()
    p = bare_plugin()
    p.cam_user = p.cam_pass = ""
    monkeypatch.setattr(plugin, "CAMERAS", [])
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    ran = {"presence": 0, "logwatch": 0, "sweep": 0, "drive": 0, "rooms": 0}
    bump = lambda k: (lambda: ran.__setitem__(k, ran[k] + 1))   # noqa: E731
    p._build_rooms_json = bump("rooms")
    p._build_scenes_json = lambda: None
    p._cleanup_setup_links = lambda: None
    p._prune_change_ledger = lambda: None
    p._refresh_feature_flags = lambda: None
    p._run_presence_watch = bump("presence")
    p._run_log_error_watch = bump("logwatch")
    p._run_fp300_config_watch = lambda: None
    p._run_appliance_scheduler = lambda: None
    p._run_reflector_bandwidth_watch = lambda: None
    p._run_night_lights_sweep = bump("sweep")
    p._run_drive_lights_sun = bump("drive")
    checks = {"n": 0}

    def running():
        checks["n"] += 1
        return running_by_tick(checks["n"])
    p._ticker_running = running
    n = {"ticks": 0}

    def fake_sleep(_s):
        n["ticks"] += 1
        if n["ticks"] >= ticks:
            raise p.StopThread()
    p.sleep = fake_sleep
    p.runConcurrentThread()
    return ran


def test_while_the_ticker_runs_dashboards_runs_no_script(monkeypatch):
    ran = _drive_loop(monkeypatch, lambda n: True)
    assert ran["rooms"] >= 1                    # its own work carries on
    assert ran["presence"] == ran["logwatch"] == ran["sweep"] == ran["drive"] == 0


def test_without_the_ticker_dashboards_runs_them(monkeypatch):
    ran = _drive_loop(monkeypatch, lambda n: False)
    assert ran["presence"] >= 1 and ran["logwatch"] == 1 and ran["sweep"] == 1


def test_when_the_ticker_stops_dashboards_takes_the_scripts_back(monkeypatch, ):
    # Running at the seed check, gone at the first loop check.
    ran = _drive_loop(monkeypatch, lambda n: n == 1)
    assert ran["logwatch"] == 1 and ran["sweep"] == 1 and ran["drive"] == 1


def test_laundry_replan_goes_through_the_ticker(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    info = _plugin_info(running=True)
    info.executeAction.return_value = {"ok": True, "job": "laundry", "error": ""}
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: info)
    p._run_appliance_scheduler = MagicMock()
    p._read_laundry_plan = lambda: {"plans": ["new"]}
    assert p._replan_laundry() == {"plans": ["new"]}
    info.executeAction.assert_called_once_with(
        "runJob", props={"job": "laundry"}, waitUntilDone=True)
    p._run_appliance_scheduler.assert_not_called()


class _IndigoDictLike:
    """indigo.Dict: a mapping with keys()/get()/[] that is NOT a dict."""
    def __init__(self, **kw):
        self._d = kw

    def keys(self):
        return self._d.keys()

    def __getitem__(self, k):
        return self._d[k]


def test_a_failed_ticker_reply_is_read_although_it_is_not_a_dict(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    info = _plugin_info(running=True)
    info.executeAction.return_value = _IndigoDictLike(ok=False, job="laundry", error="boom")
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: info)
    p._run_appliance_scheduler = MagicMock()
    p._read_laundry_plan = lambda: {"plans": []}
    p._replan_laundry()
    msgs = [str(c.args[0]) for c in p.logger.debug.call_args_list]
    assert any("could not replan: boom" in m for m in msgs), msgs
    p._run_appliance_scheduler.assert_not_called()


def test_laundry_replan_runs_here_when_the_ticker_cannot_take_it(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    info = _plugin_info(running=True)
    info.executeAction.side_effect = RuntimeError("plugin went away")
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: info)
    p._run_appliance_scheduler = MagicMock()
    p._read_laundry_plan = lambda: {"plans": []}
    p._replan_laundry()
    p._run_appliance_scheduler.assert_called_once()


def test_laundry_replan_without_the_ticker_runs_here(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: None)
    p._run_appliance_scheduler = MagicMock()
    p._read_laundry_plan = lambda: None
    p._replan_laundry()
    p._run_appliance_scheduler.assert_called_once()


def test_ticker_id_matches_the_ticker_bundle():
    # The ticker's own Info.plist is the owner; this is the one place the id
    # is copied, so pin it to the string the ticker ships.
    plugin = load_plugin_module()
    assert plugin.Plugin._TICKER_PLUGIN_ID == "com.clives.indigoplugin.scriptticker"
