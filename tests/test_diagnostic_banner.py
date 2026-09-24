#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_diagnostic_banner.py
# Description: Every diagnostic menu dumps the SAME banner, extras included
#              (review 24-09-2026 [28]). Test Dashboards Setup printed a bare
#              banner, so the paste a support post is built from lacked the
#              URL, key source, cameras and history-backend lines.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
from conftest import bare_plugin, load_plugin_module


def _plugin(monkeypatch):
    mod = load_plugin_module()
    seen = []
    monkeypatch.setattr(mod, "log_startup_banner",
                        lambda pid, name, ver, extras=None: seen.append(extras))
    p = bare_plugin()
    p.pluginId, p.pluginDisplayName, p.pluginVersion = "id", "Dashboards", "9.9"
    p.api_url, p.pluginPrefs, p.timestamp_enabled = "http://x:8176", {}, False
    p._dashboard_url = lambda: "http://x:8176/public/dashboards/index.html"
    p._secrets_state = lambda: "IndigoSecrets.py"
    p._camera_state = lambda: "2 configured"
    p._setup_checks = lambda: []
    return p, seen


def test_setup_menu_banner_carries_the_same_extras_as_show_plugin_info(monkeypatch):
    p, seen = _plugin(monkeypatch)
    p.showPluginInfo()
    p.menuTestSetup()
    assert len(seen) == 2
    assert seen[0] and seen[1] == seen[0]
    labels = [label for label, _ in seen[1]]
    assert "Dashboards URL:" in labels and "History backend:" in labels
