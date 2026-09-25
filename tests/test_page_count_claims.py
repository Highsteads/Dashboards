#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_page_count_claims.py
# Description: Every place the docs say how many pages the plugin ships agrees
#              with the pages actually in the bundle (v3.26.0). Retiring
#              webrtc-test.html took the count from 27 to 26 in three places by
#              hand; the next change should not rely on remembering them.
#              1.1 (3.46.0): counts written as WORDS too. The README's "Twenty-
#              two pages you use, plus five" said 27 for months while the
#              digits beside it said 21, because only digits were checked.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.1
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"


def test_every_page_count_claim_matches_the_bundle():
    from conftest import redirect_pages
    n = len(set(p.name for p in PAGES.glob("*.html")) - redirect_pages(PAGES))   # a redirect is not a page
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs/index.md").read_text(encoding="utf-8")
    claims = {
        "README badge": re.search(r"badge/pages-(\d+)-", readme),
        "README prose": re.search(r"every one of the (\d+) pages", readme),
        "docs/index.md": re.search(r"each of the (\d+) pages", index),
    }
    missing = [k for k, m in claims.items() if not m]
    assert not missing, f"no page count found in: {missing}"
    wrong = {k: int(m.group(1)) for k, m in claims.items() if int(m.group(1)) != n}
    assert not wrong, f"the bundle ships {n} pages; these say otherwise: {wrong}"


_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
          "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
          "eighteen", "nineteen"]
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}


def words_to_int(text):
    """'Twenty-two' -> 22, 'five' -> 5, '21' -> 21; None if it is not a number."""
    t = str(text).strip().lower().replace(" ", "-")
    if t.isdigit():
        return int(t)
    if t in _UNITS:
        return _UNITS.index(t)
    head, _, tail = t.partition("-")
    if head in _TENS and (not tail or tail in _UNITS[1:10]):
        return _TENS[head] + (_UNITS.index(tail) if tail else 0)
    return None


def test_the_number_words_helper():
    assert words_to_int("Twenty-two") == 22 and words_to_int("five") == 5
    assert words_to_int("Sixteen") == 16 and words_to_int("21") == 21
    assert words_to_int("thirty") == 30 and words_to_int("pages") is None


_WORD = r"([A-Za-z]+(?:-[A-Za-z]+)?|\d+)"


def test_every_split_count_in_words_adds_up_to_the_bundle():
    """"<n> pages you use, plus <m> that hold the whole thing together", in
    words or digits, wherever it is written."""
    from conftest import redirect_pages
    n = len(set(p.name for p in PAGES.glob("*.html")) - redirect_pages(PAGES))
    found = {}
    for rel in ("README.md", "docs/pages/index.md", "docs/index.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(_WORD + r" pages you use,\s+plus\s+" + _WORD, text):
            a, b = words_to_int(m.group(1)), words_to_int(m.group(2))
            assert a is not None and b is not None, f"{rel}: cannot read {m.group(0)!r}"
            found[rel] = a + b
    assert "README.md" in found and "docs/pages/index.md" in found, found
    wrong = {k: v for k, v in found.items() if v != n}
    assert not wrong, f"the bundle ships {n} pages; these add up otherwise: {wrong}"
