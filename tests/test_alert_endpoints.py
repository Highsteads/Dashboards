#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_alert_endpoints.py
# Description: The Alerts page's endpoints (3.47.0). alertRules hands the page
#              every rule with its target's current value (or that it was
#              deleted), which channels are ready and the recent firings, and
#              in its light form only the firings a page has not seen.
#              saveAlertRules refuses junk with a clear error and saves nothing,
#              refuses a save from an out-of-date page, and moves a browser's
#              old rules only into an empty plugin, giving each the default
#              channels. sendTestAlert sends off the dispatch path and answers
#              per channel, pending until it is done, once per nonce. A Settings
#              save can neither set nor clear the alert keys. None of them is a
#              guest route, the menu item sends over every ready channel, and
#              the list_alerts MCP tool reads the same view without the key.
# Author:      CliveS & Claude
# Date:        25-09-2026
# Version:     1.0

import json
import re
import time
from pathlib import Path

import pytest

from conftest import FakePushover, alert_plugin

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "Dashboards.indigoPlugin/Contents/Server Plugin"
JSON_HDRS = {"Content-Type": "application/json", "Host": "192.168.1.10:8176"}


class Action:
    def __init__(self, body, headers=None):
        self.props = {"request_body": json.dumps(body) if not isinstance(body, str) else body,
                      "headers": dict(headers or JSON_HDRS)}


class Dev:
    def __init__(self, dev_id, name, on=False, ui="off", enabled=True):
        self.id, self.name, self.onState, self.displayStateValUi = dev_id, name, on, ui
        self.enabled = enabled


class Vars(dict):
    def subscribeToChanges(self):
        self.subscribed = True


class Var:
    def __init__(self, var_id, name, value):
        self.id, self.name, self.value = var_id, name, value


def _rule(**kw):
    r = {"kind": "device", "id": 5, "cond": "on", "name": "Hall", "enabled": True,
         "channels": ["pushover", "browser"]}
    r.update(kw)
    return r


def _plugin(monkeypatch, tmp_path, rules=None, **kw):
    import sys
    p, ctx = alert_plugin(monkeypatch, tmp_path, rules=rules, **kw)
    ind = sys.modules["indigo"]
    monkeypatch.setattr(ind, "devices", {5: Dev(5, "Hall light", on=True, ui="on"),
                                         6: Dev(6, "Shed", enabled=False)})
    monkeypatch.setattr(ind, "variables", Vars({9: Var(9, "Mode", "away")}))
    return p, ctx


# ── alertRules ───────────────────────────────────────────────────────────

def test_the_full_view(monkeypatch, tmp_path):
    rules = [_rule(), _rule(id=6, name="Shed"), _rule(id=77, name="Gone"),
             {"kind": "variable", "id": 9, "cond": "change", "name": "Mode", "enabled": True,
              "channels": ["email"]}]
    p, ctx = _plugin(monkeypatch, tmp_path, rules=rules, email="house@example.com")
    reply = p.handleAlertRules(Action({}))
    assert reply["status"] == 200
    v = reply["obj"]
    got = [(r["name"], r["target"], r["now"]) for r in v["rules"]]
    assert got == [("Hall", "ok", "on"), ("Shed", "disabled", "disabled"),
                   ("Gone", "missing", "deleted in Indigo"), ("Mode", "ok", "away")]
    assert v["rules"][0]["targetName"] == "Hall light"
    assert v["channels"]["pushover"] == {"ready": True, "status": "ready"}
    assert v["channels"]["email"] == {"ready": True, "status": "ready", "source": "settings"}
    assert v["defaultChannels"] == ["pushover", "browser"]
    assert v["defaultEmail"] == "house@example.com" and v["active"] is True
    assert v["max"] == 100 and v["rev"] == 0 and v["firings"] == []
    assert "uTEST" not in reply["content"], "the Pushover key never goes to a page"


def test_the_secrets_address_is_named_not_shown(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path)
    p.alert_email_secret = "hidden@example.com"
    reply = p.handleAlertRules(Action({}))
    assert reply["obj"]["emailSource"] == "secrets" and reply["obj"]["defaultEmail"] == ""
    assert "hidden@example.com" not in reply["content"]


def test_the_light_view_is_only_what_is_new(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()])
    p._alert_enqueue = lambda st, job: None
    st = p._alerts()
    a = p._alert_fire(st, _rule(), "Hall turned on", time.time())
    b = p._alert_fire(st, _rule(cond="off"), "Hall turned off", time.time())
    reply = p.handleAlertRules(Action({"firingsSince": a["seq"]}))["obj"]
    assert [f["text"] for f in reply["firings"]] == ["Hall turned off"]
    assert reply["seq"] == b["seq"] and reply["browserRules"] == 1
    assert "rules" not in reply, "the light form never walks the devices"
    assert p.handleAlertRules(Action({"firingsSince": "x"}))["status"] == 400


def test_the_light_view_says_no_browser_rules_when_switched_off(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()], active=False)
    assert p.handleAlertRules(Action({"firingsSince": 0}))["obj"]["browserRules"] == 0


# ── saveAlertRules ───────────────────────────────────────────────────────

def test_a_good_save_is_stored_indexed_and_counted(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path)
    body = {"rules": [_rule(), {"kind": "variable", "id": 9, "cond": "change", "name": "Mode",
                                "channels": ["email"]}],
            "active": True, "defaultEmail": "house@example.com", "rev": 0}
    reply = p.handleSaveAlertRules(Action(body))
    assert reply["status"] == 200, reply
    stored = ctx.saves[-1]
    assert [r["name"] for r in stored["alertRules"]] == ["Hall", "Mode"]
    assert stored["alertEmail"] == "house@example.com" and stored["alertRulesRev"] == 1
    assert reply["obj"]["rev"] == 1 and len(reply["obj"]["rules"]) == 2
    assert ("device", 5) in p._alerts()["index"] and ("variable", 9) in p._alerts()["index"]
    import sys
    assert getattr(sys.modules["indigo"].variables, "subscribed", False)


@pytest.mark.parametrize("body, needle", [
    ({"rules": [_rule(kind="scene")]}, "kind must be device or variable"),
    ({"rules": [_rule(id="5")]}, "id must be a whole"),
    ({"rules": [_rule(channels=["fax"])]}, "channels must be a list drawn from"),
    ({"rules": [_rule(email="nope")]}, "does not look like an email"),
    ({"rules": "all of them"}, "rules must be a list"),
    ({"rules": [_rule(id=i + 1) for i in range(101)]}, "at most 100 rules"),
    ({"defaultEmail": "not-an-address"}, "does not look like an email"),
    ({"active": "yes"}, "active must be true or false"),
])
def test_junk_is_refused_and_nothing_saved(monkeypatch, tmp_path, body, needle):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()])
    reply = p.handleSaveAlertRules(Action(body))
    assert reply["status"] == 400 and needle in reply["obj"]["error"], reply["obj"]
    assert ctx.saves == []


def test_a_stale_page_is_refused(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()])
    p.cfg_store["alertRulesRev"] = 4
    reply = p.handleSaveAlertRules(Action({"rules": [], "rev": 3}))
    assert reply["status"] == 409 and reply["obj"]["reason"] == "stale" and reply["obj"]["rev"] == 4
    assert ctx.saves == []
    assert p.handleSaveAlertRules(Action({"rules": [], "rev": 4}))["status"] == 200


def test_a_blank_default_email_clears_it(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, email="house@example.com")
    assert p.handleSaveAlertRules(Action({"defaultEmail": "  "}))["status"] == 200
    assert ctx.saves[-1]["alertEmail"] == ""


def test_saving_only_the_switch_keeps_the_rules(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()])
    assert p.handleSaveAlertRules(Action({"active": False}))["status"] == 200
    assert ctx.saves[-1]["alertRules"] == [_rule()] and ctx.saves[-1]["alertsActive"] is False
    assert p._alerts()["index"] == {}, "switched off: the callbacks have nothing to look up"


def test_a_failed_write_is_a_500_and_changes_nothing_live(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path)

    def boom(data):
        raise OSError("disk full")
    p._save_config_store = boom
    reply = p.handleSaveAlertRules(Action({"rules": [_rule()]}))
    assert reply["status"] == 500 and "disk full" in reply["obj"]["error"]
    assert p._alert_rules() == [] and p._alerts()["index"] == {}


def test_a_form_post_is_refused(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path)
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    assert p.handleSaveAlertRules(Action({"rules": []}, form))["status"] == 415
    assert p.handleSendTestAlert(Action({"channels": ["email"], "nonce": "abcdefgh1"}, form))["status"] == 415
    assert ctx.saves == []


# ── moving a browser's rules in ──────────────────────────────────────────

LEGACY = [{"kind": "device", "id": 5, "name": "Hall", "cond": "on", "enabled": True},
          {"kind": "variable", "id": 9, "name": "Mode", "cond": "change", "enabled": False}]


def test_migration_gives_the_old_rules_the_default_channels(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path)
    reply = p.handleSaveAlertRules(Action({"rules": LEGACY, "active": False, "migrate": True,
                                           "rev": 0}))
    assert reply["status"] == 200, reply["obj"]
    stored = ctx.saves[-1]["alertRules"]
    assert [r["channels"] for r in stored] == [["pushover", "browser"]] * 2
    assert stored[1]["enabled"] is False and ctx.saves[-1]["alertsActive"] is False
    assert any("moved from a browser" in m for lvl, m in ctx.logs if lvl == "INFO")


def test_migration_with_no_pushover_falls_back_to_email_then_browser(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, pushover_user="", email="house@example.com")
    p.handleSaveAlertRules(Action({"rules": LEGACY, "migrate": True}))
    assert ctx.saves[-1]["alertRules"][0]["channels"] == ["email", "browser"]
    q, qctx = _plugin(monkeypatch, tmp_path, pushover_user="")
    q.handleSaveAlertRules(Action({"rules": LEGACY, "migrate": True}))
    assert qctx.saves[-1]["alertRules"][0]["channels"] == ["browser"]


def test_migration_never_lands_on_rules_the_plugin_already_has(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule(id=6, name="Shed")])
    reply = p.handleSaveAlertRules(Action({"rules": LEGACY, "migrate": True}))
    assert reply["status"] == 409 and reply["obj"]["reason"] == "not_empty"
    assert "already has 1 rule" in reply["obj"]["error"] and ctx.saves == []


# ── the Settings page cannot touch them ──────────────────────────────────

def test_a_settings_save_keeps_the_alert_keys(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()], email="house@example.com")
    p.cfg_store["alertRulesRev"] = 3
    p.cameras, p.swap_out_host = [], ""
    p._write_config_js = p._build_rooms_json = p._build_scenes_json = lambda: None
    p._camera_login_withheld = lambda cams: []
    p.control_pin = ""
    reply = p._apply_config({"siteName": "Home", "alertRules": [], "alertsActive": False,
                             "alertEmail": "evil@example.com"})
    assert reply["status"] == 200, reply
    saved = ctx.saves[-1]
    assert saved["alertRules"] == [_rule()] and saved["alertsActive"] is True
    assert saved["alertEmail"] == "house@example.com" and saved["alertRulesRev"] == 3


def test_the_settings_editor_is_not_shown_them(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule()], email="house@example.com")
    p.cameras, p.swap_out_host, p.main_cameras, p.room_extras = [], "", [], {}
    p._hidden_scenes = lambda: set()
    p.control_pin, p.pin_required, p.favourites, p.custom_links = "", [], [], []
    eff = p._effective_config()
    assert not {"alertRules", "alertsActive", "alertEmail", "alertRulesRev"} & set(eff)


# ── sendTestAlert ────────────────────────────────────────────────────────

@pytest.fixture
def workers():
    started = []
    yield started
    for p in started:
        p._stop_offpath_workers()


def _with_workers(p, workers):
    p._start_offpath_workers()
    workers.append(p)
    return p


def test_a_test_alert_reports_each_channel(monkeypatch, tmp_path, workers):
    p, ctx = _plugin(monkeypatch, tmp_path)
    _with_workers(p, workers)
    reply = p.handleSendTestAlert(Action({"channels": ["pushover", "email", "browser"],
                                          "nonce": "abcdefgh1"}))
    assert reply["status"] == 200, reply
    res = reply["obj"]["results"]
    assert res["pushover"]["ok"] is True and res["browser"]["ok"] is True
    assert res["email"] == {"ok": False, "reason": "no email address (set one on the Alerts page)"}
    assert ctx.pushover.sent[0][1]["msgBody"] == "Test from Dashboards"
    assert any("test alert" in m for lvl, m in ctx.logs)


def test_a_slow_test_is_pending_then_collected_once(monkeypatch, tmp_path, workers):
    p, ctx = _plugin(monkeypatch, tmp_path, pushover=FakePushover(delay=1.2))
    _with_workers(p, workers)
    body = {"channels": ["pushover"], "nonce": "slow-one-123"}
    first = p.handleSendTestAlert(Action(body))
    assert first["status"] == 503 and first["obj"]["pending"] is True
    deadline = time.time() + 5
    reply = first
    while reply["status"] == 503 and time.time() < deadline:
        reply = p.handleSendTestAlert(Action(body))      # the same body, as DashUI.message resends it
    assert reply["status"] == 200 and reply["obj"]["results"]["pushover"]["ok"] is True
    assert len(ctx.pushover.sent) == 1, "asking again with the same nonce must not send again"


@pytest.mark.parametrize("body, needle", [
    ({"channels": ["email"]}, "nonce"),
    ({"channels": ["email"], "nonce": "short"}, "nonce"),
    ({"channels": [], "nonce": "abcdefgh1"}, "channels"),
    ({"channels": ["pigeon"], "nonce": "abcdefgh1"}, "channels"),
    ({"channels": ["email"], "nonce": "abcdefgh1", "email": "nope"}, "email address"),
])
def test_a_bad_test_request_is_a_400(monkeypatch, tmp_path, body, needle):
    p, ctx = _plugin(monkeypatch, tmp_path)
    reply = p.handleSendTestAlert(Action(body))
    assert reply["status"] == 400 and needle in reply["obj"]["error"]


# ── the menu item ────────────────────────────────────────────────────────

def test_the_menu_sends_over_every_ready_channel(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, email="house@example.com")
    jobs = []
    p._alert_enqueue = lambda st, job: jobs.append(job)
    assert p.menuSendTestAlert() is True
    assert jobs == [("test", ["pushover", "email"])]
    p._alert_run_job(p._alerts(), jobs[0])
    assert ctx.pushover.sent and ctx.server.sendEmailTo.called
    line = [m for lvl, m in ctx.logs if "test alert:" in m][-1]
    assert "Pushover sent" in line and "email sent" in line


def test_the_menu_with_nothing_set_up_says_what_to_do(monkeypatch, tmp_path):
    p, ctx = _plugin(monkeypatch, tmp_path, pushover_user="")
    jobs = []
    p._alert_enqueue = lambda st, job: jobs.append(job)
    p.menuSendTestAlert()
    assert jobs == []
    warn = [m for lvl, m in ctx.logs if lvl == "WARNING"]
    assert warn and "PUSHOVER_USER_TOKEN" in warn[0] and "no user key" in warn[0]


def test_the_menu_item_is_declared():
    xml = (SERVER / "MenuItems.xml").read_text(encoding="utf-8")
    assert re.search(r"<Name>Send Test Alert</Name>\s*<CallbackMethod>menuSendTestAlert</CallbackMethod>", xml)


# ── not a guest route ────────────────────────────────────────────────────

def test_no_guest_route_reaches_the_alerts():
    src = (SERVER / "cameras_mixin.py").read_text(encoding="utf-8")
    subs = set(re.findall(r'sub == "(\w+)"', src))
    assert subs and not any("alert" in s.lower() for s in subs), subs
    assert "handleAlertRules" not in src and "_alert_" not in src
    guest = (ROOT / "Dashboards.indigoPlugin/Contents/Resources/static/pages/guest.html").read_text(encoding="utf-8")
    assert "alertRules" not in guest and "dashboards-alerts.js" not in guest


# ── the MCP tool ─────────────────────────────────────────────────────────

def test_the_mcp_tool_lists_rules_channels_and_firings(monkeypatch, tmp_path):
    import mcp_tools
    p, ctx = _plugin(monkeypatch, tmp_path, rules=[_rule(), _rule(id=77, name="Gone")],
                     email="house@example.com")
    p._alert_enqueue = lambda st, job: None
    st = p._alerts()
    for i in range(3):
        p._alert_fire(st, _rule(id=100 + i, name=f"D{i}"), f"D{i} turned on", time.time())
    env = json.loads(mcp_tools.dispatch(p, "list_alerts", {"firings": 2}))
    assert env["status"] == "ok", env
    r = env["result"]
    assert [x["name"] for x in r["rules"]] == ["Hall", "Gone"] and r["missingTargets"] == ["Gone"]
    assert r["channels"]["pushover"]["ready"] is True and r["defaultEmail"] == "house@example.com"
    assert [f["text"] for f in r["recentFirings"]] == ["D2 turned on", "D1 turned on"]
    assert "uTEST" not in json.dumps(env), "never the Pushover key"
    bad = json.loads(mcp_tools.dispatch(p, "list_alerts", {"firings": 500}))
    assert bad["status"] == "error" and bad["error"]["type"] == "validation"
