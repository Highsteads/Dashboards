#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_no_orphan_pages.py
# Description: Every page can be reached from another page (v3.33.0). The
#              Graphs page shipped for weeks with nothing linking to it; the
#              spring-clean review found it by reading. A page nobody can reach
#              is either dead or lost, and both are worth knowing about.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
from pathlib import Path

from conftest import redirect_pages

PAGES = Path(__file__).resolve().parents[1] / "Dashboards.indigoPlugin/Contents/Resources/static/pages"

# Reached from outside the pages: the home page itself, a paired guest's QR
# code, a one-time setup link, and the docs' demo link.
ENTRY_POINTS = {"index.html", "guest.html", "setup.html", "demo.html"}


def _sources():
    return {p.name: p.read_text(encoding="utf-8")
            for p in PAGES.iterdir() if p.suffix in (".html", ".js")}


def test_every_page_is_linked_from_another():
    src = _sources()
    pages = sorted(p.name for p in PAGES.glob("*.html"))
    skip = ENTRY_POINTS | redirect_pages(PAGES)
    orphans = [page for page in pages if page not in skip
               and not any(page in text for name, text in src.items() if name != page)]
    assert not orphans, f"nothing links to: {orphans}"


def test_the_check_can_see_a_page():
    assert len([p for p in PAGES.glob("*.html")]) >= 20
