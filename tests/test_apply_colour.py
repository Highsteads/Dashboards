#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_apply_colour.py
# Description: Contract test for Plugin.handleApplyColour — the v2.94.0 endpoint
#              that moved the colour sequence off the phone.
#
#              WHY IT EXISTS
#              Applying a preset used to be three ordered commands fired by the
#              BROWSER — turn on, set brightness, set colour — each wrapped in an
#              empty catch. A phone that locked, backgrounded the tab or lost
#              signal between them left the lamp half-set and said nothing at
#              all. The sequence now runs on the server behind one request.
#
#              WHAT IS LOCKED HERE
#              1. The three commands go in ORDER. Brightness before colour, and
#                 both after the lamp is switched on.
#              2. A failing step does NOT stop the rest, but IS reported. The
#                 whole point was to stop losing failures.
#              3. Junk input is REFUSED, never clamped — a clamp turns a bad
#                 request into a light that quietly did something else.
#              4. A preset is applied from the SERVER's table, so the browser
#                 cannot ask for values the server has not agreed to.
# Author:      CliveS & Claude Opus 5
# Date:        30-08-2026
# Version:     1.0

import json
from unittest.mock import MagicMock

import pytest
from conftest import bare_plugin, load_plugin_module


class FakeAction:
    def __init__(self, body):
        self.props = {"request_body": body}


class _Devices:
    """Stands in for indigo.devices: subscriptable, and `in` answers without
    raising for an unknown id (which is how the real collection behaves)."""

    def __init__(self, devs):
        self._d = devs

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        return self._d[key]


@pytest.fixture
def rig(monkeypatch):
    """A plugin with the Indigo command namespaces recorded in call order."""
    plugin = load_plugin_module()
    p = bare_plugin()

    calls = []
    dev = MagicMock()
    dev.id = 372666822
    dev.name = "Living Room Colour Lamp"

    monkeypatch.setattr(plugin.indigo, "devices", _Devices({dev.id: dev}), raising=False)

    device_ns = MagicMock()
    device_ns.turnOn.side_effect = lambda i: calls.append(("turnOn", i))
    dimmer_ns = MagicMock()
    dimmer_ns.setBrightness.side_effect = lambda i, value=None: calls.append(("setBrightness", i, value))
    dimmer_ns.setColorLevels.side_effect = lambda i, **kw: calls.append(("setColorLevels", i, kw))
    monkeypatch.setattr(plugin.indigo, "device", device_ns, raising=False)
    monkeypatch.setattr(plugin.indigo, "dimmer", dimmer_ns, raising=False)

    p._evo_reply = lambda payload, status=200: {"status": status, "content": json.dumps(payload)}
    return p, calls, device_ns, dimmer_ns


def call(p, body):
    reply = p.handleApplyColour(FakeAction(json.dumps(body) if not isinstance(body, str) else body))
    return reply["status"], json.loads(reply["content"])


def test_preset_applies_in_order(rig):
    """turn on, THEN brightness, THEN colour. Out of order, a lamp can land at
    the old brightness or flash the previous colour on the way."""
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 372666822, "preset": "warm"})
    assert status == 200 and body["ok"] is True
    assert [c[0] for c in calls] == ["turnOn", "setBrightness", "setColorLevels"]
    assert calls[1][2] == 100
    assert calls[2][2] == {"whiteTemperature": 2700}
    assert [s["step"] for s in body["steps"]] == ["turnOn", "setBrightness", "setColorLevels"]


def test_colour_preset_sends_rgb(rig):
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 372666822, "preset": "movie"})
    assert status == 200 and body["ok"] is True
    assert calls[1][2] == 18
    assert calls[2][2] == {"redLevel": 100, "greenLevel": 35, "blueLevel": 8}


def test_explicit_levels_without_a_preset(rig):
    """The colour picker sends levels directly and deliberately sends NO
    brightness — it leaves brightness where the user had it."""
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 372666822, "whiteTemperature": 3000})
    assert status == 200 and body["ok"] is True
    assert [c[0] for c in calls] == ["turnOn", "setColorLevels"]
    assert calls[1][2] == {"whiteTemperature": 3000}
    assert body["applied"]["brightness"] is None


def test_a_failing_step_is_reported_and_the_rest_still_run(rig):
    """The browser used to swallow each failure. A failed turn-on must not
    abort the colour — a colour command lands on a lamp that is off — but it
    must be RETURNED, and the call must not report success."""
    p, calls, device_ns, _ = rig
    device_ns.turnOn.side_effect = RuntimeError("device is not responding")
    status, body = call(p, {"deviceId": 372666822, "preset": "warm"})
    assert status == 502 and body["ok"] is False
    steps = {s["step"]: s for s in body["steps"]}
    assert steps["turnOn"]["ok"] is False
    assert "not responding" in steps["turnOn"]["error"]
    assert steps["setBrightness"]["ok"] is True and steps["setColorLevels"]["ok"] is True
    assert [c[0] for c in calls] == ["setBrightness", "setColorLevels"]
    assert p.logger.warning.called


def test_unknown_preset_is_refused(rig):
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 372666822, "preset": "disco"})
    assert status == 400 and body["ok"] is False and "disco" in body["error"]
    assert calls == []


def test_unknown_device_is_refused_not_guessed(rig):
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 999, "preset": "warm"})
    assert status == 404 and body["ok"] is False
    assert calls == []


@pytest.mark.parametrize("body,fragment", [
    ({"deviceId": "nope", "preset": "warm"}, "deviceId"),
    ({"deviceId": 372666822, "redLevel": 101}, "redLevel"),
    ({"deviceId": 372666822, "redLevel": -1}, "redLevel"),
    ({"deviceId": 372666822, "whiteTemperature": 300}, "whiteTemperature"),
    ({"deviceId": 372666822, "whiteTemperature": "warmish"}, "whiteTemperature"),
    ({"deviceId": 372666822, "brightness": 120}, "brightness"),
    ({"deviceId": 372666822, "brightness": "half"}, "brightness"),
    ({"deviceId": 372666822}, "nothing to apply"),
])
def test_junk_is_refused_never_clamped(rig, body, fragment):
    """A clamp would turn a caller's mistake into a light that quietly did
    something other than what was asked — much harder to notice than a 400."""
    p, calls, _, _ = rig
    status, reply = call(p, body)
    assert status == 400 and reply["ok"] is False
    assert fragment in reply["error"]
    assert calls == []


def test_bad_json_and_non_object_bodies(rig):
    p, _, _, _ = rig
    status, body = call(p, "{not json")
    assert status == 400 and "bad JSON" in body["error"]
    status, body = call(p, json.dumps(["a", "list"]))
    assert status == 400 and "object" in body["error"]


def test_unknown_level_keys_are_ignored_not_forwarded(rig):
    """Only the keys setColorLevels actually accepts are passed on. A stray key
    would raise inside the IOM call and lose the whole colour change."""
    p, calls, _, _ = rig
    status, body = call(p, {"deviceId": 372666822, "whiteTemperature": 3000,
                            "sparkle": 11, "brightness": 50})
    assert status == 200
    assert calls[2][2] == {"whiteTemperature": 3000}


def test_preset_table_matches_what_the_pages_are_told(rig):
    """The page draws its buttons from `colourPresets` in config.js and sends
    only the KEY. Both come from this one table — two copies would drift the
    moment one was edited."""
    plugin = load_plugin_module()
    assert set(plugin.COLOUR_PRESETS) == {"warm", "movie"}
    for preset in plugin.COLOUR_PRESETS.values():
        assert preset["label"] and preset["icon"] and preset["mode"] in ("white", "color")
