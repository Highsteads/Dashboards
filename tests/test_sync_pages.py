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
# Version:     1.1 (demo mode removed in 3.53.0: the old demo-data folder is cleared)

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
    (dst / "video-rtc.js").write_text("// go2rtc", encoding="utf-8")            # mirrored by versions before 3.26.0
    (dst / "rooms.json").write_text("{}", encoding="utf-8")                      # runtime data
    (dst / "cam-1.2.3.4.jpg").write_bytes(b"\xff\xd8")                           # snapshot
    import publish_mixin      # the sync lives there since v3.32.0
    monkeypatch.setattr(publish_mixin, "PAGES_SOURCE_DIR", str(src))
    monkeypatch.setattr(p, "_public_dashboards_dir", lambda: str(dst))
    monkeypatch.setattr(publish_mixin, "log", lambda *a, **k: None)
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
    for keep in ("config.js", "rooms.json", "cam-1.2.3.4.jpg"):
        assert (dst / keep).exists(), f"{keep} is written at runtime and must never be swept"


def test_the_old_go2rtc_js_copies_are_cleared(tmp_path, monkeypatch):
    """v3.26.0: nothing loads go2rtc's video-rtc.js any more, so the plugin
    stopped mirroring it and the sweep clears the copy older versions left."""
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    p._sync_pages_to_public()
    assert not (dst / "video-rtc.js").exists()


def test_no_tmp_files_left_behind(tmp_path, monkeypatch):
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    p._sync_pages_to_public()
    assert not [f for f in os.listdir(dst) if f.endswith(".tmp")]


def test_the_old_demo_data_folder_is_cleared(tmp_path, monkeypatch):
    """3.53.0 removed demo mode. Older versions mirrored its sample data into
    demo-data/, which the extension sweep cannot see, so the sync clears that
    one folder by name and leaves everything else in place."""
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    (dst / "demo-data" / "api").mkdir(parents=True)
    (dst / "demo-data" / "devices.json").write_text("[]", encoding="utf-8")
    (dst / "demo-data" / "api" / "timelineDay.json").write_text("{}", encoding="utf-8")
    (dst / "demo.html").write_text("<html>demo</html>", encoding="utf-8")
    p._sync_pages_to_public()
    assert not (dst / "demo-data").exists()
    assert not (dst / "demo.html").exists()
    for keep in ("config.js", "rooms.json", "cam-1.2.3.4.jpg"):
        assert (dst / keep).exists(), keep


def test_a_demo_data_link_is_not_followed(tmp_path, monkeypatch):
    """rmtree must never walk into a folder the plugin did not make."""
    plugin, p, src, dst = _setup(tmp_path, monkeypatch)
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    (elsewhere / "keep.json").write_text("{}", encoding="utf-8")
    os.symlink(elsewhere, dst / "demo-data")
    p._sync_pages_to_public()
    assert (elsewhere / "keep.json").exists()


def test_the_bundle_ships_no_demo(tmp_path):
    from conftest import SP
    real = os.path.join(SP, "..", "Resources", "static", "pages")
    assert not os.path.exists(os.path.join(real, "demo-data"))
    assert not os.path.exists(os.path.join(real, "demo.html"))
