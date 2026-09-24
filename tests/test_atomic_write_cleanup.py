#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_atomic_write_cleanup.py
# Description: _write_atomic and _copy_atomic leave no temp file behind when
#              the write or the rename fails (review 24-09-2026 [38]). A
#              disk-full episode left partial files in anonymous /public that
#              nothing ever removed. The error still reaches the caller.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import os

import pytest

from conftest import bare_plugin


def _boom(*a, **k):
    raise OSError(28, "No space left on device")


def test_a_failed_rename_leaves_no_temp_file(tmp_path, monkeypatch):
    p = bare_plugin()
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        p._write_atomic(str(tmp_path / "cam-x.jpg"), b"\xff\xd8partial")
    assert os.listdir(tmp_path) == []


def test_a_failed_copy_leaves_no_temp_file(tmp_path, monkeypatch):
    p = bare_plugin()
    src = tmp_path / "src.js"
    src.write_text("// x", encoding="utf-8")
    out = tmp_path / "public"
    out.mkdir()
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        p._copy_atomic(str(src), str(out / "page.js"))
    assert os.listdir(out) == []


def test_a_good_write_still_lands(tmp_path):
    p = bare_plugin()
    p._write_atomic(str(tmp_path / "a.json"), b"{}")
    assert os.listdir(tmp_path) == ["a.json"]
