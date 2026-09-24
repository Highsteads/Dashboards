#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    publish_mixin.py
# Description: Publishing the pages: copying them into Web Assets/public/dashboards,
#              and writing config.js with the feature flags for optional plugins.
#              Split out of plugin.py in v3.32.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0

try:
    import indigo
except ImportError:
    pass

import json
import os

from dash_common import (
    CAMERA_POLL_SECONDS,
    CAMERA_THUMB_WIDTH,
    COLOUR_PRESETS,
    LIVE_POOL_SIZE,
    PROXY_PORT,
    PAGES_SOURCE_DIR,
    PUBLIC_SUBDIR,
    log,
)


class PublishMixin:
    def _lan_origin(self):
        """The Indigo web server's origin at the detected LAN address, e.g.
        http://192.168.1.10:8176, or "" when no LAN address was found.

        The scheme and port come from api_url (INDIGO_URL), with only the host
        swapped for the LAN address, because the IWS port is configurable and
        can be https. A hardcoded http://<lan>:8176 was a dead link on any
        install that had changed either. With no api_url: http and 8176, the
        Indigo defaults. An api_url with no port keeps its scheme's default.
        """
        lan = getattr(self, "lan_ip", "") or ""
        if not lan:
            return ""
        from urllib.parse import urlsplit
        raw = (getattr(self, "api_url", "") or "").strip()
        try:
            parts = urlsplit(raw) if raw else None
            scheme = (parts.scheme or "http").lower() if parts else "http"
            port = parts.port if parts else 8176
        except ValueError:                   # a malformed port in the setting
            scheme, port = "http", 8176
        if scheme not in ("http", "https"):
            scheme, port = "http", 8176
        host = f"[{lan}]" if ":" in lan else lan
        return f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"

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
        # The whole tree (review 24-09-2026): demo mode's DashUI.message reads
        # demo-data/api/<name>.json since 3.39, and a top-level-only copy left
        # every such card on an installed plugin saying "not in the demo".
        demo_src = os.path.join(src, "demo-data")
        if os.path.isdir(demo_src):
            demo_dst = os.path.join(dst, "demo-data")
            try:
                for here, dirs, files in os.walk(demo_src):
                    dirs[:] = sorted(d for d in dirs
                                     if not os.path.islink(os.path.join(here, d)))
                    rel = os.path.relpath(here, demo_src)
                    out = demo_dst if rel == "." else os.path.join(demo_dst, rel)
                    os.makedirs(out, exist_ok=True)
                    for name in sorted(files):
                        if not name.endswith(".json"):
                            continue
                        sp = os.path.join(here, name)
                        dp = os.path.join(out, name)
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
            # v3.33.0: views and cards that draw what a companion script
            # writes hide when it is not installed, so a new user never
            # meets an empty page (Timeline's Nights view, the laundry plan).
            "scripts":         self._companion_scripts_installed(),
            # The room page's device catalog is not shipped in the bundle; an
            # outside tool may put one in /public/dashboards. Published so the
            # page asks for it only where it exists, rather than 404ing (which
            # IWS logs) on every room view of every other install.
            "catalog":         self._catalog_published(),
        }

    def _catalog_published(self):
        """True when a catalog.json sits in the public dashboards folder."""
        try:
            return os.path.isfile(os.path.join(self._public_dashboards_dir(), "catalog.json"))
        except Exception:
            return False            # cannot tell: the page falls back to live inference

    # The companion script each optional view reads, by the key config.js uses.
    _SCRIPT_FLAGS = {"presence": "Presence_Watch.py", "laundry": "Appliance_Scheduler.py"}

    def _companion_scripts_installed(self):
        try:
            base = self._scripts_dir()
        except Exception:
            return {k: True for k in self._SCRIPT_FLAGS}   # cannot tell: never hide
        return {k: os.path.isfile(os.path.join(base, name))
                for k, name in self._SCRIPT_FLAGS.items()}

    # Marks _config_js_flags after a failed config.js write, so the tick retries.
    _CONFIG_JS_UNWRITTEN = "_unwritten"

    def _refresh_feature_flags(self):
        """Tick task (every 30 s): rewrite config.js when an optional plugin
        has appeared or gone since the last write, so the pages follow an
        install or removal without a restart. Returns True when it rewrote."""
        last = getattr(self, "_config_js_flags", None)
        if last is None:
            return False            # startup has not written config.js yet
        if last.get(self._CONFIG_JS_UNWRITTEN):
            self._write_config_js()     # the last write failed: try again, say nothing new
            return True
        flags = self._feature_flags()
        if flags == last:
            return False
        for key, label in (("sigenAvailable", "SigenEnergyManager"),
                           ("heatingControls", "EvoHomeControl")):
            if flags.get(key) != last.get(key):
                self.logger.info(f"[Config] {label} is now "
                                 f"{'present' if flags.get(key) else 'absent'} — "
                                 f"config.js rewritten so the pages follow")
        for key, name in self._SCRIPT_FLAGS.items():
            now_, was = (flags.get("scripts") or {}).get(key), (last.get("scripts") or {}).get(key)
            if now_ != was:
                self.logger.info(f"[Config] {name} is now {'installed' if now_ else 'missing'} — "
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
        # Objects only (review 24-09-2026): the load already filters, and this
        # file is built in startup(), where a raise stops the plugin starting.
        cfg["favourites"] = [dict(f) for f in self.favourites if isinstance(f, dict)]
        # Custom links (v2.x): full-size hub tiles opening an arbitrary URL.
        # {title,url,desc?,icon?} — just a link, no secret, safe in config.js.
        cfg["customLinks"] = [dict(l) for l in self.custom_links if isinstance(l, dict)]
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
        # Carbon region 0 = "Off (not in Great Britain)": the menu drops the
        # tile and the advisor never calls the GB-only API.
        try:
            cfg["carbon"] = int((getattr(self, "pluginPrefs", None) or {}).get("carbonRegionId", 4) or 4) != 0
        except (TypeError, ValueError):
            cfg["carbon"] = True
        # The LAN origin, for the "you are on the reflector — at home use
        # this" notice (v2.96.1). config.js is what a reflector-origin page
        # has to hand, so this is the one place it can learn the LAN address.
        cfg["lanURL"] = self._lan_origin() or (self.api_url or "")
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
        # as static files into a token-named folder under /public, so
        # credentials never leave the server and the pictures are not at a
        # name anyone can guess.
        cam_cfg = {
            "hosts":          [c["host"] for c in self.cameras],
            "names":          {c["host"]: c["name"] for c in self.cameras},
            "slugs":          {c["host"]: self._cam_slug(c["name"]) for c in self.cameras},
            # No imagePattern / thumbPattern here any more: the stills live in
            # a folder named by a secret token, and this file is anonymous. A
            # page asks the Bearer-authenticated cameraStills action for them.
            "thumbWidth":     CAMERA_THUMB_WIDTH,
            "pollSeconds":    CAMERA_POLL_SECONDS,
            "proxyPort":      PROXY_PORT,                  # the plugin's own port: WebRTC signalling
            "webrtcPath":     "/webrtc/{host}",            # WHEP signalling, on proxyPort
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
            # Recorded only once the file is written (review 24-09-2026). It
            # was set before the write, so a failed write read as published
            # and the 30 s tick, seeing no change, never tried again.
            self._config_js_flags = dict(flags)
        except Exception as e:
            log(f"Failed to write {path}: {e}", level="ERROR")
            self._config_js_flags = {self._CONFIG_JS_UNWRITTEN: True}   # the tick retries
