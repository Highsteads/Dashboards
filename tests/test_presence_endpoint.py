#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_presence_endpoint.py
# Description: Contract tests for the v2.71.0 presence-data privacy fix — the
#              Bearer-authed presenceData endpoint that replaced the anonymous
#              /public/dashboards/presence.json (14 nights of bedroom
#              occupancy and sleep timing, reflector-reachable). Pins: the
#              route is REGISTERED in Actions.xml (an unregistered /message
#              route HANGS, it does not 404), the handler's three outcomes,
#              the startup legacy-file sweep, and the repo script's PK-range
#              discipline (no ts-filtered scans against the unindexed DB).
# Author:      CliveS & Claude Fable 5
# Date:        31-07-2026
# Version:     1.0

import json
import os

from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()

SP = os.path.join(os.path.dirname(__file__), "..",
                  "Dashboards.indigoPlugin", "Contents", "Server Plugin")
SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _handler_plugin(tmp_path):
    p = bare_plugin()
    install = tmp_path / "Indigo 2025.2"
    install.mkdir()
    (tmp_path / "Python Scripts").mkdir()
    plugin.indigo.server.getInstallFolderPath.return_value = str(install)
    return p, tmp_path / "Python Scripts" / "presence_data.json"


def _content(reply):
    return json.loads(reply["content"])


def test_serves_the_data_file(tmp_path):
    p, data_path = _handler_plugin(tmp_path)
    data_path.write_text(json.dumps({"dates": ["2026-07-30"], "rooms": {}}),
                         encoding="utf-8")
    out = _content(p.handlePresenceData(None))
    assert out["ok"] is True
    assert out["dates"] == ["2026-07-30"]


def test_missing_file_is_a_clean_not_built_yet(tmp_path):
    p, _ = _handler_plugin(tmp_path)
    out = _content(p.handlePresenceData(None))
    assert out["ok"] is False
    assert "not built yet" in out["error"]


def test_corrupt_file_is_a_clean_unavailable(tmp_path):
    p, data_path = _handler_plugin(tmp_path)
    data_path.write_text("{not json", encoding="utf-8")
    out = _content(p.handlePresenceData(None))
    assert out["ok"] is False
    assert out["error"] == "presence data unavailable"


def test_route_is_registered_in_actions_xml():
    # An unregistered /message route does not 404 — it HANGS the request.
    xml = open(os.path.join(SP, "Actions.xml"), encoding="utf-8").read()
    assert '<Action id="presenceData" uiPath="hidden">' in xml
    assert "<CallbackMethod>handlePresenceData</CallbackMethod>" in xml


def test_startup_sweeps_the_legacy_public_copy():
    src = open(os.path.join(SP, "plugin.py"), encoding="utf-8").read()
    i = src.find("def startup(self):")
    j = src.find("def stopConcurrentThread", i)
    body = src[i:j]
    assert '"presence.json"' in body and "os.remove" in body, \
        "startup must remove the pre-v2.71.0 anonymous /public presence.json"


def test_shipped_script_never_ts_filters_the_history_db():
    src = open(os.path.join(SCRIPTS, "Presence_Watch.py"), encoding="utf-8").read()
    assert "datetime(ts,'localtime')" not in src, \
        "a ts-filtered query full-scans the unindexed 2 GB DB under a read lock"
    assert "_rowid_for_ts" in src, "PK-range discipline must be present"


def test_shipped_script_output_avoids_public():
    src = open(os.path.join(SCRIPTS, "Presence_Watch.py"), encoding="utf-8").read()
    # The write path must be the Python Scripts folder; the ONLY mention of the
    # public path is the legacy sweep that deletes the old copy.
    assert 'os.path.join(os.path.dirname(base), "Python Scripts")' in src
    assert src.count('"public"') == 1 and "LEGACY_PUBLIC_RELPATH" in src


def test_repo_and_installed_script_copies_match():
    live = "/Library/Application Support/Perceptive Automation/Python Scripts/Presence_Watch.py"
    if not os.path.isfile(live):
        return   # other machines: repo copy is the only one
    a = open(os.path.join(SCRIPTS, "Presence_Watch.py"), encoding="utf-8").read()
    b = open(live, encoding="utf-8").read()
    assert a == b, "repo scripts/ copy has drifted from the live Python Scripts copy"
