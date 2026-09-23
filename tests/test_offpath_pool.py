#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_offpath_pool.py
# Description: No /message/ handler may do slow work on the dispatch path. One
#              shared worker pool serves the three that used to — sigenApi
#              (v3.18.0), then timelineDay and systemHealth when the pool was
#              generalised in v3.19.0.
#
#              THE FAULT THIS PINS. An Indigo /message/ handler runs on the
#              shared dispatch path — this plugin's own gate comment says such a
#              call "can wedge the whole IWS event loop for ~5 min" — so slow
#              work done inline is an outage of the web server, not a slow tile,
#              and whatever request is in flight comes back as a 500. September
#              2026 logged 130 of those, and "[SigenProxy] status fetch failed:
#              timed out" fell within ten seconds of one in 16 of its 58
#              occurrences, 324x the background rate, 16 of the 24 pairs in the
#              SAME two-second bucket as the timeout being logged. The file they
#              named was innocent: changed.stamp took 84 of them only because
#              every open dashboard asks for it every two seconds.
#
#              Then all 32 browser-reachable endpoints were audited AND TIMED.
#              Worst of three calls each: timelineDay 1707 ms, systemHealth
#              262 ms. A grep says what blocks; only the clock says how much.
#
#              The headline test is test_a_dead_producer_does_not_hold_the_handler:
#              give the pool something that never returns, and the handler is
#              still back inside a second.
# Author:      CliveS & Claude Opus 5
# Date:        18-09-2026 + UK time now
# Version:     2.0

import json
import os
import threading
import time

import pytest

from conftest import bare_plugin, plugin_source

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "Dashboards.indigoPlugin", "Contents", "Server Plugin", "plugin.py")


class FakeAction:
    def __init__(self, body=""):
        self.props = {"request_body": body}


@pytest.fixture
def plug():
    p = bare_plugin()
    p._refuse_reflector = lambda action: None
    p._sigen_available = lambda: True
    p._evo_reply = lambda payload, status=200: {
        "status": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "content": json.dumps(payload),
    }
    p._start_offpath_workers()
    yield p
    p._stop_offpath_workers()


def sigen(p, path="status", query=None):
    return p.handleSigenApi(FakeAction(json.dumps({"path": path, "query": query or {}})))


def timeline(p, date="2026-09-18"):
    return p.handleTimelineDay(FakeAction(json.dumps({"date": date})))


def health(p):
    return p.handleSystemHealth(FakeAction("{}"))


def body(reply):
    return json.loads(reply["content"])


# ── the reason this file exists ────────────────────────────────────────────

def test_a_dead_producer_does_not_hold_the_handler(plug, monkeypatch):
    """The whole point. Work that never finishes must cost the caller
    OFFPATH_WAIT, not the producer's own timeout."""
    started = threading.Event()

    def never_answers(url):
        started.set()
        time.sleep(plug.SIGEN_UPSTREAM_TIMEOUT)
        raise RuntimeError("timed out")

    monkeypatch.setattr(plug, "_sigen_fetch", never_answers)
    t0 = time.time()
    reply = sigen(plug)
    elapsed = time.time() - t0

    assert started.is_set(), "the pool never got the job"
    assert elapsed < 1.5, f"handler blocked for {elapsed:.1f}s on the dispatch path"
    assert reply["status"] == 503
    assert body(reply)["reason"] == "sigen_pending"


@pytest.mark.parametrize("name,handler,producer_attr", [
    ("sigenApi",     sigen,    "_sigen_fetch"),
    ("timelineDay",  timeline, "_timeline_day"),
    ("systemHealth", health,   "_system_health_payload"),
])
def test_no_handler_waits_on_a_slow_producer(plug, monkeypatch, name, handler,
                                             producer_attr):
    """All three, not just the one that was fixed first. A slow producer must
    not be able to hold any of them."""
    monkeypatch.setattr(plug, producer_attr, lambda *a, **k: time.sleep(8))
    t0 = time.time()
    reply = handler(plug)
    assert time.time() - t0 < 1.5, f"{name} blocked the dispatch path"
    assert reply["status"] == 503
    assert body(reply).get("pending") or body(reply).get("reason") == "sigen_pending"


# ── the pool itself ────────────────────────────────────────────────────────

def test_a_fresh_entry_answers_without_running_the_producer(plug):
    ran = []
    st = plug._offpath()
    st["cache"]["k"] = (time.time(), {"v": 1})
    state, payload = plug._offpath_get("k", lambda: ran.append(1) or {"v": 2}, 30)
    assert (state, payload) == ("fresh", {"v": 1})
    assert ran == [], "a fresh entry must not run the producer"


def test_a_stale_entry_is_rebuilt_never_served(plug):
    """A figure about now has to come from now. Pages keep their last render on
    a bad reply, so holding the tile is honest; an old reading dressed as a new
    one is not."""
    st = plug._offpath()
    st["cache"]["k"] = (time.time() - 3600, {"v": "old"})
    state, payload = plug._offpath_get("k", lambda: time.sleep(8), 30)
    assert state == "pending"
    assert payload is None


def test_a_result_inside_the_wait_comes_straight_back(plug):
    state, payload = plug._offpath_get("k", lambda: {"v": 9}, 30)
    assert (state, payload) == ("fresh", {"v": 9})


def test_a_failure_is_reported_with_its_detail(plug):
    def boom():
        raise RuntimeError("Connection refused")
    state, payload = plug._offpath_get("k", boom, 30)
    assert state == "failed"
    assert "Connection refused" in payload


def test_a_later_success_clears_an_earlier_failure(plug):
    def boom():
        raise RuntimeError("boom")
    assert plug._offpath_get("k", boom, 30)[0] == "failed"
    assert plug._offpath_get("k", lambda: {"v": 1}, 30) == ("fresh", {"v": 1})
    assert "k" not in plug._offpath()["fail"]


def test_concurrent_callers_run_the_producer_once(plug):
    """Three pages polling the same thing within a second must cost one run,
    not three."""
    runs = []

    def slowish():
        runs.append(1)
        time.sleep(0.15)
        return {"v": 1}

    out = []
    ts = [threading.Thread(target=lambda: out.append(plug._offpath_get("k", slowish, 30)))
          for _ in range(3)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(runs) == 1, f"{len(runs)} runs for one question"
    assert [s for s, _ in out] == ["fresh"] * 3


def test_a_slow_key_does_not_block_a_different_one(plug):
    assert plug.OFFPATH_WORKERS >= 2
    slow = threading.Thread(target=lambda: plug._offpath_get("slow", lambda: time.sleep(1.0), 30))
    slow.start()
    time.sleep(0.05)
    t0 = time.time()
    state, _ = plug._offpath_get("quick", lambda: {"v": 1}, 30)
    assert time.time() - t0 < 0.5
    assert state == "fresh"
    slow.join()


def test_a_producer_that_raises_does_not_kill_the_worker(plug):
    def explode():
        raise ValueError("kaboom")
    assert plug._offpath_get("a", explode, 30)[0] == "failed"
    assert plug._offpath_get("b", lambda: {"v": 1}, 30) == ("fresh", {"v": 1})


def test_the_cache_is_capped(plug):
    for i in range(plug.OFFPATH_CACHE_MAX + 5):
        plug._offpath_get(f"k{i}", lambda i=i: {"v": i}, 30)
    assert len(plug._offpath()["cache"]) <= plug.OFFPATH_CACHE_MAX


def test_the_cap_evicts_the_oldest_not_everything(plug):
    """v3.27.0: reaching the cap used to clear the WHOLE cache, throwing out
    timeline days meant to be held for a day. Now the least recently used goes."""
    plug._offpath_get("keep", lambda: {"v": "keep"}, 3600)
    for i in range(plug.OFFPATH_CACHE_MAX - 2):
        plug._offpath_get(f"k{i}", lambda i=i: {"v": i}, 30)
    plug._offpath_get("keep", lambda: {"v": "rebuilt"}, 3600)      # touched: recently used
    for i in range(10):
        plug._offpath_get(f"more{i}", lambda i=i: {"v": i}, 30)
    cache = plug._offpath()["cache"]
    assert "keep" in cache and cache["keep"][1] == {"v": "keep"}
    assert "k0" not in cache, "the oldest untouched entry is the one that goes"


def test_an_old_failure_does_not_answer_for_a_new_run(plug):
    """v3.27.0: a failure recorded once was returned to every later caller
    while their own run was still pending, until something succeeded."""
    def explode():
        raise ValueError("kaboom")
    assert plug._offpath_get("x", explode, 30)[0] == "failed"
    gate = threading.Event()
    def slow_ok():
        gate.wait(2)
        return {"v": 1}
    state, _ = plug._offpath_get("x", slow_ok, 30, wait=0.05)
    gate.set()
    assert state == "pending", f"got {state}: the earlier failure answered for this run"


def test_swr_placeholder_then_value_then_stale_while_refreshing(plug):
    ph = {"building": True}
    calls = []
    gate = threading.Event()
    def build():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(2)                  # the refresh is slow
        return {"n": len(calls)}
    kw = dict(ttl=0.2, fail_ttl=60, placeholder=ph, on_fail=lambda d: {"err": d})
    assert plug._offpath_swr("s", build, **kw) is ph            # nothing yet: never waits
    deadline = time.time() + 2
    while plug._offpath_swr("s", build, **kw) is ph and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.25)                                            # let it go stale
    t0 = time.monotonic()
    assert plug._offpath_swr("s", build, **kw) == {"n": 1}      # stale, served at once
    assert time.monotonic() - t0 < 0.1, "a stale answer must never wait for the refresh"
    assert plug._offpath_swr("s", build, **kw) == {"n": 1}      # still refreshing: one job
    gate.set()
    deadline = time.time() + 2
    while plug._offpath_swr("s", build, **kw) != {"n": 2} and time.time() < deadline:
        time.sleep(0.02)
    assert plug._offpath_swr("s", build, **kw) == {"n": 2}
    assert len(calls) == 2, "two stale reads queued one refresh, not two"


def test_swr_remembers_a_failure_and_does_not_hammer(plug):
    calls = []
    def boom():
        calls.append(1)
        raise RuntimeError("no SQL Logger")
    kw = dict(ttl=60, fail_ttl=60, placeholder={"building": True},
              on_fail=lambda d: {"error": d})
    plug._offpath_swr("f", boom, **kw)
    time.sleep(0.2)
    for _ in range(5):
        assert plug._offpath_swr("f", boom, **kw) == {"error": "no SQL Logger"}
    assert len(calls) == 1, "a remembered failure must not be retried on every poll"


def test_swr_ttl_can_depend_on_the_payload(plug):
    """Carbon reports an API failure inside its reply; that reply is kept for
    less time than a good one."""
    plug._offpath_swr("c", lambda: {"error": "api down"},
                      ttl=lambda p: 0.05 if "error" in p else 600, fail_ttl=60,
                      placeholder={}, on_fail=lambda d: {})
    time.sleep(0.2)
    st = plug._offpath()
    ts, payload = st["cache"]["c"]
    plug._offpath_swr("c", lambda: {"ok": 1},
                      ttl=lambda p: 0.05 if "error" in p else 600, fail_ttl=60,
                      placeholder={}, on_fail=lambda d: {})
    time.sleep(0.2)
    assert st["cache"]["c"][1] == {"ok": 1}, "the short-lived error reply was refreshed"


def test_stopping_the_workers_ends_them(plug):
    st = plug._offpath()
    assert any(t.is_alive() for t in st["threads"])
    plug._stop_offpath_workers()
    assert not any(t.is_alive() for t in st["threads"])
    assert st["threads"] == []


# ── per-endpoint behaviour ─────────────────────────────────────────────────

def test_sigen_serves_the_upstream_body_verbatim(plug, monkeypatch):
    monkeypatch.setattr(plug, "_sigen_fetch", lambda u: '{"soc": 77}')
    reply = sigen(plug)
    assert reply["status"] == 200
    assert body(reply)["soc"] == 77


def test_sigen_reports_an_upstream_failure_as_502(plug, monkeypatch):
    def boom(url):
        raise RuntimeError("Connection refused")
    monkeypatch.setattr(plug, "_sigen_fetch", boom)
    reply = sigen(plug)
    assert reply["status"] == 502
    assert "Connection refused" in body(reply)["detail"]


def test_an_unknown_sigen_path_is_refused_before_anything_is_queued(plug):
    reply = sigen(plug, "../../etc/passwd")
    assert reply["status"] == 400
    assert plug._offpath()["queue"].qsize() == 0


def test_only_the_numeric_sigen_params_are_forwarded(plug, monkeypatch):
    seen = {}
    monkeypatch.setattr(plug, "_sigen_fetch",
                        lambda u: seen.setdefault("url", u) or "{}")
    sigen(plug, "history", {"hours": 24, "evil": "; rm -rf /", "days": "9"})
    assert "hours=24" in seen["url"] and "days=9" in seen["url"]
    assert "evil" not in seen["url"]


def test_the_sigen_upstream_host_is_fixed(plug, monkeypatch):
    seen = {}
    monkeypatch.setattr(plug, "_sigen_fetch",
                        lambda u: seen.setdefault("url", u) or "{}")
    sigen(plug)
    assert seen["url"].startswith("http://127.0.0.1:8179/api/")


def test_timeline_caches_a_past_day_far_longer_than_today(plug):
    """A finished day cannot change; today is still being written to."""
    assert plug.TIMELINE_PAST_TTL > plug.TIMELINE_TODAY_TTL * 10


def test_timeline_keys_each_day_separately(plug, monkeypatch):
    monkeypatch.setattr(plug, "_timeline_day", lambda d: {"day": d})
    assert body(timeline(plug, "2026-09-01"))["day"] == "2026-09-01"
    assert body(timeline(plug, "2026-09-02"))["day"] == "2026-09-02"


def test_a_bad_date_is_a_400_and_never_reaches_the_pool(plug, monkeypatch):
    """The page must tell the user, not poll for ever on a request that can
    never succeed.

    The first version decided this from the TEXT of the exception, looking for
    the word "format" — and the real message is "date must be YYYY-MM-DD", so
    live it answered 500. The date is checked on the dispatch path now, where
    it costs nothing, and the pool never sees a malformed one.
    """
    ran = []
    monkeypatch.setattr(plug, "_timeline_day", lambda d: ran.append(d) or {})
    for bad in ("not-a-date", "2026-13-01", "18/09/2026", "2026-09-1x"):
        reply = timeline(plug, bad)
        assert reply["status"] == 400, f"{bad!r} answered {reply['status']}"
        assert not body(reply).get("pending")
    assert ran == [], "a malformed date must never reach a worker"


def test_a_timeline_build_error_is_a_500(plug, monkeypatch):
    def boom(d):
        raise RuntimeError("history db is locked")
    monkeypatch.setattr(plug, "_timeline_day", boom)
    assert timeline(plug)["status"] == 500


def test_system_health_degrades_section_by_section(plug, monkeypatch):
    """One collector failing must cost that card, not the page — which is why
    the producer never raises and the pool never records a failure for it."""
    monkeypatch.setattr(plug, "_mac_vitals", lambda: (_ for _ in ()).throw(OSError("no")))
    monkeypatch.setattr(plug, "_storage_breakdown", lambda: {"used": 1})
    monkeypatch.setattr(plug, "_device_health", lambda: {"n": 2})
    monkeypatch.setattr(plug, "_service_health", lambda: {"go2rtc": True})
    out = plug._system_health_payload()
    assert out["ok"] is True
    assert "error" in out["mac"]
    assert out["storage"] == {"used": 1}


def test_system_health_answers_from_one_key(plug, monkeypatch):
    runs = []
    monkeypatch.setattr(plug, "_system_health_payload",
                        lambda: runs.append(1) or {"ok": True})
    health(plug); health(plug)
    assert len(runs) == 1, "the second call must come from cache"

def test_the_pages_that_wait_properly_get_a_shorter_hand_off(plug):
    """timeline.html and system-health.html poll a pending reply through
    DashUI.message, so their handlers need not hold the dispatch path for the
    full default. Measured with the default: timelineDay's worst call was
    779 ms, which was the cap and not the work."""
    assert plug.TIMELINE_WAIT < plug.OFFPATH_WAIT
    assert plug.SYSTEM_HEALTH_WAIT < plug.OFFPATH_WAIT


@pytest.mark.parametrize("handler,producer_attr,cap_attr", [
    (timeline, "_timeline_day",          "TIMELINE_WAIT"),
    (health,   "_system_health_payload", "SYSTEM_HEALTH_WAIT"),
])
def test_the_shorter_cap_is_the_one_actually_applied(plug, monkeypatch, handler,
                                                     producer_attr, cap_attr):
    monkeypatch.setattr(plug, producer_attr, lambda *a, **k: time.sleep(5))
    t0 = time.time()
    reply = handler(plug)
    elapsed = time.time() - t0
    cap = getattr(plug, cap_attr)
    assert reply["status"] == 503
    assert elapsed < cap + 0.35, (
        f"held the path {elapsed:.2f}s against a {cap}s cap")

# ── historyQuery (v3.20.0) ─────────────────────────────────────────────────
# Measured before the move, with the parameters the Graphs page actually sends
# (action=series, maxPoints=240, the 720 h chip, biggest table at 4.0 M rows):
# 5.2-6.1 SECONDS on every call, uncached. The worst wedge in the plugin, and
# one click reached it.

def history(p, **kw):
    params = {"action": "series", "deviceId": 933771328, "state": "voltage",
              "hours": 720, "maxPoints": 240}
    params.update(kw)
    return p.handleHistoryQuery(FakeAction(json.dumps(params)))


def test_a_slow_history_query_does_not_hold_the_handler(plug, monkeypatch):
    monkeypatch.setattr(plug, "_history_query", lambda params: time.sleep(8))
    t0 = time.time()
    reply = history(plug)
    elapsed = time.time() - t0
    assert elapsed < plug.HISTORY_WAIT + 0.35, (
        f"held the path {elapsed:.2f}s — the 720 h chip used to cost six seconds")
    assert reply["status"] == 503
    assert body(reply)["pending"] is True


def test_a_history_result_comes_back_and_is_then_cached(plug, monkeypatch):
    runs = []
    monkeypatch.setattr(plug, "_history_query",
                        lambda params: runs.append(1) or {"ok": True, "points": [1, 2]})
    assert body(history(plug))["points"] == [1, 2]
    history(plug)
    assert len(runs) == 1, "the second identical question must come from cache"


def test_every_parameter_that_changes_the_answer_is_in_the_key(plug):
    base = {"action": "series", "deviceId": 1, "state": "voltage",
            "hours": 24, "maxPoints": 240}
    seen = {plug._history_key(base)}
    for field, other in (("action", "states"), ("deviceId", 2), ("state", "current"),
                         ("hours", 720), ("maxPoints", 1000)):
        v = dict(base); v[field] = other
        k = plug._history_key(v)
        assert k not in seen, f"changing {field} did not change the cache key"
        seen.add(k)


def test_the_key_normalises_so_the_same_question_shares_one_build(plug):
    a = plug._history_key({"action": "Series", "deviceId": "7", "state": " voltage ",
                           "hours": "24", "maxPoints": "240"})
    b = plug._history_key({"action": "series", "deviceId": 7, "state": "voltage",
                           "hours": 24, "maxPoints": 240})
    assert a == b


def test_a_missing_device_is_a_400_and_never_reaches_the_pool(plug, monkeypatch):
    ran = []
    monkeypatch.setattr(plug, "_history_query", lambda p: ran.append(1) or {})
    for bad in ({"deviceId": 0}, {"deviceId": "nonsense"}, {"deviceId": -3}):
        reply = history(plug, **bad)
        assert reply["status"] == 400, f"{bad} answered {reply['status']}"
    assert ran == [], "a request with no device must never reach a worker"


def test_a_caller_error_from_the_query_is_a_400_not_a_500(plug, monkeypatch):
    """_history_query raises ValueError when the CALLER asked for something
    impossible — an unknown state, a device with no history. The producer
    returns that as data, so the handler never has to guess it from the text
    of an exception, which is how timelineDay's bad-date path once answered
    500 while its test passed."""
    def unknown(params):
        raise ValueError("no history recorded for device 933771328")
    monkeypatch.setattr(plug, "_history_query", unknown)
    reply = history(plug)
    assert reply["status"] == 400
    assert "no history recorded" in body(reply)["error"]
    assert not body(reply).get("pending")


def test_a_real_failure_is_a_500(plug, monkeypatch):
    def boom(params):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(plug, "_history_query", boom)
    assert history(plug)["status"] == 500


def test_the_guest_path_shares_the_history_cache(plug):
    """v3.27.0 reversed the earlier choice. /guest/history runs on the :8177
    proxy's own threads, so blocking there never hurt the web server — but a
    30-day chart is 5-6 s of disk reads, and every guest request paid it
    afresh with no cache. It now uses the same key and producer as the main
    handler, with a long wait its own thread can afford."""
    src = plugin_source()
    assert "plugin_self._history_key(flat)" in src
    assert "wait=plugin_self.GUEST_HISTORY_WAIT" in src
    assert "plugin_self._history_query(flat)" not in src, "a direct, uncached call is back"
    assert plug.GUEST_HISTORY_WAIT >= 5


# ── one fault, one log line (v3.23.1) ───────────────────────────────────────
# Every Sigen timeout used to be logged twice — "[SigenProxy] status fetch
# failed" by the producer, then "[offpath] sigen:... failed" by the worker —
# 82 duplicated amber pairs in a week.

class _Rec:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda msg, *a, **k: self.lines.append((level, msg))


def test_a_sigen_timeout_is_one_warning_not_two(plug, monkeypatch):
    import urllib.request

    def timeout(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    plug.logger = _Rec()
    assert plug._offpath_get("sigen:x", lambda: plug._sigen_fetch(
        "http://127.0.0.1:8179/api/status"), 30)[0] == "failed"
    warnings = [m for lvl, m in plug.logger.lines if lvl == "warning"]
    assert warnings == ["[SigenProxy] status fetch failed: timed out"]


def test_an_unreported_producer_failure_is_still_a_warning(plug):
    plug.logger = _Rec()

    def explode():
        raise ValueError("kaboom")
    plug._offpath_get("a", explode, 30)
    assert ("warning", "[offpath] a failed: kaboom") in plug.logger.lines


def test_startup_does_not_wait_for_go2rtc():
    import ast
    tree = ast.parse(plugin_source())
    startup = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "startup")
    direct = [n for n in ast.walk(startup) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "_go2rtc_settle_check"]
    assert not direct, "startup() must hand these to a thread"
    starts = [n for n in ast.walk(startup) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "_start_go2rtc"]
    assert starts and all(any(kw.arg == "settle" and kw.value.value is False
                              for kw in n.keywords) for n in starts), \
        "startup() must call _start_go2rtc(settle=False)"
    handed = [kw for n in ast.walk(startup) if isinstance(n, ast.Call)
              for kw in n.keywords if kw.arg == "target"
              and getattr(kw.value, "attr", "") == "_go2rtc_boot_bg"]
    assert handed, "startup() no longer starts the mirror at all"


class _Proc:
    def __init__(self, rc):
        self._rc = rc

    def poll(self):
        return self._rc


@pytest.fixture
def settle(monkeypatch):
    import sys
    mod = sys.modules[type(bare_plugin()).__module__]
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    lines = []
    import cameras_mixin      # the settle check lives there since v3.32.0
    monkeypatch.setattr(cameras_mixin, "log", lambda m, level="INFO": lines.append((level, m)))
    p = bare_plugin()
    p._go2rtc_log_path = lambda: "go2rtc.log"
    p._cam_pool_closed = False
    return p, lines


def test_a_go2rtc_that_dies_at_once_is_reported_and_forgotten(settle):
    p, lines = settle
    p._go2rtc_proc = _Proc(1)
    assert p._go2rtc_settle_check() is False
    assert p._go2rtc_proc is None
    assert lines and lines[0][0] == "ERROR" and "Exited immediately" in lines[0][1]


def test_a_go2rtc_still_up_after_a_second_passes(settle):
    p, lines = settle
    p._go2rtc_proc = proc = _Proc(None)
    assert p._go2rtc_settle_check() is True
    assert p._go2rtc_proc is proc and not lines


def test_an_exit_during_shutdown_is_not_an_error(settle):
    p, lines = settle
    p._go2rtc_proc = _Proc(-15)
    p._cam_pool_closed = True
    assert p._go2rtc_settle_check() is False and not lines


def test_a_supervisor_restart_is_not_cleared_by_a_stale_check(settle):
    p, lines = settle
    old = _Proc(1)
    p._go2rtc_proc = old
    new = _Proc(None)
    real_poll = old.poll
    def poll():                       # the supervisor swaps in a new process
        p._go2rtc_proc = new
        return real_poll()
    old.poll = poll
    assert p._go2rtc_settle_check() is False
    assert p._go2rtc_proc is new
