#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tick_script.py
# Description: The shared companion-script runner (v2.95.2) and the poller's
#              per-task isolation. Locks four things: (1) a script's
#              module-level sys.path insert does not leak into the host —
#              five scripts used to add one entry a tick each, for ever;
#              (2) TICK_MEMORY survives between ticks so a script can warn
#              once; (3) the first failure is logged with its traceback and
#              repeats are silent until the text changes, then a recovery
#              line; (4) in runConcurrentThread one task failing every tick
#              cannot stop the tasks behind it — the old single try/except
#              switched off the log watch, the night sweep and the drive
#              lights together when rooms.json failed to build.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

import sys
from conftest import bare_plugin, load_plugin_module


def _plugin_with_scripts(tmp_path, monkeypatch, **files):
    plugin = load_plugin_module()
    p = bare_plugin()
    scripts = tmp_path / "Python Scripts"
    scripts.mkdir()
    for name, src in files.items():
        (scripts / name).write_text(src, encoding="utf-8")
    monkeypatch.setattr(p, "_scripts_dir", lambda: str(scripts))
    return plugin, p


def test_sys_path_is_restored_after_a_tick(tmp_path, monkeypatch):
    plugin, p = _plugin_with_scripts(
        tmp_path, monkeypatch,
        **{"Drive_Lights_Sun.py": 'import sys\nsys.path.insert(0, "/nowhere/special")\n'})
    before = list(sys.path)
    assert p._tick_script("drivelights") is True
    assert sys.path == before


def test_tick_memory_persists_between_ticks(tmp_path, monkeypatch):
    plugin, p = _plugin_with_scripts(
        tmp_path, monkeypatch,
        **{"Drive_Lights_Sun.py": 'TICK_MEMORY["n"] = TICK_MEMORY.get("n", 0) + 1\n'})
    p._tick_script("drivelights"); p._tick_script("drivelights")
    assert p._tick_memory["drivelights"]["n"] == 2


def test_failure_logged_once_with_traceback_then_recovery(tmp_path, monkeypatch):
    plugin, p = _plugin_with_scripts(
        tmp_path, monkeypatch, **{"Drive_Lights_Sun.py": 'raise RuntimeError("boom")\n'})
    assert p._tick_script("drivelights") is False
    assert p._tick_script("drivelights") is False
    warns = [c.args[0] for c in p.logger.warning.call_args_list]
    assert len(warns) == 1 and "RuntimeError: boom" in warns[0] and "Traceback" in warns[0]
    # The script is fixed: the next tick says so, once.
    (tmp_path / "Python Scripts" / "Drive_Lights_Sun.py").write_text("x = 1\n", encoding="utf-8")
    assert p._tick_script("drivelights") is True
    infos = [c.args[0] for c in p.logger.info.call_args_list]
    assert any("recovered" in m for m in infos)


def test_missing_script_is_recorded_silently(tmp_path, monkeypatch):
    """v2.96.0: a missing optional script is recorded, not logged per key —
    runConcurrentThread reports every absent one in ONE line after the seed
    pass (five separate lines used to greet every fresh install)."""
    plugin, p = _plugin_with_scripts(tmp_path, monkeypatch)
    assert p._tick_script("nightsweep") is False
    assert p._tick_script("nightsweep") is False
    assert "nightsweep" in p._script_missing_logged
    p.logger.info.assert_not_called()


def test_one_failing_task_does_not_starve_the_others(monkeypatch):
    plugin = load_plugin_module()
    p = bare_plugin()
    p.cam_user = p.cam_pass = ""
    monkeypatch.setattr(plugin, "CAMERAS", [])
    monkeypatch.setattr(plugin, "log", lambda *a, **k: None)
    ran = {"scenes": 0, "logwatch": 0, "sweep": 0}
    def boom(): raise ValueError("bad roomExtras")
    p._build_rooms_json = boom                                  # fails EVERY tick
    p._build_scenes_json = lambda: ran.__setitem__("scenes", ran["scenes"] + 1)
    p._run_presence_watch = lambda: None
    p._cleanup_setup_links = lambda: None
    p._prune_change_ledger = lambda: None
    p._run_log_error_watch = lambda: ran.__setitem__("logwatch", ran["logwatch"] + 1)
    p._run_fp300_config_watch = lambda: None
    p._run_night_lights_sweep = lambda: ran.__setitem__("sweep", ran["sweep"] + 1)
    p._run_drive_lights_sun = lambda: None
    # Three ticks, then the stop flag — sleep() raises StopThread on the fourth.
    ticks = {"n": 0}
    def fake_sleep(_s):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            p.stopThread = True
            raise p.StopThread()
    p.sleep = fake_sleep
    p.runConcurrentThread()
    assert ran["scenes"] >= 1 and ran["logwatch"] >= 1 and ran["sweep"] >= 1, ran
    assert p._step_failures["rooms.json"] >= 1
