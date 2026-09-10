#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_guest_scrub.py
# Description: A guest-token holder must never receive plugin props. The
#              :8177 guest passthrough relayed the v2 API's device JSON
#              verbatim until 2.95.1, and that JSON carries pluginProps /
#              globalProps / ownerProps — where the Email+ SMTP device keeps
#              the mail server password, and every Shelly keeps its address.
#              The "read-only, no control surface" tier was handing the
#              household mail password to anyone who scanned the pairing QR.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

from conftest import load_plugin_module


def _P():
    return load_plugin_module().Plugin


DEVICE = {
    "id": 1192809466, "name": "Email+ SMTP Server", "class": "Device",
    "deviceTypeId": "smtp", "enabled": True, "onState": None,
    "states": {"status": "ok"}, "lastChanged": "2026-09-02 10:00:00",
    "pluginProps": {"serverLogin": "clive", "serverPassword": "hunter2"},
    "globalProps": {"com.indigodomo.email": {"serverPassword": "hunter2"}},
    "ownerProps": {"serverPassword": "hunter2"},
    "sharedProps": {"x": 1}, "description": "the house mail", "address": "smtp.example",
}


def _no_secret(obj):
    import json
    return "hunter2" not in json.dumps(obj)


def test_single_device_loses_its_props_but_keeps_what_the_pages_read():
    out = _P()._guest_scrub(dict(DEVICE))
    assert _no_secret(out)
    for k in ("pluginProps", "globalProps", "ownerProps", "sharedProps", "description", "address"):
        assert k not in out
    for k in ("id", "name", "class", "deviceTypeId", "enabled", "onState", "states", "lastChanged"):
        assert out[k] == DEVICE[k]


def test_device_list_and_envelope_are_scrubbed_recursively():
    assert _no_secret(_P()._guest_scrub([dict(DEVICE), dict(DEVICE)]))
    assert _no_secret(_P()._guest_scrub({"objects": [dict(DEVICE)], "count": 1}))


def test_non_container_values_pass_through():
    assert _P()._guest_scrub("text") == "text"
    assert _P()._guest_scrub(42) == 42
