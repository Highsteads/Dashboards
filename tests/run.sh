#! /usr/bin/env bash
# Filename:    run.sh
# Description: Single gate for the Dashboards contract-test suite — runs the
#              Python unit tests (pytest) and EVERY tests/*.mjs node test.
#              Exit 0 only if all pass. Run from anywhere: tests/run.sh
# Author:      CliveS & Claude Fable 5; Claude Opus 5 (1.1)
# Date:        30-08-2026
# Version:     1.2
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."

echo "== pytest =="
python3 -m pytest tests -q

echo
echo "== pytest (the companion scripts this repo SHIPS) =="
# A gate can only cover what it enumerates. scripts/ holds code other people install, and
# nothing here ran a line of it until v3.11.0.
python3 -m pytest scripts -q

echo
echo "== node (every tests/*.mjs) =="
# GLOB, never a hand-written list. Six .mjs tests had accumulated that this
# gate never ran — including the two covering the hub Favourites card — so a
# clean local run said nothing about them while CI (which already globs) did
# run them. A gate can only cover what it enumerates, so it enumerates itself.
for f in tests/*.mjs; do
    echo "-- $(basename "$f")"
    node "$f"
done

echo
echo "== compileall + ruff (what CI runs; two lines each, never cmd && echo under set -e) =="
python3 -m compileall -q "Dashboards.indigoPlugin/Contents/Server Plugin"
echo "  compileall ok"
python3 -m ruff check .
echo "  ruff ok"

echo
echo "All contract tests passed."
