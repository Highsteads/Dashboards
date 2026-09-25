#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    dash_common.py
# Description: The constants, small pure helpers and the log() helper that
#              plugin.py and its mixin modules share (v3.32.0). They lived at
#              the top of plugin.py, where no mixin could import them without
#              importing plugin.py itself.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import json
import re
import logging
import os
from datetime import datetime

# Indigo sets cwd to Contents/Server Plugin/ at launch; captured at import, as
# plugin.py does, in case anything changes the working directory later.
SERVER_PLUGIN_DIR = os.getcwd()
CONTENTS_DIR      = os.path.dirname(SERVER_PLUGIN_DIR)

try:
    from plugin_utils import as_bool
except ImportError:
    # Fallback only if plugin_utils.py is missing from the bundle. A saved
    # checkbox arrives as a real bool, but a value written as a string (or a
    # device state from another plugin) does not, and bool("false") is True.
    def as_bool(value, default=False):
        if value is None or value == "":
            return default
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "off")
        return bool(value)


# ============================================================
# Constants
# ============================================================

# Pages are mirrored into Web Assets/public/dashboards/ so IWS serves them
# WITHOUT HTTP Basic Auth. Indigo only treats the global /public/ namespace
# as anonymous — per-plugin `public/` subfolders still require auth.
PUBLIC_SUBDIR     = "dashboards"
INDEX_PATH        = f"/public/{PUBLIC_SUBDIR}/index.html"

# Source folder inside the plugin bundle that holds the HTML pages we mirror.
PAGES_SOURCE_DIR  = os.path.join(CONTENTS_DIR, "Resources", "static", "pages")

# Colour presets (v2.94.0). These used to live in room.html, where applying one
# meant the BROWSER firing three ordered commands — turn on, set brightness, set
# colour — each wrapped in an empty catch. A phone that locked, backgrounded the
# tab or lost signal between them left the lamp half-set, and said nothing. The
# sequence now runs on the server behind ONE request (the applyColour endpoint),
# so the table has to live here too: two copies of it would drift the moment one
# was edited. The page draws its buttons from `colourPresets` in config.js.
#
# mode is presentational — the page uses it to decide which swatch to draw. What
# the server acts on is which of the level keys are present.
COLOUR_PRESETS = {
    "warm":  {"label": "Warm white", "icon": "cloudsun", "mode": "white",
              "whiteTemperature": 2700, "brightness": 100},
    "movie": {"label": "Movie", "icon": "film", "mode": "color",
              "redLevel": 100, "greenLevel": 35, "blueLevel": 8, "brightness": 18},
}
# The colour keys setColorLevels accepts, and the range each is valid over. A
# request naming anything else, or a value outside the range, is REFUSED rather
# than clamped: a clamp turns a caller's mistake into a light that silently did
# something other than what was asked, which is the harder fault to spot.
_COLOUR_LEVEL_KEYS = {
    "redLevel":         (0, 100),
    "greenLevel":       (0, 100),
    "blueLevel":        (0, 100),
    "whiteLevel":       (0, 100),
    "whiteLevel2":      (0, 100),
    "whiteTemperature": (1000, 10000),
}

# The settings-store keys the Alerts page owns (3.47.0). The Settings page's
# save neither sets nor clears them: it carries the stored values over, as it
# does the stills token, so a Settings tab opened before a rule was added
# cannot save the rules away. alerts_mixin.py reads and writes them.
ALERT_STORE_KEYS = ("alertRules", "alertsActive", "alertEmail", "alertRulesRev")

# Cameras configuration is now user-supplied via:
#   1. IndigoSecrets.DASHBOARDS_CAMERAS (JSON string or list of dicts), or
#   2. PluginConfig "camerasJson" textfield (JSON list).
# Each entry must have keys: host, name, vendor ("dahua" or "hikvision").
# When empty, the camera grid, WebRTC and go2rtc are simply disabled.
#
# Order matters: the first entry is the default "focused" tile on
# cameras.html — it appears large at the top with the rest as a row of
# smaller tiles underneath. By default the LAST entry in the list is the
# "swap-out" cam — the one bumped to still when the user peeks at a tail-of-
# list camera. Override with PluginConfig "swapOutHost" if a different cam
# is better to drop from the live pool.
CAMERA_PORT          = 80                                  # snapshot HTTP port (Dahua & Hikvision)
CAMERA_POLL_SECONDS  = 2.0                                 # snapshot poll interval per camera (drives all thumbnail tiles, including cameras with live viewers)
# 3.48.0: stills are taken only while a page is showing them. Each still opens a
# fresh RTSP session to the camera and waits for a keyframe (go2rtc keeps nothing
# open between frame.jpeg calls), so ten cameras every 2 s was five camera
# connections a second around the clock: ~4.4 Mbit/s in from the cameras and
# ~13 GB a day of JPEG writes, measured 25-09-2026, for pictures nobody saw.
CAMERA_WATCH_TTL_S   = 30.0                                # a camera counts as watched this long after a page last said so (pages report every 10 s)
CAMERA_WATCH_HOSTS_MAX = 64                               # the most hosts one watchCameras call may name
CAMERA_IDLE_MINUTES_DEFAULT = 5                           # an unwatched camera is still checked this often, so camera health and the hub's offline warning keep working
CAMERA_IDLE_MINUTES_MAX = 60                              # the most a saved stillsIdleMinutes may ask for (0 = never check an unwatched camera)
CAMERA_RECHECK_SECONDS = 30.0                             # an unwatched camera whose last still FAILED is tried again this soon, so "offline" (3 failures) shows in about a minute, not 15
CAMERA_POLL_MAX_WORKERS = 9                                # concurrent snapshot fetches. Serially, nine cameras
                                                           # overran the 2s interval and each tile only refreshed
                                                           # every ~4.1s (measured); these are all network waits,
                                                           # so overlapping them costs nothing.
LIVE_POOL_SIZE       = 6                                   # how many cameras run live (WebRTC) on cameras.html at home; the rest poll stills
LIVE_POOL_MAX        = 12                                  # 3.46.0: the most a saved livePoolSize may ask for (each live tile is ~1 Mbit/s and a decoder)
CAMERA_HTTP_TIMEOUT  = 15.0                                # per-snapshot timeout (4K snapshots can take 5-10s on busy cams)
PRESENCE_REFRESH_SECONDS = 300                             # how often to re-run Presence_Watch.py (refreshes presence.json for the Presence tile — live-tonight needs periodic rebuilds)
LOG_WATCH_REFRESH_SECONDS = 3600                           # how often to re-run Log_Error_Watch.py (hourly by design — it dedupes against its own state file, so a double-run is harmless)
FP300_WATCH_REFRESH_SECONDS = 3600                         # how often to re-run FP300_Config_Watch.py (hourly — it only writes when a sensor has drifted AND is awake, so most ticks do nothing)
REFLECTOR_BW_REFRESH_SECONDS = 300                         # how often to sample the reflector tunnel's byte counters (5 min — the counters are cumulative, so the cadence only sets how finely an hour can be attributed, and each sample costs two short subprocess calls)
def normalise_deadline(text):
    """"HH:MM" -> "HH:MM" zero-padded, "" -> "", anything else -> None.

    An Indigo variable takes any string it is given, so junk written here would make
    Appliance_Scheduler.py warn and fall back every fifteen minutes for ever. Refuse at the
    door instead, and say what a good value looks like.
    """
    text = str(text or "").strip()
    if not text:
        return ""                       # empty is legitimate: it means "use the default"
    if text.count(":") != 1:
        return None
    hh, _, mm = text.partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        return None
    hh, mm = int(hh), int(mm)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def normalise_appliance_key(text):
    """A scheduler appliance key, or None.

    Lower case, digits and single underscores only. It is interpolated into an Indigo
    variable name, and Indigo variable names may not contain spaces — so anything else is
    refused rather than quietly creating a variable no one can read back.
    """
    text = str(text or "").strip().lower()
    if not text or len(text) > 60:
        return None
    if not all(c.isalnum() or c == "_" for c in text):
        return None
    if text.startswith("_") or text.endswith("_") or "__" in text:
        return None
    if not text[0].isalpha():
        return None
    return text


LAUNDRY_REFRESH_SECONDS = 900                              # how often to re-run Appliance_Scheduler.py (15 min — the inputs are an hourly solar forecast, a half-hourly price and a battery that moves slowly, so a faster cadence would recompute the same answer; the page polls the file it writes, never the plugin)
NIGHT_SWEEP_REFRESH_SECONDS = 120                          # how often to re-run Night_Lights_Sweep.py (2 min — its own gap guard discards every streak if a run is more than 10 min after the last, so a slower cadence would stop it acting at all)


# Liveness stamp (v2.70.0). A /message/ request in flight when this plugin
# host stops wedges the ENTIRE IWS event loop for a fixed ~298 s (measured
# 6/6 across 11 restarts) — so the pages must stop calling /message/ BEFORE
# the host dies. The plugin heartbeats a tiny JSON stamp into the anonymous
# /public dir (IWS serves it itself, no plugin IPC, so it cannot wedge);
# dashboards-gate.js reads it and gates every /message/ poller. state flips
# to "stopping" in stopConcurrentThread — the earliest signal Indigo gives
# us, seconds before shutdown()'s 20-30 s worst-case teardown begins.
# Contains nothing sensitive: epochs and a state word only.
STAMP_FILENAME          = "changed.stamp"
STAMP_PERIOD_SECONDS    = 2.0     # heartbeat cadence (matches the camera poller)
STAMP_CHANGE_WRITE_GAP  = 1.0     # min gap between deviceUpdated-driven writes
# How long shutdown() holds the host ALIVE after the sentinel, before any
# teardown. The gate memoises its stamp verdict for STAMP_PERIOD_SECONDS, so
# a poll can fire on a verdict up to ~2 s stale — and a fast teardown
# (measured: stop to new boot in TWO seconds on this Mac) can kill the host
# inside that window, stranding exactly the request the stamp exists to
# prevent (live-hit on the third verification restart, 31-Jul-2026). 4 s
# covers the stale-verdict window plus the request itself, with margin.
STAMP_QUIESCE_SECONDS   = 4.0

def _safe_int_list(values):
    """Coerce a list to ints, dropping anything unconvertible. The old inline
    guard (`lstrip("-").isdigit()`) passed "--5" and int() then raised, 500ing
    the whole config save."""
    out = []
    for x in values or []:
        try:
            out.append(int(str(x).strip()))
        except (ValueError, TypeError):
            pass
    return out


# A camera host is interpolated into go2rtc.yaml RTSP producer lines and into
# WebRTC signalling URLs, so it is an IP address or a plain hostname and nothing
# else. ONE rule for the Settings save and the running list (review 24-09-2026).
CAMERA_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")


def dict_entries(value):
    """(entries, dropped): the dict items of a stored list, each copied, and
    how many items were not dicts (review 24-09-2026). A hand-edited
    favourites or customLinks entry that was not an object made config.js's
    build raise, which stopped startup before the proxy, go2rtc or the
    liveness stamp. A value that is not a list at all counts as one dropped."""
    if value is None or value == [] or value == "":
        return [], 0
    if not isinstance(value, (list, tuple)):
        return [], 1
    keep = [dict(v) for v in value if isinstance(v, dict)]
    return keep, len(value) - len(keep)


def _parse_cameras(value):
    """Parse camera config — accepts a JSON string, a Python list, or empty.

    Required keys per entry: ``host``, ``name``, ``vendor`` (in {"dahua",
    "hikvision"}).
    Optional: ``room`` — the dashboard room(s) this cam should also appear
    on. Either a string (``"Garage"``) for a single room or a list
    (``["Garage", "Hall"]``) so one camera can surface on multiple room
    pages. Each room name must match an entry in ROOM_FOLDERS to actually
    show; unrecognised names are silently ignored by the room template (the
    camera still appears on the main cameras page regardless).
    Invalid entries are silently dropped.
    """
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            # A typo in DASHBOARDS_CAMERAS / camerasJson used to read as
            # "0 cameras configured" with no clue why.
            log(f"[Cameras] camera config is not valid JSON ({exc}) — "
                f"no cameras will be configured until it is fixed", level="ERROR")
            return []
    if not isinstance(value, list):
        return []
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        if not all(k in entry for k in ("host", "name", "vendor")):
            continue
        # Preserve room as string OR list of strings. Downstream code in
        # _build_rooms_json normalises both to a list before lookup.
        raw_room = entry.get("room", "")
        if isinstance(raw_room, (list, tuple)):
            room_val = [str(x).strip() for x in raw_room if str(x).strip()]
        else:
            room_val = str(raw_room).strip()
        # `stream` picks which RTSP path the go2rtc config uses for this
        # camera's source — "main" or "sub2". Default is sub2 (see
        # CAMERA_DEFAULT_STREAM). Anything unknown silently falls back to
        # the default so a typo doesn't take a camera offline.
        stream = str(entry.get("stream", CAMERA_DEFAULT_STREAM)).lower().strip()
        if stream not in ("main", "sub2"):
            stream = CAMERA_DEFAULT_STREAM
        cleaned.append({
            "host":   str(entry["host"]),
            "name":   str(entry["name"]),
            "vendor": str(entry["vendor"]).lower(),
            "room":   room_val,
            "stream": stream,
        })
    return cleaned


def _detect_lan_ip():
    """Best-effort LAN IP detection (used in go2rtc WebRTC candidates +
    the startup log line that prints the go2rtc API URL).  Returns the
    first non-loopback IPv4 the host advertises, or '127.0.0.1' on
    failure.  No outbound connection is actually made."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 198.51.100.1 is a TEST-NET-2 address — never routes anywhere,
            # but the kernel picks the correct source interface for it.
            s.connect(("198.51.100.1", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"

# Vendor URL templates: {host} {user} {pwd} are substituted. Each vendor has
# both a mainstream URL (highest quality, big bandwidth) and a substream 2 URL
# (typically 720p / ~512 kbps — plenty for an at-a-glance dashboard mosaic).
# Per-camera `stream` field in DASHBOARDS_CAMERAS picks which one go2rtc uses
# as the ffmpeg source. Default is sub2 — see CAMERA_DEFAULT_STREAM below.
#
# Stream conventions per vendor:
#   Dahua     — subtype=0 main, subtype=1 sub1 (unused), subtype=2 sub2
#   Hikvision — Channels/101 main (ch 1 stream 01), Channels/102 sub2
#
# Why sub2 by default: the dashboard is a "is anything moving?" surface, not
# a recording archive. Mainstream lives in the Synology NVR at 4K for the
# actual footage. Using sub2 here halves ffmpeg CPU and cuts LAN bandwidth
# from ~50 Mbps to ~5 Mbps across the 9 cameras.
VENDOR_URLS = {
    "dahua": {
        "snapshot_path": "/cgi-bin/snapshot.cgi",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/cam/realmonitor?channel=1&subtype=0",
        "rtsp_sub2":     "rtsp://{user}:{pwd}@{host}:554/cam/realmonitor?channel=1&subtype=2",
    },
    "hikvision": {
        "snapshot_path": "/ISAPI/Streaming/channels/101/picture",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/Streaming/Channels/101",
        "rtsp_sub2":     "rtsp://{user}:{pwd}@{host}:554/Streaming/Channels/102",
    },
}

# Default stream when a DASHBOARDS_CAMERAS entry omits `stream` — sub2 saves
# CPU + bandwidth and quality is plenty for tile-sized viewing. Override per
# camera by setting `"stream": "main"` in IndigoSecrets.
CAMERA_DEFAULT_STREAM = "sub2"

# The plugin's own small HTTP server: WebRTC signalling, the API-key and
# guest bootstraps and the guest read path. LAN and Tailscale sources only;
# never port-forwarded, never fronted by the reflector. It also carried live
# MJPEG until v3.36.0.
PROXY_PORT     = 8177

# go2rtc — WebRTC video for the live camera tiles. The plugin generates a
# config.yaml at startup (RTSP URLs include DAHUA_USER/DAHUA_PASS) and runs
# go2rtc as a subprocess. Bind addresses:
#   :1984 — HTTP API, loopback only (signalling reaches it via the :8177 proxy)
#   :8555 — WebRTC media, UDP and TCP, straight to the browser
GO2RTC_BIN           = os.path.expanduser("~/bin/go2rtc")
# go2rtc.log is kept for triage only; start a fresh file past this size
# (checked at start AND on the 30 s supervision sweep while it runs).
GO2RTC_LOG_CAP_BYTES = 5 * 1024 * 1024
GO2RTC_API_PORT      = 1984
# Snapshots are only ever shown in a TILE — the hub's camera strip at ~215px
# and the cameras grid at about the same. They were being fetched at the
# camera's full resolution: 1280x720, 124-173 KB, for a 200px box. go2rtc will
# scale the frame for us (`&width=`), which costs it nothing extra because it
# is decoding the frame either way.
#   1280 -> 124 KB      640 -> 38 KB      480 -> 26 KB      320 -> 11 KB
# 640 keeps a focused tile looking respectable when it falls back to stills on
# a slow link, and is still a third of what was being sent.
CAMERA_SNAPSHOT_WIDTH = 640

# A SECOND, smaller copy of each snapshot, for the eight thumbnails in the grid.
# They are drawn about 300 px wide on a desktop and less than that on a phone, so
# sending them 640 px of picture was paying for detail no one can see. MEASURED
# across all nine cameras: 640 -> 33.2 KB each, 320 -> 12.3 KB each, so a grid
# pass drops from 299 KB to 111 KB. The focused tile keeps the full-size picture.
#
# The resize happens HERE, from the frame we already fetched, rather than by
# asking go2rtc for a second one at a different width. That was the obvious
# approach and it is wrong: eighteen frame requests a pass made go2rtc answer
# HTTP 500, because each camera was being asked to decode twice in quick
# succession. Resizing a frame already in memory costs about a millisecond and
# leaves the load on the cameras exactly as it was.
CAMERA_THUMB_WIDTH   = 320
# Pause before the single retry of a failed snapshot. 250 ms was measured, not
# guessed: over 270 requests, 4 came back HTTP 500 and all 4 succeeded at this
# delay, none needing a second attempt.
CAMERA_RETRY_DELAY   = 0.25
CAMERA_THUMB_QUALITY = 72              # JPEG quality for the shrunk copy

GO2RTC_WEBRTC_PORT   = 8555
GO2RTC_RTSP_PORT     = 8554            # exposed for completeness; not used by the page


# ============================================================
# Helpers
# ============================================================

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


# The module log() helper writes STRAIGHT to indigo.server.log, deliberately:
# that call bypasses the logging handlers altogether, so a WARNING or an ERROR
# reaches the shared event log whatever the Log Level pref is set to, and
# Log_Error_Watch.py reads the event log and nothing else.
#
# The cost of bypassing the handlers is that none of those 56 fault lines ever
# reached this plugin's OWN log file, while the routine narration moved there
# on 06-09-2026 - so diagnosing a fault meant reading two files side by side
# and interleaving them by hand. _FILE_MIRROR writes the same record a second
# time through the plugin's file handler alone, so one file holds the fault
# and the plumbing around it.
_FILE_MIRROR = None


def _install_file_mirror(file_handler):
    """Point the module log() helper at this plugin's own log file as well.

    A CHILD of the "Plugin" logger with propagate=False, carrying the file
    handler and nothing else. Both halves of that matter: propagation would
    take the record up to indigo_log_handler and write the event-log line a
    SECOND time, and the file handler is the same object self.logger writes
    through, so a mirrored fault interleaves with the surrounding _activity()
    lines in one file in the order they happened.

    plugin_base builds plugin_file_handler in its own __init__, so call this
    after super().__init__(). A host that could not create the log directory
    gets a StreamHandler instead and this still works; a host with no handler
    at all leaves the mirror off and log() behaves exactly as it did before.

    Mirrored lines are recognisable in plugin.log: the file handler's format
    carries the logger name, so they read "Plugin.eventlog.log:" where a
    self.logger line reads "Plugin.<method>:". They also lack the
    "[HH:MM:SS.mmm] " prefix, because plugin_utils attaches that filter to the
    "Plugin" logger itself and a child logger's records bypass it - no loss,
    since the file handler stamps its own timestamp on every line anyway.
    """
    global _FILE_MIRROR
    mirror = logging.getLogger("Plugin.eventlog")
    mirror.propagate = False
    # Replace, never append: a second __init__ in one process (which is what a
    # test run does) would otherwise stack the handler and write every mirrored
    # line twice. Detached in the no-handler case too, so a stale handler from
    # an earlier install cannot outlive it.
    for existing in list(mirror.handlers):
        mirror.removeHandler(existing)
    if file_handler is None:
        _FILE_MIRROR = None
        return None
    mirror.addHandler(file_handler)
    # The handler does the filtering, as it does for self.logger - see
    # _apply_log_level for why the logger is left wide open.
    mirror.setLevel(logging.DEBUG)
    _FILE_MIRROR = mirror
    return mirror


def log(message, level="INFO"):
    lvl = _lvl(level)
    # Event log FIRST, and unconditionally. If the mirror below ever throws,
    # the line that something is watching has already gone out.
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=lvl)
    if _FILE_MIRROR is not None:
        try:
            # The RAW message: the file handler stamps its own asctime, so
            # mirroring the event-log copy would date every line twice.
            _FILE_MIRROR.log(lvl, message)
        except Exception:
            # A logging failure must never take its caller down.
            pass
