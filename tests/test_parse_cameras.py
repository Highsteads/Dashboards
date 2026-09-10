#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_parse_cameras.py
# Description: Contract test for the module-level _parse_cameras — JSON-string vs
#              list input, required keys, vendor lowercasing, stream/room
#              normalisation, and safe handling of malformed input (never raises).
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import json
import pytest
from conftest import load_plugin_module


@pytest.fixture(scope="module")
def parse():
    return load_plugin_module()._parse_cameras


def test_json_string_valid_entry(parse):
    out = parse(json.dumps([{"host": "10.0.0.5", "name": "Front", "vendor": "DAHUA"}]))
    assert len(out) == 1
    assert out[0]["vendor"] == "dahua"          # lowercased
    assert out[0]["stream"] == "sub2"           # default stream
    assert out[0]["room"] == ""                 # no room -> empty string


def test_python_list_input(parse):
    out = parse([{"host": "h", "name": "n", "vendor": "hikvision"}])
    assert out[0]["host"] == "h" and out[0]["vendor"] == "hikvision"


def test_missing_required_key_dropped(parse):
    assert parse([{"host": "h", "name": "n"}]) == []          # no vendor key


def test_stream_main_preserved_unknown_falls_back(parse):
    assert parse([{"host": "h", "name": "n", "vendor": "dahua", "stream": "main"}])[0]["stream"] == "main"
    assert parse([{"host": "h", "name": "n", "vendor": "dahua", "stream": "hd"}])[0]["stream"] == "sub2"


def test_room_string_and_list_both_normalise(parse):
    assert parse([{"host": "h", "name": "n", "vendor": "dahua", "room": "Garage"}])[0]["room"] == "Garage"
    got = parse([{"host": "h", "name": "n", "vendor": "dahua", "room": ["Garage", " Hall "]}])[0]["room"]
    assert got == ["Garage", "Hall"]


@pytest.mark.parametrize("bad", ["not json", "", None, [], {"not": "a list"}, "123"])
def test_malformed_input_returns_empty(parse, bad):
    assert parse(bad) == []


def test_non_dict_entries_skipped(parse):
    out = parse([{"host": "h", "name": "n", "vendor": "dahua"}, "junk", 42, None])
    assert len(out) == 1
