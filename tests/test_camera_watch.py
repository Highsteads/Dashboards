#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_camera_watch.py
# Description: Stills only while a page is showing them (3.48.0). The poller
#              took a still of every camera every 2 s around the clock; each
#              still opens a fresh RTSP session to the camera, so ten cameras
#              meant five camera connections a second (measured 25-09-2026:
#              ~4.4 Mbit/s in, ~13 GB a day of JPEG writes) for pictures
#              nobody saw. Pages now report the cameras they show
#              (watchCameras); a watched camera gets a still every 2 s, the
#              rest an idle health check (stillsIdleMinutes, default 5), and a
#              camera whose check failed is tried again in 30 s so "offline"
#              still shows in about a minute.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.0

import json
import threading
from unittest.mock import MagicMock

import pytest

from conftest import bare_plugin, load_plugin_module

plugin = load_plugin_module()
dash_common = __import__("dash_common")
dash_util = __import__("dash_util")

A, B, C = "192.0.2.10", "192.0.2.11", "192.0.2.12"
POLL = dash_common.CAMERA_POLL_SECONDS
TTL = dash_common.CAMERA_WATCH_TTL_S
RECHECK = dash_common.CAMERA_RECHECK_SECONDS
IDLE = dash_common.CAMERA_IDLE_MINUTES_DEFAULT * 60


class Action:
    def __init__(self, body, ctype="application/json"):
        self.props = {"request_body": body if isinstance(body, str) else json.dumps(body),
                      "headers": {"Content-Type": ctype}}


def _plugin(store=None):
    p = bare_plugin()
    p.pluginPrefs = {}
    p.cfg_store = store if store is not None else {}
    p.cameras = [{"host": h, "name": f"Cam {h[-2:]}"} for h in (A, B, C)]
    p._cam_state = {}
    return p


def _state(**kw):
    st = {"ok_count": 0, "fail_count": 0, "last_log": 0, "last_ok": None, "last_failure": None}
    st.update(kw)
    return st


def _body(reply):
    return json.loads(reply["content"])


# ── the endpoint ────────────────────────────────────────────────────────────

def test_watch_records_known_hosts_and_ignores_the_rest():
    p = _plugin()
    reply = p.handleWatchCameras(Action({"hosts": [A, "203.0.113.9"]}))
    assert reply["status"] == 200
    assert _body(reply) == {"ok": True, "watching": 1, "ttlSeconds": TTL}
    watch = p._cam_watch()
    assert set(watch) == {A}, "a host that is not a configured camera is never watched"


def test_a_newly_watched_camera_is_due_at_once():
    p = _plugin()
    p._cam_state[A] = _state(last_try=1e12)          # "just tried", far in the future
    p.handleWatchCameras(Action({"hosts": [A]}))
    assert p._cam_state[A].get("due_now") is True
    # A camera already being watched is not pushed forward again.
    p._cam_state[A].pop("due_now")
    p.handleWatchCameras(Action({"hosts": [A]}))
    assert "due_now" not in p._cam_state[A]


@pytest.mark.parametrize("body", [
    {"hosts": "192.0.2.10"},
    {"hosts": [1, 2]},
    {},
    {"hosts": ["h"] * (dash_common.CAMERA_WATCH_HOSTS_MAX + 1)},
])
def test_a_malformed_list_is_refused(body):
    p = _plugin()
    assert p.handleWatchCameras(Action(body))["status"] == 400
    assert p._cam_watch() == {}


def test_it_insists_on_json_like_every_endpoint_that_changes_something():
    p = _plugin()
    assert p.handleWatchCameras(Action({"hosts": [A]}, ctype="text/plain"))["status"] == 415
    assert p._cam_watch() == {}


def test_the_action_is_declared():
    xml = (plugin.__file__.rsplit("/", 1)[0] + "/Actions.xml")
    src = open(xml, encoding="utf-8").read()
    assert '<Action id="watchCameras" uiPath="hidden">' in src
    assert "<CallbackMethod>handleWatchCameras</CallbackMethod>" in src


# ── when a camera is due ────────────────────────────────────────────────────

NOW = 1_000_000.0


def test_never_tried_is_due():
    assert _plugin()._camera_due(A, _state(), NOW)


def test_watched_is_due_every_poll_and_not_before():
    p = _plugin()
    p._cam_watch()[A] = NOW + 10
    assert not p._camera_due(A, _state(last_try=NOW - 1.0), NOW)
    assert p._camera_due(A, _state(last_try=NOW - POLL), NOW)
    assert p._camera_due(A, _state(last_try=NOW - (POLL - 0.4)), NOW), "a pass that wakes a hair early"


def test_a_watch_that_has_run_out_drops_to_the_idle_check():
    p = _plugin()
    p._cam_watch()[A] = NOW - 0.1
    assert not p._camera_due(A, _state(last_try=NOW - 60), NOW)
    assert p._camera_due(A, _state(last_try=NOW - IDLE), NOW)


def test_unwatched_healthy_camera_waits_for_the_idle_check():
    p = _plugin()
    assert not p._camera_due(A, _state(last_try=NOW - (IDLE - 5)), NOW)
    assert p._camera_due(A, _state(last_try=NOW - IDLE), NOW)


@pytest.mark.parametrize("fails", [1, 2])
def test_a_failing_unwatched_camera_is_rechecked_soon(fails):
    p = _plugin()
    assert not p._camera_due(A, _state(fail_count=fails, last_try=NOW - (RECHECK - 5)), NOW)
    assert p._camera_due(A, _state(fail_count=fails, last_try=NOW - RECHECK), NOW)


def test_an_offline_unwatched_camera_goes_back_to_the_idle_check():
    p = _plugin()
    assert not p._camera_due(A, _state(fail_count=3, last_try=NOW - RECHECK), NOW)
    assert p._camera_due(A, _state(fail_count=3, last_try=NOW - IDLE), NOW)


def test_the_saved_idle_interval_is_used():
    p = _plugin({"stillsIdleMinutes": 1})
    assert p._camera_due(A, _state(last_try=NOW - 60), NOW)
    assert not p._camera_due(A, _state(last_try=NOW - 50), NOW)


def test_idle_zero_means_an_unwatched_camera_is_never_checked():
    p = _plugin({"stillsIdleMinutes": 0})
    assert not p._camera_due(A, _state(), NOW), "not even once at start-up"
    assert not p._camera_due(A, _state(last_try=NOW - 86400), NOW)
    assert p._camera_due(A, _state(due_now=True), NOW), "a page asking still wins"
    p._cam_watch()[A] = NOW + 10
    assert p._camera_due(A, _state(), NOW)


def test_a_bad_saved_value_warns_once_and_uses_the_default(monkeypatch):
    logged = []
    monkeypatch.setattr(__import__("cameras_mixin"), "log",
                        lambda msg, level="INFO": logged.append((msg, level)))
    p = _plugin({"stillsIdleMinutes": "often"})
    assert p._stills_idle_seconds() == IDLE
    assert p._stills_idle_seconds() == IDLE
    assert len(logged) == 1 and logged[0][1] == "WARNING"


# ── the pass itself ─────────────────────────────────────────────────────────

class _Pool:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, cam):
        self.submitted.append(cam["host"])


def _pass_plugin(store=None):
    p = _plugin(store)
    p._cam_inflight = set()
    p._cam_inflight_lock = threading.Lock()
    p._fetch_go2rtc_streams = MagicMock(return_value={})
    p._write_streams_json = MagicMock()
    pool = _Pool()
    p._snapshot_pool = lambda: pool
    return p, pool


def test_a_pass_takes_stills_only_of_due_cameras(monkeypatch):
    p, pool = _pass_plugin()
    clock = [NOW]
    monkeypatch.setattr(__import__("cameras_mixin").time, "time", lambda: clock[0])
    p._poll_cameras_once()
    assert sorted(pool.submitted) == [A, B, C], "the first pass checks every camera"
    for h in (A, B, C):                               # the workers would release these
        p._cam_inflight.discard(h)
    pool.submitted.clear()

    clock[0] = NOW + POLL
    p._poll_cameras_once()
    assert pool.submitted == [], "nobody is watching: no stills 2 s later"

    p.handleWatchCameras(Action({"hosts": [B]}))
    clock[0] = NOW + 2 * POLL
    p._poll_cameras_once()
    assert pool.submitted == [B]
    assert "due_now" not in p._cam_state[B]
    assert p._cam_state[B]["last_try"] == NOW + 2 * POLL
    p._cam_inflight.discard(B)
    pool.submitted.clear()

    clock[0] = NOW + 3 * POLL
    p._poll_cameras_once()
    assert pool.submitted == [B], "a watched camera keeps its 2 s cadence"
    assert p._write_streams_json.call_count == 4, "health is still published every pass"


# ── the setting ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    (None, (5, "")), ("", (5, "")), (0, (0, "")), (15, (15, "")), ("15", (15, "")),
    (15.0, (15, "")),
])
def test_stills_idle_minutes_accepts(raw, want):
    assert dash_util.stills_idle_minutes(raw, 5, 60) == want


@pytest.mark.parametrize("raw", [True, -1, 2.5, "often", float("nan"), float("inf"), [5]])
def test_stills_idle_minutes_refuses(raw):
    got, problem = dash_util.stills_idle_minutes(raw, 5, 60)
    assert got == 5 and problem


def test_stills_idle_minutes_holds_to_the_most():
    got, problem = dash_util.stills_idle_minutes(600, 5, 60)
    assert got == 60 and "60" in problem
