#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_csrf_json_only.py
# Description: The endpoints that change something insist on
#              Content-Type: application/json (3.46.0). _request_body took any
#              body with any content type, so a plain HTML form on another
#              website could POST to saveDashboardsConfig (or the heating,
#              colour, laundry, PIN and setup-link handlers) from a browser
#              logged in to the Indigo web server. A form can only send
#              form-urlencoded, multipart or text/plain; application/json
#              needs a script, and a script on another site gets no CORS
#              preflight from IWS. Every page call site already sends JSON,
#              and this file pins that too, so the guard can never lock the
#              pages out.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.2 (3.48.0: watchCameras)
#              1.1 (3.47.0: every plugin module is scanned; the alert save and test)

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module, plugin_source_files

plugin = load_plugin_module()
ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
SERVER = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin"


class Action:
    def __init__(self, body, headers=None, with_headers=True):
        self.props = {"request_body": body}
        if with_headers:
            self.props["headers"] = headers or {}


def _save_plugin():
    p = bare_plugin()
    p._save_config_store = MagicMock(side_effect=lambda clean: {"config": clean})
    p._write_config_js = MagicMock()
    p._build_rooms_json = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_store = {}
    p.cameras = []
    p.pluginPrefs = {}
    return p


BODY = json.dumps({"config": {"siteName": "Pwned"}})


@pytest.mark.parametrize("ctype", [
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x",
    "text/plain",
    "text/plain; charset=utf-8",
    "",
])
def test_a_form_shaped_request_cannot_save_settings(ctype):
    p = _save_plugin()
    hdrs = {"Content-Type": ctype} if ctype else {"Host": "192.168.1.10:8176"}
    reply = p.handleSaveDashboardsConfig(Action(BODY, hdrs))
    assert reply["status"] == 415, ctype
    assert "application/json" in json.loads(reply["content"])["error"]
    assert not p._save_config_store.called, "nothing may be written"


@pytest.mark.parametrize("ctype", ["application/json", "application/json; charset=utf-8",
                                   "Application/JSON"])
def test_json_is_accepted_in_any_spelling(ctype):
    p = _save_plugin()
    reply = p.handleSaveDashboardsConfig(Action(BODY, {"content-type": ctype}))
    assert reply["status"] == 200, reply
    assert p._save_config_store.called


def test_no_headers_at_all_is_allowed_and_logged_once(monkeypatch):
    said = []
    monkeypatch.setattr(plugin, "log", lambda m, level="INFO": said.append((level, m)))
    p = _save_plugin()
    for _ in range(2):
        assert p.handleSaveDashboardsConfig(Action(BODY, with_headers=False))["status"] == 200
    assert len([m for lvl, m in said if lvl == "WARNING" and "no request headers" in m]) == 1


def test_the_other_state_changing_handlers_refuse_a_form_too():
    p = bare_plugin()
    p.pluginPrefs = {}
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    for name in ("handleEvoHomeAction", "handleLaundryDeadline", "handleVerifyPin",
                 "handleApplyColour", "handleBurnSetupToken", "handleSaveAlertRules",
                 "handleSendTestAlert", "handleWatchCameras"):
        reply = getattr(p, name)(Action("{}", form))
        assert reply["status"] == 415, name


def test_exactly_the_state_changing_handlers_are_guarded():
    # Every module the Plugin class is built from (3.47.0): the scan named five
    # files, so a handler in a new mixin would have been invisible to it.
    src = "\n".join(open(f, encoding="utf-8").read() for f in plugin_source_files()) + "\n    def "
    guarded = set()
    for m in re.finditer(r"def (handle\w+)\(self, action[^)]*\):(.*?)(?=\n    def )", src, re.S):
        if "_request_body(action, changes_state=True)" in m.group(2):
            guarded.add(m.group(1))
    assert guarded == {"handleSaveDashboardsConfig", "handleEvoHomeAction", "handleLaundryDeadline",
                       "handleVerifyPin", "handleApplyColour", "handleBurnSetupToken",
                       "handleSaveAlertRules", "handleSendTestAlert", "handleWatchCameras"}, guarded


def test_every_page_post_to_the_plugin_says_json():
    """The guard must never lock the pages out: each place a page POSTs to
    /message/ sends Content-Type: application/json."""
    hits = 0
    for f in sorted(PAGES.glob("*.*")):
        if f.suffix not in (".html", ".js") or f.name == "chart.umd.min.js":
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"fetch\(([^;]{0,200}?/message/[^;]*?)\)\s*;", text, re.S):
            call = m.group(1)
            if "POST" in call:
                hits += 1
                assert "application/json" in call, f"{f.name}: {call[:120]}"
        for m in re.finditer(r"this\._fetch\(\s*(?:_DELTA_PATH|\"/message/[^\"]+\")\s*,\s*\{(.*?)\}\s*\)", text, re.S):
            hits += 1
            assert '"Content-Type": "application/json"' in m.group(1), f"{f.name}: {m.group(1)[:120]}"
    ui = (PAGES / "dashboards-ui.js").read_text(encoding="utf-8")
    assert "'Content-Type': 'application/json'" in ui.split("async function message(", 1)[1].split("\n  }\n", 1)[0]
    assert hits >= 5, f"the scan found only {hits} call sites"
