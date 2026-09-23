#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_legacy_config_import.py
# Description: One settings store (v3.27.0). A first start with no
#              dashboards_config.json imports the legacy IndigoSecrets
#              DASHBOARDS_* keys and Configure fields into it once; from then
#              on only the store is read. Before this there were two paths and
#              every consumer branched between them.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
from conftest import bare_plugin, load_plugin_module


def _plugin(monkeypatch, **legacy):
    load_plugin_module()
    import config_mixin as mod      # the import lives there since v3.32.0
    for k in ("DASHBOARDS_CAMERAS", "DASHBOARDS_MAIN_CAMERAS",
              "DASHBOARDS_ROOM_EXTRAS", "DASHBOARDS_HIDDEN_SCENES"):
        monkeypatch.setattr(mod, k, legacy.get(k, [] if "EXTRAS" not in k else {}))
    logs = []
    monkeypatch.setattr(mod, "log", lambda m, level="INFO": logs.append((level, m)))
    p = bare_plugin()
    saved = {}
    def _save(data):
        saved.update(data)
        return dict(data)
    p._save_config_store = _save
    return p, saved, logs


def test_secrets_and_configure_values_are_imported_once(monkeypatch):
    p, saved, logs = _plugin(
        monkeypatch,
        DASHBOARDS_CAMERAS='[{"host":"192.0.2.5","name":"Door","vendor":"dahua"}]',
        DASHBOARDS_MAIN_CAMERAS=["192.0.2.5"],
        DASHBOARDS_ROOM_EXTRAS={"Hall": {"mainLight": [1]}})
    store = p._import_legacy_config({"swapOutHost": " 192.0.2.5 ",
                                     "hiddenScenesJson": '["Reset", "folder:Maint"]'})
    assert store["cameras"][0]["host"] == "192.0.2.5"
    assert store["mainCameras"] == ["192.0.2.5"]
    assert store["roomExtras"] == {"Hall": {"mainLight": [1]}}
    assert store["swapOutHost"] == "192.0.2.5"
    assert store["hiddenScenes"] == ["Reset", "folder:Maint"]
    assert saved == store, "the import is written to dashboards_config.json"
    said = " ".join(m for _, m in logs)
    assert "imported" in said and "no longer read" in said


def test_configure_field_used_when_secrets_are_blank(monkeypatch):
    p, saved, logs = _plugin(monkeypatch)
    store = p._import_legacy_config(
        {"camerasJson": '[{"host":"192.0.2.9","name":"Drive","vendor":"hikvision"}]'})
    assert [c["host"] for c in store["cameras"]] == ["192.0.2.9"]


def test_a_fresh_install_gets_an_empty_store_and_no_import_line(monkeypatch):
    p, saved, logs = _plugin(monkeypatch)
    store = p._import_legacy_config({})
    assert store["cameras"] == [] and store["roomExtras"] == {}
    assert saved, "still written, so the next start does not import again"
    assert not [m for _, m in logs if "imported" in m]


def test_a_failed_save_still_runs_on_the_imported_settings(monkeypatch):
    p, saved, logs = _plugin(monkeypatch, DASHBOARDS_MAIN_CAMERAS=["192.0.2.1"])
    def boom(data):
        raise OSError("read-only")
    p._save_config_store = boom
    store = p._import_legacy_config({})
    assert store["mainCameras"] == ["192.0.2.1"]
    assert any(level == "WARNING" for level, _ in logs)


def test_hidden_scenes_come_from_the_store_only(monkeypatch):
    p, saved, logs = _plugin(monkeypatch, DASHBOARDS_HIDDEN_SCENES=["From secrets"])
    p.cfg_store = {"hiddenScenes": ["From settings"]}
    p.pluginPrefs = {"hiddenScenesJson": '["From configure"]'}
    assert p._hidden_scenes() == {"From settings"}
