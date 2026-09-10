#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Reflector_Bandwidth_Watch.py
# Description: Measure how much data the Indigo reflector is actually carrying,
#              and say so before somebody else has to.
#
#              Indigo Domotics wrote twice about this house's reflector usage
#              (02 and 03-Sep-2026) and deactivated the reflector the second
#              time. Nothing on this server could answer the question "how much,
#              and since when" — IWS logs no successful request, and the tunnel
#              is invisible to lsof and netstat. It is not invisible to nettop.
#
#              The reflector is an SSH reverse tunnel:
#                  ssh -N -F <PrismReflector/ssh_config...> -R1234:127.0.0.1:8176 prism@<host>
#              so every byte in and out of that one process IS the reflector,
#              and its cumulative counters are all this needs.
#
#              Logs an hourly line, WARNs when an hour exceeds the budget, and
#              keeps a per-hour history so a spike can be dated afterwards
#              rather than guessed at.
# Author:      CliveS & Claude Opus 5
# Date:        03-09-2026
# Version:     1.0

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
# Indigo execs a script without setting __file__, so this cannot simply ask
# where it lives — the same guard every companion script here carries.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__)) \
    if "__file__" in globals() else \
    "/Library/Application Support/Perceptive Automation/Python Scripts"
STATE_PATH   = os.path.join(_SCRIPTS_DIR, "reflector_bandwidth_state.json")
WARN_MB_HOUR = 20.0     # an hour above this gets a WARNING naming the figure
                        # MB here is DECIMAL (1e6), which is how bandwidth is
                        # billed and what Indigo Domotics will be counting.
KEEP_HOURS   = 168      # a week of hourly buckets
NETTOP_TIMEOUT = 8

_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
               "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}


def _lvl(level):
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}",
                      level=_lvl(level))


def _read_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            s = json.load(fh)
        return s if isinstance(s, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write_state(state):
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        log(f"[ReflectorBW] could not write state: {exc}", level="WARNING")


def find_tunnel():
    """(pid, started_epoch) of the reflector's ssh tunnel, or (None, None).

    Matched on the PrismReflector config path rather than on 'ssh', so an
    unrelated ssh session of CliveS's can never be mistaken for the tunnel.
    """
    try:
        out = subprocess.run(["/bin/ps", "-Ao", "pid=,lstart=,args="],
                             capture_output=True, text=True, timeout=NETTOP_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"[ReflectorBW] could not list processes: {exc}", level="WARNING")
        return None, None
    for line in out.splitlines():
        if "PrismReflector" not in line or "ssh" not in line:
            continue
        m = re.match(r"\s*(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s", line)
        if not m:
            continue
        try:
            started = datetime.strptime(m.group(2), "%a %b %d %H:%M:%S %Y").timestamp()
        except ValueError:
            started = None
        return int(m.group(1)), started
    return None, None


def read_counters(pid):
    """(bytes_in, bytes_out) for that process's tunnel socket, or (None, None).

    nettop's counters are cumulative for the life of the PROCESS, so a tunnel
    restart resets them — which is why the caller keys its baseline on the pid.
    """
    try:
        out = subprocess.run(["/usr/bin/nettop", "-m", "tcp", "-x", "-L", "1", "-p", str(pid)],
                             capture_output=True, text=True, timeout=NETTOP_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"[ReflectorBW] nettop failed: {exc}", level="WARNING")
        return None, None
    for line in out.splitlines():
        parts = line.split(",")
        # The per-socket row, not the per-process summary: it names both ends.
        if len(parts) > 6 and "<->" in parts[1] and parts[4].strip().isdigit():
            return int(parts[4]), int(parts[5])
    # Fall back to the process row when the socket row is not present.
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) > 6 and parts[1].strip().startswith("ssh") and parts[4].strip().isdigit():
            return int(parts[4]), int(parts[5])
    return None, None


def main():
    state = _read_state()
    now   = time.time()
    pid, started = find_tunnel()

    if pid is None:
        # Not an error: Indigo Domotics deactivated the reflector on 03-Sep-2026,
        # and a house that never enables it has no tunnel either.
        if state.get("pid") is not None:
            log("[ReflectorBW] the reflector tunnel is no longer running")
        state.update({"pid": None, "last_run": now})
        _write_state(state)
        return

    b_in, b_out = read_counters(pid)
    if b_in is None:
        state["last_run"] = now
        _write_state(state)
        return

    prev_pid = state.get("pid")
    prev_in  = state.get("bytes_in")
    prev_out = state.get("bytes_out")
    prev_at  = state.get("sampled_at")

    # A new pid means a new tunnel and counters that started again from zero;
    # the same pid with a SMALLER counter means the same thing (nettop wrapping
    # or a re-attach), and reading either as a delta would invent a huge spike.
    fresh = (pid != prev_pid or prev_in is None or prev_at is None
             or b_in < prev_in or b_out < prev_out)

    hours = state.setdefault("hours", {})
    if not fresh:
        d_in  = b_in - prev_in
        d_out = b_out - prev_out
        bucket = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H")
        h = hours.setdefault(bucket, {"in": 0, "out": 0})
        h["in"]  += d_in
        h["out"] += d_out
        # Report the hour just finished, once, when the clock moves on.
        last_bucket = state.get("last_bucket")
        if last_bucket and last_bucket != bucket and last_bucket in hours:
            done = hours[last_bucket]
            mb_out = done["out"] / 1e6
            mb_in  = done["in"] / 1e6
            msg = (f"[ReflectorBW] {last_bucket}:00 — {mb_out:.1f} MB out, "
                   f"{mb_in:.1f} MB in through the Indigo reflector")
            if mb_out >= WARN_MB_HOUR:
                log(msg + f" (over the {WARN_MB_HOUR:.0f} MB/hour budget — something "
                          f"remote is pulling from this server; check for a dashboards "
                          f"page or Indigo Touch on the reflector address)", level="WARNING")
            else:
                log(msg)
        state["last_bucket"] = bucket
    else:
        state["last_bucket"] = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H")
        if prev_pid is not None and pid != prev_pid:
            log("[ReflectorBW] the reflector tunnel restarted — counters re-based")

    # Keep a week, no more: this file is read by a human after the event.
    if len(hours) > KEEP_HOURS:
        for k in sorted(hours)[:len(hours) - KEEP_HOURS]:
            hours.pop(k, None)

    state.update({"pid": pid, "started": started, "bytes_in": b_in, "bytes_out": b_out,
                  "sampled_at": now, "last_run": now,
                  "total_mb_out_this_tunnel": round(b_out / 1e6, 1),
                  "total_mb_in_this_tunnel": round(b_in / 1e6, 1)})
    _write_state(state)


main()
