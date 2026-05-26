#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Dashboards plugin — at startup, copies the HTML pages from the
#              plugin bundle into Indigo's `Web Assets/public/dashboards/`
#              folder so they are served WITHOUT HTTP Basic Auth (the IWS
#              `public/` namespace is the only path that bypasses auth).
#              Reads INDIGO_URL / INDIGO_API_KEY from IndigoSecrets.py and
#              writes them into `config.js` alongside the copied pages.
#              Polls Dahua cameras in a background thread using HTTP Digest
#              auth (DAHUA_USER / DAHUA_PASS from IndigoSecrets.py) and writes
#              the JPEGs as cam-<ip>.jpg into the same public folder, so
#              cameras.html loads them same-origin with no browser auth.
#              Also runs a tiny HTTP MJPEG proxy on port 8177 that relays each
#              camera's live multipart/x-mixed-replace stream to the browser,
#              again handling Digest auth server-side. The page uses MJPEG
#              for the live grid and falls back to the still snapshot if a
#              stream connection fails.
# Author:      CliveS & Claude Opus 4.7
# Date:        26-05-2026
# Version:     1.18.0
#
# v1.17.1 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. Module-level log() helper bumped to ms.
# New "Toggle Timestamps in Log" menu item.

try:
    import indigo
except ImportError:
    pass

import json
import os
import shutil
import sys as _sys
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
try:
    from IndigoSecrets import SIGEN_DASHBOARD_URL
except ImportError:
    SIGEN_DASHBOARD_URL = ""
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


# ============================================================
# Constants
# ============================================================

PLUGIN_ID         = "com.clives.indigoplugin.dashboards"
PLUGIN_VERSION    = "1.18.0"
# Pages are mirrored into Web Assets/public/dashboards/ so IWS serves them
# WITHOUT HTTP Basic Auth. Indigo only treats the global /public/ namespace
# as anonymous — per-plugin `public/` subfolders still require auth.
PUBLIC_SUBDIR     = "dashboards"
INDEX_PATH        = f"/public/{PUBLIC_SUBDIR}/index.html"

# Source folder inside the plugin bundle that holds the HTML pages we mirror.
PAGES_SOURCE_DIR  = os.path.join(CONTENTS_DIR, "Resources", "static", "pages")

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
CAMERA_POLL_SECONDS  = 2.0                                 # snapshot poll interval per camera (drives the thumbnail tiles; only the 3 still cams are actually polled — live cams skipped)
LIVE_POOL_SIZE       = 6                                   # how many cameras run live MJPEG on cameras.html. Browsers cap HTTP/1.1 connections per origin at ~6, so don't exceed that.
CAMERA_HTTP_TIMEOUT  = 15.0                                # per-snapshot timeout (4K snapshots can take 5-10s on busy cams)

# Populated at __init__ from IndigoSecrets / PluginConfig. Keep as
# module-level state so the many existing reference sites below don't need
# rewriting; __init__ overwrites these in place.
CAMERAS       = []
SWAP_OUT_HOST = ""


def _parse_cameras(value):
    """Parse camera config — accepts a JSON string, a Python list, or empty.

    Required keys per entry: ``host``, ``name``, ``vendor`` (in {"dahua",
    "hikvision"}).
    Optional: ``room`` — the dashboard room this cam should also appear on
    (e.g. "Garage"). The room name must match an entry in ROOM_FOLDERS for
    the camera to land on a room page; otherwise it's silently ignored by
    the room template but still shows on the main cameras page.
    Invalid entries are silently dropped.
    """
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if not isinstance(value, list):
        return []
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        if not all(k in entry for k in ("host", "name", "vendor")):
            continue
        cleaned.append({
            "host":   str(entry["host"]),
            "name":   str(entry["name"]),
            "vendor": str(entry["vendor"]).lower(),
            "room":   str(entry.get("room", "")).strip(),
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

# Vendor URL templates: {host} {user} {pass} are substituted. RTSP paths
# target the mainstream H.264 channel so go2rtc has the highest-quality source
# to transcode into MJPEG.
VENDOR_URLS = {
    "dahua": {
        "snapshot_path": "/cgi-bin/snapshot.cgi",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/cam/realmonitor?channel=1&subtype=0",
    },
    "hikvision": {
        "snapshot_path": "/ISAPI/Streaming/channels/101/picture",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/Streaming/Channels/101",
    },
}

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
GO2RTC_WEBRTC_PORT   = 8555
GO2RTC_RTSP_PORT     = 8554            # exposed for completeness; not used by the page


# ============================================================
# Helpers
# ============================================================

def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=level)


# ============================================================
# Plugin class
# ============================================================

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.timestamp_enabled = bool(pluginPrefs.get("timestampEnabled", True))
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        self.api_key     = (INDIGO_API_KEY or CLAUDEBRIDGE_BEARER_TOKEN or "").strip()
        self.api_url     = (INDIGO_URL or "").strip()
        self.cam_user    = (DAHUA_USER or "").strip()
        self.cam_pass    = (DAHUA_PASS or "").strip()

        # Sigen dashboard link target — empty means the "Open Legacy Sigen
        # Dashboard" menu item is silently disabled. IndigoSecrets first,
        # PluginConfig fallback.
        self.sigen_legacy_url = (SIGEN_DASHBOARD_URL or pluginPrefs.get("sigenLegacyUrl", "")).strip()

        # Cameras — populate the module-level state so all existing reference
        # sites (go2rtc config, snapshot pollers, MJPEG proxy, etc.) see the
        # configured list.
        global CAMERAS, SWAP_OUT_HOST
        cam_source = DASHBOARDS_CAMERAS or pluginPrefs.get("camerasJson", "")
        CAMERAS    = _parse_cameras(cam_source)
        # Default swap-out = last entry in the list (the cam most likely to be
        # safe to drop from the live MJPEG pool). Override via PluginConfig
        # "swapOutHost" if a different cam is the better drop candidate.
        swap_pref     = (pluginPrefs.get("swapOutHost", "") or "").strip()
        SWAP_OUT_HOST = swap_pref if swap_pref else (CAMERAS[-1]["host"] if CAMERAS else "")

        # LAN IP — used by the go2rtc WebRTC config and the startup log line.
        # Detect once at __init__; the hostname doesn't change at runtime.
        self.lan_ip = _detect_lan_ip()

        secrets_state = self._secrets_state()
        cam_state     = self._camera_state()

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    def _secrets_state(self):
        if INDIGO_API_KEY:
            return "INDIGO_API_KEY"
        if CLAUDEBRIDGE_BEARER_TOKEN:
            return "CLAUDEBRIDGE_BEARER_TOKEN (fallback)"
        return "missing — page will prompt for credentials"

    def _camera_state(self):
        if self.cam_user and self.cam_pass:
            return f"{len(CAMERAS)} configured (DAHUA_USER/DAHUA_PASS from IndigoSecrets)"
        return f"{len(CAMERAS)} configured but DAHUA_USER/DAHUA_PASS missing"

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
        EXT = (".html", ".png", ".js")            # .js for standalone-nav.js
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
                    shutil.copy2(mf_src, mf_dst)
                    log(f"Synced manifest.json to {dst}")
            except Exception as exc:
                log(f"Manifest copy failed: {exc}", level="WARNING")

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

        # Cameras: only publish host list + display names to the browser. The
        # plugin polls each camera itself with Digest auth and writes the JPEGs
        # as static files into the public folder, so credentials never leave
        # the server.
        cam_cfg = {
            "hosts":          [c["host"] for c in CAMERAS],
            "names":          {c["host"]: c["name"] for c in CAMERAS},
            "slugs":          {c["host"]: self._cam_slug(c["name"]) for c in CAMERAS},
            "imagePattern":   "cam-{host}.jpg",            # snapshot fallback
            "pollSeconds":    CAMERA_POLL_SECONDS,
            "mjpegPort":      MJPEG_PROXY_PORT,            # live MJPEG proxy
            "mjpegPath":      "/mjpeg/{host}",             # ?subtype=0 (HD) / 1 (SD)
            "go2rtcPort":     GO2RTC_API_PORT,             # WebRTC backend
            "livePoolSize":   LIVE_POOL_SIZE,              # how many cams run live at once
            "mainCameras":    list(DASHBOARDS_MAIN_CAMERAS or []),  # ordered IPs for the index.html mosaic
            "swapOutHost":    SWAP_OUT_HOST,               # bumped to still when peeking a non-default cam
        }

        source = self._secrets_state()
        body = (
            "// Generated by Dashboards plugin at startup. Do not edit by hand.\n"
            "// If INDIGO_URL and INDIGO_API_KEY are set in IndigoSecrets.py the\n"
            "// dashboards auto-connect; otherwise the connection form is shown.\n"
            f"window.INDIGO_CONFIG = {json.dumps(cfg)};\n"
            f"window.INDIGO_CONFIG_SOURCE = {json.dumps(source)};\n"
            f"window.CAMERA_CONFIG = {json.dumps(cam_cfg)};\n"
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
    # MJPEG proxy (tiny HTTP server in a daemon thread)
    # --------------------------------------------------------

    def _start_mjpeg_proxy(self):
        """Bind a small HTTP server to MJPEG_PROXY_PORT and serve one endpoint
        per camera. Each request opens an upstream MJPEG stream to the camera
        (Digest auth) and pipes the multipart bytes straight to the client.
        Per-request thread because socketserver's ThreadingMixIn handles each
        connection on its own thread — fine for 3 cameras × a few viewers."""
        if not (self.cam_user and self.cam_pass):
            log("[MJPEG] DAHUA_USER/DAHUA_PASS not set — MJPEG proxy disabled",
                level="WARNING")
            self._mjpeg_server = None
            return

        import http.server
        import socketserver
        import threading
        from urllib.parse import urlparse, parse_qs

        # Map host → go2rtc stream slug. The MJPEG proxy targets go2rtc's
        # transcoded-MJPEG endpoint (mainstream H.264 → MJPEG via ffmpeg) so
        # the picture stays sharp regardless of how the camera's own MJPEG
        # substream is configured. Goodbye Garage shimmer.
        host_to_slug  = {c["host"]: self._cam_slug(c["name"]) for c in CAMERAS}
        allowed_hosts = set(host_to_slug.keys())
        plugin_self   = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            # Silence default per-request access logging — we'd flood the event log.
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                # Routes:
                #   /mjpeg/<host>?subtype=N    → live multipart stream
                #   /streams                   → go2rtc /api/streams (with CORS)
                #   /healthz                   → "ok"
                parsed = urlparse(self.path)
                if parsed.path == "/healthz":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return

                if parsed.path == "/streams":
                    # Proxy go2rtc's stats JSON. Lets the page poll byte counters
                    # for the bandwidth indicator without cross-origin headaches.
                    import urllib.request
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{GO2RTC_API_PORT}/api/streams",
                                timeout=2.0) as r:
                            payload = r.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    except Exception as exc:
                        self.send_error(502, f"go2rtc unreachable: {exc}")
                    return

                if not parsed.path.startswith("/mjpeg/"):
                    self.send_error(404, "not found")
                    return

                host = parsed.path[len("/mjpeg/"):]
                if host not in allowed_hosts:
                    self.send_error(403, "host not allowed")
                    return

                qs   = parse_qs(parsed.query or "")
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
                    # CORS: pages are same-host but different port → cross-origin.
                    # <img> doesn't need CORS but explicit header doesn't hurt.
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    for chunk in r.iter_content(chunk_size=16384):
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
        log(f"[MJPEG] Proxy listening on :{MJPEG_PROXY_PORT}")

    def _stop_mjpeg_proxy(self):
        if getattr(self, "_mjpeg_server", None):
            try:
                self._mjpeg_server.shutdown()
                self._mjpeg_server.server_close()
                log("[MJPEG] Proxy stopped")
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
        """Generate go2rtc.yaml from CAMERAS + DAHUA_USER/PASS. Each camera
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
            f"  listen: ':{GO2RTC_API_PORT}'",
            "  origin: '*'",                               # accept cross-origin WS for live.html
            "",
            "rtsp:",
            f"  listen: ':{GO2RTC_RTSP_PORT}'",
            "",
            "webrtc:",
            f"  listen: ':{GO2RTC_WEBRTC_PORT}/tcp'",
            "  candidates:",
            f"    - {self.lan_ip}:{GO2RTC_WEBRTC_PORT}",
            "    - stun:8555",
            "",
            "log:",
            "  level: info",
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
                "Install Homebrew ffmpeg or set GO2RTC_FFMPEG_BIN.", level="WARNING")
        lines += ["streams:"]
        # Two streams per camera:
        #   <slug>        = mainstream H.264 RTSP (vendor-specific URL).
        #                   Available for direct RTSP consumers; not used by
        #                   the page after retiring live.html.
        #   <slug>_mjpeg  = mainstream H.264 transcoded → MJPEG via ffmpeg.
        #                   Consumed by the plugin's MJPEG proxy so the page
        #                   gets sharp mainstream-quality MJPEG without any
        #                   substream encoder shimmer (UI3-style trick).
        for cam in CAMERAS:
            slug   = self._cam_slug(cam["name"])
            vendor = cam.get("vendor", "dahua")
            tpl    = VENDOR_URLS.get(vendor, VENDOR_URLS["dahua"])["rtsp_main"]
            rtsp   = tpl.format(user=user_q, pwd=pass_q, host=cam["host"])
            lines.append(f"  {slug}: {rtsp}")
            # ffmpeg: source is the named stream <slug>; #video=mjpeg adds an
            # MJPEG re-encode in front of go2rtc's MJPEG consumer.
            lines.append(f"  {slug}_mjpeg: ffmpeg:{slug}#video=mjpeg")

        path = self._go2rtc_config_path()
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)        # contains credentials — owner-readable only
        log(f"[go2rtc] Wrote config {path} ({len(CAMERAS)} streams)")
        return path

    @staticmethod
    def _cam_slug(name):
        """Stable stream name for a camera: lowercase, spaces → underscores."""
        return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")

    def _start_go2rtc(self):
        """Launch go2rtc as a subprocess. We don't keep stdout in memory —
        it's redirected to a logfile so the event log stays clean."""
        if not (self.cam_user and self.cam_pass):
            log("[go2rtc] DAHUA_USER/DAHUA_PASS not set — WebRTC backend disabled",
                level="WARNING")
            self._go2rtc_proc = None
            return
        if not os.path.isfile(GO2RTC_BIN) or not os.access(GO2RTC_BIN, os.X_OK):
            log(f"[go2rtc] Binary not found or not executable at {GO2RTC_BIN} — "
                f"live.html will not work. Install: download go2rtc_mac_arm64.zip "
                f"from https://github.com/AlexxIT/go2rtc/releases", level="WARNING")
            self._go2rtc_proc = None
            return

        cfg = self._write_go2rtc_config()
        import subprocess
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
            log_f = open(self._go2rtc_log_path(), "ab", buffering=0)
            self._go2rtc_logfile = log_f
            self._go2rtc_proc = subprocess.Popen(
                [GO2RTC_BIN, "-config", cfg],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,    # so SIGTERM to plugin doesn't auto-kill it; we do that explicitly
            )
            log(f"[go2rtc] Started (pid {self._go2rtc_proc.pid}) — "
                f"API http://{self.lan_ip}:{GO2RTC_API_PORT}/")
        except Exception as exc:
            log(f"[go2rtc] Could not start: {exc}", level="ERROR")
            self._go2rtc_proc = None

    def _mirror_go2rtc_assets(self):
        """Copy go2rtc's video-stream.js + video-rtc.js into the public dashboards
        folder so live.html can load them same-origin. go2rtc itself doesn't send
        CORS headers, and iOS Safari refuses cross-origin <script type=module>
        imports without them. Runs after the subprocess has had a moment to bind."""
        import urllib.request
        # Give go2rtc a beat to bind :1984 — the bind happens on its main loop
        # which takes ~200-500ms after Popen returns.
        for attempt in range(20):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{GO2RTC_API_PORT}/api",
                                            timeout=1.0) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            log("[go2rtc] API didn't respond within 5s — assets not mirrored",
                level="WARNING")
            return

        dst_dir = self._public_dashboards_dir()
        copied  = 0
        for name in ("video-stream.js", "video-rtc.js"):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{GO2RTC_API_PORT}/{name}",
                        timeout=3.0) as r:
                    data = r.read()
                with open(os.path.join(dst_dir, name), "wb") as f:
                    f.write(data)
                copied += 1
            except Exception as exc:
                log(f"[go2rtc] Could not mirror {name}: {exc}", level="WARNING")
        if copied:
            log(f"[go2rtc] Mirrored {copied} JS asset(s) into {dst_dir}")

    def _stop_go2rtc(self):
        proc = getattr(self, "_go2rtc_proc", None)
        if proc:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=2)
                log(f"[go2rtc] Stopped (pid {proc.pid})")
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

    def _fetch_one_snapshot(self, host):
        """Fetch a single JPEG via go2rtc's /api/frame.jpeg endpoint. This
        decodes one frame from the camera's RTSP stream (the same source
        go2rtc uses for the live MJPEG transcode), so any camera that streams
        will also snapshot — even cameras whose own /snapshot.cgi endpoint is
        broken (e.g. the Patio 4K returns HTTP 500 directly). Bonus: removes
        the vendor-specific snapshot URL handling — go2rtc does that work."""
        import requests
        cam  = next((c for c in CAMERAS if c["host"] == host), None)
        slug = self._cam_slug((cam or {}).get("name", host))
        url  = f"http://127.0.0.1:{GO2RTC_API_PORT}/api/frame.jpeg?src={slug}"
        try:
            r = requests.get(url, timeout=CAMERA_HTTP_TIMEOUT, stream=False)
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            ct = r.headers.get("Content-Type", "")
            if "image" not in ct:
                return False, f"unexpected content-type {ct!r}"
            return True, r.content
        except Exception as exc:
            return False, str(exc)

    def _write_atomic(self, path, data):
        """Write bytes to a temp file then rename — avoids the browser ever
        reading a half-written JPEG."""
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

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

    def _active_mjpeg_slugs_from(self, streams):
        """Given a parsed /api/streams dict, return slugs with active consumers."""
        active = set()
        if not streams:
            return active
        suffix = "_mjpeg"
        for name, info in streams.items():
            if name.endswith(suffix) and info.get("consumers"):
                active.add(name[:-len(suffix)])
        return active

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
            payload = dict(streams)
            payload["_writeTs"] = time.time()
            path = os.path.join(self._public_dashboards_dir(), "streams.json")
            self._write_atomic(path, json.dumps(payload).encode("utf-8"))
        except Exception as exc:
            log(f"[Cameras] streams.json write failed: {exc}", level="WARNING")

    # --------------------------------------------------------
    # Rooms map (Lights / Motion / Radiators / Windows / Extras)
    # --------------------------------------------------------

    # Which Indigo device folders are surfaced as dashboard rooms. Anything
    # else (ESPHome / MQTT / RAMSES / Z_Not_Used / Server Room / etc.) is
    # ignored except for the radiator-by-name pass below.
    ROOM_FOLDERS = (
        "Bathroom", "Bedroom 1", "Bedroom 2", "Bedroom 3",
        "Conservatory", "Dining Room", "Drive", "En Suite",
        "Garage", "Garden", "Hall", "Kitchen", "Living Room", "Utility Room",
    )
    # Device classification — used by _build_rooms_json. Keep these short
    # and tweak them based on what gets miscategorised in your install.
    _LIGHT_WORDS    = ("light", "lights", "lamp", "lamps", "spot", "spots",
                       "bulb", "led", "strip", "spotlight", "spotlights")
    _MOTION_WORDS   = ("motion", "presence", "occupancy", "pir")
    _OCCUPANCY_TYPES = ("z2mOccupancySensor",)
    _CONTACT_TYPES   = ("z2mContactSensor", "zwContactSensorType")
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
        # IMPORTANT: gate this on NOT being a Relay/Dimmer — those are output
        # devices (action-group virtuals like "Virtual Garage Door Opener",
        # Shelly relays etc.) which often have "door" in their names but
        # mustn't end up under Windows & Doors.
        is_output = cls in ("RelayDevice", "DimmerDevice")
        if (not is_output) and (typ in self._CONTACT_TYPES
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
        # Build folder_id → room name only for the configured ROOM_FOLDERS.
        try:
            folder_to_room = {
                f.id: f.name for f in indigo.devices.folders.iter()
                if f.name in self.ROOM_FOLDERS
            }
        except Exception as exc:
            log(f"[Rooms] Folder enumeration failed: {exc}", level="WARNING")
            return

        rooms = {n: {"lights": [], "motion": [], "radiators": [],
                     "windows": [], "sensors": [], "extras": [], "cameras": []}
                 for n in self.ROOM_FOLDERS}
        room_names_sorted = sorted(self.ROOM_FOLDERS, key=len, reverse=True)

        # Cameras that opted into a room get attached here. Each camera dict
        # carries its own host/name/vendor — the room template uses host to
        # build the MJPEG proxy URL and name as the tile label.
        for cam in CAMERAS:
            room = (cam.get("room") or "").strip()
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

        # Stable sort within each section by device name for predictable UI.
        # ID-based sections sort via indigo.devices[id].name. Cameras are dicts
        # (host/name) so they're sorted by the name field directly.
        try:
            name_of = lambda i: (indigo.devices[i].name or "").lower()
            ID_SECTIONS = ("lights", "motion", "radiators", "windows", "sensors", "extras")
            for room in rooms.values():
                for k in ID_SECTIONS:
                    room[k].sort(key=name_of)
                room["cameras"].sort(key=lambda c: c.get("name", "").lower())
        except Exception:
            pass

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
        extras_cfg = DASHBOARDS_ROOM_EXTRAS if isinstance(DASHBOARDS_ROOM_EXTRAS, dict) else {}
        for room_name, room_data in rooms.items():
            cfg = extras_cfg.get(room_name) or {}
            # (1) hide
            hide_ids = set(cfg.get("hideDeviceIds") or [])
            if hide_ids:
                for k in ("lights", "motion", "radiators", "windows", "sensors", "extras"):
                    room_data[k] = [i for i in room_data[k] if i not in hide_ids]
            # (2) include — append; dedupe per section; also pull the same
            # ID out of `extras` so it doesn't appear twice when rooms.json
            # is inspected (extras isn't rendered today, but cleaner this way).
            include = cfg.get("include") or {}
            if isinstance(include, dict):
                all_pinned = set()
                for section, ids in include.items():
                    if section not in ("lights", "motion", "radiators", "windows", "sensors", "extras"):
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
                    for k in ("lights", "motion", "radiators",
                              "windows", "sensors", "extras"):
                        room_data[k] = [i for i in room_data[k]
                                        if i not in auto_hide]

        # Re-sort sections after include-merge so manually-added IDs slot in
        # alphabetically next to the auto-classified ones.
        try:
            name_of2 = lambda i: (indigo.devices[i].name or "").lower()
            for room in rooms.values():
                for k in ("lights", "motion", "radiators", "windows", "sensors", "extras"):
                    room[k].sort(key=name_of2)
        except Exception:
            pass

        payload = {
            "_writeTs": time.time(),
            "rooms":    rooms,
        }
        try:
            path = os.path.join(self._public_dashboards_dir(), "rooms.json")
            self._write_atomic(path, json.dumps(payload, indent=2).encode("utf-8"))
        except Exception as exc:
            log(f"[Rooms] rooms.json write failed: {exc}", level="WARNING")

    def _poll_cameras_once(self):
        """One sweep over every configured camera. Skips cams that currently
        have a live MJPEG consumer (the dashboard is already streaming them;
        their cam-<ip>.jpg snapshot is unused). Logs failures throttled (state
        stored in self._cam_state) so the event log doesn't flood when a
        camera is offline for hours."""
        streams      = self._fetch_go2rtc_streams()
        active_slugs = self._active_mjpeg_slugs_from(streams)
        # Mirror the streams JSON for the dashboard bandwidth indicator.
        self._write_streams_json(streams)
        # Rebuild the rooms map (cheap — just enumerates folders + devices).
        # Picks up device-folder moves and renames automatically.
        self._build_rooms_json()
        for cam in CAMERAS:
            host = cam["host"]
            slug = self._cam_slug(cam["name"])
            if slug in active_slugs:
                # Camera is being consumed live; skip the redundant snapshot.
                continue
            st   = self._cam_state.setdefault(host, {"ok_count": 0, "fail_count": 0, "last_log": 0})
            ok, payload = self._fetch_one_snapshot(host)
            now = time.time()
            if ok:
                try:
                    self._write_atomic(self._cam_jpg_path(host), payload)
                    st["ok_count"]   += 1
                    if st["fail_count"] >= 3:                 # camera came back
                        log(f"[Cameras] {cam['name']} ({host}) recovered after {st['fail_count']} failures")
                    st["fail_count"]  = 0
                except Exception as exc:
                    log(f"[Cameras] Could not write snapshot for {host}: {exc}", level="ERROR")
            else:
                st["fail_count"] += 1
                # Log on 1st failure and then every 60s while it keeps failing.
                if st["fail_count"] == 1 or (now - st["last_log"]) > 60:
                    log(f"[Cameras] {cam['name']} ({host}) snapshot failed: {payload}", level="WARNING")
                    st["last_log"] = now

    def runConcurrentThread(self):
        """Main background loop. Indigo calls this once after startup; we keep
        looping until self.stopThread is set during shutdown. self.sleep()
        raises self.StopThread on shutdown — catching it exits cleanly.
        Builds rooms.json on every cycle regardless of whether cameras are
        configured — the room template needs it even on cam-less installs."""
        try:
            self._build_rooms_json()                # populate immediately
            if not (self.cam_user and self.cam_pass):
                log("[Cameras] DAHUA_USER/DAHUA_PASS not set — snapshot poller idle",
                    level="WARNING")
                while True:
                    # Keep rooms.json fresh even without cameras configured.
                    self._build_rooms_json()
                    self.sleep(30.0)
            log(f"[Cameras] Poller started — {len(CAMERAS)} camera(s), every {CAMERA_POLL_SECONDS}s")
            while True:
                t0 = time.time()
                self._poll_cameras_once()           # also calls _build_rooms_json
                dt = time.time() - t0
                self.sleep(max(0.1, CAMERA_POLL_SECONDS - dt))
        except self.StopThread:
            log("[Cameras] Poller stopped")

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def startup(self):
        self._cam_state    = {}                              # populated by poller
        self._mjpeg_server = None
        self._go2rtc_proc  = None
        self._sync_pages_to_public()
        self._write_config_js()
        self._start_mjpeg_proxy()
        self._start_go2rtc()
        self._mirror_go2rtc_assets()
        self.logger.info(f"{self.pluginDisplayName} started")

    def shutdown(self):
        self._stop_mjpeg_proxy()
        self._stop_go2rtc()
        self.logger.info(f"{self.pluginDisplayName} stopped")

    def showPluginInfo(self, valuesDict=None, typeId=None):
        extras = [
            ("Dashboards URL:",    f"http://<server>:8176{INDEX_PATH}"),
            ("Indigo URL:",        self.api_url or "(unset)"),
            ("API key source:",    self._secrets_state()),
            ("Cameras:",           self._camera_state()),
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
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")

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
        """Menu: open the legacy Sigenergy mini-dashboard (configurable URL).

        Resolved from IndigoSecrets.SIGEN_DASHBOARD_URL first, PluginConfig
        `sigenLegacyUrl` next. If neither is set we log a hint and return —
        the menu item still exists but is a no-op for users who don't run a
        Sigen dashboard.
        """
        if not self.sigen_legacy_url:
            log("[Menu] No Sigen dashboard URL configured. Set SIGEN_DASHBOARD_URL "
                "in IndigoSecrets.py OR fill in Sigen Dashboard URL under Plugins "
                "-> Dashboards -> Configure.", level="WARNING")
            return True
        log(f"[Menu] Legacy Sigen dashboard: {self.sigen_legacy_url}")
        try:
            import webbrowser
            opened = webbrowser.open(self.sigen_legacy_url, new=2)
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
            self.api_url  = (getattr(IndigoSecrets, "INDIGO_URL", "") or "").strip()
            self.api_key  = (getattr(IndigoSecrets, "INDIGO_API_KEY", "")
                             or getattr(IndigoSecrets, "CLAUDEBRIDGE_BEARER_TOKEN", "")
                             or "").strip()
            self.cam_user = (getattr(IndigoSecrets, "DAHUA_USER", "") or "").strip()
            self.cam_pass = (getattr(IndigoSecrets, "DAHUA_PASS", "") or "").strip()
        except Exception as exc:
            log(f"[Menu] Reload IndigoSecrets failed: {exc}", level="ERROR")
            return False
        self._sync_pages_to_public()
        self._write_config_js()
        return True
