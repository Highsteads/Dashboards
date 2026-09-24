#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_go2rtc_orphan_guard.py
# Description: The go2rtc orphan guard finds an orphan whatever binary ran it
#              and whichever Indigo version's folder held its config, and
#              checks the port was freed (review 24-09-2026 [37]). It matched
#              the exact current binary and config paths, so an orphan from a
#              binary-path change or an Indigo upgrade kept the ports.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import re
import urllib.error
import urllib.request

from conftest import bare_plugin

PA = "/Library/Application Support/Perceptive Automation"


def _p():
    p = bare_plugin()
    p.pluginId = "com.clives.indigoplugin.dashboards"
    return p


def test_the_pattern_follows_the_plugin_not_the_paths():
    pat = re.compile(_p()._go2rtc_orphan_pattern())
    ours = [
        f"/Users/x/bin/go2rtc -config {PA}/Indigo 2025.2/Preferences/Plugins/"
        f"com.clives.indigoplugin.dashboards/go2rtc/go2rtc.yaml",
        f"/opt/homebrew/bin/go2rtc -config {PA}/Indigo 2026.1/Preferences/Plugins/"
        f"com.clives.indigoplugin.dashboards/go2rtc/go2rtc.yaml",
    ]
    for cmd in ours:
        assert pat.search(cmd), cmd
    for other in (
        f"/opt/homebrew/bin/go2rtc -config {PA}/Indigo 2025.2/Preferences/Plugins/"
        f"com.other.plugin/go2rtc/go2rtc.yaml",
        "/opt/homebrew/bin/go2rtc -config /Users/x/frigate/go2rtc.yaml",
        f"go2rtc -config {PA}/Indigo 2025.2/Preferences/Plugins/"
        f"comXcliveslindigopluginXdashboards/go2rtc/go2rtc.yaml",
    ):
        assert not pat.search(other), other
    assert pat.pattern.startswith("-config")        # hence the "--" before it


def test_port_freed_polls_until_nothing_answers(monkeypatch):
    calls = []

    class _Ok:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(url, timeout=None):
        calls.append(url)
        if len(calls) < 3:
            return _Ok()
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert _p()._go2rtc_port_freed(timeout=5) is True
    assert len(calls) == 3


def test_port_still_held_is_reported(monkeypatch):
    def held(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "nope", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", held)
    assert _p()._go2rtc_port_freed(timeout=0.3) is False
