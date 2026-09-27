---
title: Cameras
nav_order: 9
---

# Cameras

The cameras output **H.264 over RTSP** (mainstream or substream 2). The plugin runs go2rtc as a
managed subprocess, which connects to each camera's RTSP feed once and shares it. A live tile is
**WebRTC**: go2rtc relays the camera's own H.264 straight to the browser, untouched, and the browser
decodes it in a `<video>`. The plugin's small server on port 8177 carries only the one request that
sets each stream up. Every tile that is not live polls a still picture, which the plugin takes
every two seconds while a page is showing it.

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

## Stills only while someone is watching

Each still opens a fresh video connection to the camera and waits for a whole picture, go2rtc keeps
nothing open between them. Until 3.48.0 the plugin took one of every camera every two seconds, day
and night, whether or not any page was open: with ten cameras, five camera connections a second,
about 4.4 Mbit/s coming in from the cameras and around 13 GB a day of pictures written to disk.

Now each page that shows stills (the hub's camera strip, a room page's camera, the Cameras page)
tells the plugin which cameras it has on screen, straight away for a new one and then every ten
seconds. The plugin keeps a still every two seconds for those cameras only, and for thirty seconds
after the last page stops asking. A page in a hidden tab, or the Cameras page after ten idle
minutes over the reflector, fetches nothing and so asks for nothing. A tile showing live video
needs no still, so it asks for none either.

A camera nobody is watching still gets one picture every five minutes. That keeps camera health,
and the hub's "camera offline" warning, working with no page open. When that picture fails, the
plugin tries again after thirty seconds, so a camera that has gone shows as offline in about a
minute. Set `stillsIdleMinutes` in the settings to change the five minutes, or to 0 to take no
pictures at all while nobody is watching (the health warning then only covers cameras on screen).

The first picture a page shows after a quiet spell is the last one taken, up to five minutes old,
and a fresh one follows within about two seconds. The Cameras page's age readout says which is
which.

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
- IP cameras reachable on the LAN with RTSP, their video stream, switched on. Any make will do.
  For the makes listed under [Camera makes](#camera-makes) the plugin knows where the video
  usually is. For any other, set it to **other** and type in the camera's own RTSP address.
- A browser with WebRTC, which is every current one. Without it every tile is a still.

Pillow (thumbnails) installs itself from `requirements.txt` the first time the plugin starts.

## Architecture

```
   ┌───────────────────────── IP camera ─────────────────────────┐
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

Whether a tile goes live depends on how fast the connection is, not on where you are. The page
shows stills until it has timed the connection, by downloading a few full-size stills from the
server at once. It then lets as many tiles go live as that speed carries at twice what each one
needs, up to `livePoolSize` (default six): a fast link gets them all, a slower one fewer, and one
with room for a single stream gets the tile you have tapped to the top. A link too slow for even
one gets stills everywhere. Over the Indigo reflector nothing is live, however fast, because it
fronts neither video port and Indigo's servers would carry every byte. The timing is kept for three
minutes and taken again after that when you come back to the page, or at once where the browser
says the network has changed. A link at the bottom of the page, "this device is", tells the page
when this browser is on the house wi-fi, which sets how often the stills refresh.

After ten minutes with nobody touching the page, everything stops. Tap anywhere to start it again.

## Bandwidth

A live tile on substream 2 is roughly 1 Mbit/s and a mainstream one about 1.5. Six live tiles
measured about 1 MB/s together, so the pages allow 1.4 Mbit/s a tile and want twice that spare
before going live: about 11 Mbit/s for the hub's four and 17 for six. The Cameras page keeps a live
kB/s figure in its header, counted from what this browser actually receives, so the
number is visible before it becomes a phone bill. Over the Indigo reflector the pages poll at a
tenth of the home rate, and the pages and the plugin can refuse the reflector (Indigo's web server
still serves the static files there, stills included to anyone who knows their folder), see
[Remote access](remote-access.md). Live video only works remotely over Tailscale, because nothing
else reaches ports 8177 and 8555.

## The hub strip and the room pages

The hub carries a strip of up to four cameras, the ones marked "main" in the configuration. Where
the connection is fast enough for all of them, by the same timing as the Cameras page, each plays
live video over its still. Where it is not, and always over the reflector, they are stills that
cross-fade from frame to frame. A camera with a `room` in its entry also appears on that room's
page, as a still that does not stream. Tap a tile and the Cameras page opens with it at the top.

## Camera makes

Every maker puts the video at its own place on the camera. For the makes below the plugin knows
the usual place, so you choose the make on the Settings page and it works the address out from
the camera's Host. The box under the make shows that address in grey, so you can see what it
will use. **Stream** picks the full picture (main) or the smaller one (sub2, the default), which
is kinder to a wall tablet and the network.

| Make | Full picture (main) | Smaller picture (sub2) | Tried here |
|---|---|---|---|
| Dahua | `/cam/realmonitor?channel=1&subtype=0` | `/cam/realmonitor?channel=1&subtype=2` | Yes |
| Hikvision | `/Streaming/Channels/101` | `/Streaming/Channels/102` | Yes |
| Amcrest | `/cam/realmonitor?channel=1&subtype=0` | `/cam/realmonitor?channel=1&subtype=1` | No |
| Lorex | `/cam/realmonitor?channel=1&subtype=0` | `/cam/realmonitor?channel=1&subtype=1` | No |
| Annke | `/Streaming/Channels/101` | `/Streaming/Channels/102` | No |
| Reolink | `/Preview_01_main` | `/Preview_01_sub` | No |
| TP-Link Tapo | `/stream1` | `/stream2` | No |
| Axis | `/axis-media/media.amp?videocodec=h264` | the same, with `&resolution=640x360` | No |
| Foscam | `/videoMain` on port 88 | `/videoSub` on port 88 | No |
| Uniview | `/media/video1` | `/media/video2` | No |

Every address starts `rtsp://` and the camera's Host, on port 554 unless the table says
otherwise. Only Dahua and Hikvision have been tried on real cameras here. The rest come from
each maker's own support pages, checked in September 2026, so if yours shows nothing, the list
below is the first place to look, and I would be glad to hear what worked.

**If your model differs**, type its address into the box under the make and the plugin uses that
instead, with the Stream choice greyed out because the address names the stream. Clear the box
to go back to the usual one.

### What catches people out, make by make

- **Dahua.** The smaller picture here is the camera's *third* stream (`subtype=2`), because that
  is what the cameras this was built on use. Plenty of Dahua models only have two, so if a
  Dahua shows nothing on sub2, choose main, or type the address with `subtype=1`.
- **Amcrest.** Amcrest cameras are Dahua inside and use the same addresses. Some of the Amcrest
  Smart Home range (the ASH models) are reported not to offer a stream to anything but
  Amcrest's own app.
- **Lorex.** Only some Lorex cameras are Dahua inside, and Lorex does not say which. A Wi-Fi or
  app-only Lorex camera may have no stream at all. A camera plugged into a Lorex recorder
  rather than your network is reached through the recorder, which the plugin cannot do yet.
- **Annke.** Annke cameras are Hikvision inside. Newer firmware will not stream until the
  camera has been set up with a password. The C800 sends only H.265, which most browsers cannot
  play live, so it will show pictures but not live video.
- **Reolink.** Newer firmware ships with the stream switched **off**. Turn on RTSP in the
  Reolink app or web page under Network, Advanced, Port Settings. Battery Reolinks have no stream
  of their own. Older firmware may want `/h264Preview_01_main` and `/h264Preview_01_sub` instead,
  and 4K models send H.265 on the full picture, so keep those on sub2.
- **TP-Link Tapo.** The stream needs a separate **camera account**, made in the Tapo app under
  the camera's Advanced Settings. It is not your Tapo login, and it is the one to put in Camera
  Logins in Configure. Battery models (C410, C420, C425 and the D230 doorbell) have no stream,
  and some others only when wired. Dual-lens models use `/stream6` and `/stream7` for the second
  lens.
- **Axis.** The plugin asks for H.264, because a camera left on H.265 will not play live in most
  browsers. The smaller picture asks for 640 by 360. A camera that cannot give that size refuses
  it, so type the address with a size your camera offers, or use main.
- **Foscam.** Most Foscam cameras stream on port 88, but some newer ones use 554 (the C1 and
  several of the V3 models among them). If port 88 shows nothing, type the address with 554.
  The oldest Foscam cameras have no stream at all.
- **Uniview.** The addresses here are for cameras. A Uniview recorder uses a different form.
  Dual-lens cameras use `/media2/video1` for the second lens.

## Any other make of camera

For a make not in the list, choose **other** and type the camera's whole address into the box,
such as `rtsp://192.168.1.50:554/stream1`. The camera's manual or its maker's website gives the
right one, and many cameras list it in their own settings pages. Most offer a smaller second
stream as well, so use that one if you can.

Three rules apply to any address you type, and the Settings page says which one an address
breaks:

- It must start `rtsp://` or `rtsps://`, and point at the same address as the camera's Host.
- It must not carry a user name or password. The login is added for you, from Configure.
- It may not hold spaces, quotes or `#`.

Each camera needs an address of its own, because the plugin tells cameras apart by it. Cameras
whose video comes through a recorder, such as UniFi Protect or a Synology, all share the
recorder's address, so only one of them can be added that way for now.

## A camera with a login of its own

When every camera uses the same login, **Camera User** and **Camera Password** in Configure are
all you need. When one does not, often because it is of another make, give it a login of its own
in **Plugins → Dashboards → Configure → Camera Logins**, written against the camera's address:

```json
{"192.168.1.50": {"user": "admin", "password": "its password"}}
```

Add one entry per camera that needs it, separated by commas, and restart the plugin. A camera
listed here gets its own login and not the shared one, and the login goes only to the address it
is written against, so it needs no approval. If you use `IndigoSecrets.py`, the same thing can go
there as `CAMERA_LOGINS`, which wins over the Configure field. The field is shown and stored in
plain text, as the camera password is.

A camera of another make that needs no login at all works with nothing set in either place.

## The camera login goes only to approved addresses

Every camera without a login of its own shares one (Configure → Camera User / Password), and go2rtc hands it to each
camera's address when it connects. A camera's address can be changed by anyone holding the API key,
from the Settings page or the `dashboards_set_camera` tool, so from 3.46.0 the login is only sent to
addresses approved on the Indigo Mac itself: the cameras that were saved when **Plugins → Dashboards
→ Configure** was last closed with **Save**. The plugin logs the list each time it changes, naming
any address that is new.

A camera whose address is not on the list is still streamed, but with no login, so a real camera
refuses it and its tile stays empty. The log says which camera and why, and so does the Settings
page's Cameras card. When you have added or changed a camera yourself: open Configure, press Save,
and restart the plugin. The first start of 3.46.0 approves every camera already running, so nothing
changes for an existing install.

## Things worth knowing

- A tile that cannot get a still says so on the tile — "No snapshot (HTTP 404)" — rather than
  sitting as a blank black square.
- go2rtc's API (1984) and RTSP (8554) listen on the Mac itself only. WebRTC media (8555) and the
  plugin's server (8177) answer the LAN and Tailscale, and 8177 refuses any other source. Neither
  is authenticated beyond that — the same trusted-LAN / Tailscale threat model as Indigo's
  `/public/`. Never expose 8177 or 8555 to the internet.
