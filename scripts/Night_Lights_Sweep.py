#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Night_Lights_Sweep.py
# Description: Overnight backstop. Every few minutes it checks that no light is
#              burning in an empty room, and that the living room fire is out.
#              Everything else in the estate turns lights off in response to a
#              HUMAN event — bedtime, departure, presence clearing, a Wallmote
#              press — or to dawn. Nothing watched for a light that came on with
#              no command behind it, which is how the Hall Lamp burned from
#              04:17 to 04:51 on 27-08-2026 after the bulb re-announced itself
#              on the Zigbee network and came up at 100%. Had nobody got up it
#              would simply have burned on. Lights_Off_Due_To_Lux_Level.py was
#              written to catch exactly that at dawn, but it was attached to no
#              trigger until 14-09-2026 and had never once run, so on 27-08 there
#              was nothing downstream to stop it. This closes that gap.
# Author:      CliveS & Claude Opus 5
# Date:        24-09-2026 + UK Time Now
# Version:     1.8
#
# v1.8 (24-09-2026) — the Living Room Door Motion Sensor is out of the
#   living room zone: CliveS is removing the device. The three FP300 presence
#   sensors cover the room.
#
# v1.7 (23-09-2026) — the gap warning no longer names Dashboards as the thing that
#   runs this: the Script Ticker plugin does now, and Dashboards only when it is not.
#
# v1.6 (21-09-2026) — THE FIRE IS NO LONGER RE-SENT WHEN ITS PLUG SAYS IT IS
#   OFF. Broadlink RF 1.4.0 lets Fire On/Off read the Living Room Fire Plug, and
#   publishes the answer as measuredState: "on", "off" or "unknown". A plug
#   reading standby (0.5 W against 37 W with the flame lit) is a measurement,
#   not a belief, so the hourly belt-and-braces OFF has nothing to guard
#   against — seven sends a night, every night, to a fire that was out.
#   Only "off" skips. "unknown" (no meter, meter disabled, in error or silent)
#   and a missing state both fall back to the old open-loop assert, so losing
#   the plug can never stop the fire being turned off. "on" in a quiet room is
#   now reported as what the plug reads, and the plugin itself confirms the OFF
#   or warns that the fire ignored it.
#
# v1.5 (07-09-2026) — THE HOURLY FIRE LINE IS NO LONGER SHOUTED. Seven lines
#   a night said the same thing: the room was quiet, the OFF code went out,
#   and Indigo had already believed the fire was off. 23 of them in the three
#   days to 07-09-2026 and not ONE was a drifted belief. That is the hourly
#   belt-and-braces re-send doing exactly its job, which is to say it is what
#   RAN, not what CHANGED. Two parts:
#     (1) The message splits by whether anything was actually wrong. Indigo
#         believing the fire was ON in a room quiet for the whole period is a
#         drifted belief with a 1.5 kW heater behind it — the exact fault this
#         function exists to catch, so it stays at INFO and is still seen. The
#         believed-off re-send drops to DEBUG. Both keep the honest 'no RF
#         return path' wording: the OFF code is still transmitted every time,
#         and nothing about WHEN it is sent has changed.
#     (2) log() gained the estate-standard DEBUG_LOGGING gate, because
#         choosing DEBUG silences nothing on its own. MEASURED 07-09-2026:
#         indigo.server.log(level=logging.DEBUG) reaches the event log like
#         any other line, tagged source '<Plugin> Debug' — the v1.4
#         'phase:sensorless-held' notice was written as DEBUG precisely to be
#         quiet and had been visible all along. The gate only ever tests below
#         INFO, so WARNING and ERROR stay audible by construction.
#   The lights-off and lights-on scripts are untouched: when one of those
#   turns the fire off it is reporting a change it made, and that stays INFO.
#
# v1.4 (06-09-2026) — IT NOW COVERS THE EVENING, which is when it was needed and
#   was not there. The clock window was 00:00-06:00, so a light left on at 21:11
#   had no backstop for nearly three hours. That is exactly what happened this
#   evening: Living_Room_Lights_Off.py debounced away the run in which the room
#   finally read empty, and the lamps, both plugs and the 1.5 kW fire ran on with
#   nothing whatever watching. Three parts, and the last two are why this is not
#   simply a smaller number:
#     (1) The window WRAPS and opens at EVENING_START = 19:00 — the hour
#         Living_Room_Lights_Off.py's own afternoon protection ends, so the
#         backstop starts exactly where the room script itself becomes willing
#         to act. `DEEP_NIGHT_START <= hour < DEEP_NIGHT_END` cannot express a
#         window that crosses midnight; it silently reads False for every hour
#         of it, so the comparison had to change too.
#     (2) The evening demands a LONGER unbroken quiet run — 30 minutes against
#         the deep night's 15. An empty lit room in the evening has innocent
#         explanations that 3am does not, and the room scripts are still awake
#         and will act first if they can. Being slower than the controller is
#         the whole point of a backstop.
#     (3) A zone with NO sensors of its own still waits for deep night. Hall and
#         conservatory ride the whole-house quiet test, and that test knows
#         nothing about the bedrooms or the bathroom — neither is a zone. At 3am
#         that is right, because everyone is in bed. At 21:00 it would put out
#         the lit pathway to the bedroom while somebody stood in the bathroom.
#         So the sensored rooms gain the evening and the sensorless ones do not.
#   `Nightime` still widens the window as before, and a Wallmote press is a real
#   "we have gone to bed" signal, so it counts as deep night for (2) and (3).
#
# v1.3 (02-09-2026) — Living Room Right Presence Sensor (1899487413) joins the
#   living_room zone beside Left and Centre.
#
# v1.2 (02-09-2026, Dashboards deep review): (1) turn-off VERIFICATION happens
#   on the NEXT tick, not after a time.sleep() — this runs inside the Dashboards
#   plugin's background loop, and a sweep that turned off three lights held the
#   camera poller for up to 36 s and could not see the plugin's stop signal.
#   (2) A daytime tick still touches last_run, so the first night tick no
#   longer discards every streak and warns about a schedule gap that does not
#   exist. (3) A light whose plugin reports it offline (deviceOnline False,
#   z2m availability "offline", errorState) is UNREADABLE, not on — commanding
#   it produced two warnings and an error every 15 minutes for nothing.
#   (4) State-file markers are epoch seconds, so a clock change cannot
#   mis-measure a streak (the old naive strings read a 2-minute gap as 62
#   minutes in March and about -58 in October). (5) TICK_MEMORY, handed in by
#   the plugin, lets a warning fire once when it changes rather than every two
#   minutes. (6) The state path derives from Indigo, not a literal.
#
# v1.1 (27-08-2026) — honours the living room override, so the Virtual On/Off
#       Device can hold the room and the fire lit through the night while
#       somebody is actually in there. The flag lapses the moment presence
#       reads clear, and the shared module does the clearing.
#
# DESIGN NOTES — read before changing anything
#
# * It is a BACKSTOP, not a controller. The room scripts are faster and know
#   more; this only acts long after they should have. Being slow is the point.
#
# * A light is turned off only after an UNBROKEN run of observations, each one
#   seeing the light on AND the room unoccupied. Endpoints prove nothing: two
#   readings fifteen minutes apart are equally consistent with somebody using
#   the room throughout. Any presence, any off-reading, and the streak resets.
#
# * If the gap since the previous run exceeds MAX_GAP_MINUTES, every streak is
#   discarded. Nothing watched the middle of that gap, so nothing may be
#   concluded about it. This makes a stopped or slow schedule fail SAFE — the
#   sweep simply never acts — and it says so in the log rather than going quiet.
#
# * Unreadable is OCCUPIED, never empty. A disabled sensor keeps whatever state
#   it held when it was disabled, a stopped plugin freezes all of them, and a
#   sensor that has never reported reads None — which equals False in Python and
#   would otherwise pass as "clear". Silence is not evidence of an empty room.
#
# * THE FIRE IS OPEN LOOP AND IS HANDLED DIFFERENTLY. Fire On/Off is a Broadlink
#   RF relay driving a New Forest 1600 over 433.92 MHz. There is no return path,
#   so its onOffState is only what the plugin last transmitted — a belief, not a
#   reading. Waiting for it to read "on" before acting would miss the exact case
#   that matters: the belief having drifted while a 1.5 kW heater runs all night.
#   So the fire is ASSERTED off whenever the living room has been quiet, whatever
#   Indigo thinks. That is safe only because the OFF code is DISCRETE
#   (fire_off_short), not a toggle — a repeat send cannot light it. If anyone
#   ever repoints offCodeName at a toggle code, this must change with it.
#   The assert is rate-limited so it does not transmit on every tick.
#
# * A turn-off is CHECKED, never assumed. indigo.device.turnOff() does not raise
#   when the owning plugin cannot reach the hardware — the plugin logs its own
#   error and the call returns normally. So: command, settle, re-read fresh,
#   retry once, then WARN. The fire is the exception and is reported honestly as
#   sent-but-unverifiable, because it genuinely cannot be checked.
#
# * Bedrooms and the bathroom are deliberately OUT of scope. A bedroom lamp
#   going off by itself at 3am is a worse outcome than the fault this prevents,
#   and the bathroom already has its own script and timer. Two owners for one
#   light is how they end up fighting.

import os
import json
import time
import logging
from datetime import datetime, timedelta

import sys as _sys
_INCLUDES = "/Library/Application Support/Perceptive Automation/Python3-includes"
if _INCLUDES not in _sys.path:    # exec()ed every 2 min from the Dashboards host — never grow its path
    _sys.path.insert(0, _INCLUDES)
try:
    import living_room_override as _override
except ImportError:
    _override = None       # fail towards sweeping, never towards a room left lit

# Ticked from the Dashboards plugin host, the shared rule module is cached in
# that process for its whole life, so an edit to it would not be live here
# until the plugin restarted. Reload it each tick — one small pure-Python
# file every two minutes.
if _override is not None and "TICK_MEMORY" in globals():
    try:
        import importlib as _importlib
        _override = _importlib.reload(_override)
    except Exception:
        pass

# Memory that survives between ticks when the Dashboards plugin runs this
# (it passes TICK_MEMORY in); an empty dict when run by hand, which means
# every warning fires — the right behaviour for a one-off run.
_MEM = globals().get("TICK_MEMORY")
if not isinstance(_MEM, dict):
    _MEM = {}

# ======================================
# CONFIGURATION
# ======================================

# The room must have been unoccupied, and the light on, for this long — proven
# by an unbroken run of observations, not by two endpoints.
#
# Two figures since v1.4. The deep-night one is the original. The evening one is
# longer because an empty lit room at 21:00 has innocent explanations that it
# does not have at 3am — somebody stepping out to the kitchen mid-programme, a
# room script deliberately holding the lit pathway to the bedroom for two
# minutes — and because the room scripts are awake and will act first if they
# can. A backstop that acts as fast as the controller is not a backstop.
QUIET_MINUTES         = 15
EVENING_QUIET_MINUTES = 30

# Discard every streak if the previous run was longer ago than this. The
# schedule should tick every 2-5 minutes; at 10 the sweep stops acting rather
# than acting on a window it did not watch.
MAX_GAP_MINUTES = 10

# Don't re-transmit the fire's OFF code more often than this once a room has
# gone quiet. One assertion an hour is plenty for a belief that rarely drifts.
FIRE_REASSERT_MINUTES = 60

# Nightime alone is not enough to rely on: it is set by a Wallmote press, so a
# night nobody pressed it would silently disable the safety net. The clock
# window is the floor, the flag widens it.
#
# DEEP NIGHT is the phase in which the whole house can be assumed asleep, so a
# zone with no sensors of its own may ride the whole-house quiet test.
DEEP_NIGHT_START = 0     # 00:00
DEEP_NIGHT_END   = 6     # 06:00 (exclusive)

# EVENING extends the sweep back to 19:00 for zones judged by their OWN sensors.
# 19:00 is not a round number picked for comfort: it is the hour
# Living_Room_Lights_Off.py's afternoon protection window ends, i.e. the hour
# that script itself becomes willing to shut the room down. Starting the
# backstop there means the two agree by construction. Everything is still gated
# on Lux_Level, so this never runs in daylight — which is what keeps a December
# 16:00 dusk out of it.
EVENING_START = 19       # 19:00, wrapping through midnight to DEEP_NIGHT_END

VERIFY_MIN_SECONDS = 30       # never judge a turn-off on the tick that sent it

VARIABLE_IDS = {
    "nighttime": 743437830,   # "Nightime"  — true once the household has gone to bed
    "lux_level": 241032502,   # "Lux_Level" — true means DAYLIGHT (see Lux_Update.py)
}

FIRE_DEVICE_ID = 614164061    # "Fire On/Off" — Broadlink RF relay, New Forest 1600

# Zones. `sensors` are read at tick time; the mmWave presence sensors HOLD while
# someone is in the room, so a point read is meaningful for them. A zone with an
# EMPTY sensor list has none of its own and falls back to the whole-house quiet
# test — that is the hall and the conservatory, and it is why the hall lamp is
# covered at all.
ZONES = {
    "living_room": {
        "sensors": [1909477979,   # Living Room Left Presence Sensor   (FP300)
                    1496890672,   # Living Room Centre Presence Sensor (FP300)
                    1899487413],  # Living Room Right Presence Sensor  (FP300)
        "lights":  [1765266302,   # Living Room Main Light
                    372666822,    # Living Room Colour Lamp
                    515728864,    # Display Lights Plug
                    1293995000],  # Twigs Plug (carries the feature-wall shelf lights)
    },
    "kitchen": {
        "sensors": [557577796,    # Kitchen Left Presence Sensor
                    1459746226],  # Kitchen Right Presence Sensor
        "lights":  [367205956,    # Kitchen Spot Lights
                    24644862],    # Kitchen Cupboard Lights
    },
    "dining_room": {
        "sensors": [631401728],   # Dining Room Presence Sensor
        "lights":  [1519699078],  # Dining Room Light
    },
    "garage": {
        "sensors": [584359376],   # Garage Presence Sensor
        # Garage Light (1641214619) is NOT here: Drive_Lights_Sun.py holds it
        # on from sunset to sunrise on purpose, and the sweep would have turned
        # it off 15 minutes after the garage last read empty — every night.
        "lights":  [888019821],   # Garage Strip Lights
    },
    "hall": {
        # Hall-Bedroom Motion Sensor is a PIR: it pulses rather than holding, so
        # a point read of it says almost nothing. Left out deliberately — the
        # hall rides on the whole-house quiet test instead.
        "sensors": [],
        "lights":  [1061201491,   # Hall Lamp
                    396627350],   # Hall Cupboard Light
    },
    "conservatory": {
        "sensors": [],            # no presence sensor in the room
        "lights":  [974294416],   # Conservatory Lamp Plug
    },
}

# Deliberately excluded, and why:
#   Bedroom 1 / 3 lamps  — they are asleep in there; a lamp dying at 3am is worse
#                          than the fault this prevents.
#   Bathroom Light       — Bathroom_Lights_Off.py and its timer already own it.
#   Front Door Light     — outside, and reasonably left lit overnight.

def _scripts_dir():
    """Where this script and its state live. __file__ when run as a file;
    otherwise (exec()ed by the Dashboards plugin) derived from Indigo — the
    two script folders sit at the Perceptive Automation ROOT, one level
    above the versioned folder getInstallFolderPath() returns."""
    if "__file__" in globals():
        return os.path.dirname(os.path.abspath(__file__))
    try:
        return os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()), "Python Scripts")
    except Exception:
        # A test harness's stub indigo has no server — the folder is the same
        # on every Indigo install, so the literal is a safe last resort.
        return "/Library/Application Support/Perceptive Automation/Python Scripts"


STATE_PATH = os.path.join(_scripts_dir(), "night_lights_sweep_state.json")

DEBOUNCE_LOCK_PATH = "/tmp/night_lights_sweep.lock"
DEBOUNCE_SECONDS   = 20

TS_FMT = "%Y-%m-%d %H:%M:%S"

# ======================================
# LOGGING
# ======================================
# Set True to add the per-run DEBUG trace. INFO and above ALWAYS log — see
# the note in log() for why the gate is needed at all.
DEBUG_LOGGING = False

_LOG_LEVELS = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored and
    the line logs as plain Info, which hides every WARNING and ERROR.
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    # DEBUG_LOGGING silences the DEBUG trace and NOTHING else.
    #
    # The gate has to exist because CHOOSING DEBUG SUPPRESSES NOTHING BY
    # ITSELF. Measured 07-09-2026: indigo.server.log(level=logging.DEBUG)
    # lands in the event log like any other line, tagged with the source
    # '<Plugin> Debug'. So v1.4's 'phase:sensorless-held' notice — written as
    # DEBUG for the express purpose of being quiet, and commented as such —
    # had been printing every evening regardless. Indigo's own log level is
    # not the script's to set, so the script has to hold the gate.
    #
    # The rule the levels follow: INFO says what CHANGED, DEBUG says what RAN.
    #
    # The gate only ever tests BELOW INFO, so a fault stays audible by
    # construction — the 04-09-2026 lesson that a quiet flag must never
    # silence a WARNING or an ERROR.
    if _lvl(level) < logging.INFO and not DEBUG_LOGGING:
        return
    indigo.server.log(
        f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [Night Sweep] {message}",
        level=_lvl(level))



def warn_once(key, message, level="WARNING"):
    """Log when the message for `key` CHANGES, not every tick. A stopped
    plugin or a missing device is one fact; it does not need saying 720
    times a day, and the log watch counts every one of those as a signature."""
    if _MEM.get(f"once:{key}") == message:
        return
    _MEM[f"once:{key}"] = message
    log(message, level=level)


def clear_once(key):
    _MEM.pop(f"once:{key}", None)


def _epoch(marker):
    """A state-file marker -> epoch seconds, accepting the v1.1 naive-string
    form once so an existing file migrates itself. None if unreadable."""
    if marker is None or marker == "":
        return None
    if isinstance(marker, (int, float)):
        return float(marker)
    try:
        return datetime.strptime(str(marker), TS_FMT).timestamp()
    except Exception:
        return None


def _age_min(marker, now):
    """Minutes since a marker, by plain epoch subtraction — a naive local
    datetime difference is an hour out across a clock change."""
    e = _epoch(marker)
    return None if e is None else (now.timestamp() - e) / 60.0

# ======================================
# STATE
# ======================================

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"last_run": None, "streaks": {}, "fire_asserted_at": None}
    except Exception as e:
        # A corrupt state file must not make the sweep act on a streak it cannot
        # vouch for. Start again from nothing — that costs one quiet period.
        log(f"Could not read state ({e}) — starting the streaks again", level="WARNING")
        return {"last_run": None, "streaks": {}, "fire_asserted_at": None}


def save_state(state):
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, STATE_PATH)          # atomic — never a half-written file
    except Exception as e:
        log(f"Could not save state: {e}", level="ERROR")


def is_debounced():
    """Cross-process guard. Each schedule fire is a fresh interpreter, so an
    in-memory flag would not be seen by a concurrent run."""
    try:
        if time.time() - os.path.getmtime(DEBOUNCE_LOCK_PATH) < DEBOUNCE_SECONDS:
            return True
    except FileNotFoundError:
        pass
    try:
        with open(DEBOUNCE_LOCK_PATH, "w") as fh:
            fh.write(str(time.time()))
    except Exception:
        pass
    return False


# ======================================
# READING THE HOUSE
# ======================================

_PLUGIN_RUNNING = {}


def owner_plugin_running(device):
    """True unless the device's owning plugin is installed but NOT running.

    A stopped plugin swallows every action sent to its devices without raising,
    and leaves their states frozen at the moment it died. Anything we cannot
    judge is allowed through: getPlugin() given an id it does not know returns
    an object reading installed/enabled/running all False, indistinguishable
    from a real outage, so an unknown id must not be what stops the sweep.
    """
    plugin_id = getattr(device, "pluginId", "") or ""
    if not plugin_id:
        return True
    if plugin_id in _PLUGIN_RUNNING:
        return _PLUGIN_RUNNING[plugin_id]
    running = True
    try:
        plugin = indigo.server.getPlugin(plugin_id)
        if plugin.isInstalled():
            running = plugin.isRunning()
            if not running:
                warn_once(f"plugin:{plugin_id}",
                          f"{plugin_id} is not running — its devices' states are stale "
                          f"and any command to them would be swallowed")
            else:
                clear_once(f"plugin:{plugin_id}")
    except Exception as e:
        log(f"Could not check plugin {plugin_id}: {e}", level="ERROR")
    _PLUGIN_RUNNING[plugin_id] = running
    return running


def read_light_on(device_id):
    """True on, False off, None UNREADABLE — and unreadable is not off."""
    try:
        dev = indigo.devices[device_id]
    except Exception:
        return None, None
    if not getattr(dev, "enabled", True):
        return None, dev
    if not owner_plugin_running(dev):
        return None, dev
    # Its own plugin says it cannot reach it: the state is the last thing seen,
    # not a reading, and a command would fail. Unreadable, not on (v1.2).
    st = dev.states
    if (st.get("deviceOnline") is False
            or str(st.get("availability", "")).strip().lower() == "offline"
            or (getattr(dev, "errorState", "") or "").strip()):
        return None, dev
    raw = st.get("onOffState")
    if raw is None:
        return None, dev
    return bool(raw), dev


def read_presence(device_id):
    """One sensor: True present, False clear, None unreadable."""
    try:
        dev = indigo.devices[device_id]
    except Exception:
        return None
    if not getattr(dev, "enabled", True):
        return None
    if not owner_plugin_running(dev):
        return None
    raw = dev.states.get("onOffState")
    if raw is None:
        return None
    return bool(raw)


def zone_unoccupied(zone_name, zone):
    """True only when the zone is positively known to be empty.

    A zone with sensors is judged by them, and if NONE of them is readable the
    zone counts as occupied — silence is unknown, not empty. A zone with no
    sensors configured returns None, meaning 'ask the house'.
    """
    sensor_ids = zone.get("sensors") or []
    if not sensor_ids:
        return None
    readings = [read_presence(i) for i in sensor_ids]
    if any(r is True for r in readings):
        return False
    if all(r is None for r in readings):
        log(f"No sensor in {zone_name} is readable — treating it as occupied",
            level="WARNING")
        return False
    return True


# ======================================
# ACTING
# ======================================

def _still_on(device_id):
    """Re-read FRESH. A device object held from earlier is a snapshot and never
    updates, so checking one would always report the state we started with."""
    try:
        dev = indigo.devices[device_id]
    except Exception as e:
        return False, f"could not re-read ({e})"
    if not dev.states.get("deviceOnline", True):
        return bool(dev.onState), "the plug is offline"
    if getattr(dev, "errorState", ""):
        return bool(dev.onState), f"errorState={dev.errorState}"
    return bool(dev.onState), ""


def send_off(device, zone_name, state, now):
    """Command it off and remember to CHECK on the next tick (v1.2).

    The check used to be a time.sleep(6) followed by a re-read, twice — but
    this runs inside the Dashboards plugin's background loop, where a sleep
    holds every other task and cannot see the plugin's stop signal. The next
    tick is two minutes away, which is longer than any settle time, so the
    verification simply waits for it. Returns True if the command was SENT.
    """
    try:
        indigo.device.turnOff(device)
    except Exception as e:
        log(f"{device.name} ({zone_name}) — turn-off raised: {e}", level="ERROR")
        return False
    pending = state.setdefault("pending_verify", {})
    pending[str(device.id)] = {"at": now.timestamp(), "attempts": 1,
                               "name": device.name, "zone": zone_name}
    return True


def verify_pending(state, now):
    """Prove last tick's turn-offs went off; retry once; then say so."""
    pending = state.get("pending_verify") or {}
    if not isinstance(pending, dict):
        pending = {}
    for did, rec in list(pending.items()):
        try:
            if now.timestamp() - float(rec.get("at", 0)) < VERIFY_MIN_SECONDS:
                continue
            still_on, detail = _still_on(int(did))
        except Exception as e:
            log(f"Could not verify {rec.get('name', did)}: {e}", level="WARNING")
            pending.pop(did, None)
            continue
        name, zone = rec.get("name", did), rec.get("zone", "")
        if not still_on:
            pending.pop(did, None)
            continue
        if int(rec.get("attempts", 1)) < 2:
            log(f"{name} ({zone}) did not go off — retrying"
                f"{' (' + detail + ')' if detail else ''}", level="WARNING")
            try:
                indigo.device.turnOff(indigo.devices[int(did)])
            except Exception as e:
                log(f"Retry of {name} raised: {e}", level="ERROR")
            rec["attempts"] = 2
            rec["at"] = now.timestamp()
        else:
            log(f"{name} ({zone}) is STILL ON after two attempts"
                f"{' — ' + detail if detail else ''}", level="WARNING")
            pending.pop(did, None)
    state["pending_verify"] = pending


def assert_fire_off(now, state, living_room_quiet_since, quiet_needed=QUIET_MINUTES):
    """Send the fire's discrete OFF code, whatever Indigo believes.

    The relay is open loop: onOffState is the last thing transmitted, not a
    reading, so acting only when it reads 'on' would miss a drifted belief with
    a 1.5 kW heater behind it. Re-asserting is safe because fire_off_short is a
    discrete OFF, not a toggle — this is checked below rather than assumed.
    """
    if living_room_quiet_since is None:
        return
    if (now - living_room_quiet_since) < timedelta(minutes=quiet_needed):
        return

    since = _age_min(state.get("fire_asserted_at"), now)
    if since is not None and since < FIRE_REASSERT_MINUTES:
        return

    try:
        fire = indigo.devices[FIRE_DEVICE_ID]
    except Exception as e:
        warn_once("fire:missing",
                  f"Fire device {FIRE_DEVICE_ID} is missing ({e}) — cannot assert it off")
        return
    clear_once("fire:missing")
    if not fire.enabled or not owner_plugin_running(fire):
        warn_once("fire:unavailable",
                  "Fire is disabled or its plugin is not running — OFF not sent")
        return
    clear_once("fire:unavailable")

    props = fire.globalProps.get(fire.pluginId, {}) or fire.pluginProps
    off_code = str(props.get("offCodeName", ""))
    if "toggle" in off_code.lower():
        # Re-asserting a toggle would LIGHT it. Refuse rather than risk that.
        log(f"Fire offCodeName is {off_code!r}, which looks like a toggle — "
            f"refusing to re-assert, as a repeat send could light it",
            level="WARNING")
        return

    # Broadlink RF 1.4.0 and later: a power meter on the fire turns the belief
    # into a reading. Only a reading of "off" is trusted to skip the send —
    # "unknown", or no such state at all, keeps the open-loop assert, so losing
    # the plug can never stop the fire being turned off. The rate-limit clock is
    # NOT reset here, so the moment the plug reads on the next tick acts.
    measured = str(fire.states.get("measuredState", "") or "").strip().lower()
    if measured == "off":
        return

    believed_on = fire.onState
    try:
        indigo.device.turnOff(fire)
        state["fire_asserted_at"] = now.timestamp()
        # INFO says what CHANGED, DEBUG says what RAN, and which of those this
        # is depends entirely on what Indigo believed a moment ago.
        #
        # Believed ON, in a room quiet for the whole period: a drifted belief
        # with a 1.5 kW heater behind it. That is the fault this function
        # exists to catch, and it must be seen.
        #
        # Believed OFF: the hourly belt-and-braces re-send, changing nothing.
        # It put seven identical lines in the log a night — 23 in the three
        # days to 07-09-2026, not one of them a drift — which is the shape of
        # a line nobody can read any more.
        #
        # Honest wording on BOTH paths: RF has no return path, so this is what
        # was SENT, never what the fire received.
        if measured == "on":
            watts = fire.states.get("measuredWatts")
            log(f"Living room quiet but the fire's plug reads {watts} W, so it is "
                f"on — sent its OFF code ({off_code}). The plugin will say if "
                f"the fire does not respond.", level="INFO")
        elif believed_on:
            log(f"Living room quiet but Indigo believed the fire was ON — "
                f"sent its OFF code ({off_code}). No RF return path, so this "
                f"is not confirmation the fire received it.", level="INFO")
        else:
            log(f"Living room quiet — re-sent the fire's OFF code ({off_code}); "
                f"Indigo already believed it was off. No RF return path, so "
                f"this is not confirmation the fire received it.", level="DEBUG")
    except Exception as e:
        log(f"Sending the fire OFF code raised: {e}", level="ERROR")


# ======================================
# MAIN
# ======================================

def _in_hour_window(hour, start, end):
    """True if `hour` falls in [start, end), correctly when the window WRAPS.

    `start <= hour < end` is silently False for EVERY hour of a window that
    crosses midnight, which is how an evening start of 19:00 would have read as
    "never" rather than as an error.
    """
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def night_now(now):
    """(should_run, why, deep) — deep is True when the house can be assumed asleep.

    `deep` gates the two things the evening must not have: the shorter quiet
    period, and the whole-house fallback that sweeps rooms with no sensors of
    their own. A Wallmote press (Nightime) is a real "we have gone to bed"
    signal, so it counts as deep whatever the clock says.
    """
    try:
        if str(indigo.variables[VARIABLE_IDS["lux_level"]].value).strip().lower() == "true":
            return False, "it is daylight", False
    except Exception as e:
        log(f"Could not read Lux_Level ({e}) — standing down", level="WARNING")
        return False, "lux unreadable", False

    deep_window    = _in_hour_window(now.hour, DEEP_NIGHT_START, DEEP_NIGHT_END)
    evening_window = _in_hour_window(now.hour, EVENING_START, DEEP_NIGHT_END)
    nighttime = False
    try:
        nighttime = str(indigo.variables[VARIABLE_IDS["nighttime"]].value).strip().lower() == "true"
    except Exception as e:
        log(f"Could not read Nightime ({e}) — relying on the clock window only",
            level="WARNING")

    deep = deep_window or nighttime
    if deep:
        return True, "deep night" if deep_window else "Nightime set", True
    if evening_window:
        return True, "evening", False
    return False, "not night yet", False


def main():
    if is_debounced():
        return

    now = datetime.now()
    ok, why, deep = night_now(now)
    quiet_needed = QUIET_MINUTES if deep else EVENING_QUIET_MINUTES
    state = load_state()
    if not ok:
        # Daytime. Still check on last night's final turn-offs, and keep
        # last_run current: with it frozen at the previous night's end, the
        # first night tick read a 15-hour "gap" and warned about a schedule
        # problem that did not exist, every single evening. Written at most
        # every five minutes, so a quiet day costs a few hundred tiny writes.
        verify_pending(state, now)
        stale = bool(state.get("streaks")) or state.get("living_room_quiet_since")
        lr_age = _age_min(state.get("last_run"), now)
        if stale or lr_age is None or lr_age > 5:
            state["streaks"] = {}
            state["living_room_quiet_since"] = None
            state["last_run"] = now.timestamp()
            state["last_run_text"] = now.strftime(TS_FMT)
            save_state(state)
        return

    streaks = state.get("streaks") or {}
    verify_pending(state, now)

    # A gap we did not watch tells us nothing about what happened inside it.
    gap_min = _age_min(state.get("last_run"), now)
    if gap_min is not None and gap_min > MAX_GAP_MINUTES:
        log(f"{int(gap_min)} minutes since the last sweep (limit {MAX_GAP_MINUTES}) — "
            f"discarding every streak, because nothing observed that gap. "
            f"Script Ticker (or Dashboards, when Script Ticker is not running) runs this "
            f"every 2 minutes; was it stopped?",
            level="WARNING")
        streaks = {}
        state["fire_asserted_at"] = None
        state["living_room_quiet_since"] = None

    # 1. Judge every zone that has sensors of its own.
    verdicts = {name: zone_unoccupied(name, z) for name, z in ZONES.items()}
    sensored = [v for v in verdicts.values() if v is not None]
    house_quiet = bool(sensored) and all(sensored)

    # 2. A sensorless zone rides on the whole house being quiet — but ONLY in
    #    deep night. The whole-house test is built from the sensored zones, and
    #    the bedrooms and the bathroom are not among them, so at 21:00 it would
    #    read "house quiet" with somebody standing in the bathroom and put out
    #    the lit pathway to the bedroom. At 3am the same test is sound, because
    #    everyone being in bed is precisely what it is entitled to assume.
    rode_the_house = {name for name, v in verdicts.items() if v is None}
    for name in rode_the_house:
        verdicts[name] = house_quiet if deep else False
    # warn_once, not log: this is one standing fact about the phase, and the
    # sweep ticks every two minutes — saying it plainly would put ~150 identical
    # lines in the log every evening, and Log_Error_Watch.py counts each one.
    if rode_the_house and not deep:
        warn_once("phase:sensorless-held",
                  f"Evening sweep — {', '.join(sorted(rode_the_house))} left alone "
                  f"until deep night, having no sensors of their own",
                  level="DEBUG")
    else:
        clear_once("phase:sensorless-held")

    turned_off, living_room_quiet_since = [], None

    for zone_name, zone in ZONES.items():
        unoccupied = verdicts[zone_name]

        # The living room override. Held only while the room reads occupied, so
        # it lapses by itself — and holds() does the clearing when it does.
        if (zone_name == "living_room" and _override
                and _override.holds(indigo, not unoccupied, log=log)):
            for k in [k for k in streaks if k.startswith("living_room:")]:
                streaks.pop(k, None)
            state["living_room_quiet_since"] = None
            living_room_quiet_since = None
            continue
        for device_id in zone["lights"]:
            key = f"{zone_name}:{device_id}"
            is_on, dev = read_light_on(device_id)

            # Anything other than a confirmed lit light in a confirmed empty
            # room breaks the run. Unreadable breaks it too — we cannot vouch
            # for a middle we could not see.
            if is_on is not True or not unoccupied:
                streaks.pop(key, None)
                continue

            since_min = _age_min(streaks.get(key), now)
            if since_min is None:
                streaks[key] = now.timestamp()
                continue

            if since_min < quiet_needed:
                continue

            log(f"{dev.name} has been on in an empty {zone_name.replace('_', ' ')} "
                f"for {int(since_min)} minutes — turning it off "
                f"({why}, threshold {quiet_needed} min)", level="INFO")
            if send_off(dev, zone_name, state, now):
                turned_off.append(dev.name)
            streaks.pop(key, None)

        if zone_name == "living_room" and unoccupied:
            marker = state.get("living_room_quiet_since")
            if _epoch(marker) is None:
                marker = now.timestamp()
            living_room_quiet_since = datetime.fromtimestamp(_epoch(marker))
            state["living_room_quiet_since"] = marker
        elif zone_name == "living_room":
            state["living_room_quiet_since"] = None

    assert_fire_off(now, state, living_room_quiet_since, quiet_needed)

    state["streaks"]  = streaks
    state["last_run"] = now.timestamp()
    state["last_run_text"] = now.strftime(TS_FMT)
    save_state(state)

    if turned_off:
        log(f"Swept {len(turned_off)} light(s) left on overnight (off sent, checked "
            f"next tick): {', '.join(turned_off)}", level="INFO")


main()
