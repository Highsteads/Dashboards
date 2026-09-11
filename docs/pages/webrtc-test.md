---
title: WebRTC test
parent: Every page
nav_order: 27
---

# WebRTC test — `webrtc-test.html`

The bench for the away-from-home camera work, kept as a diagnostic. It answers one question: does
go2rtc WebRTC play on *this* device over *this* link. It is not linked from anywhere — you reach it
by typing the URL.

## What it shows

A dark bar with a camera dropdown, Start, Stop, and a state word. A video element under it, and a
timestamped log below that, with errors in red. The log times every step from the button press, so a
stall is attributable rather than just slow.

## How it works

Media goes browser to go2rtc on port 8555, over UDP and TCP, reached on the LAN address — which also
works over a Tailscale subnet route. Signalling goes the other way: the SDP offer is posted to the
plugin's proxy at `:8177/webrtc/<host>`, which forwards it to go2rtc's loopback API. The player
functions are page-independent, because they became the Cameras page's away-mode tile.

## Worth knowing

- When an away tile misbehaves, this page is the fastest way to tell a signalling failure from a
  media-path failure, because the log separates them.
- The camera list and names come from `config.js`, the same source the Cameras page uses.
