#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Drive_Lights_Sun.py
# Description: The outside lights — Garage Light, Front Door Light and Back Door
#              Light — on at 100% from sunset to sunrise, off the rest of the
#              time. One script owns them; it replaces seven separate pieces of
#              automation that used to share the job between them.
#
#              The FILE is still called Drive_Lights_Sun because the Dashboards
#              plugin ticks it by name; only the drive lights were here at the
#              start.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026 + UK Time Now
# Version:     1.4
#
# v1.4 (06-11-2026, CliveS & Claude Opus 5.5): all three cameras — Front Door,
#   Drive and Garage — now have their white lights on (Manual) from sunset to
#   sunrise and Off by day, instead of the Drive and Garage cameras deciding for
#   themselves on Auto. Every lighting profile a camera lists is set, because the
#   Garage camera switches profiles by its own day/night setting.
#
# v1.3 (05-11-2026, CliveS & Claude Opus 5.5): the Front Door CAMERA's own white
#   lights follow the same window. Its lighting was on Auto, set exactly like the
#   Drive camera, but with the Front Door Light at 100% all night the scene never
#   looks dark to it, so its four LEDs stayed off (measured: still off at the
#   highest Auto sensitivity, on at once in Manual). So from sunset to sunrise the
#   camera is put in Manual (lights on) and in daylight back to Auto. One HTTP
#   check every 30 minutes at most, sooner when the wanted mode changes.
#
# v1.2 (09-09-2026): the Back Door Light joins them. It used to be driven by the
#   side passage motion sensors — motion turns it on, a one-minute timer turns it
#   off again — and all three of those sensors had been dead for months (the
#   front one since October 2025) before anything noticed. The sensors, their
#   triggers, the timer and both side-passage scripts are gone; the light is now
#   simply on from sunset to sunrise like its neighbours. It is the same kind of
#   device as the other two — a z2m Hue bulb reported as a DimmerDevice — so the
#   loop below needed nothing but the extra entry.
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
import re
from datetime import datetime, timedelta

# ======================================
# CONFIGURATION
# ======================================
DEVICE_IDS = {
    "garage_light"     : 1641214619,   # "Garage Light"      (Hue A60, z2m)
    "front_door_light" : 1791262116,   # "Front Door Light"  (Hue A60, z2m)
    "back_door_light"  : 10602184,     # "Back Door Light"   (z2mLight, added 09-09-2026)
}

# The cameras' own white lights (v1.3 Front Door, v1.4 all three). Each address
# is read from the camera's DahuaEvents device, so a DHCP move or a new camera
# needs no edit here.
CAMERAS = {
    "front"  : (1314507580, "Front Door"),  # "Front Door Person" (DahuaEvents)
    "drive"  : (1083620697, "Drive"),       # "Drive Person"
    "garage" : (1166250201, "Garage"),      # "Garage Person"
}
CAM_MODE_DARK         = "Manual"           # lights on
CAM_MODE_LIGHT        = "Off"              # lights off
# Profile [0][0][0] is the one the Front Door and Drive cameras use all the time
# (VideoInMode Mode=0). It must be in the reply; every other [0][N][0] profile
# the camera lists is set to match.
CAM_MODE_KEY          = "Lighting_V2[0][0][0].Mode"
CAM_MODE_RE           = re.compile(r"^table\.(Lighting_V2\[0\]\[\d+\]\[0\]\.Mode)=(.*)$")
CAM_RECHECK_SECONDS   = 1800             # re-read the camera at most this often
CAM_RETRY_SECONDS     = 300              # after a failure, try again this soon
CAM_TIMEOUT_SECONDS   = 5
SECRETS_PATH          = "/Library/Application Support/Perceptive Automation/IndigoSecrets.py"

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
    """Bring every light to the wanted state. Commands only on a mismatch, so a
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


def _dahua_creds():
    """(user, password) from IndigoSecrets, loaded under its own module name.
    Per key, so a missing one does not blank the other."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("drive_lights_secrets", SECRETS_PATH)
    if not spec or not spec.loader:
        return "", ""
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "DAHUA_USER", ""), getattr(mod, "DAHUA_PASS", "")


def _http_get(url, user, password):
    """One digest-auth GET to the camera. Returns the body text."""
    import requests
    from requests.auth import HTTPDigestAuth
    r = requests.get(url, auth=HTTPDigestAuth(user, password), timeout=CAM_TIMEOUT_SECONDS)
    r.raise_for_status()
    return r.text


def _camera(key, device_id, label, want, now_ts):
    """Bring one camera's white lights to `want`. Returns a description of a
    change made, or None. Every lighting profile the camera lists is set, so it
    does not matter which one its day/night setting has it using (the Garage
    camera runs VideoInMode 3, the other two 0)."""
    if (_MEM.get(f"cam:{key}:mode") == want
            and now_ts - _MEM.get(f"cam:{key}:checked", 0) < CAM_RECHECK_SECONDS):
        return None
    if now_ts < _MEM.get(f"cam:{key}:retry_after", 0):
        return None
    try:
        address = (indigo.devices[device_id].address or "").strip()
    except Exception as e:
        warn_once(f"cam:{key}", f"{label} camera device (id {device_id}) not found: {e}")
        return None
    if not address:
        warn_once(f"cam:{key}", f"{label} camera device has no address, so its lights cannot be set")
        return None
    try:
        user, password = _dahua_creds()
    except Exception as e:
        warn_once(f"cam:{key}", f"Could not read the Dahua login from IndigoSecrets: {e}", level="ERROR")
        return None
    if not user or not password:
        warn_once(f"cam:{key}", "DAHUA_USER or DAHUA_PASS is missing from IndigoSecrets.py, "
                                f"so the {label} camera lights cannot be set", level="ERROR")
        return None
    base = f"http://{address}/cgi-bin/configManager.cgi"
    try:
        body = _http_get(f"{base}?action=getConfig&name=Lighting_V2", user, password)
        modes = {}
        for line in body.splitlines():
            m = CAM_MODE_RE.match(line.strip())
            if m:
                modes[m.group(1)] = m.group(2).strip()
        if CAM_MODE_KEY not in modes:
            raise ValueError(f"{CAM_MODE_KEY} not in the camera's reply")
        wrong = [k for k, v in modes.items() if v != want]
        change = None
        if wrong:
            # One request. The camera applies all of it or none of it.
            query = "&".join(f"{k}={want}" for k in wrong)
            reply = _http_get(f"{base}?action=setConfig&{query}", user, password)
            if reply.strip() != "OK":
                raise ValueError(f"camera answered '{reply.strip()[:40]}' to the change")
            change = (f"{label} camera lights {modes[CAM_MODE_KEY]} -> {want}"
                      if modes[CAM_MODE_KEY] != want
                      else f"{label} camera lights -> {want} ({len(wrong)} other lighting profiles)")
    except Exception as e:
        _MEM[f"cam:{key}:retry_after"] = now_ts + CAM_RETRY_SECONDS
        warn_once(f"cam:{key}", f"Could not set the {label} camera lights to {want}: {e}", level="ERROR")
        return None
    _MEM[f"cam:{key}:mode"] = want
    _MEM[f"cam:{key}:checked"] = now_ts
    _MEM.pop(f"cam:{key}:retry_after", None)
    clear_once(f"cam:{key}")
    return change


def camera_lights(lit, now_ts=None):
    """Every camera's white lights: Manual (on) when dark, Off in daylight.

    Returns the changes made, as a list. A camera is only asked when the wanted
    mode differs from the last one confirmed, or the last check is
    CAM_RECHECK_SECONDS old, so a two-minute tick is not an HTTP call. One
    camera failing does not stop the others."""
    import time
    now_ts = now_ts if now_ts is not None else time.time()
    want = CAM_MODE_DARK if lit else CAM_MODE_LIGHT
    changes = []
    for key, (device_id, label) in CAMERAS.items():
        try:
            change = _camera(key, device_id, label, want, now_ts)
        except Exception as e:                    # never let one camera stop the tick
            warn_once(f"cam:{key}", f"{label} camera lights check failed: {e}", level="ERROR")
            change = None
        if change:
            changes.append(change)
    return changes


def main():
    lit = should_be_lit()
    changed = apply(lit)
    changed.extend(camera_lights(lit))
    if changed:
        log(f"{'Sunset' if lit else 'Sunrise'} state applied: {', '.join(changed)}")


main()
