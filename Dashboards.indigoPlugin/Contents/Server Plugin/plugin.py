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
#              Runs go2rtc, whose WebRTC relays each camera's H.264 to the
#              browser for live tiles, and a small HTTP server on port 8177
#              for the WebRTC signalling and the bootstrap routes. Tiles that
#              are not live poll the snapshots.
# Author:      CliveS & Claude Opus 5 (3.17.0-3.20.0, 3.23.0); Claude Opus 5.5 (3.23.1-3.41.0); Claude Fable 5.1 (3.12.0-3.13.0); Claude Sonnet 5 (2.99.2); Claude Fable 5 (2.79.0); Claude Opus 5 (2.80-2.81, 2.84.0)
# Date:        23-09-2026
# Version:     3.41.0
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
PLUGIN_VERSION = "3.41.0"

import logging
from dash_common import (  # noqa: E402
    as_bool,
    CAMERA_POLL_SECONDS,
    COLOUR_PRESETS,
    GO2RTC_BIN,
    INDEX_PATH,
    PROXY_PORT,
    STAMP_CHANGE_WRITE_GAP,
    STAMP_FILENAME,
    STAMP_PERIOD_SECONDS,
    STAMP_QUIESCE_SECONDS,
    _COLOUR_LEVEL_KEYS,
    _detect_lan_ip,
    _install_file_mirror,
    _parse_cameras,
    log,
    normalise_appliance_key,
    normalise_deadline,
)


# ============================================================
# Plugin class
# ============================================================

# The plugin's features live in mixin modules beside this file (v3.30.0):
# plugin.py had grown past 9,000 lines. Plugin inherits every method, so each
# is still self.<name>, and Actions.xml still names the same callbacks.
# v3.32.0 moved the cameras, the settings store, page publishing, system
# health and the companion-script runner out as well, and the shared
# constants and log() helper into dash_common.py.
from cameras_mixin import CamerasMixin  # noqa: E402
from carbon_mixin import CarbonMixin  # noqa: E402
from config_mixin import ConfigMixin  # noqa: E402
from dash_util import as_bool01  # noqa: E402
from health_mixin import HealthMixin  # noqa: E402
from history_mixin import HistoryMixin  # noqa: E402
from insights_mixin import InsightsMixin  # noqa: E402
from mains_mixin import MainsMixin  # noqa: E402
from publish_mixin import PublishMixin  # noqa: E402
from scripts_mixin import ScriptsMixin  # noqa: E402


class Plugin(CamerasMixin, ConfigMixin, PublishMixin, HealthMixin, ScriptsMixin,
             CarbonMixin, InsightsMixin, MainsMixin, HistoryMixin, indigo.PluginBase):
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
        # safe to drop from the live pool), unless Settings names one.
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

    # Script Ticker (v3.31.0): a small plugin that runs the companion scripts
    # on its own. While it is RUNNING Dashboards leaves them to it; the moment
    # it is not (stopped, crashed, never installed) Dashboards runs them
    # itself, so a script is never left unrun and never run by both.
    _TICKER_PLUGIN_ID = "com.clives.indigoplugin.scriptticker"

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
        # find the snapshot and name as the tile label.
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
        self._proxy_server = None
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
        self._start_proxy()
        self._start_go2rtc(settle=False)
        # v3.23.1: go2rtc's one-second exited-immediately check and the JS
        # mirror (which waits for it to bind) were the whole second start-up
        # spent. Nothing else here needs either — only the camera pages read the
        # two files, and the previous boot's copies stay in place meanwhile — so
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
        self._stop_proxy()
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
        if getattr(self, "_proxy_server", None) is not None:
            bits.append(f"camera proxy on :{PROXY_PORT}")
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
