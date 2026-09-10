<div align="center">

# Dashboards for Indigo

**Your house on a screen — energy, cameras, heating, every room, and the whole day replayed.**

Browser dashboards for [Indigo Domotics](https://www.indigodomo.com/), built for an iPad on the
wall, a phone in your pocket and a Mac on the desk. No app to install, no cloud account,
nothing leaving the house.

<img src="https://img.shields.io/badge/version-3.13.1-5856d6" alt="Version 3.13.1">
<img src="https://img.shields.io/badge/Indigo-2025.2-2a2a2e" alt="Indigo 2025.2">
<img src="https://img.shields.io/badge/pages-27-0a84ff" alt="27 pages">
<img src="https://img.shields.io/badge/tests-667%20passing-30d158" alt="667 tests passing">
<img src="https://img.shields.io/badge/licence-MIT-8e8e93" alt="MIT licence">

<br><br>

<img src="screenshots/index.png" width="860" alt="The hub — who is home, the heating, the battery, today's carbon, and a strip of live cameras">

</div>

---

**Version:** 3.13.1

### Jump to

**[Screenshots](#screenshots)** &nbsp;·&nbsp;
**[Every page](#every-page)** &nbsp;·&nbsp;
**[Things that move](#things-that-move)** &nbsp;·&nbsp;
**[Tap to go deeper](#tap-to-go-deeper)** &nbsp;·&nbsp;
**[Cameras](#camera-streaming--h264-into-mjpeg)** &nbsp;·&nbsp;
**[Architecture](#architecture)**

**[Requirements](#requirements)** &nbsp;·&nbsp;
**[Installation](#installation)** &nbsp;·&nbsp;
**[Configuration](#configuration)** &nbsp;·&nbsp;
**[Credentials](#credentials)** &nbsp;·&nbsp;
**[Remote access](#remote-access--run-tailscale)** &nbsp;·&nbsp;
**[Ports](#ports)**

**[Version history](#version-history)** &nbsp;·&nbsp;
**[Page reference](#page-reference)** &nbsp;·&nbsp;
**[Building on it](#building-and-extending-with-claude-code)**

---

Pages live under Indigo's `/public/` namespace, so any browser on the LAN — or on the tailnet
when you are away — opens them without typing credentials. The plugin handles all the
camera-side and Indigo-side authentication on the server.

Works in any modern browser: Chrome, Firefox, Safari, Edge and anything Chromium-based. The
camera streams use standard MJPEG in an `<img>` tag, which every browser has handled for
twenty years.

**Demo mode** — open `demo.html` on any install and every page runs from sanitised sample data
with a gentle state simulator, touching no live devices.

### Dashboard presentation

The home and Energy pages share aligned power-flow panels, clear metric cards and consistent light/dark styling. Solar charts combine actual per-array generation with a labelled kWh scale, a dashed forecast line and shaded future hours. Energy also includes battery state, power history and daily totals. Readings change immediately when refreshed; moving flow indicators show power direction. Favourites preserve keyboard focus during updates.

Version 3.5.0 was checked with captured real Energy status and history in Chrome and WebKit at phone and desktop widths. Automated light/dark accessibility scans passed for that Energy-page capture. These checks do not replace testing on physical devices or with each installation's camera and device configuration.

---

**A note on origins.** This started out as a personal plugin built around my own [ClaudeBridge](https://github.com/Highsteads/ClaudeBridge) MCP, which connects Claude Code directly to an Indigo server and is what I use day-to-day to develop and maintain it. That said, you are very welcome to use it with any Indigo MCP setup — it is not tied to ClaudeBridge in any way at runtime. If you do use Claude Code for plugin development, I would strongly recommend loading [Simon's Indigo skills](https://github.com/simons-plugins/indigo-claude-skill) at the start of your session; they bundle the full Indigo SDK reference, lifecycle docs, and worked examples in a form Claude can actually use, and will save you a fair amount of time and tokens compared to piecing it together from the wiki.

---

### Using it as a standalone web app

The dashboard ships with a PWA manifest so it can be pinned as a proper standalone app rather than just a browser tab:

**iPhone / iPad** — open the hub page in Safari, tap the Share button, then **Add to Home Screen**. The icon appears on your home screen and opens the dashboard full-screen with no browser chrome, just like a native app.

**Mac (Safari)** — open the hub page in Safari, choose **File → Add to Dock…** (macOS Sonoma and later). The dashboard gets its own icon in the Dock and opens in a standalone window.

**Mac / Windows (Chrome or Edge)** — click the install icon in the address bar (the ⊕ or screen icon to the right of the URL) and choose **Install**. The dashboard opens in its own window and appears in your app launcher.

Link navigation inside the standalone app is handled automatically — tapping through to room pages, the camera grid, and so on stays within the same standalone window rather than bouncing out to the browser.

## Screenshots

Every one of these is the real house, captured from a live server. Addresses are rewritten to
documentation ranges on the way to the browser, so the pictures are honest without being an
inventory of the network.

### The house

<img src="screenshots/living-room.png" width="49%" alt="Living Room"> <img src="screenshots/garage.png" width="49%" alt="Garage">

**A room, end to end.** Lights and sockets with real controls, the blinds, its own sensors and
its own cameras. The Garage carries the door itself — press Open and the button takes over,
counts the seconds and holds until the contact sensors confirm the door has actually moved.

<img src="screenshots/active.png" width="49%" alt="Active"> <img src="screenshots/scenes.png" width="49%" alt="Scenes">

**Everything that is on, and everything you can start.** Active is the fastest way to find
what you left running. Scenes is every Indigo action group as a button, grouped by folder,
each one reporting what actually happened rather than flashing a tick.

### Energy and money

<img src="screenshots/energy.png" width="860" alt="Energy">

**The whole solar and battery picture.** The power flow at the top really flows — streams of
dots run between the sun, the battery, the house and the grid in the direction the energy is
going, and reverse when the battery turns round. Below it: battery state, tariff, forecast,
per-array generation against a dashed forecast line, and the day's totals.

<img src="screenshots/cost.png" width="49%" alt="Cost"> <img src="screenshots/carbon.png" width="49%" alt="Carbon">

**What it costs and what it costs the planet.** Bill-exact daily electricity and gas, standing
charges, export earnings and week-on-week comparisons against the same week last year. Carbon
is live national grid intensity with a plain-English verdict on whether now is a good time.

<img src="screenshots/laundry.png" width="49%" alt="Laundry"> <img src="screenshots/mains.png" width="49%" alt="Mains">

**Two pages that try hard to be honest.** Laundry works out when to run each metered appliance
from the solar forecast, the house's own measured load and the live half-hourly prices — and
tells you plainly when it makes no difference. Mains leads with how far the meters disagree
rather than a reading, because they genuinely span 3.7 volts.

<img src="screenshots/meter-detail.png" width="860" alt="One meter in detail">

**Tap any meter and you get its own page** — its live reading, where it sits against every
other meter in the house with a rank, its seven-day offset and its history.

### The day

<img src="screenshots/timeline.png" width="860" alt="Timeline">

**Any day, replayed.** Presence, lights, doors and heating on their own lanes with a battery
and solar trace underneath. Drag anywhere on it and the house rebuilds itself at that moment.

<img src="screenshots/presence.png" width="49%" alt="Presence"> <img src="screenshots/activity.png" width="49%" alt="Activity">

**Who was where, and what happened.** Presence draws each night's sensor timelines with a
derived "both agree" track and calls out the dropouts. Activity is the house diary — locks,
doors, safety events, plugin restarts — with recent errors folded in at the bottom.

<img src="screenshots/history.png" width="860" alt="Graphs">

**Plot anything that was ever recorded**, straight out of the SQL Logger's history database.

### Watching over it

<img src="screenshots/cameras.png" width="49%" alt="Cameras"> <img src="screenshots/heating.png" width="49%" alt="Heating">

**Nine live streams and twelve heating zones.** The cameras are real video, not stills, and
slow themselves right down on a link that is paying by the byte.

<img src="screenshots/ecowitt.png" width="49%" alt="Weather"> <img src="screenshots/system-health.png" width="49%" alt="System health">

**The weather station in full, and the server's own vitals** — disk, memory and swap pressure,
load, uptime, the history database's size, and a census of every device that is in error, low
on battery or has gone quiet.

<img src="screenshots/wifi.png" width="49%" alt="Wi-Fi"> <img src="screenshots/wifi-ap-detail.png" width="49%" alt="One access point">

**Every access point and how hard it is working** — and tap one for its own page, with
per-radio state and every client on it.

<img src="screenshots/alerts.png" width="49%" alt="Alerts"> <img src="screenshots/settings.png" width="49%" alt="Settings">

**Notifications from your own browser, and everything configurable from a form.** No push
service, no account, nothing leaving the house. Settings covers favourites, custom links,
cameras, per-room extras and the scenes hide-list, with raw JSON when you want it.

## Every page

Twenty-two pages you use, plus five that hold the whole thing together. Every one is a
plain HTML file — no build step, no framework, no bundler — and every one reads live Indigo
data through the same Bearer-authed API.

### The house

| Page | What it is for | Opens |
|---|---|---|
| **Hub** `index.html` | The front page. Who is home, the heating, the battery, today's carbon, and a strip of live camera thumbnails. Below that: your pinned Favourites, a money card, a house-pulse trace, the solar day so far, and a power-cut banner when there is one. | a room, the cameras, the weather, the energy page, the timeline, alerts, the full menu |
| **Menu** `menu.html` | Every page in one list, grouped, with each room as its own entry. What the Hub's "More" opens. | any page, any room |
| **Per-room** `room.html?room=Name` | One room end to end — its lights and sockets with real controls, blinds, its sensors, its own cameras, and anything you have added to it. Fourteen rooms here. | a camera stream, a colour picker, a light's own detail |
| **Active** `active.html` | Everything currently on, across the whole house, on one page. The fastest way to find what you left running. | the device's own controls, in place |
| **Scenes** `scenes.html` | Every Indigo action group as a button, grouped by folder. Press it and the button itself tells you what actually happened rather than flashing a tick. | nothing — it acts in place |

### Energy and money

| Page | What it is for | Opens |
|---|---|---|
| **Energy** `energy.html` | Needs SigenEnergyManager, and hides itself without it. The whole solar and battery picture: animated power flow, battery state, tariff, forecast, period totals, history charts and a week-on-week comparison with the same week last year alongside. | the Cost page |
| **Cost** `cost.html` | Needs SigenEnergyManager, and hides itself without it. What the house actually costs to run, from bill-exact economics — daily electricity and gas, standing charges, export earnings, solar savings, and week, month and year totals. | the Energy page |
| **Carbon** `carbon.html` | How dirty the grid is right now and over the next day, from the free national Carbon Intensity API, with advice on when to shift a load. | the Energy page |
| **Laundry** `laundry.html` | Needs SigenEnergyManager, and hides itself without it. When to run each metered appliance so it costs the least grid import — worked out from the solar forecast, the house's own measured load profile, the battery and the live half-hourly prices. Chips set the deadline. Advisory only: it never switches anything on. | the Energy page |
| **Mains** `mains.html` | Every 240 V meter in the house and how far each one disagrees with the others. Leads with the trust panel, because the meters here span 3.7 V and pretending otherwise would be the wrong kind of confident. | **a meter's own page**, the Active page |
| **Meter** `meter.html?id=N` | One meter in detail — its live reading, where it sits against every other meter in the house, its seven-day offset, and its own history. | back to Mains |

### The day

| Page | What it is for | Opens |
|---|---|---|
| **Timeline** `timeline.html` | Any day replayed on one scrubbable timeline: presence, lights, doors and heating lanes, with a battery and solar trace underneath. | the Presence page |
| **Presence** `presence.html` | Per-night presence-sensor timelines with a derived "both agree" track, dropout callouts, a movement strip and a bedroom sleep proxy. | the Hub |
| **Activity** `activity.html` | A house diary from the Indigo event log — locks, doors, safety events, plugin restarts — with recent errors folded in at the bottom. | the Timeline |
| **Graphs** `history.html` | Time-series charts of any recorded device state, straight out of the SQL Logger's history database. | nothing — pick and plot |

### Watching over it

| Page | What it is for | Opens |
|---|---|---|
| **Heating** `heating.html` | Every zone, its temperature and its setpoint, with controls where the heating plugin supports them. | the Hub |
| **Cameras** `cameras.html` | All nine cameras as live streams, tap to enlarge. Slows itself right down when it can see it is on a slow link, and stops entirely after ten minutes untouched. | Settings |
| **Weather** `ecowitt.html` | The weather station in full — every sensor it reports, with each tile opening its own detail. | a sensor's own detail, in place |
| **System** `system-health.html` | The Indigo server's own vitals: disk, memory and swap pressure, load, uptime, the history database's size, and a device-health census. | Settings |
| **Wi-Fi** `wifi.html` | Every access point, its client count and how hard it is working. | **an AP's own page** |
| **Wi-Fi AP** `wifi-ap.html?id=N` | One access point in detail — per-radio state and every client on it. | back to Wi-Fi |
| **Alerts** `alerts.html` | Browser notification rules. Pick devices or variables and your own browser tells you when they change, with no third-party service anywhere. | the Hub |

### The supporting cast

| Page | What it is for |
|---|---|
| **Settings** `settings.html` | Forms-based configuration — favourites, custom links, cameras, per-room extras, the scenes hide-list, and raw JSON when you want it |
| **Setup** `setup.html` | First-run pairing. Hands the browser its key once, then burns the token |
| **Guest** `guest.html` | Pairing for a read-only device — a wall tablet or a visitor's phone gets a guest token instead of the full key |
| **Demo** `demo.html` | The whole thing running on fixtures, with no Indigo behind it |
| **WebRTC test** `webrtc-test.html` | A diagnostic for the camera transport, not part of the daily set |

## Things that move

A screenshot cannot show any of this, which is rather the point of the list.

**The power flow really flows.** On the Energy page and on the Hub's power card, the sun,
the battery, the house and the grid sit around the inverter and streams of dots run along
the links between them, in the direction the energy is actually going. Reverse the battery
from charging to discharging and the dots turn round. The figures behind it refresh every
five seconds, and the battery ring sweeps to its new level rather than jumping.

**The live dot tells you whether to believe the page.** Every page carries a small green dot
beside its "Updated" time that pulses while the data is arriving. If nothing has arrived for
three missed polls it turns amber, stops pulsing, and the line changes to "not updating for
four minutes". It runs on its own timer rather than on the poll, because a poll that has
died cannot be trusted to report that it has died — and only a poll that actually returned
data clears it.

**Sensors pulse while they are seeing something.** A motion or presence tile on a room page
breathes gently for as long as the sensor is detecting, so a glance tells you the difference
between "someone is in the kitchen" and "someone was".

**A door in motion sweeps.** Press Open on the garage or the front door and the button takes
itself over: it fills, says what it is doing, counts the seconds, and a light sweep runs
across the tile for as long as the contacts say the door is actually moving. It holds until
the sensors confirm the door really has moved, goes red if it failed, and goes amber and
tells you to go and look if nothing confirmed it either way. It is reporting the door, not
the fact that Indigo accepted the request.

**Cameras are live video, not stills.** Nine H.264 streams transcoded to MJPEG and dropped
straight into an `<img>` tag, which every browser has handled for twenty years. The Hub
carries a thumbnail strip of them. On a slow link — away from home over Tailscale, on mobile
data — everything slows right down and then stops altogether after ten minutes untouched,
because somebody is paying for those bytes.

**Charts redraw rather than reload.** The energy, cost, carbon and history charts update in
place as new figures arrive, and the Timeline's replay control pulses while it is playing.

**Cards animate in once.** A card slides in on the first paint of a page and never again —
a page that re-ran its entry animation every thirty seconds was one of the things that made
the older versions feel restless. Identical output now writes nothing to the DOM at all, so
text stays selectable and anything you have opened stays open.

**And all of it stops if you ask it to.** Every animation on every page sits behind
`prefers-reduced-motion`. Turn motion down in your operating system and the dots, the
pulses, the sweeps and the card entrances all go, while everything keeps working.

## Tap to go deeper

Nothing here is a dead end. Every page has a Home button, and the tiles that look tappable
are tappable.

**Tiles that open a page of their own:**

| On this page | Tapping this | Opens |
|---|---|---|
| Hub | a room tile | that room, end to end |
| Hub | the camera strip | the full nine-camera grid |
| Hub | the weather, energy or timeline card | that page |
| **Mains** | **any meter tile** | **that meter's own page** — its live reading, its rank against every other meter in the house, its seven-day offset and its history |
| **Wi-Fi** | **any access-point tile** | **that AP's own page** — per-radio state and every client on it |
| Menu | any room | that room |
| Activity | an event | that moment on the Timeline |
| Timeline | the presence lane | the Presence page |
| Energy | the money figures | the Cost page, and back again |

**Tiles that open in place, without leaving the page:**

| On this page | Tapping this | Opens |
|---|---|---|
| Per-room | a light or socket | its own controls, and a full colour picker for anything colour-capable |
| Per-room | a camera | that camera's stream, full width |
| Per-room | a blind | its position control |
| Weather | any sensor | that sensor's reading and its recent history |
| Cameras | any stream | full screen — tap again to come back |
| Hub | a Favourite | the device's controls, in the tile |
| Laundry | a deadline chip | replans that appliance on the spot |
| Meter, System, Activity, Settings | a fold | the detail underneath, which stays open while you are on the page |

**And two things that look like they should be tappable and deliberately are not.** A meter
that is not answering shows no position on the voltage scale, because a frozen reading
cannot be placed on a scale of live ones. And an appliance that has not run enough times to
be measured gets no deadline chips, because there is nothing yet to schedule.

## Camera streaming — H.264 into MJPEG

The cameras themselves output **H.264 over RTSP** (mainstream or substream 2). The plugin runs go2rtc as a managed subprocess, which connects to each camera's RTSP feed and uses ffmpeg to transcode H.264 → MJPEG. The plugin's own Python proxy on port 8177 then relays that MJPEG stream to the browser. MJPEG requires nothing more than an `<img>` tag and works in every browser without any JavaScript video player.

As of **v1.19.2** all cameras default to **substream 2** (roughly ¼ the bitrate of mainstream) to reduce ffmpeg CPU and LAN bandwidth while keeping acceptable motion-detection quality. Individual cameras can override this by adding `"stream": "main"` to their entry in `DASHBOARDS_CAMERAS`.

```
Camera → RTSP (H.264) → go2rtc → ffmpeg transcode → MJPEG → Plugin proxy :8177 → Browser <img>
```

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

## Alerts — notifications from your own browser

The hub's 🔔 **Alerts** card (v2.6.0) lets any device that shows the
dashboard also watch it: pick devices and variables, choose a condition
("turns on", "turns off", "changes at all"), and matching changes raise a
system notification on that device — with a 30-second per-rule cooldown so
a chattering sensor can't spam you. Rules are stored in the browser itself,
nothing on the server. Being honest about the limits: there is no cloud
push service behind this, so notifications only arrive while a dashboard
tab (or the installed home-screen app) is open. That makes it ideal for a
wall tablet, a kiosk, or a pinned tab on the computer you sit at, rather
than a phone in your pocket.

## Page files

Dashboard HTML pages are stored in two places:

| Location | Purpose |
|---|---|
| `Contents/Resources/static/pages/` | **Source of truth** — edit files here |
| `<Indigo install>/Web Assets/public/dashboards/` | **Served by IWS** — copied from source at plugin startup |

`dashboards-action.js` holds the shared control-button behaviour: it runs the action,
takes the button over, and watches the device states until the thing has really
happened. Which states confirm which action is declared per action group in the
`actionWatch` config key, so no page carries device numbers. Its rule evaluator is a
pure function driven directly by `tests/test_action_watch.mjs`.

`energy-calc.js` holds the arithmetic shared by the Energy and Cost pages — unit
formatting, the daily energy allocation behind the Sankey, the half-hourly
supply/sink balance, and the rolling-window money sums. It is plain, DOM-free
functions so `tests/test_energy_cost.mjs` can drive it directly; put any new
page maths there rather than inline in a page.

The plugin mirrors the source pages into the public folder during `startup()`. If you edit a page and restart the plugin, IWS will serve the updated version. Editing the public folder directly has no lasting effect — the next restart will overwrite it from source.

The Indigo install folder is version-dependent (e.g. `Indigo 2025.2`). To find it:

```
/Library/Application Support/Perceptive Automation/Indigo <ver>/Web Assets/public/dashboards/
```

Or inside the plugin bundle at runtime it is always `../../Web Assets/public/dashboards/` relative to `Contents/Server Plugin/`.

## Requirements

- **Indigo 2025.2** (Python 3.13, IWS 8176)
- **UniFiHealth plugin ≥ v0.2.0** for the Wi-Fi detail pages (optional)
- **EvoHomeControl plugin** for the heating page's boost / force buttons (optional — the panel hides itself when that plugin is not installed; zone temperatures and setpoints work with any thermostat device)
- **SigenEnergyManager plugin** for the Energy, Cost and Laundry pages and the hub's Energy · Now card (optional — without it the three pages hide themselves, the menu drops their tiles and the hub says in one line which plugin is missing; Carbon and Mains do not need it)
- **SQL Logger plugin** (ships with Indigo) for the Graphs page, the Timeline and the Home Insights card (optional — not everyone runs it, and everything else works without it, and the pages say so clearly rather than showing empty charts)
- **PostgreSQL** (v2.47.0, optional) — if your SQL Logger writes to PostgreSQL rather than the default SQLite, pick the backend under the plugin's Configure. Reads go through the `psql` command-line client, so **Postgres.app** or the `postgresql` client package must be installed. No Python driver is added, so SQLite users install nothing. Use **Plugins → Dashboards → Test History Connection** to check the settings before relying on them

### Camera grid — both binaries required

The camera grid needs **both** of the following. Without either one the plugin logs a warning and the camera pages show no streams.

- **Homebrew ffmpeg** — `brew install ffmpeg` — go2rtc calls ffmpeg to transcode the camera's H.264 RTSP stream to MJPEG; the camera grid will not work without it
- **go2rtc** — `brew install go2rtc`, or download `go2rtc_mac_arm64.zip` from [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and put the binary anywhere on your PATH. The plugin looks in the path set under **Plugins → Dashboards → Configure** first, then on the PATH, then at `~/bin/go2rtc` as a last resort
- Pillow (thumbnails) and qrcode (setup links) install themselves from `requirements.txt` the first time the plugin starts — nothing to fetch by hand
- IP cameras reachable on the LAN with RTSP enabled (Dahua and Hikvision supported out of the box)

> **Using Claude Code?** [Claude Code](https://claude.ai/claude-code) has built-in shell access and can install both binaries for you — no other plugins or MCP servers needed. Just type:
> 
> *"Install ffmpeg and go2rtc via Homebrew so I can use the Dashboards camera grid"*
> 
> Claude Code will run the Homebrew install and go2rtc download directly on your Mac.

## Credentials

**`IndigoSecrets.py` is not a requirement** — it is simply the approach I use personally to keep credentials out of source code and shared across all my plugins from one place. Every credential the plugin needs can be entered directly through **Plugins → Dashboards → Configure** in the Indigo client instead, and that is probably the simpler starting point for most people.

The resolution order for every setting is: `IndigoSecrets.py` first (if present), then PluginConfig, then the feature is disabled gracefully. The two approaches work alongside each other — you can use PluginConfig for everything, IndigoSecrets for everything, or mix them as you like.

If you do want to use `IndigoSecrets.py` (for example, because you already use it with other CliveS plugins), the keys the Dashboards plugin looks for are:

| Key | Used for |
|---|---|
| `INDIGO_URL` | Indigo REST API base URL, e.g. `http://192.168.1.10:8176`. Blank means the local server on port 8176 |
| `INDIGO_API_KEY` | Indigo REST API Bearer token — used for the plugin's own diagnostics and the guest passthrough, never written into `config.js`. Browsers are prompted for the key once and store it locally (`CLAUDEBRIDGE_BEARER_TOKEN` is accepted as an alias) |
| `DAHUA_USER` / `DAHUA_PASS` | Camera admin username and password (shared across all cameras; works for Hikvision too) |
| `DASHBOARDS_CAMERAS` | JSON list of camera dicts — see Configuration below |
| `DASHBOARDS_MAIN_CAMERAS` | List of host IPs for the hub 4-up mosaic (must also appear in `DASHBOARDS_CAMERAS`) |
| `DASHBOARDS_ROOM_EXTRAS` | Per-room overrides dict — doors, appliances, TV group, plugs, hide/include lists, sort order |
| `DASHBOARDS_HIDDEN_SCENES` | Action-group names or ids to keep off the Scenes page |
| `SIGEN_DASHBOARD_URL` | Optional URL of a legacy Sigenergy mini-dashboard, for the matching menu item |
| `OWM_API_KEY` / `LATITUDE` / `LONGITUDE` | OpenWeatherMap One Call key and your site's coordinates, for the hub weather card's forecast and sun times |
| `HISTORY_PG_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DATABASE` | PostgreSQL connection for the history pages, when the SQL Logger writes to Postgres |

Every one of these has a matching field under **Plugins → Dashboards → Configure**, and the repo ships `IndigoSecrets_example.py` with empty placeholders to copy from. Installs that have saved from the Settings page read cameras, main cameras, room extras and hidden scenes from `dashboards_config.json` instead.

## Configuration

As of **v2.0.0** the easiest way to configure everything is the built-in **Settings page** — open the dashboards, tap the Settings card on the hub, and you get a forms-based editor for cameras (including the hub mosaic and swap-out choice), per-room extras (pulse doors, appliance monitors, TV groups, hide/include/sort overrides), and the Scenes hide-list, plus a raw-JSON view for anything exotic. Device fields take IDs, with a live lookup showing which devices they resolve to. The first Save writes `dashboards_config.json` into the plugin's Preferences folder, and from that point the file is the single source of truth — the IndigoSecrets dicts below are only read on installs that have never saved from the editor. Camera changes need a plugin restart (the streaming pipeline is built at startup); everything else applies immediately.

For fresh installs (or if you prefer files), the legacy path still works exactly as before: settings come from **Plugins → Dashboards → Configure**, with `IndigoSecrets.py` values taking precedence over PluginConfig where both exist.

### Cameras JSON

```json
[
  {"host": "192.168.1.50", "name": "Front Door", "vendor": "dahua"},
  {"host": "192.168.1.51", "name": "Drive",      "vendor": "hikvision"},
  {"host": "192.168.1.52", "name": "Garden",     "vendor": "dahua", "stream": "main", "room": "Garden"}
]
```

- `vendor` — `"dahua"` or `"hikvision"` (controls the RTSP URL template)
- `stream` — `"sub2"` (default) or `"main"` to override per camera
- `room` — string or list of strings; controls which per-room pages show this camera; omit to keep the camera out of room pages

### DASHBOARDS_ROOM_EXTRAS

This is an optional per-room configuration that unlocks the more advanced tile types on the room pages. You only need it if you want any of the features described below — a room with nothing in DASHBOARDS_ROOM_EXTRAS will still show its lights, motion sensors, and contact sensors automatically.

The value is a dictionary keyed by room name (matching the Indigo device folder the room is built from — see **Room folders** below). Each room can have any combination of the following:

**`doors`** — Adds a pulse-door tile to the room page. Each entry needs a `label` (the name shown on the tile), one or more `relayIds` (the Indigo device IDs of the relay or relays to momentarily pulse — useful for garage door openers and electric gate controllers), a `pulseMs` duration in milliseconds, and optionally a `statusContactId` (the Indigo ID of a contact sensor that reports whether the door is open or closed) and `openWhenContactOnState` (True if the contact being On means the door is open, False if it is the other way round). Any device IDs listed in `doors` are automatically hidden from all other sections on that page so they do not appear twice.

**`appliances`** — Adds a read-only appliance tile pairing a power meter with a cycle monitor. `label` is the display name. `monitorId` is the Indigo device ID of a power meter (e.g. a Shelly plug with energy monitoring) that provides live wattage. `cycleId` is the Indigo device ID of an ApplianceMonitor virtual device that tracks cycle state (Idle / Running / Door open). Either can be omitted — a monitor-only tile shows live watts and on/off state, a cycle-only tile shows cycle state and last-cycle stats.

**`tv`** — A list of Indigo device IDs treated as a group. Each device gets its own toggle tile and the section gets an All On / All Off button. Useful for grouping a TV and its associated smart plugs together.

**`hideDeviceIds`** — A list of Indigo device IDs to suppress from all auto-discovered sections on that room page. Handy for devices that appear in the estate but are not relevant to a particular room.

**`include`** — A dictionary of section name to list of Indigo device IDs to force into that section regardless of how the device is classified. For example `{"lights": [123]}` will make device 123 appear in the Lights section even if the classifier would not normally put it there. Supported section keys are `lights`, `motion`, `radiators`, `windows`, `sensors` and `extras`.

**`plugs`** — A list of Indigo device IDs shown in their own Plugs & Sockets section with a toggle each. They are kept out of the "lights on" count and there is deliberately no bulk All On / All Off for them — a freezer or a router could be on one.

**`fire`** — Device IDs treated as a fire (an open-loop relay whose state is the last thing sent, not a reading). The room page shows them separately and the night sweep re-asserts them off.

**`openLoop`** — Device IDs whose state cannot be read back (RF relays, IR blasters). A group favourite commands them but never lets their believed state decide the group's label.

**`sortOrder`** — A dictionary of section name to list of Indigo device IDs. Devices in the list appear first in that section in the order given; all remaining devices follow alphabetically. Useful for putting the most important lamp at the top of the Lights list.

### Other config keys

These live in `dashboards_config.json` (the Settings page writes it; anything the forms do not model can be set in the raw-JSON box at the bottom of that page):

| Key | Shape | What it does |
|---|---|---|
| `roomFolders` | list of folder names | Which Indigo device folders become rooms. Tick them on the Settings page's Rooms card; with nothing ticked the plugin uses its own defaults, which are one house's folder names and will produce no rooms on yours |
| `siteName` | string | The name in every page title, the hub heading and the home-screen icon. Default "Dashboards" |
| `vehicles` | `[{"id": <device>, "label": "Car 12V"}]` | Battery-voltage monitors to list under the energy page's battery fleet, with a frozen-reading check |
| `arrayKwp` | number | Your solar array's rating, for the weather station page's roof-vs-sky cross-check |
| `actionWatch` | object | Per-action-group confirmation rules for scene buttons (see the Settings page hint) |
| `livePoolSize` | number, default 6 | How many cameras show a moving picture at once. **Six is a ceiling, not a preference** — each one is a long-lived connection and browsers allow about six per address, so a seventh never connects rather than merely running slowly. Lower it if you want less traffic; raising it costs tiles. Away from home the plugin measures the link and uses fewer |

## Installation

> **Using Claude Code?** If you have [Claude Code](https://claude.ai/claude-code) available, you can skip most of the manual steps below — just ask it to install the Dashboards plugin, set up ffmpeg and go2rtc, and configure the credentials. It can handle all of it directly with no other plugins or MCP servers required.

1. Go to the [Releases](https://github.com/Highsteads/Dashboards/releases) page and download `Dashboards.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Dashboards.indigoPlugin`
3. Double-click `Dashboards.indigoPlugin` — Indigo will install it automatically
4. **Camera grid only** — install both ffmpeg and go2rtc (see Requirements above); the rest of the plugin works without them:
   - `brew install ffmpeg`
   - `brew install go2rtc` (or download the binary from [go2rtc releases](https://github.com/AlexxIT/go2rtc/releases) and set its path under Configure)
5. Configure credentials via **Plugins → Dashboards → Configure** (or via `IndigoSecrets.py` — see Credentials above)
6. Enable the plugin in Indigo and open `http://<indigo-host>:8176/public/dashboards/index.html`

## Remote access — run Tailscale

Away from home, the best way to use the dashboards is [Tailscale](https://tailscale.com) — a zero-config WireGuard VPN whose free tier comfortably covers a family's devices. With it running, your phone or laptop is effectively "at home" anywhere in the world, and the plugin already treats it that way: the private-client gate on port 8177 explicitly accepts Tailscale's `100.64.0.0/10` range alongside the LAN.

Why this plugin needs it:

- **Cameras only work remotely this way.** The MJPEG proxy lives on port 8177, which nothing else fronts — without Tailscale you get every data page but no live streams; over Tailscale you get the lot, including the hub's camera mosaic.
- **No pairing ceremony.** A new browser on the tailnet auto-pairs on first visit via `/bootstrap`, exactly as at home. Any other way in, you would need a one-time setup link or to type the API key.
- **Nothing exposed.** No port forwarding, no public attack surface, WireGuard encryption end to end.

Setup:

1. Install Tailscale on the **Indigo Mac**, sign in once, and tick "start on login" — it just sits in the menu bar.
2. Install the Tailscale app on the **iPhone / iPad / MacBook**, signed into the same tailnet, and enable **MagicDNS** in the admin console.
3. Bookmark the dashboard using the Mac's tailnet name, e.g. `http://your-mac-name:8176/public/dashboards/` — that one URL then works identically on the sofa and on holiday.
4. On the phone, leave the VPN toggle **on**. WireGuard is idle when unused, so the battery cost is negligible — and toggling it on demand (e.g. from a Shortcut) is noticeably slow, so always-on is both simpler and faster.


## Ports

| Port | Purpose | Auth |
|---|---|---|
| 8176 | Indigo Web Server — HTML pages served here | None (public namespace) |
| 8177 | Plugin MJPEG proxy — live camera streams | None (trusted LAN / Tailscale) |
| 1984 | go2rtc HTTP API | None |
| 8554 | go2rtc RTSP republish | None |
| 8555 | go2rtc WebRTC media (TCP) | None |

The MJPEG proxy and go2rtc ports are intentionally unauthenticated — same trusted-LAN / Tailscale threat model as Indigo's `/public/` namespace. Do not expose port 8177 directly to the internet.

## Third-party

The history charts use [Chart.js](https://www.chartjs.org) (MIT licence),
bundled inside the plugin since v2.4.2 so charts work without an internet
connection.

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]` to match the convention used across all CliveS plugins. Toggle the prefix at any time from **Plugins → Dashboards → Toggle Timestamps in Log**.

## Version history

**3.13.1** (10-Sep-2026) - **First public release.** The repository is now public, rebuilt as a fresh single commit from a scrubbed tree; the earlier history stays in a private archive. In the tree itself the changes are small: example addresses in comments and tests are now generic documentation ones, the demo fixture has been re-sanitised (credentials of every kind, e-mail addresses, Zigbee and Shelly hardware addresses and a household name are placeholders, not only IP addresses), and the fixture generator scrubs those same classes so a regenerated fixture cannot bring them back. Two new tests keep it that way: one refuses any real-looking address, hostname or e-mail anywhere in the tree, the other checks the demo fixture and the generator. Nothing on a running install changes.

**3.13.0** (10-Sep-2026) - **The Sigenergy pages hide themselves when the plugin is not there.** Energy, Cost and Laundry only have something to draw with the SigenEnergyManager plugin installed, and until now nothing said so: an install without it got three tiles leading to empty charts and fetch errors, a hub card reading "Sigen device not found", and an amber line in the event log every thirty seconds as the hub asked a port nothing was listening on. Now the plugin publishes whether SigenEnergyManager is present beside the flag the heating page already uses; without it the menu drops the three tiles, the hub hides its Energy and Solar cards and says in one line which plugin is missing, each page opened from a bookmark shows one card explaining what it needs, the proxy answers at once instead of dialling out, the laundry planner does not run, and Test Dashboards Setup reports it as an optional skip rather than a failure. Installing or removing the plugin is noticed within thirty seconds without a restart. Demo mode is unaffected, and an older config file without the new flag reads as present, so an upgrade cannot hide pages that were there yesterday. The heating page's boost panel now also asks that EvoHomeControl be enabled, not merely installed, since a disabled plugin swallows those actions silently.

**3.12.0** (10-Sep-2026) - **The plugin now offers its own tools to Claude.** Any Indigo MCP server that reads plugin-provided tool manifests (mlamoure's Indigo MCP Server from v2026.8.1, Claude Bridge from v2.26.0) finds `Contents/Resources/mcp-manifest.json` in the bundle and lists eight `dashboards_` tools to the AI: the plugin's status, the setup check as data rather than log lines, the room folders (read and set, with unknown folder names refused and the real ones offered back), the cameras (list, add or update, remove), and the last lines of the plugin's own log. So "set my dashboard rooms to Kitchen, Hall and Lounge" or "why is the garden camera not streaming" is now a conversation with no source files in it. The writes go through exactly the validation the Settings page uses, and say plainly when a restart is needed. With no MCP server installed nothing changes: the manifest is inert data and the action behind it is never called. Also fixed: reopening Settings straight after adding a camera showed the camera list from before the save, so a second Save would quietly have deleted the new one; the editor now shows what is saved.

**3.11.0** (09-Sep-2026) - **The Laundry page now covers every metered appliance, and works each machine's habits out for itself.** Asked to add a tumble dryer and a dishwasher, and neither is metered - so rather than type in cycle figures for two machines nobody can measure, which is exactly what this page refuses to do, it now finds whatever is metered and measures each one from its own history. Put a metering plug on the dryer, add an Appliance Monitor device pointed at it, and it turns up here on its own with real timings once it has run about five cycles. No editing, no version of this plugin to wait for. Until then it says plainly that the machine has not run enough times yet, which is a more useful thing to read than a confident number off a manual. Each appliance gets its own card, its own deadline chips and its own advice, and the washing machine's own figures are now derived the same way - forty-seven cycles rather than the forty-one that were counted by hand. Two smaller things went in with it: the deadline endpoint checks the appliance name as tightly as it checks the time, since that name becomes an Indigo variable and one with a space in it can never be read back, and the companion scripts this repo ships are finally run by the test gate and by CI, which had never executed a line of them.

**3.10.0** (09-Sep-2026) - **A Laundry page: when to put the washing on so it costs the least.** It reads the solar forecast, the house's own measured load profile, the battery and the live half-hourly prices, and answers in a sentence - "put the washing machine on at half eleven and it should finish about half twelve, the whole 0.7 kWh should come from the sun". Chips along the top say when it has to be finished by, and picking one works the plan out again on the spot. It advises and nothing more: the washing machine's meter is deliberately monitor-only, and a machine has to be loaded by a person anyway, so a person is standing in front of it at exactly the moment the advice is any use. The timings are not off a manual either - they come from forty-one real cycles of this particular machine, which turn out to be sixty-one minutes and 0.74 kWh, and the page says so. Be warned that in summer it will usually tell you it makes very little difference, which is the honest answer when a 35 kWh battery is sitting at ninety per cent: it earns its keep on dull days, through the winter, and once the price starts moving through the day. The plan is served over the same Bearer-authed route as everything else rather than dropped into the anonymous public folder, because when a household does its washing is nobody else's business.

**3.9.2** (09-Sep-2026) - **A page that has stopped updating now says so.** Both the Mains page and a meter's own page could render once and then stop for ever without a word, because the error message only appears when the page is empty - so a dead poll left perfectly plausible readings on screen with nothing but a quietly frozen clock to give it away. Once nothing has arrived for more than ninety seconds the live dot turns amber, stops pulsing, and the line reads "not updating for 4 minutes". It is driven by its own timer rather than by the poll, because a poll that has died cannot be trusted to report that it has died, and only a poll that actually returned data clears it. A failed poll is also written to the browser console now, so the next one of these leaves evidence.

**3.9.1** (08-Sep-2026) - **The voltage map is gone from the meter page, and both pages touch the screen far less often.** Every thirty seconds these two pages threw away the whole page and built it again, whether anything had changed or not. They now compare what they are about to draw against what is already there and write nothing at all when it matches, the card entry animation runs on the first paint only rather than on every refresh, and anything you have opened - the settings fold on a meter's page - is reopened after a rebuild instead of snapping shut twice a minute. Dropping the map also took a whole sweep of every device in the house off each request for one meter's detail.

**3.9.0** (08-Sep-2026) - **The Mains page leads with the meters again.** The voltage map and the table of how far each meter is out were two full screens of analysis sitting between the summary and the meters themselves, so the tiles were below the fold and easy to miss entirely. Both have moved onto the individual meter's page, which is where they belong: they are context for one reading, and a reader wondering whether 252 volts is high is looking at that meter, not at the wall of them. The map there shows every meter in the house that is reading a voltage right now, lowest to highest, with the one you opened picked out and its position given as a rank. A meter that is not answering gets no map, because it cannot be placed on a scale of live readings. The Mains page is now the trust summary, the four house figures, and then every meter as a tile.

**3.8.3** (08-Sep-2026) - **A meter that is not answering no longer shows a voltage.** The tile on the Mains page blanked the watts for a meter that had stopped answering and then printed its volts, amps and power factor underneath as though they were live, so an unplugged freezer monitor sat there reading 250.6 volts with no mains anywhere near it. They were the last values it sent before it lost power - Indigo keeps a device's readings until something replaces them, and nothing writes a zero when a device simply goes away. The whole reading is held back now and shown as "last sent", and a meter's own page carries one line saying the same thing about everything on it, since a frozen uptime or wi-fi signal looks just as ordinary as a frozen voltage.

**3.8.2** (08-Sep-2026) - **A meter's page no longer shouts a reading the rest of it is refusing to show.** The headline printed the last figure in large type beside the words "the device is not answering", while the gauges under it correctly showed nothing. The figure is still there, said as history rather than as a reading. Also: a meter heard from a moment ago says so, instead of "0 seconds ago".

**3.8.1** (08-Sep-2026) - **A meter that has dropped off the network is no longer counted at its last reading.** The Mains page asked only one of the four plugin families whether a device was still answering, so when a freezer monitor went off the wi-fi at nine in the evening the page carried on reporting 794 watts for it - which made the measured total that much too high and the unmeasured remainder that much too low. Every family says it in its own words, and one of them says it as a word rather than a yes or no, which is the awkward part: "Offline" is not nothing, so anything that treats it as a simple true or false reads it as healthy. All four are understood now, and a device that says something unfamiliar is treated as unknown rather than assumed well. The Active page also stopped identifying the relay-less monitors by their name and asks whether they have a switch at all, so renaming one cannot quietly put a read-only meter on a control page.

**3.8.0** (08-Sep-2026) - **Every meter on the Mains page is now a tile you can tap, and each one opens a page of its own.** The table read well on a laptop and badly on a phone, and it gave nothing to touch. Each meter is now a card carrying what fits - its power, its voltage, current and power factor, today's units, how far it normally sits from the reference, and whether it is answering - and tapping it opens everything else. That page leads with what identifies the physical plug, because two of mine are named alike and I could not tell them apart: the address, the network name, how long it has been powered, its lifetime energy, and a day of its load and voltage drawn out. Under that sits its measured offset, every reading it publishes, and the plugin's own settings for it, with anything that could be a credential kept back at the server. Two corrections came out of building it. A meter that reports only when something changes may never send the zero when it switches off, so the kitchen cupboard lights had been counted at 76 watts for the ten days since they were last on - the page believes the switch now, says what the old figure was, and the unmetered total is 76 watts better for it. And a Z-Wave meter's page failed outright, because Indigo hands some of its settings back in a form the reply could not carry.

**3.7.1** (08-Sep-2026) - **The Mains page now looks like the rest of the dashboard, and it counts every meter.** The page shipped yesterday relying on a shared stylesheet that does not exist - the theme file carries the colours and the type scale, and every page declares its own layout - so it rendered essentially unstyled beside its neighbours. It now uses the same cards, headings, tables, chips and gauges as System Health and Energy. Two meters were also missing from the census while appearing in the trust panel, which is built from history rather than live readings, so the page named seventeen meters and listed fifteen. Both are Athom monitors with no relay, which put their real power in a state none of the usual names cover, and they happened to be the two lowest readers - which is why the voltage map looked far tighter than the measured spread said it was. Both are in the census now, and a reading like that counts as power only on a device that is also reporting a mains voltage, so a light sensor can never be shown as watts.

**3.7.0** (08-Sep-2026) - **A new Mains page: every device that measures a 240 V load, and how far each one can be trusted.** The house measures its mains with four different families of meter and they do not agree. Measured against the inverter over a week, the two Athom plugs read about 1.7 V and 0.9 V low and the Shelly plugs about 2 V high - a spread of roughly 3.7 volts, or one and a half per cent. None of them is calibrated and the Shelly offers no way to trim it. So the page does not pick one number and call it the truth. It leads with a trust panel showing each meter's own measured offset and the spread across the fleet, then a voltage map putting every live meter side by side with the reference marked, so the disagreement is visible rather than hidden. Underneath: what the house is drawing that no meter can see, and a table of every meter with watts, volts, amps, power factor and today's units. A reading older than fifteen minutes, or one from a plugin that is not running, is shown as a last known value rather than a measurement - the kitchen extractor had been reporting an impossible 291 volts for weeks with its plugin long gone. Power factor is reported where the meter gives it and worked out where it does not, and watts are never calculated from volts times amps, which on a switch-mode supply overstates the load by more than half.

**3.6.0** (06-Sep-2026) - **Routine plumbing out of the shared event log.** About 79 lines a day of file writes and camera poller/proxy start-stop now go to the plugin's own log instead. The Night Sweep line stays where it was, because that one records the plugin actually firing an RF code at the living room fire - a thing done to the house rather than a note about itself. Setting Log Level to Debug also puts the narration back, which is what a log-level setting is for, and the field help now says so. Includes 3.5.0, which was never released.

**3.5.0** (05-Sep-2026) — **Dashboard presentation refresh.** Home and Energy share aligned power panels, animated directional paths, readable chart scales and a continuous forecast line. Section menus, battery graphics and history charts use consistent spacing and typography. Favourites retain keyboard focus during refresh. Numeric readings update immediately, without counting or rolling; directional power-flow animation remains. Real-data browser checks led to improved light/dark text contrast and an accessible table heading. No changes to energy calculations or device commands.

**3.4.0** (04-Sep-2026) — **A main light you can keep out of "All Off".**

A room's Lights tile has one button that turns everything on or off together, and there is usually one light you do not want in it — the ceiling light, when what you meant was the lamps.

A room can now name that light with `mainLight` in its `DASHBOARDS_ROOM_EXTRAS` entry. It still appears as its own tile and still switches on its own. It is simply out of the group: the button ignores it when deciding whether to offer On or Off, and leaves it alone when pressed.

That is the difference from `openLoop`, which is easy to confuse. An unreadable device is kept out of the *decision* but still gets the command. A main light is kept out of both.

The code for this was already there and had never worked. It filtered on a single id fixed at -1, which matches no device, in both the button's label and its action — so it read as implemented twice over while every light, main one included, went off together.

**3.3.0** (04-Sep-2026) — **Weather moves up beside Energy.**

The hub's glance row has three cards in two columns, so the third wrapped underneath and left a hole the size of the Weather card sitting beside it. Solar was being stretched to match Energy's height for no reason at all — 623 pixels of card around 240 pixels of content.

Energy now runs down the left across both rows, with Solar above Weather on the right, each at its own height. Nothing is hidden and nothing moved page.

It uses ordinary grid placement rather than fixed rows on purpose. The Solar card hides itself when there is no per-string data to show, and with fixed rows that would put the hole straight back — as it is, Weather simply moves up. Phones are untouched: everything is one column there, as before.

**3.2.0** (03-Sep-2026) — **A South array that generated 220 kWh in a day.**

The solar chart had the South string producing 215 kW at dusk, on an array rated 4.275 kW. The fault was next door in SigenEnergyManager, which read the inverter's per-string current as a plain number when the inverter sends it signed. As a string falls to nothing at dawn and dusk, its current dips a hundredth of an amp below zero, and read the wrong way round that tiny negative becomes 655 amps.

That is fixed at the source, but the bad readings are already in the history database and nothing rewrites what is logged. So the chart now throws out any per-string figure above 15 kW before it averages the hour. The bound is not a guess: across 383,000 logged rows the largest real reading is 4,705 W and the smallest wrong one is 32,832 W, with nothing whatever in between.

Twenty-one days of South totals come back to earth — the worst of them from 220 kWh to 8.5 kWh. An hour with nothing left after the filter draws a gap rather than a zero, because a zero would read as a genuinely dark hour and quietly pull the day down.

**3.1.0** (03-Sep-2026) — **Refuse the reflector, if you have another way in.**

Indigo's reflector relays remote traffic through Indigo Domotics' own servers, and they pay for it. Camera pictures are far heavier than it is meant to carry: one page left open away from home, asking for nine snapshots a second, is gigabytes a day. If you can reach your server another way when you are out — Tailscale, WireGuard, any VPN back to the house — there is now a checkbox in Configure that refuses the reflector outright.

With it on, every dashboard request that arrives through the reflector is refused, and a page opened at the reflector address stops before it asks for anything and offers the local address instead. That second half matters more than it looks: the camera pictures are static files the plugin never sees a request for, so stopping the page asking is the only thing that stops them being sent.

It is off by default. Plenty of installs have no other way in from outside, and quietly breaking those would be worse than the traffic.

**3.0.0** (03-Sep-2026) — **Something had to be able to say what the reflector is carrying.**

Indigo Domotics wrote twice about this server's reflector usage and deactivated the reflector the second time. The awkward part was not the traffic, it was that nothing on the server could answer "how much, and since when". Indigo's web server logs no successful request, so a page quietly pulling camera pictures through the reflector leaves no trace whatever, and the tunnel does not appear in `lsof` or `netstat` either.

It does appear in `nettop`. The reflector is one SSH reverse tunnel, so every byte in and out of that single process is the reflector and nothing else. The new `Reflector_Bandwidth_Watch.py` samples it every five minutes, logs a line for each finished hour, warns when an hour goes over 20 MB outbound, and keeps a week of hourly figures so a spike can be dated afterwards rather than guessed at.

Version 3.0.0 rather than 2.99.4 because this is the first thing the plugin has ever measured about its own effect on somebody else's bill.

**2.99.3** (03-Sep-2026) — **Says why six moving pictures is the most you can have.**

The cameras page shows six cameras moving and the rest as pictures that refresh, and nothing explained why. It is not a preference: a moving picture is one connection held open for as long as you watch, and browsers allow about six connections to one address, so a seventh never connects at all rather than merely running slowly. The Settings page's Cameras card now says so, and the README documents the `livePoolSize` key alongside it.

**2.99.2** (03-Sep-2026) — **The presence page speaks for three sensors now, not just two.**

Living Room's third FP300 (Presence_Watch.py 1.5, N-way agreement track) made the page's two-sensor assumptions show: the combined row was always labelled "Both", the "sensors reporting" stat was always "1 of 2", and the "no data yet" callout could only ever name one missing sensor. All three read correctly now for any sensor count, and the "sensors agreed" callout counts however many there are. Bedroom 1 is unaffected — still two sensors, same text.

**2.99.1** (02-Sep-2026) — **The cameras page stops hopping up and down.**

The bar along the bottom of the cameras page is stuck to the bottom of the screen, and its top line carries the live data rate. Every time that rate gained a digit — 19 kB/s to 153 kB/s and back — the line wrapped, the bar grew by a line, and the whole grid of cameras shifted. Measured on a phone-width screen: 74 pixels against 90, twice a minute, for as long as the page was open.

The line is now a single line that cannot wrap, and the rate reserves the width of its longest value, so nothing before it shuffles as it changes. The word "total" stays on the top bar, which has room for it, and the bottom bar says "health OK" rather than "camera health OK" — the line already begins "9 cameras". Measured again after the change: the same height at every rate from 7 kB/s to 12.3 MB/s, with nothing cut off.

**2.99.0** (02-Sep-2026) — **All four hub cameras go live when the link can carry them.**

The hub decides how many camera tiles may stream by measuring what the link can actually carry, and the measurement was too crude to trust. It fetched a 44 KB file once. A home network delivers that in about three milliseconds, so the reading was one scheduler hiccup wide — and the one sample it took was the cold one, the first fetch on a fresh connection. Measured here back to back: 6.9 Mbit/s cold, then 92, 126, 117 and 110. That first figure is a fifteenth of the truth, and it is below the bar for a single stream, so a phone sitting in the same room as the cameras was shown four three-second stills.

Interference on a network only ever runs one way — a cold connection, a slow start, the page's own loading, a sleeping phone radio all make a reading worse, and nothing makes bytes arrive faster than the link allows. So the probe now opens the connection first and throws that timing away, then takes the best of two samples of a file five times larger. The correction for round-trip time is bounded as well, so a fast link with a long ping cannot be credited with capacity it has not got.

Nothing about the policy changed: four tiles need about 34 Mbit/s, and a link that cannot carry them still falls back to stills rather than opening streams that queue and fall behind.

**2.98.0** (02-Sep-2026) — **Solar and weather are two cards, and each opens the page it is about.**

Today's generation was drawn inside the weather card, so a tap on the day's solar total opened the weather page. They are two cards now: Solar goes to Energy, Weather goes to Weather. The solar card draws itself and hides itself, so a server with no inverter gets no empty box.

**2.97.0** (02-Sep-2026) — **Live video is decided by bandwidth, and the pages say when you press them.**

The cameras were the real complaint. Whether a tile streamed live or polled a picture every few seconds was decided by how long a small file took to come back, and that is the wrong question: a stream needs throughput, not a short round trip. A phone on the house wi-fi with a VPN running measures about 116 ms because every packet goes out to the tunnel and back, so it was called remote and given three-second stills while sitting in the same room as the camera. The pages now measure how many bytes a second the link actually carries and open as many live tiles as it can hold, none if it cannot hold one. The room pages join in: they used to open a stream per camera whatever the link, which is why the Drive page showed three black boxes with question marks, and they now fall back to pictures that any link can fetch.

The light hub is gone. It hid the cameras, the weather and the alerts on a link it judged slow, and a missing region reads as a broken one however carefully it is explained. What it was trying to save is now saved where the data actually is.

Every favourite tile is the same size, whatever it holds. Anything you press is marked for a moment so you can see the press landed, on every page. Solar today has a line of its own on the hub's energy card. House, Rooms and Tools sit above Doors and Windows, within reach rather than under two status cards. On the energy page, Generation and forecast moves above Today's energy flow, and the battery fleet card is gone: the car's 12 V reading is a favourite on the hub and the house battery has a card of its own. The Rooms page gets the same Home button as every other page and lists the Living Room first.

Also: a Postgres session time zone of `localtime` is now refused rather than quietly resolved against the wrong machine's clock.

**2.96.1** (02-Sep-2026) — **The reflector is not free, and the plugin now behaves as if it knows.**

Indigo Domotics wrote to say this house was pushing a lot of traffic through its reflector. The address they saw was the house's own broadband line — a phone on the home wi-fi had been paired with the reflector address, so every camera still it asked for went out to Indigo's servers and back, nine of them a second on the cameras page. Nothing on the server could say which device, because Indigo's web server logs nothing for static files or authenticated calls.

Three things change. The plugin now looks at the headers on every dashboard request and, when one arrived through the reflector, logs a warning naming the device (its address and browser) and the LAN address to use instead — once an hour per device, not once a second. The pages slow right down on that route: the cameras page polls stills every 10 s (3 s for the tile you are looking at) instead of every second, the hub strip every 15 s instead of 3, and both stop altogether after ten minutes with nothing touched, resuming on a tap. The hub also says plainly that it was reached through the reflector and links the LAN address. And the pairing QR now carries the LAN address rather than the reflector one, so a phone paired at home stays on the LAN — the reflector link is still in the log for pairing a device that is away.

The server's verdict travels back with the device poll, so a page slows down even when its address bar shows a name the classifier does not know.

**2.96.0** (02-Sep-2026) — **The plugin stops assuming it is installed in this house.**

The rooms are the big one. A room is an Indigo device folder, and until now the list of folders that count was baked in — six names from one house — so on anyone else's server the plugin quietly produced no rooms at all, and the only way to change that was a key typed into the raw JSON box that nothing mentioned. The Settings page's Rooms card now shows every device folder on your server with a tick box beside it. Tick the ones that are rooms and save. The "Test Dashboards Setup" menu item checks the same thing and says so in plain words when none of the configured folders exist.

The site name comes out of the same card. Every page title, the hub heading and the home-screen icon used to say "Highsteads", which is my house. They now say "Dashboards" until you type your own name in.

The heating page's boost and force buttons only work with my EvoHomeControl plugin, so the page now hides that panel unless that plugin is installed, rather than answering every press with an error. The carbon region menu has an "Off (not in Great Britain)" choice that removes the Carbon page and stops the lookups, since the grid data only covers Great Britain. The hub's weather card works from an OpenWeatherMap key alone, with no Ecowitt station, and says what would fill it when it has neither. The energy page's car battery row comes from a vehicles entry in the settings rather than from a search for my car's name.

The setup check no longer paints five red lines on a healthy install for optional scripts it does not need; they are listed as skipped, and the check gained ffmpeg and the SQL Logger database. A fresh install gets one line naming any optional scripts it has not got, instead of five. Show Plugin Info prints your real dashboard address. The README's requirements now match the code: go2rtc can come from Homebrew or anywhere on your PATH, the credentials table lists the keys the plugin actually reads and drops one it never did, the room-extras section documents the plugs, fire and open-loop settings and the other config keys, and the repo ships an IndigoSecrets_example.py to copy from. The Configure dialog says exactly what a blank Indigo URL means.

**2.95.4** (02-Sep-2026) — **The fourth batch: the small things, and the tests that should have been there.**

A group favourite whose member cannot be read now says "1 unknown" rather than counting it as off. A hub press on a group with several PIN-protected members asks for the PIN once, not once per member. Four functions left over from the old tile wall are gone from the hub, along with the poll they ran for nothing every three seconds. A camera tile paused for a hidden tab keeps its last frame instead of going black the moment it was captured, a tile that keeps failing after a brief recovery is now parked like any other, a snapshot taken from a WebRTC tile saves the moving picture rather than the stale poster underneath it, and the still pictures work from Domio's mirror as well as the plugin's own folder.

The week-on-week tables on the energy and cost pages say when a window holds fewer than seven days and stop drawing a comparison arrow between windows of different lengths. The yearly total on the cost page is marked incomplete when a month has no figure to add. A day missing its export rate is valued at the latest known rate rather than nothing. The balance chart redraws the moment the plugin reports the battery's real capacity.

On the Settings page a favourite whose device or scene has since been deleted is named as missing and kept, so removing it is your decision rather than a side effect of saving. Opening Settings over the reflector now says the guest pairing URL has to be opened on the home network. A few smaller ones: the battery ring no longer paints an empty reading as 0 %, the forecast bars survive a string-valued hour, a download link in the standalone app downloads instead of navigating, the Wi-Fi list shows a 240 MHz channel, and the carbon page no longer labels a slot from late last night as "tomorrow".

Twelve more tests cover the startup page sync and its sweep, the credential fallback every non-secrets install relies on, the Configure dialog's live apply, the carbon time labels, and the thumbnail resize through the real function. The test runner now runs the same compile and lint steps as CI, and the tests README is generated from the files on disk.

**2.95.3** (02-Sep-2026) — **The third batch: the pages.**

Every page that talks to the plugin now checks first whether the plugin is in the middle of restarting. Three pages never did (Settings, Timeline and the setup page), and the Graphs and heating pages had one call each that slipped past the check. One tap on any of them mid-restart used to take the whole web server down for five minutes.

The hub's "Updated" clock no longer ticks while the plugin is away and the page is showing you its cache. The power-cut banner, the VPP chip and the money rows now fade out when the energy figures they come from are more than two minutes old, rather than sitting there as if they were live. Switching back to the light hub genuinely stops the camera streams and timers it was supposed to save you from. A camera tile whose live stream fails becomes a polled still with a badge instead of one frozen frame. The Doors & Windows card counts only the sensors that can actually report, and says how many cannot. The pressure trend stops rewriting its history on every three-second poll.

The solar charts on the hub and the energy page take "today" and "now" from the server, not from whatever clock the phone happens to be on. Viewed from Perth in December, the old way had most of the day's forecast already due while it was still breakfast time at home. The forecast accuracy tile no longer prints "100%" over no history at all, the car battery row says how old its reading is instead of painting a cranking dip as a live voltage, the manager's decision trace shows home, battery and grid figures it was always meant to show, and the cost page keeps its last good figures on screen when the upstream data comes back as an error.

On the room pages a window or motion sensor that cannot report reads as unknown, with the reason, instead of a confident "Closed" or "Clear". Windows and doors get their wording from the section they are in, not from a guess at the name. The "All Off" button decides from the same list the label was drawn from. Every on/off switch now checks back with the device a few seconds later and reverts if the command was swallowed. Brightness sliders on room pages survive a poll landing mid-drag.

The Settings page's raw JSON box can no longer leave a half-built form behind a bad edit, the form re-reads what the server actually kept after a save, and four fields that skipped the usual escaping now get it. The cameras page names a dead camera after three failed fetches instead of saying "Connecting…" for ever, treats a brief WebRTC hiccup as a hiccup rather than a sixty-second retreat, cancels an orphaned signalling request, and says in its footer when WebRTC is the thing in use. The weather station page greys a sensor that has stopped reporting and says when it last spoke, the carbon page stops asserting your tariff is flat, the Wi-Fi page marks every access point stale when the controller itself is unreachable, and the System Health page reads the Mac's memory size from the server rather than assuming eight gigabytes.

The presence page shows why a sensor's track is empty. The Timeline page no longer prints "00:60". The activity page stops polling from a background tab. Two hidden traps in the menu page and a null favourite that could blank the whole hub card are gone. The link-quality test harness now uses real promises and three differing samples, so a wrong estimator would actually fail it.

**2.95.2** (02-Sep-2026) — **The second batch: the plugin's mediums, and the lows that lived next door to them.**

The five companion scripts the plugin runs from its background loop now share one runner. It puts the host's import path back the way it found it after every run (each script had been adding a line to it every tick, for as long as the plugin stayed up), gives each script a small memory that survives between ticks so it can warn once about a missing device rather than every two minutes, and logs the first failure with a proper traceback instead of the same bare line 720 times a day. The loop itself now isolates every task on its own: one builder failing every tick used to switch off the log watch, the night sweep and the drive lights together, with one warning and then silence.

The hourly log watch has a watchdog now. If it stops completing runs, the plugin says so once a day in red, because nothing downstream would otherwise notice.

Pressing a colour preset on a lamp whose plugin has stopped, or whose communication is disabled, used to report success while nothing happened. Indigo swallows both without a word. The plugin now checks first and tells you which of the two it is. The heating page's boost buttons got the same check.

The carbon page's advice read the inverter's numbers as live even when the device was disabled or in error, and treated a missing number as zero. Unknown is now unknown, and the advice falls back to the carbon-only recommendation it already had for that case.

Files that hold secrets are created private from the first byte: the settings store, which carries the control PIN, was written world-readable along with every backup of it. The proxy's RTSP server now listens on loopback only, since the only thing that ever dials it is the proxy's own transcoder. A connection that goes quiet on the proxy port is dropped after thirty seconds rather than holding a transcode open for ever. The guest token no longer appears in full in the event log.

A blank Indigo URL in Configure now means the local server, as the dialog has promised since 2.0. Weather settings entered in Configure apply straight away rather than on the next restart. An install with no cameras gets one quiet line at startup instead of three warnings. Home Insights skip devices that are disabled or in error, and the battery trend looks for the exact column before it guesses. The solar-by-hour chart and the timeline agree with the clock on the two nights a year the clock changes.

Thirteen new tests, and the plugin's shared utility file learned the two letters PostgreSQL uses for true and false.

**2.95.1** (02-Sep-2026) — **The first batch from a full review: twenty-four faults, most of them quiet ones.**

Every Zigbee bulb on a room page had lost its brightness slider and was calling itself a relay. The device catalogue knows those bulbs can do colour, and the page took "colour" to mean "not a dimmer". It is both, and the slider is back.

The Alerts page was dead on arrival for anyone who had saved a rule. A helper it needed was declared further down the page than its first use, so the page drew its list, wired its buttons and then quietly stopped — no "now" readings, no notifications, ever. The helper now comes first.

The weather station page multiplied wind speeds by the wrong number for anyone not on this house's settings. It assumed metres per second and converted to mph, but the Ecowitt plugin's default is km/h, so a 20 km/h breeze read as 44.7 mph. It now reads the unit the plugin publishes, and does the same for temperature and pressure rather than assuming Celsius and hPa.

Two things on the camera side. The supervisor that restarts go2rtc when it dies gave up for good after one failed restart, because a failed start looked the same to it as "never started". It now remembers that it was meant to be running. And shutting the plugin down waited for any camera fetch in flight to time out before go2rtc was even told to stop, which with one camera offline could take longer than Indigo allows before it force-kills the plugin. go2rtc now stops first, nothing waits on the camera pool, and the whole teardown fits comfortably inside the window.

The cameras page, when opened away from home more than a minute after the last visit, never switched the focused tile to WebRTC. The check for "did the policy change" counted live MJPEG tiles, and the WebRTC arrangement has none of those, so nothing looked different. It now compares the whole decision. The same page could also leave an MJPEG stream running underneath a WebRTC tile on mobile data. It releases the old stream first now.

The guest tier had two faults that cancelled each other out. Browsers could not use it at all, because the proxy refused the preflight request the guest header forces. And had they been able to, the read-only feed would have handed over every device's plugin properties, which is where Email+ keeps the mail server password. Both fixed: the preflight is answered, and the feed carries names, states and classes only.

The go2rtc log file was readable by every account on the Mac and contained the camera password several hundred times over. It is now private to the Indigo user, and an existing file is corrected on the next start. The MJPEG route on the proxy port gained the same private-network check every other route already had, and the wildcard cross-origin headers on the camera routes now answer only pages served from the same machine.

The Timeline page opened with one query per lane that scanned the whole history table for that device — the pattern that froze the web server for three minutes in July. It is bounded by row id like everything else now.

The hourly log watch, once a Pushover or email send had failed, kept paging the same fault every hour until it stopped or was muted. A delivered alert now clears the retry flag.

For anyone running the SQL Logger on PostgreSQL: the history timestamps there are stored in local time, not UTC as they are on SQLite, and every graph, timeline and insight was an hour out for the eight months of British Summer Time. Booleans came back as the letters t and f and read as false. Both handled. This install is on SQLite, so none of that was visible here, but it would be on yours.

The System Health page reported a crashed plugin as running, because it asked "is it enabled" rather than "is it running". It asks the right question now, and tells a stopped plugin apart from one switched off on purpose.

A PIN with a non-ASCII character in it crashed the PIN check instead of saying no. Twenty-nine new tests cover the fixes, and the test harness can now drive the main loop's stop signal, which it could not before.

**2.95.0** (30-Aug-2026) — **The hub was hiding the cameras on the phone, and saying nothing about it.**

Four camera tiles on the laptop, none on the iPhone, both a few feet apart on the same network, both on the same build. Nothing was broken and nothing had been switched off. The hub has a light mode for when you are away, which drops the cameras, the weather, the alerts and two other cards to save mobile data — and it had decided the phone was away.

It decides by timing three small downloads and taking the middle one, and the middle one is the wrong one to take. A phone puts its wi-fi radio to sleep between requests, so it pays a wake-up that a laptop never pays, and two slow readings out of three are enough to push the middle reading over the line. The quickest reading is the honest one: a request can arrive late for all sorts of reasons, but none can arrive sooner than the wire allows. It now takes the quickest of the three. The bar has not moved and does not need to — a link from outside the house cannot produce a fast reading however many times you ask it.

The worse half was the silence. Cameras that vanish with no explanation read as cameras that are broken, which is exactly how this one came in. The light hub now says so in a line above the gap, names what it has held back, and that line is the button: tap it and this device shows everything from then on. Tap it again to go back. The choice is remembered per device, so the phone and the laptop can differ.


**2.94.0** (30-Aug-2026) — **Changing a lamp's colour is now one request, and the server does the work.** Pressing a colour preset used to fire three separate commands from the phone, in a fixed order — switch on, set brightness, set colour — each one wrapped so that a failure said nothing. A phone that locked, went to another app or lost signal part-way through left the lamp half-set: the right brightness with last night's film colour still on it, or on at full white when you asked for something dim. The plugin now runs the whole sequence in one go and reports each step, so a failure is something you are told about rather than something you notice later.

The presets themselves moved to the plugin at the same time, and the page draws its buttons from them. Editing a preset now changes what the button says and what it does together, instead of in two files that could disagree.

While in there: the two preset buttons had been printing the names of their icons — they read "cloudsunWarm white" and "filmMovie". They draw the icons now.

**2.93.0** (30-Aug-2026) — **One tile for the living room.** The colour lamp, the twigs, the display lights and the fire now sit behind a single Favourites tile: one press puts the lot on, with the colour lamp going to full rather than wherever it was left, and the next press puts the lot off. The tile says what it can see — "On", "Off", or "3 of 4 on" — so a half-lit room still reads honestly.

The fire is in the group but does not get a vote on which way a press goes. It is a one-way radio relay: Indigo knows only what it last transmitted, so a fire lit from its own handset still reads off, and letting that belief count would stop the tile ever offering to turn things off — the same trap the room page's All On / All Off button fell into. Every member is commanded on each press, including any already believed to be doing the right thing, because that is the only way to be sure about one that cannot be read.

Building it turned up something that had been quietly waiting to bite. The settings editor drew each favourite from a picker of devices, scenes and doors, and threw away any row it could not draw — so opening Settings and pressing Save would have **deleted all three room shortcuts**, with nothing said and no way to tell what had gone. Anything the editor cannot draw now rides through a save untouched, keeps its label editable and can still be moved or removed. That covers rooms, groups, and whatever a future version adds.

**2.92.1** (30-Aug-2026) — **The Conservatory fan, the three living-room lamps and the fire are now one tap from the hub.** They join the front door and the garage in Favourites as plain on/off tiles that show what each thing is doing and switch it when pressed. The living room's main ceiling light is deliberately not among them.

Adding them turned up a small fault worth its own line: Settings offers a label box on every favourite, and the on/off tiles were the one kind that threw it away. The live device name won, so a label you typed was saved and then never shown — which is how the fire came to be titled "Fire On/Off" above the word "On". A typed label now wins, as it already did on the door and reading tiles, and leaving the box empty still shows the live name so a rename in Indigo carries through on its own.

**2.92.0** (28-Aug-2026) — **The drive lights now simply come on at sunset and go off at sunrise.** Both of them, at full brightness, all night. That job had been split between seven separate pieces of automation — on at sunset plus thirty minutes, off at ten to midnight, three motion triggers that lit them for two minutes at a time, and two more that turned them off again — and between them they never quite added up to "on when it is dark".

The motion triggers had to go rather than simply be left in place: each lit the lights with a two-minute auto-off attached, so anyone walking up the drive after dark would have switched them off again shortly afterwards, which is the one thing an all-night light must not do. They are disabled rather than deleted, so the old arrangement can be put back in a moment.

It is checked every two minutes rather than fired once at dusk, which means it repairs itself: a missed command, a bulb that dropped off the mesh and came back, or a power cut at three in the morning are all corrected on the next pass instead of leaving the light wrong until the following night.

**2.91.0** (28-Aug-2026) — **The overnight lights sweep now runs itself.** The plugin ticks it every two minutes, alongside the presence, log-error and sensor-config watches it already drove. Indigo's scripting interface can create a schedule but cannot give it anything to do, so a schedule made that way would have sat there running nothing — this is the same reason the other three are driven from here.

Two minutes is not arbitrary. The sweep only acts after an unbroken run of observations and throws the lot away if more than ten minutes passed since it last looked, on the grounds that nothing watched that gap. Tick it more slowly than that and it quietly stops doing anything at all. Outside its night window each tick reads two variables and returns.

**2.90.0** (28-Aug-2026) — **A device that cannot be read no longer decides the All On / All Off button.** The living room fire is a one-way radio relay: Indigo only knows what it last transmitted, so a fire lit from its own handset still reads as off. That belief was enough to stop the Lights button ever offering “All Off”, which meant the single press that would have turned the fire off was never on offer — the button showed “All On” instead and would have lit everything.

Such a device now gets a vote in the command but not in the decision. The button makes its mind up from the lights it can actually read, and then sends the command to everything — including whatever it already believes is off, and including the fire. Sending an off to something already off costs nothing, and it is the only way to be certain about a device that cannot answer.

**2.89.0** (28-Aug-2026) — **Rooms you use most get a second row in Favourites.** Pin any room and it appears as a shortcut under the live tiles — one tap from the landing page to that room, without going through the Rooms menu. They sit on their own row rather than mixed in among the device tiles, because one is somewhere to go and the other is something to switch, and a card that muddles the two makes you read every tile before pressing anything.

They are pinned by room name rather than by an id, so renaming a room in Indigo carries the shortcut with it instead of leaving a tile pointing at nothing.

**2.88.1** (28-Aug-2026) — **A browser with an out-of-date key no longer fills the log.** Four of the hub's background pollers fetched directly rather than through the usual API wrapper, which meant they never noticed being refused — they simply asked again half a minute later, indefinitely, and every refusal wrote a warning to the Indigo log. That is roughly a hundred and twenty lines an hour, per open tab, for a key that was never going to start working. They now report a refusal like everything else, so three of them are enough to prompt for the key again. A server error or a missing endpoint is explicitly not treated as a credential problem, because clearing somebody's key over a temporary 500 would be worse than the noise.

Two of those pollers also kept going in a background tab. The rest were taught to stand down last week and these two were missed, which is why a tab nobody was looking at could sit there filling the log.

**2.88.0** (28-Aug-2026) — **The landing page stops being a contents page.** House, Rooms and Tools were three stacked walls of tiles sitting open on the hub, which is a lot of scrolling to reach something you already knew the name of. Each is now a single tile that opens its own page, exactly the way Energy · Now opens the energy page, and that holds whether you are at home or away. What is left on the landing page is what a landing page is for: the greeting, your favourites and Energy · Now.

The “Needs attention” strip has gone as well. It and the Insights card below it were drawing from the same list — the strip showed a count and the first item and existed mainly to point at the card — so there was never a reason to read both. Insights keeps the detail and now takes itself off the page entirely when it has nothing to report, which the strip was invented to work around.

**2.87.1** (28-Aug-2026) — Fixes two things in yesterday's lean hub. The Insights and log watch cards were being made visible when the full layout came back, showing as empty strips on every home load — they ship hidden on purpose and now go back to exactly how they started. And the layout tweak is wrapped so that whatever it does, the greeting, the favourites and Energy · Now still come up: a cosmetic adjustment has no business being able to take the page down with it.

**2.87.0** (28-Aug-2026) — **Away from home, the hub stops fetching the house.** The landing page off the LAN is now three things: the greeting, your favourites and Energy · Now. Cameras, weather, the doors-and-windows strip, insights and the log watch are not drawn and, more to the point, not fetched — everything is still one tap away under House and Rooms. The saving that matters is not the cards, which never held the page up anyway; it is the four camera thumbnails that were being re-fetched every three seconds for as long as the page stayed open, which on a mobile connection is the part you actually feel. The page assumes it is away until it has *measured* otherwise, because its address is the same either way and believing the address is how a phone on 5G ended up being handed the full picture. At home nothing changes but one extra render.

**2.86.0** (28-Aug-2026) — **The garage door tile on a room page now asks the door itself.** It had been doing what four other places in the house used to do — pulsing a relay and working out whether the door was open from a single contact sensor — which is precisely the job the garage door plugin was written to take over. It now reads that plugin's own state, which means it can finally say *Opening…*, *Closing…* and *Stuck*, none of which two bare contacts can tell you. The button follows the state showing: closed offers to open, open offers to close, stuck offers to close because securing the house is the useful recovery, and while the door is moving there is nothing to press — interrupting an opener mid-travel does unpredictable things. A door the page cannot read shows a dash rather than a reassuring "Closed". Doors still configured the old way keep working exactly as before.

**2.85.0** (28-Aug-2026) — **The living room fire gets a tile of its own.** It turns out it had been in the room's data all along, filed under a heading no page has ever drawn, so it was present, correct and completely invisible. It now sits in its own section with the same toggle as the lights and the television, and deliberately not among the lights — a lit fire counting as "one light on" is the sort of small wrongness that quietly teaches you to distrust the number above it. The tile shows what Indigo last told the fire rather than what the fire is actually doing, because that radio only talks one way and there is no honest way to pretend otherwise. Along the way a lamp retired a fortnight ago came out of two sort orders it could no longer appear in.

**2.84.4** (20-Aug-2026) — **The dashboards now explain the picture rather than merely drawing it.** Energy’s forecast line carries a lightly shaded *typical* range based on its own recent average error—explicitly not a promise about today’s weather. Each solar array gains a daily yield fingerprint, deliberately descriptive rather than a fault verdict because roofs, direction and shade differ. A small decision trace puts the live solar/home/battery/grid flow into words, and a manual replay lets you step through the same half-hour slots behind the history graph. The Hub brings current Home Insights to the top as a compact “Needs attention” card. Hidden Hub and Energy tabs stop their routine polling and catch up immediately when you return. Cameras now report a concise health state—OK, retrying or offline—without exposing stream addresses, errors, credentials or viewer data in the anonymous public file. Finally, a regression test keeps the four release-version declarations together.

**2.84.3** (18-Aug-2026) — The grid-events table drops the "Our kWh" and "Diff" columns. Our own figure is measured over a different span from Axle's — the plugin drives the export either side of the paid window — so setting the two beside each other under a heading like "Diff" invited exactly the wrong reading: that a wide gap meant Axle had short-changed you. On 11 August it showed 7.05 against 3.801 while the paid hour itself was textbook. The figure is still recorded, and is still what makes an over-running window detectable, but it isn't this table's business.

**2.84.2** (18-Aug-2026) — A 404 from the solar plugin's API no longer logs as a warning. It isn't a fault — it means that plugin is older than the thing being asked for, which is the ordinary state of affairs while the two are being upgraded. The Cost page asks for the earnings ledger every five minutes, so an open page would have put an amber line in the log every five minutes for a system doing precisely what it was designed to do. Anything that is a real failure still warns.

**2.84.1** (18-Aug-2026) — Internal tidy-up with nothing to see. The two VPP lines on the hub moved into functions of their own so they can be tested properly, which matters because the states they describe — a window running, a feed that has stopped answering — turn up a few times a month and are exactly the ones you would never notice being wrong. Writing the tests promptly caught a hole in them: one branch escaped the text it was given and its twin did not, and only the escaped one was covered.

**2.84.0** (18-Aug-2026) — **What the grid events have actually earned.** The dashboard has always been able to tell you a grid event was running, and never once what it paid — the only place that figure existed was the Axle account page. The Cost page now carries a Grid events card: the balance waiting to be withdrawn, the lifetime total, this month, and the grid-event earnings kept apart from the monthly floor payments and any signup or referral credit, because lumping those together flatters the battery considerably. Below it, every event with Axle's settled figure beside our own. That pairing is the point of the card — Axle pays on the change against a baseline rather than on raw export, so their kWh always runs a little under ours, and a gap of about a fifth of a unit is perfectly ordinary. A much bigger one means the export ran on past the paid hour, and there is nowhere else you would ever see it. An event Axle has not settled yet reads "pending", never £0.00: settlement runs several days behind, so the newest event is normally unsettled and a confident zero would be reporting a loss that never happened. The hub's VPP line is now always there, saying "none announced" when there is nothing coming — which, alongside the feed-health check beside it, is what stops a dead connection to Axle looking like a quiet fortnight.

**2.83.0** (13-Aug-2026) — **Grid voltage on the battery card, and it's worth a look.** The register the solar plugin had been reading for mains voltage turned out to be the 230 V nameplate rather than a measurement. The real one reads **252 V**, against a UK statutory ceiling of 253 — and above that an inverter is obliged to curtail or shut down, so it costs you export earnings and the cause sits with the network operator rather than anything here. The tile warns within three volts of the limit and goes red past it. The limits come from the plugin rather than being written into the page, since they aren't the same on every network.

**2.82.0** (13-Aug-2026) — **Three more tiles the documentation paid for.** Reading the inverter's own protocol document named several readings the plugin had measured but couldn't identify, and the battery card now shows the useful ones: the **inverter's temperature** (58 °C — its power electronics, which nothing here had been watching), **PV insulation resistance**, and whether the inverter is **carrying an alarm**. Insulation resistance is shown deliberately without a verdict: it's a safety reading — a falling value means water getting in or a damaged cable — but the manufacturer's fault threshold isn't published, so the honest use is to watch it drift rather than judge it against a number we'd be making up. The inverter's own alarm answers the pass-or-fail question.

**2.81.0** (13-Aug-2026) — **The battery card says what it can about the four packs.** Asked to show each pack's charge and temperature, the honest answer came from a probe rather than a guess: the inverter doesn't report them. What it does report is the average, the hottest pack and the coldest — and over four identical packs those three are enough to work out whether one is out of step with the rest. The card now says so in words: on today's reading, **one pack is running 4.8°C above its neighbours**. There's a grid-frequency tile alongside it, showing how far the mains has drifted from 50 Hz — the thing a grid event is ultimately about, and the reason the battery gets asked to export during one. Neither tile appears unless the figures support it: a card that cannot know must not reassure.

**2.80.0** (13-Aug-2026) — **The hub's Solar · today shows the same chart.** The block on the front page had only ever shown the forecast — bars for what the day was meant to bring, and nothing about what it actually brought. It now draws the same chart as the Energy page, smaller: hours that have happened stacked in the four string colours, each with its dashed forecast tick, so you can see at a glance which hours beat their forecast without opening anything. The scoreboard sits alongside Remaining and Tomorrow. To make that possible the chart itself moved into the shared code both pages load, so there is one implementation drawn at two sizes rather than two that can drift apart. The other half of the change is quieter but worth knowing: the hours endpoint now also returns the whole-system total per hour, taken from the same query at no extra cost. That figure has been recorded for years, so both charts can now draw a full day — including the mornings before per-string recording began — from a single request, and the hub needs no history fetch of its own. Cross-checked against the day's own total on the way in: 42.14 kWh summed hour by hour against 42.2 kWh recorded, which is the arithmetic proving itself.

**2.79.0** (13-Aug-2026) — **The hourly solar chart grows up.** The little strip of forecast bars is now a proper chart, twice the height and with a scale. Hours that have already happened show what the panels actually did — stacked in the four string colours from the Sigen app, so you can see which roof each slice came from — and each hour carries a small dashed line at the height the forecast promised. A stack that tops its line beat the forecast, one that falls short didn't, and a line under the chart keeps score in words: "Beat the forecast 7 of 7 daylight hours so far". Hours still to come stay as pale forecast bars, and tapping any hour spells out its per-string breakdown against the forecast. Mornings from before the per-string readings existed draw as plain single-colour bars, and an hour with no data at all is left as a gap rather than drawn as a zero — a chart must not invent. The per-string strip below the tiles also gains each string's total for the day.

**2.78.0** (13-Aug-2026) — **The Solar card shows the race against the forecast, and each string of panels.** A new chart on the Energy page's Solar card draws two lines through the day: a solid one climbing as solar is banked, and a dashed one showing where the bias-corrected forecast said you would be, running on to dusk. The gap between them is the story — a chip above the chart says it in words, "4.5 kWh ahead" or "behind" or simply "on forecast". No new plumbing: it is drawn from the history and forecast the page already fetches, so it works away from home like everything else. Below the solar tiles, a new per-string strip shows what each string of panels is producing right now — one row per string with a bar scaled to that string's own capacity once named, so a small string pulling its weight reads as full beside a big one. The strip needs SigenEnergyManager 5.67.0, which reads the four strings from the inverter; until that plugin is updated (or on an inverter without per-string readings) the strip simply stays hidden.

**2.77.0** (13-Aug-2026) — **The Front Door joins in, and readings can carry a colour.** The Front Door button — which still said Open Front Door and still flashed green — is now a state tile like the garage's. It reads plain Front Door, white and quiet while the door is closed and locked. Press it and the unlock sequence runs under the same blue veil, and the tile then tells the story itself: red Open while the door stands open, blue Unlocked if the door is shut but the lock has not gone home yet, and back to white Locked when it has. Only the locked tile is pressable — nothing on a dashboard can close a front door, so the open and unlocked states simply say what they see. The door contact is believed before the lock, so a dead lock can never hide an open door, and if the contact goes silent the tile shows a dash rather than a comforting Locked it cannot know. Any reading favourite can now colour its value too: give it an amber-below and a red-below figure in Settings and the number turns green, amber or red as it moves. The Qashqai battery voltage uses it first — green at or above 12.4 volts, amber below that, red under 12.

**2.76.0** (13-Aug-2026) — **One garage button instead of two.** The hub's Favourites carried an Open Garage and a Close Garage button — two tiles for one door. They are replaced by a single tile that watches the door itself. Closed, it sits quietly in white saying Garage Closed. Press it and the door opens — the tile turns blue with a moving bar while the door travels, then red, Garage Open, for as long as it stands open. Press it again to close, blue again on the way down, and back to white when the door is home. Because the tile is driven by the door's real state rather than by whatever was last pressed, it doubles as an indicator — open the garage from the hall button or from HomeKit and the tile goes red on its own. While the door is moving the tile ignores presses, since jabbing an opener mid-travel does unpredictable things, and if the door sticks part-way the tile goes amber and says so, a press then trying the safe direction, closed. If the door's sensors stop reporting, the tile shows a dash rather than guessing — a tile that cannot know must not claim to. It is a new favourite type in Settings, so any door with a state device and a pair of open and close actions can have one, and the press confirmation from 2.75.0 still runs underneath — the in-flight veil now matches the tile's blue, and the green "done" flash is gone for doors because the tile turning red or white is the confirmation.

**2.75.4** (13-Aug-2026) — **The camera log now says which day it is talking about.** go2rtc, which does the camera work behind the scenes, stamps every line it writes with the time and not the date. That is fine for an hour and useless after a week, and it cost real time this morning working out whether a run of camera errors came from last night or from days earlier. go2rtc cannot be told to do otherwise, so the plugin now writes a short dated line into that log when it starts and again whenever the date changes. One line a day, and any error can be placed on a day again.

**2.75.3** (08-Aug-2026) — **Added the missing support link.** Every Indigo plugin is meant to carry a web address inside its bundle — it is what the "About" item in the Plugins menu opens. This one had the entry but left it blank, so that menu item went nowhere. It now points at this repository. Nothing else changed.
**2.75.2** (02-Aug-2026) — **Dropped the "Run" label from the hub's scene tiles.** It was there to say the tile was a button rather than a reading. The takeover covers the whole tile the moment you press it, which says the same thing far more clearly, so the tile now only needs to name itself.

**2.75.1** (02-Aug-2026) — **Housekeeping.** The FP300 configuration watch shipped with the author's own MQTT broker address as its fallback, which meant anyone running it without that key set was pointed at an address that is not theirs; it now names the missing key in an error and skips, rather than guessing. The demo data still listed a relay retired in June. And the lint gate, which had drifted to sixteen findings and so was being read by nobody, is clean again — eleven were the companion scripts using the `indigo` name the host injects, now ignored on purpose and in writing; the other five were real.

**2.75.0** (02-Aug-2026) — **The door buttons now tell you what actually happened.** Pressing Open Front Door, or either garage button, used to answer with a tick twelve pixels tall, printed inside the tile your finger was covering, for a second or so at best — and often for no time at all, because the hub rebuilds that card every three seconds and threw the tick away before it could be read. It was also confirming the wrong thing. Indigo answering a control button means only that it accepted the request: the garage script can drop a press on its own five-second guard and still answer normally, and the front-door script then spends up to ninety seconds retrying the unlock. So the tick said Done whether or not a door had moved, and a dead network looked exactly the same as a success. Now the button itself takes over. It fills with colour, says what it is doing, counts the seconds, and holds until the contact sensors confirm the door really has moved — Opening, then Door moving while both reeds are apart, then Garage open. A failure goes red and says why. A press nothing confirms goes amber and tells you to check the door rather than quietly claiming success. Which sensors mean what is configuration, not code, so anyone can point the same mechanism at their own doors, and the confirmation rides the device poll the pages already run, so it costs no extra traffic. Two things behind it are worth naming: the garage's Open and Close buttons ran the same toggling script, so Close would open a closed garage, and they now use the direction-safe force actions instead; and the Scenes page has been unable to run anything at all since 2.73.0, where a refactor moved it onto the shared client without loading it — every press threw and reported a failure. Both fixed here.

**2.74.0** (01-Aug-2026) — **An hourly watch on the presence sensors' own settings, because they quietly revert.** The two Aqara FP300 sensors in the bedroom kept losing their lock on a sleeping person. Presence held for a few hours from bedtime and then broke into dozens of short gaps, the worst of them seventy-five minutes, and the cause turned out to be a setting on the sensor rather than anything in Indigo. Adaptive sensitivity had been switched off back in June, exactly so the radar would stop learning a motionless body as background, and a battery change on the 6th of July put it straight back to the firmware default, where it sat unnoticed for four weeks. The absence timer was no better at ten seconds against a range that runs to three hundred, which turns any brief loss of lock on a sleeping chest into an empty room. Both are now watched hourly by a new companion script, `FP300_Config_Watch.py`, which compares the live values against the intended ones, warns when they drift, and puts them back over MQTT. It only writes while a sensor reports presence, because these are battery devices and zigbee2mqtt will not reliably hold a message for one, so the correction lands the next time somebody walks into the room. It also watches the power-outage counter, which is the earliest sign a sensor has been reset and wants its settings again.

**2.73.0** (31-Jul-2026) — **The review's final tier: sixty-odd smaller fixes and quality-of-life improvements.** The ones worth naming: the hub's room tiles are now built from your own rooms rather than fourteen tiles naming the author's house; the heating page finds its zones the same way; a new "Test Dashboards Setup" menu item runs a PASS/FAIL sweep of everything a stuck install needs checked; the control PIN no longer travels to the browser at all (the settings page keeps it without ever seeing it); go2rtc can live anywhere (config field, PATH, or the old `~/bin`); the weather card's OpenWeatherMap key gains the standard config-dialog fallback; guest data routes lost their wildcard CORS; camera viewers' IP addresses and user agents no longer reach the public streams file; demo mode wears an exit banner; pairing QR codes work when the server address is set to localhost; the Postgres history path survives text containing tabs and newlines; and the accessibility layer now treats content rendered after page load. Under the hood: rooms.json is rebuilt every 30 seconds rather than every 2, the changed-device ledger can no longer drop a fresh change during pruning, and the test suite — now wired into CI, which previously ran no tests — runs against stubbed credentials with several tautological tests rewritten so they can actually fail.

**2.72.0** (31-Jul-2026) — **Forty-seven fixes from the deep review's medium tier, across the plugin and thirteen pages.** The highlights: go2rtc is now supervised, so a crash mid-run restarts it instead of silently killing every camera until someone restarts the plugin; Configure changes apply live (they were all restart-only, including the bootstrap security toggle); the "Regenerate Config" menu no longer wipes credentials on installs that configure through the dialog rather than IndigoSecrets; the heating page's control buttons no longer error for everyone (they were wired to a private plugin only the author has — from 2.96.0 the panel is only shown when EvoHomeControl is installed); the hub's weather card and the Ecowitt page find your sensors by what they report rather than by this house's device numbers; four pages' "Updated" clocks now tell the truth instead of advancing on a blind timer through an outage; a wrong PIN no longer freezes the whole plugin for half a second; the carbon advisor fetches in the background instead of stalling every request behind a 20-second lookup; identical energy-page polls queued behind a slow Sigen fetch now share one answer; the Graphs state picker stopped full-scanning the largest table in the history database; room pages honour your configured sort order in every section; a failed door-relay release now retries and says so; and the log watcher stopped double-counting its deliberate window overlap. Plus a raft of smaller honesty and robustness fixes — see the repo history for the lot.

**2.71.0** (31-Jul-2026) — **Presence data off the public internet, and the two companion scripts now ship with the plugin.** The Presence page's data — fourteen nights of room occupancy and a bedroom sleep timeline — was written into Indigo's anonymous `/public` folder, which the reflector serves to anyone who knows the address. It now lives beside the companion scripts and is served through a new key-protected `presenceData` endpoint; the old public copy is deleted automatically on upgrade, and the Presence page asks for the same key as every other data page. The script that builds it also had every history query rewritten onto primary-key ranges: the old queries full-scanned the (unindexed, 2 GB here) history database about 168 times per run while blocking the logger's writes — the rewrite does the same work in half a second. Both companion scripts (`Presence_Watch.py`, `Log_Error_Watch.py`) are now in the repo under `scripts/` with their own README, and the plugin logs one line per boot naming whichever is missing instead of silently doing nothing.

**2.70.1** (31-Jul-2026) — The plugin now pauses four seconds at the start of every shutdown, after flagging "stopping", before tearing anything down. A page's liveness verdict can be up to two seconds stale, and on a fast machine the old shutdown could complete inside that window — killing the plugin while a page, acting in good faith on the stale verdict, still had a poll on the wire. The pause lets every page notice the flag and go quiet while the plugin is still able to answer.

**2.70.0** (31-Jul-2026) — **A plugin restart no longer takes the web server down with it.** Restarting the plugin used to freeze Indigo's whole web server for about five minutes: any page still polling for updates would catch the plugin mid-stop, and that one stranded request blocked everything — every dashboard, every API call — until it timed out. The plugin now heartbeats a tiny liveness file every two seconds, flips it to "stopping" the moment a stop begins, and every page checks it before polling: when a stop is under way the pages go quiet, show their last known state, and pick up again on their own a few seconds after the plugin returns. Pages also stop polling while their tab is hidden, give up on hung requests after ten seconds rather than letting them dangle, and no longer re-download the entire device list every three seconds for the whole outage when the server is unreachable. Works over the reflector too, and older pages simply behave as before.

**2.69.0** (30-Jul-2026) — **Live video away from home.** The big tile now plays real, moving video when you are away — WebRTC straight from the house over the VPN, at about half a megabit, roughly a second behind reality. Tap another camera and the stream follows. The other eight tiles stay as still pictures refreshing every second, and if the stream cannot connect or stalls, the tile quietly falls back to exactly what it did before and retries later — it can never end up worse than the previous release. At home nothing changes: six live tiles on the house wi-fi as always. The little badge under each tile also now tells the truth about how often a still refreshes.

**2.68.0** (30-Jul-2026) — **Groundwork for a live camera tile away from home.** The plugin's camera proxy gains a small signalling route that lets a browser set up a WebRTC session with the go2rtc engine already running behind the scenes, and go2rtc now listens for that traffic over UDP as well as TCP. Nothing on the dashboards changes yet — this release carries the plumbing and a hidden test page, and the live tile itself follows once real-phone testing passes. One quiet fix: go2rtc no longer advertises the house's public internet address in its connection offers, which it had been doing to no purpose.

**2.67.0** (30-Jul-2026) — **Every camera tile can now tell you how old its picture really is.** The focused tile shows a small age chip — *age 2.3s* — computed from the frame's own timestamp, and it keeps counting up when nothing new arrives rather than pretending all is well. Tap the policy line in the footer and every tile shows its age, which is the view to screenshot when something looks stale. Live tiles show how long ago the picture last visibly changed, labelled as the different measurement it is, and if your device's clock disagrees with the server's the readout says *clock?* instead of standing behind a wrong number.

The *Updated* clock in the header is honest now too: it only ticks when a real frame arrives, not when a stream merely starts or the page shuffles images about. And a live tile that misses its ten-second connection window now gets retried on the usual backoff, instead of silently sitting on still pictures until the page was next re-laid-out.

**2.66.0** (30-Jul-2026) — **The hub tells you when a grid event is coming, and which version you are running.** The carbon-intensity chip has gone from the greeting row — useful to some, not to everyone, and it was costing a request every five minutes whether anyone looked at it or not. The Carbon page itself is unchanged and still on the tile wall.

In its place, a chip appears when a battery-trading event is announced or running, showing the window, and the Energy card gains a matching line. Both vanish the rest of the time, so nothing new clutters an ordinary day. The running version now sits beside the date at the top of the page, taken from the plugin itself rather than written into the page, so it always describes the build actually running.

**2.65.1** (30-Jul-2026) — **Two faults on the energy page, both hidden until a grid event finally turned up.** A battery-trading event was announced for the evening, and it was the first one in six weeks — which is precisely why neither of these had been seen before.

The alert strip along the top printed raw page source instead of an icon: a line of `<svg class="dsh-icon" …>` in red across the width of the phone. The strip is only ever used for exceptions — a storm warning, a lost connection to the inverter, a grid event — and none of those had happened since the icons were introduced, so nothing had ever drawn it. Underneath it, the little status chips beside "Live power flow" were positioned to float over the heading, which was fine while there were two of them; the event added a third, the row grew leftwards, and it ended up sitting on top of the title. The chips now share a row with the heading and wrap underneath it when there are too many, so a fourth would simply move down rather than collide. Both are display-only — nothing about how the battery is managed was affected.

**2.65.0** (30-Jul-2026) — **The camera page no longer opens six video streams before checking where you are.** Until now the page trusted its own address at boot. On this network the address always looks local — even from a phone on 5G reaching home through a VPN — so the page started all six live streams first and asked questions afterwards. On mobile data those streams flooded the link, the measurement that should have corrected the mistake got stuck in the queue behind them, and tiles that stalled were quietly dropped to a slow five-second refresh they could never escape.

Four fixes, all on the camera page. It now boots on the last *measured* answer, remembered for sixty seconds per browser, and starts with still pictures when there isn't a fresh one — at home that costs under a second before live video appears. A tile dropped to the slow refresh is properly restored when circumstances change, instead of being left there for good. A stuck download is abandoned after ten seconds rather than silently freezing its tile forever. And the "Updated" clock now only ticks when a real frame arrives — hiding the page used to fire nine phantom updates that stamped it fresh and turned every status dot green.

The result away from home should be pictures roughly two to three seconds old instead of nine. The next releases add an honest per-tile age readout so that claim can be checked on the phone itself, then a proper live tile for the away case.

**2.64.0** (30-Jul-2026) — **Stop guessing whether you are at home, and ask.** Everything up to here inferred it from how long a request took, because that was the only signal the page had. It is a poor one: with a VPN running permanently, home reads 116 milliseconds and mobile data reads 245, and no line drawn between two numbers that close is trustworthy.

But the answer was already sitting on the server. The UniFi controller knows which phones are associated with which access point, and the UniFiHealth plugin publishes that as a device carrying both `presence` and the network name — *Highsteads_AX*. That is not an estimate of whether you are home. It is the fact.

So the camera page now asks. Tell it once which phone it is running on — there is a small **"this device is:"** link at the bottom of the page — and from then on it knows exactly where it is. On the house wi-fi you get live video, VPN or no VPN. Off it, still pictures. The footer says which network it found you on, so the reasoning is never hidden.

Three things it is careful about. The sighting has to be **recent**, because the controller holds a phone as "home" for a few minutes after it has actually gone, and being wrongly at home is the expensive direction. The timing has to agree as well, so one stale reading cannot on its own open six video streams on mobile data. And the question goes over the **authenticated** interface, never the public one — whether anybody is home is not something to serve anonymously to the internet.

If you never set it, nothing changes: the page falls back to timing exactly as before.

**2.63.0** (30-Jul-2026) — **Catering for a VPN that is always on, including at home.** The previous release worked out whether you were on your home network by timing the connection, and treated anything slower than 50 milliseconds as away. That quietly assumed you would turn your VPN off indoors. You should not: switching it off on wi-fi to get live video also leaves it off on café and hotel wi-fi, which is the one place it really earns its keep. Asking for that was bad advice and this release takes it back.

The difficulty is honest. Measured on a phone, home wi-fi with the tunnel up reads **116 milliseconds**, and 5G with the tunnel up reads **245**. That is barely a factor of two, and a good mobile connection can beat a poor wi-fi one — so no single dividing line can tell those two apart, and pretending otherwise would just move the mistake around.

So it no longer pretends. There are now three bands rather than two. Below 50 milliseconds is certainly your own network and runs the full six live streams. Above 150 is certainly not, and runs still pictures as before. **In between — which is where a VPN at home lands — it runs exactly one live stream instead of six.** Get it right and you have live video at home with the tunnel up. Get it wrong and it costs one stream rather than six, and the existing stall watchdog drops it to stills within seconds, because a connection that cannot carry video shows it almost immediately. Being wrong in that band is survivable. Being wrong at six streams is what stalled the phone in the first place.

The footer now distinguishes them too — *VPN, near* against *VPN, far* — because both read simply "VPN" before, at 116 milliseconds and at 245, which is exactly what made this hard to see.

**2.62.0** (30-Jul-2026) — **Live video at home had been switched off by one millisecond.** The page decides whether you are on your home network by timing the connection, not by trusting the address — a home address reached through a VPN looks identical to the real thing. The bar was 20 milliseconds. Measured on the phone, on home wi-fi with the VPN off, the answer was **21**. So it concluded "not home", quietly served still pictures instead of live video, and did that everywhere, always. Nothing looked broken, which is why it went unnoticed.

The 20 came from assuming a home connection is a couple of milliseconds. That is true of a computer on a cable and **not** of a phone on wi-fi, which is the thing that actually matters here. The bar is now **50 milliseconds**, which sits midway between the two real readings — 21 at home, and 116 through the VPN *in the same building*, so a genuinely distant connection cannot get near it. It is also kinder to anyone whose wi-fi is slower than ours.

**The other half: turning wi-fi off changed nothing.** The verdict was worked out once and kept for as long as the tab stayed open, so a phone put down at home and picked up on mobile data carried on behaving as though it were still at home. It now expires after a minute, and the page re-checks whenever you come back to it — which on a phone is exactly when you have moved.

Both were found from four numbers off the page's own footer. It reports the connection it measured, which is the only reason any of this was visible at all.

**2.61.2** (30-Jul-2026) — **The bandwidth figure in the header was measuring the wrong machine.** On a phone on mobile data it read **3.0 MB/s**, which is alarming and was nonsense — the real figure was about 130 kB/s, so it was overstating by roughly twenty times, in the direction most likely to worry someone watching their allowance.

It was summing the camera server's own byte counters: the video it pulls **from the nine cameras across the house network**, which it does whether or not anybody is looking. Nothing to do with the phone at all. The header now counts what the page itself actually downloads, and only credits the server's figure to a tile genuinely holding a live stream.

Two things fell out of fixing it. Away from home no tile is live, so the once-a-second request the page made purely to read those counters was fetching a number nothing used — it is skipped entirely now, which is one request per second less from every phone. And the little green dot on a still tile was showing that *the server* was receiving from that camera, not that *your tile* was updating, so a frozen tile could sit there looking healthy. Each tile is now judged on its own last delivered picture.

**2.61.1** (30-Jul-2026) — **Two faults reported together: a lot of HTTP 500 warnings in the log, and the refresh jumping between three and seven seconds.** They turned out to be unrelated, and neither was where it looked.

**The warnings.** The camera server shells out to a second program to rescale each picture, and that program occasionally exits without producing one — which comes back as a bare "HTTP 500" and reads like a broken camera. It is not: measured over 270 requests, 4 failed, **and all four succeeded on a single retry a quarter of a second later**. None needed a second attempt. So a failed snapshot is now simply asked for again, once, and only becomes a warning if that fails too. A failure used to cost that camera a whole two-second cycle as well, because its picture was never rewritten.

Two things it is *not*, both tested rather than assumed. It is not the nine cameras being fetched at once — fetching all nine together produced **no failures at all** in 135 requests, while spreading the same nine across the same two seconds produced two, so staggering them would have made it slightly worse. And it is not the rescaling itself — fetching the picture at its native size still failed, and tripled the bytes.

**The jumping refresh was the dashboard, not the server.** Over three minutes the nine pictures were rewritten **797 times at an average of 2.04 seconds apart, with no gap longer than 2.5 seconds**. What varied was the page asking for them. It ran on a fixed one-second beat and skipped any beat where the previous request had not come back yet — so a request that overran by a fraction cost a whole second, and on a connection with a round trip near a second, ordinary variation dropped beats and the rate visibly sawtoothed.

It now schedules the next request from the moment the last one **finishes**, waiting out whatever is left of the second. On a quick connection that is every second as before. On a slow one it simply asks again shortly after each answer arrives, instead of missing beats. It also cannot overlap itself, so there is nothing left to skip.

**2.61.0** (30-Jul-2026) — **The grid was being sent pictures three times bigger than it could show.** The eight thumbnails are drawn about 300 pixels wide on a desktop and less than that on a phone, but each one was arriving at 640 pixels. The plugin now writes a second, smaller copy of every snapshot and the grid uses that, while the focused tile at the top — the only one big enough to tell the difference — keeps the full-size picture.

Measured across all nine cameras: **33.2 kB per full picture against 12.3 kB per thumbnail**, so one pass over the grid drops from 299 kB to 87 kB. The four camera tiles on the hub get the same treatment, and they are smaller again.

The end result, over the reflector, sampling what was actually on screen:

| | data | picture on screen |
|---|---|---|
| before both changes | 786 kbit/s | 3.44 s old, 5.33 s at the worst |
| after 2.60.0 | 1235 kbit/s | 2.63 s, 4.00 s |
| **now** | **496 kbit/s** | **2.47 s, 3.43 s** |

So it is now **using less data than it did before any of this started, and showing you a picture nearly two seconds fresher**.

The obvious way to make a smaller picture is to ask the camera server for one — it takes a width, and that is how the full-size snapshot is already fetched. It is also wrong. Eighteen requests a pass instead of nine made it start refusing, because each camera was being asked to decode two frames in quick succession. Shrinking a picture we already have takes **1.6 thousandths of a second** and leaves the cameras doing exactly what they were doing before. The snapshots still land every 2.04 seconds, unchanged.

Shrinking needs a library called Pillow, which Indigo installs on first start. If it is ever missing the pictures do not disappear — every tile quietly goes back to the full-size one, which is what it used before this release, and the log says so once.

**2.60.0** (30-Jul-2026) — **The pictures were still about five seconds behind when away from home.** Measured over the reflector with all nine cameras, sampling continuously what was actually on screen rather than what had just arrived: the picture you were looking at was **3.3 seconds old on average and 5.0 seconds old at the ninety-fifth percentile**. That is the "about five seconds" to the tenth of a second, so the report was not a rough impression, it was the number.

Most of that was the page guessing. It asked for a fresh picture every three seconds and paid the full 26 kB to find out whether there was one, which there usually was not — the server only takes a new photograph every two seconds. So the page now **asks instead of guessing**. It sends back the timestamp of the picture it already holds, and the server either says "nothing new" in **53 bytes** or ships the new one. That is five hundred times cheaper for the answer "no change", and it is what makes asking every second affordable rather than extravagant.

Measured afterwards, same nine cameras, same link: **2.4 seconds on average and 3.6 at the ninety-fifth percentile**. Asking three times as often costs almost nothing extra, because you cannot download a picture that does not exist yet — nearly half the requests now come back as "nothing new". Against asking every second the old way it moves 44 per cent less data.

What is left is not the page's to give back. About a second of it is the wait for the server's next photograph, and 0.9 of it is the round trip out to the reflector and home again. Both are real distances, not waste.

A note on why this is not a push notification, which would be the obvious way to be told rather than to ask. A push needs a connection held open, and everything a plugin does goes through a single thread — one held-open connection would stop every other thing the dashboards do, for as long as it lasted. Asking conditionally gets almost all the benefit and holds nothing open. It also works over the reflector, which the streaming port does not.

Two smaller things fixed alongside. A tile whose previous request has not come back yet now skips its turn instead of asking again, so a slow connection quietly asks less often rather than building a queue it can never clear — the same runaway backlog that used to leave live video half a minute behind. And a tile handed a picture every second gives the old one back properly when it switches to live video, which it previously did not.

**2.59.2** (29-Jul-2026) — **Some camera tiles never updated at all while others were fine.** Reported as .56, .57 and .68 frozen on their first picture while the rest kept up, and that turned out to be exactly the right clue.

The snapshot poller had always skipped any camera someone was watching live, on the sensible-sounding grounds that if you are watching the stream you do not need the still picture as well. That stopped being true the moment the dashboards started using pictures instead of live video when away from home, because the person watching live and the person looking at pictures are now usually two different people. One browser left open at home held six streams and quietly froze those six cameras' pictures for everybody else. Measured: the six with a viewer were 294 to 298 seconds stale, the three without were fresh within two seconds.

Every camera is now photographed whether anyone is watching it live or not. The skip existed to avoid a genuine clash that used to produce errors, but that clash was with a different internal stream than the one used today — checked with a live viewer attached, six snapshots in a row came back correct and quickly and the live picture was undisturbed. Verified after the change with three live viewers attached: all nine cameras refreshing ten times in twenty seconds, the watched ones no different from the rest.

**2.59.1** (29-Jul-2026) — **The camera stills were only as fresh as four seconds, whatever the page asked for.** The snapshot poller fetched all nine cameras one after another, and nine sequential fetches take longer than its two-second interval — so it simply ran back to back and each picture was actually only replaced every **4.1 seconds** (measured across all nine over half a minute). A page asking every three seconds was therefore re-downloading pictures it already had, and that accounts for most of the "the stills are five to ten seconds behind".

The fetches now happen at the same time instead of in turn. They are pure waiting-on-the-network, so overlapping them costs nothing at all, and a pass now takes as long as the slowest camera rather than the sum of all nine. Measured afterwards: **every camera refreshing every 2.0 seconds**, which is exactly what it was always meant to be. A camera that has stopped answering no longer holds the others up either — it waits on its own and the rest carry on without it.

With the pictures genuinely arriving twice as often, the tile you are actually looking at now refreshes every two seconds to match, and the other eight stay at three to keep the data down. Two seconds is the floor worth asking for — anything faster just fetches the same picture again.

**Live video is now off entirely when you are away from home.** On a phone a live tile measured over thirty seconds behind, while the plain pictures beside it were five to eight seconds behind. Live video sends every frame in order and throws nothing away, so on a connection that cannot keep up the backlog simply grows and never recovers — and it costs around 17 Mbit/s to fall further and further behind. A refreshing picture asks for the newest frame each time and cannot drift like that. Away from home it is better on both counts, so there is nothing left to weigh up.


**2.57.1** (29-Jul-2026) — **The camera page now says what it is doing.** Along the bottom it reports which kind of connection it thinks you are on, how many tiles are live versus refreshing stills and how often, and which version of the page you are actually looking at — for example *"VPN · 1 live + 8 still @3s · build 2.57.1"*.

This is here because "the cameras stop when I am away" took three attempts, and each one began by not knowing two things: which connection the phone had decided it was on, and whether it had even picked up the new page. A dashboard kept on a phone's home screen resumes from memory and will happily run last week's code for days without re-fetching it. Both questions are now answered on the device itself, which is where the answer has to be.

**2.57.0** (29-Jul-2026) — **Cameras stopping when you are away from home.** Reported again after the last two attempts at it, so this time the page was loaded over the reflector and measured rather than reasoned about. Six of the nine tiles were loading and three never loaded at all, and across any twelve seconds every tile was blank for most of it.

The cause was not the streams, the connection or the watchdog — it was how a tile refreshes. Pointing a picture at a new address clears it instantly and leaves it empty until the new one arrives. At home that gap is about five milliseconds and you will never see it. Over the reflector one snapshot takes three quarters of a second, and all nine were asked for at the same moment, which took nearly two. Against a three second refresh the tiles were empty more often than not, and the last three in the queue were cancelled by the next refresh before they ever finished — so they showed nothing, ever.

Each tile now loads its next picture quietly in the background and only puts it on screen once it is ready, so the previous one stays up in the meantime and a slow connection costs freshness instead of a blank square. The nine requests are also spread across the refresh interval instead of going out together. Measured over the reflector afterwards: **nothing blank at any point, all nine updating.**

Also fixed: if you reach the dashboards over Tailscale using its name rather than its address, the page had been treating the connection as if it were the reflector and switching live video off needlessly. It now recognises it properly.

**2.56.0** (29-Jul-2026) — **The Graphs and Timeline pages were freezing the whole plugin while they loaded.** Indigo's history database has no index on its timestamp column, so asking it for "everything in this day" makes it read the entire table — and while it does, it holds a lock that stops the SQL Logger writing and stops this plugin answering anything else. Measured here: one Timeline load read its forty tables for **7.6 seconds**. That is the freeze that has been showing up as pages briefly dying, and it is now **46 times faster — 164 milliseconds**, returning exactly the same rows.

The method was already in the plugin, added a year ago for the same reason, but had only ever been wired to one page. Wiring it to the other two turned up something better: the helper doing the work **opened with a full table scan of its own**. It asked SQLite for the smallest and largest row number in one go, and it turns out that asking for both at once makes SQLite read the whole table, where asking for each separately is instant. On the largest table that one line cost 96 milliseconds every call. Splitting it in two is the difference between the fix working and the fix being slower than the problem. There is a test that checks the query *plan*, not just the answer, because both forms return the same numbers and a tidy-up would put it straight back.

**2.55.2** (29-Jul-2026) — **The Energy page could freeze solid if the battery skipped a reading.** The inverter is read over Modbus, and now and then a read comes back with the battery level missing from it. The page took that gap as a number, tried to print it, and fell over — quietly, halfway through drawing, so everything below the power-flow diagram stopped updating while the clock at the top carried on saying "live". You would have had to reload to notice anything was wrong. An unknown level now reads as a dash, and the ring goes a neutral grey rather than red. That last part matters more than it sounds: filling the gap with a zero would have been the easy fix, and it would have shown you a flat battery and a red warning ring on a pack that was actually full. A missing reading is not a reading of nought, and the page now says so.

**2.55.1** (29-Jul-2026) — **Security: the video backend was handing out your camera password to the whole network.** go2rtc, which the plugin runs to turn camera streams into something a browser can show, exposes a small web API. It needs no password of its own, and one of its endpoints returns each camera's full connection URL — which has the camera username and password embedded in it, in plain text. That API had been bound to every network interface rather than kept on the machine itself, and configured to accept requests from any website.

Two consequences. Anything on your network could read the camera password by asking. Worse, because it accepted requests from anywhere, any web page open in any browser on your network could quietly fetch it in the background and send the credentials somewhere else.

It is now reachable only from the Indigo machine itself. Nothing needed it exposed: the plugin has always talked to it over the local loopback, no dashboard page ever used the port, and the one page that once did was retired. The camera list the dashboards do fetch has had the passwords stripped out of it since 2.35.0 — this closes the door that stripping was standing in front of.

**If you run this plugin, change your camera password.** It has been readable on your network for as long as this has been running.

**2.55.0** (28-Jul-2026) — **Every page was quietly downloading the whole house, every three seconds.** The dashboards were built to ask the server "what has changed since I last looked" and fetch only that. It turns out they never did. The marker they send starts at zero, the server quite correctly answers "you had better take the lot" to a marker of zero, and the code that took the lot forgot to move the marker on — so it stayed at zero for ever and every single poll fetched all 214 devices. That is 685 kB every three seconds for each open page, where the answer should have been 498 bytes. The marker is now set on that path too, which is a two-line change for something that has been running since the feature shipped over a year ago. Nothing looks different, it is simply enormously lighter — and if you have a dashboard sitting open on a wall tablet, that is a great deal of traffic that will now stop.

The existing tests all replaced the very function that was wrong, which is exactly why they had never noticed. The new ones drive the real thing.

Three others found in the same sweep. **Away from home, a camera could get stuck on stills.** With a single live stream shared between the tiles, the tile you tapped to the top was allowed to go live, but if its connection then stalled the code that tries again was still asking an older question — "is this one of the tiles that starts live" — and quietly refusing. It logged that it was retrying every second and a half while doing nothing of the sort. The reverse could happen too: the tile you had moved away from could bring itself back to life, leaving two video streams running on precisely the link that cannot carry them.

**A safety check on the video backend had never once run.** It looks for a leftover copy of go2rtc still holding the port after an unclean shutdown, which would otherwise leave your camera or password changes silently not taking effect. A missing import meant it failed instantly, every time, into a catch-all that made the failure look identical to a clean result. It works now, and if it ever cannot run it says so rather than pretending all is well.

**Two tick-boxes did not do anything when un-ticked.** Indigo stores a cleared box as the word "false", which any programming language will cheerfully read as true. This install was never affected — the setting had never been saved — but anyone who did open the configuration and untick "seed the API key automatically" would have found it still seeding.

**2.54.0** (28-Jul-2026) — **The cameras stop flooding a mobile link.** Away from home the hub's camera strip was opening four live video streams at once — about 17 Mbit/s, continuously, on the page you land on, and with none of the stall detection the cameras page has. What happens now depends on how you reached the dashboard, which the page knows the moment it loads. On your own network nothing changes. Over the VPN the top camera stays live and the rest fall back to the still image the plugin already keeps up to date, refreshed every three seconds. Over the remote link, where live video was never actually reachable, every tile uses stills — which is why they used to sit there doing nothing.

The camera page follows the same rule. It had been running six live streams at once regardless, despite a comment claiming it ran one; away from home it now runs a single one, and that one **follows whichever camera you tap to the top** rather than staying put.

The snapshots themselves were being fetched at the camera's full resolution — 1280x720, up to 173 KB — and then displayed in a tile a couple of hundred pixels wide. They are fetched at tile size now, which took the average from 96 KB to 33 KB with nothing visibly lost.

Together: the hub over a remote link goes from 17 Mbit/s of streams that could not connect, to about a third of one.

**2.53.1** (28-Jul-2026) — **The power-flow diagram now appears on a phone in portrait.** It had been shown only above 600 pixels, because the Energy and Weather cards stayed side by side on a phone and each was only about 205 pixels wide — too narrow for a four-node diagram to be read. Those two cards now stack in portrait, so each gets the full width and the diagram is clearer there than it is on a desktop. Turning the phone no longer makes it vanish and reappear either: the card's frame is built once and never rebuilt on a rotation, so only the rows underneath change, and they change straight away rather than on the next poll.

**2.53.0** (28-Jul-2026) — **The hub's Weather card now leads with the sun.** Sunshine is weather, and the card was a plain list of readings sitting beside a diagram, so it had nothing to look at. It opens with the day's generation against the forecast, a bar for how far through that you are, and the hour-by-hour forecast with the hours already gone faded back and the current hour picked out — the same chart the Energy page draws, from the same code, so the two cannot drift apart. Underneath it, what is left to come today and what tomorrow is expected to bring. The weather readings follow as before.

The Energy page's copy of that chart had its colours written in rather than read from the theme, so its bars kept light-mode colours in dark mode, and one of the two was the battery green from before the colour-blindness fix — a colour that no longer meant anything. Both now follow the theme.

**2.52.1** (28-Jul-2026) — The power-flow diagram on the hub now shows everything its twin on the Energy page shows. It had been dropping the Solar, Home, Grid and Battery labels, and giving the battery's charge percentage where the Energy page gives what it is actually charging at — so the two drawings of the same thing disagreed about what they were telling you. Same labels, same figures, same battery treatment now; only the size differs. The battery's stored energy comes from the pack's own reported capacity, so it is right for any size of battery rather than assuming this one.

**2.52.0** (28-Jul-2026) — **The static files stopped being pulled out from under the web server.** "Internal server error" lines had been appearing for days whenever a page or script was requested — 23 of them on one day — and every single one landed within seconds of a plugin restart. That is when the plugin copies its pages out to the web folder, and it did so by emptying each file and then filling it, so a browser that asked at the wrong moment got half a file and an error. Each file is now written beside its target and swapped into place in one step, so a reader gets either the old one or the new one and never something in between. Tested by asking for six files continuously across a restart: 4110 requests, no failures, where the same test used to reproduce the error every time.

**The battery green has changed.** Under the commonest form of colour blindness the old mint green and the solar amber beside it collapse into nearly the same olive — they sit together on the flow diagram, in the Sankey and in every chart, and were indistinguishable. Deepening the green to a sea green separates them properly, and fixes a readability problem at the same time: the old mint was too pale against a white card to meet the standard for large text, and the new one comfortably does. Solar is unchanged, and nothing else in the palette got worse.

**Every "Back" button now says "Home", because that is where it goes** — none of them ever went back. The shape scale is applied rather than just declared, collapsing seventeen different corner radiuses to five. And icons now fill in wherever they appear, including parts of a page built after it loads, which had been leaving empty squares on the Settings page.

**2.51.1** (28-Jul-2026) — Four emoji survived the icon sweep because they live in the plugin rather than in a page: the Insights card's battery, quiet-sensor, temperature and left-on markers were built server-side. They are drawn icons now like everything else. Also fixes the screenshot tool, which happily wrote a styled "404 — Not Found" page into the repo and reported success — a missing page comes back as plain text, so the check that was looking only at HTML responses never saw it.

**2.51.0** (28-Jul-2026) — **A design system, and the end of the emoji.** Every page used to declare the whole palette itself, light and dark, in its own stylesheet. Twenty-three copies of anything drift, and these had: the page background was one grey on eighteen pages and a different grey on five, so it visibly changed as you moved between them; fourteen pages used the dark-mode red for errors while in light mode; there were three different card shadows and two different greys for secondary text. None of it was a decision anyone made. There is now one stylesheet holding the colours, the type and the shape, and the pages read from it — so changing a colour is one edit rather than twenty-three, and the next drift cannot start. The font stack is one stack too: fourteen pages had left out the Windows and Android fallback, so most of the dashboard dropped to a plain system font on those devices while a handful did not.

The other half is the icons. There were 106 emoji standing in for icons across the pages — the hub's tiles, the system page's status chips, the room cards, the timeline lanes. Emoji are a font rather than artwork: they look different on every platform, they carry their own fixed colours that fight whatever is beside them, and they ignore the colour a page asks for — the hub's tinted icon squares have always set a colour that the emoji inside simply disregarded. They are replaced by 48 drawn line icons that take the colour of whatever they sit in, so the hub's tiles now read as one set rather than a ransom note.

Three pages got more than paint. **Overview has gone** — it predated the redesign, used a card style nothing else did, and showed you open contacts, low batteries and heating that the hub, the system page and the heating page had each done better for a while; the links that led there now go to the timeline. **Heating's controls** were six identical outlined buttons stretched across a row, so turning the heating on for a day looked exactly like the button that writes a line to the log; the real actions now look like actions, cancelling is quieter, and the diagnostic sits out of the way. **The house diary** was a log tail: the battery optimiser thinks out loud in the log, and the filter that looks for the words "flood" and "power cut" was catching every line of it, so a quiet evening produced a dozen near-identical entries. Its working is now filtered out, repeats collapse into one line with a count, and a long notification is an entry rather than a wall of text.

**2.50.0** (28-Jul-2026) — **The live power flow has been redrawn, and its movement now means something.** The old diagram put four labelled boxes around a circle marked "INV", joined them with straight lines at right angles, and ran three dots along each line at a fixed speed. That last part was the real problem: two hundred watts trickling in looked exactly like eight kilowatts pouring in, so the animation was decoration rather than information. The four corners now carry drawn icons instead of emoji, each with its own reading beneath it, and the battery wears its charge as a ring around its own icon rather than a bar tucked underneath. The lines run on the diagonal and carry a moving dash whose **speed and thickness both rise with the power going through it** — so the busiest leg is now the one that catches your eye, and a glance tells you roughly how much is moving before you read a single figure. Readings count up to their new value rather than jumping. Anyone who has asked their system to reduce motion gets the thickness and the colour without the movement. A long-standing fault is fixed along the way: the flow colours were written into the page as fixed values, so in dark mode they stayed on the light palette while everything around them changed — they now follow the theme like the rest of the page. The same diagram, in a smaller form, has replaced the list of numbers in the hub's Energy card, and the hub, the energy page and the overview now agree on how a wattage is written; the hub used to round differently from the page it links to. On a phone the hub keeps its list, which reads better at that width than any diagram would.

**2.49.0** (27-Jul-2026) — **Camera tiles now notice when a live stream has quietly stopped, and fall back to updating stills.** Away from home on a weak mobile signal the live view would connect, deliver its first frame and then simply stop, leaving what looked like a working camera showing one frozen moment with nothing to say it had died. The page did already have a stall check, but it was watching the wrong half of the journey — it counted video arriving from the camera into the server, which carries on perfectly happily while the leg from the server out to your phone is the one that cannot keep up. So it could only ever catch a camera going quiet, never the case that actually bites when you are out. The tile now watches the picture itself, on your own device, and if it stops changing for nine seconds that camera drops to a still image refreshed every five seconds — around a tenth of the bandwidth, and fetched by a route that works from anywhere. It says "slow link" underneath, so it is obvious why it is not moving rather than looking like another fault. When the signal recovers the tile puts itself back to live, and if it keeps failing it waits longer each time so a poor connection is not hammered pointlessly. At home, where the stream never stalls, nothing changes at all.

**2.48.0** (25-Jul-2026) — **Something now watches the Indigo log for you.** Nothing did. You could set a trigger to catch an error you had already met and named, but a problem you had never seen before sat in the log until you happened to scroll past it — which, on a good week, is never. The Activity page collapses errors neatly, but only while you have it open, and it forgets everything the moment you close the tab.

A new script, `Log_Error_Watch.py`, reads the log every hour. It groups errors that are really the same fault into one entry, ignoring the digits that change between them, so fifty register-read failures read as one problem with a count beside it rather than fifty lines. It keeps a note of what it has already seen, and tells you only about what is genuinely new, or what has been going wrong all day without being fixed. The first run is deliberately silent: it writes down everything already in the log and treats the lot as normal, so you are not woken on day one by the background hum your house has been making for months. You get one Pushover with the headline and an email with the detail, and errors are the only thing that reaches your phone — warnings are recorded and shown, but they never buzz.

The results appear at the top of the **Alerts** page, kept clearly apart from the notification rules below it, because those still only work while the page is open and this one does not care either way. A chip appears on the hub when there is something wrong and stays out of the way when there is not. The feed is served over an authenticated route rather than written into the public folder, since log text tends to carry hostnames, addresses and fragments of tracebacks, and the public folder is readable by anyone who finds it.

Writing the script turned up a real fault in the Activity page. Messages from Indigo itself carry the bare word "Error" where a plugin would carry its name, and the code that strips that suffix expects a space in front of it, so every server-level error had been filed under a plugin called "Error". They now say "Indigo Server".

To mute a known nuisance, add it to the `MUTED` list at the top of the script. It ships empty on purpose — muting things before you have seen what your log actually says is a good way to hide a fault you would rather have known about.

**2.47.0** (25-Jul-2026) — **A tidier Graphs page, on/off states drawn properly, and PostgreSQL support.** Indigo's SQL Logger cannot change a column's type once it has been created, so when a device starts reporting a state differently the logger quietly adds a second column and leaves the first behind for good. Those dead columns were being offered for charting alongside the live ones — 256 of them here, and picking a battery level on one device meant choosing between three near-identical entries. They are now hidden. The same fix closes a subtler one: the Timeline and Home Insights cards look up a column by prefix, so they could quietly chart a dead one.

On/off states are now drawn as a **step** with an on/off axis and a "on for N% of the range" figure, instead of a line sloping between 0 and 1 through readings that never happened.

If your SQL Logger writes to **PostgreSQL** rather than SQLite, Graphs, Timeline and Home Insights now work — pick the backend in Configure and use the new **Test History Connection** menu item to check it. Credentials come from `IndigoSecrets.py` first (`HISTORY_PG_*`) and the dialog is the fallback. Access is read-only and there is no new dependency to install. SQLite remains the default and is unaffected.

The two-backend idea and the dead-column filter are borrowed, with thanks, from the [Domio](https://github.com/simons-plugins) plugin. 56 new tests.

**2.46.1** (25-Jul-2026) — Pages shown inside the Domio iOS app now get all their scripts. The plugin copied a fixed list of three shared script files into Domio's folder, and that list had fallen behind what the pages actually use — so the Domio copies had been running without the accessibility helper and without the charting library for some time, and the new Energy and Cost pages would not have rendered at all. It now copies every shared script, the same way it copies every page.

**2.46.0** (25-Jul-2026) — **The Energy and Cost figures were audited against the live system, and the Cost page rebuilt.** Six faults, every one confirmed against the old code before it was touched. The biggest: the half-hourly energy chart double-counted. It stacked Solar and Export upwards and Home and Import downwards, but export is part of what solar generated, not something on top of it — on a real day, 36 kWh generated drew a stack reading 48. It is now an honest picture of supply against use: solar, battery discharge and grid import above the line; the house, battery charging and export below, with the two sides balancing to within the battery's round-trip loss. The Sankey diagram lost energy quietly — the solar block was drawn taller than everything leaving it, with no explanation — so conversion and round-trip losses are now shown as their own flow and both sides add up. A missing battery reading used to drop the state-of-charge trace to zero and report a false low; gaps now simply break the line. The week-on-week bill charged nothing for standing charges on any day recorded before the plugin started saving them, which made recent weeks look dearer than older ones for no real reason. Small watts printed as "0.03 kW", and a half-penny export rate rounded to the wrong whole number. And the battery capacity was hardcoded to this system's size, so every stored-energy and backup figure was wrong for anyone else — it now comes from the plugin.

The **Cost page** has been rebuilt to match the Energy page's depth: the headline saving now splits into the import you avoided and what the export earned; each daily bill shows how much of it the export covered; the month card has progress meters; and the one chart with two different scales became two charts with one each, because the daily figures and the running total were never comparable heights. Both roll-up tables now read as a sum you can check by eye — solar benefit = grid-only − elec bill + export earned — and gained sticky headers. Chart colours come from the theme, so they follow dark mode, and the stacked series order was checked for colour-blind separation.

The duplicate money cards are **gone from the Energy page** — today's cost, yesterday, the whole-house bill, period totals and calendar months all live on the Cost page now. The two pages had been showing different numbers under the same word "Net" on the same day. Needs SigenEnergyManager 5.52.0. 39 new tests.

**2.45.1–2.45.2** (21-Jul-2026) — Housekeeping pair. Named log levels now map to the real logging levels — warnings and errors raised through the shared helper had been appearing as plain info lines, so amber and red entries people relied on for diagnosis never showed. Shared-utility refresh: calling the log timestamp filter twice no longer double-stamps every line, and the module imports cleanly outside Indigo.

**2.45.0** (19-Jul-2026) — Expected total on the Energy page solar card: generated-so-far plus the bias-corrected still-to-come, so the card's headline matches what the day will actually add up to.

**2.44.1** (18-Jul-2026) — The energy tile no longer drops to a 502 when the Sigen data takes its time — the SigenProxy timeout goes from 8 to 12 seconds.

**2.44.0** (15-Jul-2026) — Backup runtime chip. The Energy page's live power flow card gains a chip next to the grid status showing how long the battery could power the house in a power cut, at the current house draw — stored energy above a 5% reserve floor divided by what the house is using right now. It's a live estimate: daytime solar would stretch it, heavier usage would shorten it, and the help tip says so. Green above 8 hours, amber below 2.

**2.43.0** (15-Jul-2026) — Week on week. The Energy and Cost pages each gain a "Week on week" card: the last 7 recorded days against the 7 before, with change arrows — solar, home use, import, export and self-sufficiency on the Energy page, and the electric bill, export earnings and net position on the Cost page (estimated from each day's saved rates). Both cards carry a "same week last year" column that fills in automatically once a full year of history has been collected, using a 364-day offset so weekdays line up.

**2.42.0** (15-Jul-2026) — Home Insights. The hub now has an Insights card that compares the house against its own history and only speaks up when something is genuinely out of the ordinary: a battery falling unusually fast (with a days-left estimate), a normally-busy motion sensor that has gone silent, a room noticeably colder or warmer than it usually is at that time of day, and anything that has been switched on far longer than its daily norm. It reads the history the SQL Logger already keeps, the analysis runs in the background on the server (a 15-minute cache keeps it cheap), and when all is well the card simply says so, along with how many checks it ran.

**2.41.0** (15-Jul-2026) — A proper test suite. The plugin now ships with a contract-test layer that runs with no Indigo server and no camera hardware, so the trickiest logic is pinned against regressions: the room-classifier truth table, battery detection across the three idioms the estate uses, camera-config parsing, the door-code roster's PIN scrub, the settings save-and-round-trip, the read-only history queries (including that a malicious state name can never reach the database), the timeline replay maths, and the carbon run-advice ladder — plus a Node test for the dashboard's delta-aware device cache. Run them all with `tests/run.sh`. Nothing changes on screen; this is about keeping the dashboards honest as they grow.

**2.40.0** (15-Jul-2026) — Timeline replay. A new page that replays a whole day of the house on one scrubbable timeline. Drag across it and the readout shows exactly what was happening at that moment — which rooms had movement, which lights were on, which doors and windows were open, whether the heating was calling, and where the battery and solar were. It reads straight from the history the SQL Logger already keeps, with lanes for presence, lights, doors and heating over a battery-and-solar trace, and you can step back day by day. There's a new "Timeline" tile on the hub.

**2.39.0** (15-Jul-2026) — Accessibility pass. Every page now shares a small accessibility layer that makes the dashboards work properly with a keyboard and a screen reader. There's a "Skip to content" link for keyboard users, the main content and header are marked up as proper landmarks, every icon-only button (the snapshot, top, and toolbar buttons) now has a spoken name, the decorative emoji on tiles are hidden from screen readers so they aren't read out as gibberish, and important messages like alerts are announced when they change. It's all done as a single shared script that enhances each page as it loads, so nothing looks different on screen — it just behaves the way assistive technology expects.

**2.38.0** (15-Jul-2026) — Hardening sweep (part of the same review). A pass to make the pages defensive about the text they render and to tighten a few small security edges. Every page that shows a device name, a camera name, a recorded-state name or a log line now escapes it before putting it on screen, so an unusual name can never break the layout or slip markup in. The control PIN and guest token are now compared in constant time, the camera credentials file is created private from the outset rather than a moment later, the door-code labels on the Activity page scrub any stray digits so a PIN reminder in a trigger name can never reach the browser, the "Open Dashboards" menu no longer puts the key in the browser address bar on the server, and the camera transcoder's log is capped so it can't grow without bound. None of this changes anything you'll see day to day — it's the quiet tidying that makes a plugin safe to hand to other people.

**2.37.0** (15-Jul-2026) — Robustness fixes (part of the same review). A batch of smaller reliability fixes. The `config.js` file every page loads first is now written atomically, so a page opening at the exact moment it is rewritten (most likely just after you save settings) can no longer catch a half-written file and come up blank. If the plugin ever exits uncleanly and leaves its camera transcoder running, the next start now spots the stray copy and replaces it rather than quietly running on the old settings. The live-update path no longer lets a device go stale if a single fetch blips — it re-checks it on the next cycle instead of waiting for the periodic full refresh. The Settings page now preserves any advanced keys you have set via its raw-JSON box when you save through the forms. The Carbon page's forecast chart no longer occasionally blanks out on a refresh. And a room's door button now stays disabled through its full cooldown so it can not be double-pressed mid-pulse.

**2.36.0** (15-Jul-2026) — Security tidy-up (part of a full plugin review). A closer look at how the camera pipeline talks to the browser turned up a couple of spots worth tightening. The stats feed the cameras page reads for its bandwidth indicator was passing through the raw stream data from go2rtc, which quietly included the camera login details in the source URLs — the same feed is now stripped of anything private before it leaves the server, so only the byte counters the page actually needs go across. The guest token and the one-tap key hand-off for browsers on your own network are now locked to same-origin requests, so a stray web page open in another tab on the network can not read them. And there is a new option in the plugin config to turn the automatic key hand-off off entirely if you run read-only guest screens and want that boundary strictly enforced — it stays on by default, so nothing changes unless you want it to.

While in there I also filled a couple of gaps: the plugin config now has proper fallback fields for the Indigo and camera credentials for anyone who does not keep them in an `IndigoSecrets.py` file (the settings screen used to mention these without actually offering them), and the Log Level setting is now honoured rather than ignored.

**2.35.0** (14-Jul-2026) — Security and robustness, first batch of a deep review. The most important change closes a genuine hole. The camera bandwidth file the plugin writes for the cameras page, `streams.json`, lives in the same unauthenticated `/public` folder as everything else the browser reads, and it was being written with the raw camera stream addresses in it — which for an RTSP camera includes the camera's admin username and password. Anyone who knew your reflector address could have read those. The plugin now strips the addresses out before writing the file and keeps only the byte counters the page actually needs, so the bandwidth indicator still works and the passwords never leave the house. If you have ever exposed this dashboard beyond your own network, treat those camera passwords as compromised and change them. Alongside that, three sturdiness fixes. The one-time key handout that pairs a new browser now refuses to be read by any other website open in your browser, not just any site on your network. The Energy page no longer goes half-blank on the odd poll where the battery manager reports no dawn projection. The background worker that keeps the room and scene data fresh now shrugs off a single bad tick and carries on, rather than quietly stopping until the next restart. And the Settings page will no longer let you save over your whole configuration if it failed to load in the first place, with the plugin keeping a one-deep backup of the previous config as a safety net either way.

**2.34.0** (14-Jul-2026) — Per-person presence chips on the hub. Each tracked person now gets a chip of their own — "Clive · Home" in green, or "Clive · Away" — instead of one combined who's-home chip. Somebody being out is now something you can see, rather than something you have to notice is missing from a list.

**2.33.0** (13-Jul-2026) — System Health audited and redesigned. The audit found four things wrong. Memory was reported in decimal gigabytes, so an 8 GB Mac mini claimed 8.6 GB — it is now binary GiB, matching the hardware, while disk stays decimal to match Finder. The storage meter's caption described a different sum from the one it performed, and now shows the database as a share of current free space and says so. The server worked out the boot time and then never showed it, so there is an Up-since row. And the per-second countdown gave way to the live dot the other pages use. New with it: a verdict hero that answers the question in one glance (all healthy, worth a look, or needs attention) with a chip for each thing that triggered it, a Dashboard services card reporting whether the plugin's own transcoder and MJPEG proxy are actually alive, Indigo and API versions on the Mac card, and a gauge of running versus total device-owning plugins.

**2.32.0** (13-Jul-2026) — Plugs and Sockets, and settings saves stop dropping what you set by hand. A mains socket pinned into a room's Lights — the only toggleable section there was — made the hub tile count it as a light. Rooms now take a first-class plugs list: those devices get their own Plugs and Sockets section on the room page and count as a plug badge on the hub tile, never a light. There is deliberately no bulk all-on/off for them. The same release fixes the settings whitelist trap at its worst: the room editor rebuilt each room's overrides from its own form fields alone, so any key set by hand was silently dropped on every save, and the Garage's pinned car-battery monitor had already gone that way. The editor now starts from the stored configuration and overwrites only the fields the form actually edits.

**2.31.0** (13-Jul-2026) — Live room tiles on the hub. The Rooms tiles are no longer plain links. Each renders live state from the 3-second poll that was already running, so there is no extra network cost: a colour-banded temperature pill from the room's radiator valves (blue below 18°, amber at 24° and above, with a flame when the room is calling for heat), a green ring and status when a presence sensor is triggered, a count of lights on, and an amber count of open windows. The renderer works off each tile's own link, so new rooms go live on their own with no markup to write.

**2.30.0** (13-Jul-2026) — The hub audited and redesigned. Four faults first: the who's-home chip coloured its text with a CSS variable that did not exist, so the green never appeared, the Scenes and Settings tiles were the only two without tinted icon chips, the power-cut banner said "export held" for the whole lockout window (the same misleading-window bug fixed on the Energy page in 2.15.1, now fixed here too, so it only says that while export really is held), and the per-second countdown went the way of the others. Then the redesign: a greeting hero carrying the time of day, date, conditions, high and low and the sun times absorbs the House Pulse card, and its chips now deep-link to their own pages, joined by a live grid-carbon chip. The energy glance hints whether tomorrow's rate is up or down.

**2.29.0** (13-Jul-2026) — The Cost page audited and redesigned. The totals were all correct, but each bill column carried a separate Standing row for charges already inside the Electric and Gas figures, so the column looked as though it did not add up. That is now a unit and standing subline under each fuel. Rebuilt in the redesigned Energy page's style, and showing the economics the page had never surfaced: provisional and settled tags with covered badges on the day columns, month-to-date tiles (net position, bill and export so far, days self-funded, account balance) with a clearly labelled run-rate projection, a 30-day bill-versus-export chart with a cumulative net line, rates cards, an electric-bill column in the period totals, and the calendar-months table with year tabs.

**2.28.0** (13-Jul-2026) — The redesigned Energy page takes over. `energy2.html` becomes `energy.html`, so every existing link — the hub banner, the glance card, the Energy tile, the Carbon page's Energy button — keeps working untouched. The original page and the temporary Energy 2 hub tile used for the side-by-side comparison are both gone.

**2.27.0** (13-Jul-2026) — A redesigned Energy page, alongside the old one. New `energy2.html` and an Energy 2 hub tile beside the original, so the two could be compared before either was thrown away. It carries every figure the old page had in a cleaner layout, and adds detail the solar plugin's API had been offering all along without anywhere to show it: a Sankey diagram of the day's energy flow from sources to sinks, a 24h/48h/7d power chart with the battery level overlaid, an environmental-benefits card (CO₂ avoided, tree-years, coal, EV miles), a system card with the power-cut history, a tomorrow-rate chip and the kWh stored on the battery node.

**2.26.0** (06-Jul-2026) — EcoFlow references removed. The three EcoFlow power stations were retired and their Indigo devices deleted, so the now-stale mentions go from the pages, the help text and the sample data. The battery-fleet section itself is generic — it renders any device reporting a battery level — and stays exactly where it was.

**2.25.0** (03-Jul-2026) — Design polish across every page, aimed at Safari and iOS. Frosted top and bottom bars in both light and dark, hover lift only where there is a real pointer so an iPad never gets stuck in a hover state, focus rings for keyboard users on a Mac, and respect for reduced-motion. The iOS fixes matter most: the page now measures itself against the address-bar-aware viewport, text no longer inflates in landscape, and the tap highlight is gone. The hub was hand-polished on top — dead styling from removed features pruned, and the tile wall grouped under full-width House, Rooms and Tools labels.

**2.24.0** (03-Jul-2026) — Hardening across the three newest pages. System Health now recognises all three ways a battery level shows up in this estate — the native level, the Zigbee custom state, and the plain low-battery alarm — which on its first live run caught a sensor at 1% and another that had been quiet for 87 days, both invisible to the native-only check. On the Activity page, the key used to collapse repeated alerts now ignores digits that change between them, so a Modbus outage reads as one row with a count rather than six, and times gain a day prefix when the window spans days. The Carbon page keeps a short negative cache on failure so a down API is not re-hit by every open tab, and a failed forecast degrades to the current reading rather than breaking the section.

**2.23.0** (01-Jul-2026) — Activity feed. A new page and hub tile turn Indigo's very chatty event log into three readable things. Alerts, where errors and warnings are collapsed by source and message with a repeat count, so fifty identical lines read as one. A house diary of locks and doors, safety events and plugin restarts, with the raw radio echo of a lock event dropped so a lock is one row. And an automation panel showing which schedules fire next, which triggers are watching for problems, what has been switched off, and who holds a door code. Any digits in a code-trigger name are stripped on the server, so a PIN written into a trigger label never reaches the browser.

**2.22.0** (01-Jul-2026) — Carbon-aware advisor. A new page and hub tile combine the UK grid's carbon intensity (the free Carbon Intensity API, regional, no key needed, cached server-side) with your live solar surplus and your import rate, and answer one question: is now a good time to run a load. It ranks spare solar first, because that is both free and clean, then a genuinely clean grid, then waiting for the cleanest window in the next 16 hours. The page shows the advice, a strip of the figures behind it, a 24-hour forecast chart with the cleanest window marked, and the current generation mix. Set your region under the plugin's Configure.

**2.21.0** (30-Jun-2026) — System Health page. A new page and a hidden endpoint that works everything out server-side in one round trip: the Mac's disk, memory and swap pressure, load and uptime, the size of the history database with a breakdown of the logs, and a census of device health — what is in error, what is low on battery, which battery sensors have gone quiet, and how many devices each plugin owns along with whether it is running. Quiet detection is deliberately battery-only, because a mains or virtual device that has not changed in months is not telling you anything. The first live run caught a motion sensor at 5% that had been silent for 19 days.

**2.20.0** (30-Jun-2026) — Cost page. A dedicated whole-house money view — today, yesterday and the day before with electric, gas and standing charges broken out and a covered badge, a solar-benefit hero, and week, month and year totals — rendered from the solar plugin's bill-exact economics through the existing proxy, so it works away from home like the rest.

**2.19.0** (30-Jun-2026) — Reading favourites. A hub favourite can now pin a device *reading* — a voltage, a temperature, a battery level, a wattage — as a read-only tile, not only an on/off switch. Settings → Favourites gains a reading dropdown filled from the chosen device's live states.

**2.18.0** (30-Jun-2026) — Money and a house pulse on the hub. The energy glance now shows what actually matters — what the solar saved today, self-sufficiency, the live import rate, and what the battery is doing this minute. A new house-pulse strip shows who is home, which zones are calling for heat, and the low-battery and device-error counts. A banner appears at the top only when there is a power cut running or export is being held for a storm. Every part is guarded, so the hub works unchanged if any of those sources is absent.

**2.17.0** (29-Jun-2026) — The Wi-Fi page shows much more of what UniFi knows. New cards for the internet connection (speedtest up and down, latency, public address, gateway load), for clients (a Wi-Fi generation mix bar, a warning about legacy devices, and the least happy clients), and for the RF neighbourhood (how many neighbouring access points sit on each 2.4 GHz channel). Each access point tile gains a firmware line and condition badges — update pending, uplink running below its rated speed, high memory, channel congestion — and the detail page gains a hardware and uplink card. All of it is guarded, so it no-ops against an older UniFiHealth.

**2.16.1** (26-Jun-2026) — Voltage on sensor tiles. A device that reports a voltage but no temperature now shows the voltage as its main reading — so a monitor on a 12 V car battery reads "12.60 V" rather than a dash. Temperature and humidity tiles are unchanged. Tile labels also lose a trailing IP address and hardware suffix, so the name reads as the thing rather than the wiring.

**2.16.0** (24-Jun-2026) — The Energy page works away from home. It used to fetch its data straight from the solar plugin's LAN-only port, so it only worked on the home Wi-Fi. A new hidden endpoint proxies that data API from the server side, with the paths allow-listed, so the page reaches it over the reflector and is login-gated like every other page. One dashboard now works on a phone, a tablet or a laptop, at home and away.

**2.15.1** (24-Jun-2026) — The Energy card's "Lockout" chip told the truth for the wrong length of time. It showed for the whole window after a power cut, even while the battery was happily exporting. It now keys off whether export is actually being held rather than off the clock, so an exporting battery correctly reads "On Grid".

**2.15.0** (23-Jun-2026) — Presence Watch. A new hub tile and page showing per-night timelines for each pair of presence sensors — two sensor tracks plus a derived "both" track that turns amber wherever the pair disagree, which is how you catch one unit dropping a person who is sitting still. With it come per-sensor statistics, dropout callouts, a movement strip, a bedroom sleep proxy, and a 7-night pattern strip you can scroll back through. A companion script builds the data from the SQL Logger history and the plugin ticks it every five minutes, so tonight fills in as it happens.

**2.14.0–2.14.7** (21–22-Jun-2026) — The whole-house cost card, and a week of settling it down. 2.14.0 added the card itself to the energy dashboard: today provisional and yesterday settled, electric and gas with unit and standing charges, a covered-or-short verdict, month-to-date net position, days self-funded, account balance and a 30-day bill-versus-export chart, all from the solar plugin's economics. The rest were the polish that followed — 2.14.1 a review pass over the card, 2.14.2 a chart that refused to redraw ("canvas is already in use"), 2.14.3 a third day column so you see today, yesterday and the day before, 2.14.4 and 2.14.5 stopping the chart re-animating itself every five seconds and then killing the needless redraw at its source, 2.14.6 a day tag that flips from provisional to settled on its own, and 2.14.7 a new Solar card alongside it.

**2.13.1** (19-Jun-2026) — Fix: custom-link tiles never appeared. The shared authentication shim rebuilds the browser's configuration from a fixed list of allowed fields, and custom links were not on it, so they were dropped before the hub could render them — the same trap that had caught favourites in 2.10.0. Hard-refresh the browser once to pick up the corrected script.

**2.13.0** (19-Jun-2026) — Custom links. Settings gains a Custom links section for pinning full-size hub tiles that open any URL in a new tab — a separate tool's page, a Grafana board, a router admin page, and so on. Each is a title, a URL, and an optional description and emoji icon, and they sit on the hub just before the Overview/Active/Scenes/Settings cluster. The URL goes into the unauthenticated `config.js`, so it must not carry a token or password — the target page handles its own login — and the link scheme is checked both on save and on render so a stored value can't smuggle in markup. A root-relative URL works whether you load the dashboard over the LAN or the reflector.

**2.12.0** (16-Jun-2026) — The Active page becomes a full on/off list. It used to show only what was currently on, which was no help when the thing you wanted to switch back on was off and hidden from its room page. It now always lists every switchable device, on or off, sorted strictly by name so a device keeps its place when you toggle it instead of jumping between groups. The category pills stay.

**2.11.0** (16-Jun-2026) — Hub declutter, and kiosk mode removed. With Favourites at the top the hub had grown two cards that no longer earned their place, so the live heating glance and the battery/solar/grid/devices-on strip are gone (the compact Heating tile stays), and Overview, Active, Scenes, Graphs and Settings moved to a utility cluster at the bottom. Kiosk mode is removed outright — the page, its Settings card, its published configuration block and the Fully Kiosk screen driver all stripped out. No tablet was ever deployed, so the driver had only ever sat dormant.

**2.10.0** (16-Jun-2026) — Favourites. One-tap device and scene tiles pinned to the top of the hub, edited in Settings and stored on the server. It answers the "too many taps" complaint directly: the controls you use most are now the first thing you see. Tapping a device toggles it, respecting the per-tile PIN, and tapping a scene runs its action group.

**2.9.0** (13-Jun-2026) — The Page Builder, retired. The no-code page builder was a nice idea, but these dashboards are built around one particular house and the builder always sat a little awkwardly beside that — so it has been taken out, along with its 🧱 hub card. Nothing you use day to day changes: every room page, the cameras, the energy and heating views and the rest carry on exactly as before, and the smart room view that picks the right control for each device stays put. The page-authoring extras that grew up around the builder — the Settings "Builder's Pack" and the authoring guide — have gone with it, so the plugin is now purely the dashboards themselves.

**2.8.0** (13-Jun-2026) — A friendlier builder, and the smart features made shareable. The device palette gains a deliberate "add" button rather than a whole row you could click by accident, shows how many tiles are on the page, suggests a tile type from what the device can actually do, and flashes and scrolls to each new tile so you see it land. The more important half is underneath: the smart room view now works out its power, energy and battery annotations from each device's own live states, which every Indigo install provides, instead of from a catalogue of this estate. That makes it work for anyone, with none of these plugins and no catalogue at all.

**2.7.0** (13-Jun-2026) — The live room view picks its controls from what a device can do. The room page chose between a dimmer and a plain switch by pattern-matching the device class, which works until it does not. It now reads a device capability catalogue instead, which is declarative and copes with device types nobody has thought of yet, and it shows live watts on metering sockets — "On · 740 W" rather than "On · relay". It falls back to the old test until the catalogue loads, so nothing looks different while it does.

**2.6.2** (11-Jun-2026) — The builder uses the width it is given. The whole page was capped at 1100px, so it showed two panes however much monitor sat either side. The cap is gone, and on screens 1280px and wider the live preview becomes a sticky third column beside the editor, so the page updates in view while you edit rather than after a scroll. Narrow screens keep the old layout.

**2.6.1** (11-Jun-2026) — Graceful everywhere the SQL Logger is not running. Not everyone runs it, and the pages assumed otherwise. The server had always returned a friendly error, but nothing showed it: the Graphs page blamed the device when the real answer was that the database did not exist, and chart tiles dimmed silently and went on polling for ever. The page now says plainly that the SQL Logger is not running, how to turn it on, and that everything else works without it, and chart tiles carry a one-line note and stop retrying.

**2.6.0** (11-Jun-2026) — Alerts. The hub gains a 🔔 Alerts card: pick devices and variables, choose conditions, and matching changes raise system notifications on whichever device has the dashboard open — a wall tablet, a kiosk, a pinned browser tab. Rules live in the browser's own storage (nothing is sent to or kept on the server), first-poll seeding means opening the page never fires a storm of alerts for the current state, and a per-rule cooldown keeps chattering sensors polite. Honest small print: there's no cloud push service behind it, so notifications stop when every dashboard tab is closed. Also new: a `community-pages/` folder in the repo for sharing page definitions — pull requests welcome.

**2.5.0** (11-Jun-2026) — The Page Builder. Make your own dashboard pages by clicking: a 🧱 card on the hub opens the builder, where you pick devices from a searchable list, choose tile types (switch, slider, sensor, chart, scene button, camera, heading), preview against live data, and save — the page appears on the hub immediately, no code and no restart. Behind the scenes each page is a small JSON description rendered by `custom.html`, which means Claude (or a text editor) can write the very same pages the builder makes. Pages are stored by the plugin and survive upgrades; saving needs the same access key the dashboards already use, and the save endpoint validates everything it is given.

**2.4.2** (11-Jun-2026) — Offline charts and the Builder's Pack. The charting library is now bundled inside the plugin rather than fetched from the internet, so the Graphs page keeps working when your broadband doesn't. The "Builder's Pack" — a briefing you can paste into any Claude chat to have it write a dashboard page for you — now ships with the plugin and is one click to copy from the Settings page.

**2.4.1** (11-Jun-2026) — Kiosk camera fix and cycle costs on appliance tiles. The kiosk previously loaded every rotation page at once, and the hub's camera mosaic plus the camera grid together exhausted the browser's six-connection limit to the stream proxy — so the cameras starved. The kiosk now loads pages on demand: the old page stays visible while the next one loads, the cross-fade fires when it's ready, and everything else is parked, meaning only one page ever holds camera connections. Appliance tiles on the room pages also now show the last cycle's cost when ApplianceMonitor v1.3.0+ provides it.

**2.4.0** (11-Jun-2026) — Graphs: the house gets a memory. The new Graphs page charts the history of any recorded state of any device — pick a device, pick a state, pick a range (6 hours to 30 days), and you get an average line with a min/max band, plus deep links like `history.html?device=123`. The clever bit is where the data comes from: Indigo's stock SQL Logger plugin has been quietly recording every device state change all along, so there are months of history available from the very first day, with no new recording machinery and no extra storage. The plugin queries that database strictly read-only, with state names validated against the live table schema and downsampling done in-query — a 30-day series over a 5 GB database answers in under 50 milliseconds. Guest devices get the same charts through the read-only proxy, and demo mode draws plausible synthetic curves so the hosted showcase works too. Requires the SQL Logger plugin (bundled with Indigo, though not everyone runs it) — without it the Graphs page and chart tiles explain what is missing, and everything else works as normal.

**2.3.0** (11-Jun-2026) — Demo mode and a hosted showcase. Open `demo.html` and every page runs from canned fixtures with a gentle state simulator — solar output wobbles, the battery drifts, motion sensors flicker, and toggling a light updates the local data so the controls feel real. No Indigo server or credentials are involved anywhere. The fixtures are generated from a live system by `tools/make_demo_fixtures.py` with thorough sanitising (private IPs become documentation addresses, MAC addresses are blanked, and address/client/serial fields are dropped entirely), and `tools/build_demo_site.sh` builds the GitHub Pages showcase into `docs/`, where a special `config.js` forces demo mode for every visitor.

**2.2.0** (11-Jun-2026) — Kiosk mode *(removed in 2.11.0 — no tablet was ever deployed, so the driver sat dormant)*. A new full-screen `kiosk.html` rotates through your chosen pages with a cross-fade, position dots, a clock overlay, and night dimming driven by the `Lux_Value` Indigo variable. Touching the screen pauses rotation so the page underneath stays usable, resuming after a minute idle. Display settings live on the Settings page's new Kiosk card, with `?pages=` and `?dwell=` URL overrides for ad-hoc use. For an Android wall tablet running **Fully Kiosk Browser PLUS**, the plugin now drives the screen itself: motion on any chosen presence sensor turns the display on via Fully's REST API, and it turns off again after a configurable idle period — so the tablet shows a live dashboard when someone walks in and goes dark when the room empties. The Fully remote-admin password is read from `IndigoSecrets.DASHBOARDS_FULLY_PASSWORD` (with a config fallback), and the whole driver stays dormant until a host is configured. Pairs naturally with guest access: provision the tablet via `guest.html` and it can display everything while controlling nothing.

**2.1.0** (11-Jun-2026) — Guest tier and per-tile PIN. A guest device (wall tablet, a visitor's phone on your WiFi) pairs by opening `guest.html` and receives only a guest token, never the API key — so there is no control surface on it at all, not merely hidden buttons. Guest reads flow through the plugin's port-8177 proxy, which the reflector never fronts and which refuses non-private addresses, making guest access home-network and Tailscale only by construction. The guest token is auto-generated and the new **Show Guest Access Info** menu item logs the pairing URL. Separately, a **control PIN** can now protect chosen devices (front door lock, garage door): paired browsers are asked for the PIN once per session before commanding them, with the check done server-side so the PIN never reaches the browser. Both are managed from the new Security card on the Settings page. Worth saying plainly: the PIN is a speed bump for shared family devices, not a security boundary — a paired browser holds a full API key regardless.

**2.0.0** (11-Jun-2026) — The settings editor. A new Settings page on the hub gives you a forms-based editor for the whole configuration: cameras (with vendor, stream, room placement, hub-mosaic membership and swap-out choice), per-room extras (pulse doors, appliance monitors, TV groups, hide/include/sort overrides), and a checkbox tree of every action group for the Scenes hide-list — plus a raw-JSON view as the escape hatch. Your first Save writes `dashboards_config.json` into the plugin's Preferences folder, which then becomes the single source of truth, so configuration no longer means editing Python dicts in IndigoSecrets. Fresh installs keep working from IndigoSecrets/PluginConfig until they save from the editor, and the migration carries every existing setting across untouched. The Sigenergy inverter is now auto-discovered too, removing the last hardcoded device ID from the pages — the hub energy strip works on any install with SigenEnergyManager, whatever the device ID.

**1.22.0** (11-Jun-2026) — Delta live updates. The plugin now subscribes to every Indigo device change and keeps a ledger, and the pages ask a new lightweight endpoint "what changed since my last poll" instead of refetching the entire device list. Each poll is one tiny request plus a refetch of only the devices that actually moved, so polling tightens from five seconds to three across every page — a light switched elsewhere shows up on the dashboard in about three seconds. A full list refresh still happens at page load and every five minutes as a safety net, and everything falls back to the old full-fetch behaviour automatically if the endpoint is unavailable. Under the bonnet, the nine per-page copies of the JavaScript API client have been replaced by one shared `dashboard.js`, which is what made the v1.18.0 wrong-file-paste class of bug possible — that whole category is now structurally gone.

**1.21.0** (11-Jun-2026) — New Scenes page. Every Indigo action group appears as a tappable button on `scenes.html`, grouped by its Indigo folder, with running/done/failed feedback and a confirmation toast. The plugin generates `scenes.json` (refreshed every 30 seconds, so new action groups appear without a restart), and anything you'd rather not show — internal resets, test groups, whole folders — goes on a hide-list via `DASHBOARDS_HIDDEN_SCENES` in IndigoSecrets or the new Hidden Scenes field in the plugin config. Entries match a group name, a group ID, or `folder:Folder Name`. There is a new Scenes card on the hub.

**1.20.1** (11-Jun-2026) — Pairing made painless, building on the v1.20.0 security release. Browsers at home or on Tailscale now pair automatically — the plugin's proxy on port 8177 gains a `/bootstrap` route that hands the key only to private source addresses (the reflector never fronts that port), and `dashboards-auth.js` fetches it silently on first visit. For browsers arriving over the reflector there is a new **Generate One-Time Setup Link (+QR)** menu item — the link pairs the browser and is burned on first use, with unredeemed links swept after ten minutes and on every restart. API calls now follow the page's own origin rather than a configured LAN address, which means the dashboards genuinely work over the reflector once paired. The QR is generated server-side via the `qrcode` package (the plugin's first `requirements.txt`), and the proxy now starts even on camera-less installs.

**1.20.0** (11-Jun-2026) — Security release. The Indigo API key is no longer written into `config.js`, which sits in the unauthenticated `/public/` namespace and is reachable over the Indigo reflector — in other words, anything in that file is readable from the public internet. The file now carries only the server URL, and each browser is asked for the API key once via the Connect form on the hub page, keeping it in its own localStorage from then on. A new shared `dashboards-auth.js` shim merges the stored key in so all pages work exactly as before. The Connect form's server URL is now pre-filled from the published config rather than hardcoded, and the key field is a proper password input. The "Regenerate config.js" menu item has been renamed **Regenerate Config + Resync Pages** to reflect what it has always done — it also re-copies the HTML pages, so page edits no longer need a plugin restart. After upgrading, each browser will show the Connect form once — paste in your API key and you are away.

**1.19.7** (08-Jun-2026) — Energy page rebuilt as a full native replica of the SigenEnergyManager mini-dash, replacing the previous simplified four-cell view. All sections now rendered natively within the dashboard's standard navigation: animated energy-flow SVG, battery SOC ring and 24h sparkline, tariff card, hourly forecast bar chart, today's and yesterday's economics, period totals, calendar month breakdown, export-sync table, and Chart.js history charts. Data fetches from port 8179 every 5 seconds; the iframe is gone entirely.

**1.19.6** (07-Jun-2026) — Heating page Boost and Force Heating control panel. Six heating plugin actions (Start Timed Boost 1h/2h, Cancel Timed Boost, Force Heating On 24h, Cancel Forced Heating, Show Summer Status) exposed as buttons on the heating page, routed via the Command Centre API.

**1.19.5** (31-May-2026) — Wi-Fi hub tile shows worst-band utilisation (colour-coded) rather than audit-flag count.

**1.19.4** (31-May-2026) — Wi-Fi AP detail pages; per-AP client list (requires UniFiHealth ≥ v0.2.0).

**1.19.3** (27-May-2026) — Hub Energy and Weather cards sit side-by-side on narrow screens.

**1.19.2** (27-May-2026) — All cameras default to substream 2 (RTSP sub2, roughly ¼ the ffmpeg CPU and LAN bandwidth of mainstream). New stale-stream watchdog (amber dot) catches feeds that are connected but not delivering frames.

**1.19.1** (27-May-2026) — Security fix (rotated bearer token that had been committed to the repo); new `tools/preflight.py` that lints every `<script>` block, validates JSON, and syntax-checks the plugin before a release.

**1.19.0** (26-May-2026) — All 14 rooms now driven by the shared `room.html` template, dropping ~890 KB of duplicated per-room HTML. New section types: Appliances, TV group, per-section sort order. Hub Weather card extended with feels-like, pressure trend, rain total, UV index.

**1.18.0** (26-May-2026) — Command-centre hub rebuilt: 4-up camera mosaic + clickable Energy, Weather, Heating and Alerts summary cards above the room grid. Energy page shows energy device states from Indigo, with an optional iframe mode for embedding an external energy dashboard.

**1.16.0** (23-May-2026) — All hardcoded LAN-specific config removed; data-driven camera list and credentials via `IndigoSecrets.py` / PluginConfig.

## Page reference

### Hub (`index.html`)

The main landing page. Shows a summary of the whole house at a glance.

| Tile | What it shows |
|---|---|
| Hero | Greeting, date, sun/conditions, and the house-pulse chips — who's home, zones heating, low batteries, grid carbon — each a deep link to its page |
| Favourites | One-tap device/scene tiles pinned at the top, including read-only value tiles for a chosen device state (a voltage, a temperature) |
| Camera mosaic | Up to 4 live MJPEG streams for the cameras chosen in Settings |
| Energy card | Battery %, solar, grid, home consumption — plus today's totals |
| Weather card | Outdoor temperature, today's high/low, humidity, wind, rain today, pressure, UV index, sunset time, indoor readings |
| Doors & Windows card | Count of open contacts; lists any that are open by name |
| Home Insights card | Anomalies vs the house's own norms — battery falling fast, sensor gone quiet, room off its usual temperature, something on longer than normal. Says "nothing unusual" (with the check count) when all is well |
| Page grid | Tiles for every page, grouped House / Rooms / Tools; room tiles show a count of lights currently on |

---

### Per-room (`room.html?room=Room+Name`)

One page per room, driven by a shared template. Each section only appears if the room has devices of that type.

| Section | What it shows | Controls |
|---|---|---|
| Lights | Every light in the room — name, on/off state, device type | Toggle on/off; brightness slider for dimmers; scene preset buttons (Warm white, Movie, etc.) for colour-capable devices |
| TV | A grouped set of relay devices (TV + speakers/plugs) | Toggle each device; All On / All Off for the group |
| Motion | All motion and presence sensors in the room | Read-only — shows Clear / Detected and time since last change |
| Windows & Doors | Contact sensors — shows only open contacts (always-on appliance contacts like freezers are always shown) | Read-only |
| Appliances | Paired power meter + cycle monitor tiles | Read-only — shows live watts, cycle state (Idle / Running), last-cycle stats |
| Cameras | Any cameras assigned to this room in `DASHBOARDS_CAMERAS` | Live MJPEG stream; tap to enlarge |
| Heating | Thermostat zone(s) for this room | Read-only — shows current temperature and setpoint |
| Garage / pulse door | A momentary pulse button for relay-driven doors and gates | Tap to pulse; shows Open / Closed from contact sensor |

---

### Heating (`heating.html`)

All thermostat zones in one view, with quick-action controls at the top (if a compatible heating plugin is configured).

| Section | What it shows | Controls |
|---|---|---|
| Timed Boost | — | Start a 1-hour or 2-hour boost (+2 °C on all zones); Cancel Boost |
| Force Heating | — | Force heating on for 24 hours (overrides any seasonal lockout); Cancel Force; Show Status in log |
| Zone tiles | Every zone: room name, current temperature, setpoint | Setpoint − / + buttons to nudge the target temperature |

Zone temperatures are colour-coded: white when at or near setpoint, amber when notably above it (room is warm, valve closed).

---

### Cameras (`cameras.html`)

The full camera grid — all cameras in `DASHBOARDS_CAMERAS`.

| Element | What it shows |
|---|---|
| Main view | Large live MJPEG stream for the selected camera |
| Thumbnail strip | One thumbnail per camera; click to switch the main view |
| Status dot | Four states — grey (initial), green (live frames arriving), amber (connected but frames stalled for > 10 s), red (unreachable) |
| Bandwidth | Per-stream kB/s and total MB/s across all active streams |
| Timestamp | Camera-side timestamp overlaid on each stream |

---

### Active (`active.html`)

Lights and motion sensors that are currently active across the whole estate — useful for a quick "is everything off?" check before leaving the house.

| Section | What it shows |
|---|---|
| Lights on | Every light currently on — name, room, brightness, time since switched on |
| Motion detected | Every motion or presence sensor currently active — name, room, time since triggered |

---

### Weather (`ecowitt.html`)

Detailed weather data from any source that exposes device states in Indigo (OpenWeatherMap, Ecowitt weather station, other hardware weather stations, etc.).

| Element | What it shows |
|---|---|
| Current conditions | Temperature, feels-like, humidity, wind speed and direction, gust |
| Today | High and low forecast, rain total, UV index, sunrise and sunset |
| Pressure | Current pressure with trend arrow (rising, falling, steady) |
| Indoor | Indoor temperature and humidity from a separate sensor |

---

### Energy (`energy.html`)

Needs the SigenEnergyManager plugin. Without it (v3.13.0) the page shows one card saying so, the menu drops its tile and the hub keeps its Energy card hidden — nothing else on the dashboards depends on the plugin.

Full native replica of the SigenEnergyManager mini-dash, served within the dashboard's standard navigation. Data comes from the SigenEnergyManager's `/api/status`, `/api/history`, `/api/daily`, `/api/calendar`, `/api/years` and `/api/export-sync` endpoints on port 8179, reached through the plugin's own `sigenApi` proxy so the page works away from home over Tailscale as well as on the LAN.

Sections, in order — **Today**: live power-flow diagram (solar, home, grid and battery around the inverter, the moving dash on each leg running faster and thicker the more power it carries, and not moving at all for anyone who has asked for reduced motion), a four-tile strip of self-sufficiency, solar today, benefit and battery, a Sankey of where every kWh has gone since midnight, power metrics, and today's summary. **Battery**: state and health with the SOC ring and 24h sparkline, plus the battery fleet. **Money**: saved today, with the full breakdown a click away on the Cost page. **Solar**: generation and forecast. **Manager**: the optimiser's current decision, the tariff and system state. **Environment**, **History** (half-hourly supply/sink balance, daily totals, week on week, export sync) and **Records**. Updates every 5 seconds; charts refresh every 5 minutes.

---

### Wi-Fi (`wifi.html` and `wifi-ap.html`)

Requires the **UniFiHealth plugin ≥ v0.2.0**.

| Page | What it shows |
|---|---|
| `wifi.html` | Controller summary, WAN speed test, client Wi-Fi-generation mix, least-happy clients, 2.4 GHz RF neighbourhood, and one tile per access point — client count, band utilisation (colour-coded), any audit flags |
| `wifi-ap.html?ap=AP+Name` | Detail for one AP — per-radio stats, full connected client list with device names and signal strength |

---

### Cost (`cost.html`)

Needs the SigenEnergyManager plugin. Without it (v3.13.0) the page shows one card saying so, the menu drops its tile and the hub keeps its Energy card hidden — nothing else on the dashboards depends on the plugin.

The money view of the energy system, from a solar/battery plugin's bill-exact economics: saved-by-solar today, the whole-house daily bill (electric + gas including standing charges), month position with a run-rate projection, account balance, a 30-day bill-vs-export chart, a week-on-week money compare, period totals and a calendar-month breakdown.

---

### Carbon (`carbon.html`)

Live UK grid carbon intensity for your region (the free [Carbon Intensity API](https://carbonintensity.org.uk), no key needed), the current generation mix, a 24-hour forecast chart, and a plain-English "is now a good time to run a load" verdict that ranks spare solar first, then a clean grid, then the cleanest window ahead.

---

### Timeline (`timeline.html`)

Replays one day of the house on a single scrubbable timeline — lanes for presence, lights, doors & windows and heating, over a battery-SOC and solar trace. Drag or tap anywhere to scrub; the readout shows who and what was active at that moment, with prev/next day navigation. Assembled server-side from the SQL Logger history.

---

### Presence (`presence.html`)

Per-night presence-sensor timelines for each monitored room, with a derived "both sensors agree" track, first-seen / last-clear / occupied stats, and a seven-night history strip — useful for spotting a sensor that drops a still person.

---

### Graphs (`history.html`)

Time-series charts of any recorded state of any device, straight from the SQL Logger database — pick a device, a state and a range (6 hours to 30 days) and get an average line with a min/max band. Deep links like `history.html?device=123` work too.

---

### Activity (`activity.html`)

A curated house diary from the Indigo event log — locks and doors, safety events, plugin restarts — with recent errors and warnings collapsed into one row each, plus an automation panel: which schedules fire next, which triggers watch for problems, what's switched off, and who holds a door code (PIN digits are scrubbed server-side and never reach the browser).

---

### System health (`system-health.html`)

The Indigo server's own vitals — disk, RAM and swap pressure, load, uptime, history database size — plus a device-health census: devices in error, low batteries, quiet battery sensors, and per-plugin device counts. Computed server-side, so it works away from home over Tailscale too.

---

### Scenes (`scenes.html`)

Every Indigo action group as a tappable button, grouped by folder, with running/done/failed feedback. A hide-list (managed from Settings) keeps internal or test groups out of sight.

---

### Guest (`guest.html`)

The pairing page for a read-only device. Open it **on** the device — a wall
tablet, or a visitor's phone on your Wi-Fi — and it takes a guest token from the
plugin's LAN-only proxy on port 8177, stores it, and sends the browser on to the
hub. The device never holds the API key, so there is no control surface on it at
all rather than hidden buttons. That proxy is not exposed outside the LAN and
refuses any non-private source address, which makes guest access home-network and
Tailscale only by construction. **Plugins → Dashboards → Show Guest Access Info**
logs the pairing URL.

---

### Mains (`mains.html`)

Every 240 V meter in the house, and how far each one disagrees with the others. It leads with a trust panel rather than a reading, because the meters here genuinely do not agree: measured over seven days against the inverter, the two Athom monitors read low and all fifteen Shellys read high, a spread of 3.66 V. The page shows each meter's raw reading and its measured offset, and never a corrected number — correcting them would only make them agree with a reference that is itself uncalibrated.

A meter that is not answering is greyed out as a whole row, values and all. An Indigo device state is a LAST KNOWN value, so a dead meter's voltage and power are last week's readings, not measurements, and showing one beside a dash would make the survivor look authoritative.

Tap any meter tile to open its own page.

---

### Meter (`meter.html?id=N`)

One meter in detail: its live reading, its position on a scale of every live meter in the house with its rank, its seven-day offset against the reference, and its own history. The position map is only drawn for a meter that is answering — a frozen reading cannot be placed on a scale of live ones.

---

### Laundry (`laundry.html`)

Needs the SigenEnergyManager plugin. Without it (v3.13.0) the page shows one card saying so, the menu drops its tile and the hub keeps its Energy card hidden — nothing else on the dashboards depends on the plugin.

When to run each metered appliance so it costs the least grid import, worked out from the solar forecast, the house's own measured hourly load profile, the battery state and the live half-hourly prices. It answers in a sentence and shows its working: where the run's energy would come from, and every half hour between now and the deadline with what each would cost.

Chips along the top of each card set that appliance's deadline and replan on the spot. Where every slot costs the same — a large battery on a summer night — it says so once instead of listing forty-five identical rows.

**It advises and never switches anything on.** A machine has to be loaded by a person anyway, so a person is standing in front of it at exactly the moment the advice is useful.

It finds every Appliance Monitor device by itself and measures each machine's cycle from that device's own logged history, so adding a dishwasher is a metering plug and a device rather than an edit. A machine that has finished fewer than five cycles gets no profile at all and the page says so: a median of two is not a measurement, and a nameplate rating is not what a cycle actually draws.

---

### Alerts (`alerts.html`)

Browser notification rules. Pick devices or variables, choose what counts as a change, and your own browser raises a system notification — no third-party push service, no account, nothing leaving the house. Rules live in the browser that made them, so a phone and a wall tablet can watch different things.

---

### Menu (`menu.html`)

Every page in one grouped list, with each configured room as its own entry. This is what the Hub's "More" button opens, and it is the only page that enumerates the rooms, so a room added in Settings appears here without touching any HTML.

---

### Setup (`setup.html`) and Guest (`guest.html`)

First-run pairing. `setup.html` hands a browser the API key once, from a single-use token that is burned on redemption, so the key never travels in a link that can be re-used. `guest.html` does the same for a device that should only ever look — a wall tablet or a visitor's phone gets a guest token with no control rights.

---

### Demo (`demo.html`) and WebRTC test (`webrtc-test.html`)

Neither is part of the daily set. `demo.html` runs the whole thing on fixtures with no Indigo behind it, which is what the public Examples site is built from. `webrtc-test.html` is a diagnostic for the camera transport.

---

### Settings (`settings.html`)

The forms-based configuration editor — favourites, custom links, cameras, per-room extras, the scenes hide-list, security (control PIN and guest access), and a raw-JSON escape hatch. Saves to the plugin-owned `dashboards_config.json`, which then becomes the single source of truth.

---

## Building and extending with Claude Code

The whole dashboard was built and is maintained through conversation with Claude Code — no hand-editing of HTML or plugin internals required. To give a flavour of the kind of thing you can ask it to do:

- *"Add a heating page that shows all my thermostat zones with their current temperature and setpoint"*
- *"The garden camera is not showing in the grid — can you check the go2rtc config and see what is wrong"*
- *"Add a door control tile to the garage room page that pulses relay device 12345 for 2 seconds when tapped, and shows open or closed using contact sensor 67890"*
- *"Create a room page for the conservatory showing its lights, the patio contact sensor, and the camera on 192.168.1.55"*
- *"Install ffmpeg and go2rtc on my Mac so the camera grid works"*
- *"The weather card on the hub is not updating — have a look at the event log and tell me what is going on"*
- *"Add an appliance tile to the kitchen page pairing the washing machine power meter with the ApplianceMonitor device"*
- *"Move the energy card so it sits next to the weather card on the hub page"*

Claude Code can read the plugin source, check the Indigo event log through whichever Indigo MCP server you run, edit HTML pages, restart the plugin, and verify the result — all in one conversation. Most changes that would otherwise mean half an hour of hunting through source files take a couple of minutes.

### The plugin's own Claude tools

From v3.12.0 the bundle ships `Contents/Resources/mcp-manifest.json`, a plugin-provided tool manifest. An Indigo MCP server that reads those — [mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server) from v2026.8.1, [Claude Bridge](https://github.com/Highsteads/ClaudeBridge) from v2.26.0 — finds it on its own and lists these tools to Claude, with no configuration on either side:

| Tool | What it does |
|---|---|
| `dashboards_get_status` | Version, hub URL, where the configuration comes from, room folders and how many exist, the camera pipeline, the history backend, which companion scripts are present |
| `dashboards_run_setup_check` | The Test Dashboards Setup sweep, returned as data: every check with its verdict and detail |
| `dashboards_list_room_folders` | The folders that become rooms, whether they are the built-in defaults, every folder Indigo has, and any configured name that does not exist |
| `dashboards_set_room_folders` | Replace the room folders. Unknown names are refused and the real ones listed back. Live at once |
| `dashboards_list_cameras` | The saved cameras, the hub mosaic, whether credentials are set and the streams are running, and whether a restart is pending |
| `dashboards_set_camera` | Add a camera, or change the one with that host. Says whether a restart is needed |
| `dashboards_remove_camera` | Remove a camera, and take it out of the hub mosaic |
| `dashboards_read_log` | The last lines of the plugin's own log, optionally filtered to a phrase |

The writes are refused if the MCP server's "allow plugin-provided tools to make changes" setting is off, and every write goes through the same validation as the Settings page. Reads never return a credential. Without an MCP server the manifest is inert and nothing about the plugin changes.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
