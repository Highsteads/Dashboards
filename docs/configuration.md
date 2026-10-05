---
title: Configuration
nav_order: 7
---

# Configuration

There are three places a setting can come from, and one of them wins.

1. **The Settings page** (`settings.html`, the Settings card on the hub). The first Save writes
   `dashboards_config.json` into the plugin's Preferences folder, and from then on that file is the
   single source of truth for favourites, custom links, cameras, room extras, hidden scenes,
   security and the other keys below. Camera changes need a plugin restart, because the streaming
   pipeline is built at startup. Everything else applies at once.
2. **The Configure dialog** (**Plugins → Dashboards → Configure**). Credentials, the history
   backend, the weather key, the carbon region, logging and the reflector switch live here. These
   are things a web page should not be able to change.
3. **`IndigoSecrets.py`**, optional. A single file of credentials that I share across all my
   plugins. If it exists, its values win over the matching Configure fields. Nobody else needs it,
   because every key has a Configure field — see [the end of this page](#credentials-in-indigosecretspy).

## The Configure dialog

Open it with **Plugins → Dashboards → Configure…**. The fields, in the order the dialog shows them:

| Field | What it does |
|---|---|
| Indigo API URL | The address of Indigo's web server, such as `http://192.168.1.10:8176`. Leave it blank for the Indigo Mac itself on the usual port 8176, and fill it in only if your web server uses another port. The "use this at home" link the pages offer over the reflector takes its start and port from here |
| Indigo API Key | The Indigo API key — the long code Indigo gives other programs so they can read and control your devices. The plugin uses it for its own checks, for guest devices and for setup links. It is never written into any public file |
| Camera User / Camera Password | One camera login, shared by every camera that has no login of its own, whatever its make. Only needed if you have cameras. Pressing **Save** here approves the camera addresses saved on the Settings page at that moment, and the login is only ever sent to approved addresses — so after adding or changing a camera, come back here, press Save and restart the plugin. See [Cameras](cameras.md#the-camera-login-goes-only-to-approved-addresses) |
| Camera Logins | Only for a camera whose login is not the shared one, written against its address as `{"192.168.1.50": {"user": "admin", "password": "its password"}}`, one entry per camera. Each goes only to the address it is written against, so it needs no approval. Shown and stored in plain text. Restart the plugin after changing it. See [Cameras](cameras.md#a-camera-with-a-login-of-its-own) |
| Pushover User Key | Your Pushover user key, for alert rules sent to your phone (3.47.0). The message goes through the Pushover plugin, which must be installed, enabled and running |
| Carbon Region | Your part of Great Britain, for the grid-carbon half of the Energy page's When to run it card. **Off** hides it and stops the lookups. North East England unless you change it. Needs SigenEnergyManager, like the Energy page |
| Auto-seed the API key to LAN browsers | Off for a new install (3.46.0). Ticked, any browser on your home network or Tailscale pairs itself on its first visit, which hands the full API key to any device that asks, a visitor's phone included, and makes guest links pointless. Unticked, you pair each device once with a setup link — see [Pairing a browser](getting-started.md#pairing-a-browser). Installs from before 3.46.0 keep the setting they had |
| Extra trusted networks | Blank unless you fill it in (3.60.0). The plugin's port 8177, which does auto-seeding, guest pairing and live camera video, answers only the Indigo Mac, Tailscale and the network the Mac is plugged into. If your own phones and tablets are on another network, add it here, written like `192.168.2.0/24`, with commas between several. A mistyped entry is refused when you press Save. See [Which networks are trusted](getting-started.md#which-networks-are-trusted) |
| OpenWeatherMap API key, Site latitude, Site longitude | Add sunset, today's high and low, UV and conditions to the hub's Weather card. Without them the card still works from your Ecowitt weather station alone |
| System Health: battery device quiet after (hours) | A battery device that has not changed for this many hours is listed as quiet on the System page. 48 unless you change it |
| System Health: low-battery threshold (%) | Devices at or below this level are listed as low on battery. 20 unless you change it |
| go2rtc binary path (optional) | Where go2rtc is, if it is not somewhere the plugin already looks. Leave it blank and the plugin tries the usual command path and then `~/bin/go2rtc` |
| SQL Logger backend | Where Indigo's SQL Logger writes its history: SQLite, the default, or PostgreSQL. Choose PostgreSQL only if you have pointed the SQL Logger at a PostgreSQL server, and then fill in the Host, Port, Database, User and Password fields that appear. Run **Test History Connection** after changing it |
| Refuse the reflector | Off unless you tick it. Ticked, the pages refuse to run over the Indigo reflector and show the home address instead, and the plugin's own replies refuse anything that came that way. Indigo's web server still hands out the page files themselves there — only switching the reflector off in Indigo stops that. See [Remote access](remote-access.md#the-indigo-reflector) |
| Log routine activity to the Indigo Event Log | Unticked, the plugin's routine housekeeping lines go only to its own log file. Tick it while you are setting the plugin up to see them in the Event Log as well. Warnings and errors always reach the Event Log |
| Log Level | The lowest level of message this plugin puts in the Event Log: Debug, Info, Warning or Error. Info unless you change it. Debug puts the routine lines into the Event Log too, so use it while chasing a problem and put it back afterwards |

Cameras, the hub's camera strip, room extras and hidden scenes are not in this dialog. They are on the
dashboards' own Settings page.

## The Settings page

Everything the pages read from configuration, editable in the browser. The banner at the top says
where it writes.

- **Favourites.** One-tap tiles for the hub, in the order given. A favourite is a control (toggle a
  device or run a scene), a reading (show a device state, not tappable), a door tile (shows the
  door's state and acts on it), a room shortcut or a group. Pickers take device ids with a live
  lookup showing which device they resolve to. A favourite pointing at something that no longer
  exists is named rather than silently dropped.
- **Custom links.** Extra tiles for the menu's Tools group — anything with a URL.
- **Cameras.** Host, name, make (one of the [known makes](cameras.md#camera-makes), or other),
  stream (`sub2`, the default, or `main`), an RTSP address when the camera needs its own, the
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
  {"host": "192.168.1.52", "name": "Garden",     "vendor": "dahua", "stream": "main", "room": "Garden"},
  {"host": "192.168.1.53", "name": "Porch",      "vendor": "other",
   "rtsp": "rtsp://192.168.1.53:554/h264Preview_01_sub"}
]
```

- `vendor` — the make: `dahua`, `hikvision`, `amcrest`, `lorex`, `annke`, `reolink`, `tapo`,
  `axis`, `foscam`, `uniview` or `other`. For all but `other` the plugin knows the usual stream
  address — see [Camera makes](cameras.md#camera-makes). `other` is any other camera and needs
  `rtsp`.
- `rtsp` — the camera's own stream address, pointing at the same address as `host` and with no
  user name or password in it. Needed for `other`. For any other make it replaces the usual
  address, for a model that differs. See
  [Any other make of camera](cameras.md#any-other-make-of-camera).
- `stream` — `sub2` (the default, the smaller picture) or `main`. Not used when `rtsp` is set,
  because the address names its stream.
- `room` — a name or a list of names. Which room pages show this camera. Omit it to keep the
  camera off room pages.

The same fields are on the Settings page's Cameras card, which is the easier way to enter them.

## Room extras

Optional, per room. A room with nothing here still shows its lights, motion sensors and contact
sensors automatically. The extras unlock the other tile types. Keyed by room name (the Indigo device
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
- **`sortOrder`** — a section name to a list of device ids that go first, in that order, the rest
  follow alphabetically. A listed device also stays in that section when the classifier would no
  longer put it there. A plug counts as a light only while its name has a light word in it, so
  renaming "Twigs Light Plug" to "Twigs Plug" would otherwise take it off the room page.

## Other config keys

These live in `dashboards_config.json`. The Settings page writes them. Anything the forms do not
model can be set in the raw-JSON box.

| Key | Shape | What it does |
|---|---|---|
| `roomFolders` | list of folder names | Which Indigo device folders become rooms. With nothing set the plugin uses its own defaults, which are one house's folder names and will produce no rooms on yours |
| `siteName` | string | The name in every page title, the hub heading and the home-screen icon. Default "Dashboards" |
| `vehicles` | `[{"id": <device>, "label": "Car 12V"}]` | Battery-voltage monitors to list under the Energy page's battery fleet, with a frozen-reading check |
| `arrayKwp` | number | Your solar array's rating, for the weather page's roof-versus-sky cross-check |
| `actionWatch` | object | Per-action-group confirmation rules for scene buttons: which device states confirm which action, so no page carries device numbers |
| `stillsIdleMinutes` | number, default 5 | How often, in minutes, a camera that no page is showing still gets a picture taken, 0 to 60. Those pictures keep camera health and the hub's "camera offline" warning working with no page open. 0 takes none, so the warning only covers cameras on screen. Cameras a page is showing always get a picture every two seconds. Added in 3.48.0 |
| `livePoolSize` | number, default 6 | How many cameras the Cameras page may show as live (WebRTC) video at once, 0 to 12. The rest refresh as stills. The page also holds it to what the connection's measured speed carries. Each live tile costs about 1 Mbit/s and some decoding work on the device, so lower it for an older tablet. Before 3.46.0 a saved value was ignored and six was always used |
| `guestVariables` | list of variable names or ids, default none | The Indigo variables a guest-paired device may read (3.46.0). Anything not listed is withheld from guests. A value that is not a list shares nothing |

The alert rules live in the same file (3.47.0) but belong to the Alerts page, which saves them
itself: `alertRules` (the rules), `alertsActive` (the "alerts active" tick), `alertEmail` (the
default address) and `alertRulesRev` (a counter that stops an out-of-date page saving over a newer
list). The Settings page neither shows them nor changes them, and its raw-JSON box cannot set them.
The recent alerts are kept in `alert_firings.json` beside it.

## Credentials in `IndigoSecrets.py`

You do not need this file. Every credential has a field under Configure, and most people should use
those. `IndigoSecrets.py` is a single file of passwords and keys that I share between all my plugins,
so each one is typed in once. If you would like to use it:

1. Download `IndigoSecrets_example.py` from the top level of the [GitHub repository](https://github.com/Highsteads/Dashboards).
2. Copy it into `/Library/Application Support/Perceptive Automation/` on the Indigo Mac.
3. Rename the copy `IndigoSecrets.py`.
4. Open it in a text editor and fill in the keys below that you need, leaving the rest empty.
5. Restart the plugin, or use **Plugins → Dashboards → Regenerate Config + Resync Pages**.

A value in the file wins over the matching field under Configure. Keep the file private — it holds
your passwords in plain text, as the Configure fields do in Indigo's own preferences file.

Cameras, the hub's camera strip, room extras and hidden scenes are kept in the file the Settings page
writes. The four `DASHBOARDS_*` keys marked "imported once" were read only on the first start of
version 3.27.0 or later with no Settings page file, when the plugin copied them across and said so
in the log. After that the Settings page owns them and the keys are not read again.

| Key | Used for |
|---|---|
| `INDIGO_URL` | REST API base URL |
| `INDIGO_API_KEY` | REST API Bearer token (`CLAUDEBRIDGE_BEARER_TOKEN` is accepted as an alias) |
| `DAHUA_USER` / `DAHUA_PASS` | The camera login every camera shares, whatever its make |
| `CAMERA_LOGINS` | A login for each camera that has its own, as `{"192.168.1.50": {"user": "admin", "password": "..."}}` |
| `DASHBOARDS_CAMERAS` | The camera list (imported once, see above) |
| `DASHBOARDS_MAIN_CAMERAS` | Host addresses for the hub's strip (imported once) |
| `DASHBOARDS_ROOM_EXTRAS` | The per-room extras dictionary (imported once) |
| `DASHBOARDS_HIDDEN_SCENES` | Action groups to keep off the Scenes page (imported once) |
| `OWM_API_KEY` / `LATITUDE` / `LONGITUDE` | OpenWeatherMap and your site's coordinates |
| `HISTORY_PG_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DATABASE` | PostgreSQL, when the SQL Logger writes to Postgres |
| `PUSHOVER_USER_TOKEN` | Your Pushover user key, for alert rules (3.47.0). The Configure field is the fallback |
| `DASHBOARDS_ALERT_EMAIL` | Where alert email goes when a rule names no address and the Alerts page has no default (3.47.0). Read at every start, unlike the other `DASHBOARDS_*` keys |

Never put a credential into anything under `/public/` — that namespace is served without
authentication, and over the reflector it is reachable from the internet.
