#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_pin_redaction.py
# Description: Security contract test for Plugin._parse_lock_code_trigger — the
#              door-code roster parse that must NEVER surface PIN digits from a
#              trigger name to the browser. Locks the v2.38.0 fix (scrub ANY run
#              of 3+ digits, not just a wholly-numeric label).
# Author:      CliveS & Claude Fable 5
# Date:        15-07-2026
# Version:     1.0

import re
import pytest
from conftest import bare_plugin


@pytest.fixture(scope="module")
def parse():
    return bare_plugin()._parse_lock_code_trigger


def test_plain_label_preserved(parse):
    got = parse("Lock Alice Front Door Unlock Code (3) Cleaner")
    assert got == {"person": "Alice", "slot": 3, "label": "Cleaner"}


def test_wholly_numeric_label_scrubbed(parse):
    got = parse("Lock Bob Front Door Unlock Code (14) 1981")
    assert got["label"] == ""
    assert got["person"] == "Bob" and got["slot"] == 14


def test_embedded_pin_scrubbed(parse):
    # The whole label isn't numeric, but still carries a PIN — must be scrubbed.
    # Contract flipped in v2.95.2: the WHOLE label goes, not just the digit
    # run. The roster only needs person + slot, and a reminder written as
    # '4-4-7-1' or '44 71' slipped through the old 3-digits-in-a-row rule.
    got = parse("Lock Carol Front Door Unlock Code (2) code 4471 spare")
    assert "4471" not in got["label"]
    assert got["label"] == ""


def test_split_digit_pin_is_scrubbed_too(parse):
    for lbl in ("4-4-7-1", "44 71", "code 1 9 8 1"):
        got = parse(f"Lock Erin Front Door Unlock Code (3) {lbl}")
        assert got["label"] == "", lbl


def test_short_number_kept(parse):
    # A 1-2 digit run is not a PIN and is left alone.
    got = parse("Lock Dave Front Door Unlock Code (5) Flat 2")
    assert got["label"] == "Flat 2"


def test_non_matching_name_returns_none(parse):
    assert parse("Some unrelated trigger") is None
    assert parse("") is None
    assert parse(None) is None


def test_no_purely_numeric_label_ever_escapes(parse):
    """Property: for any label built from 3+ digit runs, the result is scrubbed
    so no long digit-run survives."""
    for name in ("Lock X Front Door Unlock Code (1) 999",
                 "Lock Y Front Door Unlock Code (1) 0000 guest",
                 "Lock Z Front Door Unlock Code (1) pin=123456"):
        got = parse(name)
        assert not re.search(r"\d{3,}", got["label"])
