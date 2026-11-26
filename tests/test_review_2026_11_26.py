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


# ---- second group -----------------------------------------------------------

def test_the_day_view_keeps_solar_rows_that_carry_no_battery_reading():
    from conftest import plugin_source
    src = plugin_source()
    assert 'has_reading = f\'("{soc}" IS NOT NULL OR "{pv}" IS NOT NULL)\' if pv else' in src
    assert "AND {has_reading}'" in src
    assert 'ts < ? AND "{soc}" IS NOT NULL\'' not in src


def test_solar_rows_without_a_battery_figure_are_averaged(tmp_path):
    """The query itself, against a real SQLite table: SOC written once, solar
    written every five minutes. The solar trace must have every bucket."""
    import sqlite3
    db = sqlite3.connect(str(tmp_path / "h.sqlite"))
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, ts TIMESTAMP, batterysoc REAL, pvpowerwatts REAL)")
    db.execute("INSERT INTO t (ts, batterysoc, pvpowerwatts) VALUES ('2026-06-01 10:00:00', 50.0, 1000)")
    for i in range(1, 6):
        db.execute("INSERT INTO t (ts, pvpowerwatts) VALUES (?, ?)", (f"2026-06-01 10:{i * 5:02d}:00", 1000 + i * 100))
    soc, pv = "batterysoc", "pvpowerwatts"
    has_reading = f'("{soc}" IS NOT NULL OR "{pv}" IS NOT NULL)'
    rows = db.execute(
        f"SELECT ((CAST(strftime('%s', ts) AS INTEGER) - CAST(strftime('%s', '2026-06-01 10:00:00') AS INTEGER)) / 300) AS b5, "
        f'avg(CAST("{soc}" AS REAL)), avg(CAST("{pv}" AS REAL)) FROM t WHERE ts >= ? AND ts < ? AND {has_reading} '
        f"GROUP BY b5 ORDER BY b5", ("2026-06-01 10:00:00", "2026-06-01 11:00:00")).fetchall()
    assert [r[0] for r in rows] == [0, 1, 2, 3, 4, 5]
    assert rows[0][1] == 50.0 and rows[3][1] is None and rows[3][2] == 1300.0


def test_a_tiny_yearly_saving_does_not_break_the_savings_reply():
    load_plugin_module()
    import inspect
    import savings_model
    src = inspect.getsource(savings_model)
    assert "if years_left <= 200:" in src
    # The sum the old line did, to show it was real: a 26,470 pound system saving 0.01 a year.
    from datetime import date, timedelta
    import pytest
    with pytest.raises(OverflowError):
        date(2026, 11, 26) + timedelta(days=round((26470 / 0.01) * 365.25))


def test_sigen_query_must_be_an_object():
    from conftest import plugin_source
    assert 'if not isinstance(query, dict):' in plugin_source()


def test_a_meter_value_must_be_a_finite_number():
    load_plugin_module()
    pick = bare_plugin()._mains_pick
    assert pick({"powerWatts": True}, ["powerWatts"]) is None
    assert pick({"powerWatts": float("nan")}, ["powerWatts"]) is None
    assert pick({"powerWatts": "inf"}, ["powerWatts"]) is None
    assert pick({"powerWatts": "12.5"}, ["powerWatts"]) == 12.5
    assert pick({"power": float("nan"), "powerWatts": 3}, ["power", "powerWatts"]) == 3.0


def test_vehicles_with_a_bad_id_are_left_out_not_fatal():
    load_plugin_module()
    f = bare_plugin()._vehicles_for_page
    assert f([{"id": 5, "label": "Qashqai"}, {"id": "--5"}, {"id": "²"}, {"id": True}, {"id": "7"}, "x"]) == [
        {"id": 5, "label": "Qashqai"}, {"id": 7, "label": "Vehicle"}]
    assert f(None) == [] and f({"id": 5}) == []


def test_a_page_with_the_same_size_and_an_older_date_is_republished(tmp_path, monkeypatch):
    import os
    load_plugin_module()
    import inspect
    import publish_mixin
    src = inspect.getsource(publish_mixin)
    assert "filecmp.cmp(sp, dp, shallow=False)" in src
    assert "(ss.st_mtime > ds.st_mtime)\n                if need" not in src
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    a.write_text("new page"); b.write_text("old page")
    os.utime(a, (1000, 1000)); os.utime(b, (2000, 2000))        # same size, the bundle's copy older
    import filecmp
    assert os.stat(a).st_size == os.stat(b).st_size and not filecmp.cmp(str(a), str(b), shallow=False)


def test_hand_edited_store_values_of_the_wrong_type_do_not_stop_the_start():
    from conftest import plugin_source
    src = plugin_source()
    assert 'swap_pref = _swap.strip() if isinstance(_swap, str) else ""' in src
    assert "self.main_cameras = [h for h in _main if isinstance(h, str)] if isinstance(_main, (list, tuple)) else []" in src
    assert "self.pin_required = _safe_int_list(_pins) if isinstance(_pins, (list, tuple)) else []" in src


# ---- third group ------------------------------------------------------------

def test_a_bad_alert_revision_number_reads_as_nought():
    load_plugin_module()
    import alerts_mixin
    f = alerts_mixin._rules_rev
    assert f({"alertRulesRev": 7}) == 7 and f({"alertRulesRev": "7"}) == 7
    assert f({"alertRulesRev": "seven"}) == 0 and f({"alertRulesRev": None}) == 0
    assert f({"alertRulesRev": True}) == 0 and f({}) == 0 and f(None) == 0


def test_the_worker_joins_share_one_second():
    from conftest import plugin_source
    src = plugin_source()
    assert "t.join(timeout=max(0.0, deadline - time.time()))" in src
