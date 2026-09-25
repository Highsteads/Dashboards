#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_alert_rules_engine.py
# Description: The alert rules are judged by the plugin now (3.47.0), in a
#              Python port of the page's dashboards-alerts.js. Every case in
#              tests/lib/alert_rule_cases.json runs here through the port and
#              in test_alerts_shared.mjs through the JavaScript, so the two
#              cannot disagree: deviceNow, judgeDevice, judgeVariable, ruleKey
#              and the 30 s per-rule cooldown. Also the save-time validation:
#              known kinds and conditions, whole ids, channels from the allowed
#              set, a plausible email, no repeats, and the 100-rule cap.
# Author:      CliveS & Claude
# Date:        25-09-2026
# Version:     1.0

import json
from pathlib import Path

import pytest

from conftest import load_plugin_module

load_plugin_module()                     # puts Server Plugin/ on sys.path
import alerts_mixin as am                # noqa: E402

CASES = json.loads((Path(__file__).parent / "lib" / "alert_rule_cases.json").read_text(encoding="utf-8"))


def _ids(section):
    return [c.get("why") or json.dumps(c.get("dev") or c.get("rule")) for c in CASES[section]]


@pytest.mark.parametrize("case", CASES["deviceNow"], ids=_ids("deviceNow"))
def test_device_now_matches_the_page(case):
    assert am.device_now(case["dev"]) == case["expect"]


@pytest.mark.parametrize("case", CASES["device"], ids=_ids("device"))
def test_judge_device_matches_the_page(case):
    was = am.device_now(case["was"]) if case["was"] is not None else None
    now = am.device_now(case["now"])
    assert am.judge_device(case["rule"], was, now) == case["expect"]


@pytest.mark.parametrize("case", CASES["variable"], ids=_ids("variable"))
def test_judge_variable_matches_the_page(case):
    assert am.judge_variable(case["rule"], case["was"], case["value"]) == case["expect"]


@pytest.mark.parametrize("case", CASES["ruleKey"], ids=_ids("ruleKey"))
def test_rule_key_matches_the_page(case):
    assert am.rule_key(case["rule"]) == case["expect"]


@pytest.mark.parametrize("case", CASES["cooldown"], ids=_ids("cooldown"))
def test_cooldown_matches_the_page(case):
    cd = am.Cooldown()
    got = [cd.claim(key, t / 1000.0) for key, t in case["events"]]
    assert got == case["expect"]


def test_the_shared_cases_are_not_vacuous():
    assert len(CASES["device"]) >= 15 and len(CASES["variable"]) >= 8
    assert any(c["expect"] is None for c in CASES["device"])
    assert any(c["expect"] for c in CASES["device"])


def test_the_cooldown_is_the_pages_thirty_seconds():
    assert am.ALERT_COOLDOWN_S == 30.0


def test_js_str_writes_values_as_javascript_does():
    assert am.js_str(True) == "true" and am.js_str(False) == "false"
    assert am.js_str(None) == "null" and am.js_str(12.0) == "12" and am.js_str(0.1) == "0.1"
    assert am.js_str(float("nan")) == "NaN" and am.js_str(float("-inf")) == "-Infinity"
    assert am.js_str("x") == "x" and am.js_str(7) == "7"


def test_device_now_reads_an_indigo_object_too():
    class Dev:
        onState = True
        displayStateValUi = "72%"
    assert am.device_now(Dev()) == {"on": True, "ui": "72%"}

    class Bare:           # no onState at all (a sensor with no on/off)
        displayStateValUi = "dry"
    assert am.device_now(Bare()) == {"on": False, "ui": "dry"}


# ── validation ────────────────────────────────────────────────────────────

DEFAULT = ["pushover", "browser"]


def _rule(**kw):
    r = {"kind": "device", "id": 101, "cond": "on", "name": "Lamp", "enabled": True,
         "channels": ["email"]}
    r.update(kw)
    return r


def test_a_good_rule_is_kept_and_cleaned():
    clean, errors = am.validate_rules([_rule(name="  Lamp  ", channels=["browser", "email"],
                                             email=" me@example.com ", extra="dropped")], DEFAULT)
    assert errors == []
    assert clean == [{"kind": "device", "id": 101, "cond": "on", "name": "Lamp", "enabled": True,
                      "channels": ["email", "browser"], "email": "me@example.com"}]


def test_a_rule_without_channels_gets_the_default():
    """How a browser's old rule, which never had channels, is given some."""
    clean, errors = am.validate_rules([{"kind": "variable", "id": 7, "cond": "change",
                                        "name": "Mode", "enabled": False}], DEFAULT)
    assert errors == [] and clean[0]["channels"] == DEFAULT and clean[0]["enabled"] is False


@pytest.mark.parametrize("bad, needle", [
    (_rule(kind="scene"), "kind must be device or variable"),
    (_rule(id="101"), "id must be a whole"),
    (_rule(id=1.5), "id must be a whole"),
    (_rule(id=True), "id must be a whole"),
    (_rule(id=-4), "id must be a whole"),
    (_rule(cond="dim"), "condition must be one of on, off, change"),
    (_rule(kind="variable", cond="on"), "condition must be one of change"),
    (_rule(name=""), "name must be some text"),
    (_rule(name=None), "name must be some text"),
    (_rule(enabled="yes"), "enabled must be true or false"),
    (_rule(channels=["sms"]), "channels must be a list drawn from"),
    (_rule(channels="email"), "channels must be a list drawn from"),
    (_rule(channels=[]), "at least one way"),
    (_rule(email="not an address"), "does not look like an email"),
    (_rule(email="a@example.com, evil@example.com"), "does not look like an email"),
    (_rule(email=42), "does not look like an email"),
    ("junk", "must be an object"),
])
def test_junk_is_refused_with_a_clear_error(bad, needle):
    clean, errors = am.validate_rules([bad], DEFAULT)
    assert errors and needle in errors[0], errors


def test_a_repeat_is_refused():
    clean, errors = am.validate_rules([_rule(), _rule(name="Again")], DEFAULT)
    assert errors == ["rule 2 repeats rule 1 (same device and condition)"]


def test_two_conditions_on_one_device_are_two_rules():
    clean, errors = am.validate_rules([_rule(cond="on"), _rule(cond="off")], DEFAULT)
    assert errors == [] and len(clean) == 2


def test_the_cap():
    many = [_rule(id=i + 1) for i in range(am.ALERT_RULES_MAX)]
    assert am.validate_rules(many, DEFAULT)[1] == []
    clean, errors = am.validate_rules(many + [_rule(id=5000)], DEFAULT)
    assert clean == [] and "at most 100 rules" in errors[0]


def test_not_a_list():
    assert am.validate_rules({"rules": []}, DEFAULT) == ([], ["rules must be a list"])


@pytest.mark.parametrize("addr, ok", [
    ("me@example.com", True), ("first.last+alerts@example.org", True),
    ("me@example", False), ("@example.com", False), ("me @example.com", False),
    ("me@exa mple.com", False), ("me@example.com;x@example.com", False),
    ("<me@example.com>", False), ("", False), ("a" * 250 + "@example.com", False),
])
def test_plausible_email(addr, ok):
    assert am.plausible_email(addr) is ok
