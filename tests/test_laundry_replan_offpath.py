#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_laundry_replan_offpath.py
# Description: A laundry deadline replans on the off-path pool, not on IWS's
#              one dispatch thread (v3.25.0). A quick replan comes back in the
#              reply; a slow one comes back "pending" with the plan as it stood,
#              so the page can wait for its "generated" stamp to move. Two
#              script runs can never overlap, whichever thread asks.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import load_plugin_module


@pytest.fixture
def plug():
    mod = load_plugin_module()
    p = mod.Plugin.__new__(mod.Plugin)
    p.logger = MagicMock()
    p.pluginPrefs = {}
    p._evo_reply = lambda obj, status=200: {"status": status, "obj": obj}
    # The Indigo variable write is not what this tests.
    mod.indigo.variables = {}
    mod.indigo.variable = MagicMock()
    p._read_laundry_plan = lambda: {"generated": "OLD", "appliances": []}
    p._start_offpath_workers()
    yield p
    p._stop_offpath_workers()


def _action(body):
    return SimpleNamespace(props={"headers": {"Host": "192.168.1.10:8176"},
                                  "request_body": json.dumps(body)})


def test_a_quick_replan_comes_back_in_the_reply(plug):
    plug._replan_laundry = lambda: {"generated": "NEW", "appliances": []}
    r = plug.handleLaundryDeadline(_action({"appliance": "washing_machine", "deadline": "16:00"}))
    assert r["status"] == 200 and r["obj"]["plan"]["generated"] == "NEW"
    assert "pending" not in r["obj"]


def test_a_slow_replan_says_pending_and_hands_back_the_old_plan(plug):
    gate = threading.Event()
    def slow():
        gate.wait(3)
        return {"generated": "NEW", "appliances": []}
    plug._replan_laundry = slow
    plug.LAUNDRY_REPLAN_WAIT = 0.05
    t0 = time.monotonic()
    r = plug.handleLaundryDeadline(_action({"appliance": "washing_machine", "deadline": "16:00"}))
    held = time.monotonic() - t0
    gate.set()
    assert r["obj"]["pending"] is True
    assert r["obj"]["plan"]["generated"] == "OLD"
    assert held < 1.0, f"the dispatch thread was held {held:.2f} s"


def test_two_script_runs_never_overlap(plug, tmp_path):
    (tmp_path / "Slow.py").write_text(
        "import time\n"
        "TICK_MEMORY['n'] = TICK_MEMORY.get('n', 0) + 1\n"
        "RUNNING.append(1); assert len(RUNNING) == 1, 'overlap'\n"
        "time.sleep(0.1)\n"
        "RUNNING.pop()\n", encoding="utf-8")
    running = []
    plug.COMPANION_SCRIPTS = dict(plug.COMPANION_SCRIPTS)
    plug.COMPANION_SCRIPTS["slow"] = ("Slow.py", "[Slow]", {"RUNNING": running}, "")
    plug._scripts_dir = lambda: str(tmp_path)
    results = []
    ts = [threading.Thread(target=lambda: results.append(plug._tick_script("slow"))) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(3)
    assert results == [True, True, True], plug.logger.warning.call_args_list
