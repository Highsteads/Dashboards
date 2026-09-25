#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    config_mixin.py
# Description: The settings store (dashboards_config.json): loading it, the one-time
#              import of legacy settings, saving from the Settings page, and
#              the guest token kept beside it.
#              Split out of plugin.py in v3.32.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        25-09-2026
# Version:     1.1 (3.46.0: the key auto-seed default, settled and written down)

try:
    import indigo
except ImportError:
    pass

import json
import math
import os
import re
import secrets as _stdlib_secrets   # stdlib token generator (NOT IndigoSecrets)
import sys as _sys
import time

from dash_common import (
    as_bool,
    CAMERA_HOST_RE,
    _parse_cameras,
    _safe_int_list,
    log,
)

_PA_ROOT = "/Library/Application Support/Perceptive Automation"
if _PA_ROOT not in _sys.path:
    _sys.path.insert(0, _PA_ROOT)
# The legacy DASHBOARDS_* keys, read only by _import_legacy_config.
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


class ConfigMixin:
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

    # Camera stills live in /public/dashboards/stills-<this>/ — see
    # _ensure_stills_token. 32 lowercase hex characters, nothing else.
    _STILLS_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

    def _stills_token(self):
        """The current stills folder token, or "" before startup has made one."""
        tok = str((getattr(self, "cfg_store", None) or {}).get("stillsToken") or "")
        return tok if self._STILLS_TOKEN_RE.match(tok) else ""

    def _ensure_stills_token(self):
        """Make sure the store holds the per-install stills token, and return it.

        /public is anonymous, and reachable over the reflector, so the camera
        stills used to be readable by anyone who knew the fixed names
        (cam-<host>.jpg, published in config.js). They now sit in a folder
        named by this random token, which is handed out only through the
        Bearer-authenticated cameraStills action. Kept in the 0600 store so it
        survives restarts; the Settings page never sees it and cannot set it
        (_effective_config and _apply_config see to that). If the store cannot
        be saved the token still works for this run, and the next start picks
        a new folder."""
        tok = self._stills_token()
        if tok:
            return tok
        tok = _stdlib_secrets.token_hex(16)
        new = dict(getattr(self, "cfg_store", None) or {})
        new["stillsToken"] = tok
        try:
            self.cfg_store = self._save_config_store(new)
        except Exception as exc:
            self.cfg_store = new
            if not getattr(self, "_store_unreadable", ""):
                log(f"[Cameras] could not save the camera stills folder name ({exc}); "
                    f"it holds for this run and a new one is chosen at the next start",
                    level="WARNING")
        return tok

    # --------------------------------------------------------
    # Key auto-seed default (3.46.0)
    # --------------------------------------------------------
    @staticmethod
    def _prefs_have_history(prefs):
        """True when the plugin prefs hold anything the plugin or Configure
        wrote, i.e. this is not a first start. Indigo stores nothing for a
        plugin until one of them does; the Configure dialog's defaultValue only
        applies inside the dialog."""
        try:
            return any(k != "bootstrapKeySeed" for k in (prefs or {}).keys())
        except Exception:
            return False

    @staticmethod
    def _bootstrap_seed_pref(prefs, existing):
        """(value, why) for the key auto-seed, from the stored pref.

        why is "stored" (the pref holds a value, used as it is), "kept" (an
        existing install that never stored one: it keeps the old default, on)
        or "new" (a first start: off). A stored value is never overridden."""
        try:
            raw = (prefs or {}).get("bootstrapKeySeed")
        except Exception:
            raw = None
        if raw is not None and str(raw).strip() != "":
            return as_bool(raw, False), "stored"
        if existing:
            return True, "kept"
        return False, "new"

    def _settle_bootstrap_seed(self, prefs, existing):
        """Resolve the key auto-seed at start-up, and write the answer down.

        Writing it down is what keeps it stable: without a stored value the
        next start could not tell a new install from an old one, and a change
        of default would flip an old install's pairing without a word. The
        notice for an existing install is logged once, because after this the
        value is stored."""
        value, why = self._bootstrap_seed_pref(prefs, existing)
        if why == "stored":
            return value
        try:
            target = getattr(self, "pluginPrefs", None)
            if target is None:
                target = prefs
            target["bootstrapKeySeed"] = value
            self.savePluginPrefs()
        except Exception as exc:
            log(f"[Security] could not record the key auto-seed setting ({exc}); "
                f"it is {'on' if value else 'off'} for this run", level="WARNING")
        if why == "kept":
            log("[Security] Auto-seed the API key to LAN browsers is ON for this install, as it "
                "always has been: any device on your home network or tailnet that opens the "
                "dashboards is handed the full API key, a visitor's phone included. New installs "
                "now start with it off. To switch it off: Plugins > Dashboards > Configure, untick "
                "it, then pair each of your own devices once with Plugins > Dashboards > Generate "
                "One-Time Setup Link (+QR). Devices already paired keep working.",
                level="WARNING")
        else:
            log("[Security] Auto-seed the API key is off (the default for a new install). Pair "
                "each device once with Plugins > Dashboards > Generate One-Time Setup Link (+QR).")
        return value

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
        cams = _parse_cameras(DASHBOARDS_CAMERAS or prefs.get("camerasJson", ""))
        store = {
            "cameras":      cams,
            "swapOutHost":  (prefs.get("swapOutHost", "") or "").strip(),
            "mainCameras":  self._main_cameras_as_hosts(DASHBOARDS_MAIN_CAMERAS, cams),
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

    @staticmethod
    def _main_cameras_as_hosts(entries, cams):
        """The legacy hub-mosaic list as camera HOSTS (review 24-09-2026).

        The key has always meant hosts, but the example secrets file said
        names, so a list like ["Drive", "Front Door"] was imported verbatim:
        an empty mosaic, and every MCP camera write refused until one Settings
        save. A name that matches a camera (ignoring case) becomes its host;
        anything matching neither is dropped with a WARNING naming it."""
        by_host = {c["host"] for c in cams}
        by_name = {c["name"].strip().lower(): c["host"] for c in cams}
        out = []
        for e in (entries if isinstance(entries, (list, tuple)) else []):
            text = str(e).strip()
            host = text if text in by_host else by_name.get(text.lower())
            if host is None:
                log(f"[Config] DASHBOARDS_MAIN_CAMERAS entry {text!r} is neither a camera "
                    f"host nor a camera name, so it was left out of the hub mosaic",
                    level="WARNING")
            elif host not in out:
                out.append(host)
        return out

    # Set by _load_config_store when dashboards_config.json exists but cannot
    # be read. While it is set, _save_config_store refuses to write.
    _store_unreadable = ""

    def _load_config_store(self):
        """Read dashboards_config.json.

        Returns {} when the file is ABSENT, and __init__ then imports the
        legacy settings once. A file that is PRESENT but will not parse, or is
        not a JSON object, is a different case and must not be treated as
        absent: the import used to run, save, and in saving copy the broken
        file over the one good .bak, so one typo in a hand edit plus a restart
        lost the cameras, favourites and the control PIN for good. Now it logs
        an ERROR naming the file, copies it aside once, returns {} and sets
        _store_unreadable, which stops __init__ importing and stops every
        save until the file is fixed and the plugin restarted."""
        try:
            path = self._config_store_path()
        except Exception as exc:
            log(f"[Config] Could not locate dashboards_config.json ({exc})", level="WARNING")
            return {}
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            problem = f"it holds a JSON {type(data).__name__}, not an object"
        except Exception as exc:
            problem = str(exc)
        self._store_unreadable = path
        aside = self._set_aside_unreadable_store(path)
        log(f"[Config] {path} could not be read ({problem}). The dashboards are running "
            f"with no saved settings, and Settings will refuse to save so the file is "
            f"not overwritten. Fix the file (or restore {os.path.basename(path)}.bak) and "
            f"restart the plugin."
            + (f" A copy of the unreadable file is at {aside}." if aside else ""),
            level="ERROR")
        return {}

    @staticmethod
    def _set_aside_unreadable_store(path):
        """Copy an unreadable store to <name>.corrupt-<unix seconds> (0600), a
        name no save ever writes. Once per distinct content: a copy with the
        same bytes already beside it is reused, so a restart loop does not fill
        the folder. Returns the copy's path, or "" when it could not be made."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            folder, base = os.path.split(path)
            for name in sorted(os.listdir(folder)):
                if name.startswith(base + ".corrupt-"):
                    other = os.path.join(folder, name)
                    try:
                        with open(other, "rb") as f:
                            if f.read() == raw:
                                return other
                    except OSError:
                        continue
            dest = f"{path}.corrupt-{int(time.time())}"
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            return dest
        except Exception as exc:
            log(f"[Config] could not copy the unreadable dashboards_config.json aside: {exc}",
                level="WARNING")
            return ""

    @staticmethod
    def _reads_as_store(path):
        """True when the file at path parses as a JSON object."""
        try:
            with open(path, encoding="utf-8") as f:
                return isinstance(json.load(f), dict)
        except Exception:
            return False

    def _save_config_store(self, data):
        """Atomically persist the editor's config. Raises on failure.
        Keeps a one-deep .bak of the PREVIOUS good config first, so a bad save
        (e.g. an empty form harvested after a failed load — the settings page
        guards against this client-side too) is always recoverable by hand.

        Refuses outright while the store read at startup was unreadable (see
        _load_config_store): the Settings page gets an error rather than
        replacing the file with whatever it happened to be showing. And the
        .bak is only taken from a file that parses — copying a broken file
        over it destroyed the one good copy."""
        if getattr(self, "_store_unreadable", ""):
            raise RuntimeError(
                "dashboards_config.json could not be read when the plugin started, so "
                "saving is switched off to avoid overwriting it. Fix the file and "
                "restart the plugin")
        path = self._config_store_path()
        try:
            if os.path.isfile(path) and self._reads_as_store(path):
                import shutil
                shutil.copy2(path, path + ".bak")
                os.chmod(path + ".bak", 0o600)
        except Exception as exc:
            log(f"[Config] could not back up dashboards_config.json: {exc}", level="WARNING")
        data = dict(data)
        data["_savedAt"] = time.time()
        # Serialised BEFORE the file is opened, and strictly (review
        # 24-09-2026): a NaN written as a bare NaN makes the file, and every
        # config reply built from it, invalid JSON to a browser.
        text = json.dumps(data, indent=2, sort_keys=True, allow_nan=False)
        tmp  = path + ".tmp"
        # 0600 (v2.95.2): the store carries the control PIN in clear, and it
        # was written under the default umask — 0644, plus every .bak beside it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
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
                # stillsToken names the private stills folder: it stays on
                # the server, and _apply_config carries it over on a save.
                if k not in out and not str(k).startswith("_") and k != "stillsToken":
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
        """_apply_config_checked, with any fault it did not foresee answered as
        a JSON error (review 24-09-2026). A malformed value from a raw POST or
        the raw-JSON escape hatch used to raise out of the handler, and IWS
        answered a bare 500 with no reason."""
        try:
            return self._apply_config_checked(cfg)
        except Exception as exc:
            self.logger.error(f"[Config] could not apply the settings: "
                              f"{type(exc).__name__}: {exc}")
            return self._evo_reply(
                {"ok": False, "error": f"the settings could not be applied: {exc}"},
                status=500)

    def _apply_config_checked(self, cfg):
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
        # and WebRTC signalling URLs — an arbitrary string here is a config/URL
        # injection. IP addresses or plain hostnames only.
        _host_ok = CAMERA_HOST_RE        # shared with _vet_cameras (the running list)
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
        # Types checked before use (review 24-09-2026): an int here raised
        # TypeError and a non-string swapOutHost AttributeError, both as 500s.
        main_cams = cfg.get("mainCameras") or []
        if not isinstance(main_cams, list) or any(not isinstance(h, str) for h in main_cams):
            errors.append("mainCameras must be a list of camera hosts")
            main_cams = []
        swap_in = cfg.get("swapOutHost")
        if swap_in is not None and not isinstance(swap_in, str):
            errors.append("swapOutHost must be a camera host")
            swap_in = ""
        cam_hosts = {c.get("host") for c in cameras if isinstance(c, dict)}
        for h in main_cams:
            if h not in cam_hosts:
                errors.append(f"mainCameras entry {h} is not in the cameras list")
        # A swap-out host that matches no camera (the camera was re-addressed
        # or deleted) points at nothing: drop it, which means "the last in the
        # list", rather than store a dead value without a word.
        swap_in = (swap_in or "").strip()
        if swap_in and swap_in not in cam_hosts:
            self.logger.info(f"[Config] swap-out host {swap_in} is not one of the cameras "
                             f"any more — cleared (the last camera in the list is used)")
            swap_in = ""
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
        # The stills folder token is the server's, never the client's: a
        # Settings save can neither set nor clear it, and the running value is
        # carried over so the folder the pages were told about stays put.
        clean.pop("stillsToken", None)
        _stills_tok = self._stills_token()
        if _stills_tok:
            clean["stillsToken"] = _stills_tok
        clean.update({
            "cameras":      cameras,
            "mainCameras":  list(main_cams),
            "swapOutHost":  swap_in,
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
                            except (TypeError, ValueError, OverflowError):   # inf
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
                            band = float(band_val)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(band):       # "nan" parses; JSON cannot carry it
                            item[band_key] = band
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
        # A key passed through untouched can still hold NaN or Infinity from
        # the raw-JSON escape hatch; say so as a 400 rather than store it.
        try:
            json.dumps(clean, allow_nan=False)
        except ValueError:
            return self._evo_reply({"ok": False, "error": "a setting holds a number that is "
                                    "not finite (NaN or Infinity)"}, status=400)
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
