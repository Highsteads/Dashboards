#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    make_demo_fixtures.py
# Description: Generate the demo-mode fixtures (demo-data/) from a LIVE
#              Indigo system, sanitised: every RFC1918 IP is mapped to a
#              documentation address (192.0.2.x), device "address" fields are
#              dropped, and only a whitelist of variables is included. Output
#              goes into the bundle's pages/demo-data/ (and from there into
#              the repo via the normal sync).
# Author:      CliveS & Claude Fable 5
# Date:        11-06-2026
# Version:     1.1
#
# v1.1 (10-09-2026): scrubs MORE than addresses. The v1.0 fixture went into the
#   repo carrying an SMTP password, an ESPHome encryption key, a lock passkey,
#   the mail login and every Shelly and Zigbee hardware address, because this
#   only mapped IPs and colon-separated MACs. Any key that NAMES a credential
#   is blanked by shape (pass/secret/token/key/psk), e-mail addresses become
#   demo@example.com, colon-less MACs and Zigbee IEEE addresses are mapped to
#   obviously fake sequential values. Household names are NOT something a
#   generator can know — read the device and scene names in the output by
#   hand before committing it. tests/test_demo_fixture_is_sanitised.py checks
#   both the fixture and this function.
#
# Usage: python3 tools/make_demo_fixtures.py
#        (run on the Indigo server; reads INDIGO_URL/INDIGO_API_KEY from
#         IndigoSecrets.py)

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
from IndigoSecrets import INDIGO_URL, INDIGO_API_KEY  # noqa: E402

PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "Dashboards.indigoPlugin", "Contents", "Resources",
                         "static", "pages")
OUT_DIR = os.path.join(PAGES_DIR, "demo-data")

# Variables the pages actually consume (kiosk dimming).
VARIABLE_WHITELIST = {"Lux_Value", "Lux_Level"}

_IP_RE  = re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b")
_MAC_RE = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")
_MAC12_RE = re.compile(r"\b[0-9A-Fa-f]{12}\b")        # colon-less MACs (Shelly mac_address)
_IEEE_RE  = re.compile(r"0x[0-9a-fA-F]{16}")           # Zigbee IEEE addresses
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A key whose VALUE is a credential is blanked whatever the plugin calls it —
# the SMTP password, an ESPHome encryption key, a lock passkey, an API token.
# Matched on the key NAME by shape, so a new plugin's spelling is caught
# without being listed here.
_CREDENTIAL_KEY_RE = re.compile(r"pass|secret|token|encryptionkey|apikey|api_key|privatekey|psk", re.I)
# State/property keys whose VALUES are dropped outright — they can carry
# client hostnames, MACs, serials or other identifying payloads.
DROP_KEYS = {"address", "clientsJson", "serialNumber", "macAddress"}
_ip_map, _mac_map, _ieee_map = {}, {}, {}


def _scrub_ip(match):
    ip = match.group(0)
    if ip not in _ip_map:
        _ip_map[ip] = f"192.0.2.{len(_ip_map) + 1}"
    return _ip_map[ip]


def _scrub_mac12(match):
    mac = match.group(0).upper()
    if mac not in _mac_map:
        _mac_map[mac] = "02%010X" % (len(_mac_map) + 1)   # locally administered, obviously fake
    return _mac_map[mac]


def _scrub_ieee(match):
    ieee = match.group(0).lower()
    if ieee not in _ieee_map:
        _ieee_map[ieee] = "0x%016x" % (len(_ieee_map) + 1)
    return _ieee_map[ieee]


def scrub(obj, key=None):
    """Recursively sanitise: blank any value whose key names a credential, map
    private IPs to documentation addresses, blank MAC addresses (both forms),
    map Zigbee IEEE addresses and e-mail addresses to placeholders, and drop
    keys that carry identifying payloads (UniFi clientsJson, device addresses,
    serials). `key` is the dict key the value sits under, so a credential can
    be recognised by its name and a colon-less MAC only under a MAC key."""
    if isinstance(obj, dict):
        return {k: scrub(v, k) for k, v in obj.items() if k not in DROP_KEYS}
    if isinstance(obj, list):
        return [scrub(v, key) for v in obj]
    if isinstance(obj, str):
        if key and obj and _CREDENTIAL_KEY_RE.search(key):
            return "demo-secret"
        obj = _IP_RE.sub(_scrub_ip, obj)
        obj = _MAC_RE.sub("00:00:00:00:00:00", obj)
        obj = _EMAIL_RE.sub("demo@example.com", obj)
        obj = _IEEE_RE.sub(_scrub_ieee, obj)
        if key and "mac" in key.lower():
            obj = _MAC12_RE.sub(_scrub_mac12, obj)
        return obj
    return obj


def fetch(path):
    req = urllib.request.Request(
        f"{INDIGO_URL}{path}",
        headers={"Authorization": f"Bearer {INDIGO_API_KEY}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    devices = scrub(fetch("/v2/api/indigo.devices"))
    with open(os.path.join(OUT_DIR, "devices.json"), "w", encoding="utf-8") as f:
        json.dump(devices, f)
    print(f"devices.json: {len(devices)} devices ({len(_ip_map)} IPs scrubbed)")

    variables = [v for v in fetch("/v2/api/indigo.variables")
                 if v.get("name") in VARIABLE_WHITELIST]
    with open(os.path.join(OUT_DIR, "variables.json"), "w", encoding="utf-8") as f:
        json.dump(scrub(variables), f)
    print(f"variables.json: {len(variables)} variables")

    # rooms / scenes / weather straight from the live public folder, scrubbed.
    for name in ("rooms.json", "scenes.json", "weather.json"):
        try:
            with urllib.request.urlopen(f"{INDIGO_URL}/public/dashboards/{name}",
                                        timeout=10) as r:
                data = scrub(json.load(r))
            with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
                json.dump(data, f)
            print(f"{name}: copied + scrubbed")
        except Exception as exc:
            print(f"{name}: skipped ({exc})")

    print(f"\nFixtures written to {OUT_DIR}")


if __name__ == "__main__":
    main()
