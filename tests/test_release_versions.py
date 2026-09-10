"""Keep every user-visible Dashboards version declaration in lock-step.

Split in two on 08-09-2026, because the old single test mixed TRACKED
declarations with an UNTRACKED one and could therefore fail on the maintainer's
machine while passing on CI. v3.6.0 shipped with PLUGIN_VERSION still reading
3.5.0; CI went red at the release commit and stayed red for two days, and when
the constant was fixed the suite STILL failed locally — on the repo CLAUDE.md,
which is gitignored and which CI has never been able to see.

So: everything git tracks is asserted together and runs everywhere, and the
local-only note is a separate test that skips honestly when the file is absent.
A leg that can only fail on one machine must not be able to mask, or be masked
by, one that fails for everybody.

The plugin.py HEADER COMMENT is checked here for the first time. Release
checklist item 2 is two things — "plugin.py file header comment AND
PLUGIN_VERSION constant" — and only the constant was ever asserted, so the
header could rot unwatched. It is tracked, so it belongs in the tracked test.
"""

import plistlib
import re
from pathlib import Path

import pytest

ROOT   = Path(__file__).resolve().parents[1]
PLIST  = ROOT / "Dashboards.indigoPlugin/Contents/Info.plist"
PLUGIN = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/plugin.py"
README = ROOT / "README.md"
CLAUDE = ROOT / "CLAUDE.md"


def _plist_version():
    return plistlib.loads(PLIST.read_bytes())["PluginVersion"]


def _find(path, pattern, label):
    """The one capture of `pattern` in `path`, or a failure that NAMES the file.

    The old test asserted set equality and reported `{'3.5.0', '3.6.0'} ==
    {'3.6.0'}`, which says a version is wrong but not WHICH declaration holds
    it — that cost two rounds of hunting. Every leg is labelled here.
    """
    m = re.search(pattern, path.read_text(), re.M)
    assert m, f"{label}: no version declaration found in {path.name}"
    return label, m.group(1)


def _tracked():
    return [
        ("Info.plist PluginVersion", _plist_version()),
        _find(PLUGIN, r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', "plugin.py PLUGIN_VERSION"),
        _find(PLUGIN, r'^# Version:\s*([0-9][0-9.]*)', "plugin.py header comment"),
        _find(README, r'^\*\*Version:\*\*\s*v?([0-9][0-9.]*)', "README **Version:** header"),
        _find(README, r'^\*\*([0-9]+(?:\.[0-9]+)+)\*\*', "README newest changelog entry"),
    ]


def test_tracked_version_declarations_match():
    """Every declaration git tracks, so CI sees all of them."""
    want = _plist_version()
    wrong = [(label, got) for label, got in _tracked() if got != want]
    assert not wrong, (
        f"Info.plist says {want}; these disagree: "
        + ", ".join(f"{label}={got}" for label, got in wrong))


def test_the_tracked_scan_is_not_vacuous():
    """A pattern that matches nothing would make the test above pass silently."""
    legs = _tracked()
    assert len(legs) == 5, legs
    assert all(v for _, v in legs), legs


def test_repo_claude_md_matches_when_present():
    """The maintainer's own note. Gitignored, so CI never sees it — which is
    exactly why it is not allowed to sit in the tracked test."""
    if not CLAUDE.exists():
        pytest.skip("repo CLAUDE.md is gitignored — local-only leg, not on CI")
    label, got = _find(CLAUDE, r'^- \*\*Version:\*\*\s*v?([0-9][0-9.]*)', "CLAUDE.md")
    want = _plist_version()
    assert got == want, f"repo CLAUDE.md says {got}, Info.plist says {want}"
