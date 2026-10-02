#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_review_2026_10_02.py
# Description: Three faults from the independent review of 3.58.1, each one a
#              transition the earlier tests stubbed past:
#              - shutdown() lost its server connection before sweeping the
#                setup links (live: "server connection not open" at every
#                recent shutdown), so the files holding the API key stayed;
#              - a failed LOCAL laundry replan returned the old plan as the
#                answer to the new deadline;
#              - a disabled meter's frozen watts stayed "live" and counted.
# Author:      CliveS & Claude Opus 5.5
# Date:        02-10-2026
# Version:     1.0

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()

_TEARDOWN = ("_freeze_stamp", "_stop_stamp_thread", "_stop_go2rtc", "_stop_snapshot_pool",
             "_stop_proxy", "_stop_weather_thread", "_stop_offpath_workers", "_activity")


# -- shutdown with the server connection already closed ----------------------

def test_setup_links_go_at_shutdown_even_when_the_server_connection_has_closed(
        tmp_path, monkeypatch):
    monkeypatch.setattr(plugin, "STAMP_QUIESCE_SECONDS", 0)
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    monkeypatch.setattr(plugin.indigo.server, "getInstallFolderPath",
                        lambda: str(tmp_path), raising=False)
    p = bare_plugin()
    for name in _TEARDOWN:
        setattr(p, name, MagicMock())
    p.pluginDisplayName = "Dashboards"
    pub = p._public_dashboards_dir()            # startup resolves it, IPC up
    import os
    os.makedirs(pub)
    secret = os.path.join(pub, "setup-AbCdEfGhIjKlMnOpQrStUv.json")
    with open(secret, "w", encoding="utf-8") as fh:
        fh.write('{"apiKey": "k"}')

    def gone():
        raise RuntimeError("ServerCommunicationError -- server connection not open")
    monkeypatch.setattr(plugin.indigo.server, "getInstallFolderPath", gone, raising=False)
    p.shutdown()
    assert not os.path.exists(secret)


# -- a failed local laundry replan --------------------------------------------

@pytest.fixture
def laundry(tmp_path):
    p = bare_plugin()
    p._ticker_running = lambda: False
    p._sigen_available = lambda: True
    p._scripts_dir = lambda: str(tmp_path)
    (tmp_path / "appliance_plan.json").write_text('{"generated": "OLD"}', encoding="utf-8")
    return p, tmp_path


def test_a_failed_local_replan_raises_rather_than_returning_the_old_plan(laundry):
    p, d = laundry
    (d / "Appliance_Scheduler.py").write_text("raise ValueError('no forecast')\n",
                                              encoding="utf-8")
    with pytest.raises(RuntimeError, match="no forecast"):
        p._replan_laundry()


def test_a_missing_scheduler_also_fails_the_replan(laundry):
    p, _d = laundry
    with pytest.raises(RuntimeError, match="Could not replan"):
        p._replan_laundry()


def test_a_clean_local_replan_returns_the_new_plan(laundry):
    p, d = laundry
    (d / "Appliance_Scheduler.py").write_text(
        "import json, os\n"
        f"open(os.path.join({str(d)!r}, 'appliance_plan.json'), 'w').write("
        "json.dumps({'generated': 'NEW'}))\n", encoding="utf-8")
    assert p._replan_laundry() == {"generated": "NEW"}


def test_no_sigen_is_still_not_a_failure(laundry):
    p, _d = laundry
    p._sigen_available = lambda: False
    assert p._replan_laundry() == {"generated": "OLD"}


# -- a disabled meter ---------------------------------------------------------

def test_a_disabled_meter_is_dead_whatever_kind_it_is():
    P = bare_plugin()
    for continuous in (True, False):
        state, why = P._mains_liveness(5, owner_running=True, continuous=continuous,
                                       enabled=False)
        assert state == "dead" and "disabled" in why


def test_a_disabled_meter_is_not_counted_in_the_metered_total(monkeypatch):
    P = bare_plugin()
    P._mains_owner_running = lambda pid, cache: True
    dev = SimpleNamespace(id=7, name="Old Plug", pluginId="x", deviceTypeId="relay",
                          enabled=False, errorState="",
                          lastSuccessfulComm=datetime.now() - timedelta(days=30),
                          states={"curEnergyLevel": 125.0, "onOffState": True})
    monkeypatch.setattr(plugin.indigo, "devices", [dev], raising=False)
    rows, metered = P._mains_live()
    assert metered == 0.0
    assert rows[0]["state"] == "dead" and rows[0]["watts"] == 125.0   # still shown
