#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_guest_variables.py
# Description: A guest reads only the Indigo variables it is allowed (3.46.0).
#              The :8177 guest route passed /v2/api/indigo.variables through
#              whole, and the scrub only strips device props, so a visitor's
#              phone could read every variable: alarm states, away flags,
#              anything a house keeps there. No guest page needs one (only
#              the Alerts picker lists them), so the default is NONE, and
#              guestVariables in the settings store names any to share, by
#              id or by name. The allow-list fails closed on any odd input.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import re
from pathlib import Path

import pytest

from conftest import load_plugin_module

plugin = load_plugin_module()
P = plugin.Plugin
SRC = (Path(__file__).resolve().parents[1]
       / "Dashboards.indigoPlugin/Contents/Server Plugin/cameras_mixin.py").read_text(encoding="utf-8")

VARS = [
    {"id": 101, "name": "alarm_state", "value": "disarmed", "folderId": 0},
    {"id": 102, "name": "HouseMode", "value": "away"},
    {"id": 103, "name": "door_code", "value": "4321", "description": "the keypad code"},
]


@pytest.mark.parametrize("store, want", [
    ({}, (set(), set())),
    (None, (set(), set())),
    ({"guestVariables": []}, (set(), set())),
    ({"guestVariables": "HouseMode"}, (set(), set())),           # a string is not a list
    ({"guestVariables": {"HouseMode": True}}, (set(), set())),
    ({"guestVariables": True}, (set(), set())),
    ({"guestVariables": [102]}, ({102}, set())),
    ({"guestVariables": ["102", " HouseMode "]}, ({102}, {"housemode"})),
    ({"guestVariables": [True, None, "", 3.5, {"x": 1}]}, (set(), set())),
])
def test_the_allow_list(store, want):
    assert P._guest_variable_allow(store) == want


def test_nothing_allowed_is_nothing_returned():
    assert P._guest_filter_variables(VARS, set(), set()) == []


def test_by_id_and_by_name_without_regard_to_case():
    got = P._guest_filter_variables(VARS, {101}, {"housemode"})
    assert [v["id"] for v in got] == [101, 102]
    assert "4321" not in json.dumps(got)


def test_the_envelope_shape_is_filtered_too():
    got = P._guest_filter_variables({"objects": VARS, "count": 3}, set(), {"housemode"})
    assert [v["id"] for v in got["objects"]] == [102]


def test_an_unknown_shape_fails_closed():
    assert P._guest_filter_variables({"weird": VARS}, {101}, set()) == []
    assert P._guest_filter_variables("text", {101}, set()) == []


def test_a_bool_id_is_not_variable_one():
    assert P._guest_filter_variables([{"id": True, "name": "x"}], {1}, set()) == []


def test_the_route_filters_before_it_scrubs_and_skips_iws_when_nothing_is_allowed():
    route = SRC.split('elif sub == "variables":', 1)[1].split("elif sub.startswith", 1)[0]
    assert "_guest_variable_allow" in route
    assert re.search(r'if not \(guest_vars\[0\] or guest_vars\[1\]\):\s*_send_json\(b"\[\]"\)\s*return', route), \
        "with nothing allowed the guest gets [] and IWS is never asked"
    relay = SRC.split("body = json.loads(raw)", 1)[1].split("_send_json(", 1)[0]
    assert "_guest_filter_variables" in relay and "_guest_scrub" in relay
    assert relay.index("_guest_filter_variables") < relay.index("_guest_scrub")
