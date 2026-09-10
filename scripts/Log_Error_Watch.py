#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    Log_Error_Watch.py
# Description: Hourly watch on the Indigo event log. Collapses errors into
#              signatures (source + digit-normalised message), keeps a state
#              file of what it has already seen, and reports only what is
#              genuinely NEW or has gone UNRESOLVED for a day. The first run
#              seeds the state and deliberately says nothing, so the estate's
#              existing background noise never pages anyone. Alerts go out as
#              one Pushover headline plus a full email, and the state file
#              doubles as the feed for the Dashboards alerts page.
#              Errors alert; warnings are recorded and shown but never pushed.
# Author:      CliveS & Claude Fable 5.1
# Date:        02-09-2026 + UK time now
# Version:     1.5
#
# v1.5 (02-09-2026, Dashboards deep review lows): (1) two DIFFERENT errors
#   from the same source milliseconds apart — "Drive Left Motion" and "Drive
#   Right Motion" — no longer weld into one record (a wrapped tail never
#   introduces a new quoted device, and never itself matches a RECOVERS fail
#   pattern). (2) Pushover receipt needs isRunning(), not isEnabled(): a
#   crashed plugin swallows executeAction without raising, and "delivered"
#   would have been stamped over nothing. (3) fresh_count compares against a
#   full-precision last_seen, so a burst in the same second is not re-counted
#   next run. (4) The October fold hour: a negative gap of about an hour
#   between rows the log itself ordered is treated as ordered. (5) A dated
#   log's continuation line is recognised by failing to parse as a timestamp,
#   not by counting tabs — a traceback line with tabs in it was dropped.
#   (6) The buffer-shortfall note is INFO unless the file fallback also came
#   back empty; it is normal for 1.5 h after every server start. (7) The state
#   carries last_unanswered so the triage feed can tell an old unanswered
#   failure from one the source has since answered.
#
# v1.4 (02-09-2026): a delivered alert CLEARS the pending flag. `pending` is
#   set when a Pushover/email send fails so the next run retries — but a
#   successful retry never reset it, and decide() re-alerts anything pending,
#   so one delivery hiccup turned a still-occurring fault into a page EVERY
#   HOUR until it stopped or was muted. Muting is not a fix for a delivery
#   bug. Found by the Dashboards deep review (Fable 5.1). Also: the
#   module-level sys.path insert is guarded — this file is exec()ed from the
#   Dashboards plugin host every hour, and an unguarded insert grew that
#   host's sys.path by one entry a tick for as long as it ran.
#
# v1.3 (29-08-2026): an error the same source reports a SUCCESS for moments
#   later is no longer news. Indigo's Z-Wave plugin logs a first-attempt send
#   timeout to a sleeping node as an Error and says nothing about the retry that
#   lands 8ms afterwards, so a battery sensor that is working perfectly paged
#   four times in eleven days. Every one of the thirteen occurrences since June
#   is followed inside 550ms by "received ... status update battery level 100%".
#   RECOVERS carries the rule, and it is deliberately not a per-device exemption:
#   it keys on the SHAPE of the fault, so it covers every sleeping Z-Wave node in
#   the house, present and future, and only while the success actually appears.

import os
import re
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
    from IndigoSecrets import PUSHOVER_USER_TOKEN
except ImportError:
    PUSHOVER_USER_TOKEN = ""
try:
    from IndigoSecrets import LOG_WATCH_EMAIL
except ImportError:
    LOG_WATCH_EMAIL = ""
try:
    from IndigoSecrets import DIGEST_EMAIL
except ImportError:
    DIGEST_EMAIL = ""

PUSHOVER_PLUGIN_ID = "io.thechad.indigoplugin.pushover"

# ======================================
# CONFIG
# ======================================
# Window is wider than the schedule interval on purpose — an hourly run with a
# 1.5h lookback overlaps, so nothing can slip through the gap between runs.
# Re-reporting is prevented by the state file, not by a tight window.
LOOKBACK_HOURS = 1.5

# A signature not seen for this long is news again when it comes back.
QUIET_HOURS = 24

# A signature already alerted, still occurring, is re-reported this often so a
# persistent fault cannot go quiet just because it was mentioned yesterday.
RE_ALERT_HOURS = 24

# Signatures untouched for this long are dropped from the state file.
FORGET_DAYS = 30

# Levels that actually alert. Warnings are still collected and shown on the
# dashboard — they just never reach Pushover or email. Add "warn" to change it.
ALERT_LEVELS = ("error",)

# Known noise: (source substring, message regex). Anything matching is recorded
# in the feed but never alerted. Left empty on first release on purpose, so the
# seed run could show what the real background was before anything was hidden.
# Populated 04-08-2026 from ten days of that evidence — 81% of everything the
# watch had ever mailed was one of the four entries below.
MUTED = [
    # The IWS wedge cascade. A plugin restart while a browser is mid-poll takes
    # the IWS loop down for 4m58s, and every static file requested in that
    # window 500s. The named file is innocent and the fault clears itself, so
    # there is nothing here to act on. Documented in the global CLAUDE.md.
    ("Web Server", r"internal server error for request"),
    ("Web Server", r"message handler failed"),
    # The same restart seen from the other side: an action fired at a plugin
    # that was still coming back up.
    ("Indigo Server", r"unable to execute action -- device plugin .* not running"),
    # Failures inside a Claude Code session's own scripting shell. Those are a
    # dev session talking to itself, not the house misbehaving.
    ("Claude Bridge", r"\[scripting_shell\]"),
]

# Errors the source itself reports a success for, moments later. Each rule is
# (source substring, failing-message regex, recovery-message regex, seconds).
#
# This is NOT a mute and NOT a per-device exemption. A rule keys on the SHAPE of
# a fault, and it suppresses an occurrence ONLY when the matching success is
# actually there in the log — so the same signature still alerts the day the
# retry stops landing, which is the day it starts mattering. A rule that names a
# device would instead go quiet for ever, including for the real failure.
#
# The recovery must come from the same base source, must not itself be an error,
# and — when the failing line names a subject in quotes — must name that same
# subject, so one device's success can never clear another device's fault.
RECOVERS = [
    # A sleeping Z-Wave node misses the first send and answers the retry
    # milliseconds later. Indigo logs the failed attempt and not the success.
    ("Z-Wave",
     r"command failed \(module might be asleep",
     r"\breceived\b.*\b(?:status update|is responding)\b",
     30),
]

# This script's own summary line logs at WARNING when it finds something, which
# the next run would otherwise collapse into a signature and report on. Skip our
# own output so the watcher never watches itself.
SELF_PREFIX = "Log Error Watch"

FETCH_LINES          = 3000    # the in-memory buffer is the real limit (~1300)
CONTINUATION_SECONDS = 0.05    # a wrapped message arrives as rows ~1ms apart
MAX_PUSHOVER_LINES   = 4       # headline only; the email carries the rest
PUSH_LINE_CHARS      = 90
FEED_MESSAGE_CHARS   = 300

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__)) \
    if "__file__" in globals() else \
    "/Library/Application Support/Perceptive Automation/Python Scripts"
STATE_PATH = os.path.join(_SCRIPTS_DIR, "log_error_watch_state.json")
LOCK_PATH  = "/tmp/log_error_watch.lock"

ISO = "%Y-%m-%d %H:%M:%S"
_TS_PREFIX_RE = re.compile(r"^\[\d\d:\d\d:\d\d(\.\d+)?\]\s*")


# ======================================
# HELPERS
# ======================================
_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
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


def _cfg(name, default):
    """Read a module-level tunable defensively.

    A schedule-run script's main() can execute with module-level names absent
    from its globals entirely (weekly_home_digest v1.2, 03-07-2026) even though
    the top level binds them unconditionally. Functions resolve fine, constants
    may not — so never read a constant directly from inside main().
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
# PURE LOGIC (no Indigo, no disk — unit-testable)
# ======================================
def clean_message(raw):
    """Strip the plugin-added [HH:MM:SS.mmm] prefix, as the Activity page does."""
    return _TS_PREFIX_RE.sub("", str(raw or "")).strip()


def classify(src, type_val):
    """Return (base_source, level).

    TypeStr is either a bare level ('Error', 'Warning' — core server messages)
    or '<Source> Error' (plugins, e.g. 'Web Server Error'). Stripping the
    suffix off the bare form leaves nothing, hence the fallback name.
    Same test as Dashboards' _activity_events so the two never disagree.
    """
    src = str(src or "")
    base = src.replace(" Error", "").replace(" Warning", "").strip()
    # The bare forms carry no leading space, so the replace above is a no-op on
    # them and they would otherwise be sourced as "Error" / "Warning".
    if base in ("", "Error", "Warning"):
        base = "Indigo Server"
    if type_val == 1 or src.endswith("Error"):
        level = "error"
    elif type_val == 3 or src.endswith("Warning"):
        level = "warn"
    else:
        level = "info"
    return base, level


_PATH_RE         = re.compile(r"(?<=\s)/\S+")
_PLUGIN_ID_RE    = re.compile(r"\b[a-z][a-z0-9]*(?:\.[a-z0-9_\-]+){2,}\b")
_NAMED_PLUGIN_RE = re.compile(r"(device plugin )(.+?)( not running)", re.I)
_REFLECTOR_RE    = re.compile(r"reflector|indigodomo\.com", re.I)


def normalise(message):
    """Reduce a message to its FAULT, dropping the detail that merely varies.

    Normalising digits alone was not enough. One IWS wedge 500s a dozen
    different static files, and one restart names whichever plugin happened to
    be mid-request — so a single event arrived as a dozen separate signatures,
    each of them brand new, each worth its own email. The varying part must
    never reach the key.

    Applied to the KEY only. The displayed message keeps its real filename and
    plugin name, so the email still says which one it was.
    """
    text = _NAMED_PLUGIN_RE.sub(r"\1<plugin>\3", message)
    text = _PLUGIN_ID_RE.sub("<pluginid>", text)
    text = _PATH_RE.sub("<path>", text)
    return re.sub(r"\d+", "#", text)


def signature(base_src, message):
    """Collapse key: source + normalised first 80 chars.

    Digits are normalised in the KEY only, never in the displayed message, so
    'regs 30220-30223' and 'regs 30216-30219' count as one problem.
    """
    if _REFLECTOR_RE.search(message):
        # One outage speaks in four phrasings — "Unable to connect to
        # IndigoDomo.com", "reflector connection test failed: ...", "failed to
        # create reflector connection: ...". Alert on it once, not four times.
        # Still scoped by source, so a plugin's own reflector talk stays apart.
        return base_src + "|<reflector connectivity>"
    return base_src + "|" + normalise(message)[:80]


def same_error(first, second, chars=60):
    """True when two rows are the SAME error recurring, not a wrapped tail."""
    return normalise(first)[:chars] == normalise(second)[:chars]


def is_muted(base_src, message, muted):
    for src_match, msg_pattern in muted or []:
        if src_match and src_match not in base_src:
            continue
        try:
            if re.search(msg_pattern, message, re.I):
                return True
        except re.error:
            continue
    return False


_QUOTED_RE = re.compile(r'"([^"]{1,80})"')


def subjects(message):
    """The quoted names a message is about — usually the device, e.g.
    send "Drive Right Motion" requestBatteryLevel1 command failed."""
    return set(_QUOTED_RE.findall(str(message or "")))


def mark_recovered(records, rules=None):
    """Flag error records whose own source logged the matching success moments
    later. Sets rec["recovered"]; records must be chronological.

    An error that the log itself shows was answered is not a fault, and pushing
    it teaches the reader to skim — which is how a real one gets missed. The
    check is deliberately narrow in three ways at once: the success must come
    from the SAME base source, must not itself be an error, and must name the
    same quoted subject when the failing line names one. A rule with no quoted
    subject in its failing line carries no subject constraint, so its two
    regexes have to be specific enough on their own.

    Nothing is suppressed on the strength of a rule alone. Absent the success
    line the record stays an error, so a node that stops answering starts
    alerting immediately — the opposite direction to a mute, which goes quiet
    for the real failure too.
    """
    rules = rules or []
    if not rules:
        return records
    for index, rec in enumerate(records):
        base, level = classify(rec["src"], rec["tv"])
        if level != "error":
            continue
        for src_match, fail_pattern, ok_pattern, window in rules:
            if src_match and src_match not in base:
                continue
            try:
                if not re.search(fail_pattern, rec["msg"], re.I):
                    continue
            except re.error:
                continue
            wanted = subjects(rec["msg"])
            for later in records[index + 1:]:
                gap = (later["ts"] - rec["ts"]).total_seconds()
                if gap < 0 and -3660 <= gap and rec["ts"].month == 10:
                    gap = 0.0          # the October fold hour; rows are in log order
                if gap < 0:
                    continue
                if gap > window:
                    break          # chronological, so nothing later can qualify
                later_base, later_level = classify(later["src"], later["tv"])
                if later_base != base or later_level == "error":
                    continue
                try:
                    if not re.search(ok_pattern, later["msg"], re.I):
                        continue
                except re.error:
                    continue
                if wanted and not (wanted & subjects(later["msg"])):
                    continue
                rec["recovered"] = True
                break
            if rec.get("recovered"):
                break
    return records


def _is_fail_line(message):
    """True when a message matches any RECOVERS fail pattern — a complete
    failure line in its own right, never the tail of the one before."""
    for rule in _cfg("RECOVERS", RECOVERS) or []:
        try:
            if re.search(rule[1], str(message or ""), re.I):
                return True
        except (re.error, IndexError, TypeError):
            continue
    return False


def merge_continuations(rows, gap_seconds=CONTINUATION_SECONDS):
    """Fold wrapped multi-line messages back into one record.

    A long message comes back from getEventLogList as SEPARATE rows sharing a
    TypeStr and landing ~1ms apart (measured: the reflector error's
    'this can be caused by: ...' arrived at +0.001s). Left alone each becomes
    its own phantom signature.

    The window alone could not tell a wrapped tail from a fresh occurrence, so
    a burst of IWS 500s — same source, milliseconds apart, each a complete
    message — was being welded into a composite that could never recur. Every
    burst therefore read as brand new and mailed. Comparing the normalised
    opening settles it: matching openings mean a repeat, so leave them apart.

    rows: dicts with TimeStamp / TypeStr / TypeVal / Message, oldest first.
    Returns records: {"ts", "src", "tv", "msg"}.
    """
    records = []
    for row in rows:
        ts = row.get("TimeStamp")
        if not isinstance(ts, datetime):
            continue
        src = str(row.get("TypeStr") or "")
        tv = row.get("TypeVal")
        msg = clean_message(row.get("Message"))
        if not msg:
            continue
        if records:
            prev = records[-1]
            delta = (ts - prev["ts"]).total_seconds()
            if delta < 0 and -3660 <= delta and ts.month == 10:
                delta = 0.0            # the October fold hour; the log is in order
            prev_subj, cur_subj = subjects(prev["msg"]), subjects(msg)
            if (prev["src"] == src
                    and 0 <= delta <= gap_seconds
                    and not same_error(msg, prev["msg"])
                    # A wrapped tail never names a different quoted device...
                    and not (prev_subj and cur_subj and not (prev_subj & cur_subj))
                    # ...and never itself reads as a failure line of its own.
                    and not _is_fail_line(msg)):
                prev["msg"] = f"{prev['msg']} {msg}"
                continue
        records.append({"ts": ts, "src": src, "tv": tv, "msg": msg})
    return records


def collapse(records, muted=None, self_prefix=SELF_PREFIX):
    """Group records into signatures. Returns {key: {...}} for error+warn only."""
    out = {}
    for rec in records:
        base, level = classify(rec["src"], rec["tv"])
        if level == "info":
            continue
        if self_prefix and rec["msg"].startswith(self_prefix) and level != "error":
            # Skip our own routine summary lines — but NOT our own ERRORS:
            # "Log Error Watch FAILED" used to be invisible to the watcher
            # itself, so a broken watch died silently every hour for ever.
            continue
        key = signature(base, rec["msg"])
        entry = out.get(key)
        if entry is None:
            out[key] = {
                "key":     key,
                "source":  base,
                "message": rec["msg"][:_cfg("FEED_MESSAGE_CHARS", 300)],
                "level":   level,
                "count":   1,
                "first":   rec["ts"],
                "last":    rec["ts"],
                "muted":   is_muted(base, rec["msg"], muted),
                "recovered": 1 if rec.get("recovered") else 0,
            }
        else:
            entry["count"] += 1
            entry["last"] = max(entry["last"], rec["ts"])
            entry["first"] = min(entry["first"], rec["ts"])
            entry["recovered"] += 1 if rec.get("recovered") else 0
            if entry["level"] == "warn" and level == "error":
                entry["level"] = "error"
        out[key].setdefault("times", []).append(rec["ts"])
    # Quiet only when EVERY occurrence in this window was answered. One
    # unanswered failure among fifty recoveries is the one that matters, so a
    # partial recovery still alerts on the whole signature.
    for entry in out.values():
        entry["recovered_all"] = bool(
            entry["count"] and entry["recovered"] == entry["count"])
    return out


def decide(current, known, now, quiet_hours=QUIET_HOURS,
           re_alert_hours=RE_ALERT_HOURS, alert_levels=ALERT_LEVELS):
    """Split this window's signatures into (new, unresolved).

    new        — never seen, or last seen longer ago than quiet_hours, or a
                 previous alert whose delivery failed (pending).
    unresolved — alerted before, still occurring, and last alerted longer ago
                 than re_alert_hours.

    Anything seen during the seed run carries no alerted_at and is therefore
    neither: it is the estate's existing background, by definition not news.

    A signature every occurrence of which was answered by its own source is
    neither either — see mark_recovered.
    """
    new, unresolved = [], []
    for key, cur in current.items():
        if cur["level"] not in alert_levels or cur.get("muted"):
            continue
        if cur.get("recovered_all"):
            continue
        prev = known.get(key)
        if prev is None:
            new.append(cur)
            continue
        if prev.get("pending"):
            new.append(cur)
            continue
        last_seen = _parse(prev.get("last_seen"))
        if last_seen is None or (now - last_seen) > timedelta(hours=quiet_hours):
            new.append(cur)
            continue
        alerted = _parse(prev.get("alerted_at"))
        if alerted is not None and (now - alerted) > timedelta(hours=re_alert_hours):
            unresolved.append(cur)
    new.sort(key=lambda e: (-e["count"], e["source"]))
    unresolved.sort(key=lambda e: (-e["count"], e["source"]))
    return new, unresolved


def build_feed(current, now):
    """The payload the Dashboards alerts card renders. Newest and loudest first."""
    rows = []
    for entry in current.values():
        rows.append({
            "source":  entry["source"],
            "message": entry["message"],
            "level":   entry["level"],
            "count":   entry["count"],
            "muted":   bool(entry.get("muted")),
            # Shown, never hidden — the dashboard says "answered" rather than
            # pretending the failed attempt was never logged.
            "recovered": bool(entry.get("recovered_all")),
            "first":   _fmt(entry["first"]),
            "last":    _fmt(entry["last"]),
        })
    rows.sort(key=lambda r: (r["level"] != "error",
                             r["muted"] or r["recovered"], -r["count"]))

    def _counts(level):
        return sum(1 for r in rows
                   if r["level"] == level and not r["muted"] and not r["recovered"])

    return {
        "generatedLocal": _fmt(now),
        "_writeTs":       now.timestamp(),
        "errors":         _counts("error"),
        "warnings":       _counts("warn"),
        "rows":           rows,
    }


# ======================================
# LOG SOURCES
# ======================================
def _fetch_from_buffer(window_start, fetch_lines):
    """(rows_in_window, truncated). Truncated means the buffer did not reach back
    far enough, so the window is incomplete and the file must be read instead."""
    rows = indigo.server.getEventLogList(returnAsList=True, lineCount=fetch_lines)
    if not rows:
        return [], True
    stamps = [r.get("TimeStamp") for r in rows if isinstance(r.get("TimeStamp"), datetime)]
    if not stamps:
        return [], True
    truncated = min(stamps) > window_start
    in_window = [r for r in rows
                 if isinstance(r.get("TimeStamp"), datetime)
                 and r["TimeStamp"] >= window_start]
    in_window.sort(key=lambda r: r["TimeStamp"])
    return in_window, truncated


def _parse_events_file(path, window_start):
    """Parse a dated 'YYYY-MM-DD Events.txt' into getEventLogList-shaped rows.

    Three tab-separated fields: timestamp, source, message. The level is a
    SUFFIX on the source ('Shelly Direct Warning'), not a column. Wrapped
    messages emit continuation lines carrying no tabs at all.
    """
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                stamp = None
                if len(parts) >= 3:
                    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                        try:
                            stamp = datetime.strptime(parts[0].strip(), fmt)
                            break
                        except ValueError:
                            continue
                if stamp is None:
                    # Not a new row. A wrapped continuation usually carries no
                    # tabs, but a traceback source line can — decide by the
                    # timestamp, not the tab count, so nothing is dropped.
                    if rows:
                        rows[-1]["Message"] += " " + line.strip()
                    continue
                src = parts[1].strip()
                rows.append({
                    "TimeStamp": stamp,
                    "TypeStr":   src,
                    # The file has no TypeVal — classify() reads the suffix.
                    "TypeVal":   1 if src.endswith("Error") else 3 if src.endswith("Warning") else 8,
                    "Message":   "\t".join(parts[2:]).strip(),
                })
    except FileNotFoundError:
        return []
    except Exception as exc:
        log(f"Log Error Watch: could not read {os.path.basename(path)} ({exc})", level="WARNING")
        return []
    return [r for r in rows if r["TimeStamp"] >= window_start]


def _fetch_from_files(window_start, now):
    base = indigo.server.getInstallFolderPath()
    rows, day = [], window_start.date()
    while day <= now.date():
        rows += _parse_events_file(
            os.path.join(base, "Logs", f"{day.strftime('%Y-%m-%d')} Events.txt"),
            window_start)
        day += timedelta(days=1)
    rows.sort(key=lambda r: r["TimeStamp"])
    return rows


# ======================================
# STATE
# ======================================
def load_state(path):
    """A MISSING file is the normal first run. A CORRUPT file is not — a
    silent re-seed there converts every currently-firing fault into permanent
    baseline and nothing ever alerts on it again. So corruption is loud
    (ERROR, which itself lands in the next run's window), and the bad file is
    kept beside the script for inspection rather than overwritten."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("signatures"), dict):
            return data
        _quarantine_state(path, "malformed")
    except FileNotFoundError:
        pass
    except Exception as exc:
        _quarantine_state(path, f"unreadable ({exc})")
    return {"version": 1, "seeded_at": None, "signatures": {}}


def _quarantine_state(path, why):
    kept = ""
    try:
        aside = path + ".corrupt-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        os.replace(path, aside)
        kept = f" — bad file kept at {os.path.basename(aside)}"
    except OSError:
        pass
    log(f"Log Error Watch: state file {why}. RE-SEEDING: every fault firing "
        f"right now becomes baseline and will NOT alert until it goes quiet "
        f"and returns{kept}", level="ERROR")


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def prune(signatures, now, forget_days):
    cutoff = now - timedelta(days=forget_days)
    for key in [k for k, v in signatures.items()
                if (_parse(v.get("last_seen")) or now) < cutoff]:
        signatures.pop(key, None)


# ======================================
# DELIVERY
# ======================================
def send_pushover(msg_title, msg_body, priority=0):
    """True when the Pushover PLUGIN accepted the message. That is the
    strongest receipt available — the plugin queues to Pushover's cloud
    asynchronously, so acceptance is not proof of delivery. The pending
    latch therefore protects against the failures we CAN see (plugin
    missing/disabled/raising), not a drop inside Pushover itself."""
    try:
        alert_plugin = indigo.server.getPlugin(
            _cfg("PUSHOVER_PLUGIN_ID", "io.thechad.indigoplugin.pushover"))
    except Exception as exc:
        log(f"Pushover plugin unavailable: {exc}", level="ERROR")
        return False
    try:
        alive = bool(alert_plugin) and alert_plugin.isEnabled() and alert_plugin.isRunning()
    except Exception:
        alive = False
    if not alive:
        # isRunning as well as isEnabled: a plugin that is enabled and has
        # crashed swallows executeAction without raising, and this would have
        # returned True over a message nobody sent.
        log("Pushover plugin is not running", level="ERROR")
        return False
    props = {
        "msgTitle":    msg_title,
        "msgUser":     PUSHOVER_USER_TOKEN,
        "msgBody":     msg_body,
        "msgSound":    "vibrate",
        "msgPriority": str(priority),
    }
    try:
        alert_plugin.executeAction("send", props=props)
        return True
    except Exception as exc:
        log(f"Pushover error: {exc}", level="ERROR")
        return False


def send_email(recipient, subject, body):
    if not recipient:
        return False
    try:
        indigo.server.sendEmailTo(recipient, subject=subject, body=body)
        return True
    except Exception as exc:
        log(f"Log Error Watch: email to {recipient} failed ({exc})", level="ERROR")
        return False


def compose(new, unresolved, window_start, now):
    """Return (pushover_title, pushover_body, email_subject, email_body)."""
    def _headline():
        bits = []
        if new:
            bits.append(f"{len(new)} new error" + ("s" if len(new) != 1 else ""))
        if unresolved:
            bits.append(f"{len(unresolved)} still unresolved")
        return ", ".join(bits)

    lines = []
    for entry in (new + unresolved)[:MAX_PUSHOVER_LINES]:
        text = f"{entry['source']} — {entry['message']}"
        if len(text) > PUSH_LINE_CHARS:
            text = text[:PUSH_LINE_CHARS - 1] + "…"
        if entry["count"] > 1:
            text += f" (x{entry['count']})"
        lines.append(text)
    spare = len(new) + len(unresolved) - len(lines)
    if spare > 0:
        lines.append(f"…and {spare} more — see the email")

    detail = [f"Window: {_fmt(window_start)} to {_fmt(now)}", ""]
    for label, group in (("NEW", new), ("STILL UNRESOLVED", unresolved)):
        if not group:
            continue
        detail.append(f"--- {label} ({len(group)}) ---")
        for entry in group:
            detail.append(f"[{entry['source']}] x{entry['count']}")
            detail.append(f"  {entry['message']}")
            detail.append(f"  first {_fmt(entry['first'])}   last {_fmt(entry['last'])}")
            detail.append("")
    detail.append("Muting: add a (source, regex) pair to MUTED in "
                  "Python Scripts/Log_Error_Watch.py")

    return (f"Indigo: {_headline()}",
            "\n".join(lines),
            f"Indigo log errors — {_headline()}",
            "\n".join(detail))


# ======================================
# MAIN
# ======================================
def main(dry_run=False, quiet=False):
    now = datetime.now()
    lookback   = _cfg("LOOKBACK_HOURS", 1.5)
    state_path = _cfg("STATE_PATH", None) or os.path.join(
        os.path.dirname(indigo.server.getInstallFolderPath()),
        "Python Scripts", "log_error_watch_state.json")
    muted      = _cfg("MUTED", [])
    window_start = now - timedelta(hours=lookback)

    rows, truncated = _fetch_from_buffer(window_start, _cfg("FETCH_LINES", 3000))
    if truncated:
        rows = _fetch_from_files(window_start, now)
        # Normal for 1.5 h after every server start (the buffer only reaches
        # back to boot), so INFO — unless the files came back empty too.
        log("Log Error Watch: event-log buffer did not reach back far enough "
            "for the window — read the dated log files instead",
            level="WARNING" if not rows else "INFO")

    # Recovery is decided BEFORE collapse, because it needs the info rows that
    # collapse throws away — the success line is what proves the retry landed.
    records = mark_recovered(merge_continuations(rows), _cfg("RECOVERS", []))
    current = collapse(records, muted)
    state = load_state(state_path)
    known = state.get("signatures", {})
    seeding = not state.get("seeded_at")

    if seeding:
        new, unresolved = [], []
    else:
        new, unresolved = decide(current, known, now,
                                 _cfg("QUIET_HOURS", 24),
                                 _cfg("RE_ALERT_HOURS", 24),
                                 _cfg("ALERT_LEVELS", ("error",)))

    delivered = False
    if new or unresolved:
        p_title, p_body, e_subject, e_body = compose(new, unresolved, window_start, now)
        recipient = _cfg("LOG_WATCH_EMAIL", "") or _cfg("DIGEST_EMAIL", "")
        if dry_run:
            log(f"Log Error Watch DRY RUN — would send:\n{p_title}\n{p_body}")
            delivered = True
        else:
            pushed = send_pushover(p_title, p_body)
            mailed = send_email(recipient, e_subject, e_body)
            delivered = pushed or mailed
            if not delivered:
                log("Log Error Watch: both Pushover and email failed — will "
                    "retry these next run", level="ERROR")

    # Merge this window into the state. alerted_at moves ONLY on a real
    # delivery, so an outage retries next hour instead of swallowing the alert.
    alerted_keys = {e["key"] for e in new + unresolved}
    for key, entry in current.items():
        prev = known.get(key, {})
        # The window deliberately overlaps the run cadence (1.5 h vs hourly),
        # so a naive `prev + current` double-counts every event the overlap
        # sees twice. Only events NEWER than the last run's last_seen are new.
        prev_last = None
        try:
            if prev.get("last_seen_exact"):
                prev_last = datetime.fromisoformat(prev["last_seen_exact"])
            elif prev.get("last_seen"):
                prev_last = datetime.strptime(prev["last_seen"], ISO)
        except (ValueError, TypeError):
            prev_last = None
        if prev_last is None:
            fresh_count = entry["count"]
        else:
            fresh_count = sum(1 for t in entry.get("times", []) if t > prev_last)
        record = {
            "source":     entry["source"],
            "message":    entry["message"],
            "level":      entry["level"],
            "count":      int(prev.get("count", 0)) + fresh_count,
            "first_seen": prev.get("first_seen") or _fmt(entry["first"]),
            "last_seen":  _fmt(entry["last"]),
            # Full precision, so a burst inside one second is not counted
            # again next run — last_seen is truncated to the second.
            "last_seen_exact": entry["last"].isoformat() if isinstance(entry.get("last"), datetime) else None,
            # The newest occurrence the source did NOT answer, carried forward
            # when this window answered every one — the triage feed skips a
            # recovered signature only when this is older than its cutoff.
            "last_unanswered": (prev.get("last_unanswered") if entry.get("recovered_all")
                                else _fmt(entry["last"])),
            # THIS WINDOW's verdict, deliberately not sticky — the run after a
            # genuine unanswered failure flips it back to False and the triage
            # feed picks the signature up again. A sticky flag would be an
            # exemption, which is the thing this must never become.
            "recovered":  bool(entry.get("recovered_all")),
            "alerted_at": prev.get("alerted_at"),
            # A failed delivery stays pending until it is actually delivered —
            # it used to be reset to False whenever the signature reappeared
            # outside the alert set (e.g. downgraded to warn-only), silently
            # swallowing the retry. Muting DOES cancel it: that is the user
            # saying "stop telling me".
            "pending":    bool(prev.get("pending")) and not entry.get("muted"),
        }
        if key in alerted_keys:
            if delivered and not dry_run:
                record["alerted_at"] = _fmt(now)
                record["pending"] = False      # delivered: nothing left to retry (v1.4)
            elif not dry_run:
                record["pending"] = True
                record["alerted_at"] = prev.get("alerted_at")
        known[key] = record

    prune(known, now, _cfg("FORGET_DAYS", 30))
    state["version"]    = 1
    state["signatures"] = known
    state["last_run"]   = _fmt(now)
    state["seeded_at"]  = state.get("seeded_at") or _fmt(now)
    state["feed"]       = build_feed(current, now)
    if not dry_run:
        save_state(state_path, state)

    if seeding:
        log(f"Log Error Watch: seeded {len(current)} signatures from the last "
            f"{lookback:g}h — nothing alerted on a first run")
    elif new or unresolved:
        log(f"Log Error Watch: {len(new)} new, {len(unresolved)} unresolved "
            f"(from {len(current)} signatures in window)",
            level="WARNING")
    elif not quiet:
        log(f"Log Error Watch: nothing new ({len(current)} known signatures in window)")


def _run():
    """Take an exclusive lock so two schedules can never interleave a state write."""
    try:
        handle = open(LOCK_PATH, "w", encoding="utf-8")
    except Exception:
        handle = None
    if handle is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            log("Log Error Watch: another run is in progress — skipping")
            handle.close()
            return
    try:
        main(quiet=bool(globals().get("LOG_ERROR_WATCH_QUIET")))
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
if not getattr(_builtins, "_log_error_watch_core_only", False):
    try:
        _run()
    except Exception:
        log("Log Error Watch FAILED:\n" + traceback.format_exc(), level="ERROR")
