---
title: How it is built
nav_order: 9
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
| `dashboards-ui.js` | Link classification, the idle guard, the stream budget, and the other pieces several pages share |
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
  `laundryDeadline`, `evoHomeAction`, `applyColour`, `verifyPin`, `customPages`,
  `getDashboardsConfig` and `saveDashboardsConfig`, `burnSetupToken`, and `mcp_tool_invoke`.
- **Files the plugin writes** under `/public/dashboards/`: `config.js`, `rooms.json`, `weather.json`,
  `scenes.json`, the camera stills and thumbnails, and `changed.stamp` — the liveness stamp,
  rewritten every two seconds and flipped to "stopping" on shutdown. A static file cannot stall the
  web server, which is why the gate reads that rather than asking the plugin.
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
│       └── Server Plugin/         plugin.py, mcp_tools.py, history_db.py, the XML
├── docs/                          this site (GitHub Pages), including the screenshots
├── scripts/                       the companion scripts and their tests
├── tests/                         the contract-test suite
├── tools/                         capture, demo-fixture and preflight tooling
└── README.md                      the front page
```
