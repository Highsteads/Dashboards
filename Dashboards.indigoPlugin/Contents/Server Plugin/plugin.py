#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Dashboards plugin — at startup, copies the HTML pages from the
#              plugin bundle into Indigo's `Web Assets/public/dashboards/`
#              folder so they are served WITHOUT HTTP Basic Auth (the IWS
#              `public/` namespace is the only path that bypasses auth).
#              Reads INDIGO_URL from IndigoSecrets.py and writes it into
#              `config.js` alongside the copied pages. The API key is NEVER
#              published (v1.20.0+) — browsers prompt once and store it in
#              localStorage, merged in by dashboards-auth.js.
#              Polls Dahua cameras in a background thread using HTTP Digest
#              auth (DAHUA_USER / DAHUA_PASS from IndigoSecrets.py) and writes
#              the JPEGs as cam-<ip>.jpg into the same public folder, so
#              cameras.html loads them same-origin with no browser auth.
#              Also runs a tiny HTTP MJPEG proxy on port 8177 that relays each
#              camera's live multipart/x-mixed-replace stream to the browser,
#              again handling Digest auth server-side. The page uses MJPEG
#              for the live grid and falls back to the still snapshot if a
#              stream connection fails.
# Author:      CliveS & Claude Opus 5 (3.17.0-3.20.0, 3.23.0); Claude Opus 5.5 (3.23.1-3.30.0); Claude Fable 5.1 (3.12.0-3.13.0); Claude Sonnet 5 (2.99.2); Claude Fable 5 (2.79.0); Claude Opus 5 (2.80-2.81, 2.84.0)
# Date:        23-09-2026
# Version:     3.31.0
#
# Version history: docs/changelog.md (what each release does, for users) and
# `git log` (why, for developers). The per-version engineering notes that sat
# here — over a thousand lines by v3.25.0 — were removed in v3.26.0; they are
# all in git history (`git show v3.25.0:"Dashboards.indigoPlugin/Contents/Server
# Plugin/plugin.py"`).

try:
    import indigo
except ImportError:
    pass

import collections
import json
import os
import queue
import re
import secrets as _stdlib_secrets   # stdlib token generator (NOT IndigoSecrets)
import shutil
import sys as _sys
import threading
import time
from datetime import datetime

# Capture cwd at module load time — Indigo sets cwd to Contents/Server Plugin/
# at launch. Storing now is more robust than calling os.getcwd() later in case
# any subsequent code changes the working directory.
SERVER_PLUGIN_DIR = os.getcwd()
CONTENTS_DIR      = os.path.dirname(SERVER_PLUGIN_DIR)

_sys.path.insert(0, SERVER_PLUGIN_DIR)
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None
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

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import INDIGO_URL
except ImportError:
    INDIGO_URL = ""
try:
    from IndigoSecrets import INDIGO_API_KEY
except ImportError:
    INDIGO_API_KEY = ""
try:
    from IndigoSecrets import CLAUDEBRIDGE_BEARER_TOKEN
except ImportError:
    CLAUDEBRIDGE_BEARER_TOKEN = ""
try:
    from IndigoSecrets import DAHUA_USER
except ImportError:
    DAHUA_USER = ""
try:
    from IndigoSecrets import DAHUA_PASS
except ImportError:
    DAHUA_PASS = ""
try:
    from IndigoSecrets import DASHBOARDS_CAMERAS  # JSON-string OR python list
except ImportError:
    DASHBOARDS_CAMERAS = ""
try:
    from IndigoSecrets import DASHBOARDS_ROOM_EXTRAS  # dict keyed by room name
except ImportError:
    DASHBOARDS_ROOM_EXTRAS = {}
try:
    from IndigoSecrets import DASHBOARDS_MAIN_CAMERAS  # list of camera host IPs
except ImportError:
    DASHBOARDS_MAIN_CAMERAS = []
try:
    # Scenes page hide-list — entries match an action group NAME, an action
    # group ID (as a string), or "folder:<Folder Name>" to hide a whole folder.
    from IndigoSecrets import DASHBOARDS_HIDDEN_SCENES  # JSON string OR python list
except ImportError:
    DASHBOARDS_HIDDEN_SCENES = []
# Weather extras (Sunset + today high/low on the hub Weather card).
# All three are optional — if absent the weather thread quietly skips.
try:
    from IndigoSecrets import OWM_API_KEY
except ImportError:
    OWM_API_KEY = ""
try:
    from IndigoSecrets import LATITUDE
except ImportError:
    LATITUDE = None
try:
    from IndigoSecrets import LONGITUDE
except ImportError:
    LONGITUDE = None
# The PostgreSQL history credentials are read by history_mixin.py (v3.30.0).


# ============================================================
# Constants
# ============================================================

PLUGIN_ID         = "com.clives.indigoplugin.dashboards"
PLUGIN_VERSION = "3.31.0"
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

# Cameras configuration is now user-supplied via:
#   1. IndigoSecrets.DASHBOARDS_CAMERAS (JSON string or list of dicts), or
#   2. PluginConfig "camerasJson" textfield (JSON list).
# Each entry must have keys: host, name, vendor ("dahua" or "hikvision").
# When empty, the camera grid / MJPEG proxy / go2rtc are simply disabled.
#
# Order matters: the first entry is the default "focused" tile on
# cameras.html — it appears large at the top with the rest as a row of
# smaller tiles underneath. By default the LAST entry in the list is the
# "swap-out" cam — the one bumped to still when the user peeks at a tail-of-
# list camera. Override with PluginConfig "swapOutHost" if a different cam
# is better to drop from the live pool.
CAMERA_PORT          = 80                                  # snapshot HTTP port (Dahua & Hikvision)
CAMERA_POLL_SECONDS  = 2.0                                 # snapshot poll interval per camera (drives all thumbnail tiles, including cameras with live viewers)
CAMERA_POLL_MAX_WORKERS = 9                                # concurrent snapshot fetches. Serially, nine cameras
                                                           # overran the 2s interval and each tile only refreshed
                                                           # every ~4.1s (measured); these are all network waits,
                                                           # so overlapping them costs nothing.
LIVE_POOL_SIZE       = 6                                   # how many cameras run live MJPEG on cameras.html. Browsers cap HTTP/1.1 connections per origin at ~6, so don't exceed that.
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

# MJPEG proxy: tiny HTTP server bound to this port that streams the camera's
# multipart/x-mixed-replace response straight to the browser. Same trusted-LAN
# threat model as /public/dashboards/ — no auth on the proxy itself.
MJPEG_PROXY_PORT     = 8177
MJPEG_UPSTREAM_TIMEOUT = 8.0

# go2rtc — WebRTC/low-latency video for live.html. The plugin generates a
# config.yaml at startup (RTSP URLs include DAHUA_USER/DAHUA_PASS) and runs
# go2rtc as a subprocess. Bind addresses:
#   :1984 — HTTP API + WebRTC signaling (used by the browser)
#   :8555 — WebRTC media (TCP, served back to the browser)
GO2RTC_BIN           = os.path.expanduser("~/bin/go2rtc")
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

import logging


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


# ============================================================
# Plugin class
# ============================================================

# The plugin's features live in mixin modules beside this file (v3.30.0):
# plugin.py had grown past 9,000 lines. Plugin inherits every method, so each
# is still self.<name>, and Actions.xml still names the same callbacks.
from carbon_mixin import CarbonMixin  # noqa: E402
from dash_util import as_bool01  # noqa: E402
from insights_mixin import InsightsMixin  # noqa: E402
from mains_mixin import MainsMixin  # noqa: E402
from history_mixin import HistoryMixin  # noqa: E402


class Plugin(CarbonMixin, InsightsMixin, MainsMixin, HistoryMixin, indigo.PluginBase):
    cameras       = ()          # the running camera list; __init__ sets it
    swap_out_host = ""

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.timestamp_enabled = as_bool(pluginPrefs.get("timestampEnabled"), True)
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Everything the module log() helper sends to the shared event log is
        # copied into this plugin's own log file too, so one file holds a fault
        # and the routine narration around it. See _install_file_mirror.
        _install_file_mirror(getattr(self, "plugin_file_handler", None))

        # Credentials: IndigoSecrets.py first, PluginConfig fields as the
        # documented fallback — resolved by the ONE helper the menu reload and
        # the Configure save also use (v3.27.0; this block was a second copy).
        # A blank URL means the local server (v2.95.2).
        self._resolve_credentials(pluginPrefs, _sys.modules.get("IndigoSecrets"))
        # Log level (v2.36.0 — the PluginConfig field existed but was never
        # applied). Guarded coerce; bad/blank value falls back to INFO.
        self._apply_log_level(pluginPrefs.get("logLevel", 20))

        # ONE settings store (v3.27.0): dashboards_config.json, written by the
        # Settings page, held in memory as self.cfg_store and read from nowhere
        # else. On the first start without it, the legacy IndigoSecrets
        # DASHBOARDS_* keys and Configure fields are imported into it once.
        # Until then there were two paths, every consumer branched between
        # them, and some re-read the file from disk while others did not.
        self.cfg_store = self._load_config_store()
        if not self.cfg_store:
            self.cfg_store = self._import_legacy_config(pluginPrefs)
        store = self.cfg_store

        # Cameras (plugin state since 3.32.0; a module global before, which
        # every test had to monkeypatch and no mixin could see). This is the
        # RUNNING list: a Settings save changes the store, not this, until
        # the next restart.
        self.cameras = _parse_cameras(store.get("cameras") or [])
        # Default swap-out = last entry in the list (the cam most likely to be
        # safe to drop from the live MJPEG pool), unless Settings names one.
        swap_pref = (store.get("swapOutHost") or "").strip()
        self.swap_out_host = swap_pref if swap_pref else (
            self.cameras[-1]["host"] if self.cameras else "")

        self.main_cameras = list(store.get("mainCameras") or [])
        extras = store.get("roomExtras")
        self.room_extras = extras if isinstance(extras, dict) else {}

        # Guest tier (v2.1.0): read-only token + per-tile PIN policy.
        self.guest_token  = self._load_guest_token()
        self.control_pin  = str(store.get("controlPin") or "")
        self.pin_required = list(store.get("pinRequired") or [])
        # Bootstrap key auto-seed (v2.36.0). Default True = the LAN convenience
        # that seeds the API key to any private-source browser on first visit.
        # A deployment that runs guest-tier devices can set this False to make
        # the guest boundary real — /bootstrap then 403s and trusted devices
        # pair via the one-time setup links (menu: Generate One-Time Setup Link)
        # instead. Default preserves existing behaviour; nobody's setup breaks.
        self.bootstrap_key_seed = as_bool(pluginPrefs.get("bootstrapKeySeed"), True)

        # Routine activity narration (06-09-2026). OFF means the file copies,
        # page syncs and poller/proxy/go2rtc start-stop lines are written at
        # Debug, which normally means this plugin's OWN log only - normally,
        # because the Log Level pref sets the event log's floor and at Debug it
        # lets them through regardless. This checkbox is one of the two
        # switches on them, not the only one; see _apply_log_level. They are
        # the lines that grow: measured over
        # 31-Aug to 05-Sep-2026 the plugin wrote 614 Info lines to the shared
        # Indigo event log and about 490 of them were these, narrating work
        # Indigo already brackets with its own "Starting plugin" / "Stopped
        # plugin" pair. Thirteen is the high mark, not the constant: counted
        # off the dated Events.txt files on 06-09-2026, the six most recent
        # restarts produced 13, 13, 13, 10, 11 and 11 Dashboards Info lines,
        # because several of them (the since-removed Domio copy, the stale-file removal, the
        # go2rtc asset mirror) only speak when they had something to do.
        # Warnings and errors
        # are NEVER routed through this - Log_Error_Watch.py reads the event
        # log and nothing else, so a fault that only lands in a plugin file
        # is a fault nobody is watching.
        self.log_activity = as_bool(pluginPrefs.get("logActivityToEventLog"), False)

        # Favourites (v2.10.0): one-tap device/scene tiles pinned to the top of
        # the hub. Edited in Settings, stored in dashboards_config.json, and
        # published into config.js (just ids + labels — not secret) so the hub
        # reads them straight from window.INDIGO_CONFIG with no extra fetch.
        self.favourites = list(store.get("favourites") or [])

        # Custom links (v2.x): full-size hub tiles that open an arbitrary URL in a
        # new tab — e.g. the MQTT Explorer page, a Grafana board, a router admin
        # page. {title, url, desc?, icon?}. Edited in Settings, stored in
        # dashboards_config.json, published into the public config.js. The URL is
        # NOT secret (just a link); never put a token in it — the target page
        # handles its own auth.
        self.custom_links = list(store.get("customLinks") or [])

        # LAN IP — used by the go2rtc WebRTC config and the startup log line.
        # Detect once at __init__; the hostname doesn't change at runtime.
        self.lan_ip = _detect_lan_ip()


        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    def _secrets_state(self):
        # v1.20.0: the key is no longer published in config.js regardless of
        # where it lives — browsers prompt once and keep it in localStorage.
        # This string is informational only (Show Plugin Info / config.js note).
        if INDIGO_API_KEY:
            return "INDIGO_API_KEY in IndigoSecrets (not published — browser prompts)"
        if CLAUDEBRIDGE_BEARER_TOKEN:
            return "CLAUDEBRIDGE_BEARER_TOKEN in IndigoSecrets (not published — browser prompts)"
        return "no key in IndigoSecrets — browser prompts"

    def _camera_state(self):
        if self.cam_user and self.cam_pass:
            return f"{len(self.cameras)} configured (DAHUA_USER/DAHUA_PASS from IndigoSecrets)"
        return f"{len(self.cameras)} configured but DAHUA_USER/DAHUA_PASS missing"

    # --------------------------------------------------------
    # Config store (v2.0.0) — dashboards_config.json
    # --------------------------------------------------------

    def _guest_token_path(self):
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "guest_token.txt")

    def _load_guest_token(self):
        """Guest token (v2.1.0) — grants READ-ONLY access via the :8177 proxy.
        Auto-generated on first use, persisted in the per-plugin Preferences
        folder (0600), deliberately OUTSIDE dashboards_config.json so creating
        it never flips a legacy install into store mode."""
        path = self._guest_token_path()
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    return tok
        except Exception as exc:
            log(f"[Guest] Could not read guest token ({exc})", level="WARNING")
        tok = _stdlib_secrets.token_urlsafe(18)
        try:
            # Created 0600, no open-then-chmod window (v2.95.2).
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(tok)
            log("[Guest] Generated new guest access token")
        except Exception as exc:
            log(f"[Guest] Could not persist guest token ({exc})", level="WARNING")
        return tok

    def _config_store_path(self):
        """Plugin-owned config file. Lives in the per-plugin Preferences
        folder (NOT /public — no need to publish it), survives upgrades."""
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "dashboards_config.json")

    def _import_legacy_config(self, prefs):
        """Build dashboards_config.json ONCE from the legacy settings (v3.27.0).

        Before this there were two ways to configure the plugin: the Settings
        page, and IndigoSecrets DASHBOARDS_* keys backed by Configure fields.
        Every consumer branched between them. Now the store is the only one:
        on a start with no store, whatever the old sources hold is copied in,
        saved, and used from then on. Editing those keys afterwards changes
        nothing, and the log says so at the import."""
        store = {
            "cameras":      _parse_cameras(DASHBOARDS_CAMERAS or prefs.get("camerasJson", "")),
            "swapOutHost":  (prefs.get("swapOutHost", "") or "").strip(),
            "mainCameras":  list(DASHBOARDS_MAIN_CAMERAS or []),
            "roomExtras":   DASHBOARDS_ROOM_EXTRAS if isinstance(DASHBOARDS_ROOM_EXTRAS, dict) else {},
            "hiddenScenes": sorted(self._parse_hidden(
                DASHBOARDS_HIDDEN_SCENES or prefs.get("hiddenScenesJson", ""))),
        }
        imported = [k for k, v in store.items() if v]
        try:
            store = self._save_config_store(store)
        except Exception as exc:
            log(f"[Config] could not create dashboards_config.json ({exc}) — using the "
                f"imported settings for this run only", level="WARNING")
            return store
        if imported:
            log(f"[Config] imported {', '.join(imported)} from IndigoSecrets / Configure "
                f"into dashboards_config.json. The Settings page owns them from now on; "
                f"the old DASHBOARDS_* keys are no longer read.")
        return store

    def _load_config_store(self):
        """Read dashboards_config.json. Returns {} when absent/invalid, and
        __init__ then imports the legacy settings once."""
        try:
            path = self._config_store_path()
            if not os.path.isfile(path):
                return {}
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            log(f"[Config] Could not read dashboards_config.json ({exc}) — "
                "starting from the legacy settings; fix or delete the file",
                level="WARNING")
            return {}

    def _save_config_store(self, data):
        """Atomically persist the editor's config. Raises on failure.
        Keeps a one-deep .bak of the PREVIOUS good config first, so a bad save
        (e.g. an empty form harvested after a failed load — the settings page
        guards against this client-side too) is always recoverable by hand."""
        path = self._config_store_path()
        try:
            if os.path.isfile(path):
                import shutil
                shutil.copy2(path, path + ".bak")
                os.chmod(path + ".bak", 0o600)
        except Exception as exc:
            log(f"[Config] could not back up dashboards_config.json: {exc}", level="WARNING")
        data = dict(data)
        data["_savedAt"] = time.time()
        tmp  = path + ".tmp"
        # 0600 (v2.95.2): the store carries the control PIN in clear, and it
        # was written under the default umask — 0644, plus every .bak beside it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return data

    def _effective_config(self):
        """The config as currently in force, regardless of where it came
        from — exactly what the settings editor should show."""
        # v3.12.0: cameras and the swap-out host as SAVED, not as running.
        # Module self.cameras / self.swap_out_host only change at restart, so after a
        # save this handed the editor the PRE-save list: reopen Settings, save
        # again, and the camera just added was silently deleted. Once the
        # store is in force it is the truth; the streams catch up at the
        # restart the save reply asks for.
        store = getattr(self, "cfg_store", None) or {}
        if "cameras" in store:
            cams = _parse_cameras(store.get("cameras") or [])
        else:
            cams = [dict(c) for c in self.cameras]
        swap = (store.get("swapOutHost") or "") if "swapOutHost" in store else self.swap_out_host
        out = {
            "cameras":      cams,
            "mainCameras":  list(self.main_cameras),
            "swapOutHost":  swap,
            "roomExtras":   self.room_extras,
            "hiddenScenes": sorted(self._hidden_scenes()),
            "controlPin":   self.control_pin,
            "pinRequired":  list(self.pin_required),
            "favourites":   [dict(f) for f in self.favourites],
            "customLinks":  [dict(l) for l in self.custom_links],
        }
        # Round-trip safety: any stored key this build does not know — the
        # raw-JSON hatch, a newer page, a future version — passes through
        # unchanged. Without this, Settings loads a stripped view and the
        # next Save silently deletes every unknown key (the recurring
        # whitelist trap, this time on the LOAD side).
        try:
            for k, v in store.items():
                if k not in out and not str(k).startswith("_"):
                    out[k] = v
        except Exception:
            pass
        return out

    @staticmethod
    def _redact_pin(cfg):
        """The control PIN never travels to a browser — verifyPin exists so it
        does not have to. The settings editor gets a set/unset flag instead;
        its Save sends blank to KEEP the stored PIN, "clear" to remove it."""
        out = dict(cfg)
        out["controlPinSet"] = bool(out.get("controlPin"))
        out["controlPin"] = ""
        return out

    def _resolve_pin_save(self, incoming):
        if incoming.lower() == "clear":
            return ""
        if incoming == "":
            return getattr(self, "control_pin", "") or ""
        return incoming

    def _public_dashboards_dir(self):
        """Absolute path to Web Assets/public/dashboards/ for the current Indigo
        version. Derived from indigo.server.getInstallFolderPath() so it survives
        Indigo version upgrades without source changes."""
        base = indigo.server.getInstallFolderPath()
        return os.path.join(base, "Web Assets", "public", PUBLIC_SUBDIR)

    def _config_js_path(self):
        return os.path.join(self._public_dashboards_dir(), "config.js")

    def _sync_pages_to_public(self):
        """Mirror every .html file from the plugin bundle into
        Web Assets/public/dashboards/ so IWS serves them without auth.
        Skips files whose mtime/size already match (cheap re-sync on startup).
        Removes stale .html files from the public dir that no longer exist in
        the bundle, so renaming a page also drops the old copy."""
        src = PAGES_SOURCE_DIR
        dst = self._public_dashboards_dir()
        if not os.path.isdir(src):
            log(f"Source pages dir missing: {src}", level="ERROR")
            return 0
        try:
            os.makedirs(dst, exist_ok=True)
        except Exception as exc:
            log(f"Could not create {dst}: {exc}", level="ERROR")
            return 0

        # Copy / update — include HTML pages plus PNG icons (apple-touch-icon)
        # and .js for standalone-nav.js / chart.umd.min.js. `.css` joined the
        # list in v2.51.0 for dashboards-theme.css, which every page <link>s:
        # miss it and the pages load with no palette at all.
        EXT = (".html", ".png", ".js", ".css")
        # NOTE: manifest.json is copied explicitly below (NOT via EXT) so the
        # stale-file scan doesn't see streams.json / rooms.json / config.js
        # (all runtime-generated in this same dir) as "stale" and delete them.
        sources = {f for f in os.listdir(src) if f.endswith(EXT)}
        copied = 0
        for name in sorted(sources):
            sp = os.path.join(src, name)
            dp = os.path.join(dst, name)
            try:
                need = True
                if os.path.exists(dp):
                    ss = os.stat(sp); ds = os.stat(dp)
                    need = (ss.st_size != ds.st_size) or (ss.st_mtime > ds.st_mtime)
                if need:
                    self._copy_atomic(sp, dp)
                    copied += 1
            except Exception as exc:
                log(f"Copy failed for {name}: {exc}", level="ERROR")

        # Drop stale files of the synced extensions. RUNTIME-GENERATED files
        # match the extensions but are written by other parts of the plugin,
        # not mirrored from the bundle — sweeping them deleted config.js and
        # the go2rtc JS assets on EVERY sync, leaving windows where pages 404d
        # until their writers ran again (visible as "Removed stale ..." lines
        # on every restart). go2rtc's two JS files left this list in v3.26.0,
        # so the sweep now clears the copies older versions mirrored.
        _RUNTIME_KEEP = {"config.js"}
        try:
            for name in os.listdir(dst):
                if (name.endswith(EXT) and name not in sources
                        and name not in _RUNTIME_KEEP):
                    try:
                        os.remove(os.path.join(dst, name))
                        self._activity(f"Removed stale {name} from {dst}")
                    except Exception as exc:
                        log(f"Could not remove stale {name}: {exc}", level="WARNING")
        except Exception as exc:
            log(f"Stale scan failed in {dst}: {exc}", level="WARNING")

        # Demo fixtures (v2.3.0): mirror the demo-data/ subdirectory so the
        # local demo (demo.html) works. Additive copy — no stale sweep needed,
        # the fixtures are regenerated wholesale by tools/make_demo_fixtures.py.
        demo_src = os.path.join(src, "demo-data")
        if os.path.isdir(demo_src):
            demo_dst = os.path.join(dst, "demo-data")
            try:
                os.makedirs(demo_dst, exist_ok=True)
                for name in os.listdir(demo_src):
                    if not name.endswith(".json"):
                        continue
                    sp = os.path.join(demo_src, name)
                    dp = os.path.join(demo_dst, name)
                    ss = os.stat(sp)
                    ds = os.stat(dp) if os.path.exists(dp) else None
                    if ds is None or ss.st_size != ds.st_size or ss.st_mtime > ds.st_mtime:
                        self._copy_atomic(sp, dp)
            except Exception as exc:
                log(f"Demo fixtures copy failed: {exc}", level="WARNING")

        # Explicit one-off copy of manifest.json (PWA manifest for iOS
        # standalone navigation). Not part of the general EXT sweep because we
        # don't want the stale-file cleanup above to touch runtime-written
        # JSON files (streams.json, rooms.json).
        mf_src = os.path.join(src, "manifest.json")
        mf_dst = os.path.join(dst, "manifest.json")
        if os.path.isfile(mf_src):
            try:
                ss = os.stat(mf_src)
                ds = os.stat(mf_dst) if os.path.exists(mf_dst) else None
                if ds is None or ss.st_size != ds.st_size or ss.st_mtime > ds.st_mtime:
                    self._copy_atomic(mf_src, mf_dst)
                    self._activity(f"Synced manifest.json to {dst}")
            except Exception as exc:
                log(f"Manifest copy failed: {exc}", level="WARNING")

        self._activity(f"Synced {copied} of {len(sources)} asset(s) to {dst}")
        return copied

    # Script Ticker (v3.31.0): a small plugin that runs the companion scripts
    # on its own. While it is RUNNING Dashboards leaves them to it; the moment
    # it is not (stopped, crashed, never installed) Dashboards runs them
    # itself, so a script is never left unrun and never run by both.
    _TICKER_PLUGIN_ID = "com.clives.indigoplugin.scriptticker"

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

    def _plugin_present(self, plugin_id):
        """Installed AND enabled. Not isRunning(): a plugin mid-restart would
        flip its pages off and on for the seconds it takes, and a crashed one
        stays enabled, so its pages keep their own "unavailable" handling
        rather than vanishing. getPlugin() never raises for an unknown id — it
        reads as not installed, which is the right answer here."""
        try:
            p = indigo.server.getPlugin(plugin_id)
            return bool(p and p.isInstalled() and p.isEnabled())
        except Exception:
            return False

    def _sigen_available(self):
        """Is SigenEnergyManager here? The Energy, Cost and Laundry pages, the
        hub's Energy card, the sigenApi proxy and the laundry scheduler all
        ask this ONE question (v3.13.0)."""
        return self._plugin_present(self._SIGEN_PLUGIN_ID)

    def _feature_flags(self):
        """What config.js publishes about optional plugins, so a page can hide
        what it cannot draw and say why. One builder for the startup write and
        the tick's change check, so the two cannot disagree."""
        return {
            "heatingControls": self._plugin_present(self._EVO_PLUGIN_ID),
            "sigenAvailable":  self._sigen_available(),
        }

    def _refresh_feature_flags(self):
        """Tick task (every 30 s): rewrite config.js when an optional plugin
        has appeared or gone since the last write, so the pages follow an
        install or removal without a restart. Returns True when it rewrote."""
        last = getattr(self, "_config_js_flags", None)
        if last is None:
            return False            # startup has not written config.js yet
        flags = self._feature_flags()
        if flags == last:
            return False
        for key, label in (("sigenAvailable", "SigenEnergyManager"),
                           ("heatingControls", "EvoHomeControl")):
            if flags.get(key) != last.get(key):
                self.logger.info(f"[Config] {label} is now "
                                 f"{'present' if flags.get(key) else 'absent'} — "
                                 f"config.js rewritten so the pages follow")
        self._write_config_js()
        return True

    def _write_config_js(self):
        """Write window.INDIGO_CONFIG and INDIGO_CONFIG_SOURCE to config.js.
        Pages load this (then dashboards-auth.js) before their inline IndigoAPI
        class.
        SECURITY (v1.20.0): the API key is NEVER written here. This file lives
        in Web Assets/public/ which IWS serves with NO authentication — and the
        /public/ namespace is reachable over the Indigo reflector, i.e. from
        the public internet. Only the server baseURL is published; each browser
        is prompted once for the API key by the pages' Connect form and keeps
        it in localStorage (merged in by dashboards-auth.js)."""
        cfg = {}
        if self.api_url:
            cfg = {"baseURL": self.api_url}

        # v2.0.0: auto-discover the Sigenergy inverter device (the one with a
        # batterySoc state) so the hub's energy strip needs no hardcoded ID.
        # Harmless 0 on installs without SigenEnergyManager.
        inv = self._sigen_inverter()
        cfg["sigenDeviceId"] = inv.id if inv is not None else 0
        # PIN policy (v2.1.0): WHICH devices need a PIN is published (harmless
        # id list); the PIN itself never leaves the server — dashboard.js
        # verifies entries via the Bearer-gated verifyPin endpoint.
        cfg["pinRequired"] = list(self.pin_required) if self.control_pin else []
        # Favourites (v2.10.0): one-tap device/scene tiles for the top of the
        # hub. Just {type,id,label} — not secret, safe in the public config.js.
        cfg["favourites"] = [dict(f) for f in self.favourites]
        # Custom links (v2.x): full-size hub tiles opening an arbitrary URL.
        # {title,url,desc?,icon?} — just a link, no secret, safe in config.js.
        cfg["customLinks"] = [dict(l) for l in self.custom_links]
        # Colour presets (v2.94.0): published so the room page draws its preset
        # buttons from the SAME table the applyColour endpoint acts on. The page
        # sends only the preset key, so a preset edited here changes both what
        # the button says and what it does, in one place.
        cfg["colourPresets"] = {k: dict(v) for k, v in COLOUR_PRESETS.items()}
        # v2.96.0: install-specific presentation, all optional, all defaulted
        # so a fresh install reads as "Dashboards" rather than as one house.
        # From memory, not re-read from disk (v3.27.0): the Settings save
        # updates cfg_store, and a hand edit of the file now needs a restart
        # for EVERY setting, rather than for some and not others.
        store = getattr(self, "cfg_store", None) or {}
        cfg["siteName"] = (str(store.get("siteName") or "").strip() or "Dashboards")[:40]
        vehicles = store.get("vehicles")
        cfg["vehicles"] = [
            {"id": int(v["id"]), "label": (str(v.get("label") or "").strip() or "Vehicle")[:40]}
            for v in (vehicles if isinstance(vehicles, list) else [])
            if isinstance(v, dict) and str(v.get("id", "")).lstrip("-").isdigit()]
        # Optional-plugin flags (v3.13.0): heatingControls (the heating page's
        # boost/force panel is wired to EvoHomeControl's action ids) and
        # sigenAvailable (Energy, Cost, Laundry and the hub's Energy card). ONE
        # builder, so the tick can notice a change and rewrite this file.
        flags = self._feature_flags()
        cfg.update(flags)
        self._config_js_flags = dict(flags)
        # Carbon region 0 = "Off (not in Great Britain)": the menu drops the
        # tile and the advisor never calls the GB-only API.
        try:
            cfg["carbon"] = int((getattr(self, "pluginPrefs", None) or {}).get("carbonRegionId", 4) or 4) != 0
        except (TypeError, ValueError):
            cfg["carbon"] = True
        # The LAN origin, for the "you are on the reflector — at home use
        # this" notice (v2.96.1). config.js is what a reflector-origin page
        # has to hand, so this is the one place it can learn the LAN address.
        cfg["lanURL"] = (f"http://{self.lan_ip}:8176" if getattr(self, "lan_ip", "")
                         else (self.api_url or ""))
        # v3.1.0: the pages refuse to render over the reflector when this is on,
        # so a stale tab cannot sit there pulling camera pictures.
        cfg["reflectorBlock"] = self._reflector_blocked()
        # The PWA manifest carries the site name too (home-screen label).
        try:
            mf = os.path.join(self._public_dashboards_dir(), "manifest.json")
            if os.path.isfile(mf):
                with open(mf, encoding="utf-8") as fh:
                    man = json.load(fh)
                if man.get("short_name") != cfg["siteName"]:
                    man["name"] = f"{cfg['siteName']} Dashboard"
                    man["short_name"] = cfg["siteName"]
                    self._write_atomic(mf, json.dumps(man, indent=2).encode("utf-8"))
        except Exception as exc:
            self.logger.debug(f"[Config] manifest name not updated: {exc}")
        # Array rating (v2.72.0): optional `arrayKwp` store key feeding the
        # Ecowitt page's solar-vs-PV cross-check. A number, not a secret —
        # replaces this house's 14.25 that used to be hardcoded in the page.
        try:
            kwp = float(store.get("arrayKwp") or 0)
            if kwp > 0:
                cfg["arrayKwp"] = kwp
        except (TypeError, ValueError):
            pass
        # Action watches (v2.75.0): how the pages confirm that a control button
        # actually DID something, keyed by action-group id. A 200 from Indigo
        # only means the action group was accepted — the garage controller can
        # drop a press on its debounce and still return 200, and the front-door
        # script then blocks for up to 90 s. So the pages watch the contact
        # sensors instead, using declarative rules published here. Device ids
        # and labels only; nothing secret, safe in the public config.js.
        # Read raw from the store: this handler doesn't model the key, and the
        # save path preserves it via the unknown-key pass-through.
        try:
            watches = store.get("actionWatch")
            if isinstance(watches, dict) and watches:
                cfg["actionWatch"] = {str(k): v for k, v in watches.items()}
        except Exception:
            pass

        # Cameras: only publish host list + display names to the browser. The
        # plugin polls each camera itself with Digest auth and writes the JPEGs
        # as static files into the public folder, so credentials never leave
        # the server.
        cam_cfg = {
            "hosts":          [c["host"] for c in self.cameras],
            "names":          {c["host"]: c["name"] for c in self.cameras},
            "slugs":          {c["host"]: self._cam_slug(c["name"]) for c in self.cameras},
            "imagePattern":   "cam-{host}.jpg",            # snapshot fallback
            # The smaller copy the grid uses. Sent as a separate pattern rather
            # than derived on the page so a future change of naming needs one
            # edit here, not one in every page that shows a camera.
            "thumbPattern":   "cam-{host}-thumb.jpg",
            "thumbWidth":     CAMERA_THUMB_WIDTH,
            "pollSeconds":    CAMERA_POLL_SECONDS,
            "mjpegPort":      MJPEG_PROXY_PORT,            # live MJPEG proxy
            "mjpegPath":      "/mjpeg/{host}",             # ?subtype=0 (HD) / 1 (SD)
            "webrtcPath":     "/webrtc/{host}",            # WHEP signalling (same port as mjpegPort)
            "go2rtcPort":     GO2RTC_API_PORT,             # WebRTC backend
            "livePoolSize":   LIVE_POOL_SIZE,              # how many cams run live at once
            "mainCameras":    list(self.main_cameras),     # ordered IPs for the index.html mosaic
            "swapOutHost":    self.swap_out_host,               # bumped to still when peeking a non-default cam
        }

        source = self._secrets_state()
        body = (
            "// Generated by Dashboards plugin at startup. Do not edit by hand.\n"
            "// v1.20.0+: no API key in this file (it is publicly reachable).\n"
            "// Browsers are prompted once for the key and store it locally.\n"
            f"window.INDIGO_CONFIG = {json.dumps(cfg)};\n"
            f"window.INDIGO_CONFIG_SOURCE = {json.dumps(source)};\n"
            f"window.CAMERA_CONFIG = {json.dumps(cam_cfg)};\n"
            # The running version, so a page can SAY which build it is. A phone
            # keeping a home-screen dashboard alive resumes it from memory and
            # never re-fetches, so "have you got the fix yet" was unanswerable
            # from either end. config.js is regenerated every startup, so this
            # cannot go stale while the page is current.
            # v2.66.0: sourced from Info.plist (self.pluginVersion), NOT the
            # PLUGIN_VERSION constant. Indigo reads the plist, so that is the
            # version actually running — and the constant is a hand-maintained
            # copy that has already drifted twice (2.9.0 while the code was on
            # 2.13.0, and 2.65.0 against a 2.65.1 plist). A version display is
            # worse than none if it can lie, and the hub now shows this one.
            f"window.DASHBOARDS_BUILD = {json.dumps(self.pluginVersion)};\n"
        )
        path = self._config_js_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Atomic write (v2.37.0): config.js is the first script every page
            # loads and is rewritten at startup / on every settings save while
            # browsers poll continuously. A plain truncate+write handed a page
            # loading mid-write a truncated file (window.INDIGO_CONFIG undefined
            # → blank dashboard). Every sibling public file already uses this.
            self._write_atomic(path, body.encode("utf-8"))
            self._activity(f"Wrote {path} (configured={bool(cfg)})")
        except Exception as e:
            log(f"Failed to write {path}: {e}", level="ERROR")

    # --------------------------------------------------------
    # MJPEG proxy (tiny HTTP server in a daemon thread)
    # --------------------------------------------------------

    # --------------------------------------------------------
    # WebRTC signalling forward (WHEP) — v2.68.0
    # --------------------------------------------------------
    def _forward_whep(self, slug, body):
        """Forward a WHEP SDP offer to go2rtc's loopback API and return
        (status, content_type, payload_bytes) for the handler to relay.

        Contract verified live against go2rtc 1.9.14 (30-Jul-2026):
        POST /api/webrtc?src=<slug> with Content-Type: application/sdp
        answers 201 Created, application/sdp, SDP answer in the body.
        There is NO /api/whep alias (404). The RAW H.264 slug is used, NOT
        <slug>_mjpeg — WebRTC takes the H.264 straight through with no
        ffmpeg leg, and the answer negotiates H264 payload types.

        This is a SHORT-LIVED request on one of the proxy's per-connection
        threads: go2rtc answers in milliseconds (static candidates, no
        gathering wait), and the MEDIA then flows browser<->go2rtc:8555
        directly — it never transits the plugin process, so unlike /mjpeg
        this holds zero long-lived plugin threads.
        """
        import urllib.request
        import urllib.error
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/webrtc"
               f"?src={_q(slug, safe='')}")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/sdp"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "application/sdp")
                if 200 <= resp.status < 300 and payload:
                    return 200, ctype, payload
                return 502, "text/plain", (
                    f"go2rtc answered {resp.status} with no SDP".encode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = b""
            try:
                detail = exc.read()[:200]
            except Exception:
                pass
            return 502, "text/plain", (
                f"go2rtc {exc.code}: ".encode("utf-8") + detail)
        except TimeoutError:
            return 504, "text/plain", b"go2rtc timed out"
        except Exception as exc:
            if "timed out" in str(exc).lower():
                return 504, "text/plain", b"go2rtc timed out"
            return 502, "text/plain", f"go2rtc unreachable: {exc}".encode("utf-8")

    def _start_mjpeg_proxy(self):
        """Bind a small HTTP server to MJPEG_PROXY_PORT and serve one endpoint
        per camera. Each request opens an upstream MJPEG stream to the camera
        (Digest auth) and pipes the multipart bytes straight to the client.
        Per-request thread because socketserver's ThreadingMixIn handles each
        connection on its own thread — fine for 3 cameras × a few viewers."""
        # v1.20.1: the proxy also serves /bootstrap (LAN/Tailscale-only API-key
        # seed for the dashboard pages), so it now starts even with no cameras
        # configured — camera routes just 404 in that case.
        cameras_enabled = bool(self.cam_user and self.cam_pass and self.cameras)
        if not cameras_enabled and not self.api_key:
            log("[MJPEG] No cameras configured and no API key — proxy disabled",
                level="WARNING")
            self._mjpeg_server = None
            return
        if not cameras_enabled:
            if self.cameras:
                log("[MJPEG] cameras are configured but DAHUA_USER/DAHUA_PASS are not "
                    "set — camera routes disabled, /bootstrap only", level="WARNING")
            else:
                self.logger.info("[MJPEG] no cameras configured — /bootstrap only")

        import http.server
        import ipaddress
        import socketserver
        import threading
        from urllib.parse import urlparse

        # Map host → go2rtc stream slug. The MJPEG proxy targets go2rtc's
        # transcoded-MJPEG endpoint (mainstream H.264 → MJPEG via ffmpeg) so
        # the picture stays sharp regardless of how the camera's own MJPEG
        # substream is configured. Goodbye Garage shimmer.
        host_to_slug  = {c["host"]: self._cam_slug(c["name"]) for c in self.cameras}
        allowed_hosts = set(host_to_slug.keys())
        plugin_self   = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            # Socket timeout (v2.95.2). StreamRequestHandler applies this to
            # the request socket, so a client that connects and never sends a
            # request line, or a viewer whose write side has stalled, is
            # dropped after 30 s instead of pinning a handler thread — and,
            # for /mjpeg, an ffmpeg transcode in go2rtc — for ever. A healthy
            # MJPEG stream writes many times a second, so it never trips.
            timeout = 30

            # Silence default per-request access logging — we'd flood the event log.
            def log_message(self, format, *args):
                pass

            def _client_is_private(self):
                """True only for LAN / Tailscale / loopback sources. This port
                is not fronted by the Indigo reflector and must not be exposed
                through the router, but the explicit source check means a
                mistaken port-forward still doesn't leak the key."""
                try:
                    addr = ipaddress.ip_address(self.client_address[0])
                except Exception:
                    return False
                # is_private covers RFC1918 + loopback + link-local; Tailscale
                # uses CGNAT 100.64.0.0/10 which is NOT is_private, so add it.
                return addr.is_private or addr in ipaddress.ip_network("100.64.0.0/10")

            def _echo_same_host_origin(self):
                """Send Access-Control-Allow-Origin ONLY when the caller's Origin
                is served from THIS SAME MACHINE (same hostname as the request
                Host). Used on responses that carry a token/credential so a
                drive-by page in a LAN/Tailnet browser (different hostname) can't
                read the body cross-origin. Same guard as /bootstrap (v2.35.0);
                extended to /guest-bootstrap + /streams in v2.36.0."""
                from urllib.parse import urlparse as _up
                origin = self.headers.get("Origin", "")
                req_host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0].strip("[]").lower()
                origin_host = (_up(origin).hostname or "").lower() if origin else ""
                if origin and req_host and origin_host == req_host:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")

            # ── WebRTC signalling (WHEP) — v2.68.0 ─────────────────
            # POST /webrtc/<host> forwards the browser's SDP offer to
            # go2rtc's loopback API and relays the answer. Same security
            # model as /mjpeg: private sources only, configured-camera
            # allowlist, port never fronted by the reflector. The answer
            # carries session ICE credentials and the LAN candidate — no
            # camera passwords. Media never touches this process.
            def do_OPTIONS(self):
                # The page origin is :8176, this proxy is :8177, and an
                # application/sdp POST is non-simple — Safari preflights.
                # Without this handler the whole feature dies before the
                # first byte of SDP is sent.
                parsed = urlparse(self.path)
                if parsed.path.startswith("/guest/"):
                    # The guest routes are read with a custom X-Guest-Token
                    # header, which makes every fetch non-simple, so the
                    # browser preflights — and until 2.95.1 this 404'd the
                    # preflight, which meant no browser could use the guest
                    # tier at all. Same-host only, never "*".
                    self.send_response(204)
                    self._echo_same_host_origin()
                    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "X-Guest-Token")
                    self.send_header("Access-Control-Max-Age", "86400")
                    self.end_headers()
                    return
                if not parsed.path.startswith("/webrtc/"):
                    self.send_error(404, "not found")
                    return
                self.send_response(204)
                self._echo_same_host_origin()      # same-host, not "*" (v2.95.1)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()

            def do_POST(self):
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/webrtc/"):
                    self.send_error(404, "not found")
                    return
                if not self._client_is_private():
                    self.send_error(403, "forbidden")
                    return
                host = parsed.path[len("/webrtc/"):]
                if host not in allowed_hosts:
                    self.send_error(403, "host not allowed")
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except (TypeError, ValueError):
                    self.send_error(400, "Content-Length required")
                    return
                # An SDP offer is 2-8 KB; 64 KB is generous. Reject BEFORE
                # reading, so an oversized body cannot be pulled into memory.
                if length <= 0 or length > 65536:
                    self.send_error(400, "body size out of range")
                    return
                body = self.rfile.read(length)
                status, ctype, payload = plugin_self._forward_whep(
                    host_to_slug[host], body)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self._echo_same_host_origin()      # same-host, not "*" (v2.95.1)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                # Routes:
                #   /mjpeg/<host>?subtype=N    → live multipart stream
                #   /bootstrap                 → API-key seed (private sources only)
                #   /healthz                   → "ok"
                parsed = urlparse(self.path)
                if parsed.path == "/healthz":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return

                # ── Guest tier (v2.1.0) — READ-ONLY data path ────────────
                # Guest devices hold only the guest token, never the API key,
                # so there is no control surface on them at all. The proxy
                # fetches from IWS server-side with the real key and pipes the
                # JSON through, keeping the response shape identical to
                # /v2/api so the pages work unchanged. Private sources only;
                # :8177 is never fronted by the reflector.
                if parsed.path == "/guest-bootstrap":
                    if not self._client_is_private():
                        self.send_error(403, "forbidden")
                        return
                    payload = json.dumps({"guestToken": plugin_self.guest_token}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    # v2.36.0 SECURITY: same-host-only CORS (was '*'). The guest
                    # token is a credential — a drive-by LAN/Tailnet page must not
                    # read it cross-origin and then reach the /guest/* read routes.
                    self._echo_same_host_origin()
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    plugin_self.logger.info(
                        f"[Guest] Guest token issued to {self.client_address[0]}")
                    return

                if parsed.path.startswith("/guest/"):
                    from urllib.parse import parse_qs
                    qs = parse_qs(parsed.query or "")
                    supplied = (self.headers.get("X-Guest-Token")
                                or (qs.get("token") or [""])[0] or "")
                    import hmac
                    tok = plugin_self.guest_token or ""
                    if not (self._client_is_private() and tok
                            and hmac.compare_digest(str(supplied).encode("utf-8"),
                                                    str(tok).encode("utf-8"))):   # constant-time (v2.38.0); bytes so non-ASCII cannot raise
                        self.send_error(401, "guest token required")
                        return

                    def _send_json(payload_bytes, status=200):
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        # Same-host CORS (the v2.36.0 rule) — a wildcard let
                        # any website open in the guest's browser read the
                        # guest data cross-origin.
                        self._echo_same_host_origin()
                        self.send_header("Access-Control-Allow-Headers", "X-Guest-Token")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(payload_bytes)))
                        self.end_headers()
                        self.wfile.write(payload_bytes)

                    sub = parsed.path[len("/guest/"):]
                    if sub == "changedSince":
                        # Served straight from the plugin's change ledger —
                        # same payload shape as the IWS changedSince action.
                        try:
                            since = float((qs.get("since") or ["0"])[0])
                        except ValueError:
                            since = 0.0
                        body = plugin_self._changed_since_payload(since)
                        _send_json(json.dumps(body).encode("utf-8"))
                        return

                    if sub == "history":
                        # Read-only history series for guest devices (v2.4.0).
                        # Through the shared pool since v3.27.0: a 30-day chart
                        # is 5-6 s of disk reads, and every guest request used
                        # to pay it afresh. Now repeats within HISTORY_TTL share
                        # one build — with the main pages too — and this thread,
                        # being the proxy's own, can afford to wait for it.
                        flat = {k: (v[0] if v else "") for k, v in qs.items()}
                        state, got = plugin_self._offpath_get(
                            plugin_self._history_key(flat),
                            lambda: plugin_self._history_producer(flat),
                            plugin_self.HISTORY_TTL, wait=plugin_self.GUEST_HISTORY_WAIT)
                        if state == "fresh" and got.get("client_error"):
                            _send_json(json.dumps({"ok": False, "error": got["client_error"]}
                                                  ).encode("utf-8"), status=400)
                        elif state == "fresh":
                            _send_json(json.dumps(got["result"]).encode("utf-8"))
                        elif state == "failed":
                            self.send_error(500, f"history query failed: {got}")
                        else:
                            _send_json(json.dumps({"ok": False, "pending": True,
                                                   "error": "the chart is still being built"}
                                                  ).encode("utf-8"), status=503)
                        return

                    # Read-only passthroughs to IWS (server-side Bearer).
                    iws_path = None
                    if sub == "devices":
                        iws_path = "/v2/api/indigo.devices"
                    elif sub == "variables":
                        iws_path = "/v2/api/indigo.variables"
                    elif sub.startswith("device/"):
                        dev_part = sub[len("device/"):]
                        if dev_part.isdigit():
                            iws_path = f"/v2/api/indigo.devices/{dev_part}"
                    if iws_path is None:
                        self.send_error(404, "unknown guest route")
                        return
                    import urllib.request
                    try:
                        req = urllib.request.Request(
                            f"{plugin_self.api_url}{iws_path}",
                            headers={"Authorization": f"Bearer {plugin_self.api_key}",
                                     "Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=8.0) as r:
                            raw = r.read()
                        # SCRUB before relaying (v2.95.1). The v2 API device
                        # object carries pluginProps / globalProps / ownerProps,
                        # and plugins keep credentials in props — the Email+
                        # SMTP device's serverPassword among them — so the
                        # "read-only, no control surface" guest tier was
                        # handing the household mail password to anyone who
                        # scanned the pairing QR. The pages read names, states
                        # and the class fields only.
                        try:
                            body = plugin_self._guest_scrub(json.loads(raw))
                            _send_json(json.dumps(body).encode("utf-8"))
                        except ValueError:
                            self.send_error(502, "IWS returned non-JSON")
                    except Exception as exc:
                        self.send_error(502, f"IWS fetch failed: {exc}")
                    return

                if parsed.path == "/bootstrap":
                    # One-shot credential seed for dashboards-auth.js: a browser
                    # on the LAN/Tailnet fetches this on first visit, stores the
                    # key in localStorage and never asks again. Anything outside
                    # the private ranges gets a 403 (and can't reach this port
                    # anyway — the reflector only fronts IWS).
                    if not (plugin_self.api_key and self._client_is_private()):
                        self.send_error(403, "forbidden")
                        return
                    # v2.36.0 SECURITY: source-IP alone can't tell a guest-tier
                    # device from a trusted one, so on a LAN any guest device
                    # could self-upgrade by fetching the full key here. When key
                    # auto-seed is turned off, /bootstrap is disabled entirely and
                    # trusted devices pair via the one-time setup links instead —
                    # making the guest boundary real. Default keeps auto-seed on.
                    if not plugin_self.bootstrap_key_seed:
                        self.send_error(403, "key auto-seed disabled — use a setup link")
                        return
                    # SECURITY (confirmed 14-Jul-2026): this response carries the
                    # full Indigo API key, so it must NOT be readable cross-origin.
                    # The old Access-Control-Allow-Origin:* let any website open in
                    # a LAN/Tailnet browser fetch and read the key (the victim
                    # browser is itself on a private IP, so _client_is_private
                    # doesn't help). Echo an allow-origin ONLY when the caller's
                    # Origin is served from THIS SAME MACHINE (same hostname as the
                    # request Host) — that is the legitimate consumer,
                    # dashboards-auth.js on the IWS web port fetching this proxy
                    # cross-port. A drive-by page (evil.com) has a different
                    # hostname, gets no CORS grant, and cannot read the body. A
                    # same-host match would require already serving a page from the
                    # Indigo box itself, i.e. a prior compromise.
                    from urllib.parse import urlparse as _urlparse
                    origin = self.headers.get("Origin", "")
                    req_host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0].strip("[]").lower()
                    origin_host = (_urlparse(origin).hostname or "").lower() if origin else ""
                    payload = json.dumps({"apiKey": plugin_self.api_key}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    if origin and req_host and origin_host == req_host:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    # Once per client address per plugin run. A browser
                    # re-fetches this on every page load, so at INFO it grew
                    # with the number of tabs opened; a NEW address is the
                    # part actually worth a line in the shared log.
                    _ip = self.client_address[0]
                    if plugin_self._note_bootstrap_seed(_ip):
                        plugin_self.logger.info(f"[Bootstrap] API key seeded to {_ip}")
                    else:
                        plugin_self.logger.debug(f"[Bootstrap] API key re-seeded to {_ip}")
                    return

                if not parsed.path.startswith("/mjpeg/"):
                    self.send_error(404, "not found")
                    return
                # Same source rule as every other route on this port
                # (v2.95.1). It was the one route without it — the one
                # carrying the bulkiest private data on the box.
                if not self._client_is_private():
                    self.send_error(403, "forbidden")
                    return

                host = parsed.path[len("/mjpeg/"):]
                if host not in allowed_hosts:
                    self.send_error(403, "host not allowed")
                    return

                slug = host_to_slug[host]
                # All cameras go through go2rtc's ffmpeg-transcoded MJPEG —
                # works the same for Dahua and Hikvision because go2rtc only
                # cares about the RTSP source. Local connection, no auth.
                import requests
                upstream = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/stream.mjpeg"
                            f"?src={slug}_mjpeg")
                auth     = None

                try:
                    r = requests.get(
                        upstream,
                        auth=auth,
                        stream=True,
                        timeout=MJPEG_UPSTREAM_TIMEOUT,
                    )
                except Exception as exc:
                    plugin_self.logger.warning(
                        f"[MJPEG] {host} upstream connect failed: {exc}")
                    self.send_error(502, "upstream connect failed")
                    return

                try:
                    if r.status_code != 200:
                        plugin_self.logger.warning(
                            f"[MJPEG] {host} upstream HTTP {r.status_code}")
                        self.send_error(502, f"upstream {r.status_code}")
                        return

                    ct = r.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=myboundary")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Connection", "close")
                    # CORS: the pages are same-host on another port, and the
                    # cameras page sets crossOrigin="anonymous" on the <img>
                    # so it can copy the last frame to a canvas — which makes
                    # this header load-bearing. Same-host echo, not "*"
                    # (v2.95.1): a wildcard let any page in a LAN browser read
                    # the video cross-origin.
                    self._echo_same_host_origin()
                    self.end_headers()

                    chunks = r.iter_content(chunk_size=16384)
                    while True:
                        try:
                            chunk = next(chunks)
                        except StopIteration:
                            break
                        except Exception as exc:
                            # UPSTREAM died mid-stream (go2rtc restart, camera
                            # drop). Ending quietly beats the per-client
                            # traceback http.server printed when this raised
                            # straight out of do_GET.
                            plugin_self.logger.debug(
                                f"[MJPEG] {host} upstream ended mid-stream: {exc}")
                            break
                        if not chunk:
                            continue
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            # Client disconnected — close the upstream and bail.
                            break
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass

        class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads      = True
            allow_reuse_address = True

        try:
            srv = _Server(("0.0.0.0", MJPEG_PROXY_PORT), _Handler)
        except Exception as exc:
            log(f"[MJPEG] Could not bind :{MJPEG_PROXY_PORT}: {exc}", level="ERROR")
            self._mjpeg_server = None
            return

        self._mjpeg_server = srv
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="MjpegProxy")
        thread.start()
        self._activity(f"[MJPEG] Proxy listening on :{MJPEG_PROXY_PORT}")

    def _stop_mjpeg_proxy(self):
        if getattr(self, "_mjpeg_server", None):
            try:
                self._mjpeg_server.shutdown()
                self._mjpeg_server.server_close()
                self._activity("[MJPEG] Proxy stopped")
            except Exception as exc:
                log(f"[MJPEG] Shutdown error: {exc}", level="WARNING")
            self._mjpeg_server = None

    # --------------------------------------------------------
    # go2rtc lifecycle (WebRTC backend for live.html)
    # --------------------------------------------------------

    def _go2rtc_dir(self):
        """Per-plugin prefs folder. Indigo guarantees this path is writeable
        and survives version upgrades."""
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId, "go2rtc")
        os.makedirs(d, exist_ok=True)
        return d

    def _go2rtc_config_path(self):
        return os.path.join(self._go2rtc_dir(), "go2rtc.yaml")

    def _go2rtc_log_path(self):
        return os.path.join(self._go2rtc_dir(), "go2rtc.log")

    def _write_go2rtc_config(self):
        """Generate go2rtc.yaml from self.cameras + DAHUA_USER/PASS. Each camera
        gets a stream name = sanitised display name; the RTSP URL pulls the
        mainstream so go2rtc can repackage to WebRTC/MSE on demand."""
        import shutil
        from urllib.parse import quote
        user_q = quote(self.cam_user, safe="")
        pass_q = quote(self.cam_pass, safe="")

        # Indigo's plugin host runs with a minimal PATH that excludes Homebrew,
        # so go2rtc would otherwise fail with `exec: "ffmpeg": executable file
        # not found`. Resolve the absolute path here and write it into the yaml.
        ffmpeg_bin = (shutil.which("ffmpeg")
                      or shutil.which("ffmpeg", path="/opt/homebrew/bin:/usr/local/bin")
                      or "")

        lines = [
            "# Generated by Dashboards plugin — do not edit by hand.",
            "",
            "api:",
            # LOOPBACK ONLY, and no wildcard origin. go2rtc's API needs no
            # authentication and /api/streams returns each camera's full RTSP
            # URL — which carries DAHUA_USER:DAHUA_PASS in clear text. Bound to
            # ':1984' it answered every host on the LAN, and `origin: '*'` meant
            # ANY web page open in ANY browser on the network could fetch it
            # cross-origin and read the camera password. Every consumer in this
            # plugin already dials 127.0.0.1, no dashboard page references the
            # port, and live.html — the WebRTC page the wildcard was added for —
            # was retired, so closing this costs nothing. The public view is
            # streams.json, written through _sanitise_streams (v2.35.0), which
            # drops producer URLs; this shuts the door the sanitiser was standing
            # in front of. Live-confirmed exposed before the fix.
            f"  listen: '127.0.0.1:{GO2RTC_API_PORT}'",
            "",
            "rtsp:",
            f"  listen: '127.0.0.1:{GO2RTC_RTSP_PORT}'",   # only go2rtc's own ffmpeg leg dials it (v2.95.2)
            "",
            "webrtc:",
            # UDP AND TCP on the same port (was '/tcp' = TCP-only until
            # v2.68.0). UDP is WebRTC's normal path, it works over the
            # Tailscale subnet route, and iOS Safari's ICE-over-TCP support
            # is doubtful — the away live tile leads with UDP. The port is
            # LAN-bound reachability either way: no port-forward, not
            # fronted by the reflector.
            f"  listen: ':{GO2RTC_WEBRTC_PORT}'",
            "  candidates:",
            f"    - {self.lan_ip}:{GO2RTC_WEBRTC_PORT}",
            # The old 'stun:8555' line is deliberately GONE (v2.68.0): it
            # made go2rtc advertise the WAN address in every SDP answer
            # (live-confirmed 51.x.x.x:8555 in a real answer) — unreachable
            # without a port-forward we refuse to add, so it was pure ICE
            # noise plus a WAN-address leak to every LAN/Tailnet caller.
            "",
            "log:",
            "  level: info",
            # DO NOT add a `time:` key here hoping to date the lines — it does
            # nothing. go2rtc's console writer hardcodes zerolog's TimeFormat to
            # "15:04:05.000" (the literal is in the binary), so `time:` reaches
            # structured output only. MEASURED 13-08-2026 by running go2rtc
            # 1.9.14 twice on throwaway configs on unused ports, identical but
            # for the key: both logged "09:31:35.010", no date either way.
            # Dating is done by _stamp_go2rtc_log() instead.
            #
            # NB the first attempt to test this in place proved NOTHING and
            # nearly shipped as fact: _start_go2rtc calls _write_go2rtc_config,
            # so a hand-patched go2rtc.yaml is REGENERATED before the child
            # starts and the key was gone before go2rtc ever read the file.
            # Test a config change in isolation, not against a file the plugin
            # owns and rewrites.
            "",
        ]
        if ffmpeg_bin:
            lines += [
                "ffmpeg:",
                f"  bin: {ffmpeg_bin}",
                "",
            ]
        else:
            log("[go2rtc] ffmpeg not found on PATH — MJPEG transcode will fail. "
                "Install Homebrew ffmpeg (searched: PATH, /opt/homebrew/bin, /usr/local/bin).",
                level="WARNING")
        lines += ["streams:"]
        # Two streams per camera:
        #   <slug>        = H.264 RTSP source. Mainstream or sub2 per the
        #                   camera's `stream` field in DASHBOARDS_CAMERAS
        #                   (default sub2). Available for direct RTSP
        #                   consumers; not used by the page after retiring
        #                   live.html.
        #   <slug>_mjpeg  = same source transcoded → MJPEG via ffmpeg.
        #                   Consumed by the plugin's MJPEG proxy. With sub2
        #                   as the source the transcode is roughly half the
        #                   CPU of mainstream.
        sub2_count = 0
        main_count = 0
        for cam in self.cameras:
            slug   = self._cam_slug(cam["name"])
            vendor = cam.get("vendor", "dahua")
            stream = cam.get("stream", CAMERA_DEFAULT_STREAM)
            tpl_key = f"rtsp_{stream}"
            v_urls = VENDOR_URLS.get(vendor, VENDOR_URLS["dahua"])
            tpl   = v_urls.get(tpl_key, v_urls["rtsp_main"])
            rtsp  = tpl.format(user=user_q, pwd=pass_q, host=cam["host"])
            lines.append(f"  {slug}: {rtsp}")
            # ffmpeg: source is the named stream <slug>; #video=mjpeg adds an
            # MJPEG re-encode in front of go2rtc's MJPEG consumer.
            lines.append(f"  {slug}_mjpeg: ffmpeg:{slug}#video=mjpeg")
            if stream == "sub2": sub2_count += 1
            else:                main_count += 1

        path = self._go2rtc_config_path()
        # Create 0600 in one step (v2.38.0): this file holds the camera RTSP
        # credentials, and a plain open()+chmod left a brief window where it was
        # world-readable under the default umask.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)        # ensure 0600 even if the file pre-existed
        self._activity(f"[go2rtc] Wrote config {path} ({len(self.cameras)} streams: "
                       f"{main_count} main, {sub2_count} sub2)")
        return path

    @staticmethod
    def _cam_slug(name):
        """Stable stream name for a camera: lowercase, spaces → underscores."""
        return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")

    def _start_go2rtc(self, settle=True):
        """Launch go2rtc as a subprocess. We don't keep stdout in memory —
        it's redirected to a logfile so the event log stays clean.

        settle=False (startup only, v3.23.1) skips the one-second
        exited-immediately check here; the caller runs _go2rtc_settle_check()
        on a background thread instead, so start-up does not wait on it."""
        import urllib.request      # module-local: plugin.py never imports
                                   # urllib at top level, and the orphan guard
                                   # below silently NameError'd without this
                                   # from v2.37.0 until v2.55.0.
        # Intent, kept separately from the process handle (v2.95.1). The
        # supervisor reads "handle is None" as "never started (no cameras)",
        # but every failure path in here ALSO clears the handle — so a
        # supervised restart that failed to bind (port still held for a
        # second after a crash) read as 'never started' and supervision
        # stopped for good. _go2rtc_wanted says whether there is anything to
        # supervise at all; the handle says whether it is currently running.
        self._go2rtc_wanted = False
        if not self.cameras:
            self._go2rtc_proc = None             # nothing to stream: quiet by design
            return
        if not (self.cam_user and self.cam_pass):
            log("[go2rtc] cameras are configured but DAHUA_USER/DAHUA_PASS are not set — "
                "WebRTC backend disabled", level="WARNING")
            self._go2rtc_proc = None
            return
        # Binary resolution: PluginConfig `go2rtcPath` first, then the PATH,
        # then the historical ~/bin/go2rtc — the pinned path was the only
        # option before v2.73.0 and a Homebrew install simply never worked.
        go2rtc_bin = ((self.pluginPrefs.get("go2rtcPath", "") or "").strip()
                      or shutil.which("go2rtc") or GO2RTC_BIN)
        self._go2rtc_bin = go2rtc_bin
        if not os.path.isfile(go2rtc_bin) or not os.access(go2rtc_bin, os.X_OK):
            log(f"[go2rtc] Binary not found or not executable at {go2rtc_bin} — "
                f"live.html will not work. Install: download go2rtc_mac_arm64.zip "
                f"from https://github.com/AlexxIT/go2rtc/releases", level="WARNING")
            self._go2rtc_proc = None
            return

        try:
            cfg = self._write_go2rtc_config()
        except Exception as exc:
            # A config-write failure must cost cameras only, never the whole
            # startup chain — this ran unguarded inside startup() before.
            log(f"[go2rtc] Could not write go2rtc.yaml: {exc} — cameras "
                f"disabled until fixed", level="ERROR")
            self._go2rtc_proc = None
            return
        # Everything a start needs is present from here on, so whatever
        # happens below is a FAILURE to supervise, not an absence to ignore.
        self._go2rtc_wanted = True
        import subprocess
        # Orphan guard (v2.37.0): go2rtc is deliberately detached
        # (start_new_session=True) so it survives a plugin SIGTERM, and only
        # _stop_go2rtc kills it. After an UNCLEAN plugin exit (kill -9, host
        # crash, forced restart) the old instance keeps :1984/:8554/:8555, the
        # new Popen fails to bind and dies into the logfile, and health checks
        # then see the ORPHAN answering on the PREVIOUS config — so camera or
        # credential edits silently never take effect. If anything is already
        # answering on :1984 before we launch, kill our stale go2rtc first.
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{GO2RTC_API_PORT}/api", timeout=1.0) as _r:
                if _r.status == 200:
                    log("[go2rtc] Found an instance already on "
                        f":{GO2RTC_API_PORT} (orphan from an unclean exit) — "
                        "terminating it before starting fresh", level="WARNING")
                    subprocess.run(["/usr/bin/pkill", "-f",
                                    f"{go2rtc_bin} -config {cfg}"],
                                   capture_output=True)
                    time.sleep(0.5)
        except (urllib.error.URLError, OSError, TimeoutError):
            pass   # nothing answering on :1984 — the normal case
        except Exception as exc:
            # Anything else means the GUARD itself is broken, not that the port
            # is free. Swallowing that silently is how this check sat dead from
            # v2.37.0 to v2.55.0 — a missing import raised NameError straight
            # into a bare `except Exception: pass` and looked exactly like the
            # normal case. Never let a failed check pass as a passed check.
            log(f"[go2rtc] orphan check failed to run ({type(exc).__name__}: "
                f"{exc}) — starting anyway, but a stale instance would not "
                f"have been detected", level="WARNING")
        # Augment PATH so go2rtc can find ffmpeg (Indigo's plugin host PATH is
        # minimal and excludes Homebrew). The yaml's `ffmpeg.bin` setting is
        # the primary mechanism; this PATH augmentation is belt-and-braces in
        # case ffmpeg calls out to other tools (e.g. ffprobe) without absolute paths.
        env = os.environ.copy()
        env["PATH"] = (
            "/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:"
            + env.get("PATH", "")
        )
        try:
            # Cap the go2rtc log (v2.38.0): it's append-only across every
            # restart and ffmpeg is chatty, so it grew without bound. Start a
            # fresh file whenever it passes ~5 MB (we only keep it for triage).
            _logp = self._go2rtc_log_path()
            try:
                if os.path.exists(_logp) and os.path.getsize(_logp) > 5 * 1024 * 1024:
                    open(_logp, "wb").close()
            except OSError:
                pass
            # 0600, like go2rtc.yaml beside it (v2.95.1). go2rtc echoes every
            # RTSP source URL — user:password@host — into its log at startup
            # and on each reconnect: 562 copies of the camera password were
            # sitting in a 0644 file that any local account, backup or
            # support paste could read. Created private, and an existing
            # file is healed on every start.
            _old = getattr(self, "_go2rtc_logfile", None)
            if _old is not None:                 # a supervised restart leaked one fd per start
                try:
                    _old.close()
                except Exception:
                    pass
            _fd = os.open(_logp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            log_f = os.fdopen(_fd, "ab", buffering=0)
            try:
                os.chmod(_logp, 0o600)
            except OSError:
                pass
            self._go2rtc_logfile = log_f
            # Force one so a rotated (truncated) file opens dated, and so the
            # very first line after a start can always be placed on a day.
            self._go2rtc_log_day = None
            self._stamp_go2rtc_log(force=True)
            self._go2rtc_proc = subprocess.Popen(
                [go2rtc_bin, "-config", cfg],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,    # so SIGTERM to plugin doesn't auto-kill it; we do that explicitly
            )
            self._activity(f"[go2rtc] Started (pid {self._go2rtc_proc.pid}) - "
                           f"API http://127.0.0.1:{GO2RTC_API_PORT}/ (loopback only)")
            if settle:
                self._go2rtc_settle_check()
        except Exception as exc:
            log(f"[go2rtc] Could not start: {exc}", level="ERROR")
            self._go2rtc_proc = None

    def _stamp_go2rtc_log(self, force=False):
        """Write a dated marker into go2rtc.log when the local date rolls over.

        go2rtc stamps the TIME only and cannot be configured otherwise (see the
        note in the config builder), so a line in a log spanning several days
        cannot be placed on a day. That cost real diagnostic work on 13-08-2026:
        the log held camera failures and there was no way to tell last night's
        from the same failures a week earlier.

        Deliberately markers, NOT a pipe. Reading the child's stdout through a
        pipe to prefix each line would let a stalled reader fill the 64 KB pipe
        buffer and BLOCK go2rtc — trading a logging nicety for a wedged camera
        backend. Appending a line a day to the file the child already holds open
        adds no failure mode at all: both ends append, and a marker that fails to
        write costs nothing.
        """
        try:
            handle = getattr(self, "_go2rtc_logfile", None)
            if handle is None or handle.closed:
                return
            # NB `datetime` here is the CLASS (from datetime import datetime),
            # not the module — datetime.datetime.now() raises AttributeError,
            # which the except below would have swallowed into a marker that
            # silently never appeared.
            today = datetime.now().strftime("%Y-%m-%d %A")
            if not force and today == getattr(self, "_go2rtc_log_day", None):
                return
            handle.write(f"===== {today} — date marker (go2rtc stamps time only) "
                         f"=====\n".encode("utf-8"))
            self._go2rtc_log_day = today
        except Exception:
            # Never let a log cosmetic touch the supervision path it rides on.
            pass

    def _go2rtc_settle_check(self):
        """Catch an immediate bind failure (e.g. a port still held) rather
        than reporting a phantom-healthy start. True if go2rtc is still up
        a second after launch."""
        proc = getattr(self, "_go2rtc_proc", None)
        if proc is None:
            return False
        time.sleep(1.0)
        if getattr(self, "_cam_pool_closed", False):
            return False                 # shutting down: an exit now is ours
        rc = proc.poll()
        if rc is not None:
            log(f"[go2rtc] Exited immediately (code {rc}) — likely a port "
                f"still in use; see {self._go2rtc_log_path()}", level="ERROR")
            if self._go2rtc_proc is proc:  # the supervisor may have moved on
                self._go2rtc_proc = None
            return False
        return True

    def _go2rtc_boot_bg(self):
        """Start-up thread body (v3.23.1): the settle check. A failure is
        logged, never allowed to vanish with the thread. (It also mirrored
        go2rtc's video-rtc.js / video-stream.js into /public until v3.26.0;
        no page has loaded them since live.html was retired.)"""
        try:
            self._go2rtc_settle_check()
        except Exception as exc:
            log(f"[go2rtc] settle check failed: {exc}", level="WARNING")

    def _supervise_go2rtc(self):
        """Restart go2rtc if it died mid-run. Until v2.72.0 a crash killed
        every camera function — snapshots, MJPEG, WebRTC — SILENTLY until a
        manual plugin restart (the only mid-run check was the /streams
        consumer path, which merely errored). Called from the poller's 30 s
        sweep; backoff stops a crash-looping binary from thrashing."""
        proc = getattr(self, "_go2rtc_proc", None)
        if proc is not None and proc.poll() is None:
            # Healthy is the common case, and a healthy go2rtc can run for days
            # (this one had been up since Tuesday), so the date marker has to go
            # here rather than only on the restart path.
            self._stamp_go2rtc_log()
            return                      # healthy
        if proc is None and not getattr(self, "_go2rtc_wanted", False):
            return                      # never started: no cameras, no binary
        # Either the process exited, or a previous start was WANTED and failed
        # (a bind that lost the race with the old instance's port, say) and
        # cleared the handle. Both retry under the same backoff. Until 2.95.1
        # the second case took the 'never started' exit above, so one failed
        # supervised restart switched supervision off for good — every camera
        # function dead until someone restarted the plugin by hand, which is
        # precisely the failure this method exists to remove.
        now = time.time()
        if now < getattr(self, "_go2rtc_retry_at", 0):
            return
        backoff = min(getattr(self, "_go2rtc_backoff", 30), 600)
        self._go2rtc_retry_at = now + backoff
        self._go2rtc_backoff = backoff * 2
        if proc is not None:
            log(f"[go2rtc] process died (exit {proc.returncode}) — restarting "
                f"(retry in {backoff:.0f}s if it dies again)", level="WARNING")
        else:
            log(f"[go2rtc] last start failed — trying again "
                f"(next retry in {backoff:.0f}s if this one fails)", level="WARNING")
        self._go2rtc_proc = None
        try:
            self._start_go2rtc()
            live = getattr(self, "_go2rtc_proc", None)
            if live is not None and live.poll() is None:
                self._go2rtc_backoff = 30           # healthy again — reset
        except Exception as exc:
            log(f"[go2rtc] supervised restart failed: {exc}", level="ERROR")

    def _stop_go2rtc(self):
        proc = getattr(self, "_go2rtc_proc", None)
        if proc:
            try:
                proc.terminate()
                # Short on purpose: this runs inside the plugin's ~20 s
                # polite-quit budget alongside every other stop. go2rtc exits
                # on SIGTERM in well under a second; if it has not gone in 2 s
                # it is not going to, so kill it rather than wait.
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                self._activity(f"[go2rtc] Stopped (pid {proc.pid})")
            except Exception as exc:
                log(f"[go2rtc] Shutdown error: {exc}", level="WARNING")
            self._go2rtc_proc = None
        lf = getattr(self, "_go2rtc_logfile", None)
        if lf:
            try: lf.close()
            except Exception: pass
            self._go2rtc_logfile = None

    # --------------------------------------------------------
    # Camera snapshot poller (background thread via runConcurrentThread)
    # --------------------------------------------------------

    def _cam_jpg_path(self, host):
        return os.path.join(self._public_dashboards_dir(), f"cam-{host}.jpg")

    def _cam_thumb_path(self, host):
        return os.path.join(self._public_dashboards_dir(), f"cam-{host}-thumb.jpg")

    def _make_thumb(self, jpeg_bytes):
        """Shrink a snapshot for the grid. Returns bytes, or None if it cannot.

        None is a perfectly good answer — the page falls back to the full-size
        picture, which is what it used before this existed. That matters because
        Pillow is a declared requirement rather than a guaranteed one: if the
        install failed, or the frame is malformed, the cameras should carry on
        looking exactly as they always did rather than showing nothing.
        """
        if self._thumb_broken:
            return None
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(jpeg_bytes)) as im:
                if im.width <= CAMERA_THUMB_WIDTH:
                    return None                   # already small; no point
                h = max(1, round(im.height * CAMERA_THUMB_WIDTH / im.width))
                im = im.convert("RGB").resize((CAMERA_THUMB_WIDTH, h), Image.BILINEAR)
                out = io.BytesIO()
                im.save(out, format="JPEG", quality=CAMERA_THUMB_QUALITY, optimize=False)
                return out.getvalue()
        except ImportError:
            # Latch it: this cannot fix itself while the plugin is running, and
            # nine failed imports every two seconds is nine log lines a second.
            self._thumb_broken = True
            log("[Cameras] Pillow is not available, so grid thumbnails are off and "
                "the full-size pictures will be used instead. This costs about "
                "three times the data on a slow link. Restart the plugin to let "
                "Indigo install it from requirements.txt.", level="WARNING")
            return None
        except Exception as exc:
            # A single bad frame must not latch the feature off for good.
            now = time.time()
            if (now - self._thumb_last_log) > 300:
                self._thumb_last_log = now
                log(f"[Cameras] Could not shrink a snapshot for the grid: {exc}", level="WARNING")
            return None

    def _snapshot_pool(self):
        """The snapshot fetch pool, created on first use.

        Built lazily rather than in startup() so a camera-less install never
        spawns threads it has no work for, and reused across ticks rather than
        rebuilt — at a 2 s interval a per-tick pool would churn nine threads
        every two seconds for no reason. Returns None once shutdown has begun
        so a tick already in flight stops submitting.
        """
        if getattr(self, "_cam_pool_closed", False):
            return None
        pool = getattr(self, "_cam_pool", None)
        if pool is None:
            from concurrent.futures import ThreadPoolExecutor
            # One worker per camera: they are all blocked on network I/O, so
            # this is wait time overlapped, not CPU contention.
            workers = max(1, min(len(self.cameras) or 1, CAMERA_POLL_MAX_WORKERS))
            pool = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="DashSnap")
            self._cam_pool = pool
            self.logger.debug(f"[Cameras] snapshot pool started ({workers} workers)")
        return pool

    def _stop_snapshot_pool(self):
        """Stop accepting snapshots without waiting for in-flight fetches.

        wait=False, cancel_futures=True: a worker blocked in requests.get()
        against a slow or dead camera would otherwise hold shutdown for its
        full timeout (15 s, plus a retry), and the plugin host has ~20 s in
        total before Indigo force-kills it. Nothing is lost by not waiting —
        the workers are daemon threads, and _write_atomic means a snapshot
        file is either the old one or the new one, never half-written.
        """
        self._cam_pool_closed = True
        pool = getattr(self, "_cam_pool", None)
        if pool is None:
            return
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self._cam_pool = None

    def _fetch_one_snapshot(self, host):
        """Fetch a single JPEG via go2rtc's /api/frame.jpeg endpoint. This
        decodes one frame from the camera's RTSP stream (the same source
        go2rtc uses for the live MJPEG transcode), so any camera that streams
        will also snapshot — even cameras whose own /snapshot.cgi endpoint is
        broken (e.g. the Patio 4K returns HTTP 500 directly). Bonus: removes
        the vendor-specific snapshot URL handling — go2rtc does that work."""
        import requests
        cam  = next((c for c in self.cameras if c["host"] == host), None)
        slug = self._cam_slug((cam or {}).get("name", host))
        url  = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/frame.jpeg"
                f"?src={slug}&width={CAMERA_SNAPSHOT_WIDTH}")

        def attempt():
            try:
                r = requests.get(url, timeout=CAMERA_HTTP_TIMEOUT, stream=False)
                if r.status_code != 200:
                    return False, f"HTTP {r.status_code}"
                ct = r.headers.get("Content-Type", "")
                if "image" not in ct:
                    if not r.content:
                        # go2rtc answers an unreachable camera with an EMPTY
                        # 200 (mjpeg.go logs the dial error and returns
                        # without writing), so this is the camera, not
                        # go2rtc. Say so rather than name a blank header.
                        return False, ("no picture from the camera: go2rtc "
                                       "could not reach it")
                    return False, f"unexpected content-type {ct!r}"
                return True, r.content
            except Exception as exc:
                return False, str(exc)

        ok, payload = attempt()
        if ok:
            return ok, payload

        # ONE retry, after a short pause. go2rtc spawns ffmpeg to rescale each
        # frame and it occasionally exits 69 (EX_UNAVAILABLE), which comes back
        # here as a bare HTTP 500. It is transient: MEASURED over 270 requests,
        # 4 failed and ALL FOUR succeeded on a single retry 250 ms later, with
        # none needing a second. Without the retry each one costs that camera a
        # whole 2 s cycle — its file is simply not rewritten — and puts a
        # warning in the log that reads like a broken camera when nothing is
        # wrong. Retrying is also why the failure rate is not worth chasing
        # further: it is 1.5% of requests and it fixes itself.
        #
        # Deliberately ONE retry, not a loop. If go2rtc is genuinely wedged, a
        # retry loop across nine cameras every two seconds makes it worse, and
        # the caller already backs the camera off after repeated failures.
        time.sleep(CAMERA_RETRY_DELAY)
        ok, retry_payload = attempt()
        if ok:
            return True, retry_payload
        # Report the FIRST error — it is the more informative of the two, and
        # keeps the log message stable for a camera that is really down.
        return False, payload

    def _write_atomic(self, path, data):
        """Write bytes to a temp file then rename — avoids the browser ever
        reading a half-written JPEG. The temp name carries the writing
        thread's id: the stamp thread, the snapshot pool and MainThread all
        use this helper, and two concurrent writers sharing one ".tmp" could
        interleave (open/truncate/replace) into a torn or vanished file."""
        tmp = f"{path}.tmp.{threading.get_ident()}"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    @staticmethod
    def _copy_atomic(src, dst):
        """shutil.copy2 into a directory IWS is serving TRUNCATES the
        destination and then fills it, so a browser that asks for the file
        during that window gets a short read and IWS answers 500.

        That is where the "internal server error for request
        /public/dashboards/standalone-nav.js" lines came from: every one of
        them lands within seconds of a plugin restart, which is exactly when
        the startup sync rewrites all 38 assets under the browser's feet.
        config.js has been written atomically since v2.37.0 for the same
        reason — its comment claimed every sibling did too, and none did.

        Temp file in the SAME directory so os.replace stays on one filesystem
        and is therefore atomic; a reader sees the old file or the new one.
        """
        tmp = dst + ".tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    def _fetch_go2rtc_streams(self):
        """Fetch go2rtc's full /api/streams JSON. Returns parsed dict or None
        if go2rtc is unreachable."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{GO2RTC_API_PORT}/api/streams",
                timeout=2.0) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _write_streams_json(self, streams):
        """Mirror go2rtc /api/streams to Web Assets/public/dashboards/streams.json
        so the cameras page can read it same-origin (port 8176) instead of
        cross-port fetching to 8177. iOS Safari blocks the cross-port fetch
        in some configurations even with CORS headers.
        Adds a _writeTs (Unix epoch, seconds, fractional) so the page can do
        delta math against the actual write time — otherwise the page poll
        cadence and the file write cadence interleave and bandwidth alternates
        between the real value and 0."""
        if streams is None:
            return
        try:
            payload = self._sanitise_streams(streams)
            payload["_writeTs"] = time.time()
            # A deliberately small, credential-free health summary for the
            # anonymous cameras page.  The raw go2rtc map above has already
            # been sanitised; do not add URLs, exception text or client data.
            payload["_cameraHealth"] = self._camera_health_payload(self.cameras, self._cam_state)
            path = os.path.join(self._public_dashboards_dir(), "streams.json")
            self._write_atomic(path, json.dumps(payload).encode("utf-8"))
        except Exception as exc:
            log(f"[Cameras] streams.json write failed: {exc}", level="WARNING")

    # Fields a guest may see on a device or variable object. Everything the
    # pages read (id, name, class, states, on/brightness, timestamps, folder)
    # and nothing a plugin might keep a secret in.
    _GUEST_DROP_KEYS = frozenset({"pluginProps", "globalProps", "ownerProps",
                                  "sharedProps", "description", "configured",
                                  "address"})

    @classmethod
    def _guest_scrub(cls, obj):
        """Strip plugin props (and the other free-text fields) from a v2 API
        payload before it is relayed to a guest-token holder. Works on a
        single object, a list of them, or the {"objects": [...]} envelope,
        and leaves anything else alone."""
        if isinstance(obj, list):
            return [cls._guest_scrub(o) for o in obj]
        if isinstance(obj, dict):
            return {k: (cls._guest_scrub(v) if isinstance(v, (list, dict)) else v)
                    for k, v in obj.items() if k not in cls._GUEST_DROP_KEYS}
        return obj

    @staticmethod
    def _sanitise_streams(streams):
        """Strip producer source URLs before the go2rtc streams map is written
        to the ANONYMOUS /public namespace. An RTSP producer url is
        rtsp://<user>:<pass>@host/... — i.e. the camera admin credentials — and
        /public is served with no auth even over the reflector, so writing them
        there is an internet-readable leak (SECURITY, confirmed 14-Jul-2026;
        same /public-secret class the config.js hardening in v1.20.0 fixed).
        The cameras page only ever reads producers[].bytes_recv + consumers +
        _writeTs, never the url, so dropping every producer 'url' key costs the
        UI nothing."""
        safe = {}
        for name, info in (streams or {}).items():
            if not isinstance(info, dict):
                safe[name] = info
                continue
            entry = {}
            for key, val in info.items():
                if key == "producers" and isinstance(val, list):
                    entry[key] = [
                        {pk: pv for pk, pv in prod.items() if pk != "url"}
                        if isinstance(prod, dict) else prod
                        for prod in val
                    ]
                elif key == "consumers" and isinstance(val, list):
                    # Each consumer entry carries the VIEWER's IP, user agent
                    # and negotiated SDP — none of it needed by the pages
                    # (nothing reads past the count) and none of it belongs in
                    # the anonymous /public namespace.
                    entry["consumers_n"] = len(val)
                else:
                    entry[key] = val
            safe[name] = entry
        return safe

    @staticmethod
    def _camera_health_payload(cameras, states):
        """Return public-safe snapshot health, never upstream error details.

        The UI needs to distinguish a camera that is currently retrying from
        one that has not yet completed its first poll.  Timestamps are useful
        for age display but are not identifying information; URLs, exception
        messages and viewer data remain private.
        """
        out = {}
        for cam in cameras or []:
            host = cam.get("host") if isinstance(cam, dict) else None
            if not host:
                continue
            st = (states or {}).get(host, {})
            fails = max(0, int(st.get("fail_count", 0) or 0))
            last_ok = st.get("last_ok")
            last_failure = st.get("last_failure")
            if last_ok is None and last_failure is None:
                state = "unknown"
            elif fails >= 3:
                state = "offline"
            elif fails:
                state = "retrying"
            else:
                state = "ok"
            out[host] = {
                "state": state,
                "consecutiveFailures": fails,
                "lastOkTs": last_ok,
                "lastFailureTs": last_failure,
            }
        return out

    # --------------------------------------------------------
    # Scenes map (action groups by folder) — v1.21.0
    # --------------------------------------------------------

    def _hidden_scenes(self):
        """The scenes hide-list from the settings store, as a set of strings."""
        return self._parse_hidden((getattr(self, "cfg_store", None) or {}).get("hiddenScenes") or [])

    @staticmethod
    def _parse_hidden(src):
        """A hide-list given as a JSON string or a list -> set of strings."""
        if isinstance(src, str):
            s = src.strip()
            if not s:
                return set()
            try:
                src = json.loads(s)
            except Exception as exc:
                log(f"[Scenes] hide-list is not valid JSON ({exc}) — ignoring",
                    level="WARNING")
                return set()
        try:
            return {str(x) for x in src}
        except Exception:
            return set()

    def _build_scenes_json(self):
        """Write scenes.json — every Indigo action group grouped by its folder,
        minus anything on the hide-list. The scenes page renders this directly;
        execution goes browser → /v2/api/command (indigo.actionGroup.execute)."""
        try:
            hidden = self._hidden_scenes()
            folder_names = {}
            try:
                for f in indigo.actionGroups.folders:
                    folder_names[f.id] = f.name
            except Exception:
                pass
            groups = {}
            for ag in indigo.actionGroups:
                folder = folder_names.get(ag.folderId, "") or "General"
                if (ag.name in hidden or str(ag.id) in hidden
                        or f"folder:{folder}" in hidden):
                    continue
                groups.setdefault(folder, []).append({"id": ag.id, "name": ag.name})
            payload = {
                "folders": [
                    {"name": name,
                     "scenes": sorted(items, key=lambda s: s["name"].lower())}
                    for name, items in sorted(groups.items(), key=lambda kv: kv[0].lower())
                ],
                "_writeTs": time.time(),
            }
            path = os.path.join(self._public_dashboards_dir(), "scenes.json")
            self._write_json_if_changed(path, payload)
        except Exception as exc:
            log(f"[Scenes] scenes.json write failed: {exc}", level="WARNING")

    # --------------------------------------------------------
    # Rooms map (Lights / Motion / Radiators / Windows / Extras)
    # --------------------------------------------------------

    # Which Indigo device folders are surfaced as dashboard rooms. Anything
    # else (ESPHome / MQTT / RAMSES / Z_Not_Used / Server Room / etc.) is
    # ignored except for the radiator-by-name pass below.
    # Overridable via the config store's optional `roomFolders` list (Settings
    # raw-JSON hatch) — the tuple below is the fallback and, being one house's
    # folder names, produces an EMPTY rooms.json on any other install unless
    # overridden. The rooms.json builder reads _room_folders(), not this.
    ROOM_FOLDERS = (
        "Bathroom", "Bedroom 1", "Bedroom 2", "Bedroom 3",
        "Conservatory", "Dining Room", "Drive", "En Suite",
        "Garage", "Garden", "Hall", "Kitchen", "Living Room", "Utility Room",
    )

    # The auto-classified sections of a room, in one place (v3.27.0) — the
    # same six-name tuple used to be written out seven times.
    ROOM_SECTIONS = ("lights", "motion", "radiators", "windows", "sensors", "extras")

    def _room_folders(self):
        try:
            rf = (getattr(self, "cfg_store", None) or {}).get("roomFolders")
            if isinstance(rf, list) and rf:
                return tuple(str(x) for x in rf)
        except Exception:
            pass
        return self.ROOM_FOLDERS
    # Device classification — used by _build_rooms_json. Keep these short
    # and tweak them based on what gets miscategorised in your install.
    _LIGHT_WORDS    = ("light", "lights", "lamp", "lamps", "spot", "spots",
                       "bulb", "led", "strip", "spotlight", "spotlights")
    _MOTION_WORDS   = ("motion", "presence", "occupancy", "pir")
    _OCCUPANCY_TYPES = ("z2mOccupancySensor",)
    _CONTACT_TYPES   = ("z2mContactSensor", "zwContactSensorType")
    # Device types that look like sensors to the framework but are actually
    # input controls (wall remotes, scene buttons). They publish onState
    # transitions on press but aren't continuous-state sensors — they don't
    # belong in Windows & Doors, Motion or any auto-classified section even
    # when their friendly name happens to contain "door" / "window".
    _BUTTON_TYPES    = ("z2mButton",)
    # Devices we always ignore — backend plumbing, not user-facing controls.
    _SKIP_TYPES = (
        "homeKitBridgeDevice",   # HomeKit bridges (1 per room, internal)
        "z2mRepeater",            # Z2M signal repeaters
        "timer",                  # Indigo built-in timers
        "damGroup",               # Device Activity Monitor groups
    )
    # Contact-sensor exclusions by keyword (freezer/fridge aren't windows).
    _SKIP_CONTACT_WORDS = ("freezer", "fridge")
    # Names containing these aren't lights even if they're a DimmerDevice.
    _NOT_LIGHT_WORDS = ("fan",)

    @staticmethod
    def _has_word(name, words):
        toks = set(name.lower().replace("-", " ").split())
        return any(w in toks for w in words)

    def _classify_device(self, dev):
        """Return one of: 'light', 'motion', 'radiator', 'window', 'sensor',
        'extras', None. None means skip entirely (HK bridge etc.). Radiator
        classification is done separately in _build_rooms_json because it
        needs name-prefix matching across all folders, not just room ones."""
        typ = dev.deviceTypeId or ""
        if typ in self._SKIP_TYPES:
            return None
        cls  = dev.__class__.__name__
        name = dev.name or ""
        # Dimmers are lights unless explicitly disallowed (fan etc.)
        if cls == "DimmerDevice" and not self._has_word(name, self._NOT_LIGHT_WORDS):
            return "light"
        # Relay devices need a light keyword in the name to qualify.
        if cls == "RelayDevice" and self._has_word(name, self._LIGHT_WORDS):
            return "light"
        # Motion / presence sensors — also catches Z-Wave occupancy + radars.
        if typ in self._OCCUPANCY_TYPES or self._has_word(name, self._MOTION_WORDS):
            return "motion"
        # Water/leak sensors — binary alert state, sharing the motion-style tile
        # but the renderer auto-switches the label wording to Wet / Dry.
        if self._has_word(name, ("water", "leak")):
            return "motion"
        # Window / door contacts — match by deviceTypeId OR by name keyword so
        # we catch z2mSensor-typed contacts that don't have the explicit
        # z2mContactSensor type. Checked BEFORE the temp+humidity rule because
        # z2m sensor devices frequently expose dummy temperature/humidity
        # states (often 0.0) — a window contact would otherwise be mistaken
        # for an environment sensor.
        #
        # IMPORTANT: gate this on multiple "not a real contact" checks. The
        # name keyword "door"/"window" is necessary but not sufficient —
        # plenty of devices contain those words without being contact
        # sensors:
        #   - Relay/Dimmer outputs (Shelly garage-door relay, virtual
        #     opener) — already classified as light or extras above
        #   - z2mButton wall remotes (e.g. "Hall Garage Door Opener")
        #   - Z-Wave value sensors (zwValueSensorType e.g. "Front Door
        #     Luminance", "Front Door Temperature") — those expose
        #     sensorValue not onState, so onState is null and the page
        #     would render them as permanently "Closed".
        # A genuine contact ALWAYS exposes a boolean onState — that's the
        # tightest filter we have.
        is_output      = cls in ("RelayDevice", "DimmerDevice")
        is_button      = typ in self._BUTTON_TYPES
        supports_onst  = getattr(dev, "supportsOnState", False) is True
        if (not is_output) and (not is_button) and supports_onst \
                and (typ in self._CONTACT_TYPES
                     or self._has_word(name, ("contact", "window", "door"))) \
                and not any(w in name.lower() for w in self._SKIP_CONTACT_WORDS):
            return "window"
        # Continuous-value environment sensors — must have BOTH temperature
        # AND humidity states (the contact check above already filtered out
        # window/door sensors that happen to expose those keys too).
        states = getattr(dev, "states", {}) or {}
        if "temperature" in states and "humidity" in states:
            return "sensor"
        return "extras"

    def _build_rooms_json(self):
        """Walk indigo.devices.folders, classify every device, and write a
        rooms.json file into the dashboards public folder. The page-side
        room.html template reads this to know which device IDs to render in
        each section per room.

        Radiators are special — they live in a single shared "RAMSES" folder
        (Evohome zones) rather than per-room folders. We assign them to the
        room whose name appears as a prefix in the device name (e.g. "Hall
        Bedroom Radiator" → Hall, "Living Room Door Radiator" → Living Room).
        Longest-prefix-wins so "Living Room" beats "Living" if both exist."""
        room_folders = self._room_folders()
        # Build folder_id → room name only for the configured room folders.
        try:
            folder_to_room = {
                f.id: f.name for f in indigo.devices.folders.iter()
                if f.name in room_folders
            }
        except Exception as exc:
            log(f"[Rooms] Folder enumeration failed: {exc}", level="WARNING")
            return

        rooms = {n: {"lights": [], "motion": [], "radiators": [],
                     "windows": [], "sensors": [], "extras": [], "cameras": []}
                 for n in room_folders}
        room_names_sorted = sorted(room_folders, key=len, reverse=True)

        # Cameras that opted into a room get attached here. Each camera dict
        # carries its own host/name/vendor — the room template uses host to
        # build the MJPEG proxy URL and name as the tile label.
        # `room` may be a single string ("Garage") OR a list (["Garage",
        # "Hall"]) so one camera can surface on multiple room pages — useful
        # when a camera is logically attached to one room's hardware but
        # operationally interesting to another (e.g. the Inside Garage cam
        # also lives on Hall because the Hall has the soft garage-door tile).
        for cam in self.cameras:
            r = cam.get("room")
            if isinstance(r, str):
                cam_rooms = [r.strip()] if r.strip() else []
            elif isinstance(r, (list, tuple)):
                cam_rooms = [str(x).strip() for x in r if str(x).strip()]
            else:
                cam_rooms = []
            for room in cam_rooms:
                if room in rooms:
                    rooms[room]["cameras"].append({
                        "host": cam["host"],
                        "name": cam["name"],
                    })

        # Pass 1: radiators by name-prefix (regardless of folder).
        radiator_ids = set()
        for d in indigo.devices.iter():
            if not ("setpointHeat" in d.states or "setpoint" in d.states):
                continue
            for room in room_names_sorted:
                if d.name.startswith(room + " ") or d.name == room:
                    rooms[room]["radiators"].append(d.id)
                    radiator_ids.add(d.id)
                    break

        # Pass 2: classify everything else by folder.
        for d in indigo.devices.iter():
            if d.id in radiator_ids:
                continue
            room = folder_to_room.get(d.folderId)
            if not room:
                continue
            cat = self._classify_device(d)
            if cat is None:
                continue
            key = {"light":  "lights",  "motion":  "motion",
                   "window": "windows", "sensor":  "sensors",
                   "extras": "extras"}[cat]
            rooms[room][key].append(d.id)

        # Sections are sorted ONCE, after the extras merge below (a sort here
        # as well was thrown away by that one until v3.27.0). Cameras keep the
        # order they are listed in Settings: "what I wrote, in that order".

        # Merge per-room extras (DASHBOARDS_ROOM_EXTRAS) into the payload.
        # Order of operations:
        #   1. hideDeviceIds — drop devices from every auto-classified section
        #      (these get rendered as custom widgets, e.g. door contacts feed
        #      the door tile and shouldn't also appear under Windows & Doors)
        #   2. include — add specific device IDs to a named section even when
        #      the auto-classifier doesn't put them there (e.g. a Shelly plug
        #      that's a "charger", or a Z2M button you want surfaced under
        #      Motion to see last-pressed)
        #   3. doors — pass-through to the page template
        # Sort happens AFTER this so manually-included devices land in the
        # right alphabetical position.
        self._merge_room_extras(rooms)

        # Re-sort sections after include-merge so manually-added IDs slot in
        # alphabetically next to the auto-classified ones — UNLESS the room
        # config supplies a `sortOrder` map for that section, in which case
        # the listed IDs land first in the given order and any unlisted IDs
        # fall in alphabetically behind them. Useful when the alphabetical
        # default produces an unintuitive grouping (e.g. Conservatory wants
        # both windows first and then both doors, not Left-Outside-Right-
        # Sliding interleaved).
        extras_cfg = self.room_extras if isinstance(self.room_extras, dict) else {}
        try:
            name_of2 = lambda i: (indigo.devices[i].name or "").lower()
            for room_name, room in rooms.items():
                cfg = extras_cfg.get(room_name)
                if not isinstance(cfg, dict):      # already warned about by the merge
                    cfg = {}
                sort_order = cfg.get("sortOrder") or {}
                for k in self.ROOM_SECTIONS:
                    explicit = sort_order.get(k) if isinstance(sort_order, dict) else None
                    if isinstance(explicit, (list, tuple)) and explicit:
                        # Listed-first (in the given order), then anything
                        # not listed sorted alphabetically by device name.
                        listed = [i for i in explicit if i in room[k]]
                        rest   = sorted(
                            (i for i in room[k] if i not in listed),
                            key=name_of2,
                        )
                        room[k] = listed + rest
                    else:
                        room[k].sort(key=name_of2)
        except Exception:
            pass

        payload = {
            "_writeTs": time.time(),
            "rooms":    rooms,
        }
        try:
            path = os.path.join(self._public_dashboards_dir(), "rooms.json")
            self._write_json_if_changed(path, payload, indent=2)
        except Exception as exc:
            log(f"[Rooms] rooms.json write failed: {exc}", level="WARNING")
        return payload   # also return it so callers (e.g. timeline) can use it


    def _merge_room_extras(self, rooms):
        """Apply each room's roomExtras entry to its record in `rooms`.

        One room at a time (v3.25.0): a single entry of the wrong shape used to
        raise out of the whole build, every 30 s, so rooms.json went stale for
        EVERY room. Now only that room loses its extras, and the log says so."""
        extras_cfg = self.room_extras if isinstance(self.room_extras, dict) else {}
        for room_name, room_data in rooms.items():
            cfg = extras_cfg.get(room_name) or {}
            if not isinstance(cfg, dict):
                self._warn_room_extras(
                    room_name, f"its settings are a {type(cfg).__name__}, not an object")
                continue
            try:
                self._apply_room_extras(room_data, cfg)
            except Exception as exc:
                self._warn_room_extras(room_name, f"{type(exc).__name__}: {exc}")

    def _write_json_if_changed(self, path, payload, indent=None):
        """Write a rebuilt JSON file only when its content moved (v3.27.0).

        rooms.json and scenes.json are rebuilt every 30 s and were rewritten
        every time, because the `_writeTs` stamp inside them always changed.
        Nothing reads that stamp on either file, so it is left out of the
        comparison: the file, and its mtime, now change when the rooms or
        scenes do. A missing file is always written."""
        body = {k: v for k, v in payload.items() if k != "_writeTs"}
        sig = json.dumps(body, sort_keys=True)
        memo = self.__dict__.setdefault("_json_written", {})
        if memo.get(path) == sig and os.path.isfile(path):
            return False
        self._write_atomic(path, json.dumps(payload, indent=indent).encode("utf-8"))
        memo[path] = sig
        return True

    def _warn_room_extras(self, room_name, why):
        """WARN once per room and fault for this plugin run, not every 30 s."""
        seen = self.__dict__.setdefault("_room_extras_warned", set())
        if (room_name, why) in seen:
            return
        seen.add((room_name, why))
        self.logger.warning(
            f"[Rooms] ignoring the extra settings for room '{room_name}': {why}. "
            f"Fix it on the Settings page; the other rooms are unaffected.")

    def _apply_room_extras(self, room_data, cfg):
        """Merge one room's roomExtras entry into its rooms.json record.

        Moved out of _build_rooms_json in v3.25.0 so a fault in one room is
        caught per room. See the order-of-operations note at the call site."""
        # (1) hide
        hide_ids = set(cfg.get("hideDeviceIds") or [])
        if hide_ids:
            for k in self.ROOM_SECTIONS:
                room_data[k] = [i for i in room_data[k] if i not in hide_ids]
        # (2) include — append; dedupe per section; also pull the same
        # ID out of `extras` so it doesn't appear twice when rooms.json
        # is inspected (extras isn't rendered today, but cleaner this way).
        include = cfg.get("include") or {}
        if isinstance(include, dict):
            all_pinned = set()
            for section, ids in include.items():
                if section not in self.ROOM_SECTIONS:
                    continue
                if not isinstance(ids, (list, tuple)):
                    continue
                existing = set(room_data[section])
                for did in ids:
                    if isinstance(did, int) and did not in existing:
                        room_data[section].append(did)
                        existing.add(did)
                        all_pinned.add(did)
            # Drop included IDs from extras unless extras was itself the target.
            if "extras" not in include:
                room_data["extras"] = [i for i in room_data["extras"]
                                       if i not in all_pinned]
        # (2c) appliances — read-only paired tiles (power meter + cycle
        # state virtual) for things like the washing machine / tumble
        # dryer. Pass-through; the room template renders them in a
        # dedicated "Appliances" section.
        appliances = cfg.get("appliances") or []
        if appliances:
            room_data["appliances"] = list(appliances)
        # (2d) tv — list of device IDs that should appear in a "TV"
        # section as toggleable light-style tiles (Sony TV + Sonos
        # speakers in the Living Room). Render uses the same tile shape
        # as lights but lives under its own header with an All On/Off.
        tv_ids = cfg.get("tv") or []
        if isinstance(tv_ids, (list, tuple)) and tv_ids:
            room_data["tv"] = [int(i) for i in tv_ids
                               if isinstance(i, int)]
        # (2e) plugs — mains sockets / smart plugs rendered as toggleable
        # tiles under their own "Plugs & Sockets" header (same tile shape
        # as Lights/TV). A socket is not a light: keeping them separate
        # stops the hub tile counting a garage socket as "1 light on"
        # (CliveS, 13-Jul-2026). Pinned ids are removed from the
        # auto-classified sections so they can't appear twice.
        plug_ids = cfg.get("plugs") or []
        if isinstance(plug_ids, (list, tuple)) and plug_ids:
            plugs_clean = [int(i) for i in plug_ids if isinstance(i, int)]
            if plugs_clean:
                room_data["plugs"] = plugs_clean
                pinned = set(plugs_clean)
                for k in self.ROOM_SECTIONS:
                    room_data[k] = [i for i in room_data[k]
                                    if i not in pinned]
        # (2f) fire — the living room fire, and anything else of that
        # shape: an on/off appliance that is neither a light nor a socket.
        # Same toggleable tile as Lights/TV/Plugs under its own "Fire"
        # header. It is deliberately NOT pinned into `lights`: a fire is
        # not a light, and counting one would put "1 light on" on the hub
        # tile for a lit fire — the same reasoning that gave sockets their
        # own section (CliveS, 13-Jul-2026). Pinned ids are pulled out of
        # the auto-classified sections so they cannot appear twice; the
        # fire lands in `extras` by default, which nothing renders, which
        # is why it was invisible until now.
        fire_ids = cfg.get("fire") or []
        if isinstance(fire_ids, (list, tuple)) and fire_ids:
            fire_clean = [int(i) for i in fire_ids if isinstance(i, int)]
            if fire_clean:
                room_data["fire"] = fire_clean
                pinned = set(fire_clean)
                for k in self.ROOM_SECTIONS:
                    room_data[k] = [i for i in room_data[k]
                                    if i not in pinned]
        # (2g) openLoop — devices whose state is a BELIEF, not a reading.
        # The living room fire is a one-way RF relay: onOffState is only
        # what was last transmitted, so if it is lit from its own handset
        # Indigo still says off. Such a device must not get a vote in any
        # decision DERIVED from state — notably whether the Lights section's
        # bulk button offers "All On" or "All Off" — because one unreadable
        # device would otherwise veto the button the user wanted. It is
        # still COMMANDED with everything else, so an "All Off" reaches it
        # whatever anyone believes. A vote in the command, not in the
        # decision.
        open_loop = cfg.get("openLoop") or []
        if isinstance(open_loop, (list, tuple)) and open_loop:
            clean_ol = [int(i) for i in open_loop if isinstance(i, int)]
            if clean_ol:
                room_data["openLoop"] = clean_ol
        # (2h) mainLight — lights the room's bulk "All On / All Off" must
        # LEAVE ALONE. The room's main light, typically: you want the lamps
        # off in one press without also killing the ceiling light, or on
        # without it blazing.
        #
        # Deliberately NOT pinned out of `lights` the way plugs and fire
        # are: it is still a light, it still renders as its own tile, and
        # it is still switchable on its own. The only thing it is out of is
        # the group. That is the whole distinction — plugs and fire are a
        # different KIND of thing and get their own section, this is the
        # same kind of thing held back from one action.
        main_light = cfg.get("mainLight") or []
        if isinstance(main_light, (list, tuple)) and main_light:
            clean_ml = [int(i) for i in main_light if isinstance(i, int)]
            if clean_ml:
                room_data["mainLight"] = clean_ml
        # (3) doors
        doors = cfg.get("doors") or []
        if doors:
            room_data["doors"] = list(doors)
            # Auto-hide the devices that feed the door tile (relay openers
            # and status contact sensors) so they don't ALSO show up as
            # stray tiles in Lights / Windows & Doors. Saves the user
            # having to repeat those IDs under hideDeviceIds.
            auto_hide = set()
            for d in doors:
                if not isinstance(d, dict):
                    continue
                for rid in (d.get("relayIds") or []):
                    if isinstance(rid, int):
                        auto_hide.add(rid)
                sc = d.get("statusContactId")
                if isinstance(sc, int):
                    auto_hide.add(sc)
            if auto_hide:
                for k in self.ROOM_SECTIONS:
                    room_data[k] = [i for i in room_data[k]
                                    if i not in auto_hide]

    def _snapshot_worker(self, cam):
        """Fetch and store ONE camera's snapshot. Runs on a pool thread.

        Kept deliberately self-contained: it touches only this camera's own
        entry in self._cam_state (pre-created on the caller's thread) and its
        own file, so no two workers can contend for anything.
        """
        host = cam["host"]
        st   = self._cam_state[host]
        try:
            ok, payload = self._fetch_one_snapshot(host)
            now = time.time()
            if ok:
                try:
                    self._write_atomic(self._cam_jpg_path(host), payload)
                    # The grid's smaller copy. Written SECOND and separately so a
                    # resize failure can never cost us the full-size picture,
                    # which is the one thing here that must always be there.
                    thumb = self._make_thumb(payload)
                    if thumb:
                        self._write_atomic(self._cam_thumb_path(host), thumb)
                    st["ok_count"] += 1
                    st["last_ok"] = now
                    if st["fail_count"] >= 3:                 # camera came back
                        log(f"[Cameras] {cam['name']} ({host}) recovered after {st['fail_count']} failures")
                    st["fail_count"] = 0
                except Exception as exc:
                    log(f"[Cameras] Could not write snapshot for {host}: {exc}", level="ERROR")
            else:
                st["fail_count"] += 1
                st["last_failure"] = now
                # Log on 1st failure and then every 60s while it keeps failing.
                if st["fail_count"] == 1 or (now - st["last_log"]) > 60:
                    log(f"[Cameras] {cam['name']} ({host}) snapshot failed: {payload}", level="WARNING")
                    st["last_log"] = now
        finally:
            with self._cam_inflight_lock:
                self._cam_inflight.discard(host)

    def _poll_cameras_once(self):
        """One sweep over every configured camera, live-viewed or not. Logs
        failures throttled (state stored in self._cam_state) so the event log
        doesn't flood when a camera is offline for hours.

        The fetches run CONCURRENTLY. Serially, nine cameras took longer than
        the 2 s poll interval, so passes ran back-to-back and each camera was
        only refreshed every ~4 s (measured: mean 4.1 s over a 30 s window
        across all nine). That is the floor on how fresh a dashboard tile can
        possibly be, and it is most of the "the stills are five to ten seconds
        behind" report — a client polling every 3 s was re-fetching a file that
        only changed every 4 s.

        Fetching is pure network wait, so overlapping it costs nothing and the
        pass takes as long as the SLOWEST camera rather than the sum of all
        nine. A camera already in flight is not re-submitted, so a dead one
        (15 s timeout) delays only itself and can never make passes pile up.
        """
        streams = self._fetch_go2rtc_streams()
        # Mirror the streams JSON for the dashboard bandwidth indicator.
        self._write_streams_json(streams)
        # (rooms.json is rebuilt on the 30 s sweep, not here — rebuilding and
        # rewriting it every 2 s cost a full folder+device enumeration and a
        # disk write per camera tick for a file that changes on renames.)

        pool = self._snapshot_pool()
        if pool is None:                      # shutting down
            return
        for cam in self.cameras:
            host = cam["host"]
            # EVERY camera is snapshotted, including any with a live viewer.
            #
            # This used to skip a camera with an active MJPEG consumer, on the
            # reasoning that whoever was watching the stream did not need the
            # still. That stopped being true the moment off-LAN became
            # all-stills: the live watcher and the still watcher are now
            # usually DIFFERENT PEOPLE. One browser open at home held six
            # streams and froze those six cameras' snapshots for everyone
            # else — measured live at 294-298 s stale on exactly the six
            # hosts that had consumers, while the three without were 0-2 s
            # fresh. That is the "some tiles never update" report.
            #
            # The skip was added in v1.13.x against a real frame.jpeg-vs-ffmpeg
            # race that produced HTTP 500s, but that race was on the `_mjpeg`
            # DERIVED stream. The poller asks the RAW stream now, so it no
            # longer applies: verified with a live consumer attached, six
            # consecutive snapshots returned 200 at the correct 640x360 in
            # 0.16-0.27 s and the live stream was undisturbed. The cost of
            # always snapshotting is one ~25 KB loopback fetch per camera per
            # tick, which is nothing next to a tile that never changes.
            # Pre-create the state entry HERE, on this one thread, so the
            # workers only ever read and mutate an entry that already exists.
            self._cam_state.setdefault(host, {"ok_count": 0, "fail_count": 0, "last_log": 0,
                                               "last_ok": None, "last_failure": None})
            with self._cam_inflight_lock:
                if host in self._cam_inflight:
                    continue                  # previous fetch still running
                self._cam_inflight.add(host)
            try:
                pool.submit(self._snapshot_worker, cam)
            except Exception:
                # Pool refused the work (shutting down) — release the slot so
                # the camera is not left permanently marked in-flight.
                with self._cam_inflight_lock:
                    self._cam_inflight.discard(host)
                if getattr(self, "_cam_pool_closed", False):
                    return                     # shutdown race, not a fault
                raise

    # --------------------------------------------------------
    # Weather card extras (Sunset + OWM forecast → weather.json)
    # --------------------------------------------------------

    _WEATHER_POLL_SECONDS = 60 * 60          # OWM call cadence (free-tier safe)

    def _start_weather_thread(self):
        """Spawn the hourly OWM fetch on its own thread. No-op if either the
        API key OR lat/long is missing — the rest of the Weather card still
        works (the Ecowitt-derived lines render unconditionally), and
        weather.json simply never appears."""
        def _f(v):
            try:
                return float(v) if str(v).strip() != "" else None
            except (TypeError, ValueError):
                return None
        # IndigoSecrets first, PluginConfig fallback — the plugin's own
        # documented credential policy, which this thread alone ignored.
        self._owm_key = OWM_API_KEY or (self.pluginPrefs.get("owmApiKey", "") or "").strip()
        # A secrets value of 0.0 is the TEMPLATE placeholder, not a site in
        # the Gulf of Guinea (v2.95.1): it used to beat the PluginConfig
        # fields for anyone who kept IndigoSecrets_example.py's defaults.
        self._owm_lat = _f(LATITUDE) or _f(self.pluginPrefs.get("siteLatitude"))
        self._owm_lon = _f(LONGITUDE) or _f(self.pluginPrefs.get("siteLongitude"))
        if not (self._owm_key and self._owm_lat is not None and self._owm_lon is not None):
            log("[Weather] Skipping — OWM key / latitude / longitude not set in "
                "IndigoSecrets or PluginConfig; hub Weather card will use Ecowitt only.",
                level="INFO")
            return
        # The thread is handed ITS OWN stop Event (v3.25.0). It used to re-read
        # self._weather_stop on every loop, so a Configure save that swapped in
        # a new Event while a fetch was running left the old thread waiting on
        # the new one — two threads polling OpenWeatherMap until the restart.
        self._weather_thread = threading.Thread(
            target=self._weather_thread_main,
            args=(self._weather_stop,),
            name="dashboards-weather",
            daemon=True,
        )
        self._weather_thread.start()

    def _stop_weather_thread(self):
        if self._weather_stop:
            self._weather_stop.set()
        t = self._weather_thread
        if t and t.is_alive():
            # 1 s, not 3: the thread is a daemon and dies with the process; the
            # join only lets a fetch that is a moment from finishing land.
            t.join(timeout=1.0)

    def _weather_thread_main(self, stop=None):
        """Hit OWM once on entry then every _WEATHER_POLL_SECONDS until stop.
        The stop Event lets us wake up promptly on shutdown rather than
        sleeping out the full hour. `stop` is this thread's own Event, never
        re-read from self, so a replaced Event cannot adopt an old thread."""
        stop = stop or self._weather_stop
        # First fetch is fast — get the page into a useful state on next refresh.
        if stop.is_set():
            return
        self._fetch_and_write_weather()
        while not stop.wait(self._WEATHER_POLL_SECONDS):
            self._fetch_and_write_weather()

    def _fetch_and_write_weather(self):
        """One OWM round-trip → weather.json in the public dir. All exceptions
        swallowed and logged — a failed fetch must not take the thread down."""
        try:
            data = self._fetch_owm_onecall()
            if not data:
                return
            payload = self._build_weather_payload(data)
            path = os.path.join(self._public_dashboards_dir(), "weather.json")
            self._write_atomic(path, json.dumps(payload, indent=2).encode("utf-8"))
        except Exception as exc:
            log(f"[Weather] Fetch failed: {exc}", level="WARNING")

    def _fetch_owm_onecall(self):
        """OpenWeatherMap One Call API 3.0 — current weather + daily forecast
        + sunset/sunrise + UV in a single request. Uses the v3 endpoint
        (1000 calls/day free tier with "One Call by Call" subscription;
        Highsteads' OWM_API_KEY is already provisioned for it because
        EvoHomeControl uses the same endpoint). Returns the parsed dict on
        success, None on any HTTP/JSON failure (the caller logs)."""
        import urllib.request
        import urllib.parse
        params = {
            "lat":     str(self._owm_lat),
            "lon":     str(self._owm_lon),
            "exclude": "minutely,hourly,alerts",
            "appid":   self._owm_key,
            "units":   "metric",
        }
        url = "https://api.openweathermap.org/data/3.0/onecall?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": f"Dashboards/{PLUGIN_VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    log(f"[Weather] OWM HTTP {resp.status}", level="WARNING")
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log(f"[Weather] OWM request error: {exc}", level="WARNING")
            return None

    def _build_weather_payload(self, owm):
        """Pull the slim subset of the OWM response that the hub page needs.
        Keeps the JSON small — the page reads it with cache: no-store every
        render. Fields:
          sunrise/sunset   — today (unix epoch seconds, UTC; page formats to
                             local time using tz_offset).
          today_min/_max   — daily forecast high/low (°C).
          today_summary    — text description, e.g. "Clear Sky".
          today_icon       — OWM icon code (e.g. 01d) for emoji mapping.
          now_uvi          — current UV index (0–11+).
          now_conditions   — current weather description (may differ from
                             today_summary which is the daily aggregate).
          tz_offset        — seconds offset from UTC; used by page for
                             local-time formatting of sunrise/sunset.
        """
        today    = (owm.get("daily") or [{}])[0]
        current  = owm.get("current") or {}
        temp     = today.get("temp") or {}
        d_weather = (today.get("weather") or [{}])[0]
        c_weather = (current.get("weather") or [{}])[0]
        return {
            "_writeTs":       time.time(),
            "sunset":         today.get("sunset")  or current.get("sunset"),
            "sunrise":        today.get("sunrise") or current.get("sunrise"),
            "today_min":      temp.get("min"),
            "today_max":      temp.get("max"),
            "today_summary":  d_weather.get("description", "").title(),
            "today_icon":     d_weather.get("icon", ""),
            "now_uvi":        current.get("uvi"),
            "now_conditions": c_weather.get("description", "").title(),
            "now_icon":       c_weather.get("icon", ""),
            "tz_offset":      owm.get("timezone_offset"),
        }

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

    def runConcurrentThread(self):
        """Main background loop. Indigo calls this once after startup; we keep
        looping until self.stopThread is set during shutdown. self.sleep()
        raises self.StopThread on shutdown — catching it exits cleanly.

        Every task runs in its OWN isolation (v2.95.2). Until then the whole
        tick shared one try/except, so a builder that failed every time (one
        bad roomExtras value in rooms.json, say) threw before the tasks behind
        it and switched off the log watch, the night sweep and the drive
        lights together — with one WARNING and then silence. Now each task
        fails alone, says so once, and says so again when it recovers.
        Builds rooms.json on every cycle regardless of whether cameras are
        configured — the room template needs it even on cam-less installs."""
        failures = self.__dict__.setdefault("_step_failures", {})

        def step(name, fn):
            try:
                fn()
            except self.StopThread:
                raise
            except Exception as exc:            # noqa: BLE001 — one task, not the loop
                n = failures.get(name, 0) + 1
                failures[name] = n
                if n == 1:
                    log(f"[Poller] {name} failed (will keep retrying): {exc}", level="WARNING")
                else:
                    self.logger.debug(f"[Poller] {name} failed x{n}: {exc}")
                return False
            if failures.pop(name, None):
                log(f"[Poller] {name} recovered")
            return True

        cameras_on = bool(self.cam_user and self.cam_pass and self.cameras)
        if cameras_on:
            self._activity(f"[Cameras] Poller started - {len(self.cameras)} camera(s), "
                           f"every {CAMERA_POLL_SECONDS}s")
        elif self.cameras:
            log("[Cameras] cameras are configured but DAHUA_USER/DAHUA_PASS are not set — "
                "snapshot poller idle", level="WARNING")
        else:
            self.logger.info("[Cameras] no cameras configured — camera features off")
        tick = CAMERA_POLL_SECONDS if cameras_on else 30.0
        last = {"link": 0.0, "presence": 0.0, "logwatch": 0.0, "fp300": 0.0, "sweep": 0.0,
                "reflectorbw": 0.0, "laundry": 0.0}
        try:
            # Seed immediately, isolated like everything else (these three used
            # to run bare, so one bad value killed the loop before it began).
            step("rooms.json", self._build_rooms_json)
            step("scenes.json", self._build_scenes_json)
            step("script ticker check", self._note_ticker)
            scripts_here = not getattr(self, "_scripts_elsewhere", False)
            if scripts_here:
                step("presence watch", self._run_presence_watch)
                last["presence"] = time.time()
            # One line for every optional script that is not installed
            # (v2.96.0). Five separate lines used to greet every fresh
            # install, two of them about one house's lighting automations.
            try:
                absent = [v[0] for v in self.COMPANION_SCRIPTS.values()
                          if not os.path.isfile(os.path.join(self._scripts_dir(), v[0]))]
                if absent and scripts_here:
                    self.logger.info(f"[Scripts] optional companion scripts not installed: "
                                     f"{', '.join(absent)} — the dashboards work without them; "
                                     f"see scripts/README.md in the repo if you want any")
            except Exception:
                pass
            while True:
                t0 = time.time()
                if cameras_on:
                    step("camera poll", self._poll_cameras_once)
                if t0 - last["link"] > 30.0:
                    step("rooms.json", self._build_rooms_json)          # folder moves/renames
                    step("scenes.json", self._build_scenes_json)        # action groups change rarely
                    step("setup-link sweep", self._cleanup_setup_links)
                    step("change-ledger prune", self._prune_change_ledger)
                    step("feature flags", self._refresh_feature_flags)   # an optional plugin came or went
                    step("script ticker check", self._note_ticker)       # who runs the companion scripts
                    if cameras_on:
                        step("go2rtc supervisor", self._supervise_go2rtc)   # restart a crashed go2rtc
                    last["link"] = t0
                if not getattr(self, "_scripts_elsewhere", False):
                    # Leaving `last` alone while Script Ticker runs them means
                    # that if it stops, every script is overdue and runs at once.
                    self._tick_companions(step, last, t0)
                dt = time.time() - t0
                self.sleep(max(0.1, tick - dt))
        except self.StopThread:
            self._activity("[Cameras] Poller stopped" if cameras_on else "[Poller] stopped")

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def startup(self):
        self._cam_state    = {}                              # populated by poller
        # Hosts with a snapshot fetch in flight, so a slow camera is
        # never re-submitted and passes cannot pile up on it.
        self._cam_inflight = set()
        self._thumb_broken = False       # latched once Pillow is known missing
        self._thumb_last_log = 0.0       # throttles per-frame resize complaints
        self._cam_inflight_lock = threading.Lock()
        self._cam_pool     = None
        self._cam_pool_closed = False
        self._mjpeg_server = None
        self._go2rtc_proc  = None
        self._weather_stop = threading.Event()
        self._weather_thread = None
        # v2.70.0 liveness stamp — see the STAMP_* constants for why.
        self._stamp_stop       = threading.Event()
        self._stamp_lock       = threading.Lock()
        self._stamp_thread     = None
        self._boot_ts          = time.time()
        self._stamp_last_write = 0.0
        # v1.22.0 delta updates: ledger of device-change timestamps fed by
        # subscribeToChanges, served to the pages via the changedSince
        # endpoint so they refetch only what actually changed.
        self._dev_changes  = {}                              # dev id -> epoch
        self._dev_deleted  = {}                              # dev id -> epoch
        indigo.devices.subscribeToChanges()
        self._sync_pages_to_public()
        # v2.71.0: presence data moved OUT of the anonymous /public namespace
        # (14 nights of bedroom occupancy were internet-readable over the
        # reflector). Sweep the old copy so every install heals on upgrade —
        # the .json extension is deliberately preserved by the page sync's
        # stale sweep, so it needs this explicit removal.
        try:
            _legacy = os.path.join(self._public_dashboards_dir(), "presence.json")
            if os.path.isfile(_legacy):
                os.remove(_legacy)
                self.logger.info("[Presence] removed the pre-v2.71.0 anonymous "
                                 "/public/dashboards/presence.json")
        except OSError as exc:
            self.logger.warning(f"[Presence] could not remove legacy presence.json: {exc}")
        # v3.13.2: the page builder was retired in v2.9.0 and its server side is
        # gone now too. It used to publish an always-empty custom-pages.json (and
        # any saved <slug>.page.json) into /public on every start; take the
        # leftovers out so an anonymous file does not outlive the feature that
        # wrote it. Saved definitions in Preferences are left alone.
        try:
            _dst = self._public_dashboards_dir()
            _stale = [f for f in os.listdir(_dst)
                      if f == "custom-pages.json" or f.endswith(".page.json")]
            for _f in _stale:
                os.remove(os.path.join(_dst, _f))
                self.logger.info(f"[Pages] removed the retired page builder's "
                                 f"/public/dashboards/{_f}")
        except OSError as exc:
            self.logger.warning(f"[Pages] could not remove a retired builder file: {exc}")
        self._write_config_js()
        self._cleanup_setup_links(force_all=True)    # no links survive a restart
        self._start_mjpeg_proxy()
        self._start_go2rtc(settle=False)
        # v3.23.1: go2rtc's one-second exited-immediately check and the JS
        # mirror (which waits for it to bind) were the whole second start-up
        # spent. Nothing else here needs either — only live.html reads the two
        # files, and the previous boot's copies stay in place meanwhile — so
        # both run on this thread and the plugin is ready a second sooner.
        threading.Thread(target=self._go2rtc_boot_bg,
                         name="dashboards-go2rtc-mirror", daemon=True).start()
        self._start_weather_thread()
        self._start_offpath_workers()
        self._start_stamp_thread()
        self.logger.info(self._startup_summary())
        # v3.12.0: tell any MCP server that reads provider manifests that this
        # plugin's tools are ready (it re-reads mcp-manifest.json on receipt).
        # A harmless no-op when nobody subscribes; guarded so it can never
        # affect startup.
        try:
            indigo.server.broadcastToSubscribers("mcp_tools_updated")
        except Exception:
            pass

    def stopConcurrentThread(self):
        # Freeze the stamp at the FIRST sign of a stop — Indigo calls this
        # before it waits out runConcurrentThread and long before shutdown()'s
        # teardown, so gated pages go quiet while the host is still healthy.
        self._freeze_stamp()
        super().stopConcurrentThread()

    def shutdown(self):
        self._freeze_stamp()          # idempotent belt-and-braces
        # Quiesce: stay alive while gated pages notice the sentinel and stop
        # polling — see STAMP_QUIESCE_SECONDS. Must run BEFORE any teardown.
        time.sleep(STAMP_QUIESCE_SECONDS)
        self._stop_stamp_thread()
        # The teardown is BUDGETED, not summed (v2.95.1). go2rtc goes first:
        # a snapshot worker blocked in requests.get() against it fails the
        # instant the loopback listener closes, instead of running out a 15 s
        # timeout (and a retry) while the host waits. The pool is then told
        # not to wait at all — its workers are daemon threads and
        # _write_atomic already guarantees a file is either the old one or the
        # new one — and the remaining joins are each a second or less. Indigo
        # gives a plugin ~20 s to quit politely; before this, one camera
        # offline at the moment of a restart could take teardown past it, the
        # host was force-killed, this function never finished, and go2rtc was
        # left orphaned for the next boot's port-conflict path to hunt.
        self._cam_pool_closed = True
        self._stop_go2rtc()
        self._stop_snapshot_pool()
        self._stop_mjpeg_proxy()
        self._stop_weather_thread()
        # Workers are daemon threads blocked on a queue, so this only has to
        # wake them; each join is capped at a second and the budget above
        # still holds.
        self._stop_offpath_workers()
        # Indigo logs its own "Stopped plugin" line, so this one only ever
        # doubled it up in the shared log.
        self._activity(f"{self.pluginDisplayName} stopped")

    # --------------------------------------------------------
    # Device-change ledger (v1.22.0) — feeds the changedSince endpoint
    # --------------------------------------------------------

    def deviceUpdated(self, orig_dev, new_dev):
        super().deviceUpdated(orig_dev, new_dev)
        if new_dev.pluginId == self.pluginId:   # ignore own device updates (loop guard)
            return
        self._dev_changes[new_dev.id] = time.time()
        self._stamp_note_change()

    def deviceCreated(self, dev):
        super().deviceCreated(dev)
        self._dev_changes[dev.id] = time.time()
        self._stamp_note_change()

    def deviceDeleted(self, dev):
        super().deviceDeleted(dev)
        self._dev_changes.pop(dev.id, None)
        self._dev_deleted[dev.id] = time.time()
        self._stamp_note_change()

    # ── Liveness stamp (v2.70.0) — /public/dashboards/changed.stamp ─────────
    # Written every STAMP_PERIOD_SECONDS by a dedicated daemon thread, plus a
    # throttled leading-edge write from the ledger callbacks so a change never
    # waits the full period to surface. The lock + stop-event ordering below
    # guarantees a late "run" write can never clobber the "stopping" sentinel:
    # every writer takes the lock, and the run-writers re-check the stop event
    # INSIDE it, while _freeze_stamp sets the event before taking the lock.

    def _stamp_path(self):
        return os.path.join(self._public_dashboards_dir(), STAMP_FILENAME)

    def _ledger_hwm(self):
        """Highest change-ledger epoch, 0.0 when the ledger is empty. Not used
        by the client gate today, but in the schema so a future client can
        skip a changedSince call the stamp already answers."""
        hwm = 0.0
        for ts in list(self._dev_changes.values()):
            if ts > hwm:
                hwm = ts
        for ts in list(self._dev_deleted.values()):
            if ts > hwm:
                hwm = ts
        return hwm

    def _write_stamp_locked(self, state):
        """Caller MUST hold self._stamp_lock."""
        payload = {"v": 1, "boot": self._boot_ts, "ts": time.time(),
                   "hwm": self._ledger_hwm(), "state": state}
        self._write_atomic(self._stamp_path(), json.dumps(payload).encode("utf-8"))
        self._stamp_last_write = time.time()

    def _stamp_note_change(self):
        """Leading-edge stamp write from a ledger callback, ≥1 s apart. A stamp
        failure must never break device handling — swallow everything.

        With the stamp thread running, this only WAKES it (v3.27.0): device
        callbacks run on the same single thread as every /message/ handler,
        and a file write there can queue behind the disk while a long history
        query is reading — measured at up to a second. The inline write below
        is the fallback for when the thread is not running."""
        try:
            if self._stamp_stop.is_set():
                return
            wake = self.__dict__.get("_stamp_wake")
            th = getattr(self, "_stamp_thread", None)
            if wake is not None and th is not None and th.is_alive():
                wake.set()
                return
            if time.time() - self._stamp_last_write < STAMP_CHANGE_WRITE_GAP:
                return
            with self._stamp_lock:
                if not self._stamp_stop.is_set():
                    self._write_stamp_locked("run")
        except Exception:
            pass

    def _start_stamp_thread(self):
        self._stamp_wake = threading.Event()     # set by _stamp_note_change
        self._stamp_thread = threading.Thread(
            target=self._stamp_thread_main,
            name="dashboards-stamp",
            daemon=True,
        )
        self._stamp_thread.start()

    def _stamp_thread_main(self):
        while True:
            try:
                with self._stamp_lock:
                    if self._stamp_stop.is_set():
                        return
                    self._write_stamp_locked("run")
            except Exception:
                pass    # e.g. public dir briefly missing — try again next beat
            # The next beat, or sooner when a device changes (v3.27.0) — but
            # never closer than STAMP_CHANGE_WRITE_GAP to the last write.
            wake = self.__dict__.get("_stamp_wake")
            if wake is None:
                if self._stamp_stop.wait(STAMP_PERIOD_SECONDS):
                    return
                continue
            if wake.wait(STAMP_PERIOD_SECONDS):
                wake.clear()
            if self._stamp_stop.is_set():
                return
            gap = STAMP_CHANGE_WRITE_GAP - (time.time() - self._stamp_last_write)
            if gap > 0 and self._stamp_stop.wait(gap):
                return

    def _freeze_stamp(self):
        """Write the "stopping" sentinel and bar every further "run" write.
        Idempotent; called from stopConcurrentThread AND shutdown."""
        try:
            self._stamp_stop.set()
            wake = self.__dict__.get("_stamp_wake")
            if wake is not None:
                wake.set()               # a thread parked on it must see the stop
            with self._stamp_lock:
                self._write_stamp_locked("stopping")
        except Exception:
            pass

    def _stop_stamp_thread(self):
        self._stamp_stop.set()
        t = self._stamp_thread
        if t and t.is_alive():
            t.join(timeout=1.0)

    def handleChangedSince(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/changedSince/
        Body: {"since": <server epoch float>}  (Bearer-authenticated by IWS)
        Returns the device IDs that changed/were deleted after `since`, plus
        the current server clock for the next poll. Tells the client to do a
        full refetch when `since` is missing/stale or the change set is large."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        try:
            since = float(payload.get("since") or 0)
        except (TypeError, ValueError):
            return self._evo_reply({"ok": False, "error": "since must be a number"}, status=400)
        payload = self._changed_since_payload(since)
        if self._note_reflector_use(action):
            payload["via"] = "reflector"       # the pages slow down on this even when the address lies
        return self._evo_reply(payload)

    # The ledger policy lives ONCE (v2.95.1). It used to be copied into the
    # guest route on :8177, so a change to one copy would have quietly given
    # the guest tablet a different idea of "stale" from the main pages.
    CHANGED_SINCE_STALE_S = 600      # older than this: the client refetches all
    CHANGED_SINCE_MAX_IDS = 40       # more than this: cheaper to refetch all

    REFLECTOR_WARN_S = 3600     # one line per device per hour, no more

    def _reflector_blocked(self):
        """True when the user has asked for the reflector to be refused.

        Off by default: plenty of installs have no other way in from outside,
        and silently breaking them would be worse than the bandwidth. CliveS
        turned it on here after Indigo Domotics wrote twice about this server's
        usage and Tailscale replaced the reflector for every away-from-home
        case (v3.1.0)."""
        prefs = getattr(self, "pluginPrefs", None) or {}
        return as_bool(prefs.get("reflectorBlock"), False)

    def _request_body(self, action, refuse_reflector=True):
        """(payload, None) for a request to act on, or (None, reply) to send back.

        The one place for what every browser-facing handler does first (v3.25.0):
        refuse the reflector when the owner has asked for that, parse the body,
        and insist it is a JSON OBJECT. Half the handlers had drifted from this.
        Eleven never refused the reflector at all, although the docstring below
        said every handler did, and four read the body with .get() outside their
        try, so a JSON list raised AttributeError and IWS answered 500, which
        Log_Error_Watch then counted as a server fault.
        """
        if refuse_reflector:
            refused = self._refuse_reflector(action)
            if refused:
                return None, refused
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return None, self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return None, self._evo_reply(
                {"ok": False, "error": "body must be a JSON object"}, status=400)
        return payload, None

    def _refuse_reflector(self, action):
        """A 403 reply when this request came through the reflector and the
        user has asked for that to be refused — otherwise None (v3.1.0).

        Every browser-facing handler starts with this (through _request_body,
        or directly when it takes no body), so no dashboard data of any kind
        crosses the reflector: not devices, not history, not the Sigen feed.
        tests/test_reflector_guard.py holds every handler to it.
        The reply names the way in that does work, because a bare 403 on a
        phone tells the owner nothing about what to do next.
        """
        if not self._reflector_blocked():
            return None
        if not self._note_reflector_use(action):
            return None
        lan = (f"http://{self.lan_ip}:8176{INDEX_PATH}" if getattr(self, "lan_ip", "")
               else self._dashboard_url())
        return self._evo_reply({
            "ok": False,
            "error": "the dashboards are not served over the Indigo reflector",
            "reason": "reflector_blocked",
            "lanURL": lan,
        }, status=403)

    def _note_reflector_use(self, action):
        """True when this /message/ request arrived through the Indigo
        reflector, and WARN once an hour per device when it did (v2.96.1).

        Indigo Domotics wrote on 02-Sep-2026: the reflector was carrying "a
        lot of bandwidth". The address it saw was this house's own line — a
        device on the home wi-fi had been paired with the reflector address
        and every camera still it asked for went out to Indigo's servers and
        back. IWS logs nothing for /public files or authenticated calls, so
        nothing on the server could say which device. The request headers
        can: the reflector forwards the caller's address, and the browser
        names itself. The log line names both and gives the LAN address."""
        try:
            hdrs = dict(getattr(action, "props", {}).get("headers") or {})
            hdrs = {str(k).lower(): str(v) for k, v in hdrs.items()}
        except Exception:
            return False
        if not getattr(self, "_hdr_keys_logged", False):
            self._hdr_keys_logged = True
            self.logger.debug(f"[Reflector] first /message request headers: {sorted(hdrs)}")
        xff  = (hdrs.get("x-forwarded-for") or hdrs.get("x-real-ip") or "").split(",")[0].strip()
        host = (hdrs.get("host") or "").strip("[]").rsplit(":", 1)[0].lower()
        refl = getattr(self, "_reflector_host", None)
        if refl is None:
            try:
                url  = str(indigo.server.getReflectorURL() or "")
                refl = url.split("//", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].lower()
            except Exception:
                refl = ""
            self._reflector_host = refl
        via = bool(xff) or (bool(refl) and host == refl)
        if not via:
            return False
        ua   = hdrs.get("user-agent", "")[:120]
        key  = (xff, ua)
        now  = time.time()
        seen = getattr(self, "_reflector_seen", None)
        if seen is None:
            seen = self._reflector_seen = {}
        if now - seen.get(key, 0.0) >= self.REFLECTOR_WARN_S:
            seen[key] = now
            lan = (f"http://{self.lan_ip}:8176{INDEX_PATH}" if getattr(self, "lan_ip", "")
                   else self._dashboard_url())
            self.logger.warning(
                f"[Reflector] The dashboards are being used through the Indigo reflector "
                f"from {xff or host} ({ua or 'unknown browser'}). If that device is at home, "
                f"open them on {lan} instead — every byte through the reflector is carried "
                f"by Indigo's own servers.")
        return True

    def _changed_since_payload(self, since, now=None):
        """The changedSince reply for a client whose last poll was at `since`
        (server epoch). Full refetch when the client is new, stale, or the
        change set is large; else the changed + deleted ids since then."""
        now = time.time() if now is None else now
        if since <= 0 or (now - since) > self.CHANGED_SINCE_STALE_S:
            return {"ok": True, "now": now, "full": True}
        # list() snapshots guard against concurrent ledger writes mid-iteration.
        changed = [i for i, ts in list(self._dev_changes.items()) if ts > since]
        deleted = [i for i, ts in list(self._dev_deleted.items()) if ts > since]
        if len(changed) > self.CHANGED_SINCE_MAX_IDS:
            return {"ok": True, "now": now, "full": True}
        return {"ok": True, "now": now, "changed": changed, "deleted": deleted}

    def menuTestHistory(self, valuesDict=None, typeId=None):
        """Check the configured SQL Logger backend and report what it found.

        Dumps the full banner first so a forum post carries the environment and
        the test result in one paste — the convention for every diagnostic
        menu item.
        """
        self.showPluginInfo()
        try:
            hist = self._history()
        except Exception as exc:
            self.logger.error(f"History test FAILED — {exc}")
            return
        ok, detail = hist.check()
        if not ok:
            self.logger.error(f"History test FAILED ({hist.backend}) — {detail}")
            return
        self.logger.info(f"History test PASSED — {detail}")
        try:
            with hist.connect() as conn:
                ids = hist.device_tables(conn)
                self.logger.info(f"  {len(ids)} device(s) have recorded history")
                dropped = shown = 0
                for dev_id in ids:
                    real = len(hist.columns(conn, dev_id))
                    allc = len(hist.columns(conn, dev_id, include_artefacts=True))
                    shown += real
                    dropped += (allc - real)
                self.logger.info(f"  {shown} real state column(s) offered for charting")
                if dropped:
                    self.logger.info(
                        f"  {dropped} SQL Logger artefact column(s) hidden — "
                        f"type-change leftovers the logger cannot remove itself")
        except Exception as exc:
            self.logger.warning(f"History test connected but could not enumerate: {exc}")

    def _setup_checks(self):
        """Every check Test Dashboards Setup performs, as (label, ok, detail,
        optional) tuples, in the order the menu prints them. The menu item logs
        them; the run_setup_check MCP tool (v3.12.0) returns them as data. One
        builder, so the two can never report different verdicts."""
        checks = []

        def chk(label, ok, detail="", optional=False):
            # optional=True: reported as SKIP at INFO and left out of the tally.
            # Five missing optional scripts used to print five red FAIL lines
            # on a brand-new, perfectly healthy install.
            checks.append((label, bool(ok), detail, optional))

        chk("Config source", True, "dashboards_config.json (the Settings page)")
        chk("Indigo API URL", self.api_url, self.api_url or "not set — pages need it")
        chk("API key", self.api_key,
            "present" if self.api_key else "missing — pages cannot authenticate")
        pub = self._public_dashboards_dir()
        chk("Public pages dir writable", os.path.isdir(pub) and os.access(pub, os.W_OK), pub)
        chk("config.js written", os.path.isfile(self._config_js_path()))
        try:
            fresh = (os.path.isfile(self._stamp_path())
                     and time.time() - os.path.getmtime(self._stamp_path()) < 10)
        except OSError:
            fresh = False
        chk("Liveness stamp beating", fresh,
            "" if fresh else "stale/missing — restart gating will not work")
        chk("Cameras configured", True, f"{len(self.cameras)} camera(s)")
        if self.cameras:
            proc = getattr(self, "_go2rtc_proc", None)
            chk("go2rtc running", proc is not None and proc.poll() is None,
                getattr(self, "_go2rtc_bin", GO2RTC_BIN))
            chk("Camera credentials", self.cam_user and self.cam_pass,
                "" if (self.cam_user and self.cam_pass) else "DAHUA_USER/DAHUA_PASS not set")
            ff = shutil.which("ffmpeg") or next((c for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
                                                 if os.path.exists(c)), None)
            chk("ffmpeg found", bool(ff), ff or "brew install ffmpeg — go2rtc needs it to transcode")
        # Rooms: the one thing a fresh install most often gets wrong, silently.
        try:
            names = list(self._room_folders())
            existing = {f.name for f in indigo.devices.folders}
            hit = [n for n in names if n in existing]
            chk("Room folders", bool(hit),
                f"{len(hit)} of {len(names)} configured folder names exist in Indigo"
                + ("" if hit else " — tick your room folders on the Settings page (Rooms card)"))
        except Exception as exc:
            chk("Room folders", False, f"could not read device folders: {exc}")
        sem = self._sigen_available()
        chk("SigenEnergyManager", sem,
            "present — the Energy, Cost and Laundry pages are shown" if sem
            else "not installed — the Energy, Cost and Laundry pages hide themselves",
            optional=True)
        db = self._history_db_path()
        chk("SQL Logger history", os.path.isfile(db),
            db if os.path.isfile(db) else "not found — Graphs, Timeline and Insights need the SQL Logger plugin",
            optional=True)
        ticker = self._ticker_running()
        chk("Script Ticker", ticker,
            "running — it runs the companion scripts, so Dashboards does not" if ticker
            else "not running — Dashboards runs the companion scripts itself",
            optional=True)
        scripts_dir = self._scripts_dir()
        for name in (v[0] for v in self.COMPANION_SCRIPTS.values()):
            chk(name, os.path.isfile(os.path.join(scripts_dir, name)),
                "optional companion script — repo scripts/ folder", optional=True)
        return checks

    def menuTestSetup(self, valuesDict=None, typeId=None):
        """Menu: one PASS/FAIL sweep of everything a stuck install needs
        checked — the single log dump a support post wants. Banner first (the
        estate convention for diagnostic menus)."""
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion)
        checks = self._setup_checks()
        fails = counted = 0
        for label, ok, detail, optional in checks:
            if optional and not ok:
                line = f"[Setup] SKIP — {label}"
            else:
                counted += 1
                fails += 0 if ok else 1
                line = f"[Setup] {'PASS' if ok else 'FAIL'} — {label}"
            if detail:
                line += f" ({detail})"
            (self.logger.error if (not ok and not optional) else self.logger.info)(line)
        self.logger.info(f"[Setup] {counted - fails} of {counted} checks passed"
                         + (f", {len(checks) - counted} optional item(s) skipped" if len(checks) != counted else ""))
        return True

    def showPluginInfo(self, valuesDict=None, typeId=None):
        extras = [
            ("Dashboards URL:",    self._dashboard_url()),
            ("Indigo URL:",        self.api_url or "(unset)"),
            ("API key source:",    self._secrets_state()),
            ("Cameras:",           self._camera_state()),
            ("History backend:",   str((self.pluginPrefs or {}).get("historyBackend") or "sqlite")),
            ("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"),
        ]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")
            for label, value in extras:
                indigo.server.log(f"  {label} {value}")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        # pluginPrefs only flush to disk on a CLEAN shutdown — without an
        # explicit save the toggle is lost on any crash or force-quit.
        try:
            self.savePluginPrefs()
        except Exception:
            pass
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")

    # --------------------------------------------------------
    # Menu callbacks
    # --------------------------------------------------------

    def _dashboard_url(self):
        """The dashboard hub URL. The `?api-key=` form was removed in v2.38.0
        and the branch that built it went in v2.95.2 — the pages seed their
        key from the :8177 bootstrap or a setup link, never from a URL that
        ends up in browser history and server logs."""
        base = self.api_url or "http://localhost:8176"
        return f"{base}{INDEX_PATH}"

    def menuOpenDashboards(self, valuesDict=None, typeId=None):
        """Menu: open the dashboards hub in the default browser.

        Note: this opens the browser on the Indigo SERVER. If the Indigo
        client is running on a different Mac, the dashboard appears on the
        server's screen, not the client's. The URL (without api-key) is also
        logged so it can be clicked from the event log on any client.
        """
        # v2.38.0: open WITHOUT the key in the query string (it would land in
        # the server browser's history/logs). The server Mac is on the LAN, so
        # dashboards-auth.js seeds the key from :8177/bootstrap on first load
        # (or, if key auto-seed is disabled, the Connect form prompts once).
        url_log = self._dashboard_url()
        log(f"[Menu] Dashboards: {url_log}")
        try:
            import webbrowser
            opened = webbrowser.open(url_log, new=2)
            if not opened:
                log("[Menu] Could not auto-open browser — open the URL above manually",
                    level="WARNING")
        except Exception as exc:
            log(f"[Menu] Browser launch failed ({exc}) — open the URL above manually",
                level="WARNING")
        return True

    # -----------------------------------------------------------------------
    # EvoHome proxy — hidden HTTP endpoint for the heating dashboard
    # -----------------------------------------------------------------------

    _EVO_PLUGIN_ID      = "com.clives.indigoplugin.evohomecontrol"
    _EVO_ALLOWED_ACTIONS = frozenset({
        "startTimedBoost1h",
        "startTimedBoost2h",
        "cancelTimedBoost",
        "forceHeatingOn24h",
        "cancelForcedHeating",
        "showSummerStatus",
    })

    def handleEvoHomeAction(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/evoHomeAction/
        Body: {"action_id": "<actionId>"}
        Validates the action ID against an allowlist, then delegates to the
        EvoHome Heating Controller plugin via executeAction().
        """
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        action_id = str(payload.get("action_id") or "").strip()

        if action_id not in self._EVO_ALLOWED_ACTIONS:
            return self._evo_reply(
                {"ok": False, "error": f"unknown action: {action_id!r}",
                 "allowed": sorted(self._EVO_ALLOWED_ACTIONS)},
                status=400,
            )

        evo = indigo.server.getPlugin(self._EVO_PLUGIN_ID)
        # isRunning, not isEnabled (v2.95.2): an enabled-but-crashed plugin
        # reads enabled, and executeAction on a stopped host does not raise,
        # so a boost press logged 'triggered' and nothing happened.
        if not evo or not evo.isInstalled() or not evo.isRunning():
            return self._evo_reply(
                {"ok": False, "error": "EvoHome plugin not running"}, status=503
            )

        try:
            evo.executeAction(action_id)
        except Exception as exc:
            self.logger.error(f"[EvoHome proxy] executeAction({action_id!r}) failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

        self.logger.info(f"[EvoHome proxy] {action_id} triggered via dashboard")
        return self._evo_reply({"ok": True, "action": action_id})

    @staticmethod
    def _evo_reply(obj, status=200):
        return {
            "status":  status,
            "headers": {
                "Content-Type":  "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            "content": json.dumps(obj),
        }

    # -----------------------------------------------------------------------
    # Sigenergy data proxy — reflector-reachable, login-gated access to the
    # SigenEnergyManager :8179 data API, so the energy/power-flow page works
    # away from home too (not just on the LAN). The browser hits IWS (reflector)
    # → this handler → localhost:8179, so the LAN-only :8179 port is never
    # exposed. Single source of the flow card lives in energy.html now.
    # -----------------------------------------------------------------------
    # How long a fetched reply counts as current. Unchanged from the v2.72.0
    # micro-cache: three pages poll `status` within a second of each other.
    SIGEN_FRESH_SECONDS = 2.5
    # What the WORKER allows the upstream. Still 12 s, and still for the reason
    # given in _sigen_fetch — the difference is who waits it out. The handler's
    # own cap is OFFPATH_WAIT.
    SIGEN_UPSTREAM_TIMEOUT = 12

    _SIGEN_API_BASE      = "http://127.0.0.1:8179/api"
    _SIGEN_ALLOWED_PATHS = frozenset({
        "status", "history", "daily", "export-sync", "years", "calendar",
        # v2.84.0 — the VPP earnings ledger. Its own path rather than a
        # widening of `status`, because it carries the per-event list and the
        # status payload is polled every few seconds by three pages.
        "vpp",
    })

    # ── Slow work, off the dispatch path (v3.18.0, generalised v3.19.0) ────
    # WHY THIS EXISTS. An Indigo /message/ handler runs on the shared dispatch
    # path — this file's own gate comment says such a call "can wedge the whole
    # IWS event loop for ~5 min" — so anything slow done inline is an outage of
    # the web server, not a slow tile, and whatever request happens to be in
    # flight comes back as a 500.
    #
    # Measured over September 2026: 130 of those 500s. "[SigenProxy] status
    # fetch failed: timed out" fell within ten seconds of one in 16 of its 58
    # occurrences — 324 times the background rate — with 16 of the 24 correlated
    # pairs landing in the SAME two-second bucket as the timeout being logged.
    # Then an audit of all 32 browser-reachable endpoints, TIMED rather than
    # eyeballed, found two more: timelineDay at 1707 ms and systemHealth at
    # 262 ms, worst of three calls each.
    #
    # v3.18.0 fixed the Sigen proxy with its own worker pool. v3.19.0 makes that
    # ONE pool any handler can use, because three copies of this machinery would
    # have rotted apart. A handler asks for a key; it gets a cached answer, or it
    # waits OFFPATH_WAIT at the very most and is told the work is pending.

    OFFPATH_WORKERS = 3
    # The ONLY time a handler is allowed to wait. Long enough that a healthy
    # producer lands inside it (SigenEnergyManager answers in ~30 ms), short
    # enough that a sick one costs a page one poll instead of the house.
    OFFPATH_WAIT    = 0.75
    OFFPATH_CACHE_MAX = 64

    # A finished day cannot change, so it is held for the session; today's
    # is still being written to, so it is rebuilt every minute.
    TIMELINE_TODAY_TTL = 60
    TIMELINE_PAST_TTL  = 86400
    # Disk, RAM and the device census move slowly; half a minute is live
    # enough for a page somebody opens to look at them.
    SYSTEM_HEALTH_TTL  = 30

    # These two pages wait properly — they use DashUI.message, which polls a
    # pending reply and shows "Building this day…" — so their handlers need not
    # hold the dispatch path at all while a first build runs. Measured after
    # the move: with the default 0.75 s cap, timelineDay's worst call was
    # 779 ms, which is the CAP rather than the work, and still nearly a second
    # of everything else waiting. A page that can wait should be told to.
    #
    # The default stays 0.75 s for sigenApi, whose callers (hub, energy, cost)
    # do NOT poll on pending — they keep their last render — so a longer look
    # before giving up is worth more to them than a shorter one.
    TIMELINE_WAIT      = 0.15
    SYSTEM_HEALTH_WAIT = 0.15

    # A chart is a picture of a window that keeps moving, so half a minute of
    # age is invisible on every range the page offers — and on the 720 h chip
    # it turns a six-second wait into one, once.
    HISTORY_TTL        = 30
    HISTORY_WAIT       = 0.15
    GUEST_HISTORY_WAIT = 20.0      # the :8177 proxy's own thread may wait

    # Solar string hours (v3.25.0): the last history read that still ran on the
    # dispatch path. Today's chart moves as the day goes on; a past day's cannot.
    SOLAR_HOURS_TODAY_TTL = 120
    SOLAR_HOURS_WAIT      = 0.15

    # A laundry deadline replans at once (v3.25.0). The script used to be exec'd
    # on the dispatch path, and could run at the same moment as the loop's own
    # tick of it. The page polls for the new plan when the reply says pending.
    LAUNDRY_REPLAN_TTL  = 60
    LAUNDRY_REPLAN_WAIT = 0.75

    def _offpath(self):
        """Lazily built, so a handler can never race startup()."""
        st = getattr(self, "_offpath_store", None)
        if st is None:
            st = self._offpath_store = {
                "cache":   collections.OrderedDict(),   # key -> (produced_at, payload), oldest first
                "fail":    {},        # key -> (at, detail)
                "waiters": {},        # key -> Event, present only while queued
                "lock":    threading.Lock(),
                "queue":   queue.Queue(),
                "stop":    threading.Event(),
                "threads": [],
            }
        return st

    def _start_offpath_workers(self):
        st = self._offpath()
        for i in range(self.OFFPATH_WORKERS):
            t = threading.Thread(target=self._offpath_worker_main, args=(st,),
                                 name=f"dashboards-offpath-{i}", daemon=True)
            st["threads"].append(t)
            t.start()

    def _stop_offpath_workers(self):
        st = getattr(self, "_offpath_store", None)
        if not st:
            return
        st["stop"].set()
        for _ in st["threads"]:
            st["queue"].put(None)      # a worker parked in get() needs waking
        for t in st["threads"]:
            t.join(timeout=1.0)
        st["threads"] = []

    def _offpath_worker_main(self, st):
        while True:
            job = st["queue"].get()
            if job is None or st["stop"].is_set():
                return
            key, producer = job
            try:
                payload = producer()
            except Exception as exc:   # never let one bad job end a worker
                # A producer that has already reported its own failure marks
                # the exception, so one fault is one line, not two (v3.23.1).
                if getattr(exc, "_dash_logged", False):
                    self.logger.debug(f"[offpath] {key} failed: {exc}")
                else:
                    self.logger.warning(f"[offpath] {key} failed: {exc}")
                with st["lock"]:
                    st["fail"][key] = (time.time(), str(exc))
            else:
                with st["lock"]:
                    # Least-recently-used out, one at a time (v3.27.0). It used
                    # to clear EVERYTHING at the cap, which threw away timeline
                    # days meant to be held for a whole day.
                    st["cache"][key] = (time.time(), payload)
                    st["cache"].move_to_end(key)
                    while len(st["cache"]) > self.OFFPATH_CACHE_MAX:
                        st["cache"].popitem(last=False)
                    st["fail"].pop(key, None)
            finally:
                with st["lock"]:
                    ev = st["waiters"].pop(key, None)
                if ev is not None:
                    ev.set()

    def _offpath_get(self, key, producer, ttl, wait=None):
        """Return (state, payload): "fresh" | "failed" | "pending".

        Callers asking for the same key share one Event and produce ONE run of
        the producer — three pages polling the same thing within a second cost
        one round trip, not three.

        A stale entry is deliberately NOT returned as though it were current. A
        figure about now has to come from now, and every page here keeps its
        last render on a bad reply, so the tile holds its value and its clock
        stops. That is the truth; an old reading dressed as a new one is not.
        """
        st  = self._offpath()
        with st["lock"]:
            hit = st["cache"].get(key)
            if hit and time.time() - hit[0] < ttl:
                st["cache"].move_to_end(key)
                return "fresh", hit[1]
            ev = st["waiters"].get(key)
            if ev is None:
                ev = st["waiters"][key] = threading.Event()
                # A failure from an EARLIER run must not answer for this one
                # (v3.27.0): it used to be returned while the new run was still
                # pending, and was only ever cleared by a success.
                st["fail"].pop(key, None)
                st["queue"].put((key, producer))
        ev.wait(self.OFFPATH_WAIT if wait is None else wait)

        with st["lock"]:
            hit  = st["cache"].get(key)
            fail = st["fail"].get(key)
        if hit and time.time() - hit[0] < ttl:
            return "fresh", hit[1]
        if fail:
            return "failed", fail[1]
        return "pending", None

    def _offpath_swr(self, key, producer, ttl, fail_ttl, placeholder, on_fail):
        """Stale-while-revalidate on the shared pool (v3.27.0). Never waits.

        For data that is expensive to build and slow to change — carbon
        intensity, home insights, mains offsets — where an answer from a few
        minutes ago beats making the page wait. A fresh entry is returned as
        is. A stale one is returned too, and ONE refresh is queued behind it.
        With nothing cached yet, `placeholder` says it is being built.

        A failure is remembered for `fail_ttl`, so a server without SQL Logger
        or a carbon API that is down is not re-asked on every poll; while it
        stands, a stale entry still wins, and with none `on_fail(detail)` says
        what went wrong. `ttl` may be a function of the payload, for sources
        that report their own failure in the reply rather than raising.

        These three each used to run a thread and a cache of their own beside
        this pool — three copies of the same idea, each with its own bugs."""
        st  = self._offpath()
        now = time.time()
        with st["lock"]:
            hit  = st["cache"].get(key)
            fail = st["fail"].get(key)
            if hit and now - hit[0] < (ttl(hit[1]) if callable(ttl) else ttl):
                st["cache"].move_to_end(key)
                return hit[1]
            recent_fail = bool(fail and now - fail[0] < fail_ttl)
            if not recent_fail and key not in st["waiters"]:
                st["waiters"][key] = threading.Event()
                st["fail"].pop(key, None)
                st["queue"].put((key, producer))
        if hit:
            return hit[1]
        if recent_fail:
            return on_fail(fail[1])
        return placeholder

    def _sigen_fetch(self, url):
        """One upstream round trip. Runs on an off-path worker, where blocking
        is harmless. Returns the body, or raises — the pool records the failure
        and tells every caller waiting on that key."""
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": f"Dashboards/{PLUGIN_VERSION}"})
        try:
            # 12 s, not 8 s: SigenEnergyManager serves /api/status from the same
            # process that runs its periodic EMS-control cycle, which pushes a
            # burst of serial modbus writes (set EMS mode + discharge/charge
            # limits, ~8-10 s in total). At 8 s the status fetch occasionally
            # timed out mid-cycle. (Diagnosed 18-Jul-2026 — the timeouts
            # correlated to the second with SEM's "Setting ESS max
            # discharge/charge limit".)
            with urllib.request.urlopen(
                    req, timeout=self.SIGEN_UPSTREAM_TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:
            # A 404 from upstream is not a fault — it means this
            # SigenEnergyManager is older than the path being asked for, which
            # is the ordinary state of affairs between the two plugins being
            # upgraded. The page already degrades by hiding the card, so
            # warning about it once every poll would put an amber line in the
            # log for a system working exactly as designed.
            msg = f"[SigenProxy] {url.rsplit('/', 1)[-1]} fetch failed: {exc}"
            if getattr(exc, "code", None) == 404:
                self.logger.debug(msg + " — upstream plugin has no such path (optional)")
            else:
                self.logger.warning(msg)
            try:
                exc._dash_logged = True     # the off-path worker need not repeat it
            except Exception:
                pass
            raise

    def handleSigenApi(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/sigenApi/
        Body: {"path": "status"|..., "query": {"hours": 24}}
        Fetches the SigenEnergyManager :8179 data API (localhost) and returns
        its JSON. Path is allow-listed and the upstream host is fixed (no SSRF);
        only int hours/days/year query params are forwarded. Bearer-authed by
        IWS upstream.
        """
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        if not self._sigen_available():
            # No SigenEnergyManager on this server (v3.13.0): say so at once
            # rather than dial a port nothing listens on — a fresh install
            # without it used to WARN on every hub poll, thirty seconds apart.
            return self._evo_reply({"error": "SigenEnergyManager is not installed",
                                    "reason": "sem_absent"}, status=503)
        import urllib.parse      # urlencode only — the fetching lives on a worker
        payload, _reply = self._request_body(action, refuse_reflector=False)
        if _reply:
            return _reply

        path = str(payload.get("path") or "status").strip().lower()
        if path not in self._SIGEN_ALLOWED_PATHS:
            return self._evo_reply({"error": f"unknown path: {path!r}"}, status=400)

        # Only forward the handful of numeric params the data API accepts.
        query = payload.get("query") or {}
        qs = {}
        for k in ("hours", "days", "year"):
            if k in query:
                try:
                    qs[k] = int(query[k])
                except (TypeError, ValueError):
                    pass
        url = f"{self._SIGEN_API_BASE}/{path}"
        if qs:
            url += "?" + urllib.parse.urlencode(qs)

        # No network I/O on the dispatch path (v3.18.0; on the shared pool
        # since v3.19.0). See the block above _offpath for what this replaced.
        state, payload = self._offpath_get(
            f"sigen:{url}", lambda: self._sigen_fetch(url), self.SIGEN_FRESH_SECONDS)
        if state == "fresh":
            return {
                "status":  200,
                "headers": {"Content-Type":  "application/json; charset=utf-8",
                            "Cache-Control": "no-store"},
                "content": payload,
            }
        if state == "failed":
            return self._evo_reply(
                {"error": "Sigenergy data API unavailable", "detail": payload},
                status=502)
        return self._evo_reply(
            {"error": "Sigenergy data is still being fetched",
             "reason": "sigen_pending"},
            status=503)

    # -----------------------------------------------------------------------
    # System-health endpoint — Mac vitals + storage + device-health census.
    # Powers system-health.html. Everything is computed server-side in ONE
    # round-trip because a browser can't read host stats (disk/RAM/swap) or
    # the SQL history DB size, and shipping ~190 devices' full JSON over the
    # reflector just to count them would be wasteful. Bearer-authed by IWS.
    # -----------------------------------------------------------------------
    def handleSystemHealth(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/systemHealth/
        Returns {mac, storage, devices}. No request params. Each section is
        computed defensively so one failure degrades to a partial answer."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        # Off the dispatch path (v3.19.0). Measured at 262 ms worst of three on
        # 18-09-2026: subprocess.run for the Mac vitals, os.walk and os.scandir
        # for the storage breakdown. None of it is wrong; none of it belongs on
        # the thread that serves every dashboard in the house.
        state, payload = self._offpath_get(
            "systemhealth", self._system_health_payload, self.SYSTEM_HEALTH_TTL,
            wait=self.SYSTEM_HEALTH_WAIT)
        if state == "fresh":
            return self._evo_reply(payload)
        if state == "failed":
            return self._evo_reply({"ok": False, "error": payload}, status=500)
        return self._evo_reply(
            {"ok": False, "pending": True,
             "error": "system health is still being gathered — try again shortly"},
            status=503)

    def _system_health_payload(self):
        """The four collectors, on an off-path worker. Each section is computed
        defensively so one failure degrades to a partial answer rather than
        losing the page — which is why this never raises and the pool therefore
        never records a failure for it."""
        out = {"ok": True, "now": time.time()}
        for key, fn in (("mac",      self._mac_vitals),
                        ("storage",  self._storage_breakdown),
                        ("devices",  self._device_health),
                        ("services", self._service_health)):
            try:
                out[key] = fn()
            except Exception as exc:
                self.logger.warning(f"[SystemHealth] {key} section failed: {exc}")
                out[key] = {"error": str(exc)}
        return out

    def _service_health(self):
        """This plugin's own background services (v2.33.0) — the page can then
        say whether the camera pipeline is actually alive, not just assumed."""
        go2 = getattr(self, "_go2rtc_proc", None)
        mj  = getattr(self, "_mjpeg_server", None)
        return {
            # Info.plist, which is what Indigo shows (v3.25.0) — the constant can lag it.
            "plugin_version": getattr(self, "pluginVersion", None) or PLUGIN_VERSION,
            "go2rtc":         bool(go2 is not None and go2.poll() is None),
            "mjpeg_proxy":    bool(mj is not None),
            "cameras":        len(self.cameras),
        }

    def _mac_vitals(self):
        """Host vitals: disk, RAM (+swap), load, uptime, OS/Python. RAM total
        comes from os.sysconf (authoritative, no subprocess); the breakdown
        from vm_stat. subprocess uses ABSOLUTE binary paths — the plugin-host
        PATH omits /usr/sbin, so a bare 'sysctl' raises FileNotFoundError."""
        import platform
        import subprocess

        def _sh(args):
            try:
                return subprocess.run(args, capture_output=True, text=True,
                                      timeout=5).stdout.strip()
            except Exception:
                return ""

        out = {
            "hostname": platform.node(),
            "macos":    platform.mac_ver()[0] or "",
            "python":   platform.python_version(),
            "arch":     platform.machine(),
            "cores":    os.cpu_count() or 0,
        }
        try:
            out["indigo"] = str(indigo.server.version)
            out["api"]    = str(indigo.server.apiVersion)
        except Exception:
            pass
        try:
            l1, l5, l15 = os.getloadavg()
            out["load"] = [round(l1, 2), round(l5, 2), round(l15, 2)]
        except Exception:
            out["load"] = []
        try:
            du = shutil.disk_usage("/")
            out["disk"] = {
                "total_gb": round(du.total / 1e9, 1),
                "used_gb":  round(du.used / 1e9, 1),
                "free_gb":  round(du.free / 1e9, 1),
                "used_pct": round(du.used / du.total * 100, 1),
            }
        except Exception:
            out["disk"] = {}

        ram = {}
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            vm = _sh(["/usr/bin/vm_stat"])
            m = re.search(r"page size of (\d+) bytes", vm)
            psize = int(m.group(1)) if m else 4096

            def _pg(label):
                mm = re.search(rf"{re.escape(label)}:\s+(\d+)\.", vm)
                return int(mm.group(1)) if mm else 0

            # "Memory Used" as Activity Monitor reports it: app (active) +
            # wired + compressed. Free/inactive/speculative are reclaimable.
            used = (_pg("Pages active") + _pg("Pages wired down")
                    + _pg("Pages occupied by compressor")) * psize
            # RAM in binary GiB (2**30) — the convention the hardware is sold
            # in. The old decimal /1e9 made an 8 GB Mac mini report "8.6 GB
            # total". Disk stays decimal (matches Finder/Apple SSD specs).
            ram = {
                "total_gb": round(total / 2**30, 1),
                "used_gb":  round(used / 2**30, 1),
                "free_gb":  round(max(0, total - used) / 2**30, 1),
                "used_pct": round(used / total * 100, 1) if total else 0,
            }
            sw = _sh(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
            st = re.search(r"total = ([\d.]+)M", sw)
            su = re.search(r"used = ([\d.]+)M", sw)
            if st:
                ram["swap_total_mb"] = round(float(st.group(1)))
            if su:
                ram["swap_used_mb"] = round(float(su.group(1)))
        except Exception:
            pass
        # Memory-pressure verdict. On an 8 GB Mac, heavy swap is the real
        # signal — a high used_pct alone is normal for macOS.
        up = ram.get("used_pct", 0)
        swu = ram.get("swap_used_mb", 0)
        if "used_pct" not in ram:
            # The measurement itself failed (vm_stat/sysctl timed out — which
            # is exactly what a starved Mac does). Unknown, never 'normal'.
            ram["pressure"] = "unknown"
        elif swu >= 1500 or up >= 92:
            ram["pressure"] = "high"
        elif swu >= 400 or up >= 82:
            ram["pressure"] = "elevated"
        else:
            ram["pressure"] = "normal"
        out["ram"] = ram

        out["uptime_text"] = ""
        try:
            up_txt = _sh(["/usr/bin/uptime"])
            mm = re.search(r"\bup\s+(.+?),\s+\d+\s+user", up_txt)
            out["uptime_text"] = mm.group(1).strip() if mm else up_txt
        except Exception:
            pass
        try:
            bt = _sh(["/usr/sbin/sysctl", "-n", "kern.boottime"])
            mm = re.search(r"sec\s*=\s*(\d+)", bt)
            if mm:
                out["boot_epoch"] = int(mm.group(1))
        except Exception:
            pass
        return out

    def _storage_breakdown(self):
        """SQL history DB size (the dominant, actionable chunk of a near-full
        disk) plus the biggest items in the Logs dir. Cached for 5 minutes so
        the 30 s page poll doesn't re-walk the tree every tick."""
        cache = getattr(self, "_storage_cache", None)
        nowm = time.time()
        if cache and (nowm - cache[0]) < 300:
            return cache[1]
        base = indigo.server.getInstallFolderPath()
        logs = os.path.join(base, "Logs")
        sqlp = os.path.join(logs, "indigo_history.sqlite")
        out = {
            "sql_history_gb":   round(os.path.getsize(sqlp) / 1e9, 2) if os.path.exists(sqlp) else 0.0,
            "sql_history_path": sqlp,
            "logs_total_gb":    0.0,
            "top_items":        [],
        }
        items = []
        try:
            with os.scandir(logs) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            sz = e.stat(follow_symlinks=False).st_size
                            is_dir = False
                        else:
                            sz = 0
                            for root, _dirs, files in os.walk(e.path):
                                for f in files:
                                    try:
                                        sz += os.path.getsize(os.path.join(root, f))
                                    except OSError:
                                        pass
                            is_dir = True
                        items.append((e.name, sz, is_dir))
                    except OSError:
                        pass
        except OSError:
            pass
        out["logs_total_gb"] = round(sum(s for _n, s, _d in items) / 1e9, 2)
        items.sort(key=lambda x: -x[1])
        out["top_items"] = [
            {"name": n, "gb": round(s / 1e9, 2), "dir": d}
            for n, s, d in items[:6] if s > 50e6   # only items over ~50 MB
        ]
        self._storage_cache = (nowm, out)
        return out

    @staticmethod
    def _battery_pct(dev):
        """Battery reading for a device, covering the estate's three battery
        idioms: the native batteryLevel property (Z-Wave etc.), the z2m custom
        `battery` state (guarded >0 — mains z2m devices report 0), and the
        boolean `batteryLow` alarm. Returns (pct_or_None, alarm_bool) — the
        same coverage as overview.html's batteryInfo(), which caught a 1%
        sensor the native-only check missed."""
        bl = getattr(dev, "batteryLevel", None)
        if isinstance(bl, (int, float)) and not isinstance(bl, bool):
            return int(bl), False
        try:
            states = dev.states
        except Exception:
            return None, False
        try:
            bf = float(states.get("battery"))
            if bf > 0:
                return int(bf), False
        except (TypeError, ValueError):
            pass
        if str(states.get("batteryLow", "")).strip().lower() in ("true", "on", "yes", "1"):
            return None, True
        return None, False

    def _device_health(self):
        """Per-device alerts + per-plugin census, computed over the live IOM.
        'In error' uses dev.errorState (the reliable liveness signal); 'quiet'
        uses lastChanged age (not a true comms probe — framed as such on the
        page) with a configurable threshold."""
        try:
            stale_hours = int(self.pluginPrefs.get("healthStaleHours", 48) or 48)
        except (TypeError, ValueError):
            stale_hours = 48
        try:
            low_batt_pct = int(self.pluginPrefs.get("healthLowBatteryPct", 20) or 20)
        except (TypeError, ValueError):
            low_batt_pct = 20

        now = indigo.server.getTime()
        in_error, low_batt, stale = [], [], []
        census = {}
        total = enabled = 0
        # len() and iteration disagree: iteration skips unconfigured devices
        # (measured 209 vs 211 here). Publish both so the page can show the gap.
        try:
            known = len(indigo.devices)
        except Exception:
            known = None

        for d in indigo.devices:
            total += 1
            is_on = bool(d.enabled)
            if is_on:
                enabled += 1
            pid = d.pluginId or "(native/built-in)"
            c = census.setdefault(pid, {"count": 0, "enabled": 0})
            c["count"] += 1
            if is_on:
                c["enabled"] += 1

            es = (d.errorState or "").strip()
            if es:
                in_error.append({"id": d.id, "name": d.name, "plugin": pid, "error": es})

            bl, alarm = self._battery_pct(d)
            if alarm or (bl is not None and bl <= low_batt_pct):
                low_batt.append({"id": d.id, "name": d.name, "plugin": pid,
                                 "battery": bl, "alarm": alarm})

            # "Quiet" only means something for BATTERY devices — silence from a
            # battery sensor can be a flat battery or a dropped mesh link. Mains
            # devices, virtuals and timers are legitimately quiet for days, and
            # some carry an unset/epoch lastChanged (a bogus multi-year age), so
            # they are excluded and implausible ages (>1yr) are dropped.
            if is_on and (alarm or bl is not None):
                try:
                    age_h = (now - d.lastChanged).total_seconds() / 3600.0
                    if stale_hours <= age_h <= 24 * 365:
                        stale.append({"id": d.id, "name": d.name, "plugin": pid,
                                      "age_hours": round(age_h, 1), "battery": bl,
                                      "alarm": alarm})
                except Exception:
                    pass

        plugins = []
        for pid, c in census.items():
            disp, running, plugin_enabled = pid, None, None
            try:
                p = indigo.server.getPlugin(pid)
                if p:
                    disp = p.pluginDisplayName or pid
                    # isRunning, NOT isEnabled (v2.95.1): a plugin that is
                    # enabled and has crashed reads True from isEnabled(), so
                    # this page — the one built to say something is down —
                    # showed a dead device-owning plugin as healthy for 20 h
                    # during the ShellyDirect outage of 16-17 Aug. Both are
                    # returned so the page can tell "stopped" (red) from
                    # "disabled on purpose" (grey). NB getPlugin() of an
                    # unknown id does not raise — it reads all-False — so a
                    # built-in pseudo-id keeps None rather than a false red.
                    if p.isInstalled():
                        running = bool(p.isRunning())
                        plugin_enabled = bool(p.isEnabled())
            except Exception:
                pass
            plugins.append({"plugin": pid, "name": disp, "count": c["count"],
                            "enabled": c["enabled"], "running": running,
                            "pluginEnabled": plugin_enabled})

        in_error.sort(key=lambda x: x["name"].lower())
        # None battery = a batteryLow alarm with no % — sort those first (-1).
        low_batt.sort(key=lambda x: x["battery"] if x["battery"] is not None else -1)
        stale.sort(key=lambda x: -x["age_hours"])
        plugins.sort(key=lambda x: (-x["count"], x["name"].lower()))

        return {
            "total":        total,
            "known":        known,
            "enabled":      enabled,
            "disabled":     total - enabled,
            "stale_hours":  stale_hours,
            "low_batt_pct": low_batt_pct,
            "in_error":     in_error[:50],
            "low_battery":  low_batt[:50],
            "stale":        stale[:30],
            "stale_count":  len(stale),
            "by_plugin":    plugins,
        }

    _SIGEN_PLUGIN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"

    def _sigen_inverter(self):
        """The Sigenergy inverter device, or None (v3.27.0).

        ONE rule for every caller: a SigenEnergyManager device carrying both
        batterySoc and pvPowerWatts. There used to be four copies that
        disagreed: two walked every device in the house, one hardcoded the
        plugin id, and each looked for a different state."""
        try:
            for d in indigo.devices.iter(self._SIGEN_PLUGIN_ID):
                st = getattr(d, "states", {}) or {}
                if "batterySoc" in st and "pvPowerWatts" in st:
                    return d
        except Exception:
            return None
        return None


    # -----------------------------------------------------------------------
    # Activity feed + automation health — a curated "house diary" from the
    # event log (comings/goings, safety, system events), collapsed alerts, and
    # an automation panel (what fires next, what watches for problems, what's
    # switched off, who holds a door code). Powers activity.html. The event log
    # is very chatty (per-sensor motion spam), so the diary is curated by source
    # + pattern rather than dumped raw. Bearer-authed by IWS upstream.
    # -----------------------------------------------------------------------
    _ACTIVITY_NOISE_SRC = ("Device Activity Monitor",)      # motion/CLEAR spam
    _ACTIVITY_SAFETY_RE = re.compile(r"leak|flood|water detect|smoke|\balarm\b|power ?cut", re.I)
    # A script reasoning aloud is not a house event. The battery optimiser
    # narrates its working with bracketed tags — "[FLOOD-GATE ] solar 36.7 kWh
    # / need 21.9 = 1.68x vs 3.0x gate -> NOT eligible" — and the safety regex
    # above matches "flood" and "power cut" in every one of them, so a single
    # evening's run put a dozen near-identical debug lines in the house diary.
    _ACTIVITY_TRACE_RE = re.compile(
        r"^\[[A-Z][A-Z0-9 _-]{2,}\]"          # [FLOOD-GATE ] / [POWERCUT ]
        r"|^(?:calculating|checking|phase \d)"  # running commentary
        r"|^(?:flood prevention|power cut min)", re.I)
    _ACTIVITY_MAX_MSG = 220                     # a Pushover body is not a diary entry

    def handleActivityFeed(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/activityFeed/
        Returns {alerts, diary, automation}. Each section is defensive."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time()}
        try:
            out["alerts"], out["diary"] = self._activity_events()
        except Exception as exc:
            self.logger.warning(f"[Activity] events section failed: {exc}")
            out["alerts"], out["diary"] = [], []
        try:
            out["automation"] = self._activity_automation()
        except Exception as exc:
            self.logger.warning(f"[Activity] automation section failed: {exc}")
            out["automation"] = {}
        return self._evo_reply(out)

    # -----------------------------------------------------------------------
    # Hourly log-error watch feed. The judgement (what is new, what is still
    # unresolved, what is muted noise) belongs to Python Scripts/
    # Log_Error_Watch.py — this only serves the state file it writes, so the
    # page and the Pushover can never disagree about what is wrong.
    #
    # The file deliberately lives in Python Scripts/, NOT /public: that folder
    # is anonymous and reflector-reachable, and raw event-log text carries
    # hostnames, IPs and traceback fragments. This route is Bearer-authed by
    # IWS upstream, which is the whole reason for going through /message/.
    # -----------------------------------------------------------------------
    def handleLogErrors(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/logErrors/
        Returns {ok, feed:{generatedLocal, errors, warnings, rows[]}, lastRun}."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time(), "feed": None, "lastRun": None}
        try:
            path = os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                                "Python Scripts", "log_error_watch_state.json")
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            out["feed"] = state.get("feed") or {}
            out["lastRun"] = state.get("last_run")
            out["seededAt"] = state.get("seeded_at")
        except FileNotFoundError:
            # Not an error — the watch simply has not run yet.
            out["feed"] = {}
            out["note"] = "log error watch has not run yet"
        except Exception as exc:
            self.logger.warning(f"[LogWatch] feed read failed: {exc}")
            out["ok"] = False
            out["error"] = "feed unavailable"
        return self._evo_reply(out)

    def handlePresenceData(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/presenceData/
        Serves the presence timelines Presence_Watch.py writes to
        Python Scripts/presence_data.json. The file deliberately lives there,
        NOT in /public: that namespace is anonymous and reflector-reachable,
        and this payload is 14 nights of room occupancy and bedroom sleep
        timing. This route is Bearer-authed by IWS upstream (v2.71.0 — the
        same move logErrors made for raw log text in v2.48.0)."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        try:
            path = os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                                "Python Scripts", "presence_data.json")
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["ok"] = True
            return self._evo_reply(payload)
        except FileNotFoundError:
            # Not an error — the watch simply has not run (or is not installed).
            return self._evo_reply({"ok": False, "error": "presence data not built yet",
                                    "note": "Presence_Watch.py has not run on this install"})
        except Exception as exc:
            self.logger.warning(f"[Presence] data read failed: {exc}")
            return self._evo_reply({"ok": False, "error": "presence data unavailable"})

    def _activity_events(self):
        """Turn the raw event log into (alerts, diary). Alerts = errors/warnings
        collapsed by source+message with a repeat count. Diary = a curated,
        low-noise stream of comings/goings, safety and system events."""
        try:
            rows = indigo.server.getEventLogList(returnAsList=True, lineCount=500)
        except Exception:
            rows = []

        def _clean(m):
            m = str(m or "").strip()
            return re.sub(r"^\[\d\d:\d\d:\d\d(?:\.\d+)?\]\s*", "", m).strip()

        today = datetime.now().date()
        alerts, diary, diary_seen = {}, [], {}
        for r in rows:
            msg = _clean(r.get("Message"))
            if not msg:
                continue
            src = str(r.get("TypeStr", "")).strip()
            tv = r.get("TypeVal")
            t = r.get("TimeStamp")
            try:
                epoch = time.mktime(t.timetuple()) if hasattr(t, "timetuple") else 0
                # Bare HH:MM for today; "Mon 14:01" once the log window spans days.
                fmt = "%H:%M" if (hasattr(t, "date") and t.date() == today) else "%a %H:%M"
                hhmm = t.strftime(fmt) if hasattr(t, "strftime") else ""
            except Exception:
                epoch, hhmm = 0, ""
            base_src = src.replace(" Error", "").replace(" Warning", "").strip()
            # A core-server message carries the BARE level as its source, and
            # the replace above is a no-op on that (no leading space) — so those
            # rows used to be attributed to a plugin called "Error"/"Warning".
            if base_src in ("", "Error", "Warning"):
                base_src = "Indigo Server"
            level = ("error" if (tv == 1 or src.endswith("Error"))
                     else "warn" if (tv == 3 or src.endswith("Warning")) else "info")

            # Alerts — collapse errors + warnings so 50 identical lines read as
            # one. Digits are normalised in the KEY (not the display) so variants
            # of the same fault merge too — "read error regs 30220-30223" and
            # "regs 30216-30219" become one row with a count.
            if level in ("error", "warn"):
                key = base_src + "|" + re.sub(r"\d+", "#", msg)[:80]
                a = alerts.get(key)
                if a is None:
                    disp = (msg[:157] + "…") if len(msg) > 158 else msg
                    alerts[key] = {"src": base_src, "message": disp, "level": level,
                                   "count": 1, "last": hhmm, "_ep": epoch}
                else:
                    a["count"] += 1
                    if epoch >= a["_ep"]:
                        a["last"], a["_ep"] = hhmm, epoch

            # Diary — curated by source + pattern (skip motion spam entirely).
            if base_src in self._ACTIVITY_NOISE_SRC:
                continue
            low = msg.lower()
            cat = None
            if "lock" in src.lower():
                # The readable "... Lock Manager: Door unlocked ..." line. The raw
                # "Z-Wave: received ... status update" echo of the SAME event is
                # deliberately not matched here, so a lock event is one diary row.
                cat = "lock"
            elif "garage door" in low:
                cat = "lock"
            elif self._ACTIVITY_SAFETY_RE.search(msg):
                cat = "safety"
            elif src == "Application" and low.startswith("started plugin"):
                cat = "system"          # one clean line per restart, not the full 5-line lifecycle
            if cat and not self._ACTIVITY_TRACE_RE.search(msg):
                disp = (msg[:self._ACTIVITY_MAX_MSG - 1] + "…") if len(msg) > self._ACTIVITY_MAX_MSG else msg
                # Collapse repeats the same way alerts do: digits normalised in
                # the KEY only, so "Door locked manually [Node: 44]" three times
                # is one row with a count rather than three identical rows.
                dkey = base_src + "|" + cat + "|" + re.sub(r"\d+", "#", msg)[:80]
                d = diary_seen.get(dkey)
                if d is None:
                    diary_seen[dkey] = {"time": hhmm, "epoch": epoch, "src": base_src,
                                        "msg": disp, "level": level, "cat": cat, "count": 1}
                    diary.append(diary_seen[dkey])
                else:
                    d["count"] += 1
                    if epoch >= d["epoch"]:
                        d["time"], d["epoch"] = hhmm, epoch

        alert_list = sorted(alerts.values(), key=lambda a: -a["_ep"])[:15]
        for a in alert_list:
            a.pop("_ep", None)
        diary = sorted(diary, key=lambda d: -d["epoch"])[:40]
        return alert_list, diary

    @staticmethod
    def _parse_lock_code_trigger(name):
        """Parse a 'Lock <person> Front Door Unlock Code (<slot>) <label>'
        trigger name into {person, slot, label}, or None if it doesn't match.
        PIN digits are NEVER surfaced to the browser: any run of 3+ digits in
        the free-text label is scrubbed (a wholly-numeric label OR an embedded
        number like 'code 4471' — the whole label needn't be numeric)."""
        m = re.match(r"Lock (.+?) Front Door Unlock Code \((\d+)\)\s*(.*)$", name or "")
        if not m:
            return None
        lbl = m.group(3).strip()
        # Three or more digits ANYWHERE in the label ('19 81', '4-4-7-1') is
        # a PIN reminder; the roster only needs person + slot, so drop it.
        if sum(c.isdigit() for c in lbl) >= 3:
            lbl = ""
        return {"person": m.group(1).strip(), "slot": int(m.group(2)), "label": lbl}

    def _activity_automation(self):
        """Schedules due next, the error-watch triggers, what's switched off,
        and the per-person door-code roster (parsed from trigger names)."""
        now_epoch = time.time()
        next_up, disabled = [], []
        sched_total = sched_off = 0
        for s in indigo.schedules:
            sched_total += 1
            if not s.enabled:
                sched_off += 1
                disabled.append({"name": s.name, "kind": "schedule"})
                continue
            try:
                ne = s.nextExecution
                if ne and ne.year > 2000:          # skip the 0001 "not armed" sentinel
                    ep = time.mktime(ne.timetuple())
                    next_up.append({"name": s.name, "epoch": ep,
                                    "when": ne.strftime("%a %H:%M"),
                                    "in_min": round((ep - now_epoch) / 60.0)})
            except Exception:
                pass
        next_up = sorted(next_up, key=lambda x: x["epoch"])[:8]

        watchers, codes = [], []
        trig_total = trig_off = 0
        for t in indigo.triggers:
            trig_total += 1
            if not t.enabled:
                trig_off += 1
                disabled.append({"name": t.name, "kind": "trigger"})
                continue
            if (getattr(t, "pluginTypeId", "") or "") == "eventLogError":
                watchers.append({"name": t.name})
            info = self._parse_lock_code_trigger(t.name)
            if info:
                codes.append(info)
        codes.sort(key=lambda c: c["slot"])
        return {
            "next":     next_up,
            "watchers": watchers,
            "disabled": disabled,
            "codes":    codes,
            "counts": {"schedules": sched_total, "schedules_off": sched_off,
                       "triggers": trig_total, "triggers_off": trig_off},
        }

    def _apply_log_level(self, value):
        """Point the logLevel pref at the EVENT-LOG handler, not at the logger.

        Indigo hands every plugin two handlers and plugin_base.py says plainly
        why: the logger sits at THREADDEBUG "so everything gets to each
        handler - the handlers can then filter messages at the levels they
        want". indigo_log_handler echoes to the shared Indigo event log and
        starts at Info; plugin_file_handler writes this plugin's own file and
        takes everything.

        Setting the level on the LOGGER, which is what this did until now,
        gates before BOTH handlers. At the default logLevel of Info that threw
        every Debug record away before the file handler ever saw it - measured
        06-09-2026, the live plugin.log held 5 Info and 3 Warning lines and no
        Debug line at all. That is harmless while nothing logs at Debug, and
        the moment the routine narration moved there it would have DESTROYED
        it rather than redirecting it to this plugin's own log. Guarded
        coerce: a blank or non-numeric field falls back to Info.

        This pref therefore decides how much of the ROUTINE traffic reaches the
        shared event log, and it is a second switch on the narration alongside
        the logActivityToEventLog checkbox: at Debug the _activity() lines
        reach the event log whether that box is ticked or not, and at Warning
        they do not reach it even when it is. Both field helps say so.

        Faults are outside its remit, which is why the floor is capped at
        WARNING. Picking "Error" would otherwise have set indigo_log_handler
        to 40 and silently dropped all 28 self.logger.warning() lines out of
        the event log - and Log_Error_Watch.py reads the event log and nothing
        else, so that setting would have blinded the estate's only watcher to
        every warning this plugin raises. (The 56 faults raised through the
        module log() helper were never at risk: indigo.server.log bypasses the
        handlers entirely.) The cap makes "Error" behave as "Warning", which is
        a smaller cost than a fault nobody sees.
        """
        try:
            # int() alone: blank, None and junk all raise and land on the
            # fallback below, so an "is it blank" test in front of it would be
            # a guard that can never be the one that speaks.
            lvl = int(value)
        except (ValueError, TypeError):
            lvl = 20
        handler = getattr(self, "indigo_log_handler", None)
        if handler is not None:
            handler.setLevel(min(lvl, logging.WARNING))
        # Leave the logger itself wide open, so this plugin's own file keeps
        # receiving everything whatever the user picks for the event log.
        file_handler = getattr(self, "plugin_file_handler", None)
        self.logger.setLevel(getattr(file_handler, "level", None) or logging.DEBUG)

    def _activity(self, message):
        """Routine narration: per-restart plumbing, per-file writes, thread
        start and stop. Info when the user has asked for it, otherwise Debug.
        Both reach this plugin's own log file; which of them ALSO reaches the
        shared Indigo event log is the Log Level pref's business, so at Debug
        even the quiet form gets through and at Warning even the loud form does
        not. Never call this for a fault - see the logActivityToEventLog note
        in __init__ for why.

        getattr() rather than self.log_activity so a half-built instance (a
        test's bare plugin, or a failure part-way through __init__) still logs
        rather than raising inside a logging call.
        """
        if getattr(self, "log_activity", False):
            self.logger.info(message)
        else:
            self.logger.debug(message)

    def _startup_summary(self):
        """The ONE event-log line startup is worth. Indigo already logs
        "Starting plugin" and "Started plugin" either side of it, so this only
        has to say what the plugin ended up running - which is exactly what
        the nine demoted start-up lines used to convey between them."""
        bits = []
        if getattr(self, "cam_user", "") and getattr(self, "cam_pass", "") and self.cameras:
            bits.append(f"{len(self.cameras)} camera{'' if len(self.cameras) == 1 else 's'}")
        elif self.cameras:
            bits.append(f"{len(self.cameras)} camera(s) configured but no credentials")
        else:
            bits.append("no cameras")
        if getattr(self, "_mjpeg_server", None) is not None:
            bits.append(f"MJPEG proxy on :{MJPEG_PROXY_PORT}")
        if getattr(self, "_go2rtc_proc", None) is not None:
            bits.append("go2rtc running")
        return f"{self.pluginDisplayName} started - {', '.join(bits)}"

    def _note_bootstrap_seed(self, client_ip):
        """True the FIRST time this plugin run hands the API key to `client_ip`.

        A repeat seed to a browser that already has it is routine; a seed to an
        address never seen before is worth a line in the shared log, because it
        is the only record that a new device on the LAN was given the key. The
        latch is per plugin run, so a restart re-announces every device once.
        """
        seen = self.__dict__.setdefault("_bootstrap_seen", set())
        if client_ip in seen:
            return False
        seen.add(client_ip)
        return True

    def _resolve_credentials(self, prefs, secrets_mod=None):
        """One home for the credential resolution __init__ performs:
        IndigoSecrets first, PluginConfig fallback. `secrets_mod` is the
        (possibly freshly reloaded) IndigoSecrets module, or None for a
        GUI-only install — the prefs fallback then carries everything."""
        g = (lambda n: (getattr(secrets_mod, n, "") or "")) if secrets_mod else (lambda n: "")
        p = lambda n: (prefs.get(n, "") or "")
        self.api_url  = (g("INDIGO_URL") or p("indigoUrl")).strip() or "http://127.0.0.1:8176"
        self.api_key  = (g("INDIGO_API_KEY") or g("CLAUDEBRIDGE_BEARER_TOKEN")
                         or p("indigoApiKey")).strip()
        self.cam_user = (g("DAHUA_USER") or p("dahuaUser")).strip()
        self.cam_pass = (g("DAHUA_PASS") or p("dahuaPass")).strip()

    def menuRegenerateConfig(self, valuesDict=None, typeId=None):
        """Menu: re-read IndigoSecrets, rewrite config.js AND re-sync the HTML
        pages into Web Assets/public/ without a restart. Useful after editing
        IndigoSecrets.py or any page in the bundle's static/pages/ folder.
        GUI-only installs (no IndigoSecrets.py) keep their PluginConfig
        credentials — the old version dropped them and wiped api_url/api_key
        to empty strings here."""
        import importlib
        secrets_mod = None
        try:
            import IndigoSecrets
            importlib.reload(IndigoSecrets)
            secrets_mod = IndigoSecrets
        except ImportError:
            pass    # GUI-only install — PluginConfig fallback below
        except Exception as exc:
            log(f"[Menu] Reload IndigoSecrets failed: {exc} — "
                f"using PluginConfig values", level="WARNING")
        self._resolve_credentials(self.pluginPrefs, secrets_mod)
        self._sync_pages_to_public()
        self._write_config_js()
        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        """Apply Configure changes LIVE. Every pref cached at __init__ was
        previously restart-only — including the bootstrapKeySeed security
        toggle, which read as saved-and-done in the dialog while the old value
        stayed in force. Camera list/swap-out changes still need a restart
        (they rebuild go2rtc + the pollers) and say so."""
        if userCancelled:
            return
        prefs = valuesDict or {}
        self._apply_log_level(prefs.get("logLevel", 20))
        self.bootstrap_key_seed = as_bool(prefs.get("bootstrapKeySeed"), True)
        self.log_activity = as_bool(prefs.get("logActivityToEventLog"), False)
        secrets_mod = None
        try:
            import IndigoSecrets as secrets_mod
        except ImportError:
            pass
        old_creds = (self.cam_user, self.cam_pass)
        self._resolve_credentials(prefs, secrets_mod)
        try:
            self._write_config_js()
        except Exception as exc:
            self.logger.warning(f"[Prefs] config.js rewrite failed: {exc}")
        # Weather fields were startup-only and the dialog never said so
        # (v2.95.2): re-arm the thread so a key or coordinate entered here
        # takes effect now. _start_weather_thread is a no-op on blank values.
        try:
            self._stop_weather_thread()
            self._weather_stop = threading.Event()
            self._weather_thread = None
            self._start_weather_thread()
        except Exception as exc:
            self.logger.warning(f"[Prefs] weather thread restart failed: {exc}")
        if (self.cam_user, self.cam_pass) != old_creds and self.cameras:
            self.logger.info("[Prefs] camera credentials changed — go2rtc and the snapshot "
                             "poller pick them up on the next plugin restart")

    # --------------------------------------------------------
    # One-time setup links (v1.20.1)
    # --------------------------------------------------------
    # A setup link seeds a browser that can't reach the :8177 /bootstrap
    # endpoint (i.e. anything arriving over the Indigo reflector). The menu
    # item writes setup-<token>.json (the key payload) plus setup-qr-<token>.svg
    # (a QR of the redeem URL) into the public folder under a high-entropy
    # unguessable name. setup.html redeems the token: it fetches the JSON,
    # stores the key in localStorage, then calls the burnSetupToken endpoint
    # (now authenticated — it has the key) so the files are deleted on first
    # use. Unredeemed links are swept by TTL from the camera poll loop.

    SETUP_LINK_TTL_SECONDS = 600          # unredeemed links die after 10 min
    _SETUP_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

    def _cleanup_setup_links(self, force_all=False):
        """Delete expired (or all, on shutdown/startup) setup-link artefacts."""
        pub = self._public_dashboards_dir()
        try:
            names = os.listdir(pub)
        except Exception:
            return
        now = time.time()
        for name in names:
            if not (name.startswith("setup-") and name.endswith((".json", ".svg"))):
                continue
            path = os.path.join(pub, name)
            try:
                expired = (now - os.path.getmtime(path)) > self.SETUP_LINK_TTL_SECONDS
                if force_all or expired:
                    os.remove(path)
                    log(f"[SetupLink] Removed {'stale ' if not force_all else ''}{name}")
            except Exception:
                pass

    # --------------------------------------------------------
    # Plugin-provided MCP tools (v3.12.0)
    # --------------------------------------------------------

    def handle_mcp_tool_invoke(self, action, dev=None, callerWaitingForResult=True):
        """The hidden mcp_tool_invoke action. An Indigo MCP server that reads
        Contents/Resources/mcp-manifest.json calls it with props
        {"tool": <bare name>, "arguments": <JSON string>} and gets a JSON-string
        envelope back; the work is done by mcp_tools.dispatch(), imported here
        and nowhere else so a fault in it can never reach startup.

        Every hidden action is also an IWS endpoint. A request arriving that
        way carries IWS's request props and no "tool", and is answered with a
        404 reply dict rather than a tool: the tools are for a co-operating
        plugin, not for a browser with the API key."""
        try:
            props = dict(getattr(action, "props", None) or {})
        except Exception:
            props = {}
        if "tool" not in props and any(
                k in props for k in ("incoming_request_method", "incoming_request_id",
                                     "request_body", "url_query_args", "request_headers")):
            return self._evo_reply({"error": "not an HTTP endpoint"}, status=404)
        try:
            import mcp_tools
            raw = props.get("arguments", "{}")
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception as exc:
                return mcp_tools.err("validation", f"arguments must be a JSON object string: {exc}")
            return mcp_tools.dispatch(self, str(props.get("tool") or ""), arguments)
        except Exception as exc:
            self.logger.error(f"[MCP] tool invocation failed: {exc}")
            return json.dumps({"status": "error",
                               "error": {"type": "internal", "message": str(exc)}})

    def handleGetDashboardsConfig(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/getDashboardsConfig/
        Returns the config currently in force plus where it came from, and a
        device index for the editor's pickers. Bearer-authenticated by IWS."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        try:
            # ONE walk over indigo.devices. The old code zipped a second
            # iteration against the first's list — a device added or removed
            # between the walks shifted every later pairing, silently
            # attaching wrong folder names.
            try:
                folder_names = {f.id: f.name for f in indigo.devices.folders}
            except Exception:
                folder_names = {}
            devices = [{"id": d.id, "name": d.name,
                        "folder": folder_names.get(d.folderId, "")}
                       for d in indigo.devices]
            # Full action-group list (UNfiltered — scenes.json excludes hidden
            # entries, so the editor needs this to be able to un-hide them).
            ag_folders = {}
            try:
                ag_folders = {f.id: f.name for f in indigo.actionGroups.folders}
            except Exception:
                pass
            action_groups = [
                {"id": ag.id, "name": ag.name,
                 "folder": ag_folders.get(ag.folderId, "") or "General"}
                for ag in indigo.actionGroups
            ]
            return self._evo_reply({
                "ok":           True,
                "source":       "store",
                "config":       self._redact_pin(self._effective_config()),
                "devices":      sorted(devices, key=lambda x: x["name"].lower()),
                "actionGroups": sorted(action_groups,
                                       key=lambda x: (x["folder"].lower(), x["name"].lower())),
                "guestToken":   self.guest_token,   # full-auth callers only (settings page)
                # v2.96.0: what the Rooms card's folder picker draws from.
                "folders":      sorted({f for f in folder_names.values() if f}, key=str.lower),
                "roomFoldersEffective": list(self._room_folders()),
            })
        except Exception as exc:
            self.logger.error(f"[Config] getDashboardsConfig failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    def handleSaveDashboardsConfig(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/saveDashboardsConfig/
        Body: {"config": {cameras, mainCameras, swapOutHost, roomExtras,
        hiddenScenes}}. Validates, persists dashboards_config.json (which then
        becomes the single source of truth) and applies what can be applied
        live. Camera changes need a plugin restart (go2rtc / pollers / proxy
        are built at startup) — the reply says so."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        cfg = payload.get("config")
        if not isinstance(cfg, dict):
            return self._evo_reply({"ok": False, "error": "config must be an object"}, status=400)
        return self._apply_config(cfg)

    def _apply_config(self, cfg):
        """Validate an editor-shaped config dict, persist it as
        dashboards_config.json and apply what applies live. Returns the IWS
        reply dict the settings endpoint sends: 200 with {ok: true,
        cameraRestartNeeded} or 400/500 with {ok: false, error}. The endpoint
        above and the plugin-provided MCP tools (v3.12.0, mcp_tools.py) both
        come through here, so there is ONE validation path and they cannot
        drift apart. `cfg` must already be a dict."""
        # ── validate ────────────────────────────────────────────────────
        errors  = []
        cameras = cfg.get("cameras") or []
        if not isinstance(cameras, list):
            errors.append("cameras must be a list")
            cameras = []
        # Hosts are later interpolated into go2rtc.yaml RTSP producer lines
        # and MJPEG proxy URLs — an arbitrary string here is a config/URL
        # injection. IP addresses or plain hostnames only.
        _host_ok = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")
        for i, c in enumerate(cameras):
            if not isinstance(c, dict) or not all(c.get(k) for k in ("host", "name", "vendor")):
                errors.append(f"camera {i + 1} needs host, name and vendor")
            elif c.get("vendor") not in ("dahua", "hikvision"):
                errors.append(f"camera {i + 1}: vendor must be dahua or hikvision")
            elif not _host_ok.match(str(c.get("host") or "")):
                errors.append(f"camera {i + 1}: host must be an IP address or "
                              f"plain hostname (letters, digits, dots, hyphens)")
        _slugs = {}
        for i, c in enumerate(cameras):
            if isinstance(c, dict) and c.get("name"):
                slug = self._cam_slug(str(c.get("name")))
                if not slug:
                    errors.append(f"camera {i + 1}: the name must contain letters or digits "
                                  f"(it becomes the go2rtc stream name)")
                elif slug in _slugs:
                    errors.append(f"camera {i + 1}: name {c.get('name')!r} makes the same "
                                  f"stream name as camera {_slugs[slug] + 1} — rename one")
                else:
                    _slugs[slug] = i
        _hosts_seen = [str(c.get("host")) for c in cameras if isinstance(c, dict) and c.get("host")]
        for h in {h for h in _hosts_seen if _hosts_seen.count(h) > 1}:
            errors.append(f"camera host {h} appears more than once — each "
                          f"host becomes one go2rtc stream slug and duplicates "
                          f"break the whole camera config")
        extras = cfg.get("roomExtras")
        if extras is not None and not isinstance(extras, dict):
            errors.append("roomExtras must be an object keyed by room name")
        elif isinstance(extras, dict):
            for _room, _v in extras.items():
                if not isinstance(_v, dict):
                    errors.append(f"roomExtras for '{_room}' must be an object")
        hidden = cfg.get("hiddenScenes")
        if hidden is not None and not isinstance(hidden, list):
            errors.append("hiddenScenes must be a list")
        main_cams = cfg.get("mainCameras") or []
        cam_hosts = {c.get("host") for c in cameras if isinstance(c, dict)}
        for h in main_cams:
            if h not in cam_hosts:
                errors.append(f"mainCameras entry {h} is not in the cameras list")
        if errors:
            return self._evo_reply({"ok": False, "error": "; ".join(errors)}, status=400)

        pin_req = cfg.get("pinRequired") or []
        if not isinstance(pin_req, list):
            return self._evo_reply({"ok": False, "error": "pinRequired must be a list"}, status=400)
        _pin_in = str(cfg.get("controlPin") or "").strip()
        if _pin_in and not _pin_in.isascii():
            return self._evo_reply({"ok": False, "error": "the control PIN must be plain "
                                    "ASCII (digits or letters)"}, status=400)
        # Start from a copy of any keys the incoming config carries that this
        # handler doesn't model, so a key added via the settings raw-JSON escape
        # hatch survives the save instead of being whitelisted away (v2.37.0
        # round-trip fix — the client now preserves them too). The validated
        # known keys below overwrite their own entries.
        _known = {"cameras", "mainCameras", "swapOutHost", "roomExtras",
                  "hiddenScenes", "controlPin", "pinRequired", "favourites",
                  "customLinks"}
        clean = {k: v for k, v in cfg.items() if k not in _known}
        clean.update({
            "cameras":      cameras,
            "mainCameras":  list(main_cams),
            "swapOutHost":  (cfg.get("swapOutHost") or "").strip(),
            "roomExtras":   extras if isinstance(extras, dict) else {},
            "hiddenScenes": [str(x) for x in (hidden or [])],
            "controlPin":   self._resolve_pin_save(str(cfg.get("controlPin") or "").strip()),
            "pinRequired":  _safe_int_list(pin_req),
        })
        # v2.96.0 keys. Each passes through the unknown-key round trip above;
        # here they are CLEANED so a bad value cannot reach the pages.
        rf = cfg.get("roomFolders")
        if rf is not None:
            if not isinstance(rf, list) or any(not isinstance(x, str) for x in rf):
                return self._evo_reply({"ok": False, "error": "roomFolders must be a list of folder names"}, status=400)
            clean["roomFolders"] = [x.strip()[:60] for x in rf if x.strip()][:100]
        sn = cfg.get("siteName")
        if sn is not None:
            clean["siteName"] = str(sn).strip()[:40]
        veh = cfg.get("vehicles")
        if veh is not None:
            if not isinstance(veh, list):
                return self._evo_reply({"ok": False, "error": "vehicles must be a list"}, status=400)
            out_v = []
            for v in veh:
                if not isinstance(v, dict):
                    continue
                try:
                    out_v.append({"id": int(v.get("id")), "label": str(v.get("label") or "").strip()[:40]})
                except (TypeError, ValueError):
                    continue           # a row without a device id is dropped, like a bad favourite
            clean["vehicles"] = out_v
        # Favourites (v2.10.0): list of {type:"device"|"scene", id:int, label?}.
        # Anything malformed is silently dropped rather than failing the save.
        # v2.76.0 adds {type:"door", id:<door device>, openAction:int,
        # closeAction:int, label?, state?} — the hub's state-driven door tile.
        def _opt_int(v):
            """None for an absent/blank value; int otherwise (raising on junk
            so the caller can drop the whole entry rather than half-save it)."""
            if v is None or str(v).strip() == "":
                return None
            return int(v)

        favs_in = cfg.get("favourites")
        favs_clean = []
        if isinstance(favs_in, list):
            for f in favs_in:
                if not isinstance(f, dict):
                    continue
                ftype = f.get("type")
                if ftype not in ("device", "scene", "door", "room", "group"):
                    continue
                # Group favourite (v2.93.0): ONE tile driving several devices —
                # the living room's three lamps and the fire behind a single
                # press. It has no id of its own, so it is handled before the
                # int(id) below. Each member is {id, onLevel?, openLoop?}:
                # onLevel asks a dimmer for a specific brightness on the way up
                # (the colour lamp wants 100, not wherever it was left), and
                # openLoop marks a device whose state is a belief rather than a
                # reading, so it is counted in the tile's label but never
                # decides which way a press goes. A member with a junk id is
                # dropped alone; a group left with no members is dropped whole,
                # because a tile that commands nothing is a trap, not a tile.
                if ftype == "group":
                    members = []
                    for m in (f.get("devices") or []):
                        if not isinstance(m, dict):
                            continue
                        try:
                            mid = int(m.get("id"))
                        except (TypeError, ValueError):
                            continue
                        member = {"id": mid}
                        lvl = m.get("onLevel")
                        if lvl is not None and str(lvl).strip() != "":
                            try:
                                lvl = int(round(float(lvl)))
                            except (TypeError, ValueError):
                                lvl = None
                            if lvl is not None and 1 <= lvl <= 100:
                                member["onLevel"] = lvl
                        if as_bool(m.get("openLoop"), False):
                            member["openLoop"] = True
                        members.append(member)
                    if not members:
                        continue
                    group_item = {"type": "group", "devices": members}
                    group_label = str(f.get("label") or "").strip()
                    if group_label:
                        group_item["label"] = group_label[:60]
                    favs_clean.append(group_item)
                    continue
                # Room shortcut (v2.89.0): a link to room.html, not a device.
                # It is keyed by the room NAME because that is what rooms.json
                # is keyed by — there is no device id to point at, and a room
                # renamed in Indigo should follow rather than dangle on an id
                # that no longer means anything.
                if ftype == "room":
                    room_name = str(f.get("room") or "").strip()
                    if not room_name:
                        continue
                    room_item = {"type": "room", "room": room_name[:60]}
                    room_label = str(f.get("label") or "").strip()
                    if room_label:
                        room_item["label"] = room_label[:60]
                    favs_clean.append(room_item)
                    continue
                try:
                    fid = int(f.get("id"))
                except (TypeError, ValueError):
                    continue
                item = {"type": ftype, "id": fid}
                if ftype == "door":
                    # An open action always, then a close action, a lockId
                    # (v2.77.0 lock-style door), or both — never neither. A
                    # present-but-junk key drops the entry whole: half a door
                    # saved is a trap, not a tile.
                    try:
                        item["openAction"] = int(f.get("openAction"))
                        close_a = _opt_int(f.get("closeAction"))
                        lock_id = _opt_int(f.get("lockId"))
                    except (TypeError, ValueError):
                        continue
                    if close_a is None and lock_id is None:
                        continue
                    if close_a is not None:
                        item["closeAction"] = close_a
                    if lock_id is not None:
                        item["lockId"] = lock_id
                label = str(f.get("label") or "").strip()
                if label:
                    item["label"] = label[:60]
                # Reading favourites (v2.19.0): a device favourite may pin a
                # specific state to show as a read-only value tile on the hub.
                # A door favourite may override the state it watches (default
                # doorState; onOffState of the contact for lock-style) via the
                # same key.
                fstate = str(f.get("state") or "").strip()
                if ftype in ("device", "door") and fstate:
                    item["state"] = fstate[:60]
                # Colour bands (v2.77.0): a reading tile may colour its value
                # — red below badBelow, amber below warnBelow, green above.
                # A junk band is dropped alone; the reading itself still saves.
                if ftype == "device" and item.get("state"):
                    for band_key in ("warnBelow", "badBelow"):
                        band_val = f.get(band_key)
                        if band_val is None or str(band_val).strip() == "":
                            continue
                        try:
                            item[band_key] = float(band_val)
                        except (TypeError, ValueError):
                            pass
                favs_clean.append(item)
        clean["favourites"] = favs_clean

        # Custom links (v2.x): full-size hub tiles opening an arbitrary URL.
        # {title, url, desc?, icon?}. Only http(s)/relative URLs are accepted —
        # javascript:/data: etc. are rejected (the URL becomes an <a href> on a
        # public page). Anything malformed is dropped rather than failing the save.
        links_in = cfg.get("customLinks")
        links_clean = []
        if isinstance(links_in, list):
            for l in links_in:
                if not isinstance(l, dict):
                    continue
                title = str(l.get("title") or "").strip()
                url   = str(l.get("url") or "").strip()
                if not title or not url:
                    continue
                low = url.lower()
                if not (low.startswith("http://") or low.startswith("https://")
                        or (url.startswith("/") and not url.startswith("//")
                            and not url.startswith("/\\"))):
                    continue               # '//host' is protocol-relative, i.e. off-site
                item = {"title": title[:40], "url": url[:300]}
                desc = str(l.get("desc") or "").strip()
                icon = str(l.get("icon") or "").strip()
                if desc:
                    item["desc"] = desc[:60]
                if icon:
                    item["icon"] = icon[:8]
                links_clean.append(item)
        clean["customLinks"] = links_clean

        # ── persist + apply live ────────────────────────────────────────
        old_cams = [dict(c) for c in self.cameras]
        try:
            self.cfg_store  = self._save_config_store(clean)
        except Exception as exc:
            self.logger.error(f"[Config] Could not write dashboards_config.json: {exc}")
            return self._evo_reply({"ok": False, "error": f"write failed: {exc}"}, status=500)

        self.room_extras  = clean["roomExtras"]
        self.main_cameras = clean["mainCameras"]
        self.control_pin  = clean["controlPin"]
        self.pin_required = clean["pinRequired"]
        self.favourites   = clean["favourites"]
        self.custom_links = clean["customLinks"]
        # Normalise BOTH sides through _parse_cameras before comparing —
        # the raw client dicts differ from the normalised self.cameras list in key
        # order/optional keys, so an unchanged save read as "restart needed".
        camera_restart    = (_parse_cameras(clean["cameras"]) != _parse_cameras(old_cams)
                             or (clean["swapOutHost"] or "") != (self.swap_out_host or ""))
        try:
            self._write_config_js()
            self._build_rooms_json()
            self._build_scenes_json()
        except Exception as exc:
            self.logger.warning(f"[Config] Post-save refresh failed: {exc}")

        self.logger.info(
            "[Config] dashboards_config.json saved from the settings editor — "
            "now the single source of truth"
            + (" (camera changes need a plugin restart)" if camera_restart else ""))
        return self._evo_reply({"ok": True, "cameraRestartNeeded": camera_restart})

    # --------------------------------------------------------
    # History queries (v2.4.0) — read-only over SQL Logger's DB
    # --------------------------------------------------------
    # Indigo's stock SQL Logger plugin has been recording every device state
    # change into Logs/indigo_history.sqlite all along (one table per device,
    # lowercased state names as TEXT columns, UTC ts). These queries are
    # strictly READ-ONLY (sqlite URI mode=ro) so we can never disturb the
    # logger, and column names are validated against the live table schema
    # so no caller-supplied identifier ever reaches SQL.


    # --------------------------------------------------------
    # Timeline replay (v2.40.0) — assemble one local day of the house's
    # activity into lanes (presence, lights, doors, heating) + a battery/solar
    # trace, from the SQL Logger history. Powers timeline.html.
    # --------------------------------------------------------


    # One shared helper (dash_util, v3.30.0): the mixins use it too.
    _as_bool01 = staticmethod(as_bool01)


    def _device_name(self, dev_id):
        try:
            return indigo.devices[dev_id].name
        except Exception:
            return f"#{dev_id}"

    # --------------------------------------------------------
    # Solar string hours (v2.79.0) — per-hour per-string energy for the
    # Energy page's stacked hourly chart, integrated from the SQL-logged
    # pv1Watts..pv4Watts states (SigenEnergyManager v5.67.0).
    # --------------------------------------------------------


    def handleLaundryPlan(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/laundryPlan/
        Serves the laundry plan the companion script last worked out. Bearer-authed
        upstream by IWS like every /message route — see _run_appliance_scheduler for why
        this is not a static file under /public."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        if not self._sigen_available():
            return self._evo_reply(
                {"ok": False, "reason": "sem_absent",
                 "error": "the Laundry page needs the SigenEnergyManager plugin, which is "
                          "not installed on this server"}, status=200)
        plan = self._read_laundry_plan()
        if plan is None:
            return self._evo_reply(
                {"ok": False,
                 "error": "no plan yet — Appliance_Scheduler.py has not run, or could not "
                          "see the solar forecast"}, status=200)
        plan = dict(plan)
        plan["ok"] = True
        return self._evo_reply(plan)

    def handleLaundryDeadline(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/laundryDeadline/
        Body: {"appliance": "washing_machine", "deadline": "HH:MM"} to say when that
        appliance must be finished by, or {"deadline": ""} to go back to the default.
        The appliance key defaults to washing_machine for older callers.

        Replans immediately and returns the new plan, so the page shows the answer to the
        question just asked rather than the previous one until the next tick.
        """
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply

        wanted = normalise_deadline(payload.get("deadline", ""))
        if wanted is None:
            return self._evo_reply(
                {"ok": False, "error": "deadline must be a time like 16:00, or empty"},
                status=400)

        # Which appliance. The key names the variable, so it has to be checked as tightly as
        # the time is: this writes an Indigo variable, and a key of "../../x" or one carrying
        # a space would create a variable nothing can ever read back.
        key = normalise_appliance_key(payload.get("appliance", "washing_machine"))
        if key is None:
            return self._evo_reply(
                {"ok": False, "error": "appliance must be a key like washing_machine"},
                status=400)

        name = f"{key}_deadline"
        try:
            if name in indigo.variables:
                indigo.variable.updateValue(indigo.variables[name].id, wanted)
            else:
                indigo.variable.create(name, wanted)
        except Exception as exc:
            self.logger.error(f"[Laundry] could not set the deadline: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

        # A key of its own for every request: each deadline change must replan,
        # never reuse the previous run's answer.
        self._laundry_seq = getattr(self, "_laundry_seq", 0) + 1
        state, plan = self._offpath_get(
            f"laundry-replan:{self._laundry_seq}", self._replan_laundry,
            self.LAUNDRY_REPLAN_TTL, wait=self.LAUNDRY_REPLAN_WAIT)
        if state == "failed":
            return self._evo_reply({"ok": False, "error": plan}, status=500)
        reply = {"ok": True, "appliance": key, "deadline": wanted}
        if state == "fresh":
            reply["plan"] = plan
        else:
            # Still replanning. Hand back the plan as it stands so the page
            # can tell when the new one lands (its "generated" changes).
            reply["pending"] = True
            reply["plan"] = self._read_laundry_plan()
        return self._evo_reply(reply)

    def _replan_laundry(self):
        """Off-path producer: run the scheduler once and return its plan.

        While Script Ticker runs the scripts, ask IT to run this one and wait
        (v3.31.0), so the scheduler never runs in two hosts at once. If the
        request cannot be made, run it here — a deadline change must replan."""
        if self._ticker_running():
            try:
                reply = indigo.server.getPlugin(self._TICKER_PLUGIN_ID).executeAction(
                    "runJob", props={"job": "laundry"}, waitUntilDone=True)
                # The reply crosses hosts as an indigo.Dict, which is NOT a
                # dict subclass — read it through its mapping methods.
                reply = dict(reply) if hasattr(reply, "keys") else {}
                if not reply.get("ok"):
                    self.logger.debug(f"[Laundry] Script Ticker could not replan: "
                                      f"{reply.get('error') or 'no reason given'}")
                return self._read_laundry_plan()
            except Exception as exc:
                self.logger.debug(f"[Laundry] Script Ticker did not take the replan ({exc}); "
                                  f"running it here")
        self._run_appliance_scheduler()
        return self._read_laundry_plan()


    def handleVerifyPin(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/verifyPin/
        Body: {"pin": "<entered>"}. Server-side comparison so the PIN value
        never reaches the browser. NOTE: this is a speed bump for paired
        devices (kids on the iPad), NOT a security boundary — a paired
        browser already holds the full API key."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        pin = str(payload.get("pin") or "")
        if not self.control_pin:
            return self._evo_reply({"ok": True, "valid": True, "note": "no PIN configured"})
        import hmac
        # Brute-force friction WITHOUT time.sleep — every handler and callback
        # shares ONE dispatch thread, so sleeping here froze the whole plugin
        # for half a second per wrong guess: a self-DoS anyone with the API
        # key could drive. A timestamp lockout gives the same pacing for free.
        nowp = time.time()
        if nowp < getattr(self, "_pin_locked_until", 0):
            return self._evo_reply({"ok": True, "valid": False,
                                    "note": "try again in a moment"})
        # bytes, not str: compare_digest() raises TypeError on a str with any
        # non-ASCII character, and a stray "é" in the PIN box 500'd the
        # endpoint rather than answering "no" (v2.95.1).
        valid = hmac.compare_digest(pin.encode("utf-8"),
                                    str(self.control_pin).encode("utf-8"))   # constant-time (v2.38.0)
        if not valid:
            self._pin_locked_until = nowp + 0.5
            self.logger.warning("[PIN] Incorrect control PIN entered")
        return self._evo_reply({"ok": True, "valid": valid})

    # ── applyColour (v2.94.0) ────────────────────────────────────────────
    # The colour sequence used to run in the BROWSER: turnOn, then
    # setBrightness, then setColorLevels, three separate round trips in a fixed
    # order, each in an empty `catch {}`. A phone that locked, backgrounded the
    # tab or lost signal between them left the lamp half-set — the wrong colour,
    # or full brightness with last night's film colour still on it — and nothing
    # anywhere said so. Ordered multi-step work belongs on the server, where the
    # steps cannot be interrupted by the screen going off.
    #
    # No sleeps anywhere in here on purpose. Every handler and callback in this
    # plugin shares ONE dispatch thread, so a blocking pause would freeze the
    # whole plugin — and the three IOM calls queue to the owning plugin and
    # return at once, so none is needed.
    @staticmethod
    def _colour_levels_from(payload):
        """Pull the setColorLevels keys out of a request body, validating each.

        Returns (levels, error). A bad key or an out-of-range value is an
        ERROR, never a clamp: clamping turns a caller's mistake into a light
        that quietly did something else, which is much harder to notice than a
        refusal."""
        levels = {}
        for key, (lo, hi) in _COLOUR_LEVEL_KEYS.items():
            if key not in payload or payload[key] is None or str(payload[key]).strip() == "":
                continue
            try:
                val = float(payload[key])
            except (TypeError, ValueError):
                return None, f"{key} is not a number"
            if not (lo <= val <= hi):
                return None, f"{key} must be between {lo} and {hi}"
            levels[key] = int(round(val))
        return levels, None

    def _device_command_blocked(self, dev):
        """(reason, http_status) if a command to `dev` would be SWALLOWED, else
        (None, None). Indigo does not raise for either case: a device whose
        communication is disabled ignores the action and logs 'Ignored'; a
        device whose owning plugin is stopped gets 'unable to execute action'
        in the log and nothing else. Both used to come back as ok:true."""
        if not getattr(dev, "enabled", True):
            return "device communication is disabled in Indigo — the command would be ignored", 409
        pid = getattr(dev, "pluginId", "") or ""
        if pid:
            try:
                owner = indigo.server.getPlugin(pid)
                # Fail OPEN on an unknown id: getPlugin() reads all-False for a
                # typo, and a typo must never be what refuses a command.
                if owner.isInstalled() and not owner.isRunning():
                    disp = getattr(owner, "pluginDisplayName", "") or pid
                    return f"{disp} is not running — the command would be swallowed", 503
            except Exception:
                pass
        return None, None

    def handleApplyColour(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/applyColour/

        Body, either:
            {"deviceId": N, "preset": "warm"}
            {"deviceId": N, "brightness": 0-100, "<levelKey>": v, ...}

        Runs turn-on -> brightness -> colour IN ORDER on the server and reports
        what actually happened, step by step. Each step is attempted even if an
        earlier one failed — a colour command works on a lamp that is off, it
        just is not visible yet — but a failure is RECORDED and returned, never
        swallowed the way the browser used to swallow it."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply

        try:
            dev_id = int(payload.get("deviceId"))
        except (TypeError, ValueError):
            return self._evo_reply({"ok": False, "error": "deviceId must be a number"}, status=400)
        # `in` on the devices collection returns False for an unknown id rather
        # than raising, so this is a real existence check.
        if dev_id not in indigo.devices:
            return self._evo_reply({"ok": False, "error": f"no device {dev_id}"}, status=404)
        dev = indigo.devices[dev_id]
        blocked, status = self._device_command_blocked(dev)
        if blocked:
            self.logger.warning(f"[Colour] {dev.name}: refused — {blocked}")
            return self._evo_reply({"ok": False, "device": dev.name, "error": blocked},
                                   status=status)

        preset_key = str(payload.get("preset") or "").strip()
        if preset_key:
            preset = COLOUR_PRESETS.get(preset_key)
            if preset is None:
                return self._evo_reply({"ok": False, "error": f"unknown preset {preset_key!r}"},
                                       status=400)
            source = preset
        else:
            source = payload

        levels, err = self._colour_levels_from(source)
        if err:
            return self._evo_reply({"ok": False, "error": err}, status=400)

        brightness = None
        if source.get("brightness") is not None and str(source.get("brightness")).strip() != "":
            try:
                brightness = float(source["brightness"])
            except (TypeError, ValueError):
                return self._evo_reply({"ok": False, "error": "brightness is not a number"},
                                       status=400)
            if not (0 <= brightness <= 100):
                return self._evo_reply({"ok": False, "error": "brightness must be 0-100"},
                                       status=400)
            brightness = int(round(brightness))

        if not levels and brightness is None:
            return self._evo_reply({"ok": False, "error": "nothing to apply"}, status=400)

        steps = []

        def _step(name, fn):
            try:
                fn()
                steps.append({"step": name, "ok": True})
                return True
            except Exception as exc:            # noqa: BLE001 — report, never swallow
                steps.append({"step": name, "ok": False, "error": str(exc)})
                return False

        # Turn on first. A colour command lands on a lamp that is off, but it
        # is not visible until something switches it on, and the point of a
        # preset button is that the room changes.
        _step("turnOn", lambda: indigo.device.turnOn(dev.id))
        if brightness is not None:
            _step("setBrightness", lambda: indigo.dimmer.setBrightness(dev.id, value=brightness))
        if levels:
            _step("setColorLevels", lambda: indigo.dimmer.setColorLevels(dev.id, **levels))

        failed = [st for st in steps if not st["ok"]]
        if failed:
            self.logger.warning(
                f"[Colour] {dev.name}: "
                + ", ".join(f"{st['step']} failed ({st['error']})" for st in failed))
        return self._evo_reply({
            "ok": not failed,
            "device": dev.name,
            "preset": preset_key or None,
            "applied": {"brightness": brightness, "levels": levels},
            "steps": steps,
        }, status=200 if not failed else 502)

    def menuShowGuestInfo(self, valuesDict=None, typeId=None):
        """Menu: log everything needed to provision a guest (read-only)
        device — the guest token and the pairing URL."""
        base = self.api_url or "http://localhost:8176"
        log("[Guest] Guest access — read-only, LAN/Tailscale only (port 8177 "
            "is never reachable from the internet):")
        log(f"[Guest]   Pairing URL (open ON the guest device): {base}/public/dashboards/guest.html")
        # The token is a persistent credential and the event log is a 0644
        # file that gets pasted into forum posts — only its tail is shown.
        _tok = self.guest_token or ""
        log(f"[Guest]   Guest token: ends …{_tok[-4:]} (the pairing page enters it for you; "
            f"the full value is in the Settings page's Security card)")
        log("[Guest]   Guest devices cannot control anything — they hold no API key.")
        return True

    def _prune_change_ledger(self):
        """Drop ledger entries no client could still ask about — changedSince
        forces a full refetch for anything older than 600s, so an hour's grace
        is plenty. Keeps both dicts bounded."""
        cutoff = time.time() - 3600
        for ledger in (self._dev_changes, self._dev_deleted):
            for dev_id, ts in list(ledger.items()):
                # Re-check the LIVE value before popping: deviceUpdated (main
                # thread) can refresh an entry between our snapshot and the
                # pop, and blindly popping would delete a fresh change — the
                # client would then miss it until the 5-min full resync.
                if ts < cutoff and ledger.get(dev_id, cutoff) < cutoff:
                    ledger.pop(dev_id, None)

    def menuGenerateSetupLink(self, valuesDict=None, typeId=None):
        """Menu: generate a one-time setup link (+ QR) that seeds a browser
        with the API key. Single-use (burned on redeem) and TTL-limited."""
        if not self.api_key:
            log("[SetupLink] No API key available (IndigoSecrets/PluginConfig) — "
                "cannot generate a setup link", level="ERROR")
            return False

        token = _stdlib_secrets.token_urlsafe(24)
        pub   = self._public_dashboards_dir()
        try:
            with open(os.path.join(pub, f"setup-{token}.json"), "w", encoding="utf-8") as f:
                json.dump({"apiKey": self.api_key}, f)
        except Exception as exc:
            log(f"[SetupLink] Could not write setup payload: {exc}", level="ERROR")
            return False

        # Redeem URLs — LAN always, reflector too if configured. The QR encodes
        # the reflector URL when available (phones scanning a QR are usually
        # the away-from-home case), falling back to the LAN URL.
        # A loopback api_url (which the config help itself recommends) makes
        # a useless pairing link — the PHONE scanning the QR is not the
        # server. Substitute the detected LAN address in that case.
        base = (self.api_url or "").strip()
        if not base or "127.0.0.1" in base or "localhost" in base:
            base = f"http://{self.lan_ip}:8176" if getattr(self, "lan_ip", "") \
                else (base or "http://localhost:8176")
        lan_url = f"{base}/public/dashboards/setup.html#{token}"
        refl_url = ""
        try:
            refl = (indigo.server.getReflectorURL() or "").rstrip("/")
            if refl:
                refl_url = f"{refl}/public/dashboards/setup.html#{token}"
        except Exception:
            pass

        qr_note = "QR not generated (qrcode package not installed yet — restart plugin to pip-install)"
        try:
            import qrcode
            import qrcode.image.svg
            # The QR carries the LAN address (v2.96.1). It used to carry the
            # reflector address on the theory that a phone scanning a QR is
            # away from home — but a phone is paired ONCE and keeps that
            # origin for ever, so a phone paired at home fetched every camera
            # still through Indigo's servers from the sofa. The reflector
            # link is still in the log for pairing a device that is away.
            img = qrcode.make(lan_url,
                              image_factory=qrcode.image.svg.SvgPathImage)
            img.save(os.path.join(pub, f"setup-qr-{token}.svg"))
            qr_base = base
            qr_note = f"QR (open on this Mac, scan with the phone): {qr_base}/public/dashboards/setup-qr-{token}.svg"
        except Exception as exc:
            qr_note = f"QR not generated ({exc})"

        log("[SetupLink] One-time setup link created — single use, expires in "
            f"{self.SETUP_LINK_TTL_SECONDS // 60} minutes:")
        log(f"[SetupLink]   LAN:       {lan_url}")
        if refl_url:
            log(f"[SetupLink]   Reflector: {refl_url}")
        log(f"[SetupLink]   {qr_note}")
        return True

    def handleBurnSetupToken(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/burnSetupToken/
        Body: {"token": "<token>"}  (Bearer-authenticated by IWS upstream)
        Deletes the one-time setup files so a redeemed link cannot be reused."""
        payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        token = str(payload.get("token") or "").strip()

        if not self._SETUP_TOKEN_RE.match(token):
            return self._evo_reply({"ok": False, "error": "bad token format"}, status=400)

        pub = self._public_dashboards_dir()
        removed = 0
        for name in (f"setup-{token}.json", f"setup-qr-{token}.svg"):
            try:
                os.remove(os.path.join(pub, name))
                removed += 1
            except FileNotFoundError:
                pass
            except Exception as exc:
                self.logger.warning(f"[SetupLink] Could not remove {name}: {exc}")
        if removed:
            self.logger.info(f"[SetupLink] Setup link redeemed and burned ({removed} file(s))")
        return self._evo_reply({"ok": True, "removed": removed})
