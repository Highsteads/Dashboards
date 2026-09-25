#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    dash_util.py
# Description: Small pure helpers shared by plugin.py and its mixin modules
#              (v3.30.0), so no mixin has to reach into another for them.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.2 (stills_idle_minutes: the saved stillsIdleMinutes, clamped)
#              1.1 (live_pool_size: the saved livePoolSize, clamped)


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


def live_pool_size(value, default, most):
    """The number of camera tiles the Cameras page may run live (3.46.0).

    `value` is the livePoolSize key from the settings store, which Settings
    and docs/configuration.md have long offered but config.js never read, so
    every install got the default whatever it had saved. A whole number from
    0 (no live tiles) to `most` is used as it is; anything above is held to
    `most`; a negative, fractional, boolean, missing or unreadable value
    falls back to `default`, because a typo in raw JSON must not switch every
    camera off. Returns (size, problem) where problem is "" or a short reason
    the caller can log.
    """
    if value is None or value == "":
        return default, ""
    # bool is an int in Python; True must not quietly mean one live tile.
    if isinstance(value, bool):
        return default, f"livePoolSize {value!r} is not a number"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default, f"livePoolSize {value!r} is not a number"
    if f != f or f in (float("inf"), float("-inf")):
        return default, f"livePoolSize {value!r} is not a number"
    if f < 0 or f != int(f):
        return default, f"livePoolSize {value!r} is not a whole number of cameras"
    n = int(f)
    if n > most:
        return most, f"livePoolSize {n} is more than {most}, so {most} are used"
    return n, ""


def stills_idle_minutes(value, default, most):
    """How often, in minutes, a camera nobody is watching still gets a
    picture taken (3.48.0), from the stillsIdleMinutes key in the settings
    store. That picture is what camera health, and the hub's "camera
    offline" warning, are judged on. A whole number from 0 (never) to `most`
    is used as it is; anything above is held to `most`; a negative,
    fractional, boolean or unreadable value falls back to `default`, because
    a typo in raw JSON must not stop the health checks. Returns
    (minutes, problem) where problem is "" or a short reason to log."""
    if value is None or value == "":
        return default, ""
    if isinstance(value, bool):
        return default, f"stillsIdleMinutes {value!r} is not a number"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default, f"stillsIdleMinutes {value!r} is not a number"
    if f != f or f in (float("inf"), float("-inf")):
        return default, f"stillsIdleMinutes {value!r} is not a number"
    if f < 0 or f != int(f):
        return default, f"stillsIdleMinutes {value!r} is not a whole number of minutes"
    n = int(f)
    if n > most:
        return most, f"stillsIdleMinutes {n} is more than {most}, so {most} is used"
    return n, ""
