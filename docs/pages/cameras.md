---
title: Cameras
parent: Every page
nav_order: 11
---

# Cameras — `cameras.html`

![The Cameras page](../screenshots/cameras.png)

One large tile and a grid of the rest, each either streaming live or polling a still, depending on
how the page was reached and how fast the link is. The mechanics — go2rtc, ffmpeg, the proxy on
port 8177 — are on the [Cameras](../cameras.md) page; this is what the page itself does.

## Down the page

**Header.** Title, last update, and a live bandwidth figure in kB/s for the whole page. That figure
is the point of the header: this is the one page that can saturate a mobile connection.

**Main tile.** The first camera marked "main" in the configuration, at full width, with the
camera's own timestamp overlay. The strip under it carries a state dot, the age of the current
frame, the mode badge and the camera's address.

**Grid.** The remaining cameras, four across, each with the same strip.

**Footer.** Camera count, last update, total bandwidth, a health word, then a second line giving the
detected connection ("home network"), the measured link, the live-versus-still split, and the build
number. Under that, a link reading "this device is: not set" — tapping it pins how this particular
browser should behave rather than leaving it to detection.

## Modes

Each tile shows one of these as a badge:

- **live** — WebRTC video, straight from go2rtc.
- **2s**, **5s** — polling the still image at that interval. A tile that could not hold its live
  video drops to the longer one, says "SLOW LINK", and tries live again later.

The page assumes it is remote until it can prove otherwise. At home up to six tiles are live; away
over a VPN only the tile at the top is, and it follows the tile you tap; over the reflector none
are. The state dot has four
states: grey before anything has arrived, green with live frames, amber when connected but frames
have stalled, red when unreachable. A tile that cannot get a still says so on the tile itself
("No snapshot (HTTP 404)") rather than staying a blank square.

## Where the pictures come from

Live video comes from go2rtc over WebRTC, set up by one request to the plugin's own port 8177
(`/webrtc/<host>`); stills are `cam-<host>.jpg`, which the plugin writes to the web server. Camera hosts, vendors, stream names and room membership all come from the configuration;
changing them needs a plugin restart. The state dots come from Indigo's `/v2/api`.

## Refresh

The page ticks every second for its own status line. The pictures refresh at each tile's own rate:
continuously when live, every 2 or 5 seconds when polling. Reached through the reflector, it polls
at a tenth of the home rate, and after ten minutes with nobody touching it everything stops until
you tap.

## What you can do here

- Tap a tile to promote it to the main position, and tap the main tile for full screen.
- Pin this device's mode with the "this device is" link.
- Jump to Settings to change the camera configuration.

## Worth knowing

- The number of tiles that can be live at once is a browser limit (`livePoolSize`, default six),
  not a plugin one.
- A sub-second stream failure with a 500 is usually ffmpeg's first attempt; one retry clears it.
- All the cameras at full rate can be tens of megabits a second, which is why the bandwidth figure
  is in the header rather than buried in a fold.
