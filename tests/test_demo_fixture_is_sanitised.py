#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_demo_fixture_is_sanitised.py
# Description: The demo fixture (demo-data/devices.json) is a snapshot of a
#              real Indigo system and it is published. Its first version went
#              out carrying an SMTP password, an ESPHome encryption key, a lock
#              passkey, the mail login and every hardware address, because the
#              generator only mapped IP addresses. This pins both halves: the
#              committed fixture holds only placeholders for those classes, and
#              tools/make_demo_fixtures.py's scrub() blanks them, so a fixture
#              regenerated from a live house cannot bring them back.
# Author:      CliveS & Claude Fable 5.1
# Date:        10-09-2026
# Version:     1.0

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX  = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages/demo-data/devices.json"
GEN  = ROOT / "tools/make_demo_fixtures.py"

CRED  = re.compile(r"pass|secret|token|encryptionkey|apikey|api_key|privatekey|psk", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
IPV4  = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
IEEE  = re.compile(r"0x[0-9a-fA-F]{16}")


@pytest.fixture(scope="module")
def fixture_text():
    return FIX.read_text(encoding="utf-8")


def _strings(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def test_credential_values_are_placeholders(fixture_text):
    seen = 0
    for key, value in _strings(json.loads(fixture_text)):
        if key and CRED.search(key) and value:
            seen += 1
            assert value.startswith("demo"), f"{key} holds something that is not a placeholder"
    assert seen, "the fixture carries no credential-shaped keys at all — is it the right file?"


def test_emails_and_addresses_are_placeholders(fixture_text):
    assert set(EMAIL.findall(fixture_text)) <= {"demo@example.com"}
    assert all(ip.startswith("192.0.2.") or ip in ("0.0.0.0", "127.0.0.1") for ip in IPV4.findall(fixture_text))


def test_hardware_addresses_are_obviously_fake(fixture_text):
    macs = re.findall(r'"mac_address":\s*"([0-9A-Fa-f]+)"', fixture_text)
    assert macs and all(m.startswith("02") and len(m) == 12 for m in macs)
    ieees = IEEE.findall(fixture_text)
    assert ieees and all(int(v, 16) < 1000 for v in ieees), "a Zigbee IEEE address that looks real"


def _generator():
    stub = types.ModuleType("IndigoSecrets")
    stub.INDIGO_URL, stub.INDIGO_API_KEY = "http://127.0.0.1:8176", "test"
    sys.modules["IndigoSecrets"] = stub
    spec = importlib.util.spec_from_file_location("make_demo_fixtures", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_generator_scrubs_the_same_classes():
    g = _generator()
    out = g.scrub({
        "name": "Kitchen Lamp",
        "serverPassword": "hunter2", "encryptionKey": "abc=", "passkey": "1234", "apiToken": "t",
        "fromAddress": "someone@example.org",
        # Sample values only — obviously made up, so this test can never be
        # the file that carries a real address into the public repo.
        "mac_address": "A1B2C3D4E5F6", "ieee_address": "0x1234567890abcdef",
        "ip_address": "192.168.1.5", "note": "mac aa:bb:cc:dd:ee:ff at 10.0.0.9",
        "nested": [{"password": "x"}, "plain"],
    })
    assert out["name"] == "Kitchen Lamp", "a plain name must not be touched"
    for k in ("serverPassword", "encryptionKey", "passkey", "apiToken"):
        assert out[k] == "demo-secret", k
    assert out["fromAddress"] == "demo@example.com"
    assert out["mac_address"].startswith("02") and len(out["mac_address"]) == 12
    assert out["ieee_address"] == "0x0000000000000001"
    assert out["ip_address"].startswith("192.0.2.")
    assert out["note"] == "mac 00:00:00:00:00:00 at 192.0.2.2"
    assert out["nested"] == [{"password": "demo-secret"}, "plain"]
    assert "address" not in g.scrub({"address": "x", "name": "y"}), "DROP_KEYS still drops"
