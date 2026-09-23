#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    dash_util.py
# Description: Small pure helpers shared by plugin.py and its mixin modules
#              (v3.30.0), so no mixin has to reach into another for them.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0


def as_bool01(v):
    """A logged state value as 1 or 0. "1", "true", "on", "yes" and any
    non-zero number are 1; everything else, including junk, is 0."""
    s = str(v).strip().lower()
    if s in ("1", "true", "on", "yes"):
        return 1
    try:
        return 1 if float(s) != 0 else 0
    except (ValueError, TypeError):
        return 0
