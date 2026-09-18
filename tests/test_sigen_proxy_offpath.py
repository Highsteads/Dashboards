#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_sigen_proxy_offpath.py
# Description: The sigenApi proxy must never do network I/O on the dispatch
#              path (v3.18.0). It answers from cache, or asks a worker and
#              waits SIGEN_HANDOFF_WAIT at the very most.
#
#              THE FAULT THIS PINS, measured over September 2026 before the
#              change: handleSigenApi called urlopen(timeout=12) itself, and an
#              Indigo /message/ handler runs on the shared dispatch path — this
#              plugin's own gate comment says such a call "can wedge the whole
#              IWS event loop for ~5 min". The web server logged 130 internal
#              server errors that month, and "[SigenProxy] status fetch failed:
#              timed out" fell within ten seconds of one in 16 of its 58
#              occurrences (324x the background rate), 16 of the 24 correlated
#              pairs landing in the SAME two-second bucket as the timeout being
#              logged. The named file was innocent every time: /public/dashboards/
#              changed.stamp took 84 of them only because every open dashboard
#              asks for it every two seconds, so it was the request most likely
#              to be in flight when the path blocked.
#
#              The headline test is test_a_dead_upstream_does_not_hold_the_handler:
#              point the worker at something that never answers and the handler
#              still returns inside a second. Restore the old inline urlopen and
#              it takes twelve.
# Author:      CliveS & Claude Opus 5
# Date:        18-09-2026 + UK time now
# Version:     1.0

import json
import threading
import time

import pytest

from conftest import bare_plugin


class FakeAction:
    def __init__(self, body=""):
        self.props = {"request_body": body}


@pytest.fixture
def prox():
    """A plugin with the proxy's collaborators stubbed and workers running."""
    p = bare_plugin()
    p._refuse_reflector = lambda action: None
    p._sigen_available = lambda: True
    p._evo_reply = lambda payload, status=200: {
        "status": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "content": json.dumps(payload),
    }
    p._start_sigen_workers()
    yield p
    p._stop_sigen_workers()


def call(p, path="status", query=None):
    return p.handleSigenApi(FakeAction(json.dumps(
        {"path": path, "query": query or {}})))


def body(reply):
    return json.loads(reply["content"])


# ── the reason this file exists ────────────────────────────────────────────

def test_a_dead_upstream_does_not_hold_the_handler(prox, monkeypatch):
    """The whole point. An upstream that never answers must cost the caller
    SIGEN_HANDOFF_WAIT, not SIGEN_UPSTREAM_TIMEOUT."""
    started = threading.Event()

    def never_answers(st, url):
        started.set()
        time.sleep(prox.SIGEN_UPSTREAM_TIMEOUT)      # the pathological upstream
        raise RuntimeError("timed out")

    monkeypatch.setattr(prox, "_sigen_fetch", never_answers)
    t0 = time.time()
    reply = call(prox)
    elapsed = time.time() - t0

    assert started.is_set(), "the worker never got the job"
    assert elapsed < 1.5, f"handler blocked for {elapsed:.1f}s on the dispatch path"
    assert reply["status"] == 503
    assert body(reply)["reason"] == "sigen_pending"


def test_the_handler_itself_opens_no_socket(prox, monkeypatch):
    """Belt and braces: even a handler that somehow got a fetch past the
    worker must not reach urlopen from the dispatch path."""
    import urllib.request
    opened = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(
                            AssertionError("urlopen called on the dispatch path")))
    # no worker: the queue fills, the handler times out its hand-off and answers
    prox._stop_sigen_workers()
    reply = call(prox)
    assert reply["status"] == 503
    assert opened == []


# ── ordinary behaviour ─────────────────────────────────────────────────────

def test_a_fresh_cache_entry_answers_without_asking_anyone(prox, monkeypatch):
    st = prox._sigen_state()
    url = f"{prox._SIGEN_API_BASE}/status"
    st["cache"][url] = (time.time(), '{"soc": 61}')
    asked = []
    monkeypatch.setattr(prox, "_sigen_ask",
                        lambda *a: asked.append(1) or threading.Event())
    reply = call(prox)
    assert reply["status"] == 200
    assert body(reply)["soc"] == 61
    assert asked == [], "a fresh entry must not queue a fetch"


def test_a_stale_entry_is_refetched_not_served(prox, monkeypatch):
    """A figure about now has to come from now. Every page keeps its last
    render on a bad reply, so holding the tile is honest; printing an old SOC
    as the current one is not."""
    st = prox._sigen_state()
    url = f"{prox._SIGEN_API_BASE}/status"
    st["cache"][url] = (time.time() - 3600, '{"soc": 11}')

    monkeypatch.setattr(prox, "_sigen_fetch",
                        lambda s, u: time.sleep(prox.SIGEN_UPSTREAM_TIMEOUT))
    reply = call(prox)
    assert reply["status"] == 503, "an hour-old SOC was served as current"
    assert "11" not in reply["content"]


def test_a_worker_result_is_handed_back_within_the_wait(prox, monkeypatch):
    def quick(st, url):
        with st["lock"]:
            st["cache"][url] = (time.time(), '{"soc": 77}')
    monkeypatch.setattr(prox, "_sigen_fetch", quick)
    reply = call(prox)
    assert reply["status"] == 200
    assert body(reply)["soc"] == 77


def test_an_upstream_failure_is_reported_as_502(prox, monkeypatch):
    def fails(st, url):
        with st["lock"]:
            st["fail"][url] = (time.time(), "Connection refused", False)
    monkeypatch.setattr(prox, "_sigen_fetch", fails)
    reply = call(prox)
    assert reply["status"] == 502
    assert "Connection refused" in body(reply)["detail"]


def test_a_later_success_clears_an_earlier_failure(prox):
    st = prox._sigen_state()
    url = f"{prox._SIGEN_API_BASE}/status"
    st["fail"][url] = (time.time(), "boom", False)

    class _Resp:
        def read(self): return b'{"soc": 42}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.request
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: _Resp()
    try:
        prox._sigen_fetch(st, url)
    finally:
        urllib.request.urlopen = real
    assert url not in st["fail"]
    assert st["cache"][url][1] == '{"soc": 42}'


# ── coalescing, which is what stops the pile-up ────────────────────────────

def test_concurrent_callers_produce_one_upstream_fetch(prox, monkeypatch):
    """Three pages poll `status` within a second of each other. That must be
    one round trip, not three — the v2.72.0 micro-cache's job, kept."""
    calls = []
    def slowish(st, url):
        calls.append(url)
        time.sleep(0.15)
        with st["lock"]:
            st["cache"][url] = (time.time(), '{"soc": 5}')
    monkeypatch.setattr(prox, "_sigen_fetch", slowish)

    out = []
    ts = [threading.Thread(target=lambda: out.append(call(prox))) for _ in range(3)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(calls) == 1, f"{len(calls)} upstream fetches for one question"
    assert [r["status"] for r in out] == [200, 200, 200]


def test_different_paths_do_not_queue_behind_each_other(prox, monkeypatch):
    """A twelve-second `history` used to leave `status` waiting behind it.
    SIGEN_WORKERS is why it no longer does."""
    assert prox.SIGEN_WORKERS >= 2
    def by_path(st, url):
        if url.endswith("history"):
            time.sleep(1.0)
        with st["lock"]:
            st["cache"][url] = (time.time(), '{"ok": 1}')
    monkeypatch.setattr(prox, "_sigen_fetch", by_path)

    slow = threading.Thread(target=lambda: call(prox, "history"))
    slow.start()
    time.sleep(0.05)
    t0 = time.time()
    reply = call(prox, "status")
    assert time.time() - t0 < 0.5
    assert reply["status"] == 200
    slow.join()


# ── the guards that were already there, unchanged by this ──────────────────

def test_an_unknown_path_is_still_refused_before_anything_is_queued(prox):
    reply = call(prox, "../../etc/passwd")
    assert reply["status"] == 400
    assert prox._sigen_state()["queue"].qsize() == 0


def test_only_the_numeric_params_are_forwarded(prox, monkeypatch):
    seen = {}
    def capture(st, url):
        seen["url"] = url
        with st["lock"]:
            st["cache"][url] = (time.time(), "{}")
    monkeypatch.setattr(prox, "_sigen_fetch", capture)
    call(prox, "history", {"hours": 24, "evil": "; rm -rf /", "days": "9"})
    assert "hours=24" in seen["url"] and "days=9" in seen["url"]
    assert "evil" not in seen["url"]


def test_the_upstream_host_is_fixed(prox, monkeypatch):
    seen = {}
    def capture(st, url):
        seen["url"] = url
        with st["lock"]:
            st["cache"][url] = (time.time(), "{}")
    monkeypatch.setattr(prox, "_sigen_fetch", capture)
    call(prox, "status")
    assert seen["url"].startswith("http://127.0.0.1:8179/api/")


# ── lifecycle ──────────────────────────────────────────────────────────────

def test_stopping_the_workers_ends_them(prox):
    st = prox._sigen_state()
    assert any(t.is_alive() for t in st["threads"])
    prox._stop_sigen_workers()
    assert not any(t.is_alive() for t in st["threads"])
    assert st["threads"] == []


def test_a_worker_survives_a_fetch_that_raises(prox, monkeypatch):
    """One bad fetch must not take the worker down and strand every later
    caller on the hand-off timeout."""
    def explode(st, url):
        raise ValueError("kaboom")
    monkeypatch.setattr(prox, "_sigen_fetch", explode)
    first = call(prox)
    assert first["status"] == 502

    def fine(st, url):
        with st["lock"]:
            st["cache"][url] = (time.time(), '{"soc": 8}')
    monkeypatch.setattr(prox, "_sigen_fetch", fine)
    second = call(prox, "daily")
    assert second["status"] == 200, "the worker died on the first exception"
