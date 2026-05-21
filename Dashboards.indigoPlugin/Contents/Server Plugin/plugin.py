#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Dashboards plugin — at startup, copies the HTML pages from the
#              plugin bundle into Indigo's `Web Assets/public/dashboards/`
#              folder so they are served WITHOUT HTTP Basic Auth (the IWS
#              `public/` namespace is the only path that bypasses auth).
#              Reads INDIGO_URL / INDIGO_API_KEY from IndigoSecrets.py and
#              writes them into `config.js` alongside the copied pages.
# Author:      CliveS & Claude Opus 4.7
# Date:        17-05-2026
# Version:     1.4.0

try:
    import indigo
except ImportError:
    pass

import json
import os
import shutil
import sys as _sys
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


# ============================================================
# Constants
# ============================================================

PLUGIN_ID         = "com.clives.indigoplugin.dashboards"
PLUGIN_VERSION    = "1.4.0"
# Pages are mirrored into Web Assets/public/dashboards/ so IWS serves them
# WITHOUT HTTP Basic Auth. Indigo only treats the global /public/ namespace
# as anonymous — per-plugin `public/` subfolders still require auth.
PUBLIC_SUBDIR     = "dashboards"
INDEX_PATH        = f"/public/{PUBLIC_SUBDIR}/index.html"
SIGEN_LEGACY_URL  = "http://192.168.100.160:8179/"

# Source folder inside the plugin bundle that holds the HTML pages we mirror.
PAGES_SOURCE_DIR  = os.path.join(CONTENTS_DIR, "Resources", "static", "pages")


# ============================================================
# Helpers
# ============================================================

def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", level=level)


# ============================================================
# Plugin class
# ============================================================

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.api_key = (INDIGO_API_KEY or CLAUDEBRIDGE_BEARER_TOKEN or "").strip()
        self.api_url = (INDIGO_URL or "").strip()

        secrets_state = self._secrets_state()

        if log_startup_banner:
            log_startup_banner(pluginId, pluginDisplayName, pluginVersion, extras=[
                ("Dashboards URL:", f"http://<server>:8176{INDEX_PATH}"),
                ("Indigo URL:",     self.api_url or "(unset)"),
                ("API key source:", secrets_state),
            ])
        else:
            indigo.server.log(f"{pluginDisplayName} v{pluginVersion} starting — credentials: {secrets_state}")

    def _secrets_state(self):
        if INDIGO_API_KEY:
            return "INDIGO_API_KEY"
        if CLAUDEBRIDGE_BEARER_TOKEN:
            return "CLAUDEBRIDGE_BEARER_TOKEN (fallback)"
        return "missing — page will prompt for credentials"

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

        # Copy / update — include HTML pages plus PNG icons (apple-touch-icon).
        EXT = (".html", ".png")
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
                    shutil.copy2(sp, dp)
                    copied += 1
            except Exception as exc:
                log(f"Copy failed for {name}: {exc}", level="ERROR")

        # Drop stale files of the synced extensions
        try:
            for name in os.listdir(dst):
                if name.endswith(EXT) and name not in sources:
                    try:
                        os.remove(os.path.join(dst, name))
                        log(f"Removed stale {name} from {dst}")
                    except Exception as exc:
                        log(f"Could not remove stale {name}: {exc}", level="WARNING")
        except Exception as exc:
            log(f"Stale scan failed in {dst}: {exc}", level="WARNING")

        log(f"Synced {copied} of {len(sources)} asset(s) to {dst}")
        return copied

    def _write_config_js(self):
        """Write window.INDIGO_CONFIG and INDIGO_CONFIG_SOURCE to config.js.
        Pages load this before their inline IndigoAPI class, so they auto-connect
        when both values are populated and fall back to the form when either is blank.
        NOTE: this file is reachable WITHOUT authentication (Web Assets/public/),
        so the api-key inside is readable by anyone on the LAN. That is the user's
        explicit threat model (Tailscale-only, trusted LAN)."""
        cfg = {}
        if self.api_url and self.api_key:
            cfg = {"baseURL": self.api_url, "apiKey": self.api_key}

        source = self._secrets_state()
        body = (
            "// Generated by Dashboards plugin at startup. Do not edit by hand.\n"
            "// If INDIGO_URL and INDIGO_API_KEY are set in IndigoSecrets.py the\n"
            "// dashboards auto-connect; otherwise the connection form is shown.\n"
            f"window.INDIGO_CONFIG = {json.dumps(cfg)};\n"
            f"window.INDIGO_CONFIG_SOURCE = {json.dumps(source)};\n"
        )
        path = self._config_js_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            log(f"Wrote {path} (configured={bool(cfg)})")
        except Exception as e:
            log(f"Failed to write {path}: {e}", level="ERROR")

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def startup(self):
        self._sync_pages_to_public()
        self._write_config_js()
        self.logger.info(f"{self.pluginDisplayName} started")

    def shutdown(self):
        self.logger.info(f"{self.pluginDisplayName} stopped")

    def showPluginInfo(self, valuesDict=None, typeId=None):
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=[
                ("Dashboards URL:", f"http://<server>:8176{INDEX_PATH}"),
                ("Indigo URL:",     self.api_url or "(unset)"),
                ("API key source:", self._secrets_state()),
            ])
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    # --------------------------------------------------------
    # Menu callbacks
    # --------------------------------------------------------

    def _dashboard_url(self, include_api_key=True):
        """Build the dashboard hub URL, optionally appending ?api-key= so the
        browser doesn't need to do HTTP Digest auth on first visit."""
        base = self.api_url or "http://localhost:8176"
        url  = f"{base}{INDEX_PATH}"
        if include_api_key and self.api_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}api-key={self.api_key}"
        return url

    def menuOpenDashboards(self, valuesDict=None, typeId=None):
        """Menu: open the dashboards hub in the default browser.

        Note: this opens the browser on the Indigo SERVER. If the Indigo
        client is running on a different Mac, the dashboard appears on the
        server's screen, not the client's. The URL (without api-key) is also
        logged so it can be clicked from the event log on any client.
        """
        url_with_key = self._dashboard_url(include_api_key=True)
        url_log      = self._dashboard_url(include_api_key=False)
        log(f"[Menu] Dashboards: {url_log}")
        try:
            import webbrowser
            opened = webbrowser.open(url_with_key, new=2)
            if not opened:
                log("[Menu] Could not auto-open browser — open the URL above manually",
                    level="WARNING")
        except Exception as exc:
            log(f"[Menu] Browser launch failed ({exc}) — open the URL above manually",
                level="WARNING")
        return True

    def menuOpenSigenLegacy(self, valuesDict=None, typeId=None):
        """Menu: open the legacy Sigenergy mini-dashboard (port 8179, Sankey/charts)."""
        log(f"[Menu] Legacy Sigen dashboard: {SIGEN_LEGACY_URL}")
        try:
            import webbrowser
            opened = webbrowser.open(SIGEN_LEGACY_URL, new=2)
            if not opened:
                log("[Menu] Could not auto-open browser — open the URL above manually",
                    level="WARNING")
        except Exception as exc:
            log(f"[Menu] Browser launch failed ({exc}) — open the URL above manually",
                level="WARNING")
        return True

    def menuRegenerateConfig(self, valuesDict=None, typeId=None):
        """Menu: re-read IndigoSecrets and rewrite config.js without a restart.
        Useful after editing IndigoSecrets.py to change URL or API key."""
        # Re-import to pick up live edits to IndigoSecrets.py
        import importlib
        try:
            import IndigoSecrets
            importlib.reload(IndigoSecrets)
            self.api_url = (getattr(IndigoSecrets, "INDIGO_URL", "") or "").strip()
            self.api_key = (getattr(IndigoSecrets, "INDIGO_API_KEY", "")
                            or getattr(IndigoSecrets, "CLAUDEBRIDGE_BEARER_TOKEN", "")
                            or "").strip()
        except Exception as exc:
            log(f"[Menu] Reload IndigoSecrets failed: {exc}", level="ERROR")
            return False
        self._sync_pages_to_public()
        self._write_config_js()
        return True
