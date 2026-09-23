---
title: Cameras
nav_order: 7
---

# Cameras

The cameras output **H.264 over RTSP** (mainstream or substream 2). The plugin runs go2rtc as a
managed subprocess, which connects to each camera's RTSP feed and uses ffmpeg to transcode H.264 to
MJPEG. The plugin's own proxy on port 8177 then relays that stream to the browser. MJPEG needs
nothing more than an `<img>` tag, and every browser has handled it for twenty years — no video
player, no JavaScript, no codec negotiation.

```
Camera → RTSP (H.264) → go2rtc → ffmpeg transcode → MJPEG → Plugin proxy :8177 → Browser <img>
```

## What is needed

Both of these, or no streams at all. Without either the plugin logs a warning and the camera pages
show nothing.

- **ffmpeg** — `brew install ffmpeg`. go2rtc calls it to transcode.
- **go2rtc** — `brew install go2rtc`, or download `go2rtc_mac_arm64.zip` from the
  [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and put the binary anywhere on your
  PATH. The plugin looks in the path set under **Plugins → Dashboards → Configure** first, then on
  the PATH, then at `~/bin/go2rtc` as a last resort.
- IP cameras reachable on the LAN with RTSP enabled. Dahua and Hikvision are supported out of the
  box; `vendor` selects the RTSP URL template.

Pillow (thumbnails) installs itself from `requirements.txt` the first time the plugin starts.

## Architecture

```
   ┌──────────────── Camera (Dahua or Hikvision) ────────────────┐
   │  RTSP :554  —  H.264 mainstream or substream 2              │
   └─────────────────────┬───────────────────────────────────────┘
                         │ RTSP (one consumer per camera, shared)
         ┌───────────────▼──────────────────┐
         │   go2rtc  :1984 (HTTP API)        │  ← plugin-managed subprocess
         │            :8554 (RTSP republish) │
         │   + ffmpeg  H.264 → MJPEG         │
         └───────────────┬──────────────────┘
                         │ HTTP MJPEG (multipart/x-mixed-replace)
         ┌───────────────▼──────────────────┐
         │   Plugin MJPEG proxy  :8177       │  ← Python http.server in-plugin
         │   (relays stream + CORS headers)  │
         └───────────────┬──────────────────┘
                         │
         ┌───────────────▼──────────────────┐
         │   Indigo Web Server  :8176        │
         │   /public/dashboards/*.html       │
         └───────────────┬──────────────────┘
                         │  no auth (public namespace)
                  Browser / iPhone / iPad
```

Every camera defaults to **substream 2**, roughly a quarter of the mainstream's bitrate, which
keeps ffmpeg's CPU and the LAN traffic down while staying good enough to see what moved. Add
`"stream": "main"` to a camera's entry to override it.

## What a tile is doing

Each tile on the Cameras page carries a badge:

- **live** — a continuous MJPEG stream from go2rtc.
- **2s**, **5s** — polling the still image at that interval. A slow link gets the longer one, and
  the badge says "SLOW LINK" when the page has decided that for itself.

The page assumes it is remote until it can prove otherwise, because four live streams on a mobile
connection is not a thing to do by accident. It measures the link — throughput, not latency, because
a stream needs bandwidth and a phone on the home Wi-Fi through a VPN can show a slow ping on a fast
link — and picks how many tiles get a moving picture. At home that is up to `livePoolSize` (default
six); away it is fewer, and the away path uses WebRTC for the one tile that stays live. A link at
the bottom of the page, "this device is", pins how this particular browser should behave rather than
leaving it to detection.

**Six is a ceiling, not a preference.** Each live stream is a long-lived connection and browsers
allow about six per address, so a seventh never connects rather than merely running slowly. Lower
`livePoolSize` if you want less traffic; raising it costs tiles.

After ten minutes with nobody touching the page, everything stops. Tap anywhere to start it again.

## Bandwidth

Nine cameras at full rate is roughly 17 Mbit/s, which is why the Cameras page keeps a live kB/s
figure in its header — the number is visible before it becomes a phone bill. Over the Indigo
reflector the pages poll at a tenth of the home rate, and the plugin can refuse the reflector
entirely; see [Remote access](remote-access.md). Live streams only work remotely over Tailscale,
because nothing else fronts port 8177.

## The hub strip and the room pages

The hub carries a strip of up to four cameras — the ones marked "main" in the configuration — as
stills that cross-fade from frame to frame. It never streams; the Cameras page does that. A camera with a `room` in its entry also appears
on that room's page; tap it there for the stream at full width.

## Things worth knowing

- A tile that cannot get a still says so on the tile — "No snapshot (HTTP 404)" — rather than
  sitting as a blank black square.
- A sub-second stream failure with a 500 from go2rtc is usually ffmpeg exiting with code 69, and a
  single retry clears it. The plugin retries once; it is a go2rtc quirk, not a limit.
- The go2rtc ports (1984 HTTP API, 8554 RTSP, 8555 WebRTC) and the proxy on 8177 are deliberately
  unauthenticated — the same trusted-LAN / Tailscale threat model as Indigo's `/public/`. Never
  expose 8177 to the internet.
