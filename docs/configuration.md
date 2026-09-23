---
title: Configuration
nav_order: 4
---

# Configuration

There are three places a setting can come from, and one of them wins.

1. **The Settings page** (`settings.html`, the Settings card on the hub). The first Save writes
   `dashboards_config.json` into the plugin's Preferences folder, and from then on that file is the
   single source of truth for favourites, custom links, cameras, room extras, hidden scenes,
   security and the other keys below. Camera changes need a plugin restart, because the streaming
   pipeline is built at startup; everything else applies at once.
2. **The Configure dialog** (**Plugins → Dashboards → Configure**). Credentials, the history
   backend, the weather key, the carbon region, logging and the reflector switch live here. These
   are things a web page should not be able to change.
3. **`IndigoSecrets.py`**, optional. A single file of credentials shared across all the author's
   plugins. If it exists, its values take precedence over the matching Configure fields — and on an
   install that has never saved from the Settings page, its camera and room dictionaries are read
   too. Nobody else needs it: every key has a Configure field.

## The Configure dialog

| Field | What it does |
|---|---|
| Indigo API URL | The REST base URL, e.g. `http://192.168.1.10:8176`. Blank means the local server on port 8176 |
| Indigo API Key | The Bearer token the plugin uses for its own diagnostics and the guest passthrough. Never written into any public file |
| Camera User / Password | One set of camera credentials, shared across every camera. Works for Dahua and Hikvision |
| Cameras (JSON) | The camera list, for installs that have never saved from Settings — see below |
| Swap-Out Host | A camera that can replace another in the hub's strip |
| Hidden Scenes (JSON) | Action-group names or ids to keep off the Scenes page |
| Carbon Region | Your UK grid region, for the Carbon page and the hub's carbon chip |
| Auto-seed the API key to LAN browsers | A new browser on the home network or tailnet pairs itself on first visit |
| OpenWeatherMap API key, latitude, longitude | The hub weather card's forecast and sun times |
| System Health thresholds | How many hours quiet makes a battery device "quiet", and what counts as a low battery |
| go2rtc binary path | Where to find go2rtc if it is not on the PATH |
| SQL Logger backend | SQLite (the default) or PostgreSQL, with the connection fields for Postgres |
| Refuse the reflector | Off by default. When on, the pages refuse to run over the Indigo reflector and show the LAN address instead — see [Remote access](remote-access.md) |
| Log routine activity to the Indigo Event Log | Whether the plugin's own housekeeping lines go to the event log or only to its own log file |
| Log Level | Debug puts the narration back |

## The Settings page

Everything the pages read from configuration, editable in the browser. The banner at the top says
where it writes.

- **Favourites.** One-tap tiles for the hub, in the order given. A favourite is a control (toggle a
  device or run a scene), a reading (show a device state, not tappable), a door tile (shows the
  door's state and acts on it), a room shortcut or a group. Pickers take device ids with a live
  lookup showing which device they resolve to; a favourite pointing at something that no longer
  exists is named rather than silently dropped.
- **Custom links.** Extra tiles for the menu's Tools group — anything with a URL.
- **Cameras.** Host, name, vendor (Dahua or Hikvision), stream (`sub2`, the default, or `main`), the
  rooms it belongs to, and whether it is in the hub's strip. A swap-out host picker sits at the
  bottom. Changes here need a plugin restart.
- **Rooms.** Which Indigo device folders become rooms, and a per-room override for anything the
  automatic classifier gets wrong. Each room shows what it currently resolves to ("1 doors · 0
  appliances"), so a room reading "0 doors" that has doors is a classifier needing an override.
- **Scenes.** Every action group with a tick to hide it from the Scenes page, and a per-folder
  tick that hides the whole folder.
- **Security.** The guest pairing URL and token, and the control PIN — asked once per session
  before any command on the listed devices. It is a speed bump for shared and family devices, not a
  security boundary, and the page says so.
- **Raw JSON.** The whole configuration as it will be saved, with *From form* to regenerate it and
  *Apply to form* to parse it back. The escape hatch for anything the forms do not model.

Save checks that the plugin is actually up first: this is the page most likely to be opened straight
after a restart, and a save landing on a restarting plugin used to stall the web server.

## Cameras

```json
[
  {"host": "192.168.1.50", "name": "Front Door", "vendor": "dahua"},
  {"host": "192.168.1.51", "name": "Drive",      "vendor": "hikvision"},
  {"host": "192.168.1.52", "name": "Garden",     "vendor": "dahua", "stream": "main", "room": "Garden"}
]
```

- `vendor` — `dahua` or `hikvision`; it selects the RTSP URL template.
- `stream` — `sub2` (the default, roughly a quarter of the mainstream's bitrate) or `main`.
- `room` — a name or a list of names; which room pages show this camera. Omit it to keep the
  camera off room pages.

The same fields are on the Settings page's Cameras card, which is the easier way to enter them.

## Room extras

Optional, per room. A room with nothing here still shows its lights, motion sensors and contact
sensors automatically; the extras unlock the other tile types. Keyed by room name (the Indigo device
folder). The Settings page's Rooms card edits all of this.

- **`doors`** — a pulse-door tile. Each entry has a `label`, one or more `relayIds` to pulse
  momentarily (garage openers, gate controllers), a `pulseMs` duration, and optionally a
  `statusContactId` contact sensor and `openWhenContactOnState` (true if the contact being On means
  the door is open). Devices listed here are hidden from the room's other sections so they do not
  appear twice.
- **`appliances`** — a read-only tile pairing a power meter (`monitorId`, live watts) with an
  ApplianceMonitor cycle device (`cycleId`, Idle / Running / Door open and last-cycle stats). Either
  can be omitted.
- **`tv`** — device ids treated as a group, each with a toggle and an All On / All Off for the set.
- **`plugs`** — device ids shown in their own Plugs & Sockets section with a toggle each. They are
  kept out of the "lights on" count and there is deliberately no bulk button: a freezer or a router
  could be on one.
- **`fire`** — device ids treated as a fire: an open-loop relay whose state is the last thing sent,
  not a reading. Shown separately, and the night sweep re-asserts them off.
- **`openLoop`** — device ids whose state cannot be read back (RF relays, IR blasters). A group
  favourite commands them but never lets their believed state decide the group's label.
- **`mainLight`** — the light or lights to leave out of the room's All On / All Off.
- **`hideDeviceIds`** — device ids to keep off that room page altogether.
- **`include`** — a section name to a list of device ids to force into that section whatever the
  classifier thinks: `lights`, `motion`, `radiators`, `windows`, `sensors` or `extras`.
- **`sortOrder`** — a section name to a list of device ids that go first, in that order; the rest
  follow alphabetically.

## Other config keys

These live in `dashboards_config.json`. The Settings page writes them; anything the forms do not
model can be set in the raw-JSON box.

| Key | Shape | What it does |
|---|---|---|
| `roomFolders` | list of folder names | Which Indigo device folders become rooms. With nothing set the plugin uses its own defaults, which are one house's folder names and will produce no rooms on yours |
| `siteName` | string | The name in every page title, the hub heading and the home-screen icon. Default "Dashboards" |
| `vehicles` | `[{"id": <device>, "label": "Car 12V"}]` | Battery-voltage monitors to list under the Energy page's battery fleet, with a frozen-reading check |
| `arrayKwp` | number | Your solar array's rating, for the weather page's roof-versus-sky cross-check |
| `actionWatch` | object | Per-action-group confirmation rules for scene buttons: which device states confirm which action, so no page carries device numbers |
| `livePoolSize` | number, default 6 | How many cameras show live (WebRTC) video at once at home; the rest refresh as stills. Each live tile costs about 1 Mbit/s and some decoding work on the device, so lower it for an older tablet |

## Credentials in `IndigoSecrets.py`

If you already use `IndigoSecrets.py` with the author's other plugins, these are the keys this one
looks for. The repo ships `IndigoSecrets_example.py` with empty placeholders.

Cameras, main cameras, room extras and hidden scenes live in `dashboards_config.json`, which the
Settings page writes. The four `DASHBOARDS_*` keys below are read **once**: on the first start with
no `dashboards_config.json` (3.27.0 and later), the plugin copies them, and the old Configure fields
for cameras, the swap-out camera and hidden scenes, into that file and says so in the log. From then
on the Settings page owns them and the keys are no longer read. A hand edit of
`dashboards_config.json` takes effect at the next plugin restart.

| Key | Used for |
|---|---|
| `INDIGO_URL` | REST API base URL |
| `INDIGO_API_KEY` | REST API Bearer token (`CLAUDEBRIDGE_BEARER_TOKEN` is accepted as an alias) |
| `DAHUA_USER` / `DAHUA_PASS` | Camera credentials |
| `DASHBOARDS_CAMERAS` | The camera list (imported once, see above) |
| `DASHBOARDS_MAIN_CAMERAS` | Host addresses for the hub's strip (imported once) |
| `DASHBOARDS_ROOM_EXTRAS` | The per-room extras dictionary (imported once) |
| `DASHBOARDS_HIDDEN_SCENES` | Action groups to keep off the Scenes page (imported once) |
| `OWM_API_KEY` / `LATITUDE` / `LONGITUDE` | OpenWeatherMap and your site's coordinates |
| `HISTORY_PG_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DATABASE` | PostgreSQL, when the SQL Logger writes to Postgres |

Never put a credential into anything under `/public/` — that namespace is served without
authentication, and over the reflector it is reachable from the internet.
