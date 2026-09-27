#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_demo_api_is_sanitised.py
# Description: The canned endpoint answers demo mode reads (demo-data/api/,
#              written by tools/make_demo_api.py) ship in the public bundle, so
#              they must hold to the privacy rules they were cut down by. These
#              checks lived in test_demo_site.py until the online demo was
#              removed (27-09-2026); the rules still apply to the bundle copy.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
API = PAGES / "demo-data/api"


def _load(name):
    return json.loads((API / f"{name}.json").read_text(encoding="utf-8"))


def test_the_timeline_carries_no_record_of_who_was_home():
    lanes = {ln["key"] for ln in _load("timelineDay")["lanes"]}
    assert lanes and not lanes & {"presence", "doors"}, lanes
    assert not (API / "presenceData.json").exists(), "the Nights view must not be captured"


def test_no_money_account_or_outage_history_is_published():
    status = (API / "sigenApi-status.json").read_text(encoding="utf-8")
    assert not re.search(r'"balance_gbp":\s*[0-9]', status)
    assert _load("sigenApi-status")["power_cut"]["events"] == []
    for f in API.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:10|192\.168)\.\d+\.\d+\b", text), f.name
        assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text), f.name
        assert not re.search(r'"(?:mpan|mprn|account[a-z_]*|serial[a-z_]*)":\s*"', text, re.I), f.name


def test_the_diary_is_invented_and_names_no_door_codes():
    feed = _load("activityFeed")
    assert feed["automation"]["codes"] == []
    assert _load("logErrors")["feed"]["rows"], "an empty log would not show the page working"


def test_demo_mode_answers_before_the_liveness_gate():
    """Demo mode has no plugin behind it to be alive, so the gate would call
    every demo endpoint 'restarting'."""
    src = (PAGES / "dashboards-ui.js").read_text(encoding="utf-8")
    fn = src[src.index("async function message("):]
    assert fn.index("if (key === 'demo') return demoMessage(name, body);") < fn.index("DashGate")


def test_the_demo_stills_location_is_invented_not_captured():
    """The real cameraStills reply names this install's private stills folder
    (stills-<token>), which exists only so that nobody without the key can
    find the pictures. The demo answers with a placeholder instead."""
    reply = _load("cameraStills")
    assert reply["ok"] is True
    for key in ("imagePattern", "thumbPattern"):
        assert "stills-" not in reply[key], reply
