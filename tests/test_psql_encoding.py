#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_psql_encoding.py
# Description: Inside IndigoPluginHost3 the preferred encoding is US-ASCII, so
#              psql output read with text=True alone raised UnicodeDecodeError
#              on the first degree sign or accented name in any cell, and the
#              whole Postgres read failed. The run now fixes psql's encoding
#              (PGCLIENTENCODING=UTF8) and decodes as UTF-8, replacing any byte
#              that is not.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import subprocess
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                "Dashboards.indigoPlugin", "Contents", "Server Plugin")))
import history_db as H   # noqa: E402


def _fake_psql(monkeypatch, out_bytes):
    """Stand in for psql, decoding the way subprocess would INSIDE the plugin
    host: with the encoding asked for, or ASCII when none is."""
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        enc = kw.get("encoding") or "ascii"
        text = out_bytes.decode(enc, kw.get("errors") or "strict")
        return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")
    monkeypatch.setattr(H._Psql, "_binary", staticmethod(lambda: "/usr/bin/psql"))
    monkeypatch.setattr(H.subprocess, "run", run)
    return seen


def test_a_degree_sign_does_not_fail_the_read(monkeypatch):
    seen = _fake_psql(monkeypatch, "21.5°C,Café\n".encode("utf-8"))
    rows = H._Psql({}).run("SELECT 1")
    assert list(rows) == [("21.5°C", "Café")]
    assert seen["env"]["PGCLIENTENCODING"] == "UTF8"


def test_a_stray_byte_is_replaced_not_raised(monkeypatch):
    _fake_psql(monkeypatch, b"ok\xff\n")
    rows = H._Psql({}).run("SELECT 1")
    assert list(rows)[0][0].startswith("ok")


def test_an_explicit_client_encoding_is_respected(monkeypatch):
    monkeypatch.setenv("PGCLIENTENCODING", "UTF8")
    seen = _fake_psql(monkeypatch, b"1\n")
    H._Psql({}).run("SELECT 1")
    assert seen["env"]["PGCLIENTENCODING"] == "UTF8"
