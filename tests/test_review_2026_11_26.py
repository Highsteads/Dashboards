#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_review_2026_11_26.py
# Description: Server-side fixes from the 25/26-Nov-2026 deep review that have
#              no test file of their own: the memory verdict, a failed memory
#              measurement, and door codes reaching the browser.
# Author:      CliveS & Claude Fable 5.2
# Date:        26-11-2026
# Version:     1.0

import subprocess

from conftest import bare_plugin, load_plugin_module


def test_macos_decides_the_memory_verdict_where_it_gives_one():
    load_plugin_module()
    f = bare_plugin()._memory_pressure
    ram = {"total_gb": 64.0, "used_pct": 55.0, "swap_used_mb": 1126}
    assert f(dict(ram), 1) == "normal"          # 1.1 GB of swap on a 64 GB Mac read "elevated"
    assert f(dict(ram), 2) == "elevated"
    assert f(dict(ram), 4) == "high"


def test_without_macos_verdict_swap_is_judged_against_the_ram_fitted():
    load_plugin_module()
    f = bare_plugin()._memory_pressure
    assert f({"total_gb": 64.0, "used_pct": 55.0, "swap_used_mb": 1126}, None) == "normal"
    assert f({"total_gb": 64.0, "used_pct": 55.0, "swap_used_mb": 4000}, None) == "elevated"
    assert f({"total_gb": 8.0, "used_pct": 60.0, "swap_used_mb": 500}, None) == "elevated"
    assert f({"total_gb": 8.0, "used_pct": 60.0, "swap_used_mb": 1600}, None) == "high"
    assert f({"total_gb": 8.0, "used_pct": 93.0, "swap_used_mb": 0}, None) == "high"
    assert f({"total_gb": 8.0}, 1) == "unknown"          # nothing measured: never "normal"


def test_a_memory_measurement_that_fails_is_unknown_not_nought(monkeypatch):
    """vm_stat timing out (what a starved Mac does) used to give 0 GB used,
    0%, and "normal"."""
    load_plugin_module()

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("vm_stat", 5)
    monkeypatch.setattr(subprocess, "run", boom)
    ram = bare_plugin()._mac_vitals()["ram"]
    assert ram["pressure"] == "unknown"
    assert "used_gb" not in ram and "used_pct" not in ram


def test_a_door_code_in_a_lock_log_line_is_masked():
    load_plugin_module()
    scrub = bare_plugin()._scrub_codes
    assert "4471" not in scrub("Setting PIN 4471 for user 3 on Front Door Lock")
    assert "user 3" in scrub("Setting PIN 4471 for user 3 on Front Door Lock")
    assert "447" not in scrub("user code 447 set")                 # a short code beside the word
    assert scrub("Door locked manually [Node: 44]") == "Door locked manually [Node: 44]"
    assert scrub("Front Door Lock unlocked by keypad, user 2") == "Front Door Lock unlocked by keypad, user 2"
    assert "19811981" not in scrub("sent 19811981 to node 157")


def test_a_switched_off_door_code_trigger_is_listed_without_its_code():
    load_plugin_module()
    safe = bare_plugin()._safe_automation_name
    assert safe("Lock Jane Front Door Unlock Code (2) 4471") == "Lock Jane Front Door Unlock Code (2)"
    assert safe("Lock Clive Front Door Unlock Code (1) main") == "Lock Clive Front Door Unlock Code (1) main"
    assert safe("Kitchen Light Off If All Occupancy Sensors OFF") == "Kitchen Light Off If All Occupancy Sensors OFF"


def test_the_disabled_list_and_the_diary_go_through_the_scrub():
    from conftest import plugin_source
    src = plugin_source()
    assert 'disabled.append({"name": self._safe_automation_name(t.name), "kind": "trigger"})' in src
    assert "self._scrub_codes(msg) if cat == \"lock\" else msg" in src
