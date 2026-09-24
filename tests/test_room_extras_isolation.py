#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_room_extras_isolation.py
# Description: One room's roomExtras entry of the wrong shape must cost that
#              room its extras and nothing more (v3.25.0). It used to raise out
#              of _build_rooms_json every 30 s, so rooms.json went stale for
#              every room in the house. The Settings save now refuses such an
#              entry up front as well.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
from conftest import bare_plugin

SECTIONS = ("lights", "motion", "radiators", "windows", "sensors", "extras")


def _room(**kw):
    r = {k: [] for k in SECTIONS}
    r.update(kw)
    return r


def _plugin(extras):
    p = bare_plugin()
    p.room_extras = extras
    return p


def test_a_bad_room_does_not_stop_the_good_ones():
    p = _plugin({
        "Kitchen": ["not", "an", "object"],                 # wrong shape entirely
        "Hall": {"hideDeviceIds": [[1, 2]]},                # unhashable -> raises
        "Lounge": {"hideDeviceIds": [11], "plugs": [12]},   # fine
    })
    rooms = {"Kitchen": _room(lights=[1]), "Hall": _room(lights=[3]),
             "Lounge": _room(lights=[11, 12, 13])}
    p._merge_room_extras(rooms)
    assert rooms["Lounge"]["lights"] == [13]
    assert rooms["Lounge"]["plugs"] == [12]
    assert rooms["Kitchen"]["lights"] == [1]                 # untouched, not lost
    assert p.logger.warning.call_count == 2
    said = " ".join(str(c.args[0]) for c in p.logger.warning.call_args_list)
    assert "Kitchen" in said and "Hall" in said


def test_the_warning_is_once_per_fault_not_every_build():
    p = _plugin({"Kitchen": 5})
    for _ in range(3):
        p._merge_room_extras({"Kitchen": _room()})
    assert p.logger.warning.call_count == 1


def test_include_and_hide_still_work():
    p = _plugin({"Garage": {"include": {"sensors": [7]}, "hideDeviceIds": [8]}})
    rooms = {"Garage": _room(sensors=[8], extras=[7])}
    p._merge_room_extras(rooms)
    assert rooms["Garage"]["sensors"] == [7]
    assert rooms["Garage"]["extras"] == []


def test_a_rebuilt_json_file_is_written_only_when_it_changes(tmp_path):
    """v3.27.0: rooms.json and scenes.json were rewritten every 30 s because
    the _writeTs inside them always moved. Now only a real change writes."""
    p = bare_plugin()
    writes = []
    p._write_atomic = lambda path, data: (writes.append(path), open(path, "wb").write(data))
    path = str(tmp_path / "rooms.json")
    assert p._write_json_if_changed(path, {"_writeTs": 1, "rooms": {"Hall": [1]}}) is True
    assert p._write_json_if_changed(path, {"_writeTs": 2, "rooms": {"Hall": [1]}}) is False
    assert p._write_json_if_changed(path, {"_writeTs": 3, "rooms": {"Hall": [1, 2]}}) is True
    import os
    os.remove(path)                                   # someone deleted it
    assert p._write_json_if_changed(path, {"_writeTs": 4, "rooms": {"Hall": [1, 2]}}) is True
    assert len(writes) == 3


def test_a_deleted_pinned_device_does_not_stop_sorting(monkeypatch):
    """Review 24-09-2026 [25]: the sort key raised on an id whose device had
    been deleted, and one try around every room swallowed it, so that room and
    every room after it lost their order with nothing in the log."""
    from types import SimpleNamespace
    import plugin as mod
    devs = {1: SimpleNamespace(name="Zeta"), 2: SimpleNamespace(name="Alpha"),
            3: SimpleNamespace(name="Yew"), 4: SimpleNamespace(name="Beech")}
    monkeypatch.setattr(mod.indigo, "devices", devs)
    p = _plugin({})
    rooms = {"Hall": _room(lights=[1, 999, 2]),        # 999 was deleted
             "Lounge": _room(lights=[3, 4])}
    p._sort_room_sections(rooms)
    assert rooms["Hall"]["lights"] == [2, 1, 999]     # the missing id goes last
    assert rooms["Lounge"]["lights"] == [4, 3]        # a later room still sorts
    assert p.logger.warning.call_count == 0


def test_a_room_whose_sort_fails_is_warned_and_the_rest_still_sort(monkeypatch):
    from types import SimpleNamespace
    import plugin as mod
    monkeypatch.setattr(mod.indigo, "devices",
                        {3: SimpleNamespace(name="Yew"), 4: SimpleNamespace(name="Beech")})
    p = _plugin({})
    rooms = {"Hall": {"lights": None}, "Lounge": _room(lights=[3, 4])}
    p._sort_room_sections(rooms)
    assert rooms["Lounge"]["lights"] == [4, 3]
    assert p.logger.warning.call_count == 1
    assert "Hall" in str(p.logger.warning.call_args.args[0])
