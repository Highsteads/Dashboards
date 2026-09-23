#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_page_frame.py
# Description: Every page's top bar matches the Energy page (v3.29.0): one
#              header markup, the shared dashboards-chrome.css linked after the
#              page's own <style>, and no page carrying its own top-bar,
#              header or nav-button rules. The pages had drifted into five to
#              nine versions of each; this keeps them from drifting again.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import re
from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[1] / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
from conftest import redirect_pages  # noqa: E402
NO_HEADER = {"demo.html", "guest.html", "setup.html"} | redirect_pages(PAGES)
FRAME = [p.name for p in sorted(PAGES.glob("*.html")) if p.name not in NO_HEADER]

HEADER_RE = re.compile(r"<header(?![^>]*modal-head)([^>]*)>(.*?)</header>", re.S)
OWN_RULE = re.compile(r"(?:^|[},]\s*)(\.topbar(?:-inner|-3col)?|\.hdr-(?:left|center|right)|\.nav-btn|header)"
                      r"(?![\w-])[^{}]*\{", re.M)


def _body(name):
    s = (PAGES / name).read_text(encoding="utf-8")
    return s, s[s.find("<body"):]


def test_the_frame_list_is_not_vacuous():
    assert len(FRAME) >= 17, FRAME


@pytest.mark.parametrize("name", FRAME)
def test_the_header_uses_the_one_markup(name):
    s, body = _body(name)
    m = HEADER_RE.search(body)
    assert m, f"{name} has no page header"
    assert 'class="topbar"' in m.group(1), f"{name}: header is not <header class=\"topbar\">"
    kids = re.findall(r'<div class="(hdr-left|hdr-center|hdr-right)"', m.group(2))
    assert kids == ["hdr-left", "hdr-center", "hdr-right"], f"{name}: {kids}"
    assert "topbar-inner" not in m.group(2) and "topbar-3col" not in m.group(2)


@pytest.mark.parametrize("name", FRAME)
def test_the_shared_frame_is_linked_after_the_page_style(name):
    s, _ = _body(name)
    head = s[:s.index("</head>")]
    link = head.find('href="dashboards-chrome.css"')
    assert link > 0, f"{name} does not link dashboards-chrome.css"
    assert link > head.rfind("</style>"), f"{name}: the shared frame must come after the page's own <style>"


@pytest.mark.parametrize("name", FRAME)
def test_no_page_keeps_its_own_frame_rules(name):
    s, _ = _body(name)
    css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", s, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    hits = []
    for m in OWN_RULE.finditer(css):
        sel = css[m.start():css.index("{", m.start())]
        if ".stale" in sel or "#" in sel or "modal" in sel:
            continue          # page state and page content stay with the page
        hits.append(" ".join(sel.strip(" },").split()))
    assert not hits, f"{name} still styles the frame itself: {hits[:5]}"
