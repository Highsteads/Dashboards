#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Appliance_Scheduler.py
# Description: Says when to run each metered appliance so it costs the least grid import,
#              using the solar forecast, the house's own load profile and the battery.
# Author:      CliveS & Claude Opus 5
# Date:        09-09-2026
# Version:     2.0
# v2.0 (09-09-2026) - EVERY ApplianceMonitor device, not just the washing machine, and each
#      one's cycle profile MEASURED FROM ITS OWN HISTORY rather than typed in here.
#      Asked for a tumble dryer and a dishwasher; neither is metered (confirmed by CliveS,
#      and by a sweep of all 35 power-reporting devices plus the whole IoT subnet - the one
#      unaccounted Shelly is a UNI with no meters at all). Rather than invent cycle figures
#      for two machines nobody can measure, which is exactly what this page refuses to do,
#      the scheduler now discovers whatever IS metered. Plug a metering Shelly into the
#      dryer, add an ApplianceMonitor device pointed at it, and it appears here with real
#      figures once it has run five cycles. No code change.
#
# The thinking lives in appliance_planner.py, which is pure and has 46 tests behind it.
# NB the engine is deliberately NOT called appliance_scheduler.py: this volume is
# case-insensitive, so that name and this one would be the SAME FILE, and installing the
# pair silently leaves one copy of the runner where the engine should be.
# This file only fetches live values, calls it, and says the answer out loud.
#
# It does NOT switch anything on. The washing machine's Shelly is monitor-only by three
# separate mechanisms and that is deliberate, and a washing machine has to be loaded by a
# person anyway - so a person is standing in front of it exactly when the advice is useful.
#
# DEADLINE: put "HH:MM" in the Indigo variable `washing_machine_deadline` to say when the
# wash must be finished by. Blank or missing means 22:00 today (tomorrow, if it is already
# past 21:00).
#
# TESTING THIS THROUGH ClaudeBridge WILL LIE TO YOU. A module is imported once per host
# lifetime, so once a long-lived plugin host has run this, it keeps the appliance_planner
# it first loaded and every later edit is invisible - with perfectly plausible output.
# Run it from an Indigo trigger or schedule (each of those gets a fresh interpreter) or
# from a plain shell, or restart the plugin. Deliberately no importlib.reload here: that
# would pay a cost on every production run to fix a problem only a dev tool has.

import json
import logging
import os
import sys
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:                                   # pragma: no cover
    ZoneInfo = None

SCRIPT_VERSION = "1.0"

# Indigo execs a companion script without setting __file__, so this cannot simply ask where
# it lives - the same guard every companion script here carries.
_SCRIPTS = os.path.dirname(os.path.abspath(__file__)) \
    if "__file__" in globals() else \
    "/Library/Application Support/Perceptive Automation/Python Scripts"
# Guard the insert: the Dashboards tick execs this in its own host every few minutes, and an
# unguarded insert grew sys.path by one entry a tick until the companion scripts learned not to.
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import appliance_planner as sched                     # noqa: E402

FORECAST_PATH = os.path.join(_SCRIPTS, "openmeteo_forecast.json")
SITE_PATH     = os.path.join(_SCRIPTS, "sigen_site_config.json")
PLAN_PATH     = os.path.join(_SCRIPTS, "appliance_plan.json")

APPLIANCE_PLUGIN  = "com.clives.indigoplugin.appliancemonitor"
INVERTER_NAME     = "Sigenergy Inverter"
PROFILE_CACHE     = os.path.join(_SCRIPTS, "appliance_profiles.json")
PROFILE_MAX_AGE_H = 24.0              # the medians barely move; the history read is not free

HISTORY_DB = None                     # resolved at run time from the Indigo install folder
HISTORY_LOOKBACK_ROWS = 30000         # PK range, never a ts filter - the ts column is unindexed

RATES_TODAY    = "elec_rates_today_json"
RATES_TOMORROW = "elec_rates_tomorrow_json"

DEFAULT_DEADLINE_HOUR = 22

_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
               "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}


def _lvl(level):
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        indigo.server.log(f"[{stamp}] {message}", level=_lvl(level))
    except NameError:
        print(f"[{stamp}] {level:<7} {message}")


# ---------------------------------------------------------------------------
# Live values. Each returns None rather than a plausible-looking default.
# ---------------------------------------------------------------------------

def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as err:
        log(f"could not read {os.path.basename(path)}: {err}", "WARNING")
        return None


def variable(name, default=""):
    try:
        return indigo.variables[name].value
    except Exception:                                  # noqa: BLE001 - absent is normal
        return default


def parse_iso(text):
    text = str(text).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def rate_spans():
    """Both shapes at once: Tracker publishes one long span, Agile publishes half hours,
    and a day routinely arrives with 46 of its 48 slots. Nothing here counts entries."""
    spans = []
    for name in (RATES_TODAY, RATES_TOMORROW):
        raw = variable(name, "")
        if not raw:
            continue
        try:
            rows = json.loads(raw)
        except ValueError:
            log(f"{name} is not valid JSON", "WARNING")
            continue
        for row in rows:
            try:
                spans.append({"start": parse_iso(row["valid_from"]),
                              "end":   parse_iso(row["valid_to"]),
                              "pence": float(row["value_inc_vat"])})
            except (KeyError, TypeError, ValueError):
                continue
    return spans


def live_battery(site):
    """Current pack state. Capacity and reserve come from the plugin's own site config, so
    a fifth battery module cannot silently leave a hardcoded 35.04 behind."""
    try:
        inv = indigo.devices[INVERTER_NAME]
        soc = float(inv.states["batterySoc"])
    except Exception as err:                           # noqa: BLE001
        log(f"could not read the battery: {err}", "WARNING")
        return None
    b = site.get("battery", {})
    r = site.get("resilience", {})
    month = datetime.now().month
    reserve = r.get("winter_pct" if month in (11, 12, 1, 2, 3) else "summer_pct", 15.0)
    return sched.Battery(soc, b.get("capacity_kwh", 35.04), float(reserve),
                         b.get("efficiency", 0.94))


def deadline_for(key, now):
    """When this appliance must be finished by. `<key>_deadline` holds "HH:MM", or nothing.

    The variable is named from the key so the washing machine keeps the one it already has,
    and a dryer added later gets tumble_dryer_deadline without anybody wiring it up.
    """
    name = f"{key}_deadline"
    raw = variable(name, "").strip()
    if raw:
        try:
            hh, mm = (int(x) for x in raw.split(":", 1))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError(raw)
            wanted = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return wanted if wanted > now else wanted + timedelta(days=1)
        except (ValueError, TypeError):
            log(f"{name} is {raw!r}, which is not a time like 16:00 - using the default "
                f"instead", "WARNING")
    wanted = now.replace(hour=DEFAULT_DEADLINE_HOUR, minute=0, second=0, microsecond=0)
    return wanted if wanted > now else wanted + timedelta(days=1)


# ---------------------------------------------------------------------------
# Discovering what is metered, and measuring what it does
# ---------------------------------------------------------------------------

def monitor_devices():
    """Every ApplianceMonitor device, enabled, as (device, key, label)."""
    found = []
    try:
        for dev in indigo.devices:
            if dev.pluginId == APPLIANCE_PLUGIN and dev.enabled:
                found.append((dev, sched.appliance_key(dev.name), sched.appliance_label(dev.name)))
    except Exception as err:                           # noqa: BLE001
        log(f"could not list the appliance monitors: {err}", "WARNING")
    return found


def history_db_path():
    global HISTORY_DB
    if HISTORY_DB is None:
        try:
            HISTORY_DB = os.path.join(indigo.server.getInstallFolderPath(),
                                      "Logs", "indigo_history.sqlite")
        except Exception:                              # noqa: BLE001
            HISTORY_DB = ""
    return HISTORY_DB


def cycles_from_history(device_id):
    """The finished cycles this monitor has recorded: (minutes, kwh, peaks).

    PK-RANGED, never filtered on ts. That column has no index, so a ts filter reads the whole
    table and holds a lock the SQL Logger's writes queue behind - the fault that wedged the
    server for three minutes on 15-Jul-2026.
    """
    import sqlite3
    path = history_db_path()
    if not path or not os.path.exists(path):
        return [], [], []
    table = f"device_history_{int(device_id)}"
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = db.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cur.fetchone():
            return [], [], []
        cur.execute(f"SELECT MAX(id) FROM {table}")
        hi = (cur.fetchone() or [None])[0]
        if hi is None:
            return [], [], []
        low = hi - HISTORY_LOOKBACK_ROWS
        out = []
        for col in ("lastcycleminutes", "lastcycleenergykwh", "lastcyclepeakwatts"):
            try:
                cur.execute(f"SELECT {col} FROM {table} WHERE id > ? AND {col} IS NOT NULL "
                            f"ORDER BY id", (low,))
                out.append([row[0] for row in cur.fetchall()])
            except sqlite3.OperationalError:
                out.append([])                         # a column this monitor never wrote
        return tuple(out)
    except sqlite3.Error as err:
        log(f"could not read the cycle history: {err}", "WARNING")
        return [], [], []
    finally:
        try:
            db.close()
        except Exception:                              # noqa: BLE001
            pass


def load_profile_cache():
    try:
        with open(PROFILE_CACHE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_profile_cache(cache):
    try:
        tmp = PROFILE_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, indent=2)
        os.replace(tmp, PROFILE_CACHE)
    except OSError as err:
        log(f"could not cache the profiles: {err}", "WARNING")


def profile_for(dev, key, label, cache, now_ts):
    """This appliance's measured profile, or None if it has not run enough to know.

    None is the honest answer for a machine that has run twice, and the page says so rather
    than quoting a median of two or a figure off the manual.
    """
    entry = cache.get(key)
    if entry and (now_ts - entry.get("at", 0)) < PROFILE_MAX_AGE_H * 3600:
        if not entry.get("profile"):
            return None
        pr = entry["profile"]
        return sched.Appliance(key, label, pr["minutes"], pr["kwh"], pr["peak_watts"],
                               measured_from=pr.get("measured_from", ""),
                               cycles_measured=pr.get("cycles", 0))
    minutes, kwh, peaks = cycles_from_history(dev.id)
    app = sched.profile_from_cycles(key, label, minutes, kwh, peaks)
    cache[key] = {"at": now_ts,
                  "profile": None if app is None else
                             {"minutes": app.duration_minutes, "kwh": app.energy_kwh,
                              "peak_watts": app.peak_watts, "cycles": app.cycles_measured,
                              "measured_from": app.measured_from}}
    return app


def cycle_in_progress(dev, app, now):
    """If it is running, say how it is getting on rather than when to start it."""
    state = dev.states.get("cycleState")
    if state not in ("running", "finishing"):
        return None
    started = dev.states.get("cycleStartedAt") or 0
    watts = dev.states.get("currentWatts") or 0.0
    label = (app.label if app else sched.appliance_label(dev.name)).capitalize()
    if not started:
        return f"{label} is running now."
    began = datetime.fromtimestamp(started, tz=now.tzinfo)
    if not app:
        return (f"{label} is on. It started at {sched._clock(began)} and is drawing "
                f"{watts:.0f} watts.")
    expected = began + timedelta(minutes=app.duration_minutes)
    left = int((expected - now).total_seconds() // 60)
    if left > 0:
        return (f"{label} is already on. It started at {sched._clock(began)} and should "
                f"finish about {sched._clock(expected)}, so about {left} minutes to go. "
                f"It is drawing {watts:.0f} watts.")
    return (f"{label} started at {sched._clock(began)} and is past its usual "
            f"{app.duration_minutes} minutes, so it should be finishing now. It is drawing "
            f"{watts:.0f} watts.")


# ---------------------------------------------------------------------------

def build_plan():
    tz = sched.site_tz()
    now = datetime.now(tz)
    monitors = monitor_devices()
    out = {"generated": now.isoformat(), "appliances": []}

    if not monitors:
        out["note"] = ("Nothing is metered yet. Put a metering plug on an appliance and add "
                       "an Appliance Monitor device pointed at it, and it will appear here.")
        return out

    forecast = read_json(FORECAST_PATH)
    site = read_json(SITE_PATH)
    solar = (forecast or {}).get("hourly") or {}
    house = ((site or {}).get("consumption") or {}).get("hourly_kwh") or {}
    battery = live_battery(site) if site else None
    rates = rate_spans()

    # One reason, said once, rather than repeated against every appliance.
    missing = None
    if not solar or not house:
        missing = ("I cannot see the solar forecast or the house's load profile, so I have no "
                   "way to work out a good time. A forecast that has not arrived is not a "
                   "forecast of no sun, so I would rather say nothing than guess.")
    elif battery is None:
        missing = "I cannot read the battery, so I cannot tell what a run would actually cost."
    elif not rates:
        missing = "I have no electricity prices to compare times with."

    cache = load_profile_cache()
    for dev, key, label in sorted(monitors, key=lambda t: t[1]):
        app = profile_for(dev, key, label, cache, now.timestamp())
        entry = {"key": key, "label": label, "device_id": dev.id}

        running = cycle_in_progress(dev, app, now)
        if running:
            entry.update(state="running", message=running)
            out["appliances"].append(entry)
            continue

        if app is None:
            entry.update(state="unmeasured", message=(
                f"{label.capitalize()} has not run enough times yet for me to know how long "
                f"it takes or what it uses. Once it has finished about five cycles I can say "
                f"when to run it."))
            out["appliances"].append(entry)
            continue

        entry["appliance"] = {"label": app.label, "minutes": app.duration_minutes,
                              "kwh": app.energy_kwh, "measured_from": app.measured_from}
        if missing:
            entry.update(state="no_plan", message=missing)
            out["appliances"].append(entry)
            continue

        deadline = deadline_for(key, now)
        try:
            best, every = sched.plan(app, now, deadline, battery, solar, house, rates)
        except sched.NoPlan as err:
            entry.update(state="no_plan", message=str(err),
                         deadline=deadline.isoformat())
            out["appliances"].append(entry)
            continue

        entry.update(
            state="planned",
            message=sched.describe(app, best, every, now, deadline),
            deadline=deadline.isoformat(),
            start=best.start.isoformat(), finish=best.finish.isoformat(),
            grid_kwh=round(best.grid_kwh, 3), cost_p=round(best.cost_p, 2),
            solar_kwh=round(best.solar_kwh, 3), battery_kwh=round(best.battery_kwh, 3),
            battery_soc_pct=battery.soc_pct,
            options=[{"start": s.start.isoformat(), "grid_kwh": round(s.grid_kwh, 3),
                      "cost_p": round(s.cost_p, 2)} for s in every],
        )
        out["appliances"].append(entry)

    save_profile_cache(cache)
    return out


def write_plan(plan_dict):
    """Atomically, so a dashboard can never read half a file."""
    tmp = PLAN_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(plan_dict, handle, indent=2)
        os.replace(tmp, PLAN_PATH)
    except OSError as err:
        log(f"could not write the plan: {err}", "WARNING")


def set_advice(key, text):
    """One variable per appliance, so a control page or a trigger can read any of them."""
    name = f"{key}_advice"
    try:
        if name in indigo.variables:
            indigo.variable.updateValue(indigo.variables[name].id, str(text))
        else:
            indigo.variable.create(name, str(text))
    except Exception as err:                           # noqa: BLE001
        log(f"could not publish the advice for {key}: {err}", "WARNING")


def push(title, body):
    try:
        p = indigo.server.getPlugin("io.thechad.indigoplugin.pushover")
        if p and p.isEnabled():
            p.executeAction("send", props={"msgTitle": title[:250], "msgBody": body[:1024],
                                           "msgPriority": "0", "msgSound": "vibrate"})
            return True
    except Exception as err:                           # noqa: BLE001
        log(f"could not send the push: {err}", "WARNING")
    return False


def main():
    # QUIET is set by the Dashboards tick: the plan barely moves between ticks, so saying it
    # out loud every few minutes would be ~100 log lines a day describing no change. Run by
    # hand it speaks normally.
    quiet = bool(globals().get("APPLIANCE_SCHEDULER_QUIET", False))
    wants_push = "--push" in sys.argv
    try:
        plan_dict = build_plan()
    except sched.NoPlan as err:
        plan_dict = {"generated": datetime.now().isoformat(), "appliances": [],
                     "note": str(err)}
        log(str(err), "WARNING")
    write_plan(plan_dict)
    for entry in plan_dict.get("appliances", []):
        set_advice(entry["key"], entry.get("message", ""))
        if not quiet:
            log(entry.get("message", ""))
        if wants_push and entry.get("state") == "planned":
            push(entry["label"].replace("the ", "").capitalize(), entry["message"])
    if not plan_dict.get("appliances") and plan_dict.get("note") and not quiet:
        log(plan_dict["note"])


# Called at module level, not under a __name__ guard: the Dashboards tick execs this file
# with a bare globals dict, so __name__ is not defined there and the guard would raise.
try:
    main()
except Exception:                                     # noqa: BLE001
    import traceback
    log("Appliance Scheduler FAILED:\n" + traceback.format_exc(), "ERROR")
