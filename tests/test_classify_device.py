#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_classify_device.py
# Description: Truth-table contract test for Plugin._classify_device — the
#              rooms.json device classifier. Locks the historically-tricky
#              shapes (dimmer fan, name-only contacts, z2m contacts with dummy
#              temp/humidity, value-sensor "doors", button remotes, skip types)
#              so a future tweak to the ladder can't silently re-miscategorise.
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import pytest
from conftest import bare_plugin, FakeDev


@pytest.fixture(scope="module")
def clsfy():
    p = bare_plugin()
    return p._classify_device


# (label, FakeDev kwargs, expected category)
CASES = [
    # Dimmers are lights unless the name says otherwise (fan).
    ("dimmer plain light",   dict(name="Kitchen Spots", cls="DimmerDevice"), "light"),
    ("dimmer fan not light", dict(name="Bathroom Fan", cls="DimmerDevice"),  "extras"),
    # Relays need a light keyword to count as a light.
    ("relay with light word", dict(name="Hall Lamp", cls="RelayDevice"),      "light"),
    ("relay no light word",   dict(name="Immersion Heater", cls="RelayDevice"), "extras"),
    # Motion / presence — by type or by name.
    ("occupancy type",   dict(name="Landing Sensor", deviceTypeId="z2mOccupancySensor"), "motion"),
    ("motion by name",   dict(name="Garage PIR", cls="z2mSensor"),            "motion"),
    ("water leak = motion tile", dict(name="Utility Leak Sensor", cls="z2mSensor"), "motion"),
    # Genuine contacts: boolean onState + type or name keyword.
    ("z2m contact by type", dict(name="Front Door", deviceTypeId="z2mContactSensor",
                                  supportsOnState=True), "window"),
    ("contact by name+onState", dict(name="Kitchen Window", cls="z2mSensor",
                                     supportsOnState=True), "window"),
    ("contact WITH dummy temp+humidity still a window",
     dict(name="Back Door", deviceTypeId="z2mContactSensor", supportsOnState=True,
          states={"temperature": 0.0, "humidity": 0.0}), "window"),
    # NOT contacts even though the name says door/window:
    ("value-sensor 'Front Door Temperature' (no onState) -> not a window",
     dict(name="Front Door Temperature", deviceTypeId="zwValueSensorType",
          supportsOnState=False, states={"temperature": 12.0, "humidity": 55.0}), "sensor"),
    ("button remote 'Garage Door Opener' -> not a window",
     dict(name="Hall Garage Door Opener", deviceTypeId="z2mButton",
          supportsOnState=True), "extras"),
    ("relay 'garage door' output -> light-ladder wins, not window",
     dict(name="Garage Door Relay", cls="RelayDevice", supportsOnState=True), "extras"),
    ("freezer contact excluded from windows",
     dict(name="Garage Freezer Door", cls="z2mSensor", supportsOnState=True,
          deviceTypeId="z2mContactSensor"), "extras"),
    # Environment sensor — needs BOTH temperature and humidity.
    ("temp+humidity sensor", dict(name="Lounge Climate", cls="z2mSensor",
                                  states={"temperature": 21.0, "humidity": 48.0}), "sensor"),
    ("temp only -> extras",  dict(name="Loft Probe", cls="z2mSensor",
                                  states={"temperature": 9.0}), "extras"),
    # Skip types return None (classified out entirely).
    ("HK bridge skipped", dict(name="Kitchen HomeKit", deviceTypeId="homeKitBridgeDevice"), None),
    ("repeater skipped",  dict(name="Z2M Repeater 1", deviceTypeId="z2mRepeater"), None),
]


@pytest.mark.parametrize("label,kw,expected", CASES, ids=[c[0] for c in CASES])
def test_classify_device_truth_table(clsfy, label, kw, expected):
    assert clsfy(FakeDev(**kw)) == expected


def test_supports_onstate_gate_is_strict_true(clsfy):
    """A contact-typed device whose supportsOnState is a truthy-but-not-True
    value (e.g. 1) must NOT be treated as a window — the code uses `is True`."""
    dev = FakeDev(name="Side Door", deviceTypeId="z2mContactSensor")
    dev.supportsOnState = 1  # truthy, but not the singleton True
    assert clsfy(dev) == "extras"
