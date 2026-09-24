#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_shutdown_setup_links.py
# Description: A one-time setup link is a /public file holding the API key.
#              Its 10-minute expiry was enforced only by this plugin's loop and
#              its startup sweep, and shutdown() never swept, so a link made
#              just before Dashboards was disabled or uninstalled stayed
#              readable (the Web Server plugin keeps serving /public) for good.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

from unittest.mock import MagicMock

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()

_TEARDOWN = ("_freeze_stamp", "_stop_stamp_thread", "_stop_go2rtc", "_stop_snapshot_pool",
             "_stop_proxy", "_stop_weather_thread", "_stop_offpath_workers", "_activity")


def _plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin, "STAMP_QUIESCE_SECONDS", 0)
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    p = bare_plugin()
    for name in _TEARDOWN:
        setattr(p, name, MagicMock())
    p.pluginDisplayName = "Dashboards"
    p._public_dashboards_dir = lambda: str(tmp_path)
    return p


def test_shutdown_removes_a_fresh_setup_link(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch)
    (tmp_path / "setup-AbCdEfGhIjKlMnOpQrStUv.json").write_text('{"apiKey": "k"}', encoding="utf-8")
    (tmp_path / "setup-AbCdEfGhIjKlMnOpQrStUv.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "config.js").write_text("// stays", encoding="utf-8")
    p.shutdown()
    assert sorted(f.name for f in tmp_path.iterdir()) == ["config.js"]


def test_a_failed_sweep_does_not_stop_the_teardown(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch)
    p._cleanup_setup_links = MagicMock(side_effect=OSError("disk gone"))
    p.shutdown()
    p._cleanup_setup_links.assert_called_once_with(force_all=True)
    p._stop_go2rtc.assert_called_once()
    p._stop_offpath_workers.assert_called_once()
