#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_alert_delivery.py
# Description: How a fired alert rule reaches the owner (3.47.0): Pushover
#              through the Pushover plugin exactly as Log_Error_Watch.py sends
#              (getPlugin, enabled AND running, executeAction("send") with
#              msgTitle / msgUser / msgBody / msgSound / msgPriority), and email
#              through indigo.server.sendEmailTo to the rule's own address, the
#              Alerts page's default, or IndigoSecrets DASHBOARDS_ALERT_EMAIL.
#              Each failure mode is a result, never an exception: plugin
#              missing, not enabled, not running, raising, no user key, no
#              address. A failed channel is a WARNING at most once per half hour
#              per reason, never stops the others, and the user key is never
#              written to the log.
# Author:      CliveS & Claude
# Date:        25-09-2026
# Version:     1.0

import types

import pytest

from conftest import FakePushover, alert_plugin

KEY = "uTEST-USER-KEY-not-a-real-one"


def _am():
    import alerts_mixin
    return alerts_mixin


def _warnings(ctx):
    return [m for lvl, m in ctx.logs if lvl == "WARNING"]


# ── Pushover ─────────────────────────────────────────────────────────────

def test_pushover_is_sent_as_the_estate_sends_it(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    p.cfg_store["siteName"] = "Home"
    res = p._alert_deliver(["pushover"], "Hall turned on")
    assert res == {"pushover": {"ok": True, "reason": "sent"}}
    ctx.server.getPlugin.assert_called_with("io.thechad.indigoplugin.pushover")
    assert ctx.pushover.sent == [("send", {"msgTitle": "Home", "msgUser": KEY,
                                           "msgBody": "Hall turned on", "msgSound": "vibrate",
                                           "msgPriority": "0"})]
    assert _warnings(ctx) == []


def test_the_title_falls_back_to_dashboards(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    p._alert_deliver(["pushover"], "x")
    assert ctx.pushover.sent[0][1]["msgTitle"] == "Dashboards"


@pytest.mark.parametrize("plugin, reason", [
    (None, "Pushover plugin not installed"),
    (FakePushover(enabled=False), "Pushover plugin not enabled"),
    (FakePushover(running=False), "Pushover plugin not running"),
])
def test_pushover_unavailable(monkeypatch, tmp_path, plugin, reason):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    ctx.server.getPlugin.side_effect = lambda pid: plugin
    res = p._alert_deliver(["pushover"], "x")
    assert res["pushover"] == {"ok": False, "reason": reason}
    assert any(reason in w for w in _warnings(ctx))


def test_get_plugin_raising_is_a_result(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    ctx.server.getPlugin.side_effect = RuntimeError("no such plugin")
    res = p._alert_deliver(["pushover"], "x")
    assert res["pushover"]["ok"] is False and "unavailable" in res["pushover"]["reason"]


def test_is_running_raising_counts_as_not_running(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    ctx.pushover.isRunning = lambda: (_ for _ in ()).throw(RuntimeError("ipc"))
    assert p._alert_deliver(["pushover"], "x")["pushover"]["reason"] == "Pushover plugin not running"


def test_execute_action_raising_never_leaks_the_key(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path,
                          pushover=FakePushover(raises=RuntimeError(f"bad user {KEY}")))
    res = p._alert_deliver(["pushover"], "x")
    assert res["pushover"]["ok"] is False
    assert KEY not in res["pushover"]["reason"] and "refused" in res["pushover"]["reason"]
    everything = " ".join(m for _, m in ctx.logs) + repr(p.logger.mock_calls)
    assert KEY not in everything


def test_no_user_key_does_not_even_ask_the_plugin(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, pushover_user="")
    res = p._alert_deliver(["pushover"], "x")
    assert res["pushover"]["ok"] is False and "no Pushover user key" in res["pushover"]["reason"]
    ctx.server.getPlugin.assert_not_called()


# ── email ────────────────────────────────────────────────────────────────

def test_email_goes_to_the_rules_own_address_first(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, email="house@example.com")
    rule = {"name": "Hall", "kind": "device", "id": 5, "cond": "on"}
    res = p._alert_deliver(["email"], "Hall turned on", email="rule@example.com", rule=rule)
    assert res["email"] == {"ok": True, "reason": "sent"}
    args, kwargs = ctx.server.sendEmailTo.call_args
    assert args == ("rule@example.com",)
    assert kwargs["subject"] == "Dashboards: Hall turned on"
    assert "Hall turned on" in kwargs["body"] and "Rule: Hall (device 5, on)" in kwargs["body"]


def test_email_then_the_pages_default_then_indigosecrets(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, email="house@example.com")
    p.alert_email_secret = "secret@example.com"
    p._alert_deliver(["email"], "x")
    assert ctx.server.sendEmailTo.call_args[0] == ("house@example.com",)
    p.cfg_store["alertEmail"] = ""
    p._alert_deliver(["email"], "x")
    assert ctx.server.sendEmailTo.call_args[0] == ("secret@example.com",)
    assert p._alert_default_email() == ("secret@example.com", "secrets")


def test_no_address_anywhere_is_a_result(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    res = p._alert_deliver(["email"], "x")
    assert res["email"]["ok"] is False and "no email address" in res["email"]["reason"]
    ctx.server.sendEmailTo.assert_not_called()


def test_send_email_raising_is_a_result(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, email="house@example.com")
    ctx.server.sendEmailTo.side_effect = RuntimeError("SMTP not configured")
    res = p._alert_deliver(["email"], "x")
    assert res["email"]["ok"] is False and "SMTP not configured" in res["email"]["reason"]


# ── channels are independent ─────────────────────────────────────────────

def test_a_dead_channel_does_not_block_the_others(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, email="house@example.com",
                          pushover=FakePushover(running=False))
    res = p._alert_deliver(["pushover", "email", "browser"], "x")
    assert res["pushover"]["ok"] is False
    assert res["email"]["ok"] is True and ctx.server.sendEmailTo.called
    assert res["browser"]["ok"] is True


def test_a_sender_that_raises_is_caught_by_the_loop(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, email="house@example.com")
    p._alert_send_pushover = lambda text: 1 / 0
    res = p._alert_deliver(["pushover", "email"], "x")
    assert res["pushover"]["ok"] is False and "ZeroDivisionError" in res["pushover"]["reason"]
    assert res["email"]["ok"] is True


# ── the WARNING is rate-limited ──────────────────────────────────────────

def test_a_dead_pushover_plugin_warns_once_per_half_hour(monkeypatch, tmp_path):
    am = _am()
    clock = types.SimpleNamespace(t=1_000_000.0)
    monkeypatch.setattr(am.time, "time", lambda: clock.t)
    p, ctx = alert_plugin(monkeypatch, tmp_path, pushover=FakePushover(running=False))
    for _ in range(5):
        p._alert_deliver(["pushover"], "x")
        clock.t += 60
    assert len(_warnings(ctx)) == 1, _warnings(ctx)
    assert p.logger.debug.called
    clock.t += am.ALERT_WARN_GAP_S
    p._alert_deliver(["pushover"], "x")
    assert len(_warnings(ctx)) == 2


def test_a_different_reason_is_said_at_once(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, pushover=FakePushover(running=False))
    p._alert_deliver(["pushover"], "x")
    ctx.pushover.running, ctx.pushover.enabled = True, False
    p._alert_deliver(["pushover"], "x")
    assert len(_warnings(ctx)) == 2


def test_recovery_is_said_once_and_rearms_the_warning(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path, pushover=FakePushover(running=False))
    p._alert_deliver(["pushover"], "x")
    ctx.pushover.running = True
    p._alert_deliver(["pushover"], "x")
    p._alert_deliver(["pushover"], "x")
    again = [m for lvl, m in ctx.logs if lvl == "INFO" and "delivered again" in m]
    assert len(again) == 1
    ctx.pushover.running = False
    p._alert_deliver(["pushover"], "x")
    assert len(_warnings(ctx)) == 2, "a new outage after a recovery is said straight away"


# ── what the page is told is ready ───────────────────────────────────────

def test_channel_status_and_the_default_channels(monkeypatch, tmp_path):
    p, ctx = alert_plugin(monkeypatch, tmp_path)
    s = p._alert_channel_status()
    assert s["pushover"] == {"ready": True, "status": "ready"}
    assert s["email"]["ready"] is False and s["email"]["status"] == "no address"
    assert p._alert_default_channels() == ["pushover", "browser"]

    ctx.pushover.running = False
    assert p._alert_channel_status()["pushover"] == {"ready": False, "status": "plugin not running"}
    assert p._alert_default_channels() == ["browser"]
    p.cfg_store["alertEmail"] = "house@example.com"
    assert p._alert_default_channels() == ["email", "browser"]

    p.pushover_user = ""
    assert p._alert_channel_status()["pushover"] == {"ready": False, "status": "no user key"}
