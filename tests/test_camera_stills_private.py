#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_stills_private.py
# Description: The camera stills are no longer at guessable names in the
#              anonymous /public folder. They live in stills-<token>/, the token
#              is a per-install secret kept in the 0600 settings store, and the
#              only way to learn it is the Bearer-authenticated cameraStills
#              action. config.js stops publishing the patterns, a Settings save
#              can neither set nor clear the token, and startup clears every
#              still left outside the current folder.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import os
import re
import stat
from unittest.mock import MagicMock

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


class _Action:
    def __init__(self, body="{}", headers=None):
        self.props = {"request_body": body, "headers": headers or {}}


def _plugin(tmp_path, store=None):
    """A bare Plugin whose store file and public folder live in tmp_path."""
    p = bare_plugin()
    prefs = tmp_path / "prefs"
    pub = tmp_path / "public"
    prefs.mkdir(exist_ok=True)
    pub.mkdir(exist_ok=True)
    p._config_store_path = lambda: str(prefs / "dashboards_config.json")
    p._public_dashboards_dir = lambda: str(pub)
    p.cfg_store = dict(store or {})
    p.pluginPrefs = {}
    return p, prefs / "dashboards_config.json", pub


# ------------------------------------------------------------ the token ----

def test_a_token_is_made_saved_and_kept(tmp_path):
    p, store_file, _ = _plugin(tmp_path, {"siteName": "Home"})
    tok = p._ensure_stills_token()
    assert TOKEN_RE.match(tok), tok
    on_disk = json.loads(store_file.read_text(encoding="utf-8"))
    assert on_disk["stillsToken"] == tok
    assert on_disk["siteName"] == "Home", "making the token must not lose the rest"
    assert stat.S_IMODE(os.stat(store_file).st_mode) == 0o600
    # A second start reads the same token back rather than making a new one.
    assert p._ensure_stills_token() == tok


def test_a_malformed_token_is_replaced(tmp_path):
    p, _, _ = _plugin(tmp_path, {"stillsToken": "cam"})
    tok = p._ensure_stills_token()
    assert TOKEN_RE.match(tok) and tok != "cam"


def test_the_paths_sit_in_the_token_folder(tmp_path):
    p, _, pub = _plugin(tmp_path, {"stillsToken": "a" * 32})
    folder = pub / f"stills-{'a' * 32}"
    assert p._cam_jpg_path("10.0.0.5") == str(folder / "cam-10.0.0.5.jpg")
    assert p._cam_thumb_path("10.0.0.5") == str(folder / "cam-10.0.0.5-thumb.jpg")


def test_the_snapshot_worker_writes_into_the_folder(tmp_path):
    p, _, pub = _plugin(tmp_path, {"stillsToken": "b" * 32})
    import threading
    p._cam_state = {"10.0.0.5": {"ok_count": 0, "fail_count": 0, "last_log": 0}}
    p._cam_inflight = {"10.0.0.5"}
    p._cam_inflight_lock = threading.Lock()
    p._fetch_one_snapshot = lambda host: (True, b"JPEGDATA")
    p._make_thumb = lambda data: None
    p._snapshot_worker({"host": "10.0.0.5", "name": "Front"})
    assert (pub / f"stills-{'b' * 32}" / "cam-10.0.0.5.jpg").read_bytes() == b"JPEGDATA"
    assert not (pub / "cam-10.0.0.5.jpg").exists()


# ------------------------------------------------------- startup sweep ----

def test_startup_clears_every_still_outside_the_folder(tmp_path):
    tok = "c" * 32
    p, _, pub = _plugin(tmp_path, {"stillsToken": tok})
    p.logger = MagicMock()
    for name in ("cam-10.0.0.5.jpg", "cam-10.0.0.5-thumb.jpg",
                 "cam-10.0.0.6.jpg.tmp.1234"):
        (pub / name).write_bytes(b"x")
    old = pub / f"stills-{'d' * 32}"
    old.mkdir()
    (old / "cam-10.0.0.5.jpg").write_bytes(b"x")
    cur = pub / f"stills-{tok}"
    cur.mkdir()
    (cur / "cam-10.0.0.5.jpg").write_bytes(b"keep")
    (pub / "config.js").write_text("// untouched", encoding="utf-8")
    (pub / "cameras.html").write_text("untouched", encoding="utf-8")

    p._sweep_legacy_stills()

    left = sorted(os.listdir(pub))
    assert left == ["cameras.html", "config.js", f"stills-{tok}"], left
    assert (cur / "cam-10.0.0.5.jpg").read_bytes() == b"keep"


def test_startup_makes_the_folder_before_the_first_poll(tmp_path):
    tok = "e" * 32
    p, _, pub = _plugin(tmp_path, {"stillsToken": tok})
    p.logger = MagicMock()
    p._sweep_legacy_stills()
    assert (pub / f"stills-{tok}").is_dir()


def test_startup_wires_the_token_and_the_sweep():
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(plugin.Plugin.startup))
    calls = [n.func.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "_ensure_stills_token" in calls and "_sweep_legacy_stills" in calls
    assert calls.index("_ensure_stills_token") < calls.index("_sweep_legacy_stills"), \
        "the sweep keeps the CURRENT folder, so the token must exist first"


# ----------------------------------------------------------- the reply ----

def test_camera_stills_answers_the_patterns(tmp_path):
    tok = "f" * 32
    p, _, _ = _plugin(tmp_path, {"stillsToken": tok})
    reply = p.handleCameraStills(_Action())
    assert reply["status"] == 200
    assert json.loads(reply["content"]) == {
        "ok": True,
        "imagePattern": f"stills-{tok}/cam-{{host}}.jpg",
        "thumbPattern": f"stills-{tok}/cam-{{host}}-thumb.jpg",
    }


def test_camera_stills_is_declared_in_actions_xml():
    from pathlib import Path
    xml = (Path(__file__).resolve().parents[1] / "Dashboards.indigoPlugin" / "Contents"
           / "Server Plugin" / "Actions.xml").read_text(encoding="utf-8")
    m = re.search(r'<Action id="cameraStills" uiPath="hidden">.*?</Action>', xml, re.S)
    assert m and "<CallbackMethod>handleCameraStills</CallbackMethod>" in m.group(0)


# ------------------------------------------------- nothing leaks it out ----

def _config_js(tmp_path, tok):
    p, _, pub = _plugin(tmp_path, {"stillsToken": tok, "arrayKwp": 14.25})
    p.api_url = "http://192.168.1.10:8176"
    p.api_key = "key"
    p.control_pin = ""
    p.pin_required = []
    p.favourites = []
    p.custom_links = []
    p.guest_token = "guest"
    p.main_cameras = ["10.0.0.5"]
    p.cameras = [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}]
    p.swap_out_host = "10.0.0.5"
    p.lan_ip = "192.168.1.10"
    p.pluginVersion = "0.0.0-test"
    p._write_config_js()
    return (pub / "config.js").read_text(encoding="utf-8")


def test_config_js_never_carries_the_token_or_the_patterns(tmp_path):
    tok = "1" * 32
    js = _config_js(tmp_path, tok)
    assert tok not in js
    assert "stills-" not in js
    assert "imagePattern" not in js and "thumbPattern" not in js
    # The camera block itself is still there — the test must not pass by
    # the file being empty.
    assert '"hosts": ["10.0.0.5"]' in js and "thumbWidth" in js and "pollSeconds" in js


def test_the_settings_page_never_sees_the_token(tmp_path):
    tok = "2" * 32
    p, _, _ = _plugin(tmp_path, {"stillsToken": tok, "siteName": "Home"})
    p.main_cameras = []
    p.room_extras = {}
    p.control_pin = ""
    p.pin_required = []
    p.favourites = []
    p.custom_links = []
    cfg = p._effective_config()
    assert "stillsToken" not in cfg
    assert tok not in json.dumps(cfg)
    assert cfg.get("siteName") == "Home", "other unknown keys still round-trip"


def _saving_plugin(tok):
    p = bare_plugin()
    captured = {}

    def _save(clean):
        captured["clean"] = clean
        return dict(clean)
    p._save_config_store = _save
    p._write_config_js = MagicMock()
    p._build_rooms_json = MagicMock()
    p._build_scenes_json = MagicMock()
    p.cfg_store = {"stillsToken": tok}
    return p, captured


def test_a_settings_save_keeps_the_token():
    tok = "3" * 32
    p, cap = _saving_plugin(tok)
    reply = p._apply_config({"siteName": "Home"})
    assert reply["status"] == 200
    assert cap["clean"]["stillsToken"] == tok
    assert p.cfg_store["stillsToken"] == tok


def test_a_client_cannot_set_or_clear_the_token():
    tok = "4" * 32
    for sent in ("5" * 32, "", None):
        p, cap = _saving_plugin(tok)
        p._apply_config({"stillsToken": sent})
        assert cap["clean"]["stillsToken"] == tok, f"a client sent {sent!r}"
