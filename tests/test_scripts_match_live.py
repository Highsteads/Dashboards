#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_scripts_match_live.py
# Description: The companion scripts this repo ships in scripts/ must be the
#              same files as the live ones in Python Scripts/ (v3.25.0). The
#              live folder is the owner; the repo copy is what GitHub users get.
#              Four had drifted: Log_Error_Watch was 1.5 here against 1.7 live
#              and still carried the Web Server mute removed on 18-Sep-2026,
#              so a new user got an Alerts page expecting a script they did not
#              have. Skips honestly where the live folder is absent (CI).
#              To fix a failure: copy the live file over the repo one.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1] / "scripts"
LIVE = Path("/Library/Application Support/Perceptive Automation/Python Scripts")

SHIPPED = sorted(p.name for p in REPO.glob("*.py") if not p.name.startswith("test_"))


def test_the_shipped_list_is_not_vacuous():
    assert len(SHIPPED) >= 7, SHIPPED


@pytest.mark.skipif(not LIVE.is_dir(), reason="no live Python Scripts folder here (CI)")
@pytest.mark.parametrize("name", SHIPPED)
def test_repo_copy_matches_live(name):
    live = LIVE / name
    if not live.exists():
        pytest.skip(f"{name} is not installed on this machine")
    assert (REPO / name).read_bytes() == live.read_bytes(), (
        f"scripts/{name} differs from the live copy — copy the live file into the repo")
