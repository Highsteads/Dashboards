#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    alerts_mixin.py
# Description: The Alerts page's rules, kept and judged by the plugin (3.47.0).
#              Until 3.46.0 the rules lived in each browser's localStorage and
#              were judged by page JavaScript, so a rule only fired while a
#              dashboard tab was open, and only as a browser notification,
#              which needs an https address. They now live in the settings
#              store (alertRules, alertsActive, alertEmail) and are judged here
#              on Indigo's own change callbacks, with no page open, and each
#              firing is delivered by Pushover (through the Pushover plugin,
#              as Log_Error_Watch.py sends), by email (Indigo's own mail
#              settings), and/or offered to open pages ("browser").
#
#              The judgement is a straight port of dashboards-alerts.js
#              (judgeDevice, judgeVariable, ruleKey, the 30 s per-rule
#              cooldown, every rule on a device judged against the SAME
#              earlier reading). tests/lib/alert_rule_cases.json holds both
#              to the same answers, case for case.
#
#              Nothing here blocks the Indigo callback thread: a firing is
#              decided and recorded there (all in memory), and the sending is
#              handed to one worker thread. A channel that fails is logged as
#              a WARNING at most once per ALERT_WARN_GAP_S per reason and never
#              stops the other channels.
#              Plugin inherits this.
# Author:      CliveS & Claude
# Date:        25-09-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import collections
import json
import math
import os
import queue
import re
import threading
import time
from datetime import datetime

from dash_common import log

# ============================================================
# Constants
# ============================================================

ALERT_KINDS      = ("device", "variable")
ALERT_CONDS      = {"device": ("on", "off", "change"), "variable": ("change",)}
ALERT_CHANNELS   = ("pushover", "email", "browser")
ALERT_RULES_MAX  = 100
ALERT_NAME_MAX   = 80
ALERT_EMAIL_MAX  = 254
ALERT_COOLDOWN_S = 30.0             # per rule, so a chattering sensor cannot send twenty
ALERT_FIRINGS_MAX = 50              # the recent-firings list the pages read
ALERT_WARN_GAP_S = 1800.0           # one WARNING per channel and reason per half hour
ALERT_BROWSER_WINDOW_S = 600        # a page raises a firing no older than this
ALERT_TEST_TTL_S = 300              # how long a test's answer is kept for the page to collect
PUSHOVER_PLUGIN_ID = "io.thechad.indigoplugin.pushover"
ALERT_TEST_TEXT  = "Test from Dashboards"

# Plausible, not RFC 5322: one @, no spaces, commas, semicolons, angle brackets
# or quotes (each of which would let one field carry a second recipient or a
# header), and a dotted domain.
_EMAIL_RE = re.compile(
    r"^[^@\s,;<>\"'()\[\]\\]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# JavaScript's `undefined`, for the port below: String(undefined) is
# "undefined", String(null) is "null", and a rule read from a page could have
# either.
_UNDEFINED = object()


# ============================================================
# The rule semantics — a port of dashboards-alerts.js, pure
# ============================================================

def js_str(value):
    """String(value) as JavaScript writes it, for the values a device or a
    variable can carry. Used so the texts and comparisons match the page's
    word for word: String(true) is "true", String(12.0) is "12"."""
    if value is _UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return repr(value)
    return str(value)


def _js_truthy(value):
    """!!value in JavaScript."""
    if value is None or value is _UNDEFINED or value is False:
        return False
    if isinstance(value, (int, float)):
        return not (value == 0 or (isinstance(value, float) and math.isnan(value)))
    if isinstance(value, str):
        return value != ""
    return True


def _field(obj, name):
    """obj.name for an Indigo object, obj[name] for a dict; _UNDEFINED when absent."""
    if isinstance(obj, dict):
        return obj.get(name, _UNDEFINED)
    try:
        return getattr(obj, name)
    except Exception:
        return _UNDEFINED


def rule_key(rule):
    """ruleKey: kind:id:cond. The cooldown is per key, so two rules on one
    device with different conditions each keep their own."""
    return (f"{js_str(rule.get('kind', _UNDEFINED))}:{js_str(rule.get('id', _UNDEFINED))}:"
            f"{js_str(rule.get('cond', _UNDEFINED))}")


def device_now(dev):
    """deviceNow: {on, ui} from an Indigo device (or a dict shaped like the
    REST API's device)."""
    ui = _field(dev, "displayStateValUi")
    return {"on": _js_truthy(_field(dev, "onState")),
            "ui": "" if ui is None or ui is _UNDEFINED else js_str(ui)}


def device_text(now):
    """deviceText: the display value, or ON / OFF when there is none."""
    return now["ui"] or ("ON" if now["on"] else "OFF")


def judge_device(rule, was, now):
    """judgeDevice: the alert text for a device rule, or None. `was` is the
    earlier reading of the same device and `now` this one (both device_now)."""
    if was is None or now is None:
        return None
    name, cond = js_str(rule.get("name", _UNDEFINED)), rule.get("cond")
    if cond == "on" and now["on"] and not was["on"]:
        return f"{name} turned on"
    if cond == "off" and not now["on"] and was["on"]:
        return f"{name} turned off"
    if cond == "change" and (now["on"] != was["on"] or now["ui"] != was["ui"]):
        return f"{name}: {device_text(now)}"
    return None


def judge_variable(rule, was, value):
    """judgeVariable: `was` is {"val": <the earlier value as a string>}. Any
    change of value fires; the condition is not consulted (a variable rule's
    only condition is "change")."""
    if was is None:
        return None
    text = js_str(value)
    return f"{js_str(rule.get('name', _UNDEFINED))} is now {text}" if text != was["val"] else None


class Cooldown:
    """The per-rule cooldown the page's claim() kept: a key that fired less
    than `seconds` ago does not fire again. A clock that has gone backwards
    (now before the last firing) lets it fire, as the page did."""

    def __init__(self, seconds=ALERT_COOLDOWN_S):
        self.seconds = float(seconds)
        self._last = {}
        self._lock = threading.Lock()

    def claim(self, key, now):
        with self._lock:
            last = self._last.get(key)
            if last is not None and now >= last and now - last < self.seconds:
                return False
            self._last[key] = now
            # Nothing older than a day matters to a 30 s cooldown.
            if len(self._last) > 500:
                self._last = {k: t for k, t in self._last.items() if now - t < 86400}
            return True


def plausible_email(text):
    return (isinstance(text, str) and 3 <= len(text) <= ALERT_EMAIL_MAX
            and _EMAIL_RE.match(text) is not None)


def validate_rules(rules, default_channels):
    """(clean, errors) for a list of rules sent by a page or an old browser.

    Each rule: {kind, id, cond, name, enabled?, channels?, email?}. A rule with
    no `channels` key gets `default_channels` (how a rule moved from a browser,
    which never had channels, is given some). Anything else malformed is an
    error naming the rule; nothing is saved while there is one."""
    errors = []
    if not isinstance(rules, list):
        return [], ["rules must be a list"]
    if len(rules) > ALERT_RULES_MAX:
        return [], [f"at most {ALERT_RULES_MAX} rules can be kept (this list has {len(rules)})"]
    clean, seen = [], {}
    for i, r in enumerate(rules):
        where = f"rule {i + 1}"
        if not isinstance(r, dict):
            errors.append(f"{where} must be an object")
            continue
        kind = r.get("kind")
        if kind not in ALERT_KINDS:
            errors.append(f"{where}: kind must be device or variable")
            continue
        rid = r.get("id")
        if isinstance(rid, bool) or not isinstance(rid, int) or rid <= 0:
            errors.append(f"{where}: id must be a whole Indigo {kind} id")
            continue
        cond = r.get("cond")
        if cond not in ALERT_CONDS[kind]:
            errors.append(f"{where}: condition must be one of {', '.join(ALERT_CONDS[kind])}"
                          f" for a {kind}")
            continue
        name = r.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: name must be some text")
            continue
        enabled = r.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{where}: enabled must be true or false")
            continue
        if "channels" in r:
            chans = r.get("channels")
            if not isinstance(chans, list) or any(c not in ALERT_CHANNELS for c in chans):
                errors.append(f"{where}: channels must be a list drawn from "
                              f"{', '.join(ALERT_CHANNELS)}")
                continue
            chans = [c for c in ALERT_CHANNELS if c in chans]
            if not chans:
                errors.append(f"{where}: choose at least one way to be told")
                continue
        else:
            chans = list(default_channels)
        email = r.get("email")
        if email is not None and email != "":
            if not plausible_email(email.strip() if isinstance(email, str) else email):
                errors.append(f"{where}: {str(email)[:60]!r} does not look like an email address")
                continue
            email = email.strip()
        else:
            email = ""
        key = rule_key({"kind": kind, "id": rid, "cond": cond})
        if key in seen:
            errors.append(f"{where} repeats rule {seen[key] + 1} (same {kind} and condition)")
            continue
        seen[key] = i
        item = {"kind": kind, "id": rid, "cond": cond, "name": name.strip()[:ALERT_NAME_MAX],
                "enabled": enabled, "channels": chans}
        if email:
            item["email"] = email
        clean.append(item)
    return clean, errors


# ============================================================
# The mixin
# ============================================================

class AlertsMixin:

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------
    def _alerts(self):
        """The alert engine's state, built on first use so a callback or a
        handler can never race startup()."""
        st = self.__dict__.get("_alert_store")
        if st is None:
            st = self.__dict__["_alert_store"] = {
                "lock":     threading.RLock(),
                "index":    {},                    # ("device", id) -> [rule, ...]
                "cooldown": Cooldown(),
                "firings":  collections.deque(maxlen=ALERT_FIRINGS_MAX),
                "seq":      0,
                "queue":    queue.Queue(),
                "thread":   None,
                "stop":     threading.Event(),
                "warned":   {},                    # (channel, reason) -> last WARNING time
                "failing":  set(),                 # channels whose last attempt failed
                "var_sub":  False,
            }
            self._alert_reindex(st)
        return st

    def _alert_rules(self):
        rules = (getattr(self, "cfg_store", None) or {}).get("alertRules")
        return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []

    def _alerts_active(self):
        return (getattr(self, "cfg_store", None) or {}).get("alertsActive") is not False

    def _alert_reindex(self, st=None):
        """Rebuild the lookup the callbacks use: enabled rules by target.
        Empty while the master switch is off, so a callback costs one dict miss."""
        st = st or self._alerts()
        index = {}
        if self._alerts_active():
            for r in self._alert_rules():
                if r.get("enabled", True) is not False:
                    index.setdefault((r.get("kind"), r.get("id")), []).append(r)
        with st["lock"]:
            st["index"] = index
        if any(k[0] == "variable" for k in index):
            self._alert_subscribe_variables(st)

    def _alert_subscribe_variables(self, st=None):
        """Variable changes reach the plugin only once it subscribes, and every
        variable write in the house then costs a callback, so this waits for
        the first variable rule. There is no unsubscribe; a restart drops it."""
        st = st or self._alerts()
        if st["var_sub"]:
            return
        try:
            indigo.variables.subscribeToChanges()
            st["var_sub"] = True
        except Exception as exc:
            log(f"[Alerts] could not subscribe to variable changes, so variable rules will "
                f"not fire: {exc}", level="WARNING")

    # --------------------------------------------------------
    # Callbacks (Indigo's thread: in memory only, never raises)
    # --------------------------------------------------------
    # Why callbacks and not a poll: Indigo hands the plugin both the old and
    # the new copy of a device on every change (deviceUpdated), which is
    # exactly the "earlier reading" the page's poll had to keep for itself,
    # and it arrives the moment the change happens rather than up to 3 s (10 s
    # for variables) later. The plugin already subscribes to device changes
    # for the changedSince ledger, so device rules add no traffic at all. A
    # poll would miss an on-then-off inside one period, and cost a walk of
    # every watched device on the loop whether anything moved or not.

    def _alert_device_changed(self, orig_dev, new_dev):
        try:
            st = self._alerts()
            rules = st["index"].get(("device", getattr(new_dev, "id", None)))
            if not rules:
                return
            # A disabled device is skipped quietly, and so is the change that
            # disables or re-enables one: that is not the thing itself moving.
            if not getattr(new_dev, "enabled", True) or not getattr(orig_dev, "enabled", True):
                return
            was, now = device_now(orig_dev), device_now(new_dev)
            if was == now:
                return                   # a state write that changed nothing we judge
            t = time.time()
            # Every rule on the device is judged against the SAME earlier
            # reading, so "turns off" beside "turns on" fires too.
            for r in rules:
                text = judge_device(r, was, now)
                if text:
                    self._alert_fire(st, r, text, t)
        except Exception as exc:          # never into Indigo's callback
            self._alert_callback_fault(exc)

    def _alert_variable_changed(self, orig_var, new_var):
        try:
            st = self._alerts()
            rules = st["index"].get(("variable", getattr(new_var, "id", None)))
            if not rules:
                return
            before = getattr(orig_var, "value", None)
            after = getattr(new_var, "value", None)
            was = {"val": js_str(before)}
            if was["val"] == js_str(after):
                return                   # a rename, or the same value written again
            t = time.time()
            for r in rules:
                text = judge_variable(r, was, after)
                if text:
                    self._alert_fire(st, r, text, t)
        except Exception as exc:
            self._alert_callback_fault(exc)

    def _alert_callback_fault(self, exc):
        try:
            if not self.__dict__.get("_alert_cb_logged"):
                self.__dict__["_alert_cb_logged"] = True
                log(f"[Alerts] a change could not be judged against the alert rules: "
                    f"{type(exc).__name__}: {exc}", level="WARNING")
            else:
                self.logger.debug(f"[Alerts] judge failed again: {exc}")
        except Exception:
            pass

    def _alert_fire(self, st, rule, text, t):
        """Record one firing and hand its delivery to the worker. In memory
        only: this runs on the callback thread."""
        if not st["cooldown"].claim(rule_key(rule), t):
            return None
        chans = [c for c in (rule.get("channels") or []) if c in ALERT_CHANNELS]
        with st["lock"]:
            st["seq"] = max(st["seq"] + 1, int(t * 1000))
            firing = {"seq": st["seq"], "t": t, "key": rule_key(rule), "text": text,
                      "kind": rule.get("kind"), "id": rule.get("id"),
                      "name": rule.get("name"), "cond": rule.get("cond"),
                      "channels": chans, "delivered": [], "failed": [],
                      "pending": any(c != "browser" for c in chans)}
            st["firings"].appendleft(firing)
        if firing["pending"]:
            self._alert_enqueue(st, ("fire", firing, rule.get("email") or ""))
        else:
            self._alert_enqueue(st, ("save",))
        return firing

    # --------------------------------------------------------
    # The worker (all sending and file writing happens here)
    # --------------------------------------------------------
    def _alert_enqueue(self, st, job):
        th = st["thread"]
        if th is None or not th.is_alive():
            self._start_alert_worker()
        st["queue"].put(job)

    def _start_alert_worker(self):
        st = self._alerts()
        with st["lock"]:
            th = st["thread"]
            if th is not None and th.is_alive():
                return
            st["stop"].clear()
            th = st["thread"] = threading.Thread(target=self._alert_worker_main, args=(st,),
                                                 name="dashboards-alerts", daemon=True)
        th.start()

    def _stop_alert_worker(self):
        """Wake the worker and wait a second at most (the shutdown budget).
        Deliveries still queued are dropped: the plugin is going away."""
        st = self.__dict__.get("_alert_store")
        if not st:
            return
        st["stop"].set()
        st["queue"].put(None)
        th = st["thread"]
        if th is not None and th.is_alive():
            th.join(timeout=1.0)
        st["thread"] = None

    def _alert_worker_main(self, st):
        while True:
            job = st["queue"].get()
            if job is None or st["stop"].is_set():
                return
            try:
                self._alert_run_job(st, job)
            except Exception as exc:       # one bad job must not end the worker
                try:
                    log(f"[Alerts] delivery job failed: {type(exc).__name__}: {exc}",
                        level="WARNING")
                except Exception:
                    pass

    def _alert_run_job(self, st, job):
        kind = job[0]
        if kind == "fire":
            _, firing, email = job
            wanted = [c for c in firing["channels"] if c != "browser"]
            results = self._alert_deliver(wanted, firing["text"], email=email, rule=firing)
            with st["lock"]:
                firing["delivered"] = [c for c in wanted if results[c]["ok"]]
                firing["failed"] = [{"channel": c, "reason": results[c]["reason"]}
                                    for c in wanted if not results[c]["ok"]]
                firing["pending"] = False
            self.logger.debug(f"[Alerts] fired: {firing['text']} "
                              f"(sent: {', '.join(firing['delivered']) or 'none'})")
            self._save_alert_firings()
        elif kind == "save":
            self._save_alert_firings()
        elif kind == "test":
            _, channels = job
            results = self._alert_deliver(channels, ALERT_TEST_TEXT, test=True)
            self._alert_log_test(results)

    # --------------------------------------------------------
    # Delivery
    # --------------------------------------------------------
    def _alert_title(self):
        site = str((getattr(self, "cfg_store", None) or {}).get("siteName") or "").strip()
        return site or "Dashboards"

    def _alert_deliver(self, channels, text, email="", rule=None, test=False):
        """Send `text` over each channel in turn. Returns {channel: {"ok", "reason"}}.
        Never raises; one channel failing never stops the next."""
        results = {}
        for ch in channels:
            try:
                if ch == "pushover":
                    ok, reason = self._alert_send_pushover(text)
                elif ch == "email":
                    ok, reason = self._alert_send_email(text, email, rule=rule)
                elif ch == "browser":
                    ok, reason = True, "raised by the open pages"
                else:
                    ok, reason = False, "unknown channel"
            except Exception as exc:        # belt: each sender already catches
                ok, reason = False, f"{type(exc).__name__}: {exc}"
            results[ch] = {"ok": bool(ok), "reason": reason or ""}
            if ch != "browser":
                self._alert_note_result(ch, ok, reason, test=test)
        return results

    def _alert_pushover_user(self):
        return str(getattr(self, "pushover_user", "") or "").strip()

    def _alert_pushover_plugin(self):
        """(plugin, "") when the Pushover plugin can take a message now, else
        (None, why). Enabled AND running, as Log_Error_Watch.py insists: an
        enabled plugin that has crashed swallows executeAction without a word."""
        try:
            plug = indigo.server.getPlugin(PUSHOVER_PLUGIN_ID)
        except Exception as exc:
            return None, f"Pushover plugin unavailable ({type(exc).__name__})"
        if not plug:
            return None, "Pushover plugin not installed"
        try:
            enabled = bool(plug.isEnabled())
        except Exception:
            enabled = False
        if not enabled:
            return None, "Pushover plugin not enabled"
        try:
            running = bool(plug.isRunning())
        except Exception:
            running = False
        if not running:
            return None, "Pushover plugin not running"
        return plug, ""

    def _alert_send_pushover(self, text):
        user = self._alert_pushover_user()
        if not user:
            return False, "no Pushover user key (PUSHOVER_USER_TOKEN)"
        plug, why = self._alert_pushover_plugin()
        if plug is None:
            return False, why
        props = {
            "msgTitle":    self._alert_title(),
            "msgUser":     user,
            "msgBody":     text,
            "msgSound":    "vibrate",
            "msgPriority": "0",
        }
        try:
            plug.executeAction("send", props=props)
        except Exception as exc:
            # The user key must never reach the log, even inside an exception.
            detail = str(exc).replace(user, "…") if user else str(exc)
            return False, f"Pushover plugin refused the message: {detail[:160]}"
        return True, "sent"

    def _alert_default_email(self):
        """(address, source): the Alerts page's default, else IndigoSecrets
        DASHBOARDS_ALERT_EMAIL, else ("", "none")."""
        saved = str((getattr(self, "cfg_store", None) or {}).get("alertEmail") or "").strip()
        if saved:
            return saved, "settings"
        sec = str(getattr(self, "alert_email_secret", "") or "").strip()
        if sec and plausible_email(sec):
            return sec, "secrets"
        return "", "none"

    def _alert_send_email(self, text, email="", rule=None):
        to = (email or "").strip() or self._alert_default_email()[0]
        if not to:
            return False, "no email address (set one on the Alerts page)"
        title = self._alert_title()
        when = datetime.now().strftime("%H:%M:%S on %d-%b-%Y")
        lines = [text, "", f"At {when}."]
        if rule:
            lines.append(f"Rule: {rule.get('name')} ({rule.get('kind')} {rule.get('id')}, "
                         f"{rule.get('cond')}).")
        lines += ["", "Sent by the Dashboards plugin. The rules are on the dashboards' "
                      "Alerts page."]
        try:
            indigo.server.sendEmailTo(to, subject=f"{title}: {text}"[:200], body="\n".join(lines))
        except Exception as exc:
            return False, f"Indigo could not send the email: {str(exc)[:160]}"
        return True, "sent"

    def _alert_note_result(self, channel, ok, reason, test=False):
        """A failed channel is a WARNING, once per channel and reason per
        ALERT_WARN_GAP_S, so a Pushover plugin left stopped cannot fill the
        log. The first success after a failure says so once."""
        st = self._alerts()
        label = {"pushover": "Pushover", "email": "Email"}.get(channel, channel)
        now = time.time()
        if ok:
            with st["lock"]:
                was_failing = channel in st["failing"]
                st["failing"].discard(channel)
                if was_failing:
                    st["warned"] = {k: v for k, v in st["warned"].items() if k[0] != channel}
            if was_failing:
                log(f"[Alerts] {label} alerts are being delivered again")
            return
        key = (channel, reason)
        with st["lock"]:
            st["failing"].add(channel)
            last = st["warned"].get(key)
            loud = last is None or now - last >= ALERT_WARN_GAP_S
            if loud:
                st["warned"][key] = now
        if loud:
            log(f"[Alerts] {label} alert not delivered: {reason}"
                + ("" if test else " (said once per half hour; the other channels are unaffected)"),
                level="WARNING")
        else:
            self.logger.debug(f"[Alerts] {label} alert not delivered: {reason}")

    def _alert_log_test(self, results):
        parts = []
        for ch, res in results.items():
            label = {"pushover": "Pushover", "email": "email", "browser": "browser"}.get(ch, ch)
            parts.append(f"{label} {'sent' if res['ok'] else 'failed (' + res['reason'] + ')'}")
        log(f"[Alerts] test alert: {'; '.join(parts) if parts else 'no channel to send it on'}")

    # --------------------------------------------------------
    # What can be used, and the defaults
    # --------------------------------------------------------
    def _alert_channel_status(self):
        """{"pushover": {ready, status}, "email": {ready, status, source}}. Reads
        the Pushover plugin's state, which is a quick local call."""
        if not self._alert_pushover_user():
            push = {"ready": False, "status": "no user key"}
        else:
            plug, why = self._alert_pushover_plugin()
            push = ({"ready": True, "status": "ready"} if plug is not None
                    else {"ready": False, "status": why.replace("Pushover ", "")})
        addr, src = self._alert_default_email()
        mail = ({"ready": True, "status": "ready", "source": src} if addr
                else {"ready": False, "status": "no address", "source": "none"})
        return {"pushover": push, "email": mail}

    def _alert_default_channels(self, status=None):
        """A new rule's channels: Pushover if it is set up, else email if there
        is an address, plus the browser."""
        s = status or self._alert_channel_status()
        if s["pushover"]["ready"]:
            return ["pushover", "browser"]
        if s["email"]["ready"]:
            return ["email", "browser"]
        return ["browser"]

    def _alert_firings_view(self, since=0):
        st = self._alerts()
        with st["lock"]:
            rows = [dict(f, delivered=list(f["delivered"]), failed=[dict(x) for x in f["failed"]],
                         channels=list(f["channels"]))
                    for f in st["firings"] if f["seq"] > since]
            seq = st["seq"]
        return rows, seq

    def _alert_target(self, rule):
        """(state, now_text, current_name) for a rule's device or variable:
        state is "ok", "disabled" or "missing"."""
        try:
            if rule.get("kind") == "device":
                dev = indigo.devices[rule.get("id")]
                if not getattr(dev, "enabled", True):
                    return "disabled", "disabled", dev.name
                return "ok", device_text(device_now(dev)), dev.name
            var = indigo.variables[rule.get("id")]
            return "ok", js_str(var.value), var.name
        except Exception:
            return "missing", "deleted in Indigo", ""

    # --------------------------------------------------------
    # Firings that survive a restart
    # --------------------------------------------------------
    def _alert_firings_path(self):
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "alert_firings.json")

    def _save_alert_firings(self):
        """Write the recent firings beside the settings store (0600, atomic).
        Worker thread only. A failure is logged once and the list stays in
        memory."""
        st = self._alerts()
        with st["lock"]:
            data = {"seq": st["seq"], "firings": [dict(f) for f in st["firings"]]}
        try:
            path = self._alert_firings_path()
            text = json.dumps(data, allow_nan=False)
            tmp = f"{path}.tmp.{threading.get_ident()}"
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        except Exception as exc:
            if not self.__dict__.get("_alert_save_logged"):
                self.__dict__["_alert_save_logged"] = True
                log(f"[Alerts] could not save the recent alerts list ({exc}); it is kept "
                    f"in memory until the plugin restarts", level="WARNING")

    def _load_alert_firings(self):
        """Read the list back at startup. Anything malformed is dropped; a
        firing still being sent when the plugin stopped is marked as not sent."""
        st = self._alerts()
        try:
            path = self._alert_firings_path()
            if not os.path.isfile(path):
                return 0
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log(f"[Alerts] the saved recent alerts could not be read ({exc}); starting "
                f"with an empty list", level="WARNING")
            return 0
        rows = []
        for f in (data.get("firings") if isinstance(data, dict) else None) or []:
            if not isinstance(f, dict) or not isinstance(f.get("seq"), int) \
                    or not isinstance(f.get("t"), (int, float)) or not isinstance(f.get("text"), str):
                continue
            f = dict(f)
            f["channels"] = [c for c in (f.get("channels") or []) if c in ALERT_CHANNELS]
            f["delivered"] = [c for c in (f.get("delivered") or []) if c in ALERT_CHANNELS]
            f["failed"] = [x for x in (f.get("failed") or []) if isinstance(x, dict)]
            if f.get("pending"):
                f["failed"] += [{"channel": c, "reason": "the plugin stopped before it was sent"}
                                for c in f["channels"] if c != "browser"
                                and c not in f["delivered"]]
            f["pending"] = False
            rows.append(f)
        rows.sort(key=lambda f: f["seq"], reverse=True)
        with st["lock"]:
            st["firings"].clear()
            st["firings"].extend(rows[:ALERT_FIRINGS_MAX])
            saved_seq = data.get("seq") if isinstance(data.get("seq"), int) else 0
            st["seq"] = max([st["seq"], saved_seq] + [f["seq"] for f in rows])
        return len(rows)

    # --------------------------------------------------------
    # Endpoints
    # --------------------------------------------------------
    def handleAlertRules(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/alertRules/
        Body {} for everything the Alerts page shows, or {"firingsSince": seq}
        for only the firings after seq (what every open page polls)."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        try:
            since = payload.get("firingsSince")
            if since is not None:
                if isinstance(since, bool) or not isinstance(since, (int, float)):
                    return self._evo_reply({"ok": False, "error": "firingsSince must be a number"},
                                           status=400)
                rows, seq = self._alert_firings_view(since)
                browser = sum(1 for r in self._alert_rules()
                              if "browser" in (r.get("channels") or []) and r.get("enabled", True))
                return self._evo_reply({"ok": True, "seq": seq, "firings": rows,
                                        "active": self._alerts_active(),
                                        "browserRules": browser if self._alerts_active() else 0,
                                        "browserWindow": ALERT_BROWSER_WINDOW_S,
                                        "now": time.time()})
            return self._evo_reply(self._alert_full_view())
        except Exception as exc:
            self.logger.error(f"[Alerts] alertRules failed: {type(exc).__name__}: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    def _alert_full_view(self):
        status = self._alert_channel_status()
        rules = []
        for r in self._alert_rules():
            state, now_text, current = self._alert_target(r)
            rules.append(dict(r, target=state, now=now_text, targetName=current))
        addr, src = self._alert_default_email()
        store = getattr(self, "cfg_store", None) or {}
        rows, seq = self._alert_firings_view(0)
        return {
            "ok": True,
            "rules": rules,
            "active": self._alerts_active(),
            "rev": int(store.get("alertRulesRev") or 0),
            "max": ALERT_RULES_MAX,
            "defaultEmail": str(store.get("alertEmail") or ""),
            # The IndigoSecrets fallback is named, not shown.
            "emailSource": src,
            "channels": status,
            "defaultChannels": self._alert_default_channels(status),
            "firings": rows,
            "seq": seq,
            "browserWindow": ALERT_BROWSER_WINDOW_S,
            "now": time.time(),
        }

    def handleSaveAlertRules(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/saveAlertRules/
        Body {"rules": [...], "active": bool, "defaultEmail": str, "rev": n,
        "migrate": bool}. Replaces the whole list. `rev` (the one alertRules
        handed out) refuses a save made from an out-of-date page; `migrate`
        refuses to move a browser's rules over rules the plugin already has."""
        payload, _reply = self._request_body(action, changes_state=True)
        if _reply:
            return _reply
        return self._alert_save(payload)

    def _alert_save(self, payload):
        store = dict(getattr(self, "cfg_store", None) or {})
        have = self._alert_rules()
        rev = int(store.get("alertRulesRev") or 0)
        want_rev = payload.get("rev")
        if want_rev is not None and (isinstance(want_rev, bool) or want_rev != rev):
            return self._evo_reply({"ok": False, "reason": "stale", "rev": rev,
                                    "error": "the rules were changed somewhere else; "
                                             "this page has been brought up to date"}, status=409)
        if payload.get("migrate") is True and have:
            return self._evo_reply({"ok": False, "reason": "not_empty",
                                    "error": f"the plugin already has {len(have)} rule"
                                             f"{'' if len(have) == 1 else 's'}, so nothing was "
                                             f"moved from this browser"}, status=409)
        errors = []
        new_email = store.get("alertEmail") or ""
        if "defaultEmail" in payload:
            de = payload.get("defaultEmail")
            if de is None or (isinstance(de, str) and not de.strip()):
                new_email = ""
            elif not plausible_email(de.strip() if isinstance(de, str) else de):
                errors.append(f"{str(de)[:60]!r} does not look like an email address")
            else:
                new_email = de.strip()
        active = payload.get("active", self._alerts_active())
        if not isinstance(active, bool):
            errors.append("active must be true or false")
        if "rules" in payload:
            status = self._alert_channel_status()
            clean, rule_errors = validate_rules(payload.get("rules"),
                                                self._alert_default_channels(status))
            errors += rule_errors
        else:
            clean = have
        if errors:
            return self._evo_reply({"ok": False, "error": "; ".join(errors[:6])
                                    + (f" (and {len(errors) - 6} more)" if len(errors) > 6 else "")},
                                   status=400)
        store.update({"alertRules": clean, "alertsActive": active, "alertEmail": new_email,
                      "alertRulesRev": rev + 1})
        try:
            self.cfg_store = self._save_config_store(store)
        except Exception as exc:
            self.logger.error(f"[Alerts] could not save the alert rules: {exc}")
            return self._evo_reply({"ok": False, "error": f"the rules could not be saved: {exc}"},
                                   status=500)
        self._alert_reindex()
        if payload.get("migrate") is True:
            log(f"[Alerts] {len(clean)} alert rule{'' if len(clean) == 1 else 's'} moved from a "
                f"browser into the plugin; they now fire with no dashboard page open")
        else:
            self.logger.debug(f"[Alerts] rules saved: {len(clean)}, active={active}")
        reply = self._alert_full_view()
        return self._evo_reply(reply)

    def handleSendTestAlert(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/sendTestAlert/
        Body {"channels": [...], "nonce": "<8-64 chars>", "email"?: str}. Sends
        "Test from Dashboards" off the dispatch path and answers with each
        channel's result, or 503 {pending} while it is still sending: the page
        asks again with the same nonce and collects the answer."""
        payload, _reply = self._request_body(action, changes_state=True)
        if _reply:
            return _reply
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not _NONCE_RE.match(nonce):
            return self._evo_reply({"ok": False, "error": "nonce must be 8-64 letters, digits, - or _"},
                                   status=400)
        chans = payload.get("channels")
        if not isinstance(chans, list) or not chans or any(c not in ALERT_CHANNELS for c in chans):
            return self._evo_reply({"ok": False, "error": "channels must list one or more of "
                                    + ", ".join(ALERT_CHANNELS)}, status=400)
        chans = [c for c in ALERT_CHANNELS if c in chans]
        email = payload.get("email") or ""
        if email and not plausible_email(email.strip() if isinstance(email, str) else email):
            return self._evo_reply({"ok": False, "error": "that does not look like an email address"},
                                   status=400)
        email = email.strip() if isinstance(email, str) else ""

        def produce():
            results = self._alert_deliver(chans, ALERT_TEST_TEXT, email=email, test=True)
            self._alert_log_test(results)
            return results

        state, results = self._offpath_get(f"alert-test:{nonce}", produce, ALERT_TEST_TTL_S,
                                           wait=self.OFFPATH_WAIT, lane="alerts")
        if state == "fresh":
            return self._evo_reply({"ok": True, "results": results, "text": ALERT_TEST_TEXT})
        if state == "failed":
            return self._evo_reply({"ok": False, "error": results}, status=500)
        return self._evo_reply({"ok": False, "pending": True,
                                "error": "still sending the test alert"}, status=503)

    def menuSendTestAlert(self, valuesDict=None, typeId=None):
        """Menu: send "Test from Dashboards" over every channel that is set up,
        on the alert worker, which logs the result."""
        status = self._alert_channel_status()
        chans = [c for c in ("pushover", "email") if status[c]["ready"]]
        if not chans:
            log("[Alerts] no alert channel is set up: Pushover says "
                f"\"{status['pushover']['status']}\" and email has no address. Set "
                "PUSHOVER_USER_TOKEN (IndigoSecrets or Configure), or an email address on the "
                "Alerts page", level="WARNING")
            return True
        log(f"[Alerts] sending a test alert by {' and '.join(chans)}…")
        self._alert_enqueue(self._alerts(), ("test", chans))
        return True
