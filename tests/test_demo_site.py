#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_demo_site.py
# Description: The online demo (docs/demo/, published on the docs site from
#              3.39.0). It is a COPY of the bundle's pages, so it rots the
#              moment a page changes without tools/build_demo_site.sh being
#              run — this fails first. It also holds the privacy rules the
#              canned endpoint answers were cut down by (tools/make_demo_api.py),
#              and checks the hosted config only names devices the fixtures
#              actually have.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.1 (demo files must be TRACKED, not just on disk)
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages"
DEMO = ROOT / "docs/demo"
API = PAGES / "demo-data/api"

pytestmark = pytest.mark.skipif(not DEMO.is_dir(), reason="docs/demo has not been built")


def _shipped():
    for p in sorted(PAGES.rglob("*")):
        if p.is_file() and p.suffix in {".html", ".js", ".css", ".png", ".json"} and p.name != "config.js":
            yield p.relative_to(PAGES)


@pytest.mark.parametrize("rel", list(_shipped()), ids=str)
def test_the_demo_copy_matches_the_bundle(rel):
    copy = DEMO / rel
    assert copy.is_file(), f"docs/demo/{rel} is missing — run tools/build_demo_site.sh"
    assert copy.read_bytes() == (PAGES / rel).read_bytes(), \
        f"docs/demo/{rel} is behind the bundle — run tools/build_demo_site.sh"


def test_the_plugin_files_a_page_fetches_are_there():
    for name in ("rooms.json", "scenes.json", "weather.json", "config.js", "demo-cam.svg"):
        assert (DEMO / name).is_file(), name


def test_the_demo_files_are_tracked_not_just_present():
    """.gitignore hides every rooms.json, weather.json and config.js, because
    on a live install they carry the house's layout and API key. The demo's
    copies were present on disk and passing here while CI, on a clean
    checkout, had none of them (3.39.0)."""
    try:
        out = subprocess.run(["git", "ls-files", "docs/demo"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    tracked = set(out)
    for p in sorted(DEMO.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(ROOT))
            assert rel in tracked, f"{rel} is on disk but not in git — check .gitignore"


def test_the_docs_site_publishes_the_demo():
    cfg = (ROOT / "docs/_config.yml").read_text(encoding="utf-8")
    block = cfg.split("exclude:", 1)[1] if "exclude:" in cfg else ""
    assert not re.search(r"^\s*-\s*demo\s*$", block, re.M), "docs/_config.yml still excludes demo/"


def test_the_hosted_config_names_only_fixture_devices():
    cfg = (DEMO / "config.js").read_text(encoding="utf-8")
    assert 'sessionStorage.setItem("dash_demo", "1")' in cfg
    ids = {d["id"] for d in json.loads((PAGES / "demo-data/devices.json").read_text(encoding="utf-8"))}
    body = cfg.split("window.INDIGO_CONFIG = ", 1)[1].split(";\nwindow.INDIGO_CONFIG_SOURCE", 1)[0]
    conf = json.loads(body)
    assert conf["sigenDeviceId"] in ids
    named = [f.get(k) for f in conf["favourites"] for k in ("id", "lockId") if f.get(k)]
    assert named and all(i in ids for i in named), [i for i in named if i not in ids]
    assert "mjpeg" not in cfg.lower()


def _load(name):
    return json.loads((API / f"{name}.json").read_text(encoding="utf-8"))


def test_the_timeline_carries_no_record_of_who_was_home():
    lanes = {ln["key"] for ln in _load("timelineDay")["lanes"]}
    assert lanes and not lanes & {"presence", "doors"}, lanes
    assert not (API / "presenceData.json").exists(), "the Nights view must not be captured"


def test_no_money_account_or_outage_history_is_published():
    status = (API / "sigenApi-status.json").read_text(encoding="utf-8")
    assert not re.search(r'"balance_gbp":\s*[0-9]', status)
    assert _load("sigenApi-status")["power_cut"]["events"] == []
    for f in API.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:10|192\.168)\.\d+\.\d+\b", text), f.name
        assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text), f.name
        assert not re.search(r'"(?:mpan|mprn|account[a-z_]*|serial[a-z_]*)":\s*"', text, re.I), f.name


def test_the_diary_is_invented_and_names_no_door_codes():
    feed = _load("activityFeed")
    assert feed["automation"]["codes"] == []
    assert _load("logErrors")["feed"]["rows"], "an empty log would not show the page working"


def test_demo_mode_answers_before_the_liveness_gate():
    """A static host has no plugin to be alive, so the gate would call every
    demo endpoint 'restarting'."""
    src = (PAGES / "dashboards-ui.js").read_text(encoding="utf-8")
    fn = src[src.index("async function message("):]
    assert fn.index("if (key === 'demo') return demoMessage(name, body);") < fn.index("DashGate")


def test_the_demo_stills_location_is_invented_not_captured():
    """The real cameraStills reply names this install's private stills folder
    (stills-<token>), which exists only so that nobody without the key can
    find the pictures. The demo answers with its placeholder instead."""
    reply = _load("cameraStills")
    assert reply["ok"] is True
    for key in ("imagePattern", "thumbPattern"):
        assert "stills-" not in reply[key], reply
        assert (DEMO / reply[key].replace("{host}", "x")).is_file(), reply[key]
