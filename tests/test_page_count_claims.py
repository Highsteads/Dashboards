#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_page_count_claims.py
# Description: Every place the docs say how many pages the plugin ships agrees
#              with the pages actually in the bundle (v3.26.0). Retiring
#              webrtc-test.html took the count from 27 to 26 in three places by
#              hand; the next change should not rely on remembering them.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"


def test_every_page_count_claim_matches_the_bundle():
    n = len(list(PAGES.glob("*.html")))
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
