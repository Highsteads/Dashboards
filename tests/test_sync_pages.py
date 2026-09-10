#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_sync_pages.py
# Description: _sync_pages_to_public — the startup copy of the bundle's pages
#              into IWS's /public folder, and its stale sweep. The sweep
#              deletes any .html/.js/.css/.png in the public dir that the
#              bundle no longer ships, EXCEPT the runtime artefacts the plugin
#              writes there itself (_RUNTIME_KEEP: config.js and go2rtc's two
#              JS files). The plugin's own comment records the regression this
#              guards: the sweep once deleted config.js and the go2rtc assets
#              on EVERY sync. Nothing tested it.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import os
from conftest import bare_plugin, load_plugin_module


def _setup(tmp_path, monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    src = tmp_path / "pages"; src.mkdir()
    dst = tmp_path / "public"; dst.mkdir()
    (src / "index.html").write_text("<html>new</html>", encoding="utf-8")
    (src / "dashboards-ui.js").write_text("// ui", encoding="utf-8")
    (src / "manifest.json").write_text("{}", encoding="utf-8")
    # what the public dir held before this sync
    (dst / "old.html").write_text("<html>gone</html>", encoding="utf-8")     # no longer in the bundle
    (dst / "config.js").write_text("window.INDIGO_CONFIG={}", encoding="utf-8")   # written by the plugin
    (dst / "video-rtc.js").write_text("// go2rtc", encoding="utf-8")            # mirrored from go2rtc
    (dst / "rooms.json").write_text("{}", encoding="utf-8")                      # runtime data
    (dst / "cam-1.2.3.4.jpg").write_bytes(b"\xff\xd8")                           # snapshot
    monkeypatch.setattr(plugin, "PAGES_SOURCE_DIR", str(src))
    monkeypatch.setattr(p, "_public_dashboards_dir", lambda: str(dst))
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    return plugin, p, src, dst


def test_bundle_pages_are_copied_and_stale_ones_swept(tmp_path, monkeypatch):
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    p._sync_pages_to_public()
    assert (dst / "index.html").read_text(encoding="utf-8") == "<html>new</html>"
    assert (dst / "dashboards-ui.js").exists()
    assert not (dst / "old.html").exists(), "a page the bundle no longer ships must be swept"


def test_runtime_artefacts_survive_the_sweep(tmp_path, monkeypatch):
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    p._sync_pages_to_public()
    for keep in ("config.js", "video-rtc.js", "rooms.json", "cam-1.2.3.4.jpg"):
        assert (dst / keep).exists(), f"{keep} is written at runtime and must never be swept"


def test_no_tmp_files_left_behind(tmp_path, monkeypatch):
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    p._sync_pages_to_public()
    assert not [f for f in os.listdir(dst) if f.endswith(".tmp")]
