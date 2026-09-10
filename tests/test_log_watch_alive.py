#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_log_watch_alive.py
# Description: The plugin ticks Log_Error_Watch.py hourly, so the plugin is
#              the one thing placed to notice when it stops completing runs
#              (v2.95.2). A deterministic failure of the watch used to page
#              nobody: every downstream consumer just saw 'nothing new'.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import json
from datetime import datetime, timedelta
from conftest import bare_plugin, load_plugin_module


def _setup(tmp_path, monkeypatch, last_run):
    plugin = load_plugin_module(); p = bare_plugin()
    d = tmp_path / "Python Scripts"; d.mkdir()
    (d / "Log_Error_Watch.py").write_text("pass\n")
    if last_run is not None:
        (d / "log_error_watch_state.json").write_text(json.dumps({"last_run": last_run}))
    monkeypatch.setattr(p, "_scripts_dir", lambda: str(d))
    return plugin, p


def _stamp(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def test_fresh_state_is_quiet(tmp_path, monkeypatch):
    _, p = _setup(tmp_path, monkeypatch, _stamp(30))
    p._check_log_watch_alive()
    p.logger.error.assert_not_called()


def test_stale_state_shouts_once_a_day(tmp_path, monkeypatch):
    plugin, p = _setup(tmp_path, monkeypatch, _stamp(6 * 60))
    p._check_log_watch_alive(); p._check_log_watch_alive()
    assert p.logger.error.call_count == 1
    assert "NOT watching" in p.logger.error.call_args[0][0]


def test_unreadable_state_counts_as_never(tmp_path, monkeypatch):
    _, p = _setup(tmp_path, monkeypatch, "garbage")
    p._check_log_watch_alive()
    assert "since never" in p.logger.error.call_args[0][0]


def test_no_state_file_yet_is_not_a_fault(tmp_path, monkeypatch):
    _, p = _setup(tmp_path, monkeypatch, None)
    p._check_log_watch_alive()
    p.logger.error.assert_not_called()
