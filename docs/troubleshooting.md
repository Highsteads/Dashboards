---
title: Troubleshooting
nav_order: 11
---

# Troubleshooting

## Start with the setup check

**Plugins → Dashboards → Test Dashboards Setup** runs every check in one go and logs a verdict per
line: the Indigo API URL and key, the camera credentials and the camera list, the room folders, the
SQL Logger history connection, whether the public pages folder is writable, whether the liveness
stamp is beating, and whether SigenEnergyManager is present. Optional pieces that are absent report
SKIP, not FAIL. The same sweep is available to Claude as `dashboards_run_setup_check`.

**Plugins → Dashboards → Show Plugin Info** logs the environment — versions, architecture, Python —
which is the first thing to paste into a support post.

## The page asks me to connect, or shows nothing

The pages are public files; the data behind them needs an API key. Pair the browser with a
one-time setup link (**Plugins → Dashboards → Generate One-Time Setup Link (+QR)**), or enter the
key in the Connect form — see [Getting started](getting-started.md#pairing-a-browser). A new install
does not hand the key out by itself any more (3.46.0): *Auto-seed the API key to LAN browsers* is
off until you tick it. If the key was rotated, every paired browser
needs pairing again; the footer's *Reset connection* link forgets the old one.

## No rooms, or the wrong things in a room

With nothing configured the plugin uses one house's folder names and yours will produce no rooms.
Tick your Indigo device folders on the Settings page's Rooms card. A device in the wrong section is
the classifier guessing from folder and name — the Rooms card has a per-room override (`include`,
`hideDeviceIds`, `sortOrder` and the tile types in [Configuration](configuration.md#room-extras)).
Read the resolved counts under each room before assuming a page is broken.

## Cameras

- **No streams anywhere, and a warning in the log.** Both ffmpeg and go2rtc are needed. Install
  them and restart the plugin. If go2rtc is somewhere unusual, set its path under Configure.
- **One camera never connects.** Check the vendor (the RTSP URL template differs), the credentials
  (one set, shared), and that the camera has RTSP enabled. `dashboards_list_cameras` and
  `dashboards_read_log` show what the plugin sees.
- **A tile flashes a 500 and then recovers.** ffmpeg exiting with code 69 on first contact; go2rtc
  quirk, one retry clears it, the plugin already does that.
- **Tiles say "2s" or "5s" at home.** The page thinks the link is slow. Tap "this device is" at the
  bottom of the Cameras page to pin it to home. Check whether the browser was paired with the
  reflector address rather than the LAN one.
- **Only some tiles are live.** How many can be live is decided by measuring your connection, not by
  where you are: the page times a few pictures from the plugin and allows as many live tiles as the
  speed carries, up to `livePoolSize` (default six). The Cameras page footer shows the measured
  Mbit/s. On a slow connection the tiles are stills, and over the reflector they are always stills.
- **On an iPhone or iPad, the cameras only go live after you touch the page.** Turn on **Auto-Play
  Video Previews** in Settings, Accessibility, Motion. With it off, iOS will not start any video on a
  web page by itself, even a silent one, and the page says so under the cameras until you tap.
- **Live tiles never start, or drop to stills.** Live video is WebRTC: it is set up on port 8177
  and streams from go2rtc on 8555, and both have to be reachable. At home, check nothing on the Mac
  blocks 8555; away, only Tailscale reaches them. Over the reflector you get stills, slowly, by
  design.

## Energy, Cost or Laundry are missing from the menu

They need the SigenEnergyManager plugin and hide themselves without it. Installing (or enabling) it
is noticed within thirty seconds; the hub says which plugin is missing until then.

## The heating page has no boost or force buttons

They are EvoHomeControl's own actions and appear only when that plugin is installed *and enabled*.
Zone temperatures and setpoints work with any thermostat device regardless.

## Graphs, Timeline or the Meter page's history are empty

They read the SQL Logger's history database. Check the plugin is running and, under Configure, that
the backend matches where it writes (SQLite by default). For PostgreSQL the `psql` client must be
installed; **Test History Connection** proves the settings. A state that exists on a device but has
never been logged will not appear in the Graphs picker, and that is the correct answer.

## The Wi-Fi page is empty

It renders devices published by the UniFiHealth plugin (v0.2.0 or later). Nothing on the page talks
to the controller itself.

## "Not updating for four minutes"

The page's poll has stopped returning data. Usually the plugin is restarting; the amber line clears
on the next good poll. If it stays amber, check the plugin is running and read the event log. If
*every* page and every other plugin's endpoint has gone quiet for about five minutes right after a
plugin restart, a page running old JavaScript polled the plugin mid-restart and stalled the web
server; it recovers on its own, and reloading long-open tabs stops it recurring.

## The Settings page will not save

Save checks the plugin is up first, and refuses while it is restarting. Wait a few seconds and try
again. A refused save says what is wrong.

## Guest pairing fails

Guest pairing works on the home network and over Tailscale only; the proxy refuses any other source
address. A device that was previously paired with the full key is demoted to a guest, not left
holding both.

## An alert rule did not tell me

Start with **Send test** on the Alerts page, or **Plugins → Dashboards → Send Test Alert**: each
channel says whether it was sent, and why not.

- **Pushover: no user key** — put your user key in `IndigoSecrets.py` as `PUSHOVER_USER_TOKEN`, or in
  the Pushover User Key field in Configure.
- **Pushover: plugin not running** (or not installed, not enabled) — the message goes through the
  Pushover plugin, so it has to be running. The log says so once every half hour while it is not.
- **Email: no address** — set one under Where alerts go on the Alerts page. If an address is set and
  the test still fails, the reason is Indigo's own: check its mail settings (Indigo → Preferences).
- **Browser** notifications need one of the main pages open on that device and an `https://`
  address; Pushover and email do not.
- A rule fires on a change, not on a state: "turns on" says nothing about a light that is already
  on. After it fires it waits thirty seconds before it can fire again. "alerts active" off, a
  paused rule or a device that is disabled in Indigo all stay quiet, and a rule whose device was
  deleted is marked "target gone".

## Something is wrong and none of the above fits

- The plugin's own log, via **Plugins → Dashboards → Show Plugin Info** for the environment and the
  `dashboards_read_log` tool (or the log file itself) for the last lines.
- The Indigo event log, for the plugin's warnings and errors.
- The Activity page's Alerts card, which collapses the event log's errors by signature so one fault
  reads as one row.
- [Open an issue](https://github.com/Highsteads/Dashboards/issues) with the setup-check output and
  the plugin-info banner.
