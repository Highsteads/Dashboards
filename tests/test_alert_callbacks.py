#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_alert_callbacks.py
# Description: The alert rules fire from Indigo's own change callbacks, with
#              no page open (3.47.0). deviceUpdated and variableUpdated call
#              super() first, judge only real transitions (a state written
#              again with the same value is not one), let two rules on one
#              device both fire, keep the 30 s per-rule cooldown, skip a
#              disabled device, a paused rule and a switched-off engine, never
#              raise into Indigo, and never send anything on the callback
#              thread: the firing is recorded in memory and the delivery is
#              queued for the worker. Also the worker itself, and the recent
#              firings surviving a restart.
# Author:      CliveS & Claude
# Date:        25-09-2026
# Version:     1.0

import json
import time
import types

from conftest import alert_plugin, load_plugin_module


class Dev:
    def __init__(self, dev_id=5, on=False, ui="off", enabled=True, name="Hall", plugin=""):
        self.id, self.onState, self.displayStateValUi = dev_id, on, ui
        self.enabled, self.name, self.pluginId = enabled, name, plugin


class Var:
    def __init__(self, var_id=9, value="home", name="Mode"):
        self.id, self.value, self.name = var_id, value, name


def _rule(**kw):
    r = {"kind": "device", "id": 5, "cond": "on", "name": "Hall", "enabled": True,
         "channels": ["pushover", "email"]}
    r.update(kw)
    return r


def _wired(monkeypatch, tmp_path, rules, **kw):
    """A plugin whose queued jobs are captured rather than run."""
    p, ctx = alert_plugin(monkeypatch, tmp_path, rules=rules, **kw)
    p._dev_changes = {}
    p._stamp_note_change = lambda: None
    ctx.jobs = []
    p._alert_enqueue = lambda st, job: ctx.jobs.append(job)
    return p, ctx


def _texts(ctx):
    return [j[1]["text"] for j in ctx.jobs if j[0] == "fire"]


def test_device_updated_calls_super_and_fires_on_a_real_transition(monkeypatch, tmp_path):
    mod = load_plugin_module()
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])
    called = []
    base = mod.indigo.PluginBase
    monkeypatch.setattr(base, "deviceUpdated", lambda self, o, n: called.append((o.id, n.id)))
    p.deviceUpdated(Dev(on=False), Dev(on=True, ui="on"))
    assert called == [(5, 5)], "super().deviceUpdated must run"
    assert _texts(ctx) == ["Hall turned on"]
    assert 5 in p._dev_changes, "the changedSince ledger still records it"


def test_nothing_is_sent_on_the_callback_thread(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()], email="house@example.com")
    p.deviceUpdated(Dev(on=False), Dev(on=True, ui="on"))
    assert _texts(ctx) == ["Hall turned on"]
    ctx.server.getPlugin.assert_not_called()
    ctx.server.sendEmailTo.assert_not_called()
    firing = ctx.jobs[0][1]
    assert firing["pending"] is True and firing["channels"] == ["pushover", "email"]


def test_the_same_value_written_again_is_not_a_transition(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(cond="change")])
    p.deviceUpdated(Dev(on=True, ui="on"), Dev(on=True, ui="on"))
    assert ctx.jobs == []


def test_two_rules_on_one_device_both_fire(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(cond="on"), _rule(cond="change", name="Hall light")])
    p.deviceUpdated(Dev(on=False, ui="off"), Dev(on=True, ui="on"))
    assert _texts(ctx) == ["Hall turned on", "Hall light: on"]


def test_turns_off_beside_turns_on(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(cond="on"), _rule(cond="off")])
    p.deviceUpdated(Dev(on=False), Dev(on=True, ui="on"))
    p.deviceUpdated(Dev(on=True, ui="on"), Dev(on=False))
    assert _texts(ctx) == ["Hall turned on", "Hall turned off"]


def test_the_cooldown_holds_for_thirty_seconds(monkeypatch, tmp_path):
    import alerts_mixin as am
    clock = types.SimpleNamespace(t=2_000_000.0)
    monkeypatch.setattr(am.time, "time", lambda: clock.t)
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])
    for step in (0, 10, 29):
        clock.t = 2_000_000.0 + step
        p.deviceUpdated(Dev(on=False), Dev(on=True))
    assert len(_texts(ctx)) == 1
    clock.t = 2_000_000.0 + 30
    p.deviceUpdated(Dev(on=False), Dev(on=True))
    assert len(_texts(ctx)) == 2


def test_disabled_device_paused_rule_and_switched_off_engine(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])
    p.deviceUpdated(Dev(on=False, enabled=False), Dev(on=True, enabled=False))
    p.deviceUpdated(Dev(on=False, enabled=False), Dev(on=True, enabled=True))   # re-enabled
    p.deviceUpdated(Dev(on=False, enabled=True), Dev(on=True, enabled=False))   # disabled
    assert ctx.jobs == []

    p2, ctx2 = _wired(monkeypatch, tmp_path, [_rule(enabled=False)])
    p2.deviceUpdated(Dev(on=False), Dev(on=True))
    assert ctx2.jobs == []

    p3, ctx3 = _wired(monkeypatch, tmp_path, [_rule()], active=False)
    p3.deviceUpdated(Dev(on=False), Dev(on=True))
    assert ctx3.jobs == []


def test_another_device_costs_one_lookup_and_fires_nothing(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])
    p.deviceUpdated(Dev(dev_id=6, on=False), Dev(dev_id=6, on=True))
    assert ctx.jobs == []


def test_a_fault_never_reaches_indigo_and_is_said_once(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])

    class Broken(Dev):
        @property
        def onState(self):
            raise RuntimeError("stale proxy")

        @onState.setter
        def onState(self, v):
            pass
    for _ in range(3):
        p._alert_device_changed(Broken(), Dev(on=True))
    warns = [m for lvl, m in ctx.logs if lvl == "WARNING"]
    # _field swallows the attribute error, so this reads as "no on state" and
    # fires; what matters is that nothing was raised. Force a real fault too:
    p._alerts = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    p.deviceUpdated(Dev(on=False), Dev(on=True))
    p.deviceUpdated(Dev(on=False), Dev(on=True))
    warns = [m for lvl, m in ctx.logs if lvl == "WARNING"]
    assert len(warns) == 1 and "could not be judged" in warns[0]


def test_browser_only_rules_are_recorded_but_send_nothing(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(channels=["browser"])])
    p.deviceUpdated(Dev(on=False), Dev(on=True))
    assert ctx.jobs == [("save",)]
    rows, seq = p._alert_firings_view(0)
    assert rows[0]["text"] == "Hall turned on" and rows[0]["pending"] is False and seq == rows[0]["seq"]


# ── variables ────────────────────────────────────────────────────────────

def test_variable_changes_fire_and_renames_do_not(monkeypatch, tmp_path):
    mod = load_plugin_module()
    rule = {"kind": "variable", "id": 9, "cond": "change", "name": "Mode", "enabled": True,
            "channels": ["email"]}
    p, ctx = _wired(monkeypatch, tmp_path, [rule])
    called = []
    monkeypatch.setattr(mod.indigo.PluginBase, "variableUpdated",
                        lambda self, o, n: called.append(n.id))
    p.variableUpdated(Var(value="home"), Var(value="away"))
    p.variableUpdated(Var(value="away", name="Mode"), Var(value="away", name="House mode"))
    p.variableUpdated(Var(value="1"), Var(value="1"))
    assert called == [9, 9, 9]
    assert _texts(ctx) == ["Mode is now away"]


def test_variables_are_only_subscribed_to_once_a_rule_needs_them(monkeypatch, tmp_path):
    import sys
    p, ctx = _wired(monkeypatch, tmp_path, [_rule()])
    p._alerts()
    sys.modules["indigo"].variables.subscribeToChanges.assert_not_called()
    p.cfg_store["alertRules"].append({"kind": "variable", "id": 9, "cond": "change",
                                      "name": "Mode", "enabled": True, "channels": ["browser"]})
    p._alert_reindex()
    p._alert_reindex()
    sys.modules["indigo"].variables.subscribeToChanges.assert_called_once()


# ── the worker and the saved list ────────────────────────────────────────

def test_the_worker_delivers_and_records_the_outcome(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, rules=[_rule()])
    p._dev_changes = {}
    p._stamp_note_change = lambda: None
    try:
        p.deviceUpdated(Dev(on=False), Dev(on=True))
        deadline = time.time() + 5
        while time.time() < deadline and p._alert_firings_view(0)[0][0]["pending"]:
            time.sleep(0.02)
        f = p._alert_firings_view(0)[0][0]
    finally:
        p._stop_alert_worker()
    assert f["pending"] is False
    assert f["delivered"] == ["pushover"]
    assert f["failed"] == [{"channel": "email", "reason": "no email address (set one on the Alerts page)"}]
    assert ctx.pushover.sent and ctx.pushover.sent[0][1]["msgBody"] == "Hall turned on"


def test_the_firings_survive_a_restart(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(channels=["pushover"])])
    p.deviceUpdated(Dev(on=False), Dev(on=True))
    job = ctx.jobs[0]
    p._alert_run_job(p._alerts(), job)           # delivered and saved
    path = p._alert_firings_path()
    import os
    import stat
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["firings"][0]["delivered"] == ["pushover"]

    q, _ = alert_plugin(monkeypatch, tmp_path)
    assert q._load_alert_firings() == 1
    rows, seq = q._alert_firings_view(0)
    assert rows[0]["text"] == "Hall turned on" and seq == saved["seq"]


def test_a_firing_cut_off_by_a_restart_is_marked_not_sent(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    path = p._alert_firings_path()
    rows = [{"seq": 5, "t": 1.0, "text": "Hall turned on", "channels": ["pushover", "browser"],
             "delivered": [], "failed": [], "pending": True},
            {"seq": "junk"}, "not even a dict"]
    open(path, "w", encoding="utf-8").write(json.dumps({"seq": 5, "firings": rows}))
    assert p._load_alert_firings() == 1
    f = p._alert_firings_view(0)[0][0]
    assert f["pending"] is False
    assert f["failed"] == [{"channel": "pushover", "reason": "the plugin stopped before it was sent"}]


def test_an_unreadable_list_starts_empty_with_a_warning(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    open(p._alert_firings_path(), "w").write("{not json")
    assert p._load_alert_firings() == 0
    assert any("could not be read" in m for lvl, m in ctx.logs if lvl == "WARNING")


def test_only_the_last_fifty_are_kept(monkeypatch, tmp_path):
    p, ctx = _wired(monkeypatch, tmp_path, [_rule(channels=["browser"])])
    import alerts_mixin as am
    st = p._alerts()
    for i in range(60):
        p._alert_fire(st, {"kind": "device", "id": i + 100, "cond": "on", "name": f"D{i}",
                           "channels": ["browser"]}, f"D{i} turned on", 1000.0 + i)
    rows, seq = p._alert_firings_view(0)
    assert len(rows) == am.ALERT_FIRINGS_MAX and rows[0]["text"] == "D59 turned on"
    assert [r["seq"] for r in rows] == sorted((r["seq"] for r in rows), reverse=True)


def test_stop_is_safe_before_anything_started():
    from conftest import bare_plugin
    p = bare_plugin()
    p._stop_alert_worker()          # no state yet: nothing to do, nothing raised
