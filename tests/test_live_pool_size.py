#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_live_pool_size.py
# Description: config.js publishes the SAVED livePoolSize (3.46.0). Settings
#              and docs/configuration.md offered the key for months while
#              _write_config_js published the LIVE_POOL_SIZE constant, so a
#              saved value did nothing. A whole number 0..LIVE_POOL_MAX is
#              used, more is held to the maximum, and junk falls back to the
#              default (a raw-JSON typo must not switch every camera off).
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import re

import pytest

from conftest import load_plugin_module, bare_plugin

plugin = load_plugin_module()

import dash_common  # noqa: E402  (importable once conftest has set the path)
from dash_util import live_pool_size  # noqa: E402

DEFAULT = dash_common.LIVE_POOL_SIZE
MOST = dash_common.LIVE_POOL_MAX


@pytest.mark.parametrize("raw, want", [
    (None, DEFAULT), ("", DEFAULT),
    (0, 0), (1, 1), (4, 4), ("3", 3), (4.0, 4),
    (MOST, MOST), (MOST + 1, MOST), (999, MOST),
    (-1, DEFAULT), (2.5, DEFAULT), ("six", DEFAULT), (True, DEFAULT), (False, DEFAULT),
    (float("nan"), DEFAULT), (float("inf"), DEFAULT), ([3], DEFAULT), ({"n": 3}, DEFAULT),
])
def test_the_clamp(raw, want):
    size, _problem = live_pool_size(raw, DEFAULT, MOST)
    assert size == want


def test_a_good_value_is_not_a_problem_and_a_bad_one_is():
    assert live_pool_size(3, DEFAULT, MOST)[1] == ""
    assert live_pool_size(None, DEFAULT, MOST)[1] == ""
    assert "not a number" in live_pool_size("six", DEFAULT, MOST)[1]
    assert str(MOST) in live_pool_size(99, DEFAULT, MOST)[1]


def _cam_cfg(tmp_path, store):
    p = bare_plugin()
    p.api_url = "http://192.168.1.10:8176"
    p.api_key = "k"
    p.control_pin = ""
    p.pin_required = []
    p.favourites = []
    p.custom_links = []
    p.main_cameras = []
    p.cameras = []
    p.swap_out_host = ""
    p.lan_ip = "192.168.1.10"
    p.pluginVersion = "0.0.0-test"
    p.cfg_store = store
    p._public_dashboards_dir = lambda: str(tmp_path)
    p._write_config_js()
    js = (tmp_path / "config.js").read_text(encoding="utf-8")
    m = re.search(r"^window\.CAMERA_CONFIG = (.*);$", js, re.M)
    assert m, js
    return json.loads(m.group(1))


def test_config_js_publishes_the_saved_value(tmp_path):
    assert _cam_cfg(tmp_path, {"livePoolSize": 2})["livePoolSize"] == 2


def test_zero_is_honoured_not_mistaken_for_missing(tmp_path):
    assert _cam_cfg(tmp_path, {"livePoolSize": 0})["livePoolSize"] == 0


def test_no_saved_value_publishes_the_default(tmp_path):
    assert _cam_cfg(tmp_path, {})["livePoolSize"] == DEFAULT


def test_junk_publishes_the_default_and_says_so_once(tmp_path, monkeypatch):
    import publish_mixin
    logged = []
    monkeypatch.setattr(publish_mixin, "log", lambda msg, level="INFO": logged.append((level, msg)))
    p = bare_plugin()
    assert p._live_pool_size({"livePoolSize": "lots"}) == DEFAULT
    assert p._live_pool_size({"livePoolSize": "lots"}) == DEFAULT
    warned = [m for lvl, m in logged if lvl == "WARNING" and "livePoolSize" in m]
    assert len(warned) == 1, logged
