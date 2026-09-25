---
title: Getting started
nav_order: 3
---

# Getting started

Ten minutes from download to a hub page on a phone, if the cameras can wait. The cameras are the
only part with anything to install by hand.

> **Would rather not do any of this yourself?** [Start with nothing but Claude](no-coding-needed.md)
> is the same journey with Claude Code doing the typing — installing the plugin, the camera tools,
> an MCP server and Tailscale, and then building the pages you actually want.

## What you need

- **Indigo 2025.2** (Python 3.13). The pages are served by Indigo's own web server on port 8176.
- **An Indigo API key.** Every page reads live data through Indigo's REST API with a Bearer token,
  so a browser has to hold one. Make a key on the
  [Authorizations page of your Indigo account](https://www.indigodomo.com/account/authorizations),
  or create a local secret in the install folder's `Preferences/secrets.json` (Indigo's Web Server
  documentation covers both). The plugin never writes the key into anything under `/public/`; a
  browser is given it once and keeps it locally.
- **Device folders that mean rooms.** The room pages are built from Indigo device folders. With
  nothing configured the plugin uses one house's folder names and yours will produce no rooms — so
  the first thing to do after installing is tick your folders on the Settings page.

Everything below is optional, and every page that depends on something says so rather than
showing an empty chart:

| Optional piece | What it unlocks |
|---|---|
| **ffmpeg** and **go2rtc** (Homebrew) | The camera grid, the hub's camera strip and the cameras on room pages. Both are required; without either the plugin logs a warning and shows no streams. See [Cameras](cameras.md) |
| **SQL Logger** plugin (ships with Indigo) | The Timeline (all four views), the hub's Home Insights check, the Mains page's trust figures and the Meter page's history |
| **PostgreSQL** behind the SQL Logger | Supported as an alternative backend to SQLite. Reads go through the `psql` client, so Postgres.app or the `postgresql` client package must be installed. Use **Plugins → Dashboards → Test History Connection** before relying on it |
| **SigenEnergyManager** plugin | The Energy, Cost and Laundry pages and the hub's Energy · Now card. Without it the three pages hide themselves, the menu drops their tiles and the hub says in one line which plugin is missing. Carbon and Mains do not need it |
| **EvoHomeControl** plugin | The heating page's boost and force buttons. Zone temperatures and setpoints work with any thermostat device |
| **UniFiHealth** plugin (v0.2.0 or later) | The Wi-Fi pages |
| **OpenWeatherMap** key | The hub's weather card forecast and sun times |
| **Pillow** and **qrcode** | Camera thumbnails and setup-link QR codes. These install themselves from `requirements.txt` the first time the plugin starts |
| **The companion scripts** in `scripts/` | The Presence page, the hourly error watch behind the Alerts card and the Activity page, and the Laundry page. Copy the ones you want into Indigo's `Python Scripts` folder; the plugin picks them up on its next tick and logs which are missing at startup. See [How it is built](architecture.md#companion-scripts) |

## Install

1. Go to the [Releases page](https://github.com/Highsteads/Dashboards/releases) and download
   `Dashboards.indigoPlugin.zip`.
2. Unzip it — you get `Dashboards.indigoPlugin`.
3. Double-click `Dashboards.indigoPlugin`. Indigo installs it and asks whether to enable it.
4. **Cameras only:** `brew install ffmpeg` and `brew install go2rtc` (or download the go2rtc binary
   and set its path under Configure). The rest of the plugin works without them.
5. Enter credentials under **Plugins → Dashboards → Configure** — at minimum the Indigo API key,
   plus the camera user and password if you have cameras. See [Configuration](configuration.md)
   for what each field does and for the `IndigoSecrets.py` alternative.
6. Open `http://<indigo-host>:8176/public/dashboards/index.html` — or pick
   **Plugins → Dashboards → Open Dashboards in Browser**.

> **Using Claude Code?** It has shell access and can install both camera binaries, install the
> plugin and fill in the credentials for you — no other plugins or MCP servers needed. See
> [Claude Code and MCP tools](claude-code.md).

## Pairing a browser

The pages themselves are public files. What a browser needs is the API key, and there are four
ways it can get one:

- **A one-time setup link — the usual way.** **Plugins → Dashboards → Generate One-Time Setup Link
  (+QR)** writes a link (and a QR code) into the log. Open it on the device, or scan the QR with
  the phone's camera, and `setup.html` stores the key and burns the token, so the link cannot be
  used twice. Unredeemed links expire on their own. Do this once for each of your own devices.
- **The Connect form.** A browser that is not paired lands on the hub's Connect form, which says
  how to use a setup link and also takes the key typed in by hand.
- **Auto-seeding on the LAN.** With *Auto-seed the API key to LAN browsers* ticked under Configure,
  a new browser on the home network or the tailnet pairs itself on first visit through the plugin's
  own port 8177. It is off for a new install from 3.46.0, because it hands the full key to every
  device that asks, a visitor's phone on your Wi-Fi included, and that key controls the house.
  Installs from before 3.46.0 keep the setting they had, and the plugin logs once to say so.
- **Guest pairing.** For a wall tablet or a visitor's phone that should only look, **Plugins →
  Dashboards → Show Guest Access Info** logs a pairing URL. The device gets a guest token instead of
  the key, so it cannot switch anything, and it reads only the device states and the variables you
  allow (see [Guest devices](remote-access.md#guest-devices)). Home network and Tailscale only.
  With auto-seeding on, a guest device could simply ask for the full key instead, so a guest link
  only means something with it off.

The footer of every page carries a *Reset connection* link that forgets the stored key.

## The first five minutes

1. **Rooms.** Open the hub, tap Settings (or the Settings card), and on the Rooms card tick the
   Indigo device folders that are your rooms. Save. Rooms appear on the menu straight away.
2. **Cameras.** On the Cameras card add each camera's address, name and vendor (Dahua or
   Hikvision), and tick the ones for the hub's strip. Camera changes need a plugin restart; the
   card says so.
3. **Check it.** **Plugins → Dashboards → Test Dashboards Setup** runs every check in one go —
   API URL and key, camera credentials and list, room folders, the SQL Logger history, the public
   pages folder, the liveness stamp, and whether SigenEnergyManager is present — and logs a verdict
   per line. An optional piece that is absent is a SKIP, not a failure.
4. **Pin it.** On an iPhone or iPad, open the hub in Safari, tap Share, then **Add to Home
   Screen**. On a Mac, Safari's **File → Add to Dock…**. The dashboard then opens full-screen like
   an app, and links stay inside it. Chrome's and Edge's install icon only appears on a secure
   (`https://`) address, which the usual `http://…:8176` one is not; see
   [Notifications and install need HTTPS](remote-access.md#notifications-and-install-need-https).

## Demo mode

Open `demo.html` and every page runs from sanitised sample data with a gentle state simulator —
solar wobbles, the battery drifts, motion flickers, and controls change the local fixture so toggles
feel real. No devices are touched. An orange banner along the bottom says so; tap it to leave.

## Upgrading

Download the new zip and double-click the bundle as before; Indigo replaces the old one. The plugin
mirrors its pages into Indigo's public folder every time it starts, so there is nothing else to
copy. **After upgrading past v2.70, reload any dashboard tab that has been open for days** — a wall
tablet running old JavaScript can poll a restarting plugin in a way that stalls the web server for
about five minutes, and the newer pages know not to.
