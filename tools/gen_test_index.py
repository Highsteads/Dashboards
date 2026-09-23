#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    gen_test_index.py
# Description: Rebuild the Coverage table in tests/README.md from each test
#              file's own "Description:" header (or docstring), so the index
#              cannot fall behind the files. --check exits 1 when it has.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import re
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"
README = TESTS / "README.md"
HEAD = "| File | Locks |\n|------|-------|\n"


def first_line(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Description:\s*(.+)", text)
    if not m:
        m = re.search(r'^"""(.+?)$', text, re.M)
    if not m:
        # A leading block comment: /* ... */ or // lines.
        m = re.search(r"\A\s*(?:/\*+|//)\s*(.+)", text)
    line = (m.group(1) if m else "").strip().rstrip("\\").replace("|", "/")
    return line


def table():
    files = sorted(p for p in TESTS.iterdir()
                   if p.is_file() and p.name.startswith("test_") and p.suffix in (".py", ".mjs"))
    return HEAD + "".join(f"| `{p.name}` | {first_line(p)} |\n" for p in files)


def rebuilt():
    s = README.read_text(encoding="utf-8")
    i = s.index(HEAD)
    j = i + len(HEAD)
    while j < len(s) and s[j] == "|":
        j = s.index("\n", j) + 1
    return s[:i] + table() + s[j:]


if __name__ == "__main__":
    new = rebuilt()
    if "--check" in sys.argv:
        sys.exit(0 if new == README.read_text(encoding="utf-8") else 1)
    README.write_text(new, encoding="utf-8")
    print("tests/README.md rebuilt")
