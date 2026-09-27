#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_sigen_paths.py
# Description: Every SigenEnergyManager path a page asks the sigenApi proxy for
#              must be on the proxy's allow-list. A path missing from it is
#              refused with a 400, and the pages treat any refusal as "no data"
#              and hide the card — so the fault looks exactly like an older
#              SigenEnergyManager, and nothing says otherwise (v3.51.0).
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
import ast
import re
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
PLUGIN = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/plugin.py"


def _allowed():
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "_SIGEN_ALLOWED_PATHS" for t in node.targets):
            return set(ast.literal_eval(node.value.args[0]))
    raise AssertionError("_SIGEN_ALLOWED_PATHS not found")


def _asked_for():
    asked = {}
    for page in PAGES.glob("*.html"):
        for m in re.finditer(r"sigenFetch\(\s*['\"]([^'\"]+)['\"]", page.read_text(encoding="utf-8")):
            asked.setdefault(m.group(1), set()).add(page.name)
    return asked


def test_every_path_a_page_asks_for_is_allowed():
    allowed = _allowed()
    asked = _asked_for()
    assert asked, "found no sigenFetch calls — the pattern is out of date"
    missing = {p: sorted(pages) for p, pages in asked.items() if p not in allowed}
    assert not missing, f"asked for but not allowed: {missing}"


def test_the_day_patterns_path_is_allowed():
    assert "day-patterns" in _allowed()
