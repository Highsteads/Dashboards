#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_rotate_guest_stills.py
# Description: Plugins > Dashboards > Rotate Guest Link and Camera-Stills
#              Folder (3.46.0). Until then nothing handed out could be taken
#              back: a guest token worked for the life of the install, and the
#              stills folder name, which makes the camera pictures readable to
#              anyone who knows it (the reflector included), never changed.
#              Rotation makes a new guest token (saved 0600, in force at once,
#              the old one refused), a new stills token saved to the store
#              without losing the rest of it, deletes the old folder, keeps
#              the new values in force even when they cannot be saved, and
#              says so.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import os
import re
import stat
from pathlib import Path

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import config_mixin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OLD_STILLS = "a" * 32


def _plugin(tmp_path):
    p = bare_plugin()
    prefs = tmp_path / "prefs"
    pub = tmp_path / "public"
    prefs.mkdir(exist_ok=True)
    pub.mkdir(exist_ok=True)
    p._config_store_path = lambda: str(prefs / "dashboards_config.json")
    p._guest_token_path = lambda: str(prefs / "guest_token.txt")
    p._public_dashboards_dir = lambda: str(pub)
    p.cfg_store = {"siteName": "Home", "stillsToken": OLD_STILLS, "cameras": []}
    p.cameras = []
    p.pluginPrefs = {}
    (prefs / "guest_token.txt").write_text("old-guest-token", encoding="utf-8")
    p.guest_token = "old-guest-token"
    old = pub / f"stills-{OLD_STILLS}"
    old.mkdir()
    (old / "cam-10.0.0.5.jpg").write_bytes(b"\xff\xd8old")
    return p, prefs, pub


def test_both_tokens_change_are_saved_and_the_old_folder_goes(tmp_path):
    p, prefs, pub = _plugin(tmp_path)
    rep = p._rotate_guest_and_stills()
    assert rep == {"guest": True, "stills": True, "removedOld": True, "problems": []}, rep

    assert p.guest_token != "old-guest-token" and len(p.guest_token) >= 20
    on_disk = (prefs / "guest_token.txt").read_text(encoding="utf-8")
    assert on_disk == p.guest_token, "the next start must read the NEW token"
    assert stat.S_IMODE(os.stat(prefs / "guest_token.txt").st_mode) == 0o600

    new = p._stills_token()
    assert re.match(r"^[0-9a-f]{32}$", new) and new != OLD_STILLS
    store = json.loads((prefs / "dashboards_config.json").read_text(encoding="utf-8"))
    assert store["stillsToken"] == new
    assert store["siteName"] == "Home", "rotating must not lose the rest of the store"

    assert not (pub / f"stills-{OLD_STILLS}").exists(), "the old pictures must not stay readable"
    assert (pub / f"stills-{new}").is_dir(), "the new folder exists before the first poll"
    assert p._stills_dir().endswith(f"stills-{new}"), "the poller writes to the new folder"
    assert not list(prefs.glob("*.tmp")), "no temp file left behind"


def test_the_old_guest_token_is_refused_at_once():
    src = (ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/cameras_mixin.py").read_text(encoding="utf-8")
    # The /guest/ routes compare against plugin_self.guest_token on EVERY
    # request, so replacing the attribute is the revocation.
    assert "tok = plugin_self.guest_token or" in src


def test_new_values_hold_even_when_they_cannot_be_saved(tmp_path, monkeypatch):
    p, prefs, pub = _plugin(tmp_path)

    def cannot(_tok):
        raise OSError("read-only volume")
    monkeypatch.setattr(p, "_write_guest_token", cannot)
    p._store_unreadable = "/x/dashboards_config.json"      # the store refuses saves
    rep = p._rotate_guest_and_stills()
    assert rep["guest"] is False and rep["stills"] is False
    assert p.guest_token != "old-guest-token", "in force now even if not saved"
    assert p._stills_token() != OLD_STILLS
    assert len(rep["problems"]) == 2
    assert any("guest token" in m and "next plugin start" in m for m in rep["problems"])
    assert not (pub / f"stills-{OLD_STILLS}").exists()


def test_a_failed_guest_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    p, prefs, _pub = _plugin(tmp_path)
    real_replace = os.replace

    def boom(src, dst):
        if str(dst).endswith("guest_token.txt"):
            raise OSError("disk full")
        return real_replace(src, dst)
    monkeypatch.setattr(config_mixin.os, "replace", boom)
    try:
        p._write_guest_token("new")
    except OSError:
        pass
    assert (prefs / "guest_token.txt").read_text(encoding="utf-8") == "old-guest-token"
    assert not (prefs / "guest_token.txt.tmp").exists()


def test_the_menu_item_is_wired_and_logs_what_to_do(tmp_path, monkeypatch):
    xml = (ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin/MenuItems.xml").read_text(encoding="utf-8")
    assert "<CallbackMethod>menuRotateGuestAndStills</CallbackMethod>" in xml
    assert "Rotate Guest Link and Camera-Stills Folder" in xml

    p, _prefs, _pub = _plugin(tmp_path)
    lines = []
    monkeypatch.setattr(plugin, "log", lambda msg, level="INFO": lines.append((level, msg)))
    p._write_config_js = lambda: None
    p.api_url = "http://192.168.1.10:8176"
    assert p.menuRotateGuestAndStills() is True
    text = "\n".join(m for _l, m in lines)
    assert "guest.html" in text, "the user is told how to re-share the guest link"
    assert "Reload" in text, "and that open pages need a reload"
    assert "API key is unchanged" in text
