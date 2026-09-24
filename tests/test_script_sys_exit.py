#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_script_sys_exit.py
# Description: sys.exit() in a companion script raises SystemExit, which is a
#              BaseException. The runner caught only Exception, so it went past
#              _tick_script, past step() and out of runConcurrentThread,
#              stopping camera polling and every later tick until a restart.
#              Now code None/0 is a clean early exit and anything else is a
#              reported failure; neither escapes.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import pytest

from conftest import bare_plugin


def _plugin(tmp_path, monkeypatch, src):
    p = bare_plugin()
    scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    (scripts / "Drive_Lights_Sun.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(p, "_scripts_dir", lambda: str(scripts))
    return p


@pytest.mark.parametrize("src", [
    "import sys\nsys.exit()\n",
    "import sys\nsys.exit(0)\n",
    "raise SystemExit\n",
])
def test_a_clean_early_exit_is_a_clean_run(tmp_path, monkeypatch, src):
    p = _plugin(tmp_path, monkeypatch, src)
    assert p._tick_script("drivelights") is True
    p.logger.warning.assert_not_called()


@pytest.mark.parametrize("src, shown", [
    ("import sys\nsys.exit(2)\n", "2"),
    ('raise SystemExit("config missing")\n', "config missing"),
])
def test_a_failing_exit_is_reported_once_and_contained(tmp_path, monkeypatch, src, shown):
    p = _plugin(tmp_path, monkeypatch, src)
    assert p._tick_script("drivelights") is False
    assert p._tick_script("drivelights") is False
    warns = [c.args[0] for c in p.logger.warning.call_args_list]
    assert len(warns) == 1 and shown in warns[0], warns


def test_recovery_after_a_failing_exit_is_logged(tmp_path, monkeypatch):
    p = _plugin(tmp_path, monkeypatch, "import sys\nsys.exit(1)\n")
    assert p._tick_script("drivelights") is False
    (tmp_path / "Python Scripts" / "Drive_Lights_Sun.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8")
    assert p._tick_script("drivelights") is True
    assert any("recovered" in c.args[0] for c in p.logger.info.call_args_list)
