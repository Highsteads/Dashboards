#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_harness_patch_restore.py
# Description: Shared mock methods survive test cleanup.
# Author:      CliveS & Codex GPT-6
# Date:        28-10-2026 15:12 UK
# Version:     1.0
"""Shared Indigo stub methods survive repeated monkeypatch undo (pytest 9.2)."""
import pytest
from conftest import load_plugin_module


@pytest.mark.parametrize("namespace,method", [
    ("server", "getPlugin"), ("server", "getInstallFolderPath"), ("devices", "iter"),
])
def test_shared_method_survives_patch_undo(monkeypatch, namespace, method):
    target = getattr(load_plugin_module().indigo, namespace)
    original = getattr(target, method)
    for _ in range(2):
        with monkeypatch.context() as patch:
            replacement = lambda *args: None
            patch.setattr(target, method, replacement)
            assert getattr(target, method) is replacement
        assert getattr(target, method) is original
