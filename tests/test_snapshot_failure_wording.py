#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_snapshot_failure_wording.py
# Description: A snapshot warning must say what went wrong in words a person
#              can act on. go2rtc answers /api/frame.jpeg for a camera it
#              cannot reach with an EMPTY 200 and no Content-Type, which the
#              poller used to report as "unexpected content-type ''" - 51 times
#              while Garage and Patio were off the network on 21-09-2026.
# Author:      CliveS & Claude Opus 5.5
# Date:        22-09-2026 + UK time now
# Version:     1.0

import sys
import types

import pytest

from conftest import bare_plugin


class _Resp:
    def __init__(self, status=200, ct="", body=b""):
        self.status_code = status
        self.headers = {"Content-Type": ct} if ct else {}
        self.content = body


@pytest.fixture
def fetch(monkeypatch):
    p = bare_plugin()
    mod = sys.modules[type(p).__module__]
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    replies = []
    fake = types.SimpleNamespace(get=lambda *a, **k: replies.pop(0))
    monkeypatch.setitem(sys.modules, "requests", fake)
    return p, replies


def test_an_empty_reply_says_the_camera_could_not_be_reached(fetch):
    p, replies = fetch
    replies += [_Resp(), _Resp()]
    ok, why = p._fetch_one_snapshot("192.0.2.9")
    assert not ok
    assert why == "no picture from the camera: go2rtc could not reach it"


def test_a_non_image_reply_with_a_body_still_names_its_type(fetch):
    p, replies = fetch
    replies += [_Resp(ct="text/plain", body=b"x")] * 2
    ok, why = p._fetch_one_snapshot("192.0.2.9")
    assert not ok and why == "unexpected content-type 'text/plain'"


def test_a_picture_is_still_a_picture(fetch):
    p, replies = fetch
    replies += [_Resp(ct="image/jpeg", body=b"\xff\xd8jpeg")]
    assert p._fetch_one_snapshot("192.0.2.9") == (True, b"\xff\xd8jpeg")


def test_an_empty_reply_that_recovers_on_the_retry_is_fine(fetch):
    p, replies = fetch
    replies += [_Resp(), _Resp(ct="image/jpeg", body=b"ok")]
    assert p._fetch_one_snapshot("192.0.2.9") == (True, b"ok")
