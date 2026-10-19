#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_presence_gate.py
# Description: System Health shows a presence-gated device as out of contact while
#              someone is away, instead of "unreachable". Stays "unreachable" when
#              both are home, or when any presence reading is missing or unknown.
#              Mirrors Device Health Monitor's presence gate (same rule, same file).
# Author:      CliveS & Claude Haiku 5.5
# Date:        19-10-2026
# Version:     1.0

import json
from types import SimpleNamespace

from conftest import bare_plugin, load_plugin_module

QASHQAI = 7001
CLIVE   = 1809194959
JANE    = 420261884
AWAY_LABEL = "out of contact while someone is away"


class _Devices(dict):
    """Keyed by id like indigo.devices[pid], iterated like indigo.devices."""

    def __iter__(self):
        return iter(list(self.values()))


def _dev(i, name, error="", enabled=True, states=None):
    return SimpleNamespace(id=i, name=name, enabled=enabled,
                           pluginId="com.clives.indigoplugin.shellyg1",
                           errorState=error, batteryLevel=None,
                           states=states or {}, lastChanged=None)


def _page(monkeypatch, tmp_path, devices, gate=None, raw=None):
    """A bare Plugin whose device table holds `devices`, and a presence file if asked for."""
    load_plugin_module()
    import health_mixin
    cfg = tmp_path / "presence_gated.json"
    if raw is not None:
        cfg.write_text(raw, encoding="utf-8")
    elif gate is not None:
        cfg.write_text(json.dumps(gate), encoding="utf-8")
    monkeypatch.setattr(health_mixin, "PRESENCE_GATED_FILE", str(cfg))
    monkeypatch.setattr(health_mixin.indigo, "devices",
                        _Devices({d.id: d for d in devices}))
    p = bare_plugin()
    p.pluginPrefs = {}
    return p


def _car(error="unreachable"):
    return _dev(QASHQAI, "Qashqai Battery Monitor", error=error)


def _presence(clive, jane):
    return [_dev(CLIVE, "Presence - Clive", states={"presence": clive}),
            _dev(JANE, "Presence - Jane", states={"presence": jane})]


GATE = [{"id": QASHQAI, "presence_ids": [CLIVE, JANE], "name": "Qashqai"}]


def _label(out, dev_id):
    return next(d["error"] for d in out["in_error"] if d["id"] == dev_id)


class TestRule:
    """presence_gate_away and parse_presence_gated, with no Indigo in sight."""

    def test_both_home_is_not_away(self):
        load_plugin_module()
        import health_mixin
        assert health_mixin.presence_gate_away(["home", "home"]) is False

    def test_one_away_is_away(self):
        load_plugin_module()
        import health_mixin
        assert health_mixin.presence_gate_away(["away", "home"]) is True
        assert health_mixin.presence_gate_away(["home", "away"]) is True

    def test_a_missing_or_unknown_reading_is_not_away(self):
        load_plugin_module()
        import health_mixin
        assert health_mixin.presence_gate_away(["away", None]) is False
        assert health_mixin.presence_gate_away(["away", "unknown"]) is False
        assert health_mixin.presence_gate_away([]) is False

    def test_a_good_entry_parses_and_a_bad_one_is_dropped(self):
        load_plugin_module()
        import health_mixin
        by_id = health_mixin.parse_presence_gated(
            [{"id": QASHQAI, "presence_ids": [CLIVE, JANE]},
             {"id": "nope", "presence_ids": [CLIVE]},
             {"id": 5}])
        assert by_id == {QASHQAI: [CLIVE, JANE]}

    def test_a_file_that_is_not_a_list_gates_nothing(self):
        load_plugin_module()
        import health_mixin
        assert health_mixin.parse_presence_gated({"id": QASHQAI}) == {}


class TestLabel:
    """What the System Health page is told for the device while the household is out."""

    def test_car_out_with_clive_reads_out_of_contact(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("away", "home"), GATE)
        out = p._device_health()
        assert _label(out, QASHQAI) == AWAY_LABEL

    def test_car_out_with_jane_reads_out_of_contact(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("home", "away"), GATE)
        assert _label(p._device_health(), QASHQAI) == AWAY_LABEL

    def test_the_raw_error_is_still_carried(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("away", "home"), GATE)
        entry = next(d for d in p._device_health()["in_error"] if d["id"] == QASHQAI)
        assert entry["error_state"] == "unreachable"

    def test_both_home_stays_unreachable(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("home", "home"), GATE)
        assert _label(p._device_health(), QASHQAI) == "unreachable"

    def test_a_missing_presence_device_stays_unreachable(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car(), _dev(CLIVE, "Presence - Clive",
                                                       states={"presence": "away"})], GATE)
        assert _label(p._device_health(), QASHQAI) == "unreachable"

    def test_an_unknown_presence_value_stays_unreachable(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("away", ""), GATE)
        assert _label(p._device_health(), QASHQAI) == "unreachable"

    def test_an_ungated_device_keeps_its_label(self, monkeypatch, tmp_path):
        other = _dev(8001, "Garage Light", error="unreachable")
        p = _page(monkeypatch, tmp_path, [other] + _presence("away", "away"), GATE)
        assert _label(p._device_health(), 8001) == "unreachable"

    def test_no_presence_file_changes_nothing(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("away", "away"))
        assert _label(p._device_health(), QASHQAI) == "unreachable"

    def test_a_broken_presence_file_changes_nothing(self, monkeypatch, tmp_path):
        p = _page(monkeypatch, tmp_path, [_car()] + _presence("away", "away"),
                  raw="{not json")
        assert _label(p._device_health(), QASHQAI) == "unreachable"
        assert p.logger.error.called
