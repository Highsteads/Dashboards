#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_test_index.py
# Description: tests/README.md lists every test file (v3.25.0). It had fallen
#              33 files behind while docs/architecture.md said it listed them
#              all. Fix a failure with: python3 tools/gen_test_index.py
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_index_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools/gen_test_index.py"), "--check"])
    assert r.returncode == 0, "tests/README.md is out of date — run: python3 tools/gen_test_index.py"
