# Dashboards Plugin for Indigo

Browser-based dashboards for [Indigo Domotics](https://www.indigodomo.com/) home automation server. Designed for an iPad/iPhone/Mac kept on a wall or table — opens to a hub page and drills into per-room views, energy, heating, security, and a 9-camera live video grid.

Pages live under Indigo's `/public/` namespace so any browser on the LAN (or Tailscale) opens them without typing credentials. The plugin handles all the camera-side and Indigo-side authentication on the server.

## What it provides

- **Hub page** with tiles for Energy, Cameras, Heating, Overview, Active devices, and one tile per room
- **9-camera dashboard** — 6 live MJPEG streams + 3 snapshot tiles (configurable), Dahua and Hikvision IP cameras supported
- **Per-room pages** (Garage, Kitchen, Hall, Bedrooms, Conservatory, etc.) showing the devices, sensors and zones relevant to each space
- **No authentication** at the browser layer — page lives in the IWS `/public/` namespace, plugin owns all the credentials

## Camera dashboard highlights

- Live MJPEG via [go2rtc](https://github.com/AlexxIT/go2rtc) — plugin manages the go2rtc subprocess and config
- ffmpeg-based mainstream-H.264 → MJPEG transcode (UI3-style trick) — picture quality matches the camera's mainstream regardless of how its own MJPEG substream is configured
- Browser HTTP/1.1 6-connection limit respected — first N cameras stream live, the rest poll snapshots
- Tap any thumbnail → it becomes the large focused tile
- Per-tile snapshot download button
- Bandwidth indicator (kB/s per live tile + total)
- Tab-hidden auto-pause to spare LAN bandwidth
- Snapshot poller automatically skips cameras that already have a live consumer (no encoder contention)
- Vendor-aware URL templates — Dahua/Amcrest (`/cam/realmonitor`) and Hikvision (`/Streaming/Channels/101`) handled transparently

## Architecture

```
   ┌────────────── Camera (Dahua or Hikvision) ─────────────┐
   │  RTSP mainstream :554   /   substream 2 MJPEG          │
   └─────────────┬──────────────────────────────────────────┘
                 │ RTSP (one consumer per camera, shared)
   ┌─────────────▼──────────────┐
   │  go2rtc  :1984 (HTTP API)  │  ← plugin-managed subprocess
   │          :8554 (RTSP)      │
   │          :8555 (WebRTC)    │
   │   + ffmpeg for H.264→MJPEG │
   └─────────────┬──────────────┘
                 │ HTTP MJPEG (multipart/x-mixed-replace)
   ┌─────────────▼──────────────┐
   │  Plugin MJPEG proxy :8177  │  ← in-plugin Python http.server
   │  (relays + adds CORS)      │
   └─────────────┬──────────────┘
                 │ HTTP (same-origin via IWS public folder for snapshots
                 │       + streams.json bandwidth telemetry)
   ┌─────────────▼──────────────┐
   │  Indigo Web Server  :8176  │
   │  /public/dashboards/*.html │
   └─────────────┬──────────────┘
                 │ no auth (public namespace)
            Browser / iPhone / iPad / Fire OS
```

## Requirements

- Indigo 2025.2 (Python 3.13, IWS 8176)
- Homebrew `ffmpeg` (`brew install ffmpeg`) — used by go2rtc to transcode mainstream H.264 to MJPEG
- `go2rtc` binary at `~/bin/go2rtc` — download `go2rtc_mac_arm64.zip` from [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and unzip
- Cameras reachable on the LAN with RTSP enabled

## Secrets

Credentials are read from `/Library/Application Support/Perceptive Automation/IndigoSecrets.py`:

| Key | Used for |
|---|---|
| `INDIGO_URL`  | Browser → Indigo API base URL (`http://192.168.x.x:8176`) |
| `INDIGO_API_KEY` | Indigo REST API Bearer token (or `CLAUDEBRIDGE_BEARER_TOKEN` as fallback) |
| `DAHUA_USER`  | Camera admin username (shared across all cams in this build) |
| `DAHUA_PASS`  | Camera admin password |
| `SIGEN_DASHBOARD_URL` *(v1.16)* | Optional URL for the legacy Sigen dashboard menu item; blank disables the item |
| `DASHBOARDS_CAMERAS` *(v1.16)* | JSON string OR python list of camera dicts (each needs `host`, `name`, `vendor`); blank disables the cameras grid + MJPEG proxy + go2rtc |

If a key is missing, the affected feature degrades gracefully — the camera proxy logs a warning and skips, the dashboard's connection form is shown, etc.

## Configuration

As of **v1.16.0** all camera and Sigen-URL configuration is data-driven and
exposed via PluginConfig.xml (no source-edits required). Settings are read
in this order: `IndigoSecrets.py` → PluginConfig → empty (feature disabled).

| PluginConfig field | IndigoSecrets equivalent | Purpose |
|---|---|---|
| `sigenLegacyUrl` | `SIGEN_DASHBOARD_URL` | Legacy Sigen mini-dashboard URL |
| `camerasJson` | `DASHBOARDS_CAMERAS` | JSON list of `{host, name, vendor}` entries |
| `swapOutHost` | *(none)* | Override which cam is bumped to still when peeking — defaults to the LAST entry in the cameras list |

Cameras JSON example (one line):
```json
[{"host":"192.168.1.50","name":"Front Door","vendor":"dahua"},{"host":"192.168.1.51","name":"Drive","vendor":"hikvision"}]
```

Vendor templates are in `VENDOR_URLS` in `plugin.py` — add more if you have a non-Dahua/Hikvision cam.

## Installation

1. Go to the [Releases](https://github.com/Highsteads/Dashboards/releases) page and download `Dashboards.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Dashboards.indigoPlugin`
3. Double-click `Dashboards.indigoPlugin` — Indigo will install it automatically
4. Install ffmpeg (`brew install ffmpeg`) and go2rtc (see Requirements above)
5. Add `DAHUA_USER`, `DAHUA_PASS` to `IndigoSecrets.py` (alongside any existing entries)
6. Enable the plugin and open `http://<indigo-host>:8176/public/dashboards/index.html`

## Ports

| Port | Purpose | Bind |
|---|---|---|
| 8176 | Indigo Web Server (HTML pages served here) | (IWS-managed) |
| 8177 | Plugin's MJPEG proxy server | `0.0.0.0` |
| 1984 | go2rtc HTTP API + WebRTC signaling | `0.0.0.0` |
| 8554 | go2rtc RTSP republish (lets other apps consume cam streams without hitting the cam directly) | `0.0.0.0` |
| 8555 | go2rtc WebRTC media (TCP) | `0.0.0.0` |

The MJPEG and go2rtc ports are intentionally unauthenticated — same trusted-LAN/Tailscale threat model as Indigo's `/public/` namespace.

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]` so
events can be correlated tightly with other CliveS plugins (Device Activity
Monitor uses the same convention).

To turn the prefix off (or back on) at any time:

**Plugins → Dashboards → Toggle Timestamps in Log (on/off)**

The setting is stored in `pluginPrefs` (`timestampEnabled`) and persists across
restarts. Defaults to ON.

## Current Version

1.16.1 (23-May-2026) — millisecond timestamp `[HH:MM:SS.mmm]` prefix on every `self.logger` line via `plugin_utils.install_timestamp_filter()`; new "Toggle Timestamps in Log" menu item.

1.16.0 (23-May-2026) — removed hardcoded LAN-specific config (Sigen URL, cameras list, swap-out host, go2rtc host). New PluginConfig.xml + IndigoSecrets keys for shareability. See Configuration above.

## Author

CliveS — built with assistance from Claude.
