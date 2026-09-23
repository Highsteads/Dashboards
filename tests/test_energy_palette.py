#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_energy_palette.py
# Description: The five semantic energy colours (3.42.0). They were re-stepped
#              so a colour-blind reader can tell every pair apart, but the
#              fault that actually shipped was not in the theme at all:
#              dashboards-chrome.css overrode --solar with a dark text brown on
#              twenty pages, and that brown sat 3.6 from import red under
#              protanopia. These tests keep --solar a SERIES colour owned by
#              the theme, and keep text on its own token.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import re
from pathlib import Path

PAGES = Path(__file__).resolve().parents[1] / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
THEME = PAGES / "dashboards-theme.css"
SERIES = ("--solar", "--bat", "--grid-imp", "--grid-exp", "--home-load")

# Measured 23-09-2026 with the dataviz palette validator, every pair:
# light worst CVD 9.2 on #fcfcfb/#ffffff/#f3f5f7; dark worst 8.5 on
# #1c1c1e/#1b222b/#11151b. Re-measure before changing any of these.
LIGHT = {"--solar": "#d98e04", "--bat": "#1f8a5c", "--grid-imp": "#e5352b",
         "--grid-exp": "#0a6fe0", "--home-load": "#b8409e"}
DARK = {"--solar": "#c77912", "--bat": "#27a36c", "--grid-imp": "#d02c30",
        "--grid-exp": "#2f8cff", "--home-load": "#d25bc0"}


def _blocks(css):
    """(light :root body, dark :root body) of the theme file."""
    light = css[css.index(":root"):css.index("@media (prefers-color-scheme: dark)")]
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    return light, dark


def _tokens(block):
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6})", block))


def test_the_theme_carries_the_measured_palette_in_both_modes():
    light, dark = _blocks(THEME.read_text(encoding="utf-8"))
    lt, dt = _tokens(light), _tokens(dark)
    for tok in SERIES:
        assert lt.get(tok, "").lower() == LIGHT[tok], f"light {tok} is {lt.get(tok)}"
        assert dt.get(tok, "").lower() == DARK[tok], f"dark {tok} is {dt.get(tok)}"


def test_text_has_its_own_solar_token_in_both_modes():
    light, dark = _blocks(THEME.read_text(encoding="utf-8"))
    assert "--solar-text" in _tokens(light) and "--solar-text" in _tokens(dark)


def test_no_other_stylesheet_or_page_redefines_a_series_colour():
    offenders = []
    for f in sorted(PAGES.glob("*.css")) + sorted(PAGES.glob("*.html")):
        if f == THEME:
            continue
        text = f.read_text(encoding="utf-8")
        for tok in SERIES:
            if re.search(re.escape(tok) + r"\s*:", text):
                offenders.append(f"{f.name}: {tok}")
    assert not offenders, "series colours belong to the theme alone: " + ", ".join(offenders)


def test_text_never_wears_the_solar_series_colour():
    offenders = []
    for f in sorted(PAGES.glob("*.css")) + sorted(PAGES.glob("*.html")) + sorted(PAGES.glob("*.js")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![-\w])color\s*:\s*var\(--solar[,)]", line):
                offenders.append(f"{f.name}:{n}")
    assert not offenders, "use var(--solar-text) for text: " + ", ".join(offenders)
