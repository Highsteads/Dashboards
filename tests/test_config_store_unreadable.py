#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_config_store_unreadable.py
# Description: A dashboards_config.json that is PRESENT but will not parse is
#              not the same as one that is absent. It used to be treated as
#              absent: the legacy import ran and saved, and the save copied the
#              broken file over the one good .bak, so a typo plus a restart lost
#              cameras, favourites and the control PIN for good. Now it is set
#              aside once, logged as an ERROR, nothing is imported, and every
#              save refuses until the file is fixed and the plugin restarted.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import json
import os
import stat

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
import config_mixin  # noqa: E402  (importable once load_plugin_module has run)

GOOD = {"cameras": [{"host": "10.0.0.5", "name": "Front", "vendor": "dahua"}],
        "controlPin": "1234"}


@pytest.fixture
def logged(monkeypatch):
    lines = []
    monkeypatch.setattr(config_mixin, "log",
                        lambda msg, level="INFO": lines.append((level, msg)))
    return lines


def _plugin(tmp_path):
    p = bare_plugin()
    path = tmp_path / "dashboards_config.json"
    p._config_store_path = lambda: str(path)
    return p, path


def test_an_absent_file_is_still_absent(tmp_path, logged):
    p, _ = _plugin(tmp_path)
    assert p._load_config_store() == {}
    assert not p._store_unreadable
    assert not logged


def test_a_good_file_loads(tmp_path, logged):
    p, path = _plugin(tmp_path)
    path.write_text(json.dumps(GOOD), encoding="utf-8")
    assert p._load_config_store() == GOOD
    assert not p._store_unreadable


@pytest.mark.parametrize("body", ['{"cameras": [', "[1, 2, 3]", ""])
def test_an_unreadable_file_is_set_aside_and_blocks_saving(tmp_path, logged, body):
    p, path = _plugin(tmp_path)
    path.write_text(body, encoding="utf-8")
    (tmp_path / "dashboards_config.json.bak").write_text(json.dumps(GOOD), encoding="utf-8")

    assert p._load_config_store() == {}
    assert p._store_unreadable == str(path)
    errors = [m for lvl, m in logged if lvl == "ERROR"]
    assert errors and str(path) in errors[0], logged

    aside = [n for n in os.listdir(tmp_path) if n.startswith("dashboards_config.json.corrupt-")]
    assert len(aside) == 1, aside
    assert (tmp_path / aside[0]).read_text(encoding="utf-8") == body
    assert stat.S_IMODE(os.stat(tmp_path / aside[0]).st_mode) == 0o600

    # Saving is refused, and neither the file nor the good .bak changes.
    with pytest.raises(RuntimeError):
        p._save_config_store({"cameras": []})
    assert path.read_text(encoding="utf-8") == body
    assert json.loads((tmp_path / "dashboards_config.json.bak").read_text(encoding="utf-8")) == GOOD


def test_the_copy_aside_happens_once_per_content(tmp_path, logged):
    p, path = _plugin(tmp_path)
    path.write_text("{broken", encoding="utf-8")
    p._load_config_store()
    p2, _ = _plugin(tmp_path)
    p2._load_config_store()            # a second start with the same broken file
    aside = [n for n in os.listdir(tmp_path) if ".corrupt-" in n]
    assert len(aside) == 1, aside


def test_init_does_not_import_over_an_unreadable_file():
    """__init__ must skip _import_legacy_config (which saves) when the store
    was present but unreadable."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(plugin.Plugin.__init__))
    tree = ast.parse(src)
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "_import_legacy_config"
                      for b in n.body for c in ast.walk(b))]
    assert guards, "the legacy import must sit behind an if"
    assert "_store_unreadable" in ast.unparse(guards[0].test), ast.unparse(guards[0].test)


def test_the_settings_page_gets_an_error_not_an_overwrite(tmp_path, logged):
    from unittest.mock import MagicMock
    p, path = _plugin(tmp_path)
    path.write_text("{broken", encoding="utf-8")
    p.cfg_store = p._load_config_store()
    p._write_config_js = MagicMock()
    reply = p._apply_config({"siteName": "Home"})
    assert reply["status"] == 500
    assert path.read_text(encoding="utf-8") == "{broken"


def test_a_save_does_not_back_up_a_broken_file(tmp_path, logged):
    """Even with the flag clear (a file broken AFTER startup), the .bak is only
    ever taken from a file that parses."""
    p, path = _plugin(tmp_path)
    bak = tmp_path / "dashboards_config.json.bak"
    bak.write_text(json.dumps(GOOD), encoding="utf-8")
    path.write_text("{broken", encoding="utf-8")
    p._save_config_store({"siteName": "Home"})
    assert json.loads(bak.read_text(encoding="utf-8")) == GOOD
    assert json.loads(path.read_text(encoding="utf-8"))["siteName"] == "Home"


def test_a_save_still_backs_up_a_good_file(tmp_path, logged):
    p, path = _plugin(tmp_path)
    path.write_text(json.dumps(GOOD), encoding="utf-8")
    p._save_config_store({"siteName": "Home"})
    assert json.loads((tmp_path / "dashboards_config.json.bak").read_text(encoding="utf-8")) == GOOD
