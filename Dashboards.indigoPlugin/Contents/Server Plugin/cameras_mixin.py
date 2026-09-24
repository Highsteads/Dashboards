#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    cameras_mixin.py
# Description: Cameras: the go2rtc video service, the :8177 proxy (WebRTC
#              signalling, bootstraps, guest reads), the snapshot poller and its thumbnails, and the
#              stream and camera-health files the Cameras page reads.
#              Split out of plugin.py in v3.32.0; Plugin inherits it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.1 (v3.36.0: MJPEG route and transcode streams removed)

try:
    import indigo
except ImportError:
    pass

import json
import os
import shutil
import threading
import time
from datetime import datetime

from dash_common import (
    CAMERA_DEFAULT_STREAM,
    CAMERA_HOST_RE,
    CAMERA_HTTP_TIMEOUT,
    CAMERA_POLL_MAX_WORKERS,
    CAMERA_RETRY_DELAY,
    CAMERA_SNAPSHOT_WIDTH,
    CAMERA_THUMB_QUALITY,
    CAMERA_THUMB_WIDTH,
    GO2RTC_API_PORT,
    GO2RTC_BIN,
    GO2RTC_LOG_CAP_BYTES,
    GO2RTC_RTSP_PORT,
    GO2RTC_WEBRTC_PORT,
    PROXY_PORT,
    VENDOR_URLS,
    log,
)


def status_reason(text, limit=100):
    """A status-line reason that cannot break the response (review 24-09-2026).

    BaseHTTPRequestHandler writes the reason on the status line as strict
    latin-1, so a non-latin-1 character (the em dash in the /bootstrap
    refusal) raised, the connection closed with no response at all and a
    traceback went to stderr. Exception text can also carry a newline, which
    splits the status line. ASCII, one line, bounded."""
    if text is None:
        return None
    one = " ".join(str(text).split())
    one = one.encode("ascii", "replace").decode("ascii")
    return one if len(one) <= limit else one[: limit - 3] + "..."


def _discard(path):
    """Remove a temp file this plugin created, ignoring every error."""
    try:
        os.remove(path)
    except OSError:
        pass


class SafeErrorMixin:
    """send_error() whose reason is always a safe status line. The full text,
    if it had to change, goes in the body, where it is escaped and encoded as
    UTF-8 by the base class."""

    def send_error(self, code, message=None, explain=None):
        reason = status_reason(message)
        if explain is None and message is not None and reason != message:
            explain = str(message)
        super().send_error(code, reason, explain)


class CamerasMixin:
    # --------------------------------------------------------
    # The :8177 proxy (tiny HTTP server in a daemon thread)
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
        There is NO /api/whep alias (404). The RAW H.264 slug is used —
        WebRTC takes the H.264 straight through with no ffmpeg leg, and the
        answer negotiates H264 payload types.

        This is a SHORT-LIVED request on one of the proxy's per-connection
        threads: go2rtc answers in milliseconds (static candidates, no
        gathering wait), and the MEDIA then flows browser<->go2rtc:8555
        directly — it never transits the plugin process, so this holds
        zero long-lived plugin threads.
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

    _PRIVATE_DNS_SUFFIXES = ("local", "lan", "home", "internal", "localdomain", "home.arpa")

    def _proxy_host_allowed(self, host_header):
        """True when a request's Host header names THIS machine.

        The :8177 server hands out the API key (/bootstrap) and the guest
        token, and its only cross-origin guard compares the Origin's host with
        the Host header. DNS rebinding beats that: a hostile page at
        attacker.example re-points its own name at this Mac's LAN address, so
        the browser sends Host and Origin both as attacker.example, from a
        private source address, and the check passes. A rebinding attacker
        cannot choose the Host header, though, only the name, so refusing any
        name that is not ours closes it.

        Accepted: IP literals (v4 or v6, with or without a port), localhost,
        this Mac's hostname, its short name, and the short name under .local
        or another private suffix (.lan, .home ...), any *.ts.net (Tailscale
        MagicDNS) name, and the host of the configured Indigo URL. Everything
        else, a missing or malformed header included, is refused."""
        import ipaddress
        import socket
        from urllib.parse import urlparse

        h = (host_header or "").strip().lower()
        if not h:
            return False
        if h.startswith("["):                        # [v6] or [v6]:port
            end = h.find("]")
            if end < 0:
                return False
            name, rest = h[1:end], h[end + 1:]
            if rest and not (rest.startswith(":") and rest[1:].isdigit()):
                return False
        elif h.count(":") == 1:                      # name:port or v4:port
            name, port = h.split(":")
            if not port.isdigit():
                return False
        else:                                        # bare name, or a bare v6 literal
            name = h
        name = name.rstrip(".")
        if not name:
            return False
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            pass
        if name == "localhost" or name.endswith(".ts.net"):
            return True
        allowed = set()
        try:
            own = socket.gethostname().lower().rstrip(".")
            if own:
                short = own.split(".")[0]
                allowed.add(own)
                # The short name, and the short name under a suffix no public
                # registrar hands out — what a home router's DNS usually calls
                # the Mac (indigo.lan, indigo.home). An attacker cannot own a
                # name there, so rebinding cannot use it.
                allowed.add(short)
                allowed.update(f"{short}.{sfx}" for sfx in self._PRIVATE_DNS_SUFFIXES)
        except Exception:
            pass
        try:
            api_host = (urlparse(getattr(self, "api_url", "") or "").hostname or "")
            if api_host:
                allowed.add(api_host.lower().rstrip("."))
        except Exception:
            pass
        return name in allowed

    def _start_proxy(self):
        """Bind a small HTTP server to PROXY_PORT for the routes the pages
        cannot reach through IWS: WebRTC signalling (POST /webrtc/<host>),
        the API-key and guest bootstraps, the guest read path and /healthz.
        It carried live MJPEG too until v3.36.0. ThreadingMixIn gives each
        connection its own thread; none of these requests is long-lived."""
        # v1.20.1: the proxy also serves /bootstrap (LAN/Tailscale-only API-key
        # seed for the dashboard pages), so it now starts even with no cameras
        # configured — camera routes just 404 in that case.
        cameras_enabled = bool(self.cam_user and self.cam_pass and self.cameras)
        if not cameras_enabled and not self.api_key:
            log("[Proxy] No cameras configured and no API key — proxy disabled",
                level="WARNING")
            self._proxy_server = None
            return
        if not cameras_enabled:
            if self.cameras:
                log("[Proxy] cameras are configured but DAHUA_USER/DAHUA_PASS are not "
                    "set — camera routes disabled, /bootstrap only", level="WARNING")
            else:
                self.logger.info("[Proxy] no cameras configured — /bootstrap only")

        import http.server
        import ipaddress
        import socketserver
        import threading
        from urllib.parse import urlparse

        # Map host → go2rtc stream slug, for WebRTC signalling.
        host_to_slug  = {c["host"]: self._cam_slug(c["name"]) for c in self.cameras}
        allowed_hosts = set(host_to_slug.keys())
        plugin_self   = self

        class _Handler(SafeErrorMixin, http.server.BaseHTTPRequestHandler):
            # Socket timeout (v2.95.2). StreamRequestHandler applies this to
            # the request socket, so a client that connects and never sends a
            # request line, or a viewer whose write side has stalled, is
            # dropped after 30 s instead of pinning a handler thread for ever.
            timeout = 30

            # Silence default per-request access logging — we'd flood the event log.
            def log_message(self, format, *args):
                pass

            def _host_refused(self):
                """Refuse (421) a request whose Host is not this machine —
                see _proxy_host_allowed. Every do_* method calls this FIRST,
                before any route is looked at. No body beyond the status."""
                if plugin_self._proxy_host_allowed(self.headers.get("Host", "")):
                    return False
                self.send_error(421, "misdirected request")
                return True

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
            # go2rtc's loopback API and relays the answer. Security model:
            # private sources only, configured-camera
            # allowlist, port never fronted by the reflector. The answer
            # carries session ICE credentials and the LAN candidate — no
            # camera passwords. Media never touches this process.
            def do_OPTIONS(self):
                if self._host_refused():
                    return
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
                if self._host_refused():
                    return
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
                if self._host_refused():
                    return
                # Routes:
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
                        self.send_error(403, "key auto-seed disabled",
                                        "use a one-time setup link")
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
                    # hostname, gets no CORS grant, and cannot read the body.
                    # That comparison alone does NOT stop DNS rebinding: a page
                    # whose own name has been re-pointed at this Mac sends a
                    # matching Host and Origin (or is simply same-origin on
                    # :8177). The Host check at the top of do_GET is what
                    # refuses that — see _proxy_host_allowed.
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

                # /mjpeg/<host> went in v3.36.0: live video is WebRTC, whose
                # media never touches this process.
                self.send_error(404, "not found")

        class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads      = True
            allow_reuse_address = True

        try:
            srv = _Server(("0.0.0.0", PROXY_PORT), _Handler)
        except Exception as exc:
            log(f"[Proxy] Could not bind :{PROXY_PORT}: {exc}", level="ERROR")
            self._proxy_server = None
            return

        self._proxy_server = srv
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="CameraProxy")
        thread.start()
        self._activity(f"[Proxy] Proxy listening on :{PROXY_PORT}")

    def _stop_proxy(self):
        if getattr(self, "_proxy_server", None):
            try:
                self._proxy_server.shutdown()
                self._proxy_server.server_close()
                self._activity("[Proxy] Proxy stopped")
            except Exception as exc:
                log(f"[Proxy] Shutdown error: {exc}", level="WARNING")
            self._proxy_server = None

    # --------------------------------------------------------
    # go2rtc lifecycle (the WebRTC backend for live tiles, and the snapshot source)
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

    def _go2rtc_orphan_pattern(self):
        """pkill -f pattern for a go2rtc THIS plugin started, whatever binary
        ran it and whichever Indigo version's folder held its config (review
        24-09-2026). It used to be the exact current binary path plus the
        current config path, so an orphan started from another binary, or
        before an Indigo upgrade, was never matched and kept the ports."""
        pid = "".join("[.]" if ch == "." else ch for ch in self.pluginId)
        return f"-config .*/Preferences/Plugins/{pid}/go2rtc/go2rtc[.]yaml"

    def _go2rtc_port_freed(self, timeout=2.0):
        """True once nothing answers on go2rtc's API port, polling for up to
        `timeout` seconds after an orphan was told to stop."""
        import urllib.error
        import urllib.request
        deadline = time.monotonic() + timeout
        while True:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{GO2RTC_API_PORT}/api", timeout=0.5):
                    pass
            except urllib.error.HTTPError:
                pass                     # an error status is still something answering
            except (urllib.error.URLError, OSError, TimeoutError):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

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
            # streams.json, which since 24-Sep-2026 carries only a health
            # summary and none of the streams map. Live-confirmed exposed
            # before the fix.
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
            log("[go2rtc] ffmpeg not found on PATH — camera snapshots will fail. "
                "Install Homebrew ffmpeg (searched: PATH, /opt/homebrew/bin, /usr/local/bin).",
                level="WARNING")
        lines += ["streams:"]
        # One stream per camera: <slug> = the camera's H.264 RTSP source,
        # mainstream or sub2 per the camera's `stream` field (default sub2).
        # WebRTC relays it to the browser untouched and the snapshot poller
        # takes its frames from it. The `<slug>_mjpeg` ffmpeg transcode that
        # fed the MJPEG tiles went in v3.36.0 — it was an ffmpeg process per
        # camera being watched, re-encoding video nobody needed re-encoded.
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

    def _vet_cameras(self, cams):
        """The running camera list, held to the rules the Settings save
        applies (review 24-09-2026). A list from a hand-edited store or the
        legacy import skipped them, and one bad entry in go2rtc.yaml takes
        every camera down with nothing in the Indigo log: a duplicate stream
        name makes go2rtc load no streams at all, and an empty one makes the
        whole file unreadable, so go2rtc falls back to its defaults and serves
        its unauthenticated API on every interface. Each bad camera is left
        out, with a WARNING naming it; the rest carry on."""
        keep, slugs, hosts = [], set(), set()
        for i, cam in enumerate(cams or []):
            label = f"camera {i + 1} ({cam.get('name') or '?'})"
            host  = str(cam.get("host") or "")
            slug  = self._cam_slug(str(cam.get("name") or ""))
            why = None
            if cam.get("vendor") not in ("dahua", "hikvision"):
                why = "its vendor is not dahua or hikvision"
            elif not CAMERA_HOST_RE.match(host):
                why = "its host is not an IP address or plain hostname"
            elif not slug:
                why = "its name has no letters or digits for a stream name"
            elif slug in slugs:
                why = f"its name makes the same stream name ({slug}) as an earlier camera"
            elif host in hosts:
                why = f"its host {host} is already used by an earlier camera"
            if why:
                log(f"[Cameras] leaving out {label}: {why}. Fix it on the Settings "
                    f"page and restart the plugin.", level="WARNING")
                continue
            slugs.add(slug)
            hosts.add(host)
            keep.append(cam)
        return keep

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
                f"live video and camera snapshots will not work. Install: download go2rtc_mac_arm64.zip "
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
                    subprocess.run(["/usr/bin/pkill", "-f", "--", self._go2rtc_orphan_pattern()],
                                   capture_output=True)
                    if not self._go2rtc_port_freed():
                        log(f"[go2rtc] :{GO2RTC_API_PORT} is still answering after the orphan "
                            f"was stopped. Something else holds the port, so the cameras "
                            f"may run on an old config until it is freed.", level="WARNING")
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
                if os.path.exists(_logp) and os.path.getsize(_logp) > GO2RTC_LOG_CAP_BYTES:
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

    def _cap_go2rtc_log(self):
        """Empty go2rtc.log once it passes GO2RTC_LOG_CAP_BYTES, while go2rtc
        is running. Returns True when it did.

        Safe with the child still writing: its stdout is the file we opened
        O_APPEND, so every write lands at the current end, and after the
        truncate that is byte 0 again, with no hole of zeros. One stat per 30 s
        sweep, on the poller thread, never the dispatch thread. A dated marker
        follows so the fresh file can still place its lines on a day.
        """
        try:
            handle = getattr(self, "_go2rtc_logfile", None)
            if handle is None or handle.closed:
                return False
            path = self._go2rtc_log_path()
            if os.path.getsize(path) <= GO2RTC_LOG_CAP_BYTES:
                return False
            os.truncate(path, 0)
            self._go2rtc_log_day = None
            self._stamp_go2rtc_log(force=True)
            return True
        except Exception:
            # A log cosmetic must never touch the supervision path it rides on.
            return False

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
        every camera function — snapshots and WebRTC — SILENTLY until a
        manual plugin restart (the only mid-run check was the /streams
        consumer path, which merely errored). Called from the poller's 30 s
        sweep; backoff stops a crash-looping binary from thrashing."""
        proc = getattr(self, "_go2rtc_proc", None)
        if proc is not None and proc.poll() is None:
            # Healthy is the common case, and a healthy go2rtc can run for days
            # (this one had been up since Tuesday), so the date marker has to go
            # here rather than only on the restart path. The size cap has to
            # be checked here for the same reason: a camera that stays offline
            # makes go2rtc log a failed dial every second or two, about 6-9 MB
            # a day, and a cap applied only at start never fires.
            self._cap_go2rtc_log()
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

    def _stills_dir(self):
        """/public/dashboards/stills-<token>/ — where the snapshot poller
        writes. The token comes from the settings store (_ensure_stills_token),
        so the folder name is known only to callers of cameraStills."""
        tok = self._stills_token() or self._ensure_stills_token()
        return os.path.join(self._public_dashboards_dir(), f"stills-{tok}")

    def _cam_jpg_path(self, host):
        return os.path.join(self._stills_dir(), f"cam-{host}.jpg")

    def _cam_thumb_path(self, host):
        return os.path.join(self._stills_dir(), f"cam-{host}-thumb.jpg")

    def _sweep_legacy_stills(self):
        """At startup: remove every still not in the current token's folder.

        That is the cam-*.jpg files older versions wrote straight into
        /public/dashboards (guessable, and readable by anyone), and any
        stills-* folder left by an earlier token. Then make the current folder,
        so a page told about it never meets a 404 before the first poll."""
        tok = self._stills_token()
        if not tok:
            return
        pub  = self._public_dashboards_dir()
        keep = f"stills-{tok}"
        removed = 0
        try:
            names = os.listdir(pub)
        except OSError:
            names = []
        for name in names:
            full = os.path.join(pub, name)
            try:
                if (name.startswith("cam-") and (name.endswith(".jpg") or ".jpg.tmp" in name)
                        and os.path.isfile(full)):
                    os.remove(full)
                    removed += 1
                elif name.startswith("stills-") and name != keep:
                    if os.path.isdir(full) and not os.path.islink(full):
                        shutil.rmtree(full)
                    else:
                        os.remove(full)
                    removed += 1
            except OSError as exc:
                log(f"[Cameras] could not remove the old still {name}: {exc}", level="WARNING")
        try:
            os.makedirs(os.path.join(pub, keep), exist_ok=True)
        except OSError as exc:
            log(f"[Cameras] could not create the stills folder: {exc}", level="WARNING")
        orphans = self._sweep_unconfigured_stills(os.path.join(pub, keep))
        if removed or orphans:
            detail = (f", {orphans} of them for cameras no longer configured"
                      if orphans else "")
            self.logger.info(f"[Cameras] removed {removed + orphans} old camera "
                             f"still(s) from the public folder{detail}")

    @staticmethod
    def _still_host(name):
        """The camera host a stills-folder file belongs to, or None if the
        name is not one the poller writes: cam-<host>.jpg,
        cam-<host>-thumb.jpg, or either with a .tmp suffix."""
        if not name.startswith("cam-") or ".jpg" not in name:
            return None
        stem = name[4:name.index(".jpg")]
        if stem.endswith("-thumb"):
            stem = stem[:-len("-thumb")]
        return stem or None

    def _sweep_unconfigured_stills(self, folder):
        """At startup, inside the CURRENT stills folder: remove the still and
        thumbnail of any camera that is no longer configured (removed, or moved
        to a new address). Nothing else ever deletes them, so the last picture
        of a camera taken out of service stayed readable for ever. Runs before
        the poller starts, and the camera list only changes at restart, so no
        live write can race it. Returns how many files went."""
        hosts = {c.get("host") for c in (getattr(self, "cameras", None) or ())
                 if isinstance(c, dict)}
        removed = 0
        try:
            names = os.listdir(folder)
        except OSError:
            return 0
        for name in names:
            host = self._still_host(name)
            if host is None or host in hosts:
                continue
            full = os.path.join(folder, name)
            try:
                if os.path.isfile(full) and not os.path.islink(full):
                    os.remove(full)
                    removed += 1
            except OSError as exc:
                log(f"[Cameras] could not remove the old still {name}: {exc}", level="WARNING")
        return removed

    def handleCameraStills(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/cameraStills/
        No body needed. Bearer-authenticated by IWS. Answers where the camera
        stills are: {"ok": true, "imagePattern": "stills-<token>/cam-{host}.jpg",
        "thumbPattern": "stills-<token>/cam-{host}-thumb.jpg"}. Replaces the
        fixed patterns config.js used to publish anonymously. No I/O — the
        token is already in memory."""
        _payload, _reply = self._request_body(action)
        if _reply:
            return _reply
        tok = self._stills_token()
        if not tok:
            return self._evo_reply({"ok": False,
                                    "error": "the camera stills folder is not set up yet"},
                                   status=503)
        folder = f"stills-{tok}"
        return self._evo_reply({
            "ok":           True,
            "imagePattern": f"{folder}/cam-{{host}}.jpg",
            "thumbPattern": f"{folder}/cam-{{host}}-thumb.jpg",
        })

    # Frames in a row without a thumbnail before the old one is removed.
    THUMB_MISS_LIMIT = 3

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
        WebRTC relays), so any camera that streams
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
        interleave (open/truncate/replace) into a torn or vanished file.

        A failed write or replace removes its own temp file and re-raises
        (review 24-09-2026): a disk-full episode left partial files behind in
        the anonymous /public folder, where nothing ever swept them."""
        tmp = f"{path}.tmp.{threading.get_ident()}"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            _discard(tmp)
            raise

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
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        except BaseException:
            _discard(tmp)                # never leave a partial copy in /public
            raise

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

    # The ONLY keys streams.json may carry. An allowlist, because the file sits
    # in the anonymous /public namespace: go2rtc's own streams map (producer
    # RTSP URLs with the camera password, viewer addresses, any field a future
    # go2rtc adds) never goes near it.
    STREAMS_JSON_KEYS = ("_writeTs", "_go2rtcUp", "_cameraHealth")

    def _write_streams_json(self, streams):
        """Write Web Assets/public/dashboards/streams.json: when it was written
        (_writeTs, Unix seconds), whether go2rtc answered (_go2rtcUp) and the
        per-camera snapshot health (_cameraHealth). That is all the hub and
        the cameras page read.

        Until 24-Sep-2026 it also mirrored go2rtc's /api/streams map through a
        denylist sanitiser. No page had read that map since the MJPEG tiles
        went in 3.36.0, and a denylist passes any new go2rtc field straight
        into /public, so the map is no longer published at all. `streams` is
        still fetched, as the cheapest proof go2rtc is up.

        Written EVERY tick, go2rtc up or down. Returning early while go2rtc
        was unreachable froze the last healthy summary on screen through the
        very outage it should report; an old _writeTs means the plugin itself
        has stopped writing."""
        try:
            payload = {
                "_writeTs": time.time(),
                "_go2rtcUp": streams is not None,
                # Credential-free by construction: states, counts and times.
                "_cameraHealth": self._camera_health_payload(self.cameras, self._cam_state),
            }
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
                    full_path = self._cam_jpg_path(host)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    self._write_atomic(full_path, payload)
                    # The grid's smaller copy. Written SECOND and separately so a
                    # resize failure can never cost us the full-size picture,
                    # which is the one thing here that must always be there.
                    thumb = self._make_thumb(payload)
                    if thumb:
                        self._write_atomic(self._cam_thumb_path(host), thumb)
                        st["thumb_miss"] = 0
                    else:
                        # No thumbnail from this frame. One bad frame keeps the
                        # last one; a run of them, or Pillow gone for good,
                        # removes it (review 24-09-2026) so the page falls back
                        # to the full picture. A thumb left behind was served
                        # (304 on every poll) for ever while health said ok.
                        st["thumb_miss"] = st.get("thumb_miss", 0) + 1
                        if self._thumb_broken or st["thumb_miss"] >= self.THUMB_MISS_LIMIT:
                            try:
                                os.remove(self._cam_thumb_path(host))
                            except FileNotFoundError:
                                pass
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
        # Publish camera health (and whether go2rtc answered) for the pages.
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
