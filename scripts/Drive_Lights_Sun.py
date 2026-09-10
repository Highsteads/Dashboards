#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Drive_Lights_Sun.py
# Description: The drive lights — Garage Light and Front Door Light — on at
#              100% from sunset to sunrise, off the rest of the time. One
#              script owns them; it replaces seven separate pieces of
#              automation that used to share the job between them.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026 + UK Time Now
# Version:     1.1
#
# v1.1 (02-09-2026, Dashboards deep review): a bulb that reads back 98-99%
#   after a setBrightness(100) is at full brightness — z2m maps the 0-254
#   Zigbee level to 0-100, and an exact `>= 100` would re-send every two
#   minutes all night. And the warnings for a missing or unreadable device fire
#   once per change, not every tick, using the TICK_MEMORY the Dashboards
#   plugin hands in (an empty dict when run by hand, so every warning fires).
#
# WHAT THIS REPLACED (all disabled 28-08-2026, not deleted — re-enable to revert)
#   schedule 664354581  Drive Light On At Sunset +30 Minutes
#   schedule 811853343  Drive Lights Off @ 23.50
#   trigger  116463730  Drive Garage Door Left Motion Turn On Garage Light
#   trigger  361163331  Drive Garage Door Right Motion Turn On Garage Light
#   trigger  1221572369 Drive Front Door Motion Sensor Turn On Entrance Light
#   trigger  932183569  Drive Lights Off When Lux Level Is False
#   trigger  1465160120 Drive Lights Off When No Motion Detected
#
# The three motion triggers had to go rather than merely being left alone: each
# turned the lights on with auto_complement_seconds=120, so any movement on the
# drive after dark would have switched them OFF two minutes later — the one
# thing an all-night light must not do.
#
# WHY A TICKED SCRIPT AND NOT A SCHEDULE
# indigo.schedule.create() takes no ACTION STEP, and a schedule's timing fields
# are read-only through the API, so neither making a new schedule nor retiming
# the old one is possible from here. This is ticked every 2 minutes by the
# Dashboards plugin, alongside the night sweep.
#
# Being ticked rather than fired once at sunset is the better shape anyway: it
# SELF-HEALS. A missed Zigbee command, a bulb that dropped off the mesh and came
# back, a power cut at 3am — the next tick puts it right, where a single
# sunset-edge command would have left the light wrong until the following night.

import logging
from datetime import datetime, timedelta

# ======================================
# CONFIGURATION
# ======================================
DEVICE_IDS = {
    "garage_light"     : 1641214619,   # "Garage Light"      (Hue A60, z2m)
    "front_door_light" : 1791262116,   # "Front Door Light"  (Hue A60, z2m)
}

BRIGHTNESS = 100        # per CliveS: full brightness, not a dimmed level
BRIGHTNESS_SLACK = 2    # a bulb reporting 98-99% after a 100% command is AT 100%

_MEM = globals().get("TICK_MEMORY")
if not isinstance(_MEM, dict):
    _MEM = {}


def warn_once(key, message, level="WARNING"):
    """Log when the message for `key` changes, not on every two-minute tick."""
    if _MEM.get(f"once:{key}") == message:
        return
    _MEM[f"once:{key}"] = message
    log(message, level=level)


def clear_once(key):
    _MEM.pop(f"once:{key}", None)

# Minutes either side of the sun event. Both zero = exactly sunset to sunrise.
SUNSET_OFFSET_MINUTES  = 0
SUNRISE_OFFSET_MINUTES = 0

_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
               "WARNING": logging.WARNING, "ERROR": logging.ERROR,
               "CRITICAL": logging.CRITICAL}


def _lvl(level):
    """indigo.server.log(level=...) wants an int; a STRING is silently ignored
    and the line logs as plain Info."""
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(
        f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [Drive Lights] {message}",
        level=_lvl(level))


def should_be_lit(now=None):
    """True between sunset and sunrise.

    Asked at 14:00, indigo.server.calculateSunset() returns TODAY's sunset
    (still ahead) and calculateSunrise() returns TOMORROW's — so a naive
    "after sunset AND before sunrise" test is false all afternoon and also
    false at 02:00, when sunset is tomorrow evening. Comparing against
    today's pair for the calendar day avoids that: dark is before this
    morning's sunrise, or after this evening's sunset.
    """
    now = now or datetime.now()
    today = now.date()
    sunrise = indigo.server.calculateSunrise(today) + timedelta(minutes=SUNRISE_OFFSET_MINUTES)
    sunset  = indigo.server.calculateSunset(today)  + timedelta(minutes=SUNSET_OFFSET_MINUTES)
    return now < sunrise or now >= sunset


def owner_plugin_running(device):
    """A stopped plugin swallows every action without raising. Anything that
    cannot be judged is allowed through — getPlugin() given an unknown id reads
    installed/enabled/running all False, indistinguishable from a real outage."""
    plugin_id = getattr(device, "pluginId", "") or ""
    if not plugin_id:
        return True
    try:
        plugin = indigo.server.getPlugin(plugin_id)
        return plugin.isRunning() if plugin.isInstalled() else True
    except Exception:
        return True


def apply(lit):
    """Bring both lights to the wanted state. Commands only on a mismatch, so a
    2-minute tick does not spam the Zigbee mesh all night."""
    changed = []
    for key, device_id in DEVICE_IDS.items():
        try:
            dev = indigo.devices[device_id]
        except Exception as e:
            warn_once(f"missing:{key}", f"{key} (id {device_id}) not found: {e}")
            continue
        clear_once(f"missing:{key}")
        if not dev.enabled:
            continue                       # disabled on purpose; states frozen
        if not owner_plugin_running(dev):
            continue                       # command would be swallowed
        raw = dev.states.get("onOffState")
        if raw is None:
            warn_once(f"unreadable:{key}", f"{dev.name} has no readable onOffState — skipped")
            continue
        clear_once(f"unreadable:{key}")
        is_on = bool(raw)
        bright = dev.states.get("brightnessLevel")
        if lit:
            # Also correct a light that is on but dimmed — being at 40% is as
            # wrong as being off when the whole point is full brightness.
            try:
                at_full = bright is not None and int(float(bright)) >= BRIGHTNESS - BRIGHTNESS_SLACK
            except (TypeError, ValueError):
                at_full = False
            if is_on and at_full:
                continue
            try:
                indigo.dimmer.setBrightness(dev, value=BRIGHTNESS)
                changed.append(f"{dev.name} -> {BRIGHTNESS}%")
                clear_once(f"cmd:{key}")
            except Exception as e:
                warn_once(f"cmd:{key}", f"Could not set {dev.name} to {BRIGHTNESS}%: {e}", level="ERROR")
        else:
            if not is_on:
                continue
            try:
                indigo.device.turnOff(dev)
                changed.append(f"{dev.name} -> off")
                clear_once(f"cmd:{key}")
            except Exception as e:
                warn_once(f"cmd:{key}", f"Could not turn off {dev.name}: {e}", level="ERROR")
    return changed


def main():
    lit = should_be_lit()
    changed = apply(lit)
    if changed:
        log(f"{'Sunset' if lit else 'Sunrise'} state applied: {', '.join(changed)}")


main()
