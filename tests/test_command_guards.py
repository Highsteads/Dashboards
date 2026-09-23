#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_command_guards.py
# Description: applyColour must refuse a command Indigo would swallow
#              (v2.95.2). Indigo raises for neither case: a device with
#              communication disabled logs 'Ignored' and does nothing; a
#              device whose owning plugin has stopped logs 'unable to execute
#              action' and does nothing. Both used to come back ok:true with
#              every step reported as done. Also the carbon advisor's solar
#              read: a disabled or errored inverter is UNKNOWN, and an absent
#              state is not zero.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

from types import SimpleNamespace
from unittest.mock import MagicMock
from conftest import bare_plugin, load_plugin_module


def _owner(installed=True, running=True):
    o = MagicMock()
    o.isInstalled.return_value = installed
    o.isRunning.return_value = running
    o.pluginDisplayName = "MagicHome"
    return o


def test_disabled_device_is_refused_409(monkeypatch):
    load_plugin_module(); p = bare_plugin()
    dev = SimpleNamespace(enabled=False, pluginId="x", name="Lamp")
    reason, status = p._device_command_blocked(dev)
    assert status == 409 and "disabled" in reason


def test_stopped_owner_is_refused_503(monkeypatch):
    plugin = load_plugin_module(); p = bare_plugin()
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: _owner(True, False))
    dev = SimpleNamespace(enabled=True, pluginId="com.clives.indigoplugin.magichome", name="Lamp")
    reason, status = p._device_command_blocked(dev)
    assert status == 503 and "MagicHome" in reason


def test_unknown_owner_id_fails_open(monkeypatch):
    plugin = load_plugin_module(); p = bare_plugin()
    monkeypatch.setattr(plugin.indigo.server, "getPlugin", lambda pid: _owner(False, False))
    dev = SimpleNamespace(enabled=True, pluginId="typo", name="Lamp")
    assert p._device_command_blocked(dev) == (None, None)


def _inv(enabled=True, error="", **states):
    return SimpleNamespace(enabled=enabled, errorState=error, states=states)


def _solar(monkeypatch, inv):
    plugin = load_plugin_module(); p = bare_plugin()
    monkeypatch.setattr(plugin.indigo.devices, "iter", lambda pid: [inv])
    return p._carbon_solar()


def test_carbon_solar_reads_a_live_inverter(monkeypatch):
    out = _solar(monkeypatch, _inv(pvPowerWatts="3200", homePowerWatts="800",
                                   gridPowerWatts="-2400", batterySoc="87.3", batteryPowerWatts="0"))
    assert out["pv_w"] == 3200 and out["export_w"] == 2400 and out["soc"] == 87.3


def test_carbon_solar_disabled_or_errored_inverter_is_unknown(monkeypatch):
    # batterySoc is part of the identity: _sigen_inverter (v3.27.0) looks for a
    # device carrying both it and pvPowerWatts, as the real inverter does.
    live = dict(pvPowerWatts="3200", homePowerWatts="800", gridPowerWatts="-2400", batterySoc="50")
    assert _solar(monkeypatch, _inv(enabled=False, **live)) == {}
    assert _solar(monkeypatch, _inv(error="Modbus timeout", **live)) == {}


def test_carbon_solar_absent_state_is_not_zero(monkeypatch):
    assert _solar(monkeypatch, _inv(pvPowerWatts="3200", homePowerWatts="", batterySoc="")) == {}
    out = _solar(monkeypatch, _inv(pvPowerWatts="3200", homePowerWatts="800", gridPowerWatts="-2400",
                                   batterySoc=""))
    assert out["soc"] is None and out["battery_w"] is None


def test_sigen_inverter_needs_both_states(monkeypatch):
    """v3.27.0: one lookup for every caller — a SigenEnergyManager device that
    carries BOTH batterySoc and pvPowerWatts. Four copies used to disagree."""
    plugin = load_plugin_module(); p = bare_plugin()
    half = _inv(pvPowerWatts="1")
    whole = _inv(pvPowerWatts="1", batterySoc="50")
    monkeypatch.setattr(plugin.indigo.devices, "iter", lambda pid: [half, whole])
    assert p._sigen_inverter() is whole
    monkeypatch.setattr(plugin.indigo.devices, "iter", lambda pid: [half])
    assert p._sigen_inverter() is None
    def boom(pid):
        raise RuntimeError("server busy")
    monkeypatch.setattr(plugin.indigo.devices, "iter", boom)
    assert p._sigen_inverter() is None
