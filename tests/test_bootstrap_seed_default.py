#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_bootstrap_seed_default.py
# Description: Key auto-seed is OFF for a new install (3.46.0), and an
#              existing install never flips. /bootstrap hands the full API
#              key to any LAN or tailnet browser while it is on, a visitor's
#              phone in a private tab included, so a new install now pairs
#              through the one-time setup links. Indigo stores nothing for a
#              checkbox until Configure is saved, so an install that never
#              saved it since 2.36.0 has NO value: it keeps the old default
#              (on), has it written down so no later start can flip it, and
#              is told once why it should switch it off. A stored value is
#              always used as it is.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import re
from pathlib import Path

import pytest

from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()
import config_mixin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/PluginConfig.xml"


@pytest.mark.parametrize("prefs, existing, want", [
    ({}, False, (False, "new")),                                   # a first start
    ({}, True, (True, "kept")),                                    # an old install, never saved
    ({"bootstrapKeySeed": True}, False, (True, "stored")),         # stored wins, either way
    ({"bootstrapKeySeed": False}, True, (False, "stored")),
    ({"bootstrapKeySeed": "true"}, False, (True, "stored")),
    ({"bootstrapKeySeed": "false"}, True, (False, "stored")),
    ({"bootstrapKeySeed": ""}, True, (True, "kept")),              # blank is not a value
    (None, False, (False, "new")),
])
def test_the_decision(prefs, existing, want):
    assert config_mixin.ConfigMixin._bootstrap_seed_pref(prefs, existing) == want


def test_history_means_any_key_but_this_one():
    h = config_mixin.ConfigMixin._prefs_have_history
    assert h({}) is False
    assert h({"bootstrapKeySeed": False}) is False
    assert h({"logLevel": 20}) is True
    assert h(None) is False


class _Prefs(dict):
    pass


def _settle(prefs, existing, monkeypatch):
    logged = []
    monkeypatch.setattr(config_mixin, "log", lambda msg, level="INFO": logged.append((level, msg)))
    p = bare_plugin()
    p.pluginPrefs = prefs
    saved = []
    p.savePluginPrefs = lambda: saved.append(dict(prefs))
    value = p._settle_bootstrap_seed(prefs, existing=existing)
    return value, logged, saved


def test_a_new_install_starts_off_and_records_it(monkeypatch):
    prefs = _Prefs()
    value, logged, saved = _settle(prefs, False, monkeypatch)
    assert value is False
    assert prefs["bootstrapKeySeed"] is False and saved, "written down, or a later start could flip it"
    assert any("Setup Link" in m for _l, m in logged), "a new user is told how to pair"


def test_an_old_install_with_nothing_stored_keeps_it_on_and_is_told_once(monkeypatch):
    prefs = _Prefs(logLevel=20)
    value, logged, saved = _settle(prefs, True, monkeypatch)
    assert value is True, "an existing install must not lose auto-seed without a word"
    assert prefs["bootstrapKeySeed"] is True and saved
    warned = [m for lvl, m in logged if lvl == "WARNING"]
    assert len(warned) == 1 and "visitor" in warned[0] and "Configure" in warned[0]
    # the next start finds it stored: no second notice, same value
    value2, logged2, saved2 = _settle(prefs, True, monkeypatch)
    assert value2 is True and not logged2 and not saved2


def test_a_stored_value_is_left_alone(monkeypatch):
    for stored in (True, False):
        prefs = _Prefs(bootstrapKeySeed=stored)
        value, logged, saved = _settle(prefs, True, monkeypatch)
        assert value is stored and not logged and not saved


def test_a_failed_write_still_answers_and_says_so(monkeypatch):
    logged = []
    monkeypatch.setattr(config_mixin, "log", lambda msg, level="INFO": logged.append((level, msg)))
    p = bare_plugin()
    p.pluginPrefs = _Prefs()

    def boom():
        raise OSError("read-only")
    p.savePluginPrefs = boom
    assert p._settle_bootstrap_seed(p.pluginPrefs, existing=False) is False
    assert any(lvl == "WARNING" and "could not record" in m for lvl, m in logged)


def test_configure_save_without_the_field_keeps_what_is_in_force():
    from unittest.mock import MagicMock
    p = bare_plugin()
    p.bootstrap_key_seed = True
    p.cam_user = p.cam_pass = ""
    p.pluginPrefs = {}
    p.indigo_log_handler = MagicMock()
    p._write_config_js = MagicMock()
    p._stop_weather_thread = MagicMock()
    p._start_weather_thread = MagicMock()
    p.cameras = []
    p.closedPrefsConfigUi({"logLevel": 20}, userCancelled=False)
    assert p.bootstrap_key_seed is True, "a save must never be what flips it"
    p.closedPrefsConfigUi({"logLevel": 20, "bootstrapKeySeed": False}, userCancelled=False)
    assert p.bootstrap_key_seed is False


def test_the_dialog_default_is_off_and_the_help_names_the_setup_link():
    xml = XML.read_text(encoding="utf-8")
    m = re.search(r'<Field id="bootstrapKeySeed" type="checkbox" defaultValue="(\w+)"', xml)
    assert m and m.group(1) == "false"
    helptext = xml.split('id="hlpBoot"', 1)[1].split("</Field>", 1)[0]
    assert "Generate One-Time Setup Link" in helptext
    assert "visitor" in helptext


def test_the_hub_tells_an_unpaired_browser_how_to_pair():
    hub = (ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages/index.html").read_text(encoding="utf-8")
    form = hub.split("function showConfigForm()", 1)[1].split("function connect()", 1)[0]
    assert "Generate" in form and "One-Time Setup Link" in form


def _start_plugin(prefs, tmp_path, monkeypatch):
    """Run the REAL Plugin.__init__ against `prefs` (the stub PluginBase is
    swapped for one that keeps the prefs object, as Indigo's does), with the
    install folder in tmp_path. The helpers above are tested alone; this
    catches an __init__ that asks them the question at the wrong moment."""
    from unittest.mock import MagicMock
    import indigo

    def base_init(self, pid, _name, _ver, p):
        self.pluginId = pid
        self.pluginPrefs = p
        self.logger = MagicMock()
        self.stopThread = self.stop_thread = False
    monkeypatch.setattr(indigo.PluginBase, "__init__", base_init)
    monkeypatch.setattr(indigo.server, "getInstallFolderPath",
                        lambda: str(tmp_path / "Indigo"), raising=False)
    monkeypatch.setattr(plugin.Plugin, "savePluginPrefs", lambda self: None, raising=False)
    monkeypatch.setattr(config_mixin, "log", lambda msg, level="INFO": None)
    # Logging is process-global: leave the event-log mirror and the timestamp
    # filter alone, or the next test in the session inherits them.
    monkeypatch.setattr(plugin, "_install_file_mirror", lambda _h: None)
    monkeypatch.setattr(plugin, "install_timestamp_filter", None, raising=False)
    (tmp_path / "Indigo" / "Web Assets" / "public").mkdir(parents=True)
    return plugin.Plugin("com.clives.indigoplugin.dashboards", "Dashboards", "3.46.0", prefs)


def test_a_real_first_start_leaves_auto_seed_off(tmp_path, monkeypatch):
    # __init__ writes cameraLoginHosts on a first start. The history check once
    # ran after that write, so every new install read as an old one: ON.
    prefs = {}
    p = _start_plugin(prefs, tmp_path, monkeypatch)
    assert p.bootstrap_key_seed is False
    assert prefs.get("bootstrapKeySeed") is False


def test_a_real_start_of_an_old_install_keeps_auto_seed_on(tmp_path, monkeypatch):
    prefs = {"logLevel": "20"}
    p = _start_plugin(prefs, tmp_path, monkeypatch)
    assert p.bootstrap_key_seed is True
