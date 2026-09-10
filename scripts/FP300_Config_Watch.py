#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    FP300_Config_Watch.py
# Description: Hourly watch on the Aqara FP300 presence sensors' device-side
#              configuration. These settings live on the sensor, not in Indigo,
#              and a battery pull or button reset silently returns them to the
#              firmware defaults — which is exactly what happened on 06-07-2026,
#              when ai_sensitivity_adaptive went back ON on both Bedroom 1
#              sensors and stayed wrong for four weeks. Adaptive sensitivity
#              re-learns a motionless sleeper as background, so presence
#              fragments through the night.
#              The watch compares the live states against the intended values,
#              warns when they drift, and re-asserts them over MQTT. An FP300 is
#              a sleepy battery device: z2m does not reliably queue a write for
#              one, so the re-assert only fires while the sensor reports
#              presence — i.e. the next time somebody is in the room. It also
#              watches powerOutageCount, the early sign a sensor has been reset.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026 + UK Time Now
# Version:     1.2
#
# v1.2 (02-09-2026, Dashboards deep review): (1) a sensor that is disabled in
#   Indigo, or has not talked for two hours, is not "awake" whatever its frozen
#   presence flag says — the watch was republishing to it every 30 minutes for
#   ever and could never escalate. (2) The 36-hour escalation is judged BEFORE
#   the awake/asleep branch, and its message says what the evidence says: "N
#   re-asserts sent, still drifted" is a topic or token problem, not a sleep
#   problem. (3) MQTT: a real connect timeout (the old value was being passed as
#   paho's KEEPALIVE), a guarded port, publish failures caught per sensor,
#   shorter waits, no empty-username login, and paho imported normally before
#   falling back to Zigbee2MQTTBridge's bundle — appended to sys.path, never
#   put in front of everything the Dashboards host imports. (4) An empty-string
#   state does not satisfy an intended False. (5) Literal defaults for the
#   state and lock paths, derived from Indigo.

import os
import sys
import json
import fcntl
import logging
import traceback
from datetime import datetime, timedelta

_PA_ROOT = "/Library/Application Support/Perceptive Automation"
if _PA_ROOT not in sys.path:      # exec()ed hourly from the Dashboards host — never grow its path
    sys.path.insert(0, _PA_ROOT)
try:
    from IndigoSecrets import MQTT_BROKER
except ImportError:
    # No default. The old fallback hardcoded this house's broker address, which
    # both leaked the real LAN into a public repo and silently pointed anyone
    # else's install at an address that is not theirs. Absent means absent —
    # _mqtt_publish says so and skips.
    MQTT_BROKER = ""
try:
    from IndigoSecrets import MQTT_PORT
except ImportError:
    MQTT_PORT = 1883
try:
    from IndigoSecrets import MQTT_USERNAME
except ImportError:
    MQTT_USERNAME = ""
try:
    from IndigoSecrets import MQTT_PASSWORD
except ImportError:
    MQTT_PASSWORD = ""

# ======================================
# CONFIG
# ======================================
# The sensors to watch, by Indigo device id. The z2m friendly_name (the MQTT
# topic) is read from the device's plugin props at run time rather than pinned
# here — on 01-08-2026 the Indigo names were found bound to the OPPOSITE z2m
# devices (since corrected), so a hardcoded topic would have hit the wrong one.
SENSOR_IDS = [
    1881897017,   # Bedroom 1 Wall Presence Sensor      (ieee ...69492d)
    623198824,    # Bedroom 1 Headboard Presence Sensor (ieee ...6944ec)
]

# Intended device-side configuration.
#   indigo_state : the state name z2mbridge surfaces (camelCase)
#   z2m_key      : the snake_case property name z2m accepts on .../set
#   want         : the value the Indigo state should read
#   z2m_value    : the token to publish. A `binary` expose wants its own
#                  value_on/value_off token — ai_sensitivity_adaptive uses the
#                  STRINGS "ON"/"OFF", not a Python bool.
DESIRED = [
    # Adaptive sensitivity learns a still body as background. Off, always.
    {"indigo_state": "aiSensitivityAdaptive",   "z2m_key": "ai_sensitivity_adaptive",
     "want": False,      "z2m_value": "OFF"},
    # Seconds before the sensor reports absence. Range 1-300. A sleeping adult's
    # only radar signature is chest movement, so the 10s default turns any brief
    # loss of lock straight into "room empty".
    {"indigo_state": "absenceDelayTimer",       "z2m_key": "absence_delay_timer",
     "want": 120,        "z2m_value": 120},
    {"indigo_state": "motionSensitivity",       "z2m_key": "motion_sensitivity",
     "want": "high",     "z2m_value": "high"},
    {"indigo_state": "presenceDetectionOptions", "z2m_key": "presence_detection_options",
     "want": "both",     "z2m_value": "both"},
    # All 24 range gates enabled.
    {"indigo_state": "detectionRange",          "z2m_key": "detection_range",
     "want": 16777215,   "z2m_value": 16777215},
]

# Do not republish to the same sensor more often than this. A sleepy device can
# take a while to apply a set, and hammering it every tick would drain the cell.
REPUBLISH_COOLDOWN_MINUTES = 30

# How long a sensor may sit drifted-but-asleep before the quiet INFO becomes a
# WARNING. The bedroom is occupied ~10h a night, so anything beyond this means
# the writes are not landing and it needs looking at by hand.
STALE_DRIFT_HOURS = 36

MQTT_TOPIC_PREFIX = "zigbee2mqtt"
MQTT_CONNECT_TIMEOUT = 20
MQTT_SETTLE_SECONDS = 1.5   # the broker ack is local; this only lets loop_start flush

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__)) \
    if "__file__" in globals() else \
    "/Library/Application Support/Perceptive Automation/Python Scripts"
STATE_PATH = os.path.join(_SCRIPTS_DIR, "fp300_config_watch_state.json")
LOCK_PATH  = "/tmp/fp300_config_watch.lock"

ISO = "%Y-%m-%d %H:%M:%S"


# ======================================
# HELPERS
# ======================================
_LOG_LEVELS = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=_lvl(level))


def _scripts_dir():
    """Python Scripts sits at the Perceptive Automation ROOT, one level above
    the versioned folder getInstallFolderPath() returns."""
    return os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()), "Python Scripts")


def _comm_age_hours(dev, now):
    """Hours since the sensor last talked to its plugin, or None if unknown."""
    lsc = getattr(dev, "lastSuccessfulComm", None)
    if not isinstance(lsc, datetime):
        return None
    try:
        return (now - lsc).total_seconds() / 3600.0
    except Exception:
        return None


def _cfg(name, default):
    """Read a module-level tunable defensively.

    A script's main() can execute with module-level names absent from its
    globals entirely (weekly_home_digest v1.2, 03-07-2026) even though the top
    level binds them unconditionally. Functions resolve fine, constants may not.
    """
    return globals().get(name, default)


def _fmt(dt):
    return dt.strftime(ISO) if isinstance(dt, datetime) else None


def _parse(text):
    try:
        return datetime.strptime(str(text), ISO)
    except (ValueError, TypeError):
        return None


# ======================================
# PURE LOGIC (no Indigo, no MQTT, no disk — unit-testable)
# ======================================
def matches(actual, want):
    """Compare a live state against an intended value, tolerating type drift.

    Indigo hands back bools as True/False but a saved config dialog can turn a
    numeric-looking value into a string, so never compare straight across.
    """
    if isinstance(want, bool):
        if isinstance(actual, str):
            # "" is a non-reading, not a False (v1.2) — it satisfied want=False
            return actual.strip().lower() in (("true", "on", "1") if want
                                              else ("false", "off", "0"))
        return bool(actual) == want
    if isinstance(want, int):
        try:
            return int(actual) == want
        except (TypeError, ValueError):
            return False
    return str(actual).strip().lower() == str(want).strip().lower()


_MISSING = object()


def find_drift(states, desired):
    """Return the list of desired entries whose live state is wrong.

    An ABSENT state — or one present but None — counts as drift in its own
    right. Neither can be folded into the value comparison: both read back as
    None, and None against an intended False compares EQUAL, so a sensor that
    had never reported would have looked perfectly healthy. None is not a
    legitimate reading for any of these five settings.
    """
    out = []
    for item in desired:
        actual = states.get(item["indigo_state"], _MISSING)
        if actual is _MISSING or actual is None:
            out.append(dict(item, actual="<state absent>" if actual is _MISSING else None))
        elif not matches(actual, item["want"]):
            out.append(dict(item, actual=actual))
    return out


def build_payload(drift):
    """The z2m /set body that corrects everything currently wrong."""
    return {item["z2m_key"]: item["z2m_value"] for item in drift}


def describe(drift):
    return ", ".join(f"{d['indigo_state']}={d['actual']!r} (want {d['want']!r})"
                     for d in drift)


def should_publish(now, last_publish, cooldown_minutes):
    """True when the cooldown since the last publish to this sensor has expired."""
    if last_publish is None:
        return True
    return (now - last_publish) >= timedelta(minutes=cooldown_minutes)


# ======================================
# INDIGO / MQTT
# ======================================
def friendly_name(dev):
    """The z2m friendly_name, i.e. the MQTT topic for this device.

    Read from globalProps first: a foreign plugin's pluginProps can come back
    EMPTY from another host's context (197 of 221 devices, measured 21-07-2026),
    and an empty read is indistinguishable from "not set".
    """
    props = {}
    try:
        props = dev.globalProps.get(dev.pluginId) or {}
    except Exception:
        props = {}
    if not props:
        props = dev.pluginProps or {}
    if not props:
        try:
            props = dev.ownerProps or {}
        except Exception:
            props = {}
    return props.get("friendly_name") or props.get("friendlyName") or ""


def publish(sets, quiet=False):
    """Publish {friendly_name: payload} to z2m. Returns the names accepted.

    Acceptance by the BROKER is all we can see here. Whether the sensor applied
    it is confirmed by the next run seeing the state flip, never by this return.
    """
    if not sets:
        return []
    import time
    try:
        import paho.mqtt.client as mqtt          # Python3-includes / a requirement
    except ImportError:
        # Fall back to Zigbee2MQTTBridge's bundled copy — APPENDED, so it can
        # never shadow anything the Dashboards host (which execs this) imports.
        base = indigo.server.getInstallFolderPath()
        pkgs = os.path.join(base, "Plugins", "Zigbee2MQTTBridge.indigoPlugin",
                            "Contents", "Packages")
        if pkgs not in sys.path:
            sys.path.append(pkgs)
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log("FP300 Config Watch: paho-mqtt is not installed (and Zigbee2MQTTBridge's "
                "bundle does not carry it) — cannot re-assert over MQTT", level="ERROR")
            return []

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt.Client()
    user = str(_cfg("MQTT_USERNAME", "") or "")
    if user:                                     # an explicit empty username is not "no username"
        client.username_pw_set(user, _cfg("MQTT_PASSWORD", ""))
    broker = str(_cfg("MQTT_BROKER", "") or "").strip()
    if not broker:
        log("MQTT_BROKER is not set — add it to IndigoSecrets.py "
            "(e.g. MQTT_BROKER = \"192.168.1.10\"). Skipping the re-assert.",
            level="ERROR")
        return []
    try:
        port = int(_cfg("MQTT_PORT", 1883) or 1883)
    except (TypeError, ValueError):
        port = 1883
    try:
        # The socket connect timeout is a property; the third positional
        # argument of connect() is the KEEPALIVE, which is where the old
        # value went — so the real connect wait was paho's 5 s default.
        client.connect_timeout = float(_cfg("MQTT_CONNECT_TIMEOUT", 20))
    except Exception:
        pass
    client.connect(broker, port, keepalive=60)
    client.loop_start()
    done = []
    try:
        prefix = _cfg("MQTT_TOPIC_PREFIX", "zigbee2mqtt")
        for name, payload in sets.items():
            topic = f"{prefix}/{name}/set"
            try:
                result = client.publish(topic, json.dumps(payload), qos=1)
                result.wait_for_publish(3)          # the broker is local; 3 s is plenty
                accepted = result.is_published()
            except (RuntimeError, ValueError) as exc:  # paho raises on a dropped socket / full queue
                accepted = False
                log(f"FP300 Config Watch: publish to {name} failed: {exc}", level="WARNING")
            if accepted:
                done.append(name)
                if not quiet:
                    log(f"FP300 Config Watch: re-asserted {json.dumps(payload)} "
                        f"-> {topic}")
            else:
                log(f"FP300 Config Watch: broker did not accept the write for "
                    f"{name}", level="WARNING")
        time.sleep(float(_cfg("MQTT_SETTLE_SECONDS", 1.5)))
    finally:
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass
    return done


# ======================================
# STATE
# ======================================
def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("sensors"), dict):
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"FP300 Config Watch: state file unreadable ({exc}) — starting fresh",
            level="WARNING")
    return {"version": 1, "sensors": {}}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ======================================
# MAIN
# ======================================
def main(dry_run=False, quiet=False):
    now = datetime.now()
    desired  = _cfg("DESIRED", [])
    cooldown = _cfg("REPUBLISH_COOLDOWN_MINUTES", 30)
    stale_h  = _cfg("STALE_DRIFT_HOURS", 36)
    state    = load_state(_cfg("STATE_PATH", os.path.join(_scripts_dir(), "fp300_config_watch_state.json")))
    sensors  = state.get("sensors", {})

    pending, drifted, healthy = {}, [], []

    for dev_id in _cfg("SENSOR_IDS", []):
        try:
            dev = indigo.devices[dev_id]
        except Exception:
            log(f"FP300 Config Watch: device {dev_id} not found — has it been "
                f"deleted or renumbered?", level="WARNING")
            continue
        if not getattr(dev, "enabled", True):
            # Disabled in Indigo: its states are frozen and z2m may not even be
            # tracking it. Skip without touching its record (v1.2).
            if not quiet:
                log(f"FP300 Config Watch: {dev.name} is disabled in Indigo — skipping")
            continue

        key    = str(dev_id)
        record = sensors.get(key, {})
        states = dict(dev.states)
        drift  = find_drift(states, desired)

        # A rise in powerOutageCount is the early warning that the sensor was
        # reset — which is what silently undid the 24-Jun-2026 settings.
        outages = states.get("powerOutageCount")
        previous_outages = record.get("power_outage_count")
        if previous_outages is not None and outages is not None:
            try:
                if int(outages) > int(previous_outages):
                    log(f"FP300 Config Watch: {dev.name} powerOutageCount rose "
                        f"{previous_outages} -> {outages} — the sensor has been "
                        f"reset, its settings are likely back to defaults",
                        level="WARNING")
            except (TypeError, ValueError):
                pass
        record["power_outage_count"] = outages

        if not drift:
            healthy.append(dev.name)
            record.pop("drift_since", None)
            record.pop("publish_count", None)
            sensors[key] = record
            continue

        drifted.append(f"{dev.name}: {describe(drift)}")
        record["drift_since"] = record.get("drift_since") or _fmt(now)

        # Escalation is judged ONCE, before the awake/asleep branch (v1.2): a
        # sensor that was awake every time, took the write every time and is
        # STILL drifted is the case that most needs a human, and it never
        # reached the old warning because that lived on the asleep path only.
        drift_since = _parse(record.get("drift_since"))
        try:
            publishes = int(record.get("publish_count", 0) or 0)
        except (TypeError, ValueError):
            publishes = 0
        if drift_since and (now - drift_since) > timedelta(hours=stale_h):
            if publishes:
                log(f"FP300 Config Watch: {dev.name} is still drifted after {publishes} "
                    f"re-assert(s) since {record['drift_since']} — the broker accepts the "
                    f"writes but the sensor is not applying them: check its z2m "
                    f"friendly_name and the z2m log", level="WARNING")
            else:
                log(f"FP300 Config Watch: {dev.name} has been drifted since "
                    f"{record['drift_since']} and has never been awake when checked — "
                    f"no re-assert has been sent yet", level="WARNING")

        # An FP300 is a sleepy battery device. z2m does not reliably queue a
        # write for one, and an asleep sensor silently no-ops the set — so only
        # write while it reports presence, i.e. somebody is in the room. And a
        # presence flag on a sensor that has not talked for two hours is a
        # FROZEN flag, not a person (v1.2).
        awake = bool(states.get("presence")) or bool(states.get("onOffState"))
        comm_age = _comm_age_hours(dev, now)
        stale = comm_age is not None and comm_age > 2.0
        name  = friendly_name(dev)
        if not name:
            log(f"FP300 Config Watch: {dev.name} has no z2m friendly_name in its "
                f"plugin props — cannot address it over MQTT", level="WARNING")
        elif stale:
            if not quiet:
                log(f"FP300 Config Watch: {dev.name} last talked {comm_age:.1f} h ago — "
                    f"treating it as asleep whatever its presence flag says")
        elif not awake:
            if not quiet:
                log(f"FP300 Config Watch: {dev.name} is asleep — will re-assert "
                    f"when the room is next occupied")
        elif not should_publish(now, _parse(record.get("last_publish")), cooldown):
            if not quiet:
                log(f"FP300 Config Watch: {dev.name} written to recently — "
                    f"waiting for it to apply")
        else:
            pending[name] = build_payload(drift)
            record["_publish_key"] = name

        sensors[key] = record

    if drifted:
        log(f"FP300 Config Watch: configuration drift on {len(drifted)} sensor(s) "
            f"— {' | '.join(drifted)}", level="WARNING")

    if pending and not dry_run:
        published = publish(pending, quiet=quiet)
        for key, record in sensors.items():
            if record.get("_publish_key") in published:
                record["last_publish"] = _fmt(now)
                try:
                    record["publish_count"] = int(record.get("publish_count", 0) or 0) + 1
                except (TypeError, ValueError):
                    record["publish_count"] = 1
            record.pop("_publish_key", None)
    else:
        for record in sensors.values():
            record.pop("_publish_key", None)
        if pending and dry_run:
            log(f"FP300 Config Watch DRY RUN — would publish: "
                f"{json.dumps(pending)}")

    state["version"]  = 1
    state["sensors"]  = sensors
    state["last_run"] = _fmt(now)
    if not dry_run:
        save_state(_cfg("STATE_PATH", os.path.join(_scripts_dir(), "fp300_config_watch_state.json")), state)

    if not drifted and not quiet:
        log(f"FP300 Config Watch: all {len(healthy)} sensor(s) hold the intended "
            f"configuration")


def _run():
    """Take an exclusive lock so two runs can never interleave a state write."""
    try:
        handle = open(_cfg("LOCK_PATH", "/tmp/fp300_config_watch.lock"), "w", encoding="utf-8")
    except Exception:
        handle = None
    if handle is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            log("FP300 Config Watch: another run is in progress — skipping")
            handle.close()
            return
    try:
        main(quiet=bool(globals().get("FP300_CONFIG_WATCH_QUIET")))
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()


# Guard allows a test harness to exec this file and call main() directly.
# Uses builtins because Indigo runs each script with its own injected
# namespace, so globals() is not shared across exec() boundaries.
import builtins as _builtins
if not getattr(_builtins, "_fp300_config_watch_core_only", False):
    try:
        _run()
    except Exception:
        log("FP300 Config Watch FAILED:\n" + traceback.format_exc(), level="ERROR")
