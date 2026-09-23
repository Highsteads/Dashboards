#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_repo_notes_size.py
# Description: The repo's CLAUDE.md holds CURRENT facts only. It had grown to
#              289 KB, 92% of it a release log that docs/changelog.md and git
#              already hold, and it was rewritten to under 32 KB on
#              23-09-2026. This keeps it there. The file is gitignored, so the
#              test skips wherever it is absent (CI).
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
from pathlib import Path

import pytest

NOTES = Path(__file__).resolve().parents[1] / "CLAUDE.md"
LIMIT = 32_000


@pytest.mark.skipif(not NOTES.is_file(), reason="no local CLAUDE.md here (it is gitignored)")
def test_repo_notes_stay_short():
    size = NOTES.stat().st_size
    assert size <= LIMIT, (
        f"CLAUDE.md is {size:,} bytes (limit {LIMIT:,}). Keep current facts only; the release "
        f"log belongs in docs/changelog.md and git.")


@pytest.mark.skipif(not NOTES.is_file(), reason="no local CLAUDE.md here (it is gitignored)")
def test_repo_notes_carry_no_release_log():
    text = NOTES.read_text(encoding="utf-8")
    for marker in ("**Superseded:**", "**Version (prior):**", "**Previous:**"):
        assert marker not in text, f"CLAUDE.md has a release-log entry ({marker}) again"
