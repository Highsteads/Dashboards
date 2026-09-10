#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_changed_since.py
# Description: The changedSince ledger policy — ONE implementation (v2.95.1)
#              shared by the IWS action and the :8177 guest route, which used
#              to carry a verbatim copy. Locks the boundaries: a new or stale
#              client refetches everything, a big change set refetches
#              everything, otherwise the changed + deleted ids strictly after
#              `since` — a change AT `since` is not included, because the
#              client already has it.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026
# Version:     1.0

from conftest import bare_plugin


def _p():
    p = bare_plugin()
    p._dev_changes = {1: 100.0, 2: 150.0, 3: 200.0}
    p._dev_deleted = {9: 160.0}
    return p


def test_new_client_gets_full():
    assert _p()._changed_since_payload(0, now=210.0)["full"] is True


def test_stale_client_gets_full():
    p = _p()
    assert p._changed_since_payload(210.0 - p.CHANGED_SINCE_STALE_S - 1, now=210.0)["full"] is True


def test_recent_client_gets_the_delta_strictly_after_since():
    r = _p()._changed_since_payload(150.0, now=210.0)
    assert "full" not in r
    assert r["changed"] == [3]          # 2 changed AT since -> already seen
    assert r["deleted"] == [9]
    assert r["now"] == 210.0


def test_big_change_set_gets_full():
    p = _p()
    p._dev_changes = {i: 205.0 for i in range(p.CHANGED_SINCE_MAX_IDS + 1)}
    assert p._changed_since_payload(200.0, now=210.0)["full"] is True


def test_iws_handler_uses_the_shared_policy(monkeypatch):
    import json
    from types import SimpleNamespace
    p = _p()
    seen = {}
    p._changed_since_payload = lambda since, now=None: seen.setdefault("since", since) or {"ok": True}
    p._evo_reply = lambda obj, status=200: obj
    p.handleChangedSince(SimpleNamespace(props={"request_body": json.dumps({"since": 150.0})}))
    assert seen["since"] == 150.0
