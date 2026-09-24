---
title: Cameras
nav_order: 7
---

# Cameras

The cameras output **H.264 over RTSP** (mainstream or substream 2). The plugin runs go2rtc as a
managed subprocess, which connects to each camera's RTSP feed once and shares it. A live tile is
**WebRTC**: go2rtc relays the camera's own H.264 straight to the browser, untouched, and the browser
decodes it in a `<video>`. The plugin's small server on port 8177 carries only the one request that
sets each stream up. Every tile that is not live polls a still picture the plugin writes every two
seconds.

```
Camera → RTSP (H.264) → go2rtc ──WebRTC :8555──→ Browser <video>      (live tiles)
                          └─ ffmpeg → stills-<token>/cam-<host>.jpg → Browser <img>   (stills)
```

The stills live in a private folder under `/public/dashboards/`, named by a secret the plugin
makes for each install. The web server hands out anything in `/public` to anyone who asks, so the
name is the protection: only a browser holding the API key is told it, by the plugin's
`cameraStills` action, and nothing anonymous (not `config.js`, not any page) contains it. In earlier
versions the pictures were `cam-<host>.jpg` straight in `/public/dashboards/`, and `config.js` spelled
out the pattern, so anyone who could reach the web server could watch every camera. The plugin
deletes those old files, and any folder left by an earlier secret, when it starts.

Until 3.36.0 live tiles were MJPEG: go2rtc ran an ffmpeg process per camera to re-encode the
video as a stream of JPEGs. WebRTC uses about a third of the bandwidth, drops frames on a slow link
instead of falling further and further behind, needs no re-encoding, and does not hold one of the
browser's six connections per address for every tile.

## What is needed

Both of these, or no pictures at all. Without either the plugin logs a warning and the camera
pages show nothing.

- **ffmpeg** — `brew install ffmpeg`. go2rtc calls it to take the still pictures.
- **go2rtc** — `brew install go2rtc`, or download `go2rtc_mac_arm64.zip` from the
  [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and put the binary anywhere on your
  PATH. The plugin looks in the path set under **Plugins → Dashboards → Configure** first, then on
  the PATH, then at `~/bin/go2rtc` as a last resort.
- IP cameras reachable on the LAN with RTSP enabled. Dahua and Hikvision are supported out of the
  box; `vendor` selects the RTSP URL template.
- A browser with WebRTC, which is every current one. Without it every tile is a still.

Pillow (thumbnails) installs itself from `requirements.txt` the first time the plugin starts.

## Architecture

```
   ┌──────────────── Camera (Dahua or Hikvision) ────────────────┐
   │  RTSP :554  —  H.264 mainstream or substream 2              │
   └─────────────────────┬───────────────────────────────────────┘
                         │ RTSP (one consumer per camera, shared)
         ┌───────────────▼──────────────────┐
         │   go2rtc  :1984 API (loopback)    │  ← plugin-managed subprocess
         │           :8555 WebRTC media      │
         └──────┬───────────────────┬───────┘
                │ frame.jpeg        │ WebRTC (UDP or TCP), straight to the browser
   ┌────────────▼─────────┐         │
   │ Plugin snapshot poll │         │      ┌──────────────────────────────┐
   │ → cam-<host>.jpg in  │         │      │ Plugin server :8177          │
   │   a private folder   │         │      │ POST /webrtc/<host> → go2rtc │
   └────────────┬─────────┘         │      │ (sets each stream up, only)  │
                │                   │      └──────────────┬───────────────┘
         ┌──────▼───────────────────▼──────────────────────▼──┐
         │                 Browser / iPhone / iPad             │
         └─────────────────────────────────────────────────────┘
```

Every camera defaults to **substream 2**, roughly a quarter of the mainstream's bitrate, which keeps
the LAN traffic down while staying good enough to see what moved. Add `"stream": "main"` to a
camera's entry to override it.

## What a tile is doing

Each tile on the Cameras page carries a badge:

- **live** — WebRTC video from go2rtc.
- **2s**, **5s** — polling the still picture at that interval. A tile that could not hold its live
  video drops to stills, says "SLOW LINK", and tries live again after a minute, then less often.

The page assumes it is remote until it can prove otherwise. At home up to `livePoolSize` tiles
(default six) are live and the rest are stills; over a VPN only the tile you have tapped to the top
is live; over the Indigo reflector nothing is, because it fronts neither video port. A link at the
bottom of the page, "this device is", pins how this particular browser should behave rather than
leaving it to detection.

After ten minutes with nobody touching the page, everything stops. Tap anywhere to start it again.

## Bandwidth

A live tile on substream 2 is roughly 1 Mbit/s and a mainstream one about 1.5; the Cameras page
keeps a live kB/s figure in its header, counted from what this browser actually receives, so the
number is visible before it becomes a phone bill. Over the Indigo reflector the pages poll at a
tenth of the home rate, and the plugin can refuse the reflector entirely; see
[Remote access](remote-access.md). Live video only works remotely over Tailscale, because nothing
else reaches ports 8177 and 8555.

## The hub strip and the room pages

The hub carries a strip of up to four cameras — the ones marked "main" in the configuration — as
stills that cross-fade from frame to frame. A camera with a `room` in its entry also appears on that
room's page, the same way. Neither streams: tap a tile and the Cameras page opens with it live at
the top.

## Things worth knowing

- A tile that cannot get a still says so on the tile — "No snapshot (HTTP 404)" — rather than
  sitting as a blank black square.
- go2rtc's API (1984) and RTSP (8554) listen on the Mac itself only. WebRTC media (8555) and the
  plugin's server (8177) answer the LAN and Tailscale, and 8177 refuses any other source. Neither
  is authenticated beyond that — the same trusted-LAN / Tailscale threat model as Indigo's
  `/public/`. Never expose 8177 or 8555 to the internet.
