#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    preflight.py
# Description: Release preflight sweep for the Dashboards plugin bundle.
#              Lints every <script> block in every HTML page, validates
#              JSON files, syntax-checks plugin.py, and looks for stale
#              references to deleted legacy pages. Run before every commit
#              that touches static assets.
# Author:      CliveS & Claude Opus 4.7
# Date:        27-05-2026
# Version:     1.0
#
# Usage:       python3 tools/preflight.py
# Exit code:   0 if everything passes, 1 if any check fails.
#
# Why this script exists: Dashboards v1.18.0 shipped with 51 lines of
# room.html code accidentally pasted inside ecowitt.html. The JS parser
# died before start() ran and the page hung on "Connecting…" forever.
# node --check on each <script> block would have caught that in 50ms.
# Belt-and-braces sweep below covers all the other ways a static asset
# can ship broken.

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile

REPO_ROOT  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE     = os.path.join(REPO_ROOT, "Dashboards.indigoPlugin")
PAGES_DIR  = os.path.join(BUNDLE, "Contents", "Resources", "static", "pages")
PLUGIN_PY  = os.path.join(BUNDLE, "Contents", "Server Plugin", "plugin.py")

# Legacy room HTML files removed in v1.19.0. Any reference to these from
# inside the bundle is a leftover bug — every link should now point at
# room.html?room=<Name>.
LEGACY_ROOM_PAGES = (
    "bathroom.html",     "bedroom-1.html",  "bedroom-2.html",
    "bedroom-3.html",    "conservatory.html","dining-room.html",
    "drive.html",        "en-suite.html",   "garage.html",
    "garden.html",       "hall.html",       "kitchen.html",
    "living-room.html",  "utility-room.html",
)

# Bookkeeping for the final summary.
_passes  = 0
_fails   = 0
_section = ""


def section(name: str) -> None:
    global _section
    _section = name
    print(f"\n=== {name} ===")


def ok(msg: str) -> None:
    global _passes
    _passes += 1
    print(f"  OK    {msg}")


def fail(msg: str, detail: str = "") -> None:
    global _fails
    _fails += 1
    print(f"  FAIL  {msg}")
    if detail:
        for line in detail.splitlines()[:6]:
            print(f"        {line}")


# ─── 1. Every <script> block parses as JS ─────────────────────────────
section("JS syntax check (every <script> block)")
script_re = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL)
total_blocks = 0
for path in sorted(glob.glob(os.path.join(PAGES_DIR, "*.html"))):
    name = os.path.basename(path)
    html = open(path).read()
    blocks = script_re.findall(html)
    bad = 0
    for i, src in enumerate(blocks):
        if not src.strip():
            continue
        total_blocks += 1
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write(src)
            tmp = f.name
        try:
            r = subprocess.run(
                ["node", "--check", tmp],
                capture_output=True, text=True, timeout=15,
            )
        except FileNotFoundError:
            print("  SKIP  node not installed — install it for this check to run")
            break
        finally:
            os.unlink(tmp)
        if r.returncode:
            bad += 1
            fail(f"{name}  script#{i+1} ({len(src)} chars)", r.stderr)
    if bad == 0 and blocks:
        ok(f"{name}  ({len(blocks)} block(s))")

# ─── 2. Standalone JS files ────────────────────────────────────────────
section("JS syntax check (standalone .js files)")
for js in sorted(glob.glob(os.path.join(PAGES_DIR, "*.js"))):
    try:
        r = subprocess.run(["node", "--check", js],
                           capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        print("  SKIP  node not installed")
        break
    if r.returncode == 0:
        ok(os.path.basename(js))
    else:
        fail(os.path.basename(js), r.stderr)

# ─── 3. Bundled JSON files ─────────────────────────────────────────────
section("JSON validity")
for jsonf in sorted(glob.glob(os.path.join(PAGES_DIR, "*.json"))):
    try:
        json.load(open(jsonf))
        ok(os.path.basename(jsonf))
    except Exception as exc:
        fail(os.path.basename(jsonf), str(exc))

# ─── 4. plugin.py compiles ─────────────────────────────────────────────
section("plugin.py syntax")
try:
    subprocess.check_output([sys.executable, "-m", "py_compile", PLUGIN_PY],
                            stderr=subprocess.STDOUT)
    ok("plugin.py compiles")
except subprocess.CalledProcessError as exc:
    fail("plugin.py", exc.output.decode("utf-8", "replace"))

# ─── 5. HTML well-formedness (matching <script>/</script>) ────────────
section("HTML script-tag balance")
for path in sorted(glob.glob(os.path.join(PAGES_DIR, "*.html"))):
    name = os.path.basename(path)
    html = open(path).read()
    opens  = len(re.findall(r"<script(?:\s|>)", html))
    closes = len(re.findall(r"</script>", html))
    if opens != closes:
        fail(name, f"{opens} <script openers vs {closes} </script> closers")
    elif re.search(r"</script[^>]", html):
        fail(name, "malformed </script> tag")
    else:
        ok(f"{name}  ({opens} pair(s))")

# ─── 6. Stale references to deleted legacy pages ──────────────────────
section("Stale references to deleted legacy room pages")
search_exts = ("*.html", "*.js", "*.json", "*.py", "*.md")
strays = 0
for legacy in LEGACY_ROOM_PAGES:
    # Walk the bundle looking for href="legacy.html" or 'legacy.html' or /legacy.html
    needle = re.compile(rf'(?:["\'/]){re.escape(legacy)}\b')
    for root, _dirs, files in os.walk(BUNDLE):
        for fn in files:
            if not any(fn.endswith(ext.lstrip("*")) for ext in search_exts):
                continue
            fp = os.path.join(root, fn)
            try:
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if needle.search(text):
                strays += 1
                fail(f"{legacy} referenced by", fp)
if strays == 0:
    ok("no stray references to deleted legacy pages")

# ─── Final summary ────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"Preflight: {_passes} pass / {_fails} fail "
      f"({total_blocks} <script> blocks linted)")
print("=" * 60)
sys.exit(0 if _fails == 0 else 1)
