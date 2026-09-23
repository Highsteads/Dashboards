#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_capture_rename.py
# Description: capture_screenshots.py --rename (v1.3): people's names are
#              replaced, as whole words, in every response the sanitising proxy
#              passes, and one that survives is reported as a leak rather than
#              published.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools/capture_screenshots.py"
spec = importlib.util.spec_from_file_location("capture_screenshots", TOOL)
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)


def test_names_are_replaced_as_whole_words():
    s = cap.Sanitiser([("Clive", "Alex"), ("Jane", "Sam")])
    body = b'{"name": "Presence - Clive iPhone", "b": "Jane Lamp", "c": "Janet", "d": "192.168.1.5"}'
    out = s.scrub(body)
    assert b"Alex iPhone" in out and b"Sam Lamp" in out
    assert b"Janet" in out, "a longer word that starts with a name is left alone"
    assert b"192.168.1.5" not in out, "addresses are still rewritten"
    assert s.name_residue(out) == []


def test_a_surviving_name_is_reported():
    s = cap.Sanitiser([("Clive", "Alex")])
    assert s.name_residue(b"Clive Lamp") == [r"\bClive\b"]


def test_no_renames_changes_nothing_but_addresses():
    s = cap.Sanitiser()
    assert s.scrub(b"Clive Lamp") == b"Clive Lamp"


def test_content_type_is_found_whatever_its_case():
    """IWS answers the API with a lower-case content-type; an exact lookup
    missed it and those replies were never scrubbed."""
    assert cap.header_value({"content-type": "application/json"}, "Content-Type") == "application/json"
    assert cap.header_value({"Content-Type": "text/html"}, "content-type") == "text/html"
    assert cap.header_value({}, "Content-Type") == ""
    src = TOOL.read_text(encoding="utf-8")
    assert 'headers.get("Content-Type"' not in src


def test_macs_are_rewritten_and_checked():
    s = cap.Sanitiser()
    out = s.scrub(b'"mac": "70:A7:41:00:11:22", "b": "70-a7-41-00-11-22", "c": "12:30:45"')
    assert b"70:A7:41" not in out and b"70-a7-41" not in out
    assert out.count(b"02:00:00:00:00:01") == 2, "one device, one stable fake, whatever the separator"
    assert b"12:30:45" in out, "a time is not a MAC"
    assert s.mac_residue(out) == []
    assert s.mac_residue(b"aa:bb:cc:dd:ee:ff") == ["aa:bb:cc:dd:ee:ff"]
