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


def _rules():
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", ROOM, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        yield [x.strip() for x in sel.split(",")], body


WANT = {"open": "--bad", "opening": "--accent", "closing": "--accent",
        "moving": "--accent", "stuck": "--warn"}


def test_every_coloured_state_paints_the_compact_frame():
    # The colour must be on the FRAME: the card's own later background rule
    # beats .door-state-* on the card, and the frame sits on top of it anyway,
    # so a colour anywhere else is covered twice.
    painted = {}
    for sels, body in _rules():
        m = re.search(r"background\s*:\s*var\((--[\w-]+)\)", body)
        if not m:
            continue
        for sel in sels:
            k = re.fullmatch(r"\.door-card-compact\.door-state-(\w+)\s+\.door-status-frame", sel)
            if k:
                painted[k.group(1)] = m.group(1)
    assert painted == WANT, painted


def test_the_closed_state_keeps_its_white_frame():
    for sels, body in _rules():
        for sel in sels:
            assert not re.fullmatch(r"\.door-card-compact\.door-state-closed\s+\.door-status-frame", sel)
