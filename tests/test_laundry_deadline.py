#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_laundry_deadline.py
# Description: Contract test for the Laundry page's deadline validation.
#
#              WHY THIS EXISTS
#              An Indigo variable takes any string it is handed. Junk written into
#              washing_machine_deadline would not fail loudly — Appliance_Scheduler.py
#              would warn and fall back to its default every fifteen minutes, for ever,
#              while the page went on showing a plan for the wrong time. So the endpoint
#              refuses at the door, and this pins what it refuses.
# Author:      CliveS & Claude Opus 5
# Date:        09-09-2026
# Version:     1.0

from conftest import load_plugin_module

plugin = load_plugin_module()
nd = plugin.normalise_deadline
nk = plugin.normalise_appliance_key


class TestItAcceptsRealTimes:
    def test_a_plain_time(self):
        assert nd("16:00") == "16:00"

    def test_it_zero_pads_so_the_script_sees_one_shape(self):
        assert nd("9:05") == "09:05"
        assert nd("9:5") == "09:05"

    def test_the_edges_of_the_day(self):
        assert nd("00:00") == "00:00"
        assert nd("23:59") == "23:59"

    def test_surrounding_space_is_forgiven(self):
        assert nd("  14:30  ") == "14:30"


class TestEmptyMeansUseTheDefault:
    def test_empty_string(self):
        assert nd("") == ""

    def test_only_space(self):
        assert nd("   ") == ""

    def test_none(self):
        assert nd(None) == ""


class TestItRefusesEverythingElse:
    """None is the refusal; "" is a legitimate answer. They must never be confused —
    returning "" for junk would silently reset the deadline instead of reporting a fault."""

    def test_words(self):
        assert nd("tea time") is None

    def test_an_hour_that_does_not_exist(self):
        assert nd("25:00") is None

    def test_a_minute_that_does_not_exist(self):
        assert nd("16:70") is None

    def test_no_colon(self):
        assert nd("16") is None

    def test_too_many_colons(self):
        assert nd("16:00:00") is None

    def test_negative(self):
        assert nd("-1:00") is None

    def test_not_a_number(self):
        assert nd("aa:bb") is None

    def test_a_number_is_not_a_time(self):
        assert nd(1600) is None

    def test_refusal_is_None_and_never_the_empty_string(self):
        """The two are worlds apart: "" resets the deadline to the default, None reports a
        fault. Confusing them would silently discard whatever the reader had set."""
        for junk in ("tea time", "25:00", "16", "aa:bb", "16:00:00"):
            got = nd(junk)
            assert got is None, f"{junk!r} gave {got!r} — junk must never read as a value"


class TestTheApplianceKeyIsCheckedToo:
    """It is interpolated straight into an Indigo variable name, and Indigo variable names
    may not contain spaces — so a key that gets through creates a variable nothing can read
    back, silently, for ever."""

    def test_a_real_key(self):
        assert nk("washing_machine") == "washing_machine"
        assert nk("tumble_dryer") == "tumble_dryer"
        assert nk("dishwasher") == "dishwasher"

    def test_case_and_space_are_tidied(self):
        assert nk("  Washing_Machine ") == "washing_machine"

    def test_a_space_inside_is_refused(self):
        assert nk("washing machine") is None

    def test_path_traversal_is_refused(self):
        assert nk("../../etc/passwd") is None
        assert nk("a/b") is None

    def test_punctuation_is_refused(self):
        for junk in ("a-b", "a.b", "a$b", "a'b", 'a"b', "a;b"):
            assert nk(junk) is None, junk

    def test_it_must_start_with_a_letter(self):
        assert nk("1machine") is None
        assert nk("_machine") is None

    def test_stray_underscores_are_refused(self):
        assert nk("machine_") is None
        assert nk("a__b") is None

    def test_empty_is_refused_rather_than_defaulted(self):
        assert nk("") is None
        assert nk(None) is None
        assert nk("   ") is None

    def test_absurdly_long_is_refused(self):
        assert nk("a" * 61) is None
        assert nk("a" * 60) == "a" * 60
