#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_door_tile_compact_colour.py
# Description: A door tile beside a room's cameras shows its state colour.
#              Until 3.54.1 its frame kept a white background over the red,
#              blue or amber, so the white state words could not be read.
# Author:      CliveS & Claude Opus 5.5
# Date:        28-09-2026
# Version:     1.0
import re
from pathlib import Path

ROOM = (Path(__file__).resolve().parents[1]
        / "Dashboards.indigoPlugin/Contents/Resources/static/pages/room.html").read_text(encoding="utf-8")
COLOURED = ("open", "opening", "closing", "moving", "stuck")


def _rules():
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", ROOM, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        yield [x.strip() for x in sel.split(",")], body


def test_every_coloured_state_clears_the_compact_frame():
    cleared = set()
    for sels, body in _rules():
        if re.search(r"background\s*:\s*transparent", body):
            for sel in sels:
                m = re.fullmatch(r"\.door-card-compact\.door-state-(\w+)\s+\.door-status-frame", sel)
                if m:
                    cleared.add(m.group(1))
    missing = [s for s in COLOURED if s not in cleared]
    assert not missing, f"the compact door frame stays white over these states: {missing}"


def test_the_closed_state_keeps_its_white_frame():
    for sels, body in _rules():
        for sel in sels:
            assert not re.fullmatch(r"\.door-card-compact\.door-state-closed\s+\.door-status-frame", sel)
