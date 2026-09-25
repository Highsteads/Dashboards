---
title: How it is built
nav_order: 10
---

# How it is built

## Page files

Every page is a plain HTML file — no build step, no framework, no bundler. They are stored in two
places:

| Location | Purpose |
|---|---|
| `Dashboards.indigoPlugin/Contents/Resources/static/pages/` | **Source of truth** — edit files here |
| `<Indigo install>/Web Assets/public/dashboards/` | **Served by the web server** — copied from source at plugin startup |

The plugin mirrors the source pages into the public folder during `startup()`, atomically. Edit a
page, restart the plugin, and the web server serves the new version. Editing the public folder
directly has no lasting effect — the next restart overwrites it from source. The Indigo install
folder is version-dependent (`Indigo 2025.2`), so find it with `indigo.server.getInstallFolderPath()`
rather than typing it.

The shared scripts, in the order a page loads them:

| File | What it holds |
|---|---|
| `config.js` | Written by the plugin at startup and whenever a feature flag changes: the API base URL, the site name, the camera list, the room list, the colour presets, and flags such as `heatingControls` and `sigenAvailable`. Never a credential |
| `dashboards-auth.js` | Merges the browser's stored API key in, refuses the reflector when asked to, and publishes `DashFeatures` — the one place that knows which optional plugins are present |
| `dashboards-gate.js` | Checks the plugin's liveness stamp before any call to it; a page never polls a plugin that is stopping |
| `dashboard.js` | The device cache: one fetch of everything, then only the devices the `changedSince` endpoint says have moved |
| `capabilities.js` | Which control each device gets, from a capability catalogue |
| `dashboards-action.js` | Control buttons: run the action, take the button over, watch the device states until the thing has really happened. Its rule evaluator is a pure function driven by `tests/test_action_watch.mjs` |
| `dashboards-controls.js`, `dashboards-controls.css` | The device tiles the room, Active, Heating and weather pages share: the one on/off rule, the toggle and brightness handlers and the hub's favourite device press (each confirmed from the device, and put right if the command went nowhere), the heating zone tile with its read-back setpoint buttons, and their styles. Needs `dashboards-action.js` loaded first. Driven by `tests/test_dash_tile.mjs` |
| `dashboards-ui.js` | Link classification, the idle guard, the camera cross-fade (`swapImage`), the tap guard, and the other pieces several pages share |
| `dashboards-alerts.js` | Browser notifications for the alert rules, loaded by the hub, the room pages, Energy and Alerts. The plugin judges the rules (3.47.0); this asks it for new firings and raises a notification for each whose rule includes Browser. One tab polls at a time, and a firing is claimed in `localStorage` so two open tabs never announce it twice. It also keeps the page-side statement of what a rule means, which the plugin's Python is held to case for case (`tests/lib/alert_rule_cases.json`). Driven by `tests/test_alerts_shared.mjs` |
| `when-to-run.js` | The Energy page's When to run it card: the laundry plan and grid carbon |
| `energy-calc.js` | The arithmetic shared by the Energy and Cost pages — unit formatting, the daily energy allocation behind the Sankey, the half-hourly balance, the rolling money sums. DOM-free, so `tests/test_energy_cost.mjs` can drive it |
| `a11y.js`, `dashboards-icons.js`, `standalone-nav.js`, `sw.js` | Accessibility polish, the icon set, keeping links inside the home-screen app, and the service worker that raises notifications |
| `chart.umd.min.js` | [Chart.js](https://www.chartjs.org) (MIT), bundled so charts work with no internet |

## Where the data comes from

- **Indigo's REST API** (`/v2/api`, port 8176, Bearer-authed) for device state and control. The
  pages poll it through the delta cache, so a room page costs a few small requests a second, not a
  full device dump.
- **The plugin's own endpoints**, each a hidden action served by the Indigo web server at
  `/message/<plugin id>/<action>/` and gated by the same API key: `changedSince`, `sigenApi` (the
  proxy to SigenEnergyManager, so the Energy page works away from home), `systemHealth`,
  `carbonAdvisor`, `timelineDay`, `historyQuery`, `mainsMeters` and `mainsMeter`, `homeInsights`,
  `activityFeed`, `logErrors`, `presenceData`, `solarStringHours`, `laundryPlan` and
  `laundryDeadline`, `evoHomeAction`, `applyColour`, `verifyPin`, `cameraStills` (where this
  install's camera pictures are),
  `getDashboardsConfig` and `saveDashboardsConfig`, `burnSetupToken`, `alertRules`,
  `saveAlertRules` and `sendTestAlert` (the Alerts page, 3.47.0), and `mcp_tool_invoke`. The ones
  that change something (`saveDashboardsConfig`, `evoHomeAction`, `applyColour`, `laundryDeadline`,
  `verifyPin`, `burnSetupToken`, `saveAlertRules`, `sendTestAlert`) also refuse a request that is
  not sent as `application/json`, so a plain HTML form on another website cannot reach them
  (3.46.0). None of them is reachable with a guest link.
- **Indigo's change callbacks.** The plugin subscribes to device changes (and to variable changes
  once an alert rule needs them) and receives the old and new copy of each. They feed the
  `changedSince` ledger and, from 3.47.0, the alert rules: a rule is judged in memory on the
  callback, and the Pushover and email sending is handed to the plugin's own alert thread, so a
  slow mail server or a stopped Pushover plugin never holds Indigo up.
- **Files the plugin writes** under `/public/dashboards/`: `config.js`, `rooms.json`, `weather.json`,
  `scenes.json`, `streams.json` (each camera's health, for the camera pages), the camera stills and thumbnails (in a `stills-<token>` folder that only the
  Bearer-authenticated `cameraStills` action names), and `changed.stamp` — the liveness stamp,
  rewritten every two seconds and flipped to "stopping" on shutdown. A static file cannot stall the
  web server, which is why the gate reads that rather than asking the plugin.
- **Files the plugin keeps to itself** in its Preferences folder (`Preferences/Plugins/<plugin
  id>/`, never served): `dashboards_config.json` (the Settings page's store, and the alert rules)
  with a `.bak` beside it, `guest_token.txt`, and `alert_firings.json`, the last fifty alert
  firings, so a restart does not lose them. All three are 0600.
- **The plugin's proxy on port 8177** for camera streams and stills, guest pairing and WebRTC
  signalling. LAN and Tailscale only.
- **The SQL Logger's history database**, read by primary-key range after a binary search for the
  row boundary — never by timestamp, because the `ts` column has no index and a timestamp filter
  would scan the whole table. Long sweeps run on a background thread with a cached reply; a request
  thread never does one. Timestamps are stored in UTC on SQLite and in the session's local time on
  PostgreSQL, and the reader converts per engine.

## Why the gate exists

Every page calls `dashboards-gate.js` before its first request to the plugin. A `/message/` request
that lands on a plugin in the middle of restarting stalls the Indigo web server's event loop for
very close to five minutes — every static file, every API call, every other plugin's endpoint. The
plugin heartbeats `changed.stamp`, flips it to "stopping" first thing in shutdown and waits four
seconds before quiescing, and every page backs off the moment it sees that. The one wall tablet still
running pre-2.70 JavaScript is the reason the upgrade note says to reload long-open tabs.

## Companion scripts

The plugin ticks a handful of Python scripts from its own thread, so they need no schedule in
Indigo: the presence watch that writes the Presence page's data, the hourly event-log watch behind
the Alerts card and the Activity page, the drive-lights and night-sweep helpers, the FP300 presence
sensor configuration watch, the appliance scheduler behind the Laundry page, and the reflector
bandwidth watch. They live in `scripts/` in the repo with their own tests and a README; copy the ones you want
into Indigo's `Python Scripts` folder and the plugin picks them up on its next tick — no restart. At
startup it logs one line naming whichever are missing. Each is optional; a page whose script is
absent says so, and two of them are lighting automations for one house that you may not want at all.
If the Script Ticker plugin is running on the same server, Dashboards leaves the scripts to it and
takes them back within half a minute of it stopping; a laundry deadline change then asks Script
Ticker to replan, so the scheduler never runs in two places at once.

## Logging

Every log line is prefixed with a millisecond timestamp `[HH:MM:SS.mmm]`. Toggle the prefix from
**Plugins → Dashboards → Toggle Timestamps in Log**. Routine housekeeping goes to the plugin's own
log file, not the Indigo event log, unless *Log routine activity to the Indigo Event Log* is ticked;
the `dashboards_read_log` MCP tool reads the same file.

## Tests

A no-hardware contract-test layer pins the plugin's trickiest logic so a change cannot silently
regress it. `tests/run.sh` is the gate: `pytest` over `tests/` and over the companion scripts, every
`tests/*.mjs` node suite, `compileall` and `ruff`. CI runs exactly the same on every push. The Python
side mock-imports `plugin.py` with `indigo` stubbed, so the plugin's helpers run outside the Indigo
host; the node side extracts functions from the pages by name and drives them in a `vm` context.
`tests/README.md` lists every file and what it locks.

## The repository

```
Dashboards/
├── Dashboards.indigoPlugin/       the bundle Indigo installs
│   └── Contents/
│       ├── Info.plist
│       ├── Resources/
│       │   ├── mcp-manifest.json  the plugin's MCP tools
│       │   └── static/pages/      every page and shared script
│       └── Server Plugin/         plugin.py and its mixins, mcp_tools.py, history_db.py, the XML
├── docs/                          this site (GitHub Pages), including the screenshots
├── scripts/                       the companion scripts and their tests
├── tests/                         the contract-test suite
├── tools/                         capture, demo-fixture and preflight tooling
└── README.md                      the front page
```

`plugin.py` holds the plugin's core: start-up and shutdown, the background loop, the rooms and
scenes maps, the weather card, the liveness stamp and most of the page endpoints. Everything else
lives in modules beside it, which `Plugin` inherits, so every method is still `self.<name>` and
`Actions.xml` still names the same callbacks:

| Module | What it holds |
|---|---|
| `cameras_mixin.py` | go2rtc, the :8177 server (WebRTC set-up, bootstraps, guest reads), the snapshot poller and its thumbnails, and the stream and camera-health files |
| `config_mixin.py` | The settings store (`dashboards_config.json`), the one-time import of legacy settings, and the Settings page's load and save |
| `alerts_mixin.py` | The alert rules (3.47.0): judged on Indigo's change callbacks, delivered by Pushover and email on a worker thread, the recent firings, and the Alerts page's endpoints |
| `publish_mixin.py` | Copying the pages into `Web Assets/public/dashboards` and writing `config.js`, with its flags for optional plugins |
| `health_mixin.py` | The System Health page: Mac vitals, storage, services and the device census |
| `scripts_mixin.py` | The companion-script runner, its schedule and the hand-over to Script Ticker |
| `history_mixin.py` | Everything that reads the SQL Logger history: Graphs, Timeline, the per-string solar hours, and the primary-key helpers that keep those queries off a full scan |
| `mains_mixin.py` | The Mains and Meter pages: every 240 V meter and how far each can be trusted |
| `insights_mixin.py` | Home Insights, the hub's "out of the ordinary" card |
| `carbon_mixin.py` | The Carbon page's grid-intensity advice |
| `dash_common.py` | The constants and the `log()` helper every module shares |
| `dash_util.py` | Small pure helpers the modules share |
