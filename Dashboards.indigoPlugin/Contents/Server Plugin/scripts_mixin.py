#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    scripts_mixin.py
# Description: The companion Python Scripts: the runner that exec()s them, their
#              schedule, and the hand-over to the Script Ticker plugin.
#              Split out of plugin.py in v3.32.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import sys as _sys
from datetime import datetime
import json
import os
import threading
import time

from dash_common import (
    FP300_WATCH_REFRESH_SECONDS,
    LAUNDRY_REFRESH_SECONDS,
    LOG_WATCH_REFRESH_SECONDS,
    NIGHT_SWEEP_REFRESH_SECONDS,
    PRESENCE_REFRESH_SECONDS,
    REFLECTOR_BW_REFRESH_SECONDS,
    log,
)


class ScriptsMixin:
    def _ticker_running(self):
        """isRunning(), not isEnabled(): a ticker that is enabled but has
        crashed runs nothing, and that is exactly when Dashboards must step
        back in. A ticker mid-restart reads as not running for a few seconds,
        which costs at most one extra run of each script."""
        try:
            p = indigo.server.getPlugin(self._TICKER_PLUGIN_ID)
            return bool(p and p.isInstalled() and p.isRunning())
        except Exception:
            return False

    def _note_ticker(self):
        """Tick task (every 30 s): who runs the companion scripts. Logs only a
        change, and says nothing on an install that has never had the ticker."""
        now_elsewhere = self._ticker_running()
        was = getattr(self, "_scripts_elsewhere", None)
        self._scripts_elsewhere = now_elsewhere
        if was is None and not now_elsewhere:
            return now_elsewhere
        if now_elsewhere and not was:
            log("[Scripts] Script Ticker is running the companion scripts, so Dashboards "
                "is leaving them to it")
        elif was and not now_elsewhere:
            log("[Scripts] Script Ticker is not running, so Dashboards is running the "
                "companion scripts again")
        return now_elsewhere

    def _run_presence_watch(self):
        """Tick the standalone Presence_Watch.py script — the single source of
        truth for the presence-timeline logic — to refresh the presence data
        the presenceData endpoint serves (Python Scripts/presence_data.json;
        NOT /public since v2.71.0). Quiet: the script only logs its success
        line when run by hand (PRESENCE_WATCH_QUIET); errors still surface."""
        self._tick_script("presence")

    def _run_log_error_watch(self):
        """Tick the standalone Log_Error_Watch.py script — the single source of
        truth for what counts as a real, new event-log error — which refreshes
        the state file the logErrors endpoint serves. Quiet: the script only
        logs its "nothing new" line when run by hand; a genuine find still logs
        at WARNING and sends its own Pushover + email.

        Driving it from here rather than an Indigo schedule is deliberate — the
        IOM can create a schedule but cannot set its ACTION STEP, so a scripted
        schedule would sit there running nothing. The cost is that the watch
        stops if this plugin is disabled, unless Script Ticker is running it
        instead (v3.31.0), or a UI schedule runs it alongside (the script's
        flock + state make a double-run safe).
        """
        self._tick_script("logwatch")
        self._check_log_watch_alive()

    def _run_drive_lights_sun(self):
        """Tick Drive_Lights_Sun.py — the Garage and Front Door lights held on
        at 100% from sunset to sunrise.

        Driven from here for the usual reason: indigo.schedule.create() takes
        no ACTION STEP, and a schedule's timing fields are read-only through
        the API, so neither a new schedule nor retiming the old one is possible
        from code.

        Ticking beats firing once at sunset anyway, because it SELF-HEALS. A
        missed Zigbee command, a bulb that dropped off the mesh and rejoined, a
        power cut at 3am — the next tick puts it right, where a single
        sunset-edge command leaves the light wrong until the following night.
        The script only commands on a mismatch, so a correct night is silent.
        """
        self._tick_script("drivelights")

    def _run_night_lights_sweep(self):
        """Tick Night_Lights_Sweep.py — the overnight backstop that turns off a
        light burning in an empty room, and asserts the living room fire off.

        Driven from here rather than an Indigo schedule for the usual reason:
        the IOM can create a schedule but cannot set its ACTION STEP, so a
        scripted schedule would sit there running nothing.

        EVERY 2 MINUTES, and that cadence is load-bearing. The script only acts
        after an UNBROKEN run of observations, and it discards every streak if
        the previous run was more than MAX_GAP_MINUTES (10) ago — because
        nothing watched that gap. Slow this down past 10 minutes and the sweep
        never acts at all. It fails safe, but silently, so do not tune this
        without reading that guard.

        Cheap: outside its night window the script reads two variables and
        returns, so a daytime tick is a few microseconds.
        """
        self._tick_script("nightsweep")

    def _run_reflector_bandwidth_watch(self):
        """Meter the Indigo reflector's SSH tunnel (v3.0.0).

        Indigo Domotics wrote twice about this house's reflector usage and
        deactivated the reflector the second time, and nothing here could say
        how much had gone through it or when — IWS logs no successful request,
        and the tunnel is invisible to lsof and netstat. This samples the one
        process that IS the tunnel and keeps an hourly record.

        Every 5 minutes: the script's own work is two short subprocess calls,
        and the deltas it accumulates are what make an hour meaningful.
        """
        self._tick_script("reflectorbw")

    def _run_fp300_config_watch(self):
        """Tick the standalone FP300_Config_Watch.py script — the watch on the
        Aqara FP300 presence sensors' DEVICE-SIDE configuration.

        Those settings live on the sensor, not in Indigo, so a battery pull or
        button reset silently returns them to the firmware defaults and nothing
        notices. That is exactly what happened on 06-07-2026: adaptive
        sensitivity went back ON for four weeks, and presence fragmented all
        night because the radar re-learns a motionless sleeper as background.

        The script only writes while a sensor reports presence — an FP300 is a
        sleepy battery device and z2m does not reliably queue a write for one —
        so most ticks do nothing at all. Quiet: it only logs its "all sensors
        hold the intended configuration" line when run by hand; genuine drift
        still logs at WARNING.

        Driven from here for the same reason as the log watch: the IOM can
        create a schedule but cannot set its ACTION STEP, so a scripted
        schedule would sit there running nothing.
        """
        self._tick_script("fp300watch")

    def _run_appliance_scheduler(self):
        """Refresh the laundry plan. Appliance_Scheduler.py writes it to
        Python Scripts/appliance_plan.json; handleLaundryPlan serves it.

        Deliberately NOT copied into public/dashboards/. A laundry plan is behavioural —
        it says when this household washes and what the battery is holding — and
        presence.json was moved off anonymous /public in v1.1 for precisely that reason.
        The usual argument for a static file is that a page polling /message/ can wedge
        the IWS event loop for five minutes across a plugin restart, and the v2.70.0
        liveness gate already answers that: every page checks the stamp and backs off.
        """
        if not self._sigen_available():
            # Nothing to plan from without SigenEnergyManager's forecast, site
            # config and rates (v3.13.0); the script would only say so in its
            # own log every fifteen minutes.
            return
        self._tick_script("laundry")

    def _read_laundry_plan(self):
        """The plan as the script last wrote it, or None. Absent is not an error — the
        script says why in its own log, and a page that shows nothing is honest."""
        try:
            with open(os.path.join(self._scripts_dir(), "appliance_plan.json"),
                      encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ── Companion scripts (v2.95.2: ONE runner for all five) ───────────────
    # Each is exec()ed from this host with `indigo` injected, so module-level
    # code re-runs every tick and anything it changes in the host PERSISTS:
    # sys.path grew by one entry a tick until the scripts learned to guard
    # their inserts, and it is snapshotted and restored here regardless.
    # TICK_MEMORY is a per-script dict that survives between ticks, so a
    # script can warn ONCE about a missing device rather than every two
    # minutes. Failures: the first is logged WITH its traceback (a syntax
    # error in an edited script used to be one bare line, 720 times a day,
    # with no line number), repeats stay silent until the text changes, and
    # the first success afterwards logs a recovery.
    COMPANION_SCRIPTS = {
        "presence":    ("Presence_Watch.py",     "[Presence]",   {"PRESENCE_WATCH_QUIET": True},
                        "the Presence tile needs Presence_Watch.py from the repo's scripts/ "
                        "folder (copied into Python Scripts/ and edited for your rooms)"),
        "logwatch":    ("Log_Error_Watch.py",    "[LogWatch]",   {"LOG_ERROR_WATCH_QUIET": True},
                        "the hourly log-error watch needs Log_Error_Watch.py from the repo's "
                        "scripts/ folder (copied into Python Scripts/)"),
        "drivelights": ("Drive_Lights_Sun.py",   "[DriveLights]", {},
                        "the sunset-to-sunrise drive lights need Drive_Lights_Sun.py in "
                        "Python Scripts/ (repo scripts/ folder, edited for your lights)"),
        "nightsweep":  ("Night_Lights_Sweep.py", "[NightSweep]", {},
                        "the overnight lights sweep needs Night_Lights_Sweep.py in "
                        "Python Scripts/ (repo scripts/ folder, edited for your rooms)"),
        "laundry":     ("Appliance_Scheduler.py", "[Laundry]",   {"APPLIANCE_SCHEDULER_QUIET": True},
                        "the laundry page needs Appliance_Scheduler.py and appliance_planner.py "
                        "in Python Scripts/ (repo scripts/ folder)"),
        "fp300watch":  ("FP300_Config_Watch.py", "[FP300Watch]", {"FP300_CONFIG_WATCH_QUIET": True},
                        "the hourly presence-sensor config watch needs FP300_Config_Watch.py "
                        "from the repo's scripts/ folder (copied into Python Scripts/)"),
        "reflectorbw": ("Reflector_Bandwidth_Watch.py", "[ReflectorBW]", {},
                        "the reflector bandwidth meter needs Reflector_Bandwidth_Watch.py "
                        "from the repo's scripts/ folder (copied into Python Scripts/)"),
    }

    def _scripts_dir(self):
        # Python Scripts lives at the Perceptive Automation ROOT (shared across
        # Indigo versions), NOT under the versioned install folder that
        # getInstallFolderPath() returns — so go up one level.
        return os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                            "Python Scripts")

    def _tick_script(self, key):
        """Run one companion script once. Returns True on a clean run."""
        import traceback as _tb
        name, tag, extra, hint = self.COMPANION_SCRIPTS[key]
        path = os.path.join(self._scripts_dir(), name)
        memory = self.__dict__.setdefault("_tick_memory", {}).setdefault(key, {})
        errors = self.__dict__.setdefault("_script_errors", {})
        try:
            if not os.path.isfile(path):
                return False                   # reported once, in one line, after the seed pass
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            # ONE script at a time, whichever thread asks (v3.25.0). The loop
            # runs them in turn, but a laundry deadline replans from a pool
            # worker, and two runs at once shared one TICK_MEMORY dict and
            # restored each other's saved sys.path.
            with self.__dict__.setdefault("_script_tick_lock", threading.Lock()):
                saved_path = list(_sys.path)
                g = {"indigo": indigo, "TICK_MEMORY": memory}
                g.update(extra)
                try:
                    exec(compile(src, path, "exec"), g)
                finally:
                    _sys.path[:] = saved_path
        except SystemExit as exc:
            # sys.exit() / exit() in a script raises SystemExit, a
            # BaseException: it went straight past the handler below, past
            # step() and out of runConcurrentThread, which ended every camera
            # poll and script tick until the next restart. Code None or 0 is
            # a script finishing early on purpose; anything else is a failure,
            # reported the same way as an exception.
            if exc.code in (None, 0):
                if errors.pop(key, None):
                    self.logger.info(f"{tag} recovered")
                return True
            text = f"SystemExit: {exc.code}"
            if errors.get(key) != text:
                errors[key] = text
                self.logger.warning(f"{tag} tick failed: the script called sys.exit({exc.code!r})")
            return False
        except Exception as exc:               # noqa: BLE001 — isolate, report once
            text = f"{type(exc).__name__}: {exc}"
            if errors.get(key) != text:
                errors[key] = text
                self.logger.warning(f"{tag} tick failed: {text}\n{_tb.format_exc()}")
            return False
        if errors.pop(key, None):
            self.logger.info(f"{tag} recovered")
        return True

    def _check_log_watch_alive(self):
        """The watch on the event log has no watchdog of its own — if it dies
        deterministically, every downstream consumer (Pushover, the Alerts
        page, the triage feed) just sees 'nothing new'. This host ticks it, so
        this host checks its pulse: the state file it rewrites on every good
        run carries last_run, and a stamp older than two intervals means the
        estate's only log watch is not watching. One ERROR a day, not one an
        hour, and only when the script is actually installed."""
        state_path = os.path.join(self._scripts_dir(), "log_error_watch_state.json")
        if not os.path.isfile(os.path.join(self._scripts_dir(), "Log_Error_Watch.py")):
            return
        stale_after = 2 * LOG_WATCH_REFRESH_SECONDS + 600
        try:
            with open(state_path, encoding="utf-8") as fh:
                last = (json.load(fh) or {}).get("last_run") or ""
            age = time.time() - time.mktime(datetime.strptime(last, "%Y-%m-%d %H:%M:%S").timetuple())
        except FileNotFoundError:
            return                            # first run has not happened yet
        except Exception:
            age = float("inf")
        if age <= stale_after:
            return
        last_shout = self.__dict__.get("_logwatch_dead_logged_at", 0.0)
        if time.time() - last_shout < 86400:
            return
        self._logwatch_dead_logged_at = time.time()
        shown = "never" if age == float("inf") else f"{age / 3600:.1f} h ago"
        self.logger.error(
            f"[LogWatch] Log_Error_Watch.py has not completed a run since {shown} — the "
            f"event-log watch is NOT watching. Look for its own 'Log Error Watch FAILED' "
            f"lines above; nothing downstream (Pushover, the Alerts page, the triage "
            f"feed) will notice a new error until it runs again.")

    def _tick_companions(self, step, last, t0):
        """Run whichever companion scripts are due (the loop's own schedule).
        Only called while Script Ticker is not running them (v3.31.0)."""
        if t0 - last["presence"] > PRESENCE_REFRESH_SECONDS:
            step("presence watch", self._run_presence_watch)
            last["presence"] = t0
        if t0 - last["logwatch"] > LOG_WATCH_REFRESH_SECONDS:
            step("log watch", self._run_log_error_watch)           # hourly event-log error watch
            last["logwatch"] = t0
        if t0 - last["fp300"] > FP300_WATCH_REFRESH_SECONDS:
            step("FP300 watch", self._run_fp300_config_watch)     # hourly config-drift watch
            last["fp300"] = t0
        if t0 - last["laundry"] > LAUNDRY_REFRESH_SECONDS:
            step("laundry plan", self._run_appliance_scheduler)
            last["laundry"] = t0
        if t0 - last["reflectorbw"] > REFLECTOR_BW_REFRESH_SECONDS:
            step("reflector meter", self._run_reflector_bandwidth_watch)
            last["reflectorbw"] = t0
        if t0 - last["sweep"] > NIGHT_SWEEP_REFRESH_SECONDS:
            step("night sweep", self._run_night_lights_sweep)     # 2-min overnight backstop
            step("drive lights", self._run_drive_lights_sun)      # sunset->sunrise drive lights
            last["sweep"] = t0
