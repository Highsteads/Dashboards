#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_action_note_targets.py
# Description: A DashAction.note(key, ...) is painted only on an element that
#              carries data-dsh-act-key with that key, and only on a page that
#              loads dashboards-action.js (v3.25.0). The room page sent colour
#              and "No confirmation" notes to keys no element carried, and the
#              Active page never loaded the script, so every one of those
#              failure messages vanished. This cross-checks every page.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.1 (v3.37.0: notes and keys in dashboards-controls.js count for every page that loads it)
import re
from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[1] / "Dashboards.indigoPlugin/Contents/Resources/static/pages"

NOTE_RE = re.compile(r"""DashAction\.note\(\s*["']([a-z]+):""")
KEY_RE  = re.compile(r"""data-dsh-act-key=["']([a-z]+):""")


SHARED = "dashboards-controls.js"


def _source(page):
    """The page plus the shared tile module when it loads it: the toggle and
    setpoint notes, and the zone tile's key, live in that module now."""
    src = (PAGES / page).read_text(encoding="utf-8")
    if SHARED in src:
        src += (PAGES / SHARED).read_text(encoding="utf-8")
    return src


def _pages_with_notes():
    return sorted(p.name for p in PAGES.glob("*.html") if NOTE_RE.search(_source(p.name)))


def test_some_pages_send_notes():
    assert len(_pages_with_notes()) >= 2, _pages_with_notes()


@pytest.mark.parametrize("page", _pages_with_notes())
def test_every_note_has_somewhere_to_land(page):
    src = _source(page)
    assert "dashboards-action.js" in src, f"{page} sends DashAction notes but never loads dashboards-action.js"
    sent = set(NOTE_RE.findall(src))
    keyed = set(KEY_RE.findall(src))
    missing = sent - keyed
    assert not missing, f"{page} sends notes to key prefixes no element carries: {sorted(missing)}"


@pytest.mark.parametrize("page", sorted(p.name for p in PAGES.glob("*.html")
                                        if SHARED in p.read_text(encoding="utf-8")))
def test_the_shared_tile_module_loads_after_dashaction(page):
    """DashTile reads on/off through DashAction.truthy, so a page that loads
    it first gets null for every state and draws every tile as unknown."""
    src = (PAGES / page).read_text(encoding="utf-8")
    assert "dashboards-action.js" in src, page
    assert src.index("dashboards-action.js") < src.index(SHARED), page
