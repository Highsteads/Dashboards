#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_closed_prefs.py
# Description: The credential resolution every NON-IndigoSecrets user relies
#              on (_resolve_credentials with secrets_mod=None) and the live
#              apply in closedPrefsConfigUi. The changelog records that an
#              older menuRegenerateConfig wiped api_url/api_key for GUI-only
#              installs; nothing tested the fix, and that path is the one
#              every other user exercises.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import types
import logging

from unittest.mock import MagicMock
from conftest import bare_plugin, load_plugin_module


def test_prefs_fill_every_credential_when_there_are_no_secrets():
    p = bare_plugin()
    p._resolve_credentials({"indigoUrl": " http://10.0.0.5:8176 ", "indigoApiKey": "k1",
                            "dahuaUser": "u", "dahuaPass": "pw", "sigenLegacyUrl": "http://x:8179/"}, None)
    assert p.api_url == "http://10.0.0.5:8176"
    assert p.api_key == "k1" and p.cam_user == "u" and p.cam_pass == "pw"
    assert p.sigen_legacy_url == "http://x:8179/"


def test_blank_url_means_the_local_server():
    p = bare_plugin()
    p._resolve_credentials({}, None)
    assert p.api_url == "http://127.0.0.1:8176"


def test_secrets_win_over_prefs():
    p = bare_plugin()
    sec = types.ModuleType("IndigoSecrets")
    sec.INDIGO_URL = "http://192.168.1.10:8176"; sec.INDIGO_API_KEY = "fromsecrets"
    p._resolve_credentials({"indigoUrl": "http://other", "indigoApiKey": "fromprefs"}, sec)
    assert p.api_url == "http://192.168.1.10:8176" and p.api_key == "fromsecrets"


def _prefs_plugin(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    p.cfg_loaded = True
    p.cam_user = p.cam_pass = ""
    p.pluginPrefs = {}
    p._write_config_js = MagicMock()
    p._stop_weather_thread = MagicMock()
    p._start_weather_thread = MagicMock()
    monkeypatch.setattr(plugin, "CAMERAS", [])
    return plugin, p


def test_closed_prefs_applies_log_level_and_bootstrap_live(monkeypatch):
    plugin, p = _prefs_plugin(monkeypatch)
    handler = MagicMock()
    p.indigo_log_handler = handler
    p.closedPrefsConfigUi({"logLevel": "", "bootstrapKeySeed": "false"}, userCancelled=False)
    # logLevel now sets the EVENT-LOG handler's floor, not the logger's, so the
    # plugin's own file keeps receiving debug whatever the user picks. Blank
    # still means Info, and still never crashes.
    handler.setLevel.assert_called_with(20)
    p.logger.setLevel.assert_called_with(logging.DEBUG)
    assert p.bootstrap_key_seed is False
    p._write_config_js.assert_called_once()
    p._start_weather_thread.assert_called_once()        # weather fields apply live (v2.95.2)


def test_cancelled_dialog_changes_nothing(monkeypatch):
    plugin, p = _prefs_plugin(monkeypatch)
    p.closedPrefsConfigUi({"logLevel": "10"}, userCancelled=True)
    p._write_config_js.assert_not_called()
