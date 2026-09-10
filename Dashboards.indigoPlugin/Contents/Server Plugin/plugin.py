#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: Dashboards plugin — at startup, copies the HTML pages from the
#              plugin bundle into Indigo's `Web Assets/public/dashboards/`
#              folder so they are served WITHOUT HTTP Basic Auth (the IWS
#              `public/` namespace is the only path that bypasses auth).
#              Reads INDIGO_URL from IndigoSecrets.py and writes it into
#              `config.js` alongside the copied pages. The API key is NEVER
#              published (v1.20.0+) — browsers prompt once and store it in
#              localStorage, merged in by dashboards-auth.js.
#              Polls Dahua cameras in a background thread using HTTP Digest
#              auth (DAHUA_USER / DAHUA_PASS from IndigoSecrets.py) and writes
#              the JPEGs as cam-<ip>.jpg into the same public folder, so
#              cameras.html loads them same-origin with no browser auth.
#              Also runs a tiny HTTP MJPEG proxy on port 8177 that relays each
#              camera's live multipart/x-mixed-replace stream to the browser,
#              again handling Digest auth server-side. The page uses MJPEG
#              for the live grid and falls back to the still snapshot if a
#              stream connection fails.
# Author:      CliveS & Claude Fable 5.1 (3.12.0-3.13.0); Claude Sonnet 5 (2.99.2); Claude Fable 5 (2.79.0); Claude Opus 5 (2.80-2.81, 2.84.0)
# Date:        10-09-2026
# Version:     3.13.1
#
# v3.13.1 (10-09-2026): FIRST PUBLIC RELEASE — a fresh single-commit repository
#   built from a scrubbed tree; the earlier history stays in a private archive.
#   In the tree: example addresses in comments and tests are generic
#   documentation ones; the demo fixture is re-sanitised (credentials of every
#   kind, e-mail addresses, Shelly and Zigbee hardware addresses and a
#   household name are placeholders, not only IPs) and the fixture generator
#   now scrubs those same classes; two tests keep it that way. No behaviour
#   change on a running install.
#
# v3.13.0 (10-09-2026): THE SIGENERGY PAGES HIDE THEMSELVES WHEN THE PLUGIN IS
#   ABSENT. Energy, Cost and Laundry only have something to draw with
#   SigenEnergyManager installed, and the README never said so. config.js now
#   carries sigenAvailable (installed AND enabled — not isRunning, so a
#   restart cannot flicker the pages off) beside heatingControls, both from
#   ONE builder, _feature_flags(); the 30 s tick rewrites config.js when a
#   flag changes, so installing or removing the plugin needs no restart here.
#   Without it: the menu drops the three tiles, the hub hides its Energy and
#   Solar cards and the power-cut banner and says in one line which plugin is
#   missing, each of the three pages opened by bookmark draws one card saying
#   what it needs (DashFeatures.sigenAbsent in dashboards-auth.js), the sigenApi
#   proxy answers 503 {reason: sem_absent} at once instead of dialling :8179
#   and WARNING on every hub poll, the laundry endpoint says why there is no
#   plan, the scheduler tick does not run, and Test Dashboards Setup reports it
#   as an optional SKIP. Demo mode forces the flag on, since the fixtures carry
#   energy data whatever the server has. An older config.js without the key
#   reads as present, so an upgrade cannot hide pages that were there yesterday.
#   heatingControls now also requires EvoHomeControl to be ENABLED, not merely
#   installed — a disabled plugin swallows the boost/force actions silently.
#
# v3.12.0 (10-09-2026): PLUGIN-PROVIDED MCP TOOLS. The bundle ships
#   Contents/Resources/mcp-manifest.json describing eight tools (status, the
#   setup check as data, room folders read/write, cameras read/write/remove,
#   the plugin's own log tail). Any Indigo MCP server that reads provider
#   manifests — mlamoure's Indigo MCP Server from v2026.8.1, Claude Bridge
#   from v2.26.0 — lists them to the AI as dashboards_<name> and forwards each
#   call to the new hidden mcp_tool_invoke action, which hands it to
#   mcp_tools.dispatch() (imported lazily, so a fault there cannot touch
#   startup). Writes go through Plugin._apply_config, the Settings endpoint's
#   own validate + persist + apply path, now extracted so the two cannot
#   drift; the setup check's checks are built by _setup_checks() and the menu
#   item only logs them. startup() broadcasts "mcp_tools_updated" so a server
#   picks the tools up the moment the plugin starts. For everyone else the
#   manifest is inert data and the action is never called.
#   Fixed on the way: _effective_config() reported the RUNNING cameras
#   (module CAMERAS, which only changes at restart) rather than the saved
#   ones, so a Settings page reopened after adding a camera showed the old
#   list and its next Save deleted the new one. It now reports what is saved.
#
# v2.99.2 (03-09-2026): the Living Room's third FP300 (Presence_Watch 1.5) made
#   presence.html's two-sensor assumptions visible — "Both" as a fixed label,
#   "1 of 2" as a fixed string, and a callout that could only ever name ONE
#   missing sensor. All three are dynamic now: the row reads "All 3" for a
#   three-sensor room, the reporting count reads N of M from the payload's new
#   reportingCount/sensorCount fields, and the "no data yet" callout can name
#   more than one sensor (a small joinLabels() helper, mirroring
#   Presence_Watch.py's own _join()). No behaviour change for Bedroom 1,
#   still two sensors.
#
# v2.84.4 (20-08-2026): Energy now shows the forecast's typical historical
# error band (explicitly not a guarantee), a descriptive per-array yield
# fingerprint, a live decision trace and a manual half-hour replay. The hub
# leads with active Home Insights and the data-heavy pages pause polling while
# hidden. Camera health is exposed through streams.json as safe operational
# metadata only — no URLs, errors, credentials or viewer data — and the page
# reports retrying/offline cameras. A release-declaration test prevents the
# Info.plist, runtime constant, README and repo notes drifting apart again.
#
# v2.84.3 (18-08-2026): the Grid events table drops the "Our kWh" and "Diff"
# columns at CliveS's request, and he was right to ask. Our figure is measured
# over a DIFFERENT SPAN from Axle's — the driver runs either side of the paid
# window — so putting the two side by side under a column called "Diff"
# invited the reading that a wide gap meant Axle had short-changed us. On
# 11-Aug it read 7.05 against 3.801 while the paid hour was in fact textbook.
# The figure is still recorded in the ledger, and is still what makes an
# over-running window detectable; it is simply not this table's business.
#
# v2.84.2 (18-08-2026): a 404 from the Sigenergy API is no longer logged as a
# WARNING. It is not a fault — it means that plugin is older than the path
# being asked for, which is the ordinary state between the two being upgraded.
# Spotted the moment the ledger shipped: the Cost page polls `vpp` every five
# minutes, so an open page would have put an amber line in the log every five
# minutes for a system working exactly as designed, and the standing estate
# rule is that red and amber are for faults. Everything else still warns.
#
# v2.84.1 (18-08-2026): the hub's two VPP rows extracted into pure
# vppStatusRow()/vppEarningsRow(). Behaviour-identical — the point is the
# test seam: these states appear a handful of times a month, so they are
# exactly the ones nobody notices being wrong. 28 checks, and the mutation
# pass immediately earned its keep: dropping escapeAttr from the RUNNING
# branch SURVIVED, because the escaping test only ever exercised the
# ANNOUNCED one. Both branches interpolate the same field. Testing one
# branch is not testing its sibling — the v2.66.0 lesson, again.
#
# v2.84.0 (18-08-2026): VPP EARNINGS ON SCREEN — what Axle actually PAID,
# beside what we exported. The plugin has always shown whether a grid event
# was running and never once shown what it earned, so the only place the
# money existed was the Axle account page. New SigenEnergyManager /api/vpp
# (v5.72.0) carries the ledger through the existing sigenApi proxy — one new
# allow-listed path, no new transport, and it works over the reflector like
# everything else.
#   • COST PAGE gains a Grid events card: available balance, lifetime, this
#     month, and grid-event earnings kept SEPARATE from the monthly floor
#     payments and the referral credit (lumping them together flatters the
#     battery — GBP 25 of the lifetime total is a referral). Per-event table
#     pairs Axle's settled kWh with ours, because the GAP is the informative
#     part: Axle settles on the change against a baseline, so ~0.2 kWh under
#     our figure is ordinary, while the 3.2 kWh gap on 11-Aug is the export
#     over-running the paid hour and is visible nowhere else.
#   • HUB's VPP row is now PERMANENT. "None announced" is a real answer, and
#     paired with the feed-health check it is what stops a dead Axle feed
#     reading as a quiet fortnight — exactly how a revoked token hid from
#     15-Jun to 30-Jul-2026. A failing poll is reported as failing, never as
#     an absence of events, because a feed that cannot answer cannot announce.
#   • An unsettled event renders as "pending", never GBP 0.00. Settlement runs
#     days behind, so the newest event is normally unsettled and a confident
#     zero would report a loss that never happened. Same rule on a month with
#     nothing settled yet.
#   • Ledger polled every 5 min, not on the page's 30 s beat — it only moves
#     when an event ends or Axle's figures are re-imported.
#
# v2.83.0 (13-08-2026): GRID VOLTAGE ON THE CARD — 252.2 V against a 253.0 V
# ceiling. SigenEnergyManager v5.71.0 found the MEASURED voltage (the
# register the plugin had been reading was the 230 V nameplate), and it
# matters: above the UK statutory ceiling an inverter must curtail or
# disconnect, so this is lost export revenue and the cause is the DNO's
# network rather than anything in the house. The tile warns within 3 V of
# the limit and goes red beyond it. Limits come from the payload, never
# hardcoded here — they are not the same on every network. New pure
# DashCalc.gridVoltageState (energy-calc.js v1.5) with tests, including the
# case that the same reading is FINE against a different network's limits.
#
# v2.82.0 (13-08-2026): THREE MORE TILES THE DOCUMENTATION PAID FOR. Reading
# the official Sigenergy protocol (SigenEnergyManager v5.69.0) named five
# registers that had only been probed, and the card now shows the useful
# ones: INVERTER TEMP (the power electronics' own temperature, 58.3 degC
# live — nothing in the estate was watching it), PV INSULATION resistance
# (a SAFETY reading: falling means moisture ingress or damaged DC cable),
# and INVERTER ALARM (raised / clear). Insulation is shown with NO verdict
# on purpose — the manufacturer's fault threshold is not in the public spec,
# so the honest use is to watch it trend, which the SQL Logger now supports,
# rather than judge it against a number we would be inventing. The
# inverter's own alarm answers the pass/fail question.
#
# v2.81.0 (13-08-2026): THE BATTERY CARD SAYS WHAT IT CAN ABOUT THE FOUR
# PACKS. Asked to show each pack's SOC and temperature, the honest answer
# came from a probe rather than a guess: the inverter EXPOSES NO PER-PACK
# REGISTERS (SigenEnergyManager v5.68.0 has the register-by-register
# evidence). What it does publish is the average, the hottest cluster and
# the coldest — and over four identical packs those three BOUND the
# distribution, so the plugin can infer whether one pack is out of step.
# The Battery health card gains a "Pack balance" tile wording that verdict
# ("One pack 4.9°C above the others" on today's live reading) and a "Grid
# frequency" tile, both from new pure helpers in energy-calc.js v1.4
# (packBalanceText, gridFrequencyState). Neither tile appears unless the
# figures support it — a card that cannot know must not reassure. The
# frequency band is the UK statutory range: ±0.2 Hz normal, ±0.5 the
# operating limit, and it is the quantity a VPP event is ultimately about.
# NB the first cut read window.__SIGEN_DATA, which is the HUB's global and
# does not exist on this page — both tiles would have silently never
# appeared. This page keeps its payload in _solStatus.
#
# v2.80.0 (13-08-2026): THE HUB'S "SOLAR · TODAY" GETS THE SAME CHART. The
# hub block showed forecast bars only — no actuals, no strings, no verdict.
# The v2.79.0 renderer therefore MOVED OUT of energy.html into the shared
# dashboards-ui.js as DashUI.solarHoursChart (+ STRING_COLOURS /
# STRING_STACK_ORDER), so the Energy card and the hub draw ONE
# implementation at two sizes — exactly the lesson of forecastBars, whose
# duplicate copy kept light-mode hex in dark mode until v2.50.0 merged it.
# The hub gets `compact: true`: no y-axis (380 px cannot carry one beside 24
# columns), hour labels every 6, thinner ticks, legend only once something
# actually stacks, and the scoreboard folded into the existing meta row.
# THE ENABLER IS SERVER-SIDE: solarStringHours now ALSO returns `site` — the
# same hour buckets from `pvpowerwatts`, one more avg() in the SAME query,
# so it costs nothing. That column has been logged for years, so it covers
# every hour of every day INCLUDING those before per-string logging began.
# Consequences: the hub needs no history fetch at all (it never had one),
# and the Energy page's slot-MIDPOINT attribution drops from primary to
# last-resort — it now only serves an install with no SQL Logger, where the
# endpoint has nothing to read. Precedence in DashCalc.buildSolarHours
# (v1.3, signature gains siteHours): strings -> site -> slots. A partly-NULL
# string row yields its site figure and NO stack — never a half-invented
# one; an hour absent from every source stays a gap. `_hour_frac` extracted
# so "how much of this hour has run" is decided in one place for both
# series. Tests: pytest 236 -> 238 (site coverage, partly-null rows,
# _hour_frac), mjs 57 -> 59 (site beats slots, site covers what strings
# can't).
#
# v2.79.0 (13-08-2026): THE HOURLY SOLAR CHART GROWS UP — stacked strings +
# beat/miss (spec agreed by MCQ: mySigen app colours, tick-line markers, the
# cumulative chart stays too). The Energy page's forecast-only bar strip is
# replaced by a chart double the height with a kWh scale: ELAPSED hours are
# stacked per-string actuals (South indigo / East cyan / West green / Garage
# purple — the mySigen app's own colours, so the two screens read as one
# system; stack order biggest-first for visual stability), each with a dashed
# FORECAST TICK at the promised height — the stack topping or missing its
# tick IS the beat/miss verdict, drawn in geometry so it survives colour
# blindness — plus a scoreboard line ("Beat the forecast N of M daylight
# hours so far"; completed hours only, dark hours prove nothing). FUTURE
# hours stay pale forecast bars; tap any hour for its per-string breakdown
# vs forecast. Hours with no per-string history (this morning, pre-v5.67.0)
# fall back to plain site-total bars from the /api/history slots, attributed
# by slot MIDPOINT (a half-slot skew beats dropping the hour); a past hour
# with no data at all stays a GAP, never a fabricated zero. NEW hidden
# endpoint solarStringHours (Actions.xml-registered — an unregistered
# /message route HANGS) integrates per-hour per-string kWh from the
# SQL-logged pv1watts..pv4watts columns: hour-bucket avg() in SQL (mean
# power over an hour IS its kWh at /1000; the current hour scales by elapsed
# fraction), PK-ranged like every read of that DB, 120 s server cache,
# hours=[] when the columns don't exist. Pure halves tested both sides:
# Plugin._string_hours_payload (pytest) + DashCalc.buildSolarHours
# (energy-calc.js v1.2, test_energy_cost.mjs). The per-string strip also
# gains each string's kWh today, summed from the same feed. The hub's
# Weather-card forecast bars (DashUI.forecastBars) are untouched.
#
# v2.78.0 (13-08-2026): SOLAR PROGRESS CHART + PER-STRING STRIP (Energy page).
# The Solar card gains a cumulative actual-vs-expected chart: solid line =
# kWh banked so far today (today's /api/history half-hour slots, cumulative,
# with the last point PINNED to solar.actual_today_kwh so the line reaches
# "now" ahead of the unwritten current slot — and a pinned total BEHIND the
# slots is refused so a stale status payload can never step the line
# backwards), dashed line = the bias-corrected hourly_forecast accumulated to
# dusk, ending at the "Expected total" figure the card already shows, plus an
# ahead/behind/on-forecast chip (±0.3 kWh deadband). The maths is the pure
# DashCalc.buildSolarProgress (energy-calc.js v1.1, tests in
# test_energy_cost.mjs); the page only draws. Data is married from the two
# feeds the page already runs — no new endpoints, works over the reflector.
# NEW per-string strip under the Solar tiles, fed by SigenEnergyManager
# v5.67.0's solar.strings ([{n,label,v,a,w,kwp?}] from the inverter's 31025
# block): one row per string — name, capacity-scaled bar (percentage of that
# string's own kWp when the SEM labels carry one, so a 2.85 kW string pulling
# its weight reads full beside a 4.275 kW one; relative to the strongest
# string until then), live W and V. Hidden entirely while the feed has no
# strings (pre-5.67.0 SEM, or an inverter without the registers) — the page
# never draws invented zeros.
#
# v2.77.0 (13-08-2026): FRONT DOOR JOINS THE STATE-DRIVEN TILES + reading
# colour bands. The door favourite gains a LOCK-flavoured variant: a lockId
# alongside the contact-device id makes the tile derive from lock + contact
# instead of doorState — white "Locked" (press fires openAction, the unlock
# sequence), blue "Unlocked" (display-only: no action closes a front door,
# and re-firing the unlock outside its watched sequence invites overlapping
# runs of a script that blocks 90 s), red "Open" (display-only). The contact
# is consulted FIRST so a dead lock can never hide an open door, and an
# absent contact is UNKNOWN even with a healthy lock — a silent sensor must
# not render as a reassuring "Locked". The old "Open Front Door" scene
# favourite is replaced by a door entry labelled plain "Front Door" (the
# press confirmation keeps the 95 s watch spec, now with the blue veil and
# no green flash). dashboards-action.js → v1.2 (pure lockTile(), same test
# file). Reading favourites gain optional colour bands warnBelow/badBelow:
# value red below badBelow, amber below warnBelow, green at or above —
# compared against the RAW numeric state, never the ".ui" string ("12.60 V"
# is not a number); no bands configured = the plain tile, unchanged. The
# Qashqai 12V tile gets 12.4/12.0 (healthy resting ≥12.4 V). settings.html:
# door rows gain an optional lock-device picker (close action may then be
# unset — open action plus at least one of close/lock enforced both ends),
# reading rows gain the two band inputs.
#
# v2.76.0 (13-08-2026): ONE STATE-DRIVEN GARAGE TILE replaces the Open/Close
# pair in the hub favourites. New favourite type "door": {type:"door", id:
# <door device>, openAction:<ag>, closeAction:<ag>, label?, state?} — the tile
# paints itself from the device's doorState on the existing 3 s poll (white
# Closed, BLUE Opening…/Closing… with a sweep bar, RED filled Open, AMBER
# Stuck, grey dash when the device is absent from the poll — an absent state
# must never read as a confident "Closed"), and a press fires the action for
# the state SHOWING: closed→openAction, open→closeAction, stuck→closeAction
# (securing the house is the useful recovery), moving/unknown→nothing.
# Direction never depends on tile freshness — the GarageDoor plugin's actions
# are idempotent, so a stale press can only no-op. Because it is state-driven
# the tile doubles as an indicator: worked from the hall button or HomeKit it
# goes blue/red on its own, and moving direction is named from the last
# settled state this page saw (opened mid-travel = neutral "Moving…").
# dashboards-action.js → v1.1: pure doorTile() map (the test seam,
# tests/test_door_tile.mjs), spec theme:"door" turns the in-flight veil blue,
# and holdDone:0 clears a done veil at once — the tile turning red/white IS
# the confirmation, so the green interlude is gone for door presses (failure
# veils keep their long holds). settings.html: "Door tiles (state-driven)"
# optgroup + per-direction action pickers; save sanitiser accepts the new
# shape (both actions required or the row is dropped — half a door is a
# trap). Colours mirror the GarageDoor hall-lamp convention (blue moving,
# red open, white restored) so the house speaks one colour language; text
# always carries the state, colour only reinforces it (the CVD rule).
# Install-side: the two scene favourites (Force Open/Close) replaced by one
# door entry for device 489580549; the two actionWatch specs are unchanged
# and still drive press confirmation.
#
# v2.75.4 (13-08-2026): GO2RTC'S LOG CAN NOW BE PLACED ON A DAY. go2rtc stamps
# the TIME only, so a log spanning several days cannot tell last night's camera
# failures from the same failures a week earlier — which is exactly what went
# wrong on 13-08-2026 diagnosing an overnight outage in which every camera went
# unreachable for nine hours. go2rtc CANNOT be configured out of it: the console
# writer hardcodes zerolog's TimeFormat to "15:04:05.000", measured by running
# 1.9.14 twice on throwaway configs differing only in a `log: time:` key (both
# stamped identically). New `_stamp_go2rtc_log()` writes one dated marker into
# the log at start and whenever the local date rolls over, called from the
# supervision tick that already runs every 30 s.
#
#   • Deliberately markers, NOT a pipe. Reading the child's stdout to prefix
#     each line would let a stalled reader fill the 64 KB pipe buffer and BLOCK
#     go2rtc — trading a logging nicety for a wedged camera backend. Appending
#     one line a day to a file the child already holds open adds no new failure
#     mode, and a marker that fails to write costs nothing.
#   • The date is NOT recorded as stamped unless the write succeeded, or a
#     failed write would silently cost the whole day's marker.
#   • THE FIRST ATTEMPT TO MEASURE THE `time:` KEY PROVED NOTHING and nearly
#     shipped as fact: the yaml was hand-patched in place, but _start_go2rtc
#     calls _write_go2rtc_config, so the key was regenerated away before go2rtc
#     ever read the file. Test a config change in isolation, never against a
#     file the plugin owns and rewrites.
#   • The first cut of the marker itself used `datetime.datetime.now()` where
#     this file does `from datetime import datetime` — AttributeError straight
#     into the deliberate blanket except, i.e. a marker that silently never
#     appeared. py_compile passed it; a test driving the real function caught it.
#   • PLUGIN_VERSION had drifted AGAIN (2.75.2 against a 2.75.3 plist), the
#     same fault v2.66.0 was written about. It feeds the User-Agent and the
#     `plugin_version` field in /api/status, so both had been under-reporting.
#     Resynced.
#
# v2.75.3 (08-08-2026): REQUIRED Info.plist KEY. `CFBundleURLTypes` was PRESENT but
# EMPTY, so the plugin shipped without the support URL that becomes its
# "About" menu item — one of the SIX keys the official Developer's Guide lists as
# required. An empty array satisfies "key exists" while giving users nowhere to go,
# which is why an earlier sweep that only looked for a MISSING key passed it. Found
# by an estate check auditing the VALUE rather than the key's presence.
# No plugin logic changed.
#
# v2.66.0 (30-07-2026): HUB — VPP REPLACES THE CARBON CHIP, AND THE RUNNING
# VERSION IS ON SCREEN. All three asked for by CliveS after the VPP event
# turned up.
#
#   • The grid-carbon chip is GONE from the house-pulse row — he does not use
#     it. Its 5-minute carbonAdvisor poll went with it, since nothing else on
#     the hub read __CARBON_DATA: it was a request every five minutes for a
#     number nobody looked at. The Carbon PAGE is untouched and still linked
#     from the tile wall; it fetches its own data.
#   • In its place, a VPP chip — shown ONLY while a window is announced or
#     running, so the row stays short on the ~364 days a year when nothing is
#     happening. An always-on "VPP idle" chip would be noise.
#   • The Energy · Now card gains a matching VPP row, on BOTH breakpoints. The
#     phone card is deliberately short, but a paid grid event earns a line.
#   • The running version now sits beside the date in the hero.
#
# The version is read from window.DASHBOARDS_BUILD, which config.js has carried
# all along and NO page but cameras.html ever displayed. It is now sourced from
# Info.plist (self.pluginVersion) instead of the PLUGIN_VERSION constant —
# that constant is a hand-maintained copy which has drifted TWICE (2.9.0 while
# the code was on 2.13.0, and 2.65.0 against a 2.65.1 plist, found while doing
# this). Indigo reads the plist, so the plist is what is running, and a version
# display that can lie is worse than none. The constant is now correct too.
# The hero reads the global DIRECTLY rather than through INDIGO_CONFIG, because
# dashboards-auth.js rebuilds that object from a whitelist and silently drops
# anything not listed — the trap that already cost favourites (v2.10.0) and
# customLinks (v2.13.1) a release each. A comment now says so at the whitelist.
#
# v2.65.1 (30-07-2026): TWO ENERGY-PAGE FAULTS, BOTH REVEALED BY THE FIRST VPP
# EVENT SINCE 15-JUN. Reported from a phone screenshot, and neither could have
# shown up before today — that is the interesting part of both.
#
#   1. THE ALERT BAR PRINTED RAW SVG SOURCE. updateAlerts() built each message
#      as `I('bolt') + ' VPP event announced: …'` and assigned the lot to
#      `bar.textContent`. I() returns MARKUP, and textContent escapes markup, so
#      the page showed `<svg class="dsh-icon" viewBox="0 0 24 24" …>` in red
#      across the top instead of drawing an icon. It survived the v2.51.0 icon
#      sweep — which audited insertion points for exactly this — because EVERY
#      branch in that function is an exception state that had not occurred
#      since: no storm has hit, Modbus has not dropped, and the VPP branch
#      could not fire at all while the Axle feed was dead (see
#      SigenEnergyManager v5.55.0). Messages are now {icon, text} pairs written
#      with innerHTML: the icon passes through as markup, the text — which
#      carries API values like the event window and the storm level — goes
#      through esc(). Splitting them is the point; switching to innerHTML alone
#      would have traded a cosmetic bug for an injection.
#
#   2. THE CHIP ROW SAT ON TOP OF THE TITLE. .hero-chips was ABSOLUTELY
#      positioned at top/right over a static <h2>, which fitted while there
#      were two chips. Tonight a third appeared (VPP ANNOUNCED) and the row
#      grew leftwards across "Live power flow" on a phone. Absolute positioning
#      cannot push anything out of its way, so the collision was certain the
#      moment the row outgrew the gap. Title and chips now share one wrapping
#      flex row (.hero-head), so a fourth chip would wrap rather than collide.
#
# NEW tests/test_energy_alert_bar.mjs (16 checks) drives the REAL updateAlerts()
# out of the shipped page; 10 of the 16 verified failing against the pre-fix
# page, with the failure output reproducing the exact string from the
# screenshot. Suite: 206 pytest + 8 node, preflight 57/0.
#
# NB the same absolute-positioned .hero-chips pattern is also in cost.html and
# system-health.html. Neither shows a third chip today, so both were left alone
# — but they carry the same latent overlap if their rows ever grow.
#
# v2.55.1 (29-07-2026): SECURITY — the go2rtc API was serving the camera
# password to the whole network. Its config bound the API to ':1984', which is
# every interface, with `origin: '*'` on top; go2rtc requires no auth, and
# /api/streams returns each camera's full RTSP URL with DAHUA_USER:DAHUA_PASS
# in clear text. So any device on the LAN could read the camera credentials —
# and because of the wildcard origin, so could ANY web page open in ANY browser
# on the network, cross-origin, and send them anywhere. Live-confirmed before
# the fix. Now bound to 127.0.0.1 with no origin line. Nothing legitimate used
# it: every consumer in this plugin already dials 127.0.0.1, no dashboard page
# references the port, and live.html (the WebRTC page the wildcard was added
# for) was retired long ago. The plugin's own /streams route remains the public
# view and already sanitises producer URLs (v2.35.0) — this shuts the door that
# sanitiser was standing in front of. Verified after the fix: LAN refused,
# loopback 200, snapshots and cameras.html unaffected. ROTATE THE CAMERA
# PASSWORD — it has been readable on the network for as long as this shipped.
#
# v2.55.0 (28-07-2026): THE DELTA UPDATES HAD NEVER ONCE RUN, plus three more
# found by a deep review weighted on the camera path and the IWS handlers.
# (1) dashboard.js starts its changedSince cursor at 0, the server answers
# since<=0 with {full:true}, and getDevices() returns the full-fetch result
# EARLY — and that function set devices and lastFull but never the cursor. So
# the cursor could never leave 0, every poll asked with since=0, every reply
# said "full", and the delta system built in v1.22.0 has been dead since the
# day it shipped. MEASURED before the fix: 685 kB of device list every three
# seconds per open page, against a 498-byte delta reply. The full-fetch path
# now seeds the cursor from the server clock (local clock as a fallback when
# the endpoint is unreachable — slightly wrong beats pinned at zero). The
# existing tests all stubbed _fullDeviceFetch out, which is precisely why they
# never caught it; the three new cases drive the real one and were verified
# failing against the old code. (2) The go2rtc orphan guard added in v2.37.0
# was dead code: plugin.py never imports urllib at top level, every other user
# imports it inside its own function, and _start_go2rtc did not — so the guard
# raised NameError straight into a bare `except Exception: pass` and looked
# exactly like the healthy "nothing answering" case. Import added, and the
# handler now distinguishes a free port from a check that could not run,
# because a failed check silently passing as a passed check is what hid this
# for four months. (3) Off-LAN the single live camera slot follows the focus,
# but tryRestoreLive still asked DEFAULT_LIVE_SET — which holds only hosts[0]
# when the pool is one. Both halves were wrong: a focused tile promoted by
# focusTile could never regain live after a stall (while the watchdog logged
# "retrying" every 1.5s that the gate then refused), and hosts[0], demoted by
# a handover but still carrying autoDegraded, could restore ITSELF and open a
# second MJPEG socket on the one link where that is the thing being avoided.
# New mayHoldLive() answers the entitlement question properly. (4) Both
# checkbox prefs were read with bare bool(), and bool("false") is True — so
# unticking bootstrapKeySeed would not have disabled the API-key auto-seed.
# Latent here (this install's .indiPref is empty, so the default applied), but
# it would bite the first person to save the Configure dialog. Both now use
# plugin_utils.as_bool. Also new: tools/theme_shots.py renders all 20 pages in
# both colour schemes and checks the pixels, which is the honest way to verify
# the v2.51.0 theme sweep — 40/40 clean, no page where dark equals light.
#
# v2.48.0 (25-07-2026): HOURLY LOG-ERROR WATCH. Nothing on this install watched
# the event log. The five eventLogError triggers each match one hardcoded
# string, and the Activity page only collapses errors while you have it open,
# so anything genuinely new went unnoticed until somebody happened to read the
# log. New Python Scripts/Log_Error_Watch.py collapses errors into signatures
# (source + digit-normalised message, the same key the Activity page uses),
# keeps a state file of what it has seen, and reports only what is NEW or has
# gone unresolved for a day — first run seeds and deliberately says nothing, so
# the estate's existing background noise never pages anyone. It sends its own
# Pushover and email; this plugin adds:
# * _run_log_error_watch(), ticked hourly from BOTH runConcurrentThread
#   branches (LOG_WATCH_REFRESH_SECONDS). Driving it from here rather than an
#   Indigo schedule is forced: indigo.schedule.create() exists but cannot set a
#   schedule's ACTION STEP, so a scripted schedule would run nothing.
# * A Bearer-authed logErrors endpoint (Actions.xml + handleLogErrors) serving
#   the script's state file. The file lives in Python Scripts/, NOT /public —
#   that folder is anonymous and reflector-reachable, and raw event-log text
#   carries hostnames, IPs and traceback fragments (the v2.35.0 lesson).
# * A card on alerts.html, kept visually separate from the localStorage rules
#   so the page's "only while this page is open" honesty text stays true, and a
#   hub chip that stays hidden unless there are live unmuted errors.
# ALSO FIXES a real bug in _activity_events: a core-server message carries the
# BARE level as its source ("Error"/"Warning"), and `src.replace(" Error", "")`
# is a no-op on that — no leading space — so every server-level error on the
# Activity page was attributed to a plugin called "Error". Now "Indigo Server".
# The watch script's contract tests caught it; both copies are fixed.
#
# v2.47.0 (25-07-2026): three ideas harvested from the Domio plugin's
# history_db.py (Simon's, com.simons-plugins.domio).
# * SQL LOGGER ARTEFACT COLUMNS ARE HIDDEN. The logger cannot ALTER a column
#   whose logged type changes, so it adds a new one suffixed with an epoch —
#   "batterysoc_1782308459229" beside the live "batterysoc" — and never removes
#   the old one. 256 of them here across 41 of 268 devices, 17 on the Sigen
#   inverter alone, all of them offered in the Graphs picker. Worse, the
#   timeline and Home Insights column lookups fall back to a startswith match,
#   so they could silently chart a dead column; that is closed too.
# * STATES CARRY THEIR TYPE. An on/off state is now drawn as a step with an
#   on/off axis and a "on for N% of the range" figure, instead of a line
#   sloping between 0 and 1 through readings that never existed.
# * POSTGRESQL BACKEND. A user whose SQL Logger writes to Postgres can now use
#   Graphs, Timeline and Home Insights; it was SQLite-only. Selectable in
#   Configure, credentials from IndigoSecrets.py first (HISTORY_PG_*) per the
#   secrets policy, and a new "Test History Connection" menu item reports what
#   it found. No new dependency — it shells out to psql rather than making
#   every SQLite user install a Postgres driver. Parameters are refused unless
#   they are an int or a strict timestamp/digit string, so the substitution
#   cannot be turned into an injection; identifiers were already validated
#   against the live column list.
#   NB the Postgres path is UNTESTED against a real server here — this install
#   runs SQLite. It is opt-in and defaults off.
# NOT harvested: Domio corrects the logger's timestamps from local to UTC.
# Measured across all 245 history tables here, the newest row sat +1s behind
# UTC and +3601s behind local, so `ts` is already UTC on this install and that
# correction would introduce the very hour it removes.
#
# v2.46.1 (25-07-2026): the Domio page mirror copies EVERY shared .js from the
# source folder, not a hand-kept list of three. The list had drifted badly
# behind what the pages reference: a11y.js (24 pages) and chart.umd.min.js
# (6 pages) had never been mirrored at all, so the Domio copies had been
# running without accessibility wiring and without charts. v2.46.0's new
# energy-calc.js would have been worse than a degradation — the Energy and
# Cost pages reference it at parse time, so those two would have rendered
# nothing in Domio. Mirroring *.js the same way *.html is mirrored means
# adding a script can no longer half-ship.
# NB the mirror is still additive by design (it cannot tell our stale pages
# from the user's own), so a renamed page still needs deleting by hand from
# Web Assets/static/pages/. `home.html` there is NOT ours and NOT stale — it
# is a deliberate thin redirect carrying Domio page-manifest metadata.
#
# v2.46.0 (25-07-2026): Energy + Cost calculation audit and Cost page rebuild.
# Six faults were found by checking the figures against the live system rather
# than reading the code, and all six were confirmed failing against the old
# page code before anything was changed.
# * The half-hourly chart DOUBLE-COUNTED. It stacked Solar and Export upwards
#   and Home and Import downwards, but export is a SUBSET of solar (and of
#   battery discharge), and import is a subset of what feeds the house. On a
#   live day — 35.98 kWh generated — the positive stack read 47.78 kWh. It is
#   now an honest supply-against-sinks balance: solar, battery discharge and
#   import above; home, battery charge and export below. Battery flow comes
#   from the SOC delta the history slots already carry, and the two sides now
#   close to within the round-trip loss (1.8% measured).
# * The Sankey lost energy silently. The SOLAR node was drawn at its full
#   figure while its ribbons summed to less, and the allocator could also
#   charge solar it never generated (`s2b = chg - g2b` was never capped at pv).
#   Allocation is now merit-order, the residual is an explicit LOSSES sink, and
#   both sides of the diagram total the same number.
# * A null SOC slot read as 0%, dropping the sparkline to the floor and putting
#   a false "low 0%" in the caption. Nulls now break the line.
# * The week-on-week bill billed £0.00 standing charge for any day with no
#   saved rate — 87 of the first 121 history rows — while recent days carried
#   ~62p, so the comparison reported a rise that was purely the age of the
#   data. It now falls back to the latest known charge and says how many days
#   that covers.
# * fmtKw printed 30 W as "0.03 kW"; it is adaptive now. The export rate
#   printed 12.5p as "13p" while the maths used 12.5.
# * The pack size was hardcoded at 35.04 kWh — this house's battery and
#   nobody else's. It now comes from battery.capacity_kwh (SigenEnergyManager
#   v5.52.0), with the constant only as a fallback.
# Shared arithmetic moved to energy-calc.js so both pages agree and so it can
# be tested: tests/test_energy_cost.mjs, 39 cases.
# The COST PAGE was rebuilt. It now carries the full token set and the
# component grammar from system-health.html; the hero splits the saving into
# avoided import and export earnings; each bill column shows how much of it
# the export covered; the month card has coverage and settled-day meters; the
# dual-axis 30-day chart became two single-axis charts (bars and running net
# never shared a comparable scale); and the tables gained sticky headers and
# the Elec bill column, so both roll-ups read as the identity the note states.
# Chart colours now come from the tokens rather than hardcoded hex, so they
# follow dark mode; the stacked series order and the light/dark bill-vs-export
# pair were both checked with a palette validator for colour-blind separation.
# DUPLICATION REMOVED: the Today's cost, Yesterday, Whole-house, Period totals
# and Calendar months cards have gone from the Energy page. The Cost page owns
# money now. The two pages had shown different figures under the same word
# "Net" — £1.49 energy-only against £0.16 after the full bill, on the same day.
#
# v2.45.2 (21-07-2026): shared plugin_utils.py refreshed to v1.3 — the
# estate-wide propagation of the four Appliance Monitor deep-review fixes.
# * install_timestamp_filter() is idempotent — a second call used to stack a
#   second filter, so every log line came out with two timestamps.
# * `import indigo` is soft, so the module imports outside the Indigo host and
#   can be exercised by offline tests.
# * A malformed log call keeps its arguments in the log instead of dropping
#   them, so a %-placeholder mismatch is visible.
# * New shared as_bool() — a pref re-serialised as the string "false" is
#   truthy, which is exactly the wrong answer.
#
# v2.45.1 (21-07-2026): LOG-LEVEL FIX. indigo.server.log(level=...) wants a Python
# logging INT — a STRING is silently ignored and the line logs as plain Info.
# The log() helper passed its level name straight through, so every WARNING and
# ERROR raised through it had been appearing as an ordinary Info line. Added
# _lvl() to map the name to a real level. Estate-wide sweep (38 files).
#
# v2.45.0 (19-07-2026): Energy page solar card — new "Expected total" figure
# (generated so far + forecast still to come), and reworded help text for
# "Remaining" now that SigenEnergyManager v5.49.0 publishes it bias-corrected
# and pro-rated. The card previously showed "38.3 kWh today, forecast 53,
# Remaining 25.3" — figures that could not be reconciled because Remaining came
# off the raw forecast buckets while the headline was bias-corrected. The
# numeric fix is in SEM; this is the page-side half, stating the projected
# end-of-day total rather than leaving the reader to add two figures that did
# not agree. Front-end only, no plugin logic change.
#
# v2.44.1 (18-07-2026): SigenProxy timeout 8s -> 12s. The energy tile
# occasionally dropped to a 502 when SigenEnergyManager's :8179 /api/status was
# mid EMS-control cycle (a ~8-10s serial modbus write burst on the same
# process). Diagnosed from logs — the ~17-in-10-days timeouts correlated to the
# second with SEM's "Setting ESS max discharge/charge limit". 12s rides it out.
# Cosmetic-only fix; the proxy already degraded gracefully.
#
# v2.44.0 (15-07-2026): Backup-runtime chip on the Live Power Flow card — how
# long the battery could power the house in a power cut at the current draw
# (stored energy above a 5% reserve floor / live house load). Front-end only.
#
# v2.26.0 (06-07-2026): EcoFlow removal (pages + demo-data only, no plugin
# logic change). The three EcoFlow power stations were retired, so their Indigo
# devices and variables were deleted. This strips the now-stale EcoFlow
# references from the pages — the Battery-fleet help text (energy.html), two
# code comments (energy.html, overview.html) and the three EcoFlow demo-data
# fixtures (demo-data/devices.json, 219 -> 216 devices). The Battery-fleet loop
# is generic (renders any device exposing battery_soc) and stays in place.
#
# v2.25.0 (03-07-2026): Apple/Safari design polish across ALL pages (pages-only
# release — no plugin logic change). A shared CSS block appended to every page
# (22 patched; demo.html has no <style>): frosted translucent top/bottom bars
# (backdrop-filter saturate+blur, iOS-nav-bar style, light + dark variants),
# hover-lift ONLY under @media (hover:hover) and (pointer:fine) so iPads/iPhones
# never get sticky hover, :focus-visible rings for Mac keyboard nav,
# prefers-reduced-motion support, and Safari/iOS fixes: min-height 100dvh (the
# iOS address-bar viewport), -webkit-text-size-adjust 100% (stops landscape
# text inflation), tap-highlight removal, font smoothing. Pages that pad for
# the notch also switch the PWA status bar to black-translucent so the frosted
# bar runs edge-to-edge in the installed app. Hub (index.html) hand-polished:
# dead CSS pruned (.top-jump/.back-link/.status-strip/.card-sigen — all from
# removed features), the 24-tile wall grouped under full-width House / Rooms /
# Tools labels (Weather/Presence/Alerts tiles moved up beside the feature
# pages; Ecowitt tile retitled "Weather"), tile grid minmax 120→132px, radii
# standardised at 14px, icon chips 44px. node --check clean (25 files, 30
# scripts); render-tests re-run green.
#
# v2.24.0 (03-07-2026): Debug-sweep hardening across the three new pages.
# System-health: battery census now covers the estate's THREE battery idioms
# via _battery_pct() — native batteryLevel, the z2m custom `battery` state
# (guarded >0: mains z2m report 0) and the boolean `batteryLow` alarm — the
# same coverage as overview.html's batteryInfo(); on first live run it caught
# Drive Left Motion 78 at 1% and an 87-day-quiet z2m sensor the native-only
# check missed; low-battery sort is None-safe (alarms first) and the page
# renders alarm entries as "LOW". Activity: the alert-collapse key normalises
# digits (re.sub(r"\d+","#")) so variants of one fault merge — a Modbus outage
# is now one "×N" row, not six; diary/alert times gain a day prefix ("Mon
# 14:01") when the log window spans days. Carbon: intensity cache is now
# (expiry, payload) with a 2-min NEGATIVE cache on failure so a down API isn't
# re-hit by every open tab's 30s poll, and a failed forecast leg degrades to
# current-reading-only instead of erroring the whole section.
#
# v2.23.0 (01-07-2026): Activity feed + automation health. New activity.html +
# hub "Activity" tile + new hidden IWS action `activityFeed`/`handleActivityFeed`.
# Turns the (very chatty) Indigo event log into three things: ALERTS (errors +
# warnings collapsed by source+message with a repeat count — 50 identical lines
# read as one "x50"), a curated HOUSE DIARY (lock/door via the readable Lock
# Manager line — the raw Z-Wave echo of the same event is dropped so a lock is
# one row; safety leak/smoke/alarm/power-cut; one "Started plugin" line per
# restart), and an AUTOMATION panel (schedules due next by nextExecution, minus
# the 0001 not-armed sentinel; the eventLogError error-watch triggers; disabled
# schedules/triggers so nothing's off by accident; and a per-person door-code
# roster parsed from the lock-code trigger names). SECURITY: a numeric label
# segment in a code-trigger name (a PIN reminder, e.g. "...(14) 1981") is
# stripped SERVER-SIDE so the digits never reach the browser. Verified live:
# endpoint 200, correctly surfaced an 11:01 network blip (EcoFlow DNS + Sigen
# Modbus disconnect + ESPHome/Tasmota MQTT) collapsed across the alerts.
#
# v2.22.0 (01-07-2026): Carbon-aware advisor. New carbon.html + hub "Carbon"
# tile + new hidden IWS action `carbonAdvisor`/`handleCarbonAdvisor`. Combines UK
# grid carbon intensity (free api.carbonintensity.org.uk, regional, no key —
# cached 10 min server-side) with the live solar surplus (read from the Sigen
# inverter device by its pvPowerWatts state, no hardcoded id) and the import
# tariff into a "good time to run a load" recommendation that ranks: soak up
# spare solar first (free AND zero-carbon), then a genuinely clean grid, then
# wait for the cleanest 16h window. Page shows an advice hero, a now-strip (grid
# gCO2 + index, solar export/SoC, rate), a 24h Chart.js intensity forecast with
# the cleanest window marked, and the current generation mix. Region configurable
# via new PluginConfig `carbonRegionId` (default 4 = North East England). On a
# flat Tracker tariff carbon + solar drive the timing, not price. Verified live:
# endpoint 200, advice "Run it now — exporting 4.0 kW of solar" at midday.
#
# v2.21.0 (30-06-2026): System Health page. New system-health.html + a hidden
# `systemHealth` endpoint (handleSystemHealth) computing everything server-side
# in one round-trip: Mac vitals (disk, RAM + swap pressure, load, uptime — via
# vm_stat/sysctl with ABSOLUTE paths since the plugin-host PATH omits /usr/sbin),
# the SQL history DB size + Logs breakdown (cached 5 min), and a device-health
# census (in error via errorState, low battery, quiet BATTERY devices, per-plugin
# counts with running state). Hub gains a "System" tile. Quiet detection is
# battery-only on purpose — lastChanged is not a liveness signal for mains/virtual
# devices (they showed bogus multi-year ages), so silence is flagged only where it
# means something. Live test caught Drive Left Motion (5% + 19 days quiet = dead).
#
# v2.20.0 (30-06-2026): Cost page. New dedicated cost.html — a whole-house
# financial view (today/yesterday/day-before bills with elec+gas+standing
# breakdown + a covered badge, a solar-benefit hero, and week/month/year
# totals), rendered from the bill-exact SigenEnergyManager economics via the
# existing sigenApi proxy. Hub gains a "Cost" tile. NB the orphaned
# elec_*/gas_* cost VARIABLES (stale, no active writer) are a separate fix —
# being revived in SigenEnergyManager next; the Cost page deliberately uses the
# live economics, not those variables.
#
# v2.19.0 (30-06-2026): Reading favourites. A hub favourite can now pin a
# device READING (voltage, temperature, SOC, watts…) as a read-only value tile,
# not just an on/off switch — Settings → Favourites gains a "reading" dropdown
# (populated from the chosen device's live states). saveDashboardsConfig now
# preserves the favourite's `state` key. Added the Qashqai 12V battery voltage
# as a reading favourite.
#
# v2.18.0 (30-06-2026): Hub money + house pulse. The hub energy glance now shows
# the money that matters — "Solar saved £X today", self-sufficiency %, the live
# import rate and what the battery's doing now (optimiser action) — fetched from
# the SigenEnergyManager API via the existing sigenApi proxy on a 30s cadence.
# A new house-pulse strip shows who's home (UniFi presence), zones calling for
# heat (RAMSES hvacHeaterIsOn), and low-battery / device-error counts. A
# power-cut / storm banner appears at the top of the hub only when the Sigen API
# reports an ongoing grid outage or storm export-hold. All guarded so the hub
# works unchanged if any source is absent.
#
# v2.17.0 (29-06-2026): WiFi tile shows much more of what UniFi knows (pairs with
# UniFiHealth v0.5.0). wifi.html gains an Internet card (ISP speedtest down/up,
# latency, public WAN IP, gateway cpu/mem), a Clients card (Wi-Fi-generation mix
# bar, legacy a/b/g warning, least-happy-clients list), and an RF-neighbourhood
# card (neighbour AP count per 2.4 GHz channel). Each AP tile gains a firmware
# line + condition badges (firmware update, uplink-underspeed e.g. a 2.5G AP at
# 1G, high memory, co-channel-neighbour congestion); the controller summary gains
# an "FW updates" metric. wifi-ap.html gains a "Hardware & uplink" card. All new
# UI is guarded so it no-ops cleanly against a pre-0.5.0 UniFiHealth.
#
# v2.16.1 (26-06-2026): Voltage on sensor tiles + Qashqai battery on the Garage
# page. renderEnvSensor (room.html) now uses a device's voltage/voltage.ui state
# as the tile's primary read-out when it reports no temperature, so a
# voltage-only monitor (e.g. a Shelly UNI ADC on a 12 V car battery) shows
# "12.60 V" instead of "—"; temp+humidity tiles are unchanged. prettyMotionName
# also strips a trailing IPv4 and a " Shelly UNI"/" Shelly N" tail so the tile
# label reads "Qashqai Battery" not the raw name. Install side: the Qashqai
# battery monitor is pinned into the Garage page's Sensors section via
# roomExtras.Garage.include.sensors in dashboards_config.json (the live store).
#
# v2.16.0 (24-06-2026): Energy page works AWAY FROM HOME (single dashboard).
# The energy/power-flow page fetched its Sigenergy data directly from the LAN-only
# :8179 port, so it only worked on the home WiFi. New hidden IWS endpoint
# `sigenApi` (handleSigenApi) server-side proxies the SigenEnergyManager :8179 data
# API (localhost, path allow-listed, no SSRF) so the page reaches it over the
# reflector, login-gated like every other page. energy.html now loads config.js +
# dashboards-auth.js and fetches via sigenFetch() through the proxy instead of :8179.
# Result: one dashboard (this plugin) that works on iPhone/iPad/MacBook at home AND
# away, for any browser holding the API key. The SigenEnergyManager :8179 page is now
# a localhost-only data backend (no longer a second user-facing dashboard).
#
# v2.15.1 (24-06-2026): Energy card "Lockout" chip fix. The Live Power Flow grid
# chip showed "Lockout" for the whole post-power-cut window even while the battery
# was exporting. It now keys off the Sigen API's power_cut.export_suppressed (added
# in SigenEnergyManager v5.34/5.35) rather than lockout_active (the time window), so
# a battery exporting above the SOC floor correctly shows "On Grid". NB this flow-card
# JS is DUPLICATED in SigenEnergyManager's web_dashboard.py (:8179) — keep both in sync.
#
# v2.15.0 (23-06-2026): PRESENCE WATCH — new "Presence" hub tile + presence.html
# showing per-night presence-sensor timelines for the Living Room (18:00-23:00)
# and Bedroom 1 (20:30-08:00) pairs: two sensor tracks plus a derived "Both" track
# that turns amber wherever the pair disagree (one unit dropping a still person),
# per-sensor stats, dropout callouts, a PIR movement strip, a bedroom sleep proxy
# and a 7-night pattern strip with date scrollback. Data is built by the standalone
# Presence_Watch.py script (SQL Logger history -> presence.json); the plugin ticks
# it every PRESENCE_REFRESH_SECONDS (300s) from runConcurrentThread so "tonight"
# fills in live. (Header/changelog had drifted — said 2.13.1 while 2.14.x shipped;
# realigned to 2.15.0 here.)
#
# v2.13.1 (19-06-2026): FIX — custom-link tiles never appeared. dashboards-auth.js
# rebuilds window.INDIGO_CONFIG from a field whitelist (baseURL/apiKey/sigenDeviceId/
# pinRequired/favourites) and was DROPPING customLinks before the hub render read it
# — the exact bug that hit favourites in v2.10.0. Added customLinks to that whitelist.
# (Hard-refresh the browser once to clear the cached dashboards-auth.js.)
#
# v2.13.0 (19-06-2026): CUSTOM LINKS — full-size hub tiles that open any URL in a
# new tab (e.g. the MQTT Explorer page, a Grafana board, a router admin page).
# Defined in Settings → Custom links (title + URL + optional description/emoji
# icon), stored in dashboards_config.json under "customLinks", published in the
# public config.js, and rendered on the hub before the utility cluster. URL scheme
# is validated server-side (http/https/relative only) AND re-checked in the hub
# render (textContent, no innerHTML) so a config value can't inject markup. The URL
# is NOT secret — never put a token in it; the target page handles its own auth.
# Also fixed the PLUGIN_VERSION constant, which had drifted to 2.9.0 (banner
# fallback only — Info.plist is the source of truth Indigo displays).
#
# v2.12.0 (16-06-2026): ACTIVE PAGE — now a full on/off control list. active.html no
# longer filters to currently-on devices; it ALWAYS lists every switchable device
# (Relay/Dimmer class, on OR off, disabled devices skipped), sorted strictly
# alphabetically so a device keeps its place when toggled (no jumping between on/off
# groups). This lets you switch back on something you turned off that's hidden from
# its room page (the HomePod Plug case). Category pills (All/Lights/Switches/Other)
# kept; the brief "On now / All" state toggle was dropped at CliveS's request (he
# always wants all). No name/type filtering per his choice, so internal devices incl.
# .RAMSES Gateway Plug appear and are tappable (he's aware). Pure page change.
#
# v2.11.0 (16-06-2026): HUB DECLUTTER + KIOSK REMOVED. Hub trimmed now Favourites
# sits on top: removed the live Heating glance card (the compact Heating nav tile
# on the first grid line stays) and the Battery/Solar/Grid/Devices-On status strip;
# moved Overview, Active, Scenes, Graphs and Settings to a utility cluster at the
# BOTTOM of the grid. KIOSK feature fully removed — kiosk.html deleted, the Settings
# Kiosk card, the config.js kiosk block, and the Fully-Kiosk screen wake/sleep driver
# (+ its deviceUpdated wake hook and runConcurrentThread idle-check) all stripped;
# DASHBOARDS_FULLY_PASSWORD import dropped. The delta-update ledger in deviceUpdated
# is untouched. No tablet was ever deployed, so the driver was dormant.
#
# v2.10.0 (16-06-2026): FAVOURITES — one-tap device/scene tiles pinned to the top
# of the hub (index.html), edited in Settings (server-stored in
# dashboards_config.json, published into config.js as just ids+labels). Fixes the
# "too many taps" gripe: your most-used controls are the first thing on the hub.
# Tapping a device toggles it (respects the per-tile PIN); tapping a scene runs
# its action group. New config key "favourites": [{type:"device"|"scene", id, label}].
#
# v2.9.0 (13-06-2026): Page Builder + page-authoring extras SHELVED. Removed the
# no-code builder (builder.html, custom.html, custom-render.js) + its "Page
# Builder" card and saved-page link injection on the main dashboard, AND the
# AI-route "Builder's Pack" (builders-pack.txt + the Settings authoring card +
# PAGE_AUTHORING.md + community-pages/). These dashboards are bespoke to this
# house — "just my desktop only" (CliveS) — so all the make-your-own-page surface
# for other users is gone. The catalog-driven smart room view (capabilities.js)
# stays. The _mirror_custom_pages plumbing is left in place as a harmless no-op.
#
# v2.8.0 (13-06-2026): friendlier builder + made the smart features SHAREABLE.
# builder.html: the device palette now uses a deliberate "+ add" button (no more
# accidental whole-row clicks), shows a calm "on page · N" indicator + count for
# placed devices (re-rendered on every change), suggests the tile type from the
# device's capabilities (matching the live room view), and flashes + scrolls to
# the newly-added tile so you see it land. Duplicates are allowed (count shown).
# SHAREABILITY: capabilities.js now derives the power/energy/battery annotations
# from each device's OWN live states (which every Indigo install provides), not
# from a catalog profile — so the smart room view + builder work for ANY user
# with no catalog and none of CliveS's plugins. The estate-specific catalog.json
# is no longer shipped in the plugin; a local catalog, if present, is an optional
# refinement only.
#
# v2.7.0 (13-06-2026): catalog-driven control selection in the live room view.
# room.html's renderLight now picks the control (dimmer vs relay) from the
# device capability catalog (capabilities.js + catalog.json, generated from the
# live estate by indigo-device-catalog) instead of a /Dimmer/.test(class) regex
# — declarative + future-proof for any new device type — and surfaces live watts
# on metering relays the catalog flags (e.g. Shelly PM plugs): "On · 740 W"
# instead of "On · relay". Falls back to the class regex until the catalog loads,
# so no visual regression. The throwaway catalog-demo proof page was removed.
#
# v2.4.1 (11-06-2026): Kiosk camera fix + cycle cost on appliance tiles.
# The kiosk loaded every rotation page at once, so the hub mosaic (4 MJPEG
# streams) plus the cameras grid (6) exhausted the browser's six-connection
# per-host limit and camera tiles starved. kiosk.html now loads on demand:
# the old page stays visible while the new one loads, the fade fires on its
# load event (2.5s fallback), and every other frame is parked on about:blank
# afterwards — only ONE page holds camera connections at any moment. Also:
# room.html appliance tiles now show the last-cycle cost (£) when
# ApplianceMonitor v1.3.0+ publishes lastCycleCostGbp.
#
# v2.4.0 (11-06-2026): GRAPHS — the house gets a memory. New history.html
# charts any recorded state of any device (device picker, recorded-state
# picker, 6h/24h/7d/30d ranges, avg line + min/max band via Chart.js, deep
# links ?device=&state=). Data comes from Indigo's stock SQL Logger database
# (Logs/indigo_history.sqlite — months of history already recorded) via the
# new historyQuery hidden action: strictly READ-ONLY (sqlite mode=ro), state
# names validated against the live table schema so no caller identifier
# reaches SQL, bucketed avg/min/max downsampling in-query. Guest devices get
# the same via /guest/history on :8177; demo mode synthesises plausible
# series so the hosted showcase has working graphs. New Graphs card on the
# hub.
#
# v2.3.0 (11-06-2026): DEMO MODE + GitHub Pages showcase. demo.html sets a
# session flag and every page then runs from canned fixtures in demo-data/
# (generated from the live system by tools/make_demo_fixtures.py, sanitised:
# private IPs → 192.0.2.x, MACs blanked, address/clientsJson/serial fields
# dropped) with a gentle state simulator — solar wobbles, battery drifts,
# motion flickers, and controls mutate the local fixture so toggles feel
# real. No server or credentials needed. tools/build_demo_site.sh builds the
# hosted showcase into docs/ (its config.js forces demo mode for every
# visitor) for GitHub Pages. _sync_pages_to_public now mirrors demo-data/ so
# the local demo works too.
#
# v2.2.0 (11-06-2026): KIOSK MODE. New kiosk.html — full-screen rotation
# through a configurable page list (cross-faded iframes, position dots),
# clock overlay, touch-pauses-resumes-after-60s, and night dimming driven by
# the Lux_Value Indigo variable. Display settings (pages/dwell/dim) live in
# the config store under "kiosk", are published public-safe in config.js, and
# are editable on the Settings page's new Kiosk card; ?pages=&dwell= URL
# overrides for ad-hoc use. FULLY KIOSK DRIVER (dormant until configured —
# awaiting tablet hardware): motion ON on any configured wake device fires
# screenOn via Fully Kiosk Browser PLUS's REST API (:2323), screenOff after
# the idle delay (checked in the 30s sweep). Commands run in daemon threads
# with a 30s throttle; the remote-admin password comes from
# IndigoSecrets.DASHBOARDS_FULLY_PASSWORD first, store fallback. Works for
# guest-paired tablets (the kiosk page uses whatever credential the browser
# holds). New Kiosk card on the hub.
#
# v2.1.0 (11-06-2026): GUEST TIER + PER-TILE PIN. Guest devices (wall tablets,
# visitors) pair via the new guest.html and hold ONLY a guest token — never
# the API key — so there is no control surface on them at all. Reads go via
# new /guest/* routes on the :8177 proxy (private source IPs only, never
# reflector-reachable): devices/device/<id>/variables are server-side IWS
# passthroughs with the real key held plugin-side, changedSince is served
# straight from the delta ledger. Guest token auto-generated into
# Preferences/Plugins/<id>/guest_token.txt (0600, outside the config store so
# it never flips legacy installs into store mode); "Show Guest Access Info"
# menu item logs the pairing URL + token. PER-TILE PIN: optional controlPin +
# pinRequired device list in the config store (Settings → Security card);
# protected devices prompt once per session, verified server-side via the new
# verifyPin endpoint so the PIN never reaches the browser. A speed bump for
# shared devices, not a security boundary.
#
# v2.0.0 (11-06-2026): SETTINGS EDITOR + CONFIG TAKEOVER. New settings.html —
# a forms-based editor for cameras (incl. main mosaic + swap-out), per-room
# extras (doors / appliances / TV groups / hide / include / sort order), the
# scenes hide-list (checkbox tree of every action group), and a raw-JSON
# escape hatch. Two new Bearer-gated endpoints: getDashboardsConfig (effective
# config + device index + full action-group list) and saveDashboardsConfig
# (validate → persist → apply live; camera changes flag a restart).
# CONFIG HOME CHANGE: once saved, Preferences/Plugins/<id>/dashboards_config.json
# is the SINGLE source of truth — the IndigoSecrets DASHBOARDS_* dicts and the
# PluginConfig fallbacks are only read when no store file exists (fresh
# installs behave exactly as before until first save). Also: the Sigenergy
# inverter device is auto-discovered (published as sigenDeviceId in config.js),
# killing the last hardcoded device ID in index.html/overview.html.
#
# v1.22.0 (11-06-2026): DELTA LIVE UPDATES + shared dashboard.js. The plugin
# now subscribes to all device changes (subscribeToChanges, with the pluginId
# loop guard) and keeps a change ledger; the new changedSince hidden endpoint
# returns the device IDs that changed since the client's last poll. The nine
# per-page inline IndigoAPI classes are replaced by ONE shared dashboard.js
# (superset of all variants) whose getDevices() polls the delta endpoint and
# refetches only the changed devices into a module-level cache — full list
# fetch only at boot, every 5 min as a safety resync, or when the endpoint
# says so. Page polling tightened from 5s to 3s (each poll is now one tiny
# POST + usually 0-2 single-device GETs instead of the full 191-device list).
# Falls back to plain full fetches if the endpoint is unavailable.
#
# v1.21.0 (11-06-2026): SCENES PAGE. New scenes.html shows every Indigo action
# group as a tappable button, grouped by Indigo folder, with run feedback.
# Plugin writes scenes.json (refreshed every 30s) from indigo.actionGroups +
# folder names; hide-list via IndigoSecrets.DASHBOARDS_HIDDEN_SCENES (or the
# new PluginConfig hiddenScenesJson fallback) — entries match a group name, a
# group id, or "folder:<Folder Name>". Execution goes browser → /v2/api/command
# (indigo.actionGroup.execute) with the paired key. New Scenes card on the hub.
#
# v1.20.1 (11-06-2026): Pairing made painless. (1) LAN/Tailscale AUTO-SEED —
# the MJPEG proxy gains a /bootstrap route (private source IPs only; the
# reflector never fronts :8177) and dashboards-auth.js fetches it on first
# visit, so devices at home or on the Tailnet never see the Connect form.
# Proxy now starts even with no cameras configured. (2) ONE-TIME SETUP LINKS —
# new menu item writes a high-entropy setup-<token>.json (+ QR svg via the
# qrcode package, new requirements.txt) into /public; new setup.html redeems
# it, stores the key, and calls the new burnSetupToken hidden action so the
# link is single-use; unredeemed links swept after 10 min and on restart.
# (3) ORIGIN-PREFERRING baseURL in dashboards-auth.js — pages are served by
# the same IWS as the API, so API calls now follow the page's own origin,
# which makes the dashboards work over the reflector once paired.
#
# v1.20.0 (11-06-2026): SECURITY — config.js no longer contains the Indigo
# API key. The /public/ namespace is served unauthenticated by IWS and is
# reachable over the Indigo reflector, so anything in config.js is readable
# from the public internet. config.js now carries only the server baseURL;
# new shared dashboards-auth.js merges the browser's locally-stored key
# (localStorage "indigo_config", written by the existing Connect form on
# index.html) into window.INDIGO_CONFIG so all pages work unchanged. Each
# browser is prompted once for the key. Menu item renamed to "Regenerate
# Config + Resync Pages" (it already re-syncs the HTML too).
#
# v1.19.7 (08-06-2026): Energy page rebuilt as a full native replica of the
# SigenEnergyManager mini-dash — animated flow SVG, battery SOC ring, tariff,
# forecast chart, today/yesterday economics, period totals, calendar months,
# export-sync table, and Chart.js history charts. Fetches from port 8179 /api/*.
# The old simplified 4-cell + iframe approach is gone entirely.
#
# v1.19.6 (07-06-2026): Heating page gains Boost and Force Heating control panel
# (6 buttons routed through Command Centre API to EvoHome plugin actions). Adds
# Actions.xml with evoHomeAction hidden endpoint (groundwork; active if re-installed).
# v1.19.5 (31-05-2026): WiFi AP detail page banner now shows worst-band
# utilisation instead of the audit-flag count (the flags stay listed in full in
# the Config audit card below).
# v1.19.4 (31-05-2026): WiFi AP tiles are now tappable — each opens a new
# wifi-ap.html detail page (two-column layout) showing per-band radio detail
# plus a "Connected devices" list of the clients on that AP (needs UniFiHealth
# >= 0.2.0, which publishes the per-AP clientsJson state).
# v1.17.1 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. Module-level log() helper bumped to ms.
# New "Toggle Timestamps in Log" menu item.

try:
    import indigo
except ImportError:
    pass

import json
import os
import re
import secrets as _stdlib_secrets   # stdlib token generator (NOT IndigoSecrets)
import shutil
import sys as _sys
import threading
import time
from datetime import datetime, timedelta, timezone

# Capture cwd at module load time — Indigo sets cwd to Contents/Server Plugin/
# at launch. Storing now is more robust than calling os.getcwd() later in case
# any subsequent code changes the working directory.
SERVER_PLUGIN_DIR = os.getcwd()
CONTENTS_DIR      = os.path.dirname(SERVER_PLUGIN_DIR)

_sys.path.insert(0, SERVER_PLUGIN_DIR)
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None
try:
    from plugin_utils import as_bool
except ImportError:
    # Indigo re-serialises a checkbox as the STRING "false" once the Configure
    # dialog has been saved, and bool("false") is True — so a bare bool() read
    # makes an unticked box read as ticked. Never coerce a checkbox with bool().
    def as_bool(value, default=False):
        if value is None or value == "":
            return default
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "off")
        return bool(value)
try:
    import history_db as _history_db
except ImportError:
    _history_db = None

_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import INDIGO_URL
except ImportError:
    INDIGO_URL = ""
try:
    from IndigoSecrets import INDIGO_API_KEY
except ImportError:
    INDIGO_API_KEY = ""
try:
    from IndigoSecrets import CLAUDEBRIDGE_BEARER_TOKEN
except ImportError:
    CLAUDEBRIDGE_BEARER_TOKEN = ""
try:
    from IndigoSecrets import DAHUA_USER
except ImportError:
    DAHUA_USER = ""
try:
    from IndigoSecrets import DAHUA_PASS
except ImportError:
    DAHUA_PASS = ""
try:
    from IndigoSecrets import SIGEN_DASHBOARD_URL
except ImportError:
    SIGEN_DASHBOARD_URL = ""
try:
    from IndigoSecrets import DASHBOARDS_CAMERAS  # JSON-string OR python list
except ImportError:
    DASHBOARDS_CAMERAS = ""
try:
    from IndigoSecrets import DASHBOARDS_ROOM_EXTRAS  # dict keyed by room name
except ImportError:
    DASHBOARDS_ROOM_EXTRAS = {}
try:
    from IndigoSecrets import DASHBOARDS_MAIN_CAMERAS  # list of camera host IPs
except ImportError:
    DASHBOARDS_MAIN_CAMERAS = []
try:
    # Scenes page hide-list — entries match an action group NAME, an action
    # group ID (as a string), or "folder:<Folder Name>" to hide a whole folder.
    from IndigoSecrets import DASHBOARDS_HIDDEN_SCENES  # JSON string OR python list
except ImportError:
    DASHBOARDS_HIDDEN_SCENES = []
# Weather extras (Sunset + today high/low on the hub Weather card).
# All three are optional — if absent the weather thread quietly skips.
try:
    from IndigoSecrets import OWM_API_KEY
except ImportError:
    OWM_API_KEY = ""
try:
    from IndigoSecrets import LATITUDE
except ImportError:
    LATITUDE = None
try:
    from IndigoSecrets import LONGITUDE
except ImportError:
    LONGITUDE = None
# Optional PostgreSQL history backend. Per-key try/except so a missing single
# key cannot blank the others, and PluginConfig remains the fallback for users
# without an IndigoSecrets.py at all.
try:
    from IndigoSecrets import HISTORY_PG_HOST
except ImportError:
    HISTORY_PG_HOST = ""
try:
    from IndigoSecrets import HISTORY_PG_PORT
except ImportError:
    HISTORY_PG_PORT = ""
try:
    from IndigoSecrets import HISTORY_PG_USER
except ImportError:
    HISTORY_PG_USER = ""
try:
    from IndigoSecrets import HISTORY_PG_PASSWORD
except ImportError:
    HISTORY_PG_PASSWORD = ""
try:
    from IndigoSecrets import HISTORY_PG_DATABASE
except ImportError:
    HISTORY_PG_DATABASE = ""


# ============================================================
# Constants
# ============================================================

PLUGIN_ID         = "com.clives.indigoplugin.dashboards"
PLUGIN_VERSION    = "3.13.1"
# Pages are mirrored into Web Assets/public/dashboards/ so IWS serves them
# WITHOUT HTTP Basic Auth. Indigo only treats the global /public/ namespace
# as anonymous — per-plugin `public/` subfolders still require auth.
PUBLIC_SUBDIR     = "dashboards"
INDEX_PATH        = f"/public/{PUBLIC_SUBDIR}/index.html"

# Source folder inside the plugin bundle that holds the HTML pages we mirror.
PAGES_SOURCE_DIR  = os.path.join(CONTENTS_DIR, "Resources", "static", "pages")

# Colour presets (v2.94.0). These used to live in room.html, where applying one
# meant the BROWSER firing three ordered commands — turn on, set brightness, set
# colour — each wrapped in an empty catch. A phone that locked, backgrounded the
# tab or lost signal between them left the lamp half-set, and said nothing. The
# sequence now runs on the server behind ONE request (the applyColour endpoint),
# so the table has to live here too: two copies of it would drift the moment one
# was edited. The page draws its buttons from `colourPresets` in config.js.
#
# mode is presentational — the page uses it to decide which swatch to draw. What
# the server acts on is which of the level keys are present.
COLOUR_PRESETS = {
    "warm":  {"label": "Warm white", "icon": "cloudsun", "mode": "white",
              "whiteTemperature": 2700, "brightness": 100},
    "movie": {"label": "Movie", "icon": "film", "mode": "color",
              "redLevel": 100, "greenLevel": 35, "blueLevel": 8, "brightness": 18},
}
# The colour keys setColorLevels accepts, and the range each is valid over. A
# request naming anything else, or a value outside the range, is REFUSED rather
# than clamped: a clamp turns a caller's mistake into a light that silently did
# something other than what was asked, which is the harder fault to spot.
_COLOUR_LEVEL_KEYS = {
    "redLevel":         (0, 100),
    "greenLevel":       (0, 100),
    "blueLevel":        (0, 100),
    "whiteLevel":       (0, 100),
    "whiteLevel2":      (0, 100),
    "whiteTemperature": (1000, 10000),
}

# Cameras configuration is now user-supplied via:
#   1. IndigoSecrets.DASHBOARDS_CAMERAS (JSON string or list of dicts), or
#   2. PluginConfig "camerasJson" textfield (JSON list).
# Each entry must have keys: host, name, vendor ("dahua" or "hikvision").
# When empty, the camera grid / MJPEG proxy / go2rtc are simply disabled.
#
# Order matters: the first entry is the default "focused" tile on
# cameras.html — it appears large at the top with the rest as a row of
# smaller tiles underneath. By default the LAST entry in the list is the
# "swap-out" cam — the one bumped to still when the user peeks at a tail-of-
# list camera. Override with PluginConfig "swapOutHost" if a different cam
# is better to drop from the live pool.
CAMERA_PORT          = 80                                  # snapshot HTTP port (Dahua & Hikvision)
CAMERA_POLL_SECONDS  = 2.0                                 # snapshot poll interval per camera (drives all thumbnail tiles, including cameras with live viewers)
CAMERA_POLL_MAX_WORKERS = 9                                # concurrent snapshot fetches. Serially, nine cameras
                                                           # overran the 2s interval and each tile only refreshed
                                                           # every ~4.1s (measured); these are all network waits,
                                                           # so overlapping them costs nothing.
LIVE_POOL_SIZE       = 6                                   # how many cameras run live MJPEG on cameras.html. Browsers cap HTTP/1.1 connections per origin at ~6, so don't exceed that.
CAMERA_HTTP_TIMEOUT  = 15.0                                # per-snapshot timeout (4K snapshots can take 5-10s on busy cams)
PRESENCE_REFRESH_SECONDS = 300                             # how often to re-run Presence_Watch.py (refreshes presence.json for the Presence tile — live-tonight needs periodic rebuilds)
LOG_WATCH_REFRESH_SECONDS = 3600                           # how often to re-run Log_Error_Watch.py (hourly by design — it dedupes against its own state file, so a double-run is harmless)
FP300_WATCH_REFRESH_SECONDS = 3600                         # how often to re-run FP300_Config_Watch.py (hourly — it only writes when a sensor has drifted AND is awake, so most ticks do nothing)
REFLECTOR_BW_REFRESH_SECONDS = 300                         # how often to sample the reflector tunnel's byte counters (5 min — the counters are cumulative, so the cadence only sets how finely an hour can be attributed, and each sample costs two short subprocess calls)
def normalise_deadline(text):
    """"HH:MM" -> "HH:MM" zero-padded, "" -> "", anything else -> None.

    An Indigo variable takes any string it is given, so junk written here would make
    Appliance_Scheduler.py warn and fall back every fifteen minutes for ever. Refuse at the
    door instead, and say what a good value looks like.
    """
    text = str(text or "").strip()
    if not text:
        return ""                       # empty is legitimate: it means "use the default"
    if text.count(":") != 1:
        return None
    hh, _, mm = text.partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        return None
    hh, mm = int(hh), int(mm)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def normalise_appliance_key(text):
    """A scheduler appliance key, or None.

    Lower case, digits and single underscores only. It is interpolated into an Indigo
    variable name, and Indigo variable names may not contain spaces — so anything else is
    refused rather than quietly creating a variable no one can read back.
    """
    text = str(text or "").strip().lower()
    if not text or len(text) > 60:
        return None
    if not all(c.isalnum() or c == "_" for c in text):
        return None
    if text.startswith("_") or text.endswith("_") or "__" in text:
        return None
    if not text[0].isalpha():
        return None
    return text


LAUNDRY_REFRESH_SECONDS = 900                              # how often to re-run Appliance_Scheduler.py (15 min — the inputs are an hourly solar forecast, a half-hourly price and a battery that moves slowly, so a faster cadence would recompute the same answer; the page polls the file it writes, never the plugin)
NIGHT_SWEEP_REFRESH_SECONDS = 120                          # how often to re-run Night_Lights_Sweep.py (2 min — its own gap guard discards every streak if a run is more than 10 min after the last, so a slower cadence would stop it acting at all)

# Upper bound on one plausible PV string's instantaneous watts. Not a display
# clamp — a filter on what the SQL Logger already holds. SigenEnergyManager
# read the inverter's per-string CURRENT as unsigned until v5.84.0, so a
# string at its dawn or dusk zero-crossing logged 655.3 A (65534 raw = -2 as
# S16) and V*I put up to 219,667 W on a 4.275 kWp string. That is in this
# database on 21 days from 13-08-2026 and cannot be undone — rows are never
# rewritten — so the READER has to reject it. One such sample lifted an hour's
# mean by ~2 kW and took one day's South total from 9.8 kWh to 219.8 kWh.
#
# 15 kW sits in a measured gap, not a guessed one: across 383k logged rows the
# largest GENUINE per-string sample is 4,705 W and the smallest WRAPPED one is
# 32,832 W (the dusk figure falls with the string voltage, so a cap set by the
# 200 kW headline would miss the low-voltage end — 45,416 W at 69 V did slip a
# 50 kW cap). Filtering on watts rather than the current also matters: 97 of
# the bad rows have no current logged beside them, the SQL Logger writing only
# what changed. No residential string reaches 15 kW.
PV_STRING_SANE_MAX_W = 15000

# Liveness stamp (v2.70.0). A /message/ request in flight when this plugin
# host stops wedges the ENTIRE IWS event loop for a fixed ~298 s (measured
# 6/6 across 11 restarts) — so the pages must stop calling /message/ BEFORE
# the host dies. The plugin heartbeats a tiny JSON stamp into the anonymous
# /public dir (IWS serves it itself, no plugin IPC, so it cannot wedge);
# dashboards-gate.js reads it and gates every /message/ poller. state flips
# to "stopping" in stopConcurrentThread — the earliest signal Indigo gives
# us, seconds before shutdown()'s 20-30 s worst-case teardown begins.
# Contains nothing sensitive: epochs and a state word only.
STAMP_FILENAME          = "changed.stamp"
STAMP_PERIOD_SECONDS    = 2.0     # heartbeat cadence (matches the camera poller)
STAMP_CHANGE_WRITE_GAP  = 1.0     # min gap between deviceUpdated-driven writes
# How long shutdown() holds the host ALIVE after the sentinel, before any
# teardown. The gate memoises its stamp verdict for STAMP_PERIOD_SECONDS, so
# a poll can fire on a verdict up to ~2 s stale — and a fast teardown
# (measured: stop to new boot in TWO seconds on this Mac) can kill the host
# inside that window, stranding exactly the request the stamp exists to
# prevent (live-hit on the third verification restart, 31-Jul-2026). 4 s
# covers the stale-verdict window plus the request itself, with margin.
STAMP_QUIESCE_SECONDS   = 4.0

# Populated at __init__ from IndigoSecrets / PluginConfig. Keep as
# module-level state so the many existing reference sites below don't need
# rewriting; __init__ overwrites these in place.
CAMERAS       = []
SWAP_OUT_HOST = ""


def _safe_int_list(values):
    """Coerce a list to ints, dropping anything unconvertible. The old inline
    guard (`lstrip("-").isdigit()`) passed "--5" and int() then raised, 500ing
    the whole config save."""
    out = []
    for x in values or []:
        try:
            out.append(int(str(x).strip()))
        except (ValueError, TypeError):
            pass
    return out


def _parse_cameras(value):
    """Parse camera config — accepts a JSON string, a Python list, or empty.

    Required keys per entry: ``host``, ``name``, ``vendor`` (in {"dahua",
    "hikvision"}).
    Optional: ``room`` — the dashboard room(s) this cam should also appear
    on. Either a string (``"Garage"``) for a single room or a list
    (``["Garage", "Hall"]``) so one camera can surface on multiple room
    pages. Each room name must match an entry in ROOM_FOLDERS to actually
    show; unrecognised names are silently ignored by the room template (the
    camera still appears on the main cameras page regardless).
    Invalid entries are silently dropped.
    """
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            # A typo in DASHBOARDS_CAMERAS / camerasJson used to read as
            # "0 cameras configured" with no clue why.
            log(f"[Cameras] camera config is not valid JSON ({exc}) — "
                f"no cameras will be configured until it is fixed", level="ERROR")
            return []
    if not isinstance(value, list):
        return []
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        if not all(k in entry for k in ("host", "name", "vendor")):
            continue
        # Preserve room as string OR list of strings. Downstream code in
        # _build_rooms_json normalises both to a list before lookup.
        raw_room = entry.get("room", "")
        if isinstance(raw_room, (list, tuple)):
            room_val = [str(x).strip() for x in raw_room if str(x).strip()]
        else:
            room_val = str(raw_room).strip()
        # `stream` picks which RTSP path the go2rtc config uses for this
        # camera's source — "main" or "sub2". Default is sub2 (see
        # CAMERA_DEFAULT_STREAM). Anything unknown silently falls back to
        # the default so a typo doesn't take a camera offline.
        stream = str(entry.get("stream", CAMERA_DEFAULT_STREAM)).lower().strip()
        if stream not in ("main", "sub2"):
            stream = CAMERA_DEFAULT_STREAM
        cleaned.append({
            "host":   str(entry["host"]),
            "name":   str(entry["name"]),
            "vendor": str(entry["vendor"]).lower(),
            "room":   room_val,
            "stream": stream,
        })
    return cleaned


def _detect_lan_ip():
    """Best-effort LAN IP detection (used in go2rtc WebRTC candidates +
    the startup log line that prints the go2rtc API URL).  Returns the
    first non-loopback IPv4 the host advertises, or '127.0.0.1' on
    failure.  No outbound connection is actually made."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 198.51.100.1 is a TEST-NET-2 address — never routes anywhere,
            # but the kernel picks the correct source interface for it.
            s.connect(("198.51.100.1", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"

# Vendor URL templates: {host} {user} {pwd} are substituted. Each vendor has
# both a mainstream URL (highest quality, big bandwidth) and a substream 2 URL
# (typically 720p / ~512 kbps — plenty for an at-a-glance dashboard mosaic).
# Per-camera `stream` field in DASHBOARDS_CAMERAS picks which one go2rtc uses
# as the ffmpeg source. Default is sub2 — see CAMERA_DEFAULT_STREAM below.
#
# Stream conventions per vendor:
#   Dahua     — subtype=0 main, subtype=1 sub1 (unused), subtype=2 sub2
#   Hikvision — Channels/101 main (ch 1 stream 01), Channels/102 sub2
#
# Why sub2 by default: the dashboard is a "is anything moving?" surface, not
# a recording archive. Mainstream lives in the Synology NVR at 4K for the
# actual footage. Using sub2 here halves ffmpeg CPU and cuts LAN bandwidth
# from ~50 Mbps to ~5 Mbps across the 9 cameras.
VENDOR_URLS = {
    "dahua": {
        "snapshot_path": "/cgi-bin/snapshot.cgi",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/cam/realmonitor?channel=1&subtype=0",
        "rtsp_sub2":     "rtsp://{user}:{pwd}@{host}:554/cam/realmonitor?channel=1&subtype=2",
    },
    "hikvision": {
        "snapshot_path": "/ISAPI/Streaming/channels/101/picture",
        "rtsp_main":     "rtsp://{user}:{pwd}@{host}:554/Streaming/Channels/101",
        "rtsp_sub2":     "rtsp://{user}:{pwd}@{host}:554/Streaming/Channels/102",
    },
}

# Default stream when a DASHBOARDS_CAMERAS entry omits `stream` — sub2 saves
# CPU + bandwidth and quality is plenty for tile-sized viewing. Override per
# camera by setting `"stream": "main"` in IndigoSecrets.
CAMERA_DEFAULT_STREAM = "sub2"

# MJPEG proxy: tiny HTTP server bound to this port that streams the camera's
# multipart/x-mixed-replace response straight to the browser. Same trusted-LAN
# threat model as /public/dashboards/ — no auth on the proxy itself.
MJPEG_PROXY_PORT     = 8177
MJPEG_UPSTREAM_TIMEOUT = 8.0

# go2rtc — WebRTC/low-latency video for live.html. The plugin generates a
# config.yaml at startup (RTSP URLs include DAHUA_USER/DAHUA_PASS) and runs
# go2rtc as a subprocess. Bind addresses:
#   :1984 — HTTP API + WebRTC signaling (used by the browser)
#   :8555 — WebRTC media (TCP, served back to the browser)
GO2RTC_BIN           = os.path.expanduser("~/bin/go2rtc")
GO2RTC_API_PORT      = 1984
# Snapshots are only ever shown in a TILE — the hub's camera strip at ~215px
# and the cameras grid at about the same. They were being fetched at the
# camera's full resolution: 1280x720, 124-173 KB, for a 200px box. go2rtc will
# scale the frame for us (`&width=`), which costs it nothing extra because it
# is decoding the frame either way.
#   1280 -> 124 KB      640 -> 38 KB      480 -> 26 KB      320 -> 11 KB
# 640 keeps a focused tile looking respectable when it falls back to stills on
# a slow link, and is still a third of what was being sent.
CAMERA_SNAPSHOT_WIDTH = 640

# A SECOND, smaller copy of each snapshot, for the eight thumbnails in the grid.
# They are drawn about 300 px wide on a desktop and less than that on a phone, so
# sending them 640 px of picture was paying for detail no one can see. MEASURED
# across all nine cameras: 640 -> 33.2 KB each, 320 -> 12.3 KB each, so a grid
# pass drops from 299 KB to 111 KB. The focused tile keeps the full-size picture.
#
# The resize happens HERE, from the frame we already fetched, rather than by
# asking go2rtc for a second one at a different width. That was the obvious
# approach and it is wrong: eighteen frame requests a pass made go2rtc answer
# HTTP 500, because each camera was being asked to decode twice in quick
# succession. Resizing a frame already in memory costs about a millisecond and
# leaves the load on the cameras exactly as it was.
CAMERA_THUMB_WIDTH   = 320
# Pause before the single retry of a failed snapshot. 250 ms was measured, not
# guessed: over 270 requests, 4 came back HTTP 500 and all 4 succeeded at this
# delay, none needing a second attempt.
CAMERA_RETRY_DELAY   = 0.25
CAMERA_THUMB_QUALITY = 72              # JPEG quality for the shrunk copy

GO2RTC_WEBRTC_PORT   = 8555
GO2RTC_RTSP_PORT     = 8554            # exposed for completeness; not used by the page


# ============================================================
# Helpers
# ============================================================

import logging


_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


# The module log() helper writes STRAIGHT to indigo.server.log, deliberately:
# that call bypasses the logging handlers altogether, so a WARNING or an ERROR
# reaches the shared event log whatever the Log Level pref is set to, and
# Log_Error_Watch.py reads the event log and nothing else.
#
# The cost of bypassing the handlers is that none of those 56 fault lines ever
# reached this plugin's OWN log file, while the routine narration moved there
# on 06-09-2026 - so diagnosing a fault meant reading two files side by side
# and interleaving them by hand. _FILE_MIRROR writes the same record a second
# time through the plugin's file handler alone, so one file holds the fault
# and the plumbing around it.
_FILE_MIRROR = None


def _install_file_mirror(file_handler):
    """Point the module log() helper at this plugin's own log file as well.

    A CHILD of the "Plugin" logger with propagate=False, carrying the file
    handler and nothing else. Both halves of that matter: propagation would
    take the record up to indigo_log_handler and write the event-log line a
    SECOND time, and the file handler is the same object self.logger writes
    through, so a mirrored fault interleaves with the surrounding _activity()
    lines in one file in the order they happened.

    plugin_base builds plugin_file_handler in its own __init__, so call this
    after super().__init__(). A host that could not create the log directory
    gets a StreamHandler instead and this still works; a host with no handler
    at all leaves the mirror off and log() behaves exactly as it did before.

    Mirrored lines are recognisable in plugin.log: the file handler's format
    carries the logger name, so they read "Plugin.eventlog.log:" where a
    self.logger line reads "Plugin.<method>:". They also lack the
    "[HH:MM:SS.mmm] " prefix, because plugin_utils attaches that filter to the
    "Plugin" logger itself and a child logger's records bypass it - no loss,
    since the file handler stamps its own timestamp on every line anyway.
    """
    global _FILE_MIRROR
    mirror = logging.getLogger("Plugin.eventlog")
    mirror.propagate = False
    # Replace, never append: a second __init__ in one process (which is what a
    # test run does) would otherwise stack the handler and write every mirrored
    # line twice. Detached in the no-handler case too, so a stale handler from
    # an earlier install cannot outlive it.
    for existing in list(mirror.handlers):
        mirror.removeHandler(existing)
    if file_handler is None:
        _FILE_MIRROR = None
        return None
    mirror.addHandler(file_handler)
    # The handler does the filtering, as it does for self.logger - see
    # _apply_log_level for why the logger is left wide open.
    mirror.setLevel(logging.DEBUG)
    _FILE_MIRROR = mirror
    return mirror


def log(message, level="INFO"):
    lvl = _lvl(level)
    # Event log FIRST, and unconditionally. If the mirror below ever throws,
    # the line that something is watching has already gone out.
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}", level=lvl)
    if _FILE_MIRROR is not None:
        try:
            # The RAW message: the file handler stamps its own asctime, so
            # mirroring the event-log copy would date every line twice.
            _FILE_MIRROR.log(lvl, message)
        except Exception:
            # A logging failure must never take its caller down.
            pass


# ============================================================
# Plugin class
# ============================================================

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.timestamp_enabled = as_bool(pluginPrefs.get("timestampEnabled"), True)
        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Everything the module log() helper sends to the shared event log is
        # copied into this plugin's own log file too, so one file holds a fault
        # and the routine narration around it. See _install_file_mirror.
        _install_file_mirror(getattr(self, "plugin_file_handler", None))

        # Credentials: IndigoSecrets.py first, PluginConfig fields as the
        # documented fallback (v2.36.0 — the fields exist now; the intro label
        # used to promise fallbacks that weren't there, stranding GUI-only users).
        self.api_key     = (INDIGO_API_KEY or CLAUDEBRIDGE_BEARER_TOKEN
                            or pluginPrefs.get("indigoApiKey", "")).strip()
        # Blank means the local server (v2.95.2) — the Configure dialog has
        # promised that since v2.0 and nothing implemented it: a blank URL
        # 502'd every guest tile and failed Test Dashboards Setup.
        self.api_url     = ((INDIGO_URL or pluginPrefs.get("indigoUrl", "")).strip()
                            or "http://127.0.0.1:8176")
        self.cam_user    = (DAHUA_USER or pluginPrefs.get("dahuaUser", "")).strip()
        self.cam_pass    = (DAHUA_PASS or pluginPrefs.get("dahuaPass", "")).strip()
        # Log level (v2.36.0 — the PluginConfig field existed but was never
        # applied). Guarded coerce; bad/blank value falls back to INFO.
        self._apply_log_level(pluginPrefs.get("logLevel", 20))

        # Sigen dashboard link target — empty means the "Open Legacy Sigen
        # Dashboard" menu item is silently disabled. IndigoSecrets first,
        # PluginConfig fallback.
        self.sigen_legacy_url = (SIGEN_DASHBOARD_URL or pluginPrefs.get("sigenLegacyUrl", "")).strip()

        # v2.0.0 CONFIG TAKEOVER: if dashboards_config.json exists (written by
        # the settings.html editor), it is the SINGLE source of truth for
        # cameras / main mosaic / swap-out / room extras / hidden scenes.
        # Without it, the legacy IndigoSecrets + PluginConfig path applies
        # unchanged — fresh installs work exactly as before until first save.
        self.cfg_store  = self._load_config_store()
        self.cfg_loaded = bool(self.cfg_store)

        # Cameras — populate the module-level state so all existing reference
        # sites (go2rtc config, snapshot pollers, MJPEG proxy, etc.) see the
        # configured list.
        global CAMERAS, SWAP_OUT_HOST
        if self.cfg_loaded:
            cam_source = self.cfg_store.get("cameras") or []
        else:
            cam_source = DASHBOARDS_CAMERAS or pluginPrefs.get("camerasJson", "")
        CAMERAS    = _parse_cameras(cam_source)
        # Default swap-out = last entry in the list (the cam most likely to be
        # safe to drop from the live MJPEG pool). Override via the editor or
        # PluginConfig "swapOutHost" if a different cam is the better candidate.
        if self.cfg_loaded:
            swap_pref = (self.cfg_store.get("swapOutHost") or "").strip()
        else:
            swap_pref = (pluginPrefs.get("swapOutHost", "") or "").strip()
        SWAP_OUT_HOST = swap_pref if swap_pref else (CAMERAS[-1]["host"] if CAMERAS else "")

        # Main-mosaic cameras + per-room extras: store first, secrets fallback.
        if self.cfg_loaded:
            self.main_cameras = list(self.cfg_store.get("mainCameras") or [])
            extras = self.cfg_store.get("roomExtras")
        else:
            self.main_cameras = list(DASHBOARDS_MAIN_CAMERAS or [])
            extras = DASHBOARDS_ROOM_EXTRAS
        self.room_extras = extras if isinstance(extras, dict) else {}

        # Guest tier (v2.1.0): read-only token + per-tile PIN policy.
        self.guest_token  = self._load_guest_token()
        self.control_pin  = str(self.cfg_store.get("controlPin") or "") if self.cfg_loaded else ""
        self.pin_required = list(self.cfg_store.get("pinRequired") or []) if self.cfg_loaded else []
        # Bootstrap key auto-seed (v2.36.0). Default True = the LAN convenience
        # that seeds the API key to any private-source browser on first visit.
        # A deployment that runs guest-tier devices can set this False to make
        # the guest boundary real — /bootstrap then 403s and trusted devices
        # pair via the one-time setup links (menu: Generate One-Time Setup Link)
        # instead. Default preserves existing behaviour; nobody's setup breaks.
        self.bootstrap_key_seed = as_bool(pluginPrefs.get("bootstrapKeySeed"), True)

        # Routine activity narration (06-09-2026). OFF means the file copies,
        # page syncs and poller/proxy/go2rtc start-stop lines are written at
        # Debug, which normally means this plugin's OWN log only - normally,
        # because the Log Level pref sets the event log's floor and at Debug it
        # lets them through regardless. This checkbox is one of the two
        # switches on them, not the only one; see _apply_log_level. They are
        # the lines that grow: measured over
        # 31-Aug to 05-Sep-2026 the plugin wrote 614 Info lines to the shared
        # Indigo event log and about 490 of them were these, narrating work
        # Indigo already brackets with its own "Starting plugin" / "Stopped
        # plugin" pair. Thirteen is the high mark, not the constant: counted
        # off the dated Events.txt files on 06-09-2026, the six most recent
        # restarts produced 13, 13, 13, 10, 11 and 11 Dashboards Info lines,
        # because several of them (the Domio copy, the stale-file removal, the
        # go2rtc asset mirror) only speak when they had something to do.
        # Warnings and errors
        # are NEVER routed through this - Log_Error_Watch.py reads the event
        # log and nothing else, so a fault that only lands in a plugin file
        # is a fault nobody is watching.
        self.log_activity = as_bool(pluginPrefs.get("logActivityToEventLog"), False)

        # Favourites (v2.10.0): one-tap device/scene tiles pinned to the top of
        # the hub. Edited in Settings, stored in dashboards_config.json, and
        # published into config.js (just ids + labels — not secret) so the hub
        # reads them straight from window.INDIGO_CONFIG with no extra fetch.
        self.favourites = list(self.cfg_store.get("favourites") or []) if self.cfg_loaded else []

        # Custom links (v2.x): full-size hub tiles that open an arbitrary URL in a
        # new tab — e.g. the MQTT Explorer page, a Grafana board, a router admin
        # page. {title, url, desc?, icon?}. Edited in Settings, stored in
        # dashboards_config.json, published into the public config.js. The URL is
        # NOT secret (just a link); never put a token in it — the target page
        # handles its own auth.
        self.custom_links = list(self.cfg_store.get("customLinks") or []) if self.cfg_loaded else []

        # LAN IP — used by the go2rtc WebRTC config and the startup log line.
        # Detect once at __init__; the hostname doesn't change at runtime.
        self.lan_ip = _detect_lan_ip()


        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    def _secrets_state(self):
        # v1.20.0: the key is no longer published in config.js regardless of
        # where it lives — browsers prompt once and keep it in localStorage.
        # This string is informational only (Show Plugin Info / config.js note).
        if INDIGO_API_KEY:
            return "INDIGO_API_KEY in IndigoSecrets (not published — browser prompts)"
        if CLAUDEBRIDGE_BEARER_TOKEN:
            return "CLAUDEBRIDGE_BEARER_TOKEN in IndigoSecrets (not published — browser prompts)"
        return "no key in IndigoSecrets — browser prompts"

    def _camera_state(self):
        if self.cam_user and self.cam_pass:
            return f"{len(CAMERAS)} configured (DAHUA_USER/DAHUA_PASS from IndigoSecrets)"
        return f"{len(CAMERAS)} configured but DAHUA_USER/DAHUA_PASS missing"

    # --------------------------------------------------------
    # Config store (v2.0.0) — dashboards_config.json
    # --------------------------------------------------------

    def _guest_token_path(self):
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "guest_token.txt")

    def _load_guest_token(self):
        """Guest token (v2.1.0) — grants READ-ONLY access via the :8177 proxy.
        Auto-generated on first use, persisted in the per-plugin Preferences
        folder (0600), deliberately OUTSIDE dashboards_config.json so creating
        it never flips a legacy install into store mode."""
        path = self._guest_token_path()
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    return tok
        except Exception as exc:
            log(f"[Guest] Could not read guest token ({exc})", level="WARNING")
        tok = _stdlib_secrets.token_urlsafe(18)
        try:
            # Created 0600, no open-then-chmod window (v2.95.2).
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(tok)
            log("[Guest] Generated new guest access token")
        except Exception as exc:
            log(f"[Guest] Could not persist guest token ({exc})", level="WARNING")
        return tok

    def _config_store_path(self):
        """Plugin-owned config file. Lives in the per-plugin Preferences
        folder (NOT /public — no need to publish it), survives upgrades."""
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "dashboards_config.json")

    def _load_config_store(self):
        """Read dashboards_config.json. Returns {} when absent/invalid —
        callers treat that as 'legacy mode' (IndigoSecrets + PluginConfig)."""
        try:
            path = self._config_store_path()
            if not os.path.isfile(path):
                return {}
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            log(f"[Config] Could not read dashboards_config.json ({exc}) — "
                "falling back to IndigoSecrets/PluginConfig", level="WARNING")
            return {}

    def _save_config_store(self, data):
        """Atomically persist the editor's config. Raises on failure.
        Keeps a one-deep .bak of the PREVIOUS good config first, so a bad save
        (e.g. an empty form harvested after a failed load — the settings page
        guards against this client-side too) is always recoverable by hand."""
        path = self._config_store_path()
        try:
            if os.path.isfile(path):
                import shutil
                shutil.copy2(path, path + ".bak")
                os.chmod(path + ".bak", 0o600)
        except Exception as exc:
            log(f"[Config] could not back up dashboards_config.json: {exc}", level="WARNING")
        data = dict(data)
        data["_savedAt"] = time.time()
        tmp  = path + ".tmp"
        # 0600 (v2.95.2): the store carries the control PIN in clear, and it
        # was written under the default umask — 0644, plus every .bak beside it.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return data

    def _effective_config(self):
        """The config as currently in force, regardless of where it came
        from — exactly what the settings editor should show."""
        # v3.12.0: cameras and the swap-out host as SAVED, not as running.
        # Module CAMERAS / SWAP_OUT_HOST only change at restart, so after a
        # save this handed the editor the PRE-save list: reopen Settings, save
        # again, and the camera just added was silently deleted. Once the
        # store is in force it is the truth; the streams catch up at the
        # restart the save reply asks for.
        store = self._load_config_store() if getattr(self, "cfg_loaded", False) else {}
        if "cameras" in store:
            cams = _parse_cameras(store.get("cameras") or [])
        else:
            cams = [dict(c) for c in CAMERAS]
        swap = (store.get("swapOutHost") or "") if "swapOutHost" in store else SWAP_OUT_HOST
        out = {
            "cameras":      cams,
            "mainCameras":  list(self.main_cameras),
            "swapOutHost":  swap,
            "roomExtras":   self.room_extras,
            "hiddenScenes": sorted(self._hidden_scenes()),
            "controlPin":   self.control_pin,
            "pinRequired":  list(self.pin_required),
            "favourites":   [dict(f) for f in self.favourites],
            "customLinks":  [dict(l) for l in self.custom_links],
        }
        # Round-trip safety: any stored key this build does not know — the
        # raw-JSON hatch, a newer page, a future version — passes through
        # unchanged. Without this, Settings loads a stripped view and the
        # next Save silently deletes every unknown key (the recurring
        # whitelist trap, this time on the LOAD side).
        try:
            for k, v in self._load_config_store().items():
                if k not in out and not str(k).startswith("_"):
                    out[k] = v
        except Exception:
            pass
        return out

    @staticmethod
    def _redact_pin(cfg):
        """The control PIN never travels to a browser — verifyPin exists so it
        does not have to. The settings editor gets a set/unset flag instead;
        its Save sends blank to KEEP the stored PIN, "clear" to remove it."""
        out = dict(cfg)
        out["controlPinSet"] = bool(out.get("controlPin"))
        out["controlPin"] = ""
        return out

    def _resolve_pin_save(self, incoming):
        if incoming.lower() == "clear":
            return ""
        if incoming == "":
            return getattr(self, "control_pin", "") or ""
        return incoming

    def _public_dashboards_dir(self):
        """Absolute path to Web Assets/public/dashboards/ for the current Indigo
        version. Derived from indigo.server.getInstallFolderPath() so it survives
        Indigo version upgrades without source changes."""
        base = indigo.server.getInstallFolderPath()
        return os.path.join(base, "Web Assets", "public", PUBLIC_SUBDIR)

    def _config_js_path(self):
        return os.path.join(self._public_dashboards_dir(), "config.js")

    def _sync_pages_to_public(self):
        """Mirror every .html file from the plugin bundle into
        Web Assets/public/dashboards/ so IWS serves them without auth.
        Skips files whose mtime/size already match (cheap re-sync on startup).
        Removes stale .html files from the public dir that no longer exist in
        the bundle, so renaming a page also drops the old copy."""
        src = PAGES_SOURCE_DIR
        dst = self._public_dashboards_dir()
        if not os.path.isdir(src):
            log(f"Source pages dir missing: {src}", level="ERROR")
            return 0
        try:
            os.makedirs(dst, exist_ok=True)
        except Exception as exc:
            log(f"Could not create {dst}: {exc}", level="ERROR")
            return 0

        # Copy / update — include HTML pages plus PNG icons (apple-touch-icon)
        # and .js for standalone-nav.js / chart.umd.min.js. `.css` joined the
        # list in v2.51.0 for dashboards-theme.css, which every page <link>s:
        # miss it and the pages load with no palette at all.
        EXT = (".html", ".png", ".js", ".css")
        # NOTE: manifest.json is copied explicitly below (NOT via EXT) so the
        # stale-file scan doesn't see streams.json / rooms.json / config.js
        # (all runtime-generated in this same dir) as "stale" and delete them.
        sources = {f for f in os.listdir(src) if f.endswith(EXT)}
        copied = 0
        for name in sorted(sources):
            sp = os.path.join(src, name)
            dp = os.path.join(dst, name)
            try:
                need = True
                if os.path.exists(dp):
                    ss = os.stat(sp); ds = os.stat(dp)
                    need = (ss.st_size != ds.st_size) or (ss.st_mtime > ds.st_mtime)
                if need:
                    self._copy_atomic(sp, dp)
                    copied += 1
            except Exception as exc:
                log(f"Copy failed for {name}: {exc}", level="ERROR")

        # Drop stale files of the synced extensions. RUNTIME-GENERATED files
        # match the extensions but are written by other parts of the plugin,
        # not mirrored from the bundle — sweeping them deleted config.js and
        # the go2rtc JS assets on EVERY sync, leaving windows where pages 404d
        # until their writers ran again (visible as "Removed stale ..." lines
        # on every restart).
        _RUNTIME_KEEP = {"config.js", "video-rtc.js", "video-stream.js"}
        try:
            for name in os.listdir(dst):
                if (name.endswith(EXT) and name not in sources
                        and name not in _RUNTIME_KEEP):
                    try:
                        os.remove(os.path.join(dst, name))
                        self._activity(f"Removed stale {name} from {dst}")
                    except Exception as exc:
                        log(f"Could not remove stale {name}: {exc}", level="WARNING")
        except Exception as exc:
            log(f"Stale scan failed in {dst}: {exc}", level="WARNING")

        # Demo fixtures (v2.3.0): mirror the demo-data/ subdirectory so the
        # local demo (demo.html) works. Additive copy — no stale sweep needed,
        # the fixtures are regenerated wholesale by tools/make_demo_fixtures.py.
        demo_src = os.path.join(src, "demo-data")
        if os.path.isdir(demo_src):
            demo_dst = os.path.join(dst, "demo-data")
            try:
                os.makedirs(demo_dst, exist_ok=True)
                for name in os.listdir(demo_src):
                    if not name.endswith(".json"):
                        continue
                    sp = os.path.join(demo_src, name)
                    dp = os.path.join(demo_dst, name)
                    ss = os.stat(sp)
                    ds = os.stat(dp) if os.path.exists(dp) else None
                    if ds is None or ss.st_size != ds.st_size or ss.st_mtime > ds.st_mtime:
                        self._copy_atomic(sp, dp)
            except Exception as exc:
                log(f"Demo fixtures copy failed: {exc}", level="WARNING")

        # Explicit one-off copy of manifest.json (PWA manifest for iOS
        # standalone navigation). Not part of the general EXT sweep because we
        # don't want the stale-file cleanup above to touch runtime-written
        # JSON files (streams.json, rooms.json).
        mf_src = os.path.join(src, "manifest.json")
        mf_dst = os.path.join(dst, "manifest.json")
        if os.path.isfile(mf_src):
            try:
                ss = os.stat(mf_src)
                ds = os.stat(mf_dst) if os.path.exists(mf_dst) else None
                if ds is None or ss.st_size != ds.st_size or ss.st_mtime > ds.st_mtime:
                    self._copy_atomic(mf_src, mf_dst)
                    self._activity(f"Synced manifest.json to {dst}")
            except Exception as exc:
                log(f"Manifest copy failed: {exc}", level="WARNING")

        self._activity(f"Synced {copied} of {len(sources)} asset(s) to {dst}")
        return copied

    def _sync_pages_to_domio(self):
        """Copy HTML pages to Web Assets/static/pages/ so the Domio iOS app
        can discover and display them alongside its own bundled pages.
        Additive only — never deletes files from the shared Domio folder as
        we cannot safely distinguish our stale pages from another plugin's or
        the user's own custom pages. If a page is renamed or removed, the user
        should delete the old copy from Web Assets/static/pages/ manually.
        Silently skips if Domio is not installed — never creates the folder
        itself so the plugin does not choke on a Domio-free system."""
        src = PAGES_SOURCE_DIR
        base = indigo.server.getInstallFolderPath()
        domio_plugin = os.path.join(base, "Plugins", "Domio.indigoPlugin")
        if not os.path.isdir(domio_plugin):
            return 0
        dst = os.path.join(base, "Web Assets", "static", "pages")
        if not os.path.isdir(src):
            return 0
        try:
            os.makedirs(dst, exist_ok=True)
        except Exception as exc:
            log(f"Domio sync: could not create {dst}: {exc}", level="WARNING")
            return 0

        # HTML pages from the bundle source dir
        candidates = {name: os.path.join(src, name)
                      for name in sorted(os.listdir(src))
                      if name.endswith(".html")}

        # EVERY shared JS and CSS file from the source dir, not a hand-kept
        # list. The list was three names while the pages referenced eight, so
        # the Domio copies had been loading without a11y.js (24 pages) and
        # Chart.js (6 pages) since those were added — and a new one,
        # energy-calc.js, would have broken the Energy and Cost pages outright
        # rather than just degrading them. Mirroring *.js and *.css the same
        # way we mirror *.html means adding an asset can no longer half-ship.
        for asset in sorted(os.listdir(src)):
            if asset.endswith((".js", ".css")):
                candidates[asset] = os.path.join(src, asset)

        # config.js from the runtime public folder (written by _write_config_js,
        # which must be called BEFORE this method so the file exists)
        cfg_src = os.path.join(self._public_dashboards_dir(), "config.js")
        if os.path.isfile(cfg_src):
            candidates["config.js"] = cfg_src

        # Copy / update
        copied = 0
        for name, sp in candidates.items():
            dp = os.path.join(dst, name)
            try:
                need = True
                if os.path.exists(dp):
                    ss = os.stat(sp); ds = os.stat(dp)
                    need = (ss.st_size != ds.st_size) or (ss.st_mtime > ds.st_mtime)
                if need:
                    self._copy_atomic(sp, dp)
                    copied += 1
            except Exception as exc:
                log(f"Domio sync: copy failed for {name}: {exc}", level="WARNING")

        if copied:
            self._activity(f"Domio sync: copied {copied} file(s) to {dst}")
        return copied

    def _plugin_present(self, plugin_id):
        """Installed AND enabled. Not isRunning(): a plugin mid-restart would
        flip its pages off and on for the seconds it takes, and a crashed one
        stays enabled, so its pages keep their own "unavailable" handling
        rather than vanishing. getPlugin() never raises for an unknown id — it
        reads as not installed, which is the right answer here."""
        try:
            p = indigo.server.getPlugin(plugin_id)
            return bool(p and p.isInstalled() and p.isEnabled())
        except Exception:
            return False

    def _sigen_available(self):
        """Is SigenEnergyManager here? The Energy, Cost and Laundry pages, the
        hub's Energy card, the sigenApi proxy and the laundry scheduler all
        ask this ONE question (v3.13.0)."""
        return self._plugin_present(self._SIGEN_PLUGIN_ID)

    def _feature_flags(self):
        """What config.js publishes about optional plugins, so a page can hide
        what it cannot draw and say why. One builder for the startup write and
        the tick's change check, so the two cannot disagree."""
        return {
            "heatingControls": self._plugin_present(self._EVO_PLUGIN_ID),
            "sigenAvailable":  self._sigen_available(),
        }

    def _refresh_feature_flags(self):
        """Tick task (every 30 s): rewrite config.js when an optional plugin
        has appeared or gone since the last write, so the pages follow an
        install or removal without a restart. Returns True when it rewrote."""
        last = getattr(self, "_config_js_flags", None)
        if last is None:
            return False            # startup has not written config.js yet
        flags = self._feature_flags()
        if flags == last:
            return False
        for key, label in (("sigenAvailable", "SigenEnergyManager"),
                           ("heatingControls", "EvoHomeControl")):
            if flags.get(key) != last.get(key):
                self.logger.info(f"[Config] {label} is now "
                                 f"{'present' if flags.get(key) else 'absent'} — "
                                 f"config.js rewritten so the pages follow")
        self._write_config_js()
        return True

    def _write_config_js(self):
        """Write window.INDIGO_CONFIG and INDIGO_CONFIG_SOURCE to config.js.
        Pages load this (then dashboards-auth.js) before their inline IndigoAPI
        class.
        SECURITY (v1.20.0): the API key is NEVER written here. This file lives
        in Web Assets/public/ which IWS serves with NO authentication — and the
        /public/ namespace is reachable over the Indigo reflector, i.e. from
        the public internet. Only the server baseURL is published; each browser
        is prompted once for the API key by the pages' Connect form and keeps
        it in localStorage (merged in by dashboards-auth.js)."""
        cfg = {}
        if self.api_url:
            cfg = {"baseURL": self.api_url}

        # v2.0.0: auto-discover the Sigenergy inverter device (the one with a
        # batterySoc state) so the hub's energy strip needs no hardcoded ID.
        # Harmless 0 on installs without SigenEnergyManager.
        sigen_id = 0
        try:
            for d in indigo.devices.iter("com.clives.indigoplugin.sigenergy-energy-manager"):
                if "batterySoc" in d.states:
                    sigen_id = d.id
                    break
        except Exception:
            pass
        cfg["sigenDeviceId"] = sigen_id
        # PIN policy (v2.1.0): WHICH devices need a PIN is published (harmless
        # id list); the PIN itself never leaves the server — dashboard.js
        # verifies entries via the Bearer-gated verifyPin endpoint.
        cfg["pinRequired"] = list(self.pin_required) if self.control_pin else []
        # Favourites (v2.10.0): one-tap device/scene tiles for the top of the
        # hub. Just {type,id,label} — not secret, safe in the public config.js.
        cfg["favourites"] = [dict(f) for f in self.favourites]
        # Custom links (v2.x): full-size hub tiles opening an arbitrary URL.
        # {title,url,desc?,icon?} — just a link, no secret, safe in config.js.
        cfg["customLinks"] = [dict(l) for l in self.custom_links]
        # Colour presets (v2.94.0): published so the room page draws its preset
        # buttons from the SAME table the applyColour endpoint acts on. The page
        # sends only the preset key, so a preset edited here changes both what
        # the button says and what it does, in one place.
        cfg["colourPresets"] = {k: dict(v) for k, v in COLOUR_PRESETS.items()}
        # v2.96.0: install-specific presentation, all optional, all defaulted
        # so a fresh install reads as "Dashboards" rather than as one house.
        try:
            store = self._load_config_store()
        except Exception:
            store = {}
        cfg["siteName"] = (str(store.get("siteName") or "").strip() or "Dashboards")[:40]
        vehicles = store.get("vehicles")
        cfg["vehicles"] = [
            {"id": int(v["id"]), "label": (str(v.get("label") or "").strip() or "Vehicle")[:40]}
            for v in (vehicles if isinstance(vehicles, list) else [])
            if isinstance(v, dict) and str(v.get("id", "")).lstrip("-").isdigit()]
        # Optional-plugin flags (v3.13.0): heatingControls (the heating page's
        # boost/force panel is wired to EvoHomeControl's action ids) and
        # sigenAvailable (Energy, Cost, Laundry and the hub's Energy card). ONE
        # builder, so the tick can notice a change and rewrite this file.
        flags = self._feature_flags()
        cfg.update(flags)
        self._config_js_flags = dict(flags)
        # Carbon region 0 = "Off (not in Great Britain)": the menu drops the
        # tile and the advisor never calls the GB-only API.
        try:
            cfg["carbon"] = int((getattr(self, "pluginPrefs", None) or {}).get("carbonRegionId", 4) or 4) != 0
        except (TypeError, ValueError):
            cfg["carbon"] = True
        # The LAN origin, for the "you are on the reflector — at home use
        # this" notice (v2.96.1). config.js is what a reflector-origin page
        # has to hand, so this is the one place it can learn the LAN address.
        cfg["lanURL"] = (f"http://{self.lan_ip}:8176" if getattr(self, "lan_ip", "")
                         else (self.api_url or ""))
        # v3.1.0: the pages refuse to render over the reflector when this is on,
        # so a stale tab cannot sit there pulling camera pictures.
        cfg["reflectorBlock"] = self._reflector_blocked()
        # The PWA manifest carries the site name too (home-screen label).
        try:
            mf = os.path.join(self._public_dashboards_dir(), "manifest.json")
            if os.path.isfile(mf):
                with open(mf, encoding="utf-8") as fh:
                    man = json.load(fh)
                if man.get("short_name") != cfg["siteName"]:
                    man["name"] = f"{cfg['siteName']} Dashboard"
                    man["short_name"] = cfg["siteName"]
                    self._write_atomic(mf, json.dumps(man, indent=2).encode("utf-8"))
        except Exception as exc:
            self.logger.debug(f"[Config] manifest name not updated: {exc}")
        # Array rating (v2.72.0): optional `arrayKwp` store key feeding the
        # Ecowitt page's solar-vs-PV cross-check. A number, not a secret —
        # replaces this house's 14.25 that used to be hardcoded in the page.
        try:
            kwp = float(self._load_config_store().get("arrayKwp") or 0)
            if kwp > 0:
                cfg["arrayKwp"] = kwp
        except (TypeError, ValueError):
            pass
        # Action watches (v2.75.0): how the pages confirm that a control button
        # actually DID something, keyed by action-group id. A 200 from Indigo
        # only means the action group was accepted — the garage controller can
        # drop a press on its debounce and still return 200, and the front-door
        # script then blocks for up to 90 s. So the pages watch the contact
        # sensors instead, using declarative rules published here. Device ids
        # and labels only; nothing secret, safe in the public config.js.
        # Read raw from the store: this handler doesn't model the key, and the
        # save path preserves it via the unknown-key pass-through.
        try:
            watches = self._load_config_store().get("actionWatch")
            if isinstance(watches, dict) and watches:
                cfg["actionWatch"] = {str(k): v for k, v in watches.items()}
        except Exception:
            pass

        # Cameras: only publish host list + display names to the browser. The
        # plugin polls each camera itself with Digest auth and writes the JPEGs
        # as static files into the public folder, so credentials never leave
        # the server.
        cam_cfg = {
            "hosts":          [c["host"] for c in CAMERAS],
            "names":          {c["host"]: c["name"] for c in CAMERAS},
            "slugs":          {c["host"]: self._cam_slug(c["name"]) for c in CAMERAS},
            "imagePattern":   "cam-{host}.jpg",            # snapshot fallback
            # The smaller copy the grid uses. Sent as a separate pattern rather
            # than derived on the page so a future change of naming needs one
            # edit here, not one in every page that shows a camera.
            "thumbPattern":   "cam-{host}-thumb.jpg",
            "thumbWidth":     CAMERA_THUMB_WIDTH,
            "pollSeconds":    CAMERA_POLL_SECONDS,
            "mjpegPort":      MJPEG_PROXY_PORT,            # live MJPEG proxy
            "mjpegPath":      "/mjpeg/{host}",             # ?subtype=0 (HD) / 1 (SD)
            "webrtcPath":     "/webrtc/{host}",            # WHEP signalling (same port as mjpegPort)
            "go2rtcPort":     GO2RTC_API_PORT,             # WebRTC backend
            "livePoolSize":   LIVE_POOL_SIZE,              # how many cams run live at once
            "mainCameras":    list(self.main_cameras),     # ordered IPs for the index.html mosaic
            "swapOutHost":    SWAP_OUT_HOST,               # bumped to still when peeking a non-default cam
        }

        source = self._secrets_state()
        body = (
            "// Generated by Dashboards plugin at startup. Do not edit by hand.\n"
            "// v1.20.0+: no API key in this file (it is publicly reachable).\n"
            "// Browsers are prompted once for the key and store it locally.\n"
            f"window.INDIGO_CONFIG = {json.dumps(cfg)};\n"
            f"window.INDIGO_CONFIG_SOURCE = {json.dumps(source)};\n"
            f"window.CAMERA_CONFIG = {json.dumps(cam_cfg)};\n"
            # The running version, so a page can SAY which build it is. A phone
            # keeping a home-screen dashboard alive resumes it from memory and
            # never re-fetches, so "have you got the fix yet" was unanswerable
            # from either end. config.js is regenerated every startup, so this
            # cannot go stale while the page is current.
            # v2.66.0: sourced from Info.plist (self.pluginVersion), NOT the
            # PLUGIN_VERSION constant. Indigo reads the plist, so that is the
            # version actually running — and the constant is a hand-maintained
            # copy that has already drifted twice (2.9.0 while the code was on
            # 2.13.0, and 2.65.0 against a 2.65.1 plist). A version display is
            # worse than none if it can lie, and the hub now shows this one.
            f"window.DASHBOARDS_BUILD = {json.dumps(self.pluginVersion)};\n"
        )
        path = self._config_js_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Atomic write (v2.37.0): config.js is the first script every page
            # loads and is rewritten at startup / on every settings save while
            # browsers poll continuously. A plain truncate+write handed a page
            # loading mid-write a truncated file (window.INDIGO_CONFIG undefined
            # → blank dashboard). Every sibling public file already uses this.
            self._write_atomic(path, body.encode("utf-8"))
            self._activity(f"Wrote {path} (configured={bool(cfg)})")
        except Exception as e:
            log(f"Failed to write {path}: {e}", level="ERROR")

    # --------------------------------------------------------
    # MJPEG proxy (tiny HTTP server in a daemon thread)
    # --------------------------------------------------------

    # --------------------------------------------------------
    # WebRTC signalling forward (WHEP) — v2.68.0
    # --------------------------------------------------------
    def _forward_whep(self, slug, body):
        """Forward a WHEP SDP offer to go2rtc's loopback API and return
        (status, content_type, payload_bytes) for the handler to relay.

        Contract verified live against go2rtc 1.9.14 (30-Jul-2026):
        POST /api/webrtc?src=<slug> with Content-Type: application/sdp
        answers 201 Created, application/sdp, SDP answer in the body.
        There is NO /api/whep alias (404). The RAW H.264 slug is used, NOT
        <slug>_mjpeg — WebRTC takes the H.264 straight through with no
        ffmpeg leg, and the answer negotiates H264 payload types.

        This is a SHORT-LIVED request on one of the proxy's per-connection
        threads: go2rtc answers in milliseconds (static candidates, no
        gathering wait), and the MEDIA then flows browser<->go2rtc:8555
        directly — it never transits the plugin process, so unlike /mjpeg
        this holds zero long-lived plugin threads.
        """
        import urllib.request
        import urllib.error
        from urllib.parse import quote as _q
        url = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/webrtc"
               f"?src={_q(slug, safe='')}")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/sdp"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "application/sdp")
                if 200 <= resp.status < 300 and payload:
                    return 200, ctype, payload
                return 502, "text/plain", (
                    f"go2rtc answered {resp.status} with no SDP".encode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = b""
            try:
                detail = exc.read()[:200]
            except Exception:
                pass
            return 502, "text/plain", (
                f"go2rtc {exc.code}: ".encode("utf-8") + detail)
        except TimeoutError:
            return 504, "text/plain", b"go2rtc timed out"
        except Exception as exc:
            if "timed out" in str(exc).lower():
                return 504, "text/plain", b"go2rtc timed out"
            return 502, "text/plain", f"go2rtc unreachable: {exc}".encode("utf-8")

    def _start_mjpeg_proxy(self):
        """Bind a small HTTP server to MJPEG_PROXY_PORT and serve one endpoint
        per camera. Each request opens an upstream MJPEG stream to the camera
        (Digest auth) and pipes the multipart bytes straight to the client.
        Per-request thread because socketserver's ThreadingMixIn handles each
        connection on its own thread — fine for 3 cameras × a few viewers."""
        # v1.20.1: the proxy also serves /bootstrap (LAN/Tailscale-only API-key
        # seed for the dashboard pages), so it now starts even with no cameras
        # configured — camera routes just 404 in that case.
        cameras_enabled = bool(self.cam_user and self.cam_pass and CAMERAS)
        if not cameras_enabled and not self.api_key:
            log("[MJPEG] No cameras configured and no API key — proxy disabled",
                level="WARNING")
            self._mjpeg_server = None
            return
        if not cameras_enabled:
            if CAMERAS:
                log("[MJPEG] cameras are configured but DAHUA_USER/DAHUA_PASS are not "
                    "set — camera routes disabled, /bootstrap only", level="WARNING")
            else:
                self.logger.info("[MJPEG] no cameras configured — /bootstrap only")

        import http.server
        import ipaddress
        import socketserver
        import threading
        from urllib.parse import urlparse

        # Map host → go2rtc stream slug. The MJPEG proxy targets go2rtc's
        # transcoded-MJPEG endpoint (mainstream H.264 → MJPEG via ffmpeg) so
        # the picture stays sharp regardless of how the camera's own MJPEG
        # substream is configured. Goodbye Garage shimmer.
        host_to_slug  = {c["host"]: self._cam_slug(c["name"]) for c in CAMERAS}
        allowed_hosts = set(host_to_slug.keys())
        plugin_self   = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            # Socket timeout (v2.95.2). StreamRequestHandler applies this to
            # the request socket, so a client that connects and never sends a
            # request line, or a viewer whose write side has stalled, is
            # dropped after 30 s instead of pinning a handler thread — and,
            # for /mjpeg, an ffmpeg transcode in go2rtc — for ever. A healthy
            # MJPEG stream writes many times a second, so it never trips.
            timeout = 30

            # Silence default per-request access logging — we'd flood the event log.
            def log_message(self, format, *args):
                pass

            def _client_is_private(self):
                """True only for LAN / Tailscale / loopback sources. This port
                is not fronted by the Indigo reflector and must not be exposed
                through the router, but the explicit source check means a
                mistaken port-forward still doesn't leak the key."""
                try:
                    addr = ipaddress.ip_address(self.client_address[0])
                except Exception:
                    return False
                # is_private covers RFC1918 + loopback + link-local; Tailscale
                # uses CGNAT 100.64.0.0/10 which is NOT is_private, so add it.
                return addr.is_private or addr in ipaddress.ip_network("100.64.0.0/10")

            def _echo_same_host_origin(self):
                """Send Access-Control-Allow-Origin ONLY when the caller's Origin
                is served from THIS SAME MACHINE (same hostname as the request
                Host). Used on responses that carry a token/credential so a
                drive-by page in a LAN/Tailnet browser (different hostname) can't
                read the body cross-origin. Same guard as /bootstrap (v2.35.0);
                extended to /guest-bootstrap + /streams in v2.36.0."""
                from urllib.parse import urlparse as _up
                origin = self.headers.get("Origin", "")
                req_host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0].strip("[]").lower()
                origin_host = (_up(origin).hostname or "").lower() if origin else ""
                if origin and req_host and origin_host == req_host:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")

            # ── WebRTC signalling (WHEP) — v2.68.0 ─────────────────
            # POST /webrtc/<host> forwards the browser's SDP offer to
            # go2rtc's loopback API and relays the answer. Same security
            # model as /mjpeg: private sources only, configured-camera
            # allowlist, port never fronted by the reflector. The answer
            # carries session ICE credentials and the LAN candidate — no
            # camera passwords. Media never touches this process.
            def do_OPTIONS(self):
                # The page origin is :8176, this proxy is :8177, and an
                # application/sdp POST is non-simple — Safari preflights.
                # Without this handler the whole feature dies before the
                # first byte of SDP is sent.
                parsed = urlparse(self.path)
                if parsed.path.startswith("/guest/"):
                    # The guest routes are read with a custom X-Guest-Token
                    # header, which makes every fetch non-simple, so the
                    # browser preflights — and until 2.95.1 this 404'd the
                    # preflight, which meant no browser could use the guest
                    # tier at all. Same-host only, never "*".
                    self.send_response(204)
                    self._echo_same_host_origin()
                    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "X-Guest-Token")
                    self.send_header("Access-Control-Max-Age", "86400")
                    self.end_headers()
                    return
                if not parsed.path.startswith("/webrtc/"):
                    self.send_error(404, "not found")
                    return
                self.send_response(204)
                self._echo_same_host_origin()      # same-host, not "*" (v2.95.1)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()

            def do_POST(self):
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/webrtc/"):
                    self.send_error(404, "not found")
                    return
                if not self._client_is_private():
                    self.send_error(403, "forbidden")
                    return
                host = parsed.path[len("/webrtc/"):]
                if host not in allowed_hosts:
                    self.send_error(403, "host not allowed")
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except (TypeError, ValueError):
                    self.send_error(400, "Content-Length required")
                    return
                # An SDP offer is 2-8 KB; 64 KB is generous. Reject BEFORE
                # reading, so an oversized body cannot be pulled into memory.
                if length <= 0 or length > 65536:
                    self.send_error(400, "body size out of range")
                    return
                body = self.rfile.read(length)
                status, ctype, payload = plugin_self._forward_whep(
                    host_to_slug[host], body)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self._echo_same_host_origin()      # same-host, not "*" (v2.95.1)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                # Routes:
                #   /mjpeg/<host>?subtype=N    → live multipart stream
                #   /streams                   → go2rtc /api/streams (with CORS)
                #   /bootstrap                 → API-key seed (private sources only)
                #   /healthz                   → "ok"
                parsed = urlparse(self.path)
                if parsed.path == "/healthz":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return

                # ── Guest tier (v2.1.0) — READ-ONLY data path ────────────
                # Guest devices hold only the guest token, never the API key,
                # so there is no control surface on them at all. The proxy
                # fetches from IWS server-side with the real key and pipes the
                # JSON through, keeping the response shape identical to
                # /v2/api so the pages work unchanged. Private sources only;
                # :8177 is never fronted by the reflector.
                if parsed.path == "/guest-bootstrap":
                    if not self._client_is_private():
                        self.send_error(403, "forbidden")
                        return
                    payload = json.dumps({"guestToken": plugin_self.guest_token}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    # v2.36.0 SECURITY: same-host-only CORS (was '*'). The guest
                    # token is a credential — a drive-by LAN/Tailnet page must not
                    # read it cross-origin and then reach the /guest/* read routes.
                    self._echo_same_host_origin()
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    plugin_self.logger.info(
                        f"[Guest] Guest token issued to {self.client_address[0]}")
                    return

                if parsed.path.startswith("/guest/"):
                    from urllib.parse import parse_qs
                    qs = parse_qs(parsed.query or "")
                    supplied = (self.headers.get("X-Guest-Token")
                                or (qs.get("token") or [""])[0] or "")
                    import hmac
                    tok = plugin_self.guest_token or ""
                    if not (self._client_is_private() and tok
                            and hmac.compare_digest(str(supplied).encode("utf-8"),
                                                    str(tok).encode("utf-8"))):   # constant-time (v2.38.0); bytes so non-ASCII cannot raise
                        self.send_error(401, "guest token required")
                        return

                    def _send_json(payload_bytes, status=200):
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        # Same-host CORS (the v2.36.0 rule) — a wildcard let
                        # any website open in the guest's browser read the
                        # guest data cross-origin.
                        self._echo_same_host_origin()
                        self.send_header("Access-Control-Allow-Headers", "X-Guest-Token")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(payload_bytes)))
                        self.end_headers()
                        self.wfile.write(payload_bytes)

                    sub = parsed.path[len("/guest/"):]
                    if sub == "changedSince":
                        # Served straight from the plugin's change ledger —
                        # same payload shape as the IWS changedSince action.
                        try:
                            since = float((qs.get("since") or ["0"])[0])
                        except ValueError:
                            since = 0.0
                        body = plugin_self._changed_since_payload(since)
                        _send_json(json.dumps(body).encode("utf-8"))
                        return

                    if sub == "history":
                        # Read-only history series for guest devices (v2.4.0).
                        flat = {k: (v[0] if v else "") for k, v in qs.items()}
                        try:
                            body = plugin_self._history_query(flat)
                            _send_json(json.dumps(body).encode("utf-8"))
                        except ValueError as exc:
                            _send_json(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                                       status=400)
                        except Exception as exc:
                            self.send_error(500, f"history query failed: {exc}")
                        return

                    # Read-only passthroughs to IWS (server-side Bearer).
                    iws_path = None
                    if sub == "devices":
                        iws_path = "/v2/api/indigo.devices"
                    elif sub == "variables":
                        iws_path = "/v2/api/indigo.variables"
                    elif sub.startswith("device/"):
                        dev_part = sub[len("device/"):]
                        if dev_part.isdigit():
                            iws_path = f"/v2/api/indigo.devices/{dev_part}"
                    if iws_path is None:
                        self.send_error(404, "unknown guest route")
                        return
                    import urllib.request
                    try:
                        req = urllib.request.Request(
                            f"{plugin_self.api_url}{iws_path}",
                            headers={"Authorization": f"Bearer {plugin_self.api_key}",
                                     "Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=8.0) as r:
                            raw = r.read()
                        # SCRUB before relaying (v2.95.1). The v2 API device
                        # object carries pluginProps / globalProps / ownerProps,
                        # and plugins keep credentials in props — the Email+
                        # SMTP device's serverPassword among them — so the
                        # "read-only, no control surface" guest tier was
                        # handing the household mail password to anyone who
                        # scanned the pairing QR. The pages read names, states
                        # and the class fields only.
                        try:
                            body = plugin_self._guest_scrub(json.loads(raw))
                            _send_json(json.dumps(body).encode("utf-8"))
                        except ValueError:
                            self.send_error(502, "IWS returned non-JSON")
                    except Exception as exc:
                        self.send_error(502, f"IWS fetch failed: {exc}")
                    return

                if parsed.path == "/bootstrap":
                    # One-shot credential seed for dashboards-auth.js: a browser
                    # on the LAN/Tailnet fetches this on first visit, stores the
                    # key in localStorage and never asks again. Anything outside
                    # the private ranges gets a 403 (and can't reach this port
                    # anyway — the reflector only fronts IWS).
                    if not (plugin_self.api_key and self._client_is_private()):
                        self.send_error(403, "forbidden")
                        return
                    # v2.36.0 SECURITY: source-IP alone can't tell a guest-tier
                    # device from a trusted one, so on a LAN any guest device
                    # could self-upgrade by fetching the full key here. When key
                    # auto-seed is turned off, /bootstrap is disabled entirely and
                    # trusted devices pair via the one-time setup links instead —
                    # making the guest boundary real. Default keeps auto-seed on.
                    if not plugin_self.bootstrap_key_seed:
                        self.send_error(403, "key auto-seed disabled — use a setup link")
                        return
                    # SECURITY (confirmed 14-Jul-2026): this response carries the
                    # full Indigo API key, so it must NOT be readable cross-origin.
                    # The old Access-Control-Allow-Origin:* let any website open in
                    # a LAN/Tailnet browser fetch and read the key (the victim
                    # browser is itself on a private IP, so _client_is_private
                    # doesn't help). Echo an allow-origin ONLY when the caller's
                    # Origin is served from THIS SAME MACHINE (same hostname as the
                    # request Host) — that is the legitimate consumer,
                    # dashboards-auth.js on the IWS web port fetching this proxy
                    # cross-port. A drive-by page (evil.com) has a different
                    # hostname, gets no CORS grant, and cannot read the body. A
                    # same-host match would require already serving a page from the
                    # Indigo box itself, i.e. a prior compromise.
                    from urllib.parse import urlparse as _urlparse
                    origin = self.headers.get("Origin", "")
                    req_host = (self.headers.get("Host", "") or "").rsplit(":", 1)[0].strip("[]").lower()
                    origin_host = (_urlparse(origin).hostname or "").lower() if origin else ""
                    payload = json.dumps({"apiKey": plugin_self.api_key}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    if origin and req_host and origin_host == req_host:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    # Once per client address per plugin run. A browser
                    # re-fetches this on every page load, so at INFO it grew
                    # with the number of tabs opened; a NEW address is the
                    # part actually worth a line in the shared log.
                    _ip = self.client_address[0]
                    if plugin_self._note_bootstrap_seed(_ip):
                        plugin_self.logger.info(f"[Bootstrap] API key seeded to {_ip}")
                    else:
                        plugin_self.logger.debug(f"[Bootstrap] API key re-seeded to {_ip}")
                    return

                if parsed.path == "/streams":
                    # Proxy go2rtc's stats JSON for the bandwidth indicator.
                    # v2.36.0 SECURITY: go2rtc's /api/streams carries producer
                    # RTSP urls (rtsp://<user>:<pass>@host) — the camera admin
                    # credentials. The old handler returned that raw with CORS:*,
                    # a second leak channel alongside the streams.json file that
                    # v2.35.0 sanitised. Now: private-source only, run it through
                    # the same _sanitise_streams (drops producers[].url), and
                    # same-host CORS. The page only reads bytes_recv/consumers.
                    if not self._client_is_private():
                        self.send_error(403, "forbidden")
                        return
                    import urllib.request
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{GO2RTC_API_PORT}/api/streams",
                                timeout=2.0) as r:
                            raw = json.loads(r.read().decode("utf-8"))
                        payload = json.dumps(
                            plugin_self._sanitise_streams(raw)).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self._echo_same_host_origin()
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    except Exception as exc:
                        self.send_error(502, f"go2rtc unreachable: {exc}")
                    return

                if not parsed.path.startswith("/mjpeg/"):
                    self.send_error(404, "not found")
                    return
                # Same source rule as every other route on this port
                # (v2.95.1). It was the one route without it — the one
                # carrying the bulkiest private data on the box.
                if not self._client_is_private():
                    self.send_error(403, "forbidden")
                    return

                host = parsed.path[len("/mjpeg/"):]
                if host not in allowed_hosts:
                    self.send_error(403, "host not allowed")
                    return

                slug = host_to_slug[host]
                # All cameras go through go2rtc's ffmpeg-transcoded MJPEG —
                # works the same for Dahua and Hikvision because go2rtc only
                # cares about the RTSP source. Local connection, no auth.
                import requests
                upstream = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/stream.mjpeg"
                            f"?src={slug}_mjpeg")
                auth     = None

                try:
                    r = requests.get(
                        upstream,
                        auth=auth,
                        stream=True,
                        timeout=MJPEG_UPSTREAM_TIMEOUT,
                    )
                except Exception as exc:
                    plugin_self.logger.warning(
                        f"[MJPEG] {host} upstream connect failed: {exc}")
                    self.send_error(502, "upstream connect failed")
                    return

                try:
                    if r.status_code != 200:
                        plugin_self.logger.warning(
                            f"[MJPEG] {host} upstream HTTP {r.status_code}")
                        self.send_error(502, f"upstream {r.status_code}")
                        return

                    ct = r.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=myboundary")
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Connection", "close")
                    # CORS: the pages are same-host on another port, and the
                    # cameras page sets crossOrigin="anonymous" on the <img>
                    # so it can copy the last frame to a canvas — which makes
                    # this header load-bearing. Same-host echo, not "*"
                    # (v2.95.1): a wildcard let any page in a LAN browser read
                    # the video cross-origin.
                    self._echo_same_host_origin()
                    self.end_headers()

                    chunks = r.iter_content(chunk_size=16384)
                    while True:
                        try:
                            chunk = next(chunks)
                        except StopIteration:
                            break
                        except Exception as exc:
                            # UPSTREAM died mid-stream (go2rtc restart, camera
                            # drop). Ending quietly beats the per-client
                            # traceback http.server printed when this raised
                            # straight out of do_GET.
                            plugin_self.logger.debug(
                                f"[MJPEG] {host} upstream ended mid-stream: {exc}")
                            break
                        if not chunk:
                            continue
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            # Client disconnected — close the upstream and bail.
                            break
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass

        class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads      = True
            allow_reuse_address = True

        try:
            srv = _Server(("0.0.0.0", MJPEG_PROXY_PORT), _Handler)
        except Exception as exc:
            log(f"[MJPEG] Could not bind :{MJPEG_PROXY_PORT}: {exc}", level="ERROR")
            self._mjpeg_server = None
            return

        self._mjpeg_server = srv
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="MjpegProxy")
        thread.start()
        self._activity(f"[MJPEG] Proxy listening on :{MJPEG_PROXY_PORT}")

    def _stop_mjpeg_proxy(self):
        if getattr(self, "_mjpeg_server", None):
            try:
                self._mjpeg_server.shutdown()
                self._mjpeg_server.server_close()
                self._activity("[MJPEG] Proxy stopped")
            except Exception as exc:
                log(f"[MJPEG] Shutdown error: {exc}", level="WARNING")
            self._mjpeg_server = None

    # --------------------------------------------------------
    # go2rtc lifecycle (WebRTC backend for live.html)
    # --------------------------------------------------------

    def _go2rtc_dir(self):
        """Per-plugin prefs folder. Indigo guarantees this path is writeable
        and survives version upgrades."""
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId, "go2rtc")
        os.makedirs(d, exist_ok=True)
        return d

    def _go2rtc_config_path(self):
        return os.path.join(self._go2rtc_dir(), "go2rtc.yaml")

    def _go2rtc_log_path(self):
        return os.path.join(self._go2rtc_dir(), "go2rtc.log")

    def _write_go2rtc_config(self):
        """Generate go2rtc.yaml from CAMERAS + DAHUA_USER/PASS. Each camera
        gets a stream name = sanitised display name; the RTSP URL pulls the
        mainstream so go2rtc can repackage to WebRTC/MSE on demand."""
        import shutil
        from urllib.parse import quote
        user_q = quote(self.cam_user, safe="")
        pass_q = quote(self.cam_pass, safe="")

        # Indigo's plugin host runs with a minimal PATH that excludes Homebrew,
        # so go2rtc would otherwise fail with `exec: "ffmpeg": executable file
        # not found`. Resolve the absolute path here and write it into the yaml.
        ffmpeg_bin = (shutil.which("ffmpeg")
                      or shutil.which("ffmpeg", path="/opt/homebrew/bin:/usr/local/bin")
                      or "")

        lines = [
            "# Generated by Dashboards plugin — do not edit by hand.",
            "",
            "api:",
            # LOOPBACK ONLY, and no wildcard origin. go2rtc's API needs no
            # authentication and /api/streams returns each camera's full RTSP
            # URL — which carries DAHUA_USER:DAHUA_PASS in clear text. Bound to
            # ':1984' it answered every host on the LAN, and `origin: '*'` meant
            # ANY web page open in ANY browser on the network could fetch it
            # cross-origin and read the camera password. Every consumer in this
            # plugin already dials 127.0.0.1, no dashboard page references the
            # port, and live.html — the WebRTC page the wildcard was added for —
            # was retired, so closing this costs nothing. The plugin's own
            # /streams route stays the public view and sanitises producer URLs
            # (v2.35.0); this shuts the door the sanitiser was standing in front
            # of. Live-confirmed exposed before the fix.
            f"  listen: '127.0.0.1:{GO2RTC_API_PORT}'",
            "",
            "rtsp:",
            f"  listen: '127.0.0.1:{GO2RTC_RTSP_PORT}'",   # only go2rtc's own ffmpeg leg dials it (v2.95.2)
            "",
            "webrtc:",
            # UDP AND TCP on the same port (was '/tcp' = TCP-only until
            # v2.68.0). UDP is WebRTC's normal path, it works over the
            # Tailscale subnet route, and iOS Safari's ICE-over-TCP support
            # is doubtful — the away live tile leads with UDP. The port is
            # LAN-bound reachability either way: no port-forward, not
            # fronted by the reflector.
            f"  listen: ':{GO2RTC_WEBRTC_PORT}'",
            "  candidates:",
            f"    - {self.lan_ip}:{GO2RTC_WEBRTC_PORT}",
            # The old 'stun:8555' line is deliberately GONE (v2.68.0): it
            # made go2rtc advertise the WAN address in every SDP answer
            # (live-confirmed 51.x.x.x:8555 in a real answer) — unreachable
            # without a port-forward we refuse to add, so it was pure ICE
            # noise plus a WAN-address leak to every LAN/Tailnet caller.
            "",
            "log:",
            "  level: info",
            # DO NOT add a `time:` key here hoping to date the lines — it does
            # nothing. go2rtc's console writer hardcodes zerolog's TimeFormat to
            # "15:04:05.000" (the literal is in the binary), so `time:` reaches
            # structured output only. MEASURED 13-08-2026 by running go2rtc
            # 1.9.14 twice on throwaway configs on unused ports, identical but
            # for the key: both logged "09:31:35.010", no date either way.
            # Dating is done by _stamp_go2rtc_log() instead.
            #
            # NB the first attempt to test this in place proved NOTHING and
            # nearly shipped as fact: _start_go2rtc calls _write_go2rtc_config,
            # so a hand-patched go2rtc.yaml is REGENERATED before the child
            # starts and the key was gone before go2rtc ever read the file.
            # Test a config change in isolation, not against a file the plugin
            # owns and rewrites.
            "",
        ]
        if ffmpeg_bin:
            lines += [
                "ffmpeg:",
                f"  bin: {ffmpeg_bin}",
                "",
            ]
        else:
            log("[go2rtc] ffmpeg not found on PATH — MJPEG transcode will fail. "
                "Install Homebrew ffmpeg (searched: PATH, /opt/homebrew/bin, /usr/local/bin).",
                level="WARNING")
        lines += ["streams:"]
        # Two streams per camera:
        #   <slug>        = H.264 RTSP source. Mainstream or sub2 per the
        #                   camera's `stream` field in DASHBOARDS_CAMERAS
        #                   (default sub2). Available for direct RTSP
        #                   consumers; not used by the page after retiring
        #                   live.html.
        #   <slug>_mjpeg  = same source transcoded → MJPEG via ffmpeg.
        #                   Consumed by the plugin's MJPEG proxy. With sub2
        #                   as the source the transcode is roughly half the
        #                   CPU of mainstream.
        sub2_count = 0
        main_count = 0
        for cam in CAMERAS:
            slug   = self._cam_slug(cam["name"])
            vendor = cam.get("vendor", "dahua")
            stream = cam.get("stream", CAMERA_DEFAULT_STREAM)
            tpl_key = f"rtsp_{stream}"
            v_urls = VENDOR_URLS.get(vendor, VENDOR_URLS["dahua"])
            tpl   = v_urls.get(tpl_key, v_urls["rtsp_main"])
            rtsp  = tpl.format(user=user_q, pwd=pass_q, host=cam["host"])
            lines.append(f"  {slug}: {rtsp}")
            # ffmpeg: source is the named stream <slug>; #video=mjpeg adds an
            # MJPEG re-encode in front of go2rtc's MJPEG consumer.
            lines.append(f"  {slug}_mjpeg: ffmpeg:{slug}#video=mjpeg")
            if stream == "sub2": sub2_count += 1
            else:                main_count += 1

        path = self._go2rtc_config_path()
        # Create 0600 in one step (v2.38.0): this file holds the camera RTSP
        # credentials, and a plain open()+chmod left a brief window where it was
        # world-readable under the default umask.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)        # ensure 0600 even if the file pre-existed
        self._activity(f"[go2rtc] Wrote config {path} ({len(CAMERAS)} streams: "
                       f"{main_count} main, {sub2_count} sub2)")
        return path

    @staticmethod
    def _cam_slug(name):
        """Stable stream name for a camera: lowercase, spaces → underscores."""
        return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")

    def _start_go2rtc(self):
        """Launch go2rtc as a subprocess. We don't keep stdout in memory —
        it's redirected to a logfile so the event log stays clean."""
        import urllib.request      # module-local: plugin.py never imports
                                   # urllib at top level, and the orphan guard
                                   # below silently NameError'd without this
                                   # from v2.37.0 until v2.55.0.
        # Intent, kept separately from the process handle (v2.95.1). The
        # supervisor reads "handle is None" as "never started (no cameras)",
        # but every failure path in here ALSO clears the handle — so a
        # supervised restart that failed to bind (port still held for a
        # second after a crash) read as 'never started' and supervision
        # stopped for good. _go2rtc_wanted says whether there is anything to
        # supervise at all; the handle says whether it is currently running.
        self._go2rtc_wanted = False
        if not CAMERAS:
            self._go2rtc_proc = None             # nothing to stream: quiet by design
            return
        if not (self.cam_user and self.cam_pass):
            log("[go2rtc] cameras are configured but DAHUA_USER/DAHUA_PASS are not set — "
                "WebRTC backend disabled", level="WARNING")
            self._go2rtc_proc = None
            return
        # Binary resolution: PluginConfig `go2rtcPath` first, then the PATH,
        # then the historical ~/bin/go2rtc — the pinned path was the only
        # option before v2.73.0 and a Homebrew install simply never worked.
        go2rtc_bin = ((self.pluginPrefs.get("go2rtcPath", "") or "").strip()
                      or shutil.which("go2rtc") or GO2RTC_BIN)
        self._go2rtc_bin = go2rtc_bin
        if not os.path.isfile(go2rtc_bin) or not os.access(go2rtc_bin, os.X_OK):
            log(f"[go2rtc] Binary not found or not executable at {go2rtc_bin} — "
                f"live.html will not work. Install: download go2rtc_mac_arm64.zip "
                f"from https://github.com/AlexxIT/go2rtc/releases", level="WARNING")
            self._go2rtc_proc = None
            return

        try:
            cfg = self._write_go2rtc_config()
        except Exception as exc:
            # A config-write failure must cost cameras only, never the whole
            # startup chain — this ran unguarded inside startup() before.
            log(f"[go2rtc] Could not write go2rtc.yaml: {exc} — cameras "
                f"disabled until fixed", level="ERROR")
            self._go2rtc_proc = None
            return
        # Everything a start needs is present from here on, so whatever
        # happens below is a FAILURE to supervise, not an absence to ignore.
        self._go2rtc_wanted = True
        import subprocess
        # Orphan guard (v2.37.0): go2rtc is deliberately detached
        # (start_new_session=True) so it survives a plugin SIGTERM, and only
        # _stop_go2rtc kills it. After an UNCLEAN plugin exit (kill -9, host
        # crash, forced restart) the old instance keeps :1984/:8554/:8555, the
        # new Popen fails to bind and dies into the logfile, and health checks
        # then see the ORPHAN answering on the PREVIOUS config — so camera or
        # credential edits silently never take effect. If anything is already
        # answering on :1984 before we launch, kill our stale go2rtc first.
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{GO2RTC_API_PORT}/api", timeout=1.0) as _r:
                if _r.status == 200:
                    log("[go2rtc] Found an instance already on "
                        f":{GO2RTC_API_PORT} (orphan from an unclean exit) — "
                        "terminating it before starting fresh", level="WARNING")
                    subprocess.run(["/usr/bin/pkill", "-f",
                                    f"{go2rtc_bin} -config {cfg}"],
                                   capture_output=True)
                    time.sleep(0.5)
        except (urllib.error.URLError, OSError, TimeoutError):
            pass   # nothing answering on :1984 — the normal case
        except Exception as exc:
            # Anything else means the GUARD itself is broken, not that the port
            # is free. Swallowing that silently is how this check sat dead from
            # v2.37.0 to v2.55.0 — a missing import raised NameError straight
            # into a bare `except Exception: pass` and looked exactly like the
            # normal case. Never let a failed check pass as a passed check.
            log(f"[go2rtc] orphan check failed to run ({type(exc).__name__}: "
                f"{exc}) — starting anyway, but a stale instance would not "
                f"have been detected", level="WARNING")
        # Augment PATH so go2rtc can find ffmpeg (Indigo's plugin host PATH is
        # minimal and excludes Homebrew). The yaml's `ffmpeg.bin` setting is
        # the primary mechanism; this PATH augmentation is belt-and-braces in
        # case ffmpeg calls out to other tools (e.g. ffprobe) without absolute paths.
        env = os.environ.copy()
        env["PATH"] = (
            "/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:"
            + env.get("PATH", "")
        )
        try:
            # Cap the go2rtc log (v2.38.0): it's append-only across every
            # restart and ffmpeg is chatty, so it grew without bound. Start a
            # fresh file whenever it passes ~5 MB (we only keep it for triage).
            _logp = self._go2rtc_log_path()
            try:
                if os.path.exists(_logp) and os.path.getsize(_logp) > 5 * 1024 * 1024:
                    open(_logp, "wb").close()
            except OSError:
                pass
            # 0600, like go2rtc.yaml beside it (v2.95.1). go2rtc echoes every
            # RTSP source URL — user:password@host — into its log at startup
            # and on each reconnect: 562 copies of the camera password were
            # sitting in a 0644 file that any local account, backup or
            # support paste could read. Created private, and an existing
            # file is healed on every start.
            _old = getattr(self, "_go2rtc_logfile", None)
            if _old is not None:                 # a supervised restart leaked one fd per start
                try:
                    _old.close()
                except Exception:
                    pass
            _fd = os.open(_logp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            log_f = os.fdopen(_fd, "ab", buffering=0)
            try:
                os.chmod(_logp, 0o600)
            except OSError:
                pass
            self._go2rtc_logfile = log_f
            # Force one so a rotated (truncated) file opens dated, and so the
            # very first line after a start can always be placed on a day.
            self._go2rtc_log_day = None
            self._stamp_go2rtc_log(force=True)
            self._go2rtc_proc = subprocess.Popen(
                [go2rtc_bin, "-config", cfg],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,    # so SIGTERM to plugin doesn't auto-kill it; we do that explicitly
            )
            self._activity(f"[go2rtc] Started (pid {self._go2rtc_proc.pid}) - "
                           f"API http://127.0.0.1:{GO2RTC_API_PORT}/ (loopback only)")
            # Catch an immediate bind failure (e.g. a port still held) rather
            # than reporting a phantom-healthy start.
            time.sleep(1.0)
            rc = self._go2rtc_proc.poll()
            if rc is not None:
                log(f"[go2rtc] Exited immediately (code {rc}) — likely a port "
                    f"still in use; see {self._go2rtc_log_path()}", level="ERROR")
                self._go2rtc_proc = None
        except Exception as exc:
            log(f"[go2rtc] Could not start: {exc}", level="ERROR")
            self._go2rtc_proc = None

    def _stamp_go2rtc_log(self, force=False):
        """Write a dated marker into go2rtc.log when the local date rolls over.

        go2rtc stamps the TIME only and cannot be configured otherwise (see the
        note in the config builder), so a line in a log spanning several days
        cannot be placed on a day. That cost real diagnostic work on 13-08-2026:
        the log held camera failures and there was no way to tell last night's
        from the same failures a week earlier.

        Deliberately markers, NOT a pipe. Reading the child's stdout through a
        pipe to prefix each line would let a stalled reader fill the 64 KB pipe
        buffer and BLOCK go2rtc — trading a logging nicety for a wedged camera
        backend. Appending a line a day to the file the child already holds open
        adds no failure mode at all: both ends append, and a marker that fails to
        write costs nothing.
        """
        try:
            handle = getattr(self, "_go2rtc_logfile", None)
            if handle is None or handle.closed:
                return
            # NB `datetime` here is the CLASS (from datetime import datetime),
            # not the module — datetime.datetime.now() raises AttributeError,
            # which the except below would have swallowed into a marker that
            # silently never appeared.
            today = datetime.now().strftime("%Y-%m-%d %A")
            if not force and today == getattr(self, "_go2rtc_log_day", None):
                return
            handle.write(f"===== {today} — date marker (go2rtc stamps time only) "
                         f"=====\n".encode("utf-8"))
            self._go2rtc_log_day = today
        except Exception:
            # Never let a log cosmetic touch the supervision path it rides on.
            pass

    def _mirror_go2rtc_assets(self):
        """Copy go2rtc's video-stream.js + video-rtc.js into the public dashboards
        folder so live.html can load them same-origin. go2rtc itself doesn't send
        CORS headers, and iOS Safari refuses cross-origin <script type=module>
        imports without them. Runs after the subprocess has had a moment to bind."""
        import urllib.request
        # No process, nothing to mirror — without this check a camera-less
        # install burned the full probe loop and warned about a binary it
        # deliberately never started.
        proc = getattr(self, "_go2rtc_proc", None)
        if proc is None or proc.poll() is not None:
            return
        # Give go2rtc a beat to bind :1984 — the bind happens on its main loop
        # which takes ~200-500ms after Popen returns.
        for attempt in range(10):
            if proc.poll() is not None:
                return                       # it died mid-loop — nothing to mirror
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{GO2RTC_API_PORT}/api",
                                            timeout=0.5) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            log("[go2rtc] API didn't respond within ~7s — assets not mirrored",
                level="WARNING")
            return

        dst_dir = self._public_dashboards_dir()
        copied  = 0
        for name in ("video-stream.js", "video-rtc.js"):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{GO2RTC_API_PORT}/{name}",
                        timeout=3.0) as r:
                    data = r.read()
                self._write_atomic(os.path.join(dst_dir, name), data)
                copied += 1
            except Exception as exc:
                log(f"[go2rtc] Could not mirror {name}: {exc}", level="WARNING")
        if copied:
            self._activity(f"[go2rtc] Mirrored {copied} JS asset(s) into {dst_dir}")

    def _supervise_go2rtc(self):
        """Restart go2rtc if it died mid-run. Until v2.72.0 a crash killed
        every camera function — snapshots, MJPEG, WebRTC — SILENTLY until a
        manual plugin restart (the only mid-run check was the /streams
        consumer path, which merely errored). Called from the poller's 30 s
        sweep; backoff stops a crash-looping binary from thrashing."""
        proc = getattr(self, "_go2rtc_proc", None)
        if proc is not None and proc.poll() is None:
            # Healthy is the common case, and a healthy go2rtc can run for days
            # (this one had been up since Tuesday), so the date marker has to go
            # here rather than only on the restart path.
            self._stamp_go2rtc_log()
            return                      # healthy
        if proc is None and not getattr(self, "_go2rtc_wanted", False):
            return                      # never started: no cameras, no binary
        # Either the process exited, or a previous start was WANTED and failed
        # (a bind that lost the race with the old instance's port, say) and
        # cleared the handle. Both retry under the same backoff. Until 2.95.1
        # the second case took the 'never started' exit above, so one failed
        # supervised restart switched supervision off for good — every camera
        # function dead until someone restarted the plugin by hand, which is
        # precisely the failure this method exists to remove.
        now = time.time()
        if now < getattr(self, "_go2rtc_retry_at", 0):
            return
        backoff = min(getattr(self, "_go2rtc_backoff", 30), 600)
        self._go2rtc_retry_at = now + backoff
        self._go2rtc_backoff = backoff * 2
        if proc is not None:
            log(f"[go2rtc] process died (exit {proc.returncode}) — restarting "
                f"(retry in {backoff:.0f}s if it dies again)", level="WARNING")
        else:
            log(f"[go2rtc] last start failed — trying again "
                f"(next retry in {backoff:.0f}s if this one fails)", level="WARNING")
        self._go2rtc_proc = None
        try:
            self._start_go2rtc()
            live = getattr(self, "_go2rtc_proc", None)
            if live is not None and live.poll() is None:
                self._go2rtc_backoff = 30           # healthy again — reset
        except Exception as exc:
            log(f"[go2rtc] supervised restart failed: {exc}", level="ERROR")

    def _stop_go2rtc(self):
        proc = getattr(self, "_go2rtc_proc", None)
        if proc:
            try:
                proc.terminate()
                # Short on purpose: this runs inside the plugin's ~20 s
                # polite-quit budget alongside every other stop. go2rtc exits
                # on SIGTERM in well under a second; if it has not gone in 2 s
                # it is not going to, so kill it rather than wait.
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                self._activity(f"[go2rtc] Stopped (pid {proc.pid})")
            except Exception as exc:
                log(f"[go2rtc] Shutdown error: {exc}", level="WARNING")
            self._go2rtc_proc = None
        lf = getattr(self, "_go2rtc_logfile", None)
        if lf:
            try: lf.close()
            except Exception: pass
            self._go2rtc_logfile = None

    # --------------------------------------------------------
    # Camera snapshot poller (background thread via runConcurrentThread)
    # --------------------------------------------------------

    def _cam_jpg_path(self, host):
        return os.path.join(self._public_dashboards_dir(), f"cam-{host}.jpg")

    def _cam_thumb_path(self, host):
        return os.path.join(self._public_dashboards_dir(), f"cam-{host}-thumb.jpg")

    def _make_thumb(self, jpeg_bytes):
        """Shrink a snapshot for the grid. Returns bytes, or None if it cannot.

        None is a perfectly good answer — the page falls back to the full-size
        picture, which is what it used before this existed. That matters because
        Pillow is a declared requirement rather than a guaranteed one: if the
        install failed, or the frame is malformed, the cameras should carry on
        looking exactly as they always did rather than showing nothing.
        """
        if self._thumb_broken:
            return None
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(jpeg_bytes)) as im:
                if im.width <= CAMERA_THUMB_WIDTH:
                    return None                   # already small; no point
                h = max(1, round(im.height * CAMERA_THUMB_WIDTH / im.width))
                im = im.convert("RGB").resize((CAMERA_THUMB_WIDTH, h), Image.BILINEAR)
                out = io.BytesIO()
                im.save(out, format="JPEG", quality=CAMERA_THUMB_QUALITY, optimize=False)
                return out.getvalue()
        except ImportError:
            # Latch it: this cannot fix itself while the plugin is running, and
            # nine failed imports every two seconds is nine log lines a second.
            self._thumb_broken = True
            log("[Cameras] Pillow is not available, so grid thumbnails are off and "
                "the full-size pictures will be used instead. This costs about "
                "three times the data on a slow link. Restart the plugin to let "
                "Indigo install it from requirements.txt.", level="WARNING")
            return None
        except Exception as exc:
            # A single bad frame must not latch the feature off for good.
            now = time.time()
            if (now - self._thumb_last_log) > 300:
                self._thumb_last_log = now
                log(f"[Cameras] Could not shrink a snapshot for the grid: {exc}", level="WARNING")
            return None

    def _snapshot_pool(self):
        """The snapshot fetch pool, created on first use.

        Built lazily rather than in startup() so a camera-less install never
        spawns threads it has no work for, and reused across ticks rather than
        rebuilt — at a 2 s interval a per-tick pool would churn nine threads
        every two seconds for no reason. Returns None once shutdown has begun
        so a tick already in flight stops submitting.
        """
        if getattr(self, "_cam_pool_closed", False):
            return None
        pool = getattr(self, "_cam_pool", None)
        if pool is None:
            from concurrent.futures import ThreadPoolExecutor
            # One worker per camera: they are all blocked on network I/O, so
            # this is wait time overlapped, not CPU contention.
            workers = max(1, min(len(CAMERAS) or 1, CAMERA_POLL_MAX_WORKERS))
            pool = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="DashSnap")
            self._cam_pool = pool
            self.logger.debug(f"[Cameras] snapshot pool started ({workers} workers)")
        return pool

    def _stop_snapshot_pool(self):
        """Stop accepting snapshots without waiting for in-flight fetches.

        wait=False, cancel_futures=True: a worker blocked in requests.get()
        against a slow or dead camera would otherwise hold shutdown for its
        full timeout (15 s, plus a retry), and the plugin host has ~20 s in
        total before Indigo force-kills it. Nothing is lost by not waiting —
        the workers are daemon threads, and _write_atomic means a snapshot
        file is either the old one or the new one, never half-written.
        """
        self._cam_pool_closed = True
        pool = getattr(self, "_cam_pool", None)
        if pool is None:
            return
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self._cam_pool = None

    def _fetch_one_snapshot(self, host):
        """Fetch a single JPEG via go2rtc's /api/frame.jpeg endpoint. This
        decodes one frame from the camera's RTSP stream (the same source
        go2rtc uses for the live MJPEG transcode), so any camera that streams
        will also snapshot — even cameras whose own /snapshot.cgi endpoint is
        broken (e.g. the Patio 4K returns HTTP 500 directly). Bonus: removes
        the vendor-specific snapshot URL handling — go2rtc does that work."""
        import requests
        cam  = next((c for c in CAMERAS if c["host"] == host), None)
        slug = self._cam_slug((cam or {}).get("name", host))
        url  = (f"http://127.0.0.1:{GO2RTC_API_PORT}/api/frame.jpeg"
                f"?src={slug}&width={CAMERA_SNAPSHOT_WIDTH}")

        def attempt():
            try:
                r = requests.get(url, timeout=CAMERA_HTTP_TIMEOUT, stream=False)
                if r.status_code != 200:
                    return False, f"HTTP {r.status_code}"
                ct = r.headers.get("Content-Type", "")
                if "image" not in ct:
                    return False, f"unexpected content-type {ct!r}"
                return True, r.content
            except Exception as exc:
                return False, str(exc)

        ok, payload = attempt()
        if ok:
            return ok, payload

        # ONE retry, after a short pause. go2rtc spawns ffmpeg to rescale each
        # frame and it occasionally exits 69 (EX_UNAVAILABLE), which comes back
        # here as a bare HTTP 500. It is transient: MEASURED over 270 requests,
        # 4 failed and ALL FOUR succeeded on a single retry 250 ms later, with
        # none needing a second. Without the retry each one costs that camera a
        # whole 2 s cycle — its file is simply not rewritten — and puts a
        # warning in the log that reads like a broken camera when nothing is
        # wrong. Retrying is also why the failure rate is not worth chasing
        # further: it is 1.5% of requests and it fixes itself.
        #
        # Deliberately ONE retry, not a loop. If go2rtc is genuinely wedged, a
        # retry loop across nine cameras every two seconds makes it worse, and
        # the caller already backs the camera off after repeated failures.
        time.sleep(CAMERA_RETRY_DELAY)
        ok, retry_payload = attempt()
        if ok:
            return True, retry_payload
        # Report the FIRST error — it is the more informative of the two, and
        # keeps the log message stable for a camera that is really down.
        return False, payload

    def _write_atomic(self, path, data):
        """Write bytes to a temp file then rename — avoids the browser ever
        reading a half-written JPEG. The temp name carries the writing
        thread's id: the stamp thread, the snapshot pool and MainThread all
        use this helper, and two concurrent writers sharing one ".tmp" could
        interleave (open/truncate/replace) into a torn or vanished file."""
        tmp = f"{path}.tmp.{threading.get_ident()}"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    @staticmethod
    def _copy_atomic(src, dst):
        """shutil.copy2 into a directory IWS is serving TRUNCATES the
        destination and then fills it, so a browser that asks for the file
        during that window gets a short read and IWS answers 500.

        That is where the "internal server error for request
        /public/dashboards/standalone-nav.js" lines came from: every one of
        them lands within seconds of a plugin restart, which is exactly when
        the startup sync rewrites all 38 assets under the browser's feet.
        config.js has been written atomically since v2.37.0 for the same
        reason — its comment claimed every sibling did too, and none did.

        Temp file in the SAME directory so os.replace stays on one filesystem
        and is therefore atomic; a reader sees the old file or the new one.
        """
        tmp = dst + ".tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    def _fetch_go2rtc_streams(self):
        """Fetch go2rtc's full /api/streams JSON. Returns parsed dict or None
        if go2rtc is unreachable."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{GO2RTC_API_PORT}/api/streams",
                timeout=2.0) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _write_streams_json(self, streams):
        """Mirror go2rtc /api/streams to Web Assets/public/dashboards/streams.json
        so the cameras page can read it same-origin (port 8176) instead of
        cross-port fetching to 8177. iOS Safari blocks the cross-port fetch
        in some configurations even with CORS headers.
        Adds a _writeTs (Unix epoch, seconds, fractional) so the page can do
        delta math against the actual write time — otherwise the page poll
        cadence and the file write cadence interleave and bandwidth alternates
        between the real value and 0."""
        if streams is None:
            return
        try:
            payload = self._sanitise_streams(streams)
            payload["_writeTs"] = time.time()
            # A deliberately small, credential-free health summary for the
            # anonymous cameras page.  The raw go2rtc map above has already
            # been sanitised; do not add URLs, exception text or client data.
            payload["_cameraHealth"] = self._camera_health_payload(CAMERAS, self._cam_state)
            path = os.path.join(self._public_dashboards_dir(), "streams.json")
            self._write_atomic(path, json.dumps(payload).encode("utf-8"))
        except Exception as exc:
            log(f"[Cameras] streams.json write failed: {exc}", level="WARNING")

    # Fields a guest may see on a device or variable object. Everything the
    # pages read (id, name, class, states, on/brightness, timestamps, folder)
    # and nothing a plugin might keep a secret in.
    _GUEST_DROP_KEYS = frozenset({"pluginProps", "globalProps", "ownerProps",
                                  "sharedProps", "description", "configured",
                                  "address"})

    @classmethod
    def _guest_scrub(cls, obj):
        """Strip plugin props (and the other free-text fields) from a v2 API
        payload before it is relayed to a guest-token holder. Works on a
        single object, a list of them, or the {"objects": [...]} envelope,
        and leaves anything else alone."""
        if isinstance(obj, list):
            return [cls._guest_scrub(o) for o in obj]
        if isinstance(obj, dict):
            return {k: (cls._guest_scrub(v) if isinstance(v, (list, dict)) else v)
                    for k, v in obj.items() if k not in cls._GUEST_DROP_KEYS}
        return obj

    @staticmethod
    def _sanitise_streams(streams):
        """Strip producer source URLs before the go2rtc streams map is written
        to the ANONYMOUS /public namespace. An RTSP producer url is
        rtsp://<user>:<pass>@host/... — i.e. the camera admin credentials — and
        /public is served with no auth even over the reflector, so writing them
        there is an internet-readable leak (SECURITY, confirmed 14-Jul-2026;
        same /public-secret class the config.js hardening in v1.20.0 fixed).
        The cameras page only ever reads producers[].bytes_recv + consumers +
        _writeTs, never the url, so dropping every producer 'url' key costs the
        UI nothing."""
        safe = {}
        for name, info in (streams or {}).items():
            if not isinstance(info, dict):
                safe[name] = info
                continue
            entry = {}
            for key, val in info.items():
                if key == "producers" and isinstance(val, list):
                    entry[key] = [
                        {pk: pv for pk, pv in prod.items() if pk != "url"}
                        if isinstance(prod, dict) else prod
                        for prod in val
                    ]
                elif key == "consumers" and isinstance(val, list):
                    # Each consumer entry carries the VIEWER's IP, user agent
                    # and negotiated SDP — none of it needed by the pages
                    # (nothing reads past the count) and none of it belongs in
                    # the anonymous /public namespace.
                    entry["consumers_n"] = len(val)
                else:
                    entry[key] = val
            safe[name] = entry
        return safe

    @staticmethod
    def _camera_health_payload(cameras, states):
        """Return public-safe snapshot health, never upstream error details.

        The UI needs to distinguish a camera that is currently retrying from
        one that has not yet completed its first poll.  Timestamps are useful
        for age display but are not identifying information; URLs, exception
        messages and viewer data remain private.
        """
        out = {}
        for cam in cameras or []:
            host = cam.get("host") if isinstance(cam, dict) else None
            if not host:
                continue
            st = (states or {}).get(host, {})
            fails = max(0, int(st.get("fail_count", 0) or 0))
            last_ok = st.get("last_ok")
            last_failure = st.get("last_failure")
            if last_ok is None and last_failure is None:
                state = "unknown"
            elif fails >= 3:
                state = "offline"
            elif fails:
                state = "retrying"
            else:
                state = "ok"
            out[host] = {
                "state": state,
                "consecutiveFailures": fails,
                "lastOkTs": last_ok,
                "lastFailureTs": last_failure,
            }
        return out

    # --------------------------------------------------------
    # Scenes map (action groups by folder) — v1.21.0
    # --------------------------------------------------------

    def _hidden_scenes(self):
        """Resolve the scenes hide-list: IndigoSecrets.DASHBOARDS_HIDDEN_SCENES
        first (JSON string or python list), PluginConfig hiddenScenesJson as
        fallback. Returns a set of strings."""
        if self.cfg_loaded:
            src = self.cfg_store.get("hiddenScenes") or []
        else:
            src = DASHBOARDS_HIDDEN_SCENES or self.pluginPrefs.get("hiddenScenesJson", "")
        if isinstance(src, str):
            s = src.strip()
            if not s:
                return set()
            try:
                src = json.loads(s)
            except Exception as exc:
                log(f"[Scenes] hide-list is not valid JSON ({exc}) — ignoring",
                    level="WARNING")
                return set()
        try:
            return {str(x) for x in src}
        except Exception:
            return set()

    def _build_scenes_json(self):
        """Write scenes.json — every Indigo action group grouped by its folder,
        minus anything on the hide-list. The scenes page renders this directly;
        execution goes browser → /v2/api/command (indigo.actionGroup.execute)."""
        try:
            hidden = self._hidden_scenes()
            folder_names = {}
            try:
                for f in indigo.actionGroups.folders:
                    folder_names[f.id] = f.name
            except Exception:
                pass
            groups = {}
            for ag in indigo.actionGroups:
                folder = folder_names.get(ag.folderId, "") or "General"
                if (ag.name in hidden or str(ag.id) in hidden
                        or f"folder:{folder}" in hidden):
                    continue
                groups.setdefault(folder, []).append({"id": ag.id, "name": ag.name})
            payload = {
                "folders": [
                    {"name": name,
                     "scenes": sorted(items, key=lambda s: s["name"].lower())}
                    for name, items in sorted(groups.items(), key=lambda kv: kv[0].lower())
                ],
                "_writeTs": time.time(),
            }
            path = os.path.join(self._public_dashboards_dir(), "scenes.json")
            self._write_atomic(path, json.dumps(payload).encode("utf-8"))
        except Exception as exc:
            log(f"[Scenes] scenes.json write failed: {exc}", level="WARNING")

    # --------------------------------------------------------
    # Rooms map (Lights / Motion / Radiators / Windows / Extras)
    # --------------------------------------------------------

    # Which Indigo device folders are surfaced as dashboard rooms. Anything
    # else (ESPHome / MQTT / RAMSES / Z_Not_Used / Server Room / etc.) is
    # ignored except for the radiator-by-name pass below.
    # Overridable via the config store's optional `roomFolders` list (Settings
    # raw-JSON hatch) — the tuple below is the fallback and, being one house's
    # folder names, produces an EMPTY rooms.json on any other install unless
    # overridden. The rooms.json builder reads _room_folders(), not this.
    ROOM_FOLDERS = (
        "Bathroom", "Bedroom 1", "Bedroom 2", "Bedroom 3",
        "Conservatory", "Dining Room", "Drive", "En Suite",
        "Garage", "Garden", "Hall", "Kitchen", "Living Room", "Utility Room",
    )

    def _room_folders(self):
        try:
            rf = self._load_config_store().get("roomFolders")
            if isinstance(rf, list) and rf:
                return tuple(str(x) for x in rf)
        except Exception:
            pass
        return self.ROOM_FOLDERS
    # Device classification — used by _build_rooms_json. Keep these short
    # and tweak them based on what gets miscategorised in your install.
    _LIGHT_WORDS    = ("light", "lights", "lamp", "lamps", "spot", "spots",
                       "bulb", "led", "strip", "spotlight", "spotlights")
    _MOTION_WORDS   = ("motion", "presence", "occupancy", "pir")
    _OCCUPANCY_TYPES = ("z2mOccupancySensor",)
    _CONTACT_TYPES   = ("z2mContactSensor", "zwContactSensorType")
    # Device types that look like sensors to the framework but are actually
    # input controls (wall remotes, scene buttons). They publish onState
    # transitions on press but aren't continuous-state sensors — they don't
    # belong in Windows & Doors, Motion or any auto-classified section even
    # when their friendly name happens to contain "door" / "window".
    _BUTTON_TYPES    = ("z2mButton",)
    # Devices we always ignore — backend plumbing, not user-facing controls.
    _SKIP_TYPES = (
        "homeKitBridgeDevice",   # HomeKit bridges (1 per room, internal)
        "z2mRepeater",            # Z2M signal repeaters
        "timer",                  # Indigo built-in timers
        "damGroup",               # Device Activity Monitor groups
    )
    # Contact-sensor exclusions by keyword (freezer/fridge aren't windows).
    _SKIP_CONTACT_WORDS = ("freezer", "fridge")
    # Names containing these aren't lights even if they're a DimmerDevice.
    _NOT_LIGHT_WORDS = ("fan",)

    @staticmethod
    def _has_word(name, words):
        toks = set(name.lower().replace("-", " ").split())
        return any(w in toks for w in words)

    def _classify_device(self, dev):
        """Return one of: 'light', 'motion', 'radiator', 'window', 'sensor',
        'extras', None. None means skip entirely (HK bridge etc.). Radiator
        classification is done separately in _build_rooms_json because it
        needs name-prefix matching across all folders, not just room ones."""
        typ = dev.deviceTypeId or ""
        if typ in self._SKIP_TYPES:
            return None
        cls  = dev.__class__.__name__
        name = dev.name or ""
        # Dimmers are lights unless explicitly disallowed (fan etc.)
        if cls == "DimmerDevice" and not self._has_word(name, self._NOT_LIGHT_WORDS):
            return "light"
        # Relay devices need a light keyword in the name to qualify.
        if cls == "RelayDevice" and self._has_word(name, self._LIGHT_WORDS):
            return "light"
        # Motion / presence sensors — also catches Z-Wave occupancy + radars.
        if typ in self._OCCUPANCY_TYPES or self._has_word(name, self._MOTION_WORDS):
            return "motion"
        # Water/leak sensors — binary alert state, sharing the motion-style tile
        # but the renderer auto-switches the label wording to Wet / Dry.
        if self._has_word(name, ("water", "leak")):
            return "motion"
        # Window / door contacts — match by deviceTypeId OR by name keyword so
        # we catch z2mSensor-typed contacts that don't have the explicit
        # z2mContactSensor type. Checked BEFORE the temp+humidity rule because
        # z2m sensor devices frequently expose dummy temperature/humidity
        # states (often 0.0) — a window contact would otherwise be mistaken
        # for an environment sensor.
        #
        # IMPORTANT: gate this on multiple "not a real contact" checks. The
        # name keyword "door"/"window" is necessary but not sufficient —
        # plenty of devices contain those words without being contact
        # sensors:
        #   - Relay/Dimmer outputs (Shelly garage-door relay, virtual
        #     opener) — already classified as light or extras above
        #   - z2mButton wall remotes (e.g. "Hall Garage Door Opener")
        #   - Z-Wave value sensors (zwValueSensorType e.g. "Front Door
        #     Luminance", "Front Door Temperature") — those expose
        #     sensorValue not onState, so onState is null and the page
        #     would render them as permanently "Closed".
        # A genuine contact ALWAYS exposes a boolean onState — that's the
        # tightest filter we have.
        is_output      = cls in ("RelayDevice", "DimmerDevice")
        is_button      = typ in self._BUTTON_TYPES
        supports_onst  = getattr(dev, "supportsOnState", False) is True
        if (not is_output) and (not is_button) and supports_onst \
                and (typ in self._CONTACT_TYPES
                     or self._has_word(name, ("contact", "window", "door"))) \
                and not any(w in name.lower() for w in self._SKIP_CONTACT_WORDS):
            return "window"
        # Continuous-value environment sensors — must have BOTH temperature
        # AND humidity states (the contact check above already filtered out
        # window/door sensors that happen to expose those keys too).
        states = getattr(dev, "states", {}) or {}
        if "temperature" in states and "humidity" in states:
            return "sensor"
        return "extras"

    def _build_rooms_json(self):
        """Walk indigo.devices.folders, classify every device, and write a
        rooms.json file into the dashboards public folder. The page-side
        room.html template reads this to know which device IDs to render in
        each section per room.

        Radiators are special — they live in a single shared "RAMSES" folder
        (Evohome zones) rather than per-room folders. We assign them to the
        room whose name appears as a prefix in the device name (e.g. "Hall
        Bedroom Radiator" → Hall, "Living Room Door Radiator" → Living Room).
        Longest-prefix-wins so "Living Room" beats "Living" if both exist."""
        room_folders = self._room_folders()
        # Build folder_id → room name only for the configured room folders.
        try:
            folder_to_room = {
                f.id: f.name for f in indigo.devices.folders.iter()
                if f.name in room_folders
            }
        except Exception as exc:
            log(f"[Rooms] Folder enumeration failed: {exc}", level="WARNING")
            return

        rooms = {n: {"lights": [], "motion": [], "radiators": [],
                     "windows": [], "sensors": [], "extras": [], "cameras": []}
                 for n in room_folders}
        room_names_sorted = sorted(room_folders, key=len, reverse=True)

        # Cameras that opted into a room get attached here. Each camera dict
        # carries its own host/name/vendor — the room template uses host to
        # build the MJPEG proxy URL and name as the tile label.
        # `room` may be a single string ("Garage") OR a list (["Garage",
        # "Hall"]) so one camera can surface on multiple room pages — useful
        # when a camera is logically attached to one room's hardware but
        # operationally interesting to another (e.g. the Inside Garage cam
        # also lives on Hall because the Hall has the soft garage-door tile).
        for cam in CAMERAS:
            r = cam.get("room")
            if isinstance(r, str):
                cam_rooms = [r.strip()] if r.strip() else []
            elif isinstance(r, (list, tuple)):
                cam_rooms = [str(x).strip() for x in r if str(x).strip()]
            else:
                cam_rooms = []
            for room in cam_rooms:
                if room in rooms:
                    rooms[room]["cameras"].append({
                        "host": cam["host"],
                        "name": cam["name"],
                    })

        # Pass 1: radiators by name-prefix (regardless of folder).
        radiator_ids = set()
        for d in indigo.devices.iter():
            if not ("setpointHeat" in d.states or "setpoint" in d.states):
                continue
            for room in room_names_sorted:
                if d.name.startswith(room + " ") or d.name == room:
                    rooms[room]["radiators"].append(d.id)
                    radiator_ids.add(d.id)
                    break

        # Pass 2: classify everything else by folder.
        for d in indigo.devices.iter():
            if d.id in radiator_ids:
                continue
            room = folder_to_room.get(d.folderId)
            if not room:
                continue
            cat = self._classify_device(d)
            if cat is None:
                continue
            key = {"light":  "lights",  "motion":  "motion",
                   "window": "windows", "sensor":  "sensors",
                   "extras": "extras"}[cat]
            rooms[room][key].append(d.id)

        # Stable sort within each section by device name for predictable UI.
        # ID-based sections sort via indigo.devices[id].name. Cameras are dicts
        # (host/name) so they're sorted by the name field directly.
        try:
            name_of = lambda i: (indigo.devices[i].name or "").lower()
            ID_SECTIONS = ("lights", "motion", "radiators", "windows", "sensors", "extras")
            for room in rooms.values():
                for k in ID_SECTIONS:
                    room[k].sort(key=name_of)
                # Cameras keep DASHBOARDS_CAMERAS insertion order so the user
                # controls placement per room by editing IndigoSecrets (no
                # per-room alpha sort). "What I wrote, in that order."
        except Exception:
            pass

        # Merge per-room extras (DASHBOARDS_ROOM_EXTRAS) into the payload.
        # Order of operations:
        #   1. hideDeviceIds — drop devices from every auto-classified section
        #      (these get rendered as custom widgets, e.g. door contacts feed
        #      the door tile and shouldn't also appear under Windows & Doors)
        #   2. include — add specific device IDs to a named section even when
        #      the auto-classifier doesn't put them there (e.g. a Shelly plug
        #      that's a "charger", or a Z2M button you want surfaced under
        #      Motion to see last-pressed)
        #   3. doors — pass-through to the page template
        # Sort happens AFTER this so manually-included devices land in the
        # right alphabetical position.
        extras_cfg = self.room_extras if isinstance(self.room_extras, dict) else {}
        for room_name, room_data in rooms.items():
            cfg = extras_cfg.get(room_name) or {}
            # (1) hide
            hide_ids = set(cfg.get("hideDeviceIds") or [])
            if hide_ids:
                for k in ("lights", "motion", "radiators", "windows", "sensors", "extras"):
                    room_data[k] = [i for i in room_data[k] if i not in hide_ids]
            # (2) include — append; dedupe per section; also pull the same
            # ID out of `extras` so it doesn't appear twice when rooms.json
            # is inspected (extras isn't rendered today, but cleaner this way).
            include = cfg.get("include") or {}
            if isinstance(include, dict):
                all_pinned = set()
                for section, ids in include.items():
                    if section not in ("lights", "motion", "radiators", "windows", "sensors", "extras"):
                        continue
                    if not isinstance(ids, (list, tuple)):
                        continue
                    existing = set(room_data[section])
                    for did in ids:
                        if isinstance(did, int) and did not in existing:
                            room_data[section].append(did)
                            existing.add(did)
                            all_pinned.add(did)
                # Drop included IDs from extras unless extras was itself the target.
                if "extras" not in include:
                    room_data["extras"] = [i for i in room_data["extras"]
                                           if i not in all_pinned]
            # (2c) appliances — read-only paired tiles (power meter + cycle
            # state virtual) for things like the washing machine / tumble
            # dryer. Pass-through; the room template renders them in a
            # dedicated "Appliances" section.
            appliances = cfg.get("appliances") or []
            if appliances:
                room_data["appliances"] = list(appliances)
            # (2d) tv — list of device IDs that should appear in a "TV"
            # section as toggleable light-style tiles (Sony TV + Sonos
            # speakers in the Living Room). Render uses the same tile shape
            # as lights but lives under its own header with an All On/Off.
            tv_ids = cfg.get("tv") or []
            if isinstance(tv_ids, (list, tuple)) and tv_ids:
                room_data["tv"] = [int(i) for i in tv_ids
                                   if isinstance(i, int)]
            # (2e) plugs — mains sockets / smart plugs rendered as toggleable
            # tiles under their own "Plugs & Sockets" header (same tile shape
            # as Lights/TV). A socket is not a light: keeping them separate
            # stops the hub tile counting a garage socket as "1 light on"
            # (CliveS, 13-Jul-2026). Pinned ids are removed from the
            # auto-classified sections so they can't appear twice.
            plug_ids = cfg.get("plugs") or []
            if isinstance(plug_ids, (list, tuple)) and plug_ids:
                plugs_clean = [int(i) for i in plug_ids if isinstance(i, int)]
                if plugs_clean:
                    room_data["plugs"] = plugs_clean
                    pinned = set(plugs_clean)
                    for k in ("lights", "motion", "radiators",
                              "windows", "sensors", "extras"):
                        room_data[k] = [i for i in room_data[k]
                                        if i not in pinned]
            # (2f) fire — the living room fire, and anything else of that
            # shape: an on/off appliance that is neither a light nor a socket.
            # Same toggleable tile as Lights/TV/Plugs under its own "Fire"
            # header. It is deliberately NOT pinned into `lights`: a fire is
            # not a light, and counting one would put "1 light on" on the hub
            # tile for a lit fire — the same reasoning that gave sockets their
            # own section (CliveS, 13-Jul-2026). Pinned ids are pulled out of
            # the auto-classified sections so they cannot appear twice; the
            # fire lands in `extras` by default, which nothing renders, which
            # is why it was invisible until now.
            fire_ids = cfg.get("fire") or []
            if isinstance(fire_ids, (list, tuple)) and fire_ids:
                fire_clean = [int(i) for i in fire_ids if isinstance(i, int)]
                if fire_clean:
                    room_data["fire"] = fire_clean
                    pinned = set(fire_clean)
                    for k in ("lights", "motion", "radiators",
                              "windows", "sensors", "extras"):
                        room_data[k] = [i for i in room_data[k]
                                        if i not in pinned]
            # (2g) openLoop — devices whose state is a BELIEF, not a reading.
            # The living room fire is a one-way RF relay: onOffState is only
            # what was last transmitted, so if it is lit from its own handset
            # Indigo still says off. Such a device must not get a vote in any
            # decision DERIVED from state — notably whether the Lights section's
            # bulk button offers "All On" or "All Off" — because one unreadable
            # device would otherwise veto the button the user wanted. It is
            # still COMMANDED with everything else, so an "All Off" reaches it
            # whatever anyone believes. A vote in the command, not in the
            # decision.
            open_loop = cfg.get("openLoop") or []
            if isinstance(open_loop, (list, tuple)) and open_loop:
                clean_ol = [int(i) for i in open_loop if isinstance(i, int)]
                if clean_ol:
                    room_data["openLoop"] = clean_ol
            # (2h) mainLight — lights the room's bulk "All On / All Off" must
            # LEAVE ALONE. The room's main light, typically: you want the lamps
            # off in one press without also killing the ceiling light, or on
            # without it blazing.
            #
            # Deliberately NOT pinned out of `lights` the way plugs and fire
            # are: it is still a light, it still renders as its own tile, and
            # it is still switchable on its own. The only thing it is out of is
            # the group. That is the whole distinction — plugs and fire are a
            # different KIND of thing and get their own section, this is the
            # same kind of thing held back from one action.
            main_light = cfg.get("mainLight") or []
            if isinstance(main_light, (list, tuple)) and main_light:
                clean_ml = [int(i) for i in main_light if isinstance(i, int)]
                if clean_ml:
                    room_data["mainLight"] = clean_ml
            # (3) doors
            doors = cfg.get("doors") or []
            if doors:
                room_data["doors"] = list(doors)
                # Auto-hide the devices that feed the door tile (relay openers
                # and status contact sensors) so they don't ALSO show up as
                # stray tiles in Lights / Windows & Doors. Saves the user
                # having to repeat those IDs under hideDeviceIds.
                auto_hide = set()
                for d in doors:
                    if not isinstance(d, dict):
                        continue
                    for rid in (d.get("relayIds") or []):
                        if isinstance(rid, int):
                            auto_hide.add(rid)
                    sc = d.get("statusContactId")
                    if isinstance(sc, int):
                        auto_hide.add(sc)
                if auto_hide:
                    for k in ("lights", "motion", "radiators",
                              "windows", "sensors", "extras"):
                        room_data[k] = [i for i in room_data[k]
                                        if i not in auto_hide]

        # Re-sort sections after include-merge so manually-added IDs slot in
        # alphabetically next to the auto-classified ones — UNLESS the room
        # config supplies a `sortOrder` map for that section, in which case
        # the listed IDs land first in the given order and any unlisted IDs
        # fall in alphabetically behind them. Useful when the alphabetical
        # default produces an unintuitive grouping (e.g. Conservatory wants
        # both windows first and then both doors, not Left-Outside-Right-
        # Sliding interleaved).
        try:
            name_of2 = lambda i: (indigo.devices[i].name or "").lower()
            for room_name, room in rooms.items():
                cfg = extras_cfg.get(room_name) or {}
                sort_order = cfg.get("sortOrder") or {}
                for k in ("lights", "motion", "radiators",
                          "windows", "sensors", "extras"):
                    explicit = sort_order.get(k) if isinstance(sort_order, dict) else None
                    if isinstance(explicit, (list, tuple)) and explicit:
                        # Listed-first (in the given order), then anything
                        # not listed sorted alphabetically by device name.
                        listed = [i for i in explicit if i in room[k]]
                        rest   = sorted(
                            (i for i in room[k] if i not in listed),
                            key=name_of2,
                        )
                        room[k] = listed + rest
                    else:
                        room[k].sort(key=name_of2)
        except Exception:
            pass

        payload = {
            "_writeTs": time.time(),
            "rooms":    rooms,
        }
        try:
            path = os.path.join(self._public_dashboards_dir(), "rooms.json")
            self._write_atomic(path, json.dumps(payload, indent=2).encode("utf-8"))
        except Exception as exc:
            log(f"[Rooms] rooms.json write failed: {exc}", level="WARNING")
        return payload   # also return it so callers (e.g. timeline) can use it

    def _snapshot_worker(self, cam):
        """Fetch and store ONE camera's snapshot. Runs on a pool thread.

        Kept deliberately self-contained: it touches only this camera's own
        entry in self._cam_state (pre-created on the caller's thread) and its
        own file, so no two workers can contend for anything.
        """
        host = cam["host"]
        st   = self._cam_state[host]
        try:
            ok, payload = self._fetch_one_snapshot(host)
            now = time.time()
            if ok:
                try:
                    self._write_atomic(self._cam_jpg_path(host), payload)
                    # The grid's smaller copy. Written SECOND and separately so a
                    # resize failure can never cost us the full-size picture,
                    # which is the one thing here that must always be there.
                    thumb = self._make_thumb(payload)
                    if thumb:
                        self._write_atomic(self._cam_thumb_path(host), thumb)
                    st["ok_count"] += 1
                    st["last_ok"] = now
                    if st["fail_count"] >= 3:                 # camera came back
                        log(f"[Cameras] {cam['name']} ({host}) recovered after {st['fail_count']} failures")
                    st["fail_count"] = 0
                except Exception as exc:
                    log(f"[Cameras] Could not write snapshot for {host}: {exc}", level="ERROR")
            else:
                st["fail_count"] += 1
                st["last_failure"] = now
                # Log on 1st failure and then every 60s while it keeps failing.
                if st["fail_count"] == 1 or (now - st["last_log"]) > 60:
                    log(f"[Cameras] {cam['name']} ({host}) snapshot failed: {payload}", level="WARNING")
                    st["last_log"] = now
        finally:
            with self._cam_inflight_lock:
                self._cam_inflight.discard(host)

    def _poll_cameras_once(self):
        """One sweep over every configured camera, live-viewed or not. Logs
        failures throttled (state stored in self._cam_state) so the event log
        doesn't flood when a camera is offline for hours.

        The fetches run CONCURRENTLY. Serially, nine cameras took longer than
        the 2 s poll interval, so passes ran back-to-back and each camera was
        only refreshed every ~4 s (measured: mean 4.1 s over a 30 s window
        across all nine). That is the floor on how fresh a dashboard tile can
        possibly be, and it is most of the "the stills are five to ten seconds
        behind" report — a client polling every 3 s was re-fetching a file that
        only changed every 4 s.

        Fetching is pure network wait, so overlapping it costs nothing and the
        pass takes as long as the SLOWEST camera rather than the sum of all
        nine. A camera already in flight is not re-submitted, so a dead one
        (15 s timeout) delays only itself and can never make passes pile up.
        """
        streams = self._fetch_go2rtc_streams()
        # Mirror the streams JSON for the dashboard bandwidth indicator.
        self._write_streams_json(streams)
        # (rooms.json is rebuilt on the 30 s sweep, not here — rebuilding and
        # rewriting it every 2 s cost a full folder+device enumeration and a
        # disk write per camera tick for a file that changes on renames.)

        pool = self._snapshot_pool()
        if pool is None:                      # shutting down
            return
        for cam in CAMERAS:
            host = cam["host"]
            # EVERY camera is snapshotted, including any with a live viewer.
            #
            # This used to skip a camera with an active MJPEG consumer, on the
            # reasoning that whoever was watching the stream did not need the
            # still. That stopped being true the moment off-LAN became
            # all-stills: the live watcher and the still watcher are now
            # usually DIFFERENT PEOPLE. One browser open at home held six
            # streams and froze those six cameras' snapshots for everyone
            # else — measured live at 294-298 s stale on exactly the six
            # hosts that had consumers, while the three without were 0-2 s
            # fresh. That is the "some tiles never update" report.
            #
            # The skip was added in v1.13.x against a real frame.jpeg-vs-ffmpeg
            # race that produced HTTP 500s, but that race was on the `_mjpeg`
            # DERIVED stream. The poller asks the RAW stream now, so it no
            # longer applies: verified with a live consumer attached, six
            # consecutive snapshots returned 200 at the correct 640x360 in
            # 0.16-0.27 s and the live stream was undisturbed. The cost of
            # always snapshotting is one ~25 KB loopback fetch per camera per
            # tick, which is nothing next to a tile that never changes.
            # Pre-create the state entry HERE, on this one thread, so the
            # workers only ever read and mutate an entry that already exists.
            self._cam_state.setdefault(host, {"ok_count": 0, "fail_count": 0, "last_log": 0,
                                               "last_ok": None, "last_failure": None})
            with self._cam_inflight_lock:
                if host in self._cam_inflight:
                    continue                  # previous fetch still running
                self._cam_inflight.add(host)
            try:
                pool.submit(self._snapshot_worker, cam)
            except Exception:
                # Pool refused the work (shutting down) — release the slot so
                # the camera is not left permanently marked in-flight.
                with self._cam_inflight_lock:
                    self._cam_inflight.discard(host)
                if getattr(self, "_cam_pool_closed", False):
                    return                     # shutdown race, not a fault
                raise

    # --------------------------------------------------------
    # Weather card extras (Sunset + OWM forecast → weather.json)
    # --------------------------------------------------------

    _WEATHER_POLL_SECONDS = 60 * 60          # OWM call cadence (free-tier safe)

    def _start_weather_thread(self):
        """Spawn the hourly OWM fetch on its own thread. No-op if either the
        API key OR lat/long is missing — the rest of the Weather card still
        works (the Ecowitt-derived lines render unconditionally), and
        weather.json simply never appears."""
        def _f(v):
            try:
                return float(v) if str(v).strip() != "" else None
            except (TypeError, ValueError):
                return None
        # IndigoSecrets first, PluginConfig fallback — the plugin's own
        # documented credential policy, which this thread alone ignored.
        self._owm_key = OWM_API_KEY or (self.pluginPrefs.get("owmApiKey", "") or "").strip()
        # A secrets value of 0.0 is the TEMPLATE placeholder, not a site in
        # the Gulf of Guinea (v2.95.1): it used to beat the PluginConfig
        # fields for anyone who kept IndigoSecrets_example.py's defaults.
        self._owm_lat = _f(LATITUDE) or _f(self.pluginPrefs.get("siteLatitude"))
        self._owm_lon = _f(LONGITUDE) or _f(self.pluginPrefs.get("siteLongitude"))
        if not (self._owm_key and self._owm_lat is not None and self._owm_lon is not None):
            log("[Weather] Skipping — OWM key / latitude / longitude not set in "
                "IndigoSecrets or PluginConfig; hub Weather card will use Ecowitt only.",
                level="INFO")
            return
        self._weather_thread = threading.Thread(
            target=self._weather_thread_main,
            name="dashboards-weather",
            daemon=True,
        )
        self._weather_thread.start()

    def _stop_weather_thread(self):
        if self._weather_stop:
            self._weather_stop.set()
        t = self._weather_thread
        if t and t.is_alive():
            # 1 s, not 3: the thread is a daemon and dies with the process; the
            # join only lets a fetch that is a moment from finishing land.
            t.join(timeout=1.0)

    def _weather_thread_main(self):
        """Hit OWM once on entry then every _WEATHER_POLL_SECONDS until stop.
        The stop Event lets us wake up promptly on shutdown rather than
        sleeping out the full hour."""
        # First fetch is fast — get the page into a useful state on next refresh.
        self._fetch_and_write_weather()
        while not self._weather_stop.wait(self._WEATHER_POLL_SECONDS):
            self._fetch_and_write_weather()

    def _fetch_and_write_weather(self):
        """One OWM round-trip → weather.json in the public dir. All exceptions
        swallowed and logged — a failed fetch must not take the thread down."""
        try:
            data = self._fetch_owm_onecall()
            if not data:
                return
            payload = self._build_weather_payload(data)
            path = os.path.join(self._public_dashboards_dir(), "weather.json")
            self._write_atomic(path, json.dumps(payload, indent=2).encode("utf-8"))
        except Exception as exc:
            log(f"[Weather] Fetch failed: {exc}", level="WARNING")

    def _fetch_owm_onecall(self):
        """OpenWeatherMap One Call API 3.0 — current weather + daily forecast
        + sunset/sunrise + UV in a single request. Uses the v3 endpoint
        (1000 calls/day free tier with "One Call by Call" subscription;
        Highsteads' OWM_API_KEY is already provisioned for it because
        EvoHomeControl uses the same endpoint). Returns the parsed dict on
        success, None on any HTTP/JSON failure (the caller logs)."""
        import urllib.request
        import urllib.parse
        params = {
            "lat":     str(self._owm_lat),
            "lon":     str(self._owm_lon),
            "exclude": "minutely,hourly,alerts",
            "appid":   self._owm_key,
            "units":   "metric",
        }
        url = "https://api.openweathermap.org/data/3.0/onecall?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": f"Dashboards/{PLUGIN_VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    log(f"[Weather] OWM HTTP {resp.status}", level="WARNING")
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log(f"[Weather] OWM request error: {exc}", level="WARNING")
            return None

    def _build_weather_payload(self, owm):
        """Pull the slim subset of the OWM response that the hub page needs.
        Keeps the JSON small — the page reads it with cache: no-store every
        render. Fields:
          sunrise/sunset   — today (unix epoch seconds, UTC; page formats to
                             local time using tz_offset).
          today_min/_max   — daily forecast high/low (°C).
          today_summary    — text description, e.g. "Clear Sky".
          today_icon       — OWM icon code (e.g. 01d) for emoji mapping.
          now_uvi          — current UV index (0–11+).
          now_conditions   — current weather description (may differ from
                             today_summary which is the daily aggregate).
          tz_offset        — seconds offset from UTC; used by page for
                             local-time formatting of sunrise/sunset.
        """
        today    = (owm.get("daily") or [{}])[0]
        current  = owm.get("current") or {}
        temp     = today.get("temp") or {}
        d_weather = (today.get("weather") or [{}])[0]
        c_weather = (current.get("weather") or [{}])[0]
        return {
            "_writeTs":       time.time(),
            "sunset":         today.get("sunset")  or current.get("sunset"),
            "sunrise":        today.get("sunrise") or current.get("sunrise"),
            "today_min":      temp.get("min"),
            "today_max":      temp.get("max"),
            "today_summary":  d_weather.get("description", "").title(),
            "today_icon":     d_weather.get("icon", ""),
            "now_uvi":        current.get("uvi"),
            "now_conditions": c_weather.get("description", "").title(),
            "now_icon":       c_weather.get("icon", ""),
            "tz_offset":      owm.get("timezone_offset"),
        }

    def _run_presence_watch(self):
        """Tick the standalone Presence_Watch.py script — the single source of
        truth for the presence-timeline logic — to refresh the presence data
        the presenceData endpoint serves (Python Scripts/presence_data.json;
        NOT /public since v2.71.0). Quiet: the script only logs its success
        line when run by hand (PRESENCE_WATCH_QUIET); errors still surface."""
        self._tick_script("presence")

    def _run_log_error_watch(self):
        """Tick the standalone Log_Error_Watch.py script — the single source of
        truth for what counts as a real, new event-log error — which refreshes
        the state file the logErrors endpoint serves. Quiet: the script only
        logs its "nothing new" line when run by hand; a genuine find still logs
        at WARNING and sends its own Pushover + email.

        Driving it from here rather than an Indigo schedule is deliberate — the
        IOM can create a schedule but cannot set its ACTION STEP, so a scripted
        schedule would sit there running nothing. The cost is that the watch
        stops if this plugin is disabled; add a UI schedule alongside if you
        want it independent (the script's flock + state make a double-run safe).
        """
        self._tick_script("logwatch")
        self._check_log_watch_alive()

    def _run_drive_lights_sun(self):
        """Tick Drive_Lights_Sun.py — the Garage and Front Door lights held on
        at 100% from sunset to sunrise.

        Driven from here for the usual reason: indigo.schedule.create() takes
        no ACTION STEP, and a schedule's timing fields are read-only through
        the API, so neither a new schedule nor retiming the old one is possible
        from code.

        Ticking beats firing once at sunset anyway, because it SELF-HEALS. A
        missed Zigbee command, a bulb that dropped off the mesh and rejoined, a
        power cut at 3am — the next tick puts it right, where a single
        sunset-edge command leaves the light wrong until the following night.
        The script only commands on a mismatch, so a correct night is silent.
        """
        self._tick_script("drivelights")

    def _run_night_lights_sweep(self):
        """Tick Night_Lights_Sweep.py — the overnight backstop that turns off a
        light burning in an empty room, and asserts the living room fire off.

        Driven from here rather than an Indigo schedule for the usual reason:
        the IOM can create a schedule but cannot set its ACTION STEP, so a
        scripted schedule would sit there running nothing.

        EVERY 2 MINUTES, and that cadence is load-bearing. The script only acts
        after an UNBROKEN run of observations, and it discards every streak if
        the previous run was more than MAX_GAP_MINUTES (10) ago — because
        nothing watched that gap. Slow this down past 10 minutes and the sweep
        never acts at all. It fails safe, but silently, so do not tune this
        without reading that guard.

        Cheap: outside its night window the script reads two variables and
        returns, so a daytime tick is a few microseconds.
        """
        self._tick_script("nightsweep")

    def _run_reflector_bandwidth_watch(self):
        """Meter the Indigo reflector's SSH tunnel (v3.0.0).

        Indigo Domotics wrote twice about this house's reflector usage and
        deactivated the reflector the second time, and nothing here could say
        how much had gone through it or when — IWS logs no successful request,
        and the tunnel is invisible to lsof and netstat. This samples the one
        process that IS the tunnel and keeps an hourly record.

        Every 5 minutes: the script's own work is two short subprocess calls,
        and the deltas it accumulates are what make an hour meaningful.
        """
        self._tick_script("reflectorbw")

    def _run_fp300_config_watch(self):
        """Tick the standalone FP300_Config_Watch.py script — the watch on the
        Aqara FP300 presence sensors' DEVICE-SIDE configuration.

        Those settings live on the sensor, not in Indigo, so a battery pull or
        button reset silently returns them to the firmware defaults and nothing
        notices. That is exactly what happened on 06-07-2026: adaptive
        sensitivity went back ON for four weeks, and presence fragmented all
        night because the radar re-learns a motionless sleeper as background.

        The script only writes while a sensor reports presence — an FP300 is a
        sleepy battery device and z2m does not reliably queue a write for one —
        so most ticks do nothing at all. Quiet: it only logs its "all sensors
        hold the intended configuration" line when run by hand; genuine drift
        still logs at WARNING.

        Driven from here for the same reason as the log watch: the IOM can
        create a schedule but cannot set its ACTION STEP, so a scripted
        schedule would sit there running nothing.
        """
        self._tick_script("fp300watch")

    def _run_appliance_scheduler(self):
        """Refresh the laundry plan. Appliance_Scheduler.py writes it to
        Python Scripts/appliance_plan.json; handleLaundryPlan serves it.

        Deliberately NOT copied into public/dashboards/. A laundry plan is behavioural —
        it says when this household washes and what the battery is holding — and
        presence.json was moved off anonymous /public in v1.1 for precisely that reason.
        The usual argument for a static file is that a page polling /message/ can wedge
        the IWS event loop for five minutes across a plugin restart, and the v2.70.0
        liveness gate already answers that: every page checks the stamp and backs off.
        """
        if not self._sigen_available():
            # Nothing to plan from without SigenEnergyManager's forecast, site
            # config and rates (v3.13.0); the script would only say so in its
            # own log every fifteen minutes.
            return
        self._tick_script("laundry")

    def _read_laundry_plan(self):
        """The plan as the script last wrote it, or None. Absent is not an error — the
        script says why in its own log, and a page that shows nothing is honest."""
        try:
            with open(os.path.join(self._scripts_dir(), "appliance_plan.json"),
                      encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ── Companion scripts (v2.95.2: ONE runner for all five) ───────────────
    # Each is exec()ed from this host with `indigo` injected, so module-level
    # code re-runs every tick and anything it changes in the host PERSISTS:
    # sys.path grew by one entry a tick until the scripts learned to guard
    # their inserts, and it is snapshotted and restored here regardless.
    # TICK_MEMORY is a per-script dict that survives between ticks, so a
    # script can warn ONCE about a missing device rather than every two
    # minutes. Failures: the first is logged WITH its traceback (a syntax
    # error in an edited script used to be one bare line, 720 times a day,
    # with no line number), repeats stay silent until the text changes, and
    # the first success afterwards logs a recovery.
    COMPANION_SCRIPTS = {
        "presence":    ("Presence_Watch.py",     "[Presence]",   {"PRESENCE_WATCH_QUIET": True},
                        "the Presence tile needs Presence_Watch.py from the repo's scripts/ "
                        "folder (copied into Python Scripts/ and edited for your rooms)"),
        "logwatch":    ("Log_Error_Watch.py",    "[LogWatch]",   {"LOG_ERROR_WATCH_QUIET": True},
                        "the hourly log-error watch needs Log_Error_Watch.py from the repo's "
                        "scripts/ folder (copied into Python Scripts/)"),
        "drivelights": ("Drive_Lights_Sun.py",   "[DriveLights]", {},
                        "the sunset-to-sunrise drive lights need Drive_Lights_Sun.py in "
                        "Python Scripts/ (repo scripts/ folder, edited for your lights)"),
        "nightsweep":  ("Night_Lights_Sweep.py", "[NightSweep]", {},
                        "the overnight lights sweep needs Night_Lights_Sweep.py in "
                        "Python Scripts/ (repo scripts/ folder, edited for your rooms)"),
        "laundry":     ("Appliance_Scheduler.py", "[Laundry]",   {"APPLIANCE_SCHEDULER_QUIET": True},
                        "the laundry page needs Appliance_Scheduler.py and appliance_planner.py "
                        "in Python Scripts/ (repo scripts/ folder)"),
        "fp300watch":  ("FP300_Config_Watch.py", "[FP300Watch]", {"FP300_CONFIG_WATCH_QUIET": True},
                        "the hourly presence-sensor config watch needs FP300_Config_Watch.py "
                        "from the repo's scripts/ folder (copied into Python Scripts/)"),
        "reflectorbw": ("Reflector_Bandwidth_Watch.py", "[ReflectorBW]", {},
                        "the reflector bandwidth meter needs Reflector_Bandwidth_Watch.py "
                        "from the repo's scripts/ folder (copied into Python Scripts/)"),
    }

    def _scripts_dir(self):
        # Python Scripts lives at the Perceptive Automation ROOT (shared across
        # Indigo versions), NOT under the versioned install folder that
        # getInstallFolderPath() returns — so go up one level.
        return os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                            "Python Scripts")

    def _tick_script(self, key):
        """Run one companion script once. Returns True on a clean run."""
        import traceback as _tb
        name, tag, extra, hint = self.COMPANION_SCRIPTS[key]
        path = os.path.join(self._scripts_dir(), name)
        memory = self.__dict__.setdefault("_tick_memory", {}).setdefault(key, {})
        errors = self.__dict__.setdefault("_script_errors", {})
        missing = self.__dict__.setdefault("_script_missing_logged", set())
        try:
            if not os.path.isfile(path):
                missing.add(key)               # reported once, in one line, after the seed pass
                return False
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            saved_path = list(_sys.path)
            g = {"indigo": indigo, "TICK_MEMORY": memory}
            g.update(extra)
            try:
                exec(compile(src, path, "exec"), g)
            finally:
                _sys.path[:] = saved_path
        except Exception as exc:               # noqa: BLE001 — isolate, report once
            text = f"{type(exc).__name__}: {exc}"
            if errors.get(key) != text:
                errors[key] = text
                self.logger.warning(f"{tag} tick failed: {text}\n{_tb.format_exc()}")
            return False
        if errors.pop(key, None):
            self.logger.info(f"{tag} recovered")
        return True

    def _check_log_watch_alive(self):
        """The watch on the event log has no watchdog of its own — if it dies
        deterministically, every downstream consumer (Pushover, the Alerts
        page, the triage feed) just sees 'nothing new'. This host ticks it, so
        this host checks its pulse: the state file it rewrites on every good
        run carries last_run, and a stamp older than two intervals means the
        estate's only log watch is not watching. One ERROR a day, not one an
        hour, and only when the script is actually installed."""
        state_path = os.path.join(self._scripts_dir(), "log_error_watch_state.json")
        if not os.path.isfile(os.path.join(self._scripts_dir(), "Log_Error_Watch.py")):
            return
        stale_after = 2 * LOG_WATCH_REFRESH_SECONDS + 600
        try:
            with open(state_path, encoding="utf-8") as fh:
                last = (json.load(fh) or {}).get("last_run") or ""
            age = time.time() - time.mktime(datetime.strptime(last, "%Y-%m-%d %H:%M:%S").timetuple())
        except FileNotFoundError:
            return                            # first run has not happened yet
        except Exception:
            age = float("inf")
        if age <= stale_after:
            return
        last_shout = self.__dict__.get("_logwatch_dead_logged_at", 0.0)
        if time.time() - last_shout < 86400:
            return
        self._logwatch_dead_logged_at = time.time()
        shown = "never" if age == float("inf") else f"{age / 3600:.1f} h ago"
        self.logger.error(
            f"[LogWatch] Log_Error_Watch.py has not completed a run since {shown} — the "
            f"event-log watch is NOT watching. Look for its own 'Log Error Watch FAILED' "
            f"lines above; nothing downstream (Pushover, the Alerts page, the triage "
            f"feed) will notice a new error until it runs again.")

    def runConcurrentThread(self):
        """Main background loop. Indigo calls this once after startup; we keep
        looping until self.stopThread is set during shutdown. self.sleep()
        raises self.StopThread on shutdown — catching it exits cleanly.

        Every task runs in its OWN isolation (v2.95.2). Until then the whole
        tick shared one try/except, so a builder that failed every time (one
        bad roomExtras value in rooms.json, say) threw before the tasks behind
        it and switched off the log watch, the night sweep and the drive
        lights together — with one WARNING and then silence. Now each task
        fails alone, says so once, and says so again when it recovers.
        Builds rooms.json on every cycle regardless of whether cameras are
        configured — the room template needs it even on cam-less installs."""
        failures = self.__dict__.setdefault("_step_failures", {})

        def step(name, fn):
            try:
                fn()
            except self.StopThread:
                raise
            except Exception as exc:            # noqa: BLE001 — one task, not the loop
                n = failures.get(name, 0) + 1
                failures[name] = n
                if n == 1:
                    log(f"[Poller] {name} failed (will keep retrying): {exc}", level="WARNING")
                else:
                    self.logger.debug(f"[Poller] {name} failed x{n}: {exc}")
                return False
            if failures.pop(name, None):
                log(f"[Poller] {name} recovered")
            return True

        cameras_on = bool(self.cam_user and self.cam_pass and CAMERAS)
        if cameras_on:
            self._activity(f"[Cameras] Poller started - {len(CAMERAS)} camera(s), "
                           f"every {CAMERA_POLL_SECONDS}s")
        elif CAMERAS:
            log("[Cameras] cameras are configured but DAHUA_USER/DAHUA_PASS are not set — "
                "snapshot poller idle", level="WARNING")
        else:
            self.logger.info("[Cameras] no cameras configured — camera features off")
        tick = CAMERA_POLL_SECONDS if cameras_on else 30.0
        last = {"link": 0.0, "presence": 0.0, "logwatch": 0.0, "fp300": 0.0, "sweep": 0.0,
                "reflectorbw": 0.0, "laundry": 0.0}
        try:
            # Seed immediately, isolated like everything else (these three used
            # to run bare, so one bad value killed the loop before it began).
            step("rooms.json", self._build_rooms_json)
            step("scenes.json", self._build_scenes_json)
            step("presence watch", self._run_presence_watch)
            last["presence"] = time.time()
            # One line for every optional script that is not installed
            # (v2.96.0). Five separate lines used to greet every fresh
            # install, two of them about one house's lighting automations.
            try:
                absent = [v[0] for v in self.COMPANION_SCRIPTS.values()
                          if not os.path.isfile(os.path.join(self._scripts_dir(), v[0]))]
                if absent:
                    self.logger.info(f"[Scripts] optional companion scripts not installed: "
                                     f"{', '.join(absent)} — the dashboards work without them; "
                                     f"see scripts/README.md in the repo if you want any")
            except Exception:
                pass
            while True:
                t0 = time.time()
                if cameras_on:
                    step("camera poll", self._poll_cameras_once)
                if t0 - last["link"] > 30.0:
                    step("rooms.json", self._build_rooms_json)          # folder moves/renames
                    step("scenes.json", self._build_scenes_json)        # action groups change rarely
                    step("setup-link sweep", self._cleanup_setup_links)
                    step("change-ledger prune", self._prune_change_ledger)
                    step("feature flags", self._refresh_feature_flags)   # an optional plugin came or went
                    if cameras_on:
                        step("go2rtc supervisor", self._supervise_go2rtc)   # restart a crashed go2rtc
                    last["link"] = t0
                if t0 - last["presence"] > PRESENCE_REFRESH_SECONDS:
                    step("presence watch", self._run_presence_watch)
                    last["presence"] = t0
                if t0 - last["logwatch"] > LOG_WATCH_REFRESH_SECONDS:
                    step("log watch", self._run_log_error_watch)           # hourly event-log error watch
                    last["logwatch"] = t0
                if t0 - last["fp300"] > FP300_WATCH_REFRESH_SECONDS:
                    step("FP300 watch", self._run_fp300_config_watch)     # hourly config-drift watch
                    last["fp300"] = t0
                if t0 - last["laundry"] > LAUNDRY_REFRESH_SECONDS:
                    step("laundry plan", self._run_appliance_scheduler)
                    last["laundry"] = t0
                if t0 - last["reflectorbw"] > REFLECTOR_BW_REFRESH_SECONDS:
                    step("reflector meter", self._run_reflector_bandwidth_watch)
                    last["reflectorbw"] = t0
                if t0 - last["sweep"] > NIGHT_SWEEP_REFRESH_SECONDS:
                    step("night sweep", self._run_night_lights_sweep)     # 2-min overnight backstop
                    step("drive lights", self._run_drive_lights_sun)      # sunset->sunrise drive lights
                    last["sweep"] = t0
                dt = time.time() - t0
                self.sleep(max(0.1, tick - dt))
        except self.StopThread:
            self._activity("[Cameras] Poller stopped" if cameras_on else "[Poller] stopped")

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def startup(self):
        self._cam_state    = {}                              # populated by poller
        # Hosts with a snapshot fetch in flight, so a slow camera is
        # never re-submitted and passes cannot pile up on it.
        self._cam_inflight = set()
        self._thumb_broken = False       # latched once Pillow is known missing
        self._thumb_last_log = 0.0       # throttles per-frame resize complaints
        self._cam_inflight_lock = threading.Lock()
        self._cam_pool     = None
        self._cam_pool_closed = False
        self._mjpeg_server = None
        self._go2rtc_proc  = None
        self._weather_stop = threading.Event()
        self._weather_thread = None
        self._script_missing_logged = set()   # once-per-boot missing-script notes
        # v2.70.0 liveness stamp — see the STAMP_* constants for why.
        self._stamp_stop       = threading.Event()
        self._stamp_lock       = threading.Lock()
        self._stamp_thread     = None
        self._boot_ts          = time.time()
        self._stamp_last_write = 0.0
        # v1.22.0 delta updates: ledger of device-change timestamps fed by
        # subscribeToChanges, served to the pages via the changedSince
        # endpoint so they refetch only what actually changed.
        self._dev_changes  = {}                              # dev id -> epoch
        self._dev_deleted  = {}                              # dev id -> epoch
        indigo.devices.subscribeToChanges()
        self._sync_pages_to_public()
        # v2.71.0: presence data moved OUT of the anonymous /public namespace
        # (14 nights of bedroom occupancy were internet-readable over the
        # reflector). Sweep the old copy so every install heals on upgrade —
        # the .json extension is deliberately preserved by the page sync's
        # stale sweep, so it needs this explicit removal.
        try:
            _legacy = os.path.join(self._public_dashboards_dir(), "presence.json")
            if os.path.isfile(_legacy):
                os.remove(_legacy)
                self.logger.info("[Presence] removed the pre-v2.71.0 anonymous "
                                 "/public/dashboards/presence.json")
        except OSError as exc:
            self.logger.warning(f"[Presence] could not remove legacy presence.json: {exc}")
        self._mirror_custom_pages()
        self._write_config_js()
        self._sync_pages_to_domio()
        self._cleanup_setup_links(force_all=True)    # no links survive a restart
        self._start_mjpeg_proxy()
        self._start_go2rtc()
        self._mirror_go2rtc_assets()
        self._start_weather_thread()
        self._start_stamp_thread()
        self.logger.info(self._startup_summary())
        # v3.12.0: tell any MCP server that reads provider manifests that this
        # plugin's tools are ready (it re-reads mcp-manifest.json on receipt).
        # A harmless no-op when nobody subscribes; guarded so it can never
        # affect startup.
        try:
            indigo.server.broadcastToSubscribers("mcp_tools_updated")
        except Exception:
            pass

    def stopConcurrentThread(self):
        # Freeze the stamp at the FIRST sign of a stop — Indigo calls this
        # before it waits out runConcurrentThread and long before shutdown()'s
        # teardown, so gated pages go quiet while the host is still healthy.
        self._freeze_stamp()
        super().stopConcurrentThread()

    def shutdown(self):
        self._freeze_stamp()          # idempotent belt-and-braces
        # Quiesce: stay alive while gated pages notice the sentinel and stop
        # polling — see STAMP_QUIESCE_SECONDS. Must run BEFORE any teardown.
        time.sleep(STAMP_QUIESCE_SECONDS)
        self._stop_stamp_thread()
        # The teardown is BUDGETED, not summed (v2.95.1). go2rtc goes first:
        # a snapshot worker blocked in requests.get() against it fails the
        # instant the loopback listener closes, instead of running out a 15 s
        # timeout (and a retry) while the host waits. The pool is then told
        # not to wait at all — its workers are daemon threads and
        # _write_atomic already guarantees a file is either the old one or the
        # new one — and the remaining joins are each a second or less. Indigo
        # gives a plugin ~20 s to quit politely; before this, one camera
        # offline at the moment of a restart could take teardown past it, the
        # host was force-killed, this function never finished, and go2rtc was
        # left orphaned for the next boot's port-conflict path to hunt.
        self._cam_pool_closed = True
        self._stop_go2rtc()
        self._stop_snapshot_pool()
        self._stop_mjpeg_proxy()
        self._stop_weather_thread()
        # Indigo logs its own "Stopped plugin" line, so this one only ever
        # doubled it up in the shared log.
        self._activity(f"{self.pluginDisplayName} stopped")

    # --------------------------------------------------------
    # Device-change ledger (v1.22.0) — feeds the changedSince endpoint
    # --------------------------------------------------------

    def deviceUpdated(self, orig_dev, new_dev):
        super().deviceUpdated(orig_dev, new_dev)
        if new_dev.pluginId == self.pluginId:   # ignore own device updates (loop guard)
            return
        self._dev_changes[new_dev.id] = time.time()
        self._stamp_note_change()

    def deviceCreated(self, dev):
        super().deviceCreated(dev)
        self._dev_changes[dev.id] = time.time()
        self._stamp_note_change()

    def deviceDeleted(self, dev):
        super().deviceDeleted(dev)
        self._dev_changes.pop(dev.id, None)
        self._dev_deleted[dev.id] = time.time()
        self._stamp_note_change()

    # ── Liveness stamp (v2.70.0) — /public/dashboards/changed.stamp ─────────
    # Written every STAMP_PERIOD_SECONDS by a dedicated daemon thread, plus a
    # throttled leading-edge write from the ledger callbacks so a change never
    # waits the full period to surface. The lock + stop-event ordering below
    # guarantees a late "run" write can never clobber the "stopping" sentinel:
    # every writer takes the lock, and the run-writers re-check the stop event
    # INSIDE it, while _freeze_stamp sets the event before taking the lock.

    def _stamp_path(self):
        return os.path.join(self._public_dashboards_dir(), STAMP_FILENAME)

    def _ledger_hwm(self):
        """Highest change-ledger epoch, 0.0 when the ledger is empty. Not used
        by the client gate today, but in the schema so a future client can
        skip a changedSince call the stamp already answers."""
        hwm = 0.0
        for ts in list(self._dev_changes.values()):
            if ts > hwm:
                hwm = ts
        for ts in list(self._dev_deleted.values()):
            if ts > hwm:
                hwm = ts
        return hwm

    def _write_stamp_locked(self, state):
        """Caller MUST hold self._stamp_lock."""
        payload = {"v": 1, "boot": self._boot_ts, "ts": time.time(),
                   "hwm": self._ledger_hwm(), "state": state}
        self._write_atomic(self._stamp_path(), json.dumps(payload).encode("utf-8"))
        self._stamp_last_write = time.time()

    def _stamp_note_change(self):
        """Leading-edge stamp write from a ledger callback, ≥1 s apart. A stamp
        failure must never break device handling — swallow everything."""
        try:
            if self._stamp_stop.is_set():
                return
            if time.time() - self._stamp_last_write < STAMP_CHANGE_WRITE_GAP:
                return
            with self._stamp_lock:
                if not self._stamp_stop.is_set():
                    self._write_stamp_locked("run")
        except Exception:
            pass

    def _start_stamp_thread(self):
        self._stamp_thread = threading.Thread(
            target=self._stamp_thread_main,
            name="dashboards-stamp",
            daemon=True,
        )
        self._stamp_thread.start()

    def _stamp_thread_main(self):
        while True:
            try:
                with self._stamp_lock:
                    if self._stamp_stop.is_set():
                        return
                    self._write_stamp_locked("run")
            except Exception:
                pass    # e.g. public dir briefly missing — try again next beat
            if self._stamp_stop.wait(STAMP_PERIOD_SECONDS):
                return

    def _freeze_stamp(self):
        """Write the "stopping" sentinel and bar every further "run" write.
        Idempotent; called from stopConcurrentThread AND shutdown."""
        try:
            self._stamp_stop.set()
            with self._stamp_lock:
                self._write_stamp_locked("stopping")
        except Exception:
            pass

    def _stop_stamp_thread(self):
        self._stamp_stop.set()
        t = self._stamp_thread
        if t and t.is_alive():
            t.join(timeout=1.0)

    # ── Custom pages (v2.5.0) — JSON page definitions + builder endpoint ────

    _SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
    _TILE_TYPES = {"switch", "dimmer", "sensor", "variable", "scene", "chart",
                   "camera", "heading"}

    def _custom_pages_dir(self):
        """Per-plugin Preferences folder for page definitions — survives plugin
        upgrades (the bundle is replaced on update, Preferences are not)."""
        base = indigo.server.getInstallFolderPath()
        d = os.path.join(base, "Preferences", "Plugins", self.pluginId, "custom_pages")
        os.makedirs(d, exist_ok=True)
        return d

    def _reserved_slugs(self):
        """Shipped page names may not be shadowed by a custom page."""
        names = {"custom", "builder"}
        try:
            for f in os.listdir(PAGES_SOURCE_DIR):
                if f.endswith(".html"):
                    names.add(f[:-5].lower())
        except Exception:
            pass
        return names

    def _mirror_custom_pages(self):
        """Copy every stored <slug>.page.json into the public dashboards dir
        and (re)write custom-pages.json — the index that index.html and
        builder.html read. Stale .page.json files in public (definition
        deleted) are removed."""
        try:
            store = self._custom_pages_dir()
            dst   = self._public_dashboards_dir()
            os.makedirs(dst, exist_ok=True)
            index = []
            stored = sorted(f for f in os.listdir(store) if f.endswith(".page.json"))
            for f in stored:
                with open(os.path.join(store, f), encoding="utf-8") as fh:
                    page = json.load(fh)
                self._write_atomic(os.path.join(dst, f),
                                   json.dumps(page, indent=1).encode("utf-8"))
                index.append({
                    "slug":  f[:-len(".page.json")],
                    "title": page.get("title") or f[:-len(".page.json")],
                    "icon":  page.get("icon") or "📄",
                    "tiles": len(page.get("tiles") or []),
                })
            for f in os.listdir(dst):
                if f.endswith(".page.json") and f not in stored:
                    try:
                        os.remove(os.path.join(dst, f))
                    except OSError:
                        pass
            self._write_atomic(os.path.join(dst, "custom-pages.json"),
                               json.dumps({"pages": index}, indent=1).encode("utf-8"))
            if index:
                self._activity(f"[Pages] {len(index)} custom page(s) published")
            return len(index)
        except Exception as exc:
            log(f"[Pages] custom-page mirror failed: {exc}", level="ERROR")
            return 0

    def _validate_page_def(self, page):
        """Return (clean_page, errors). Conservative allow-list validation —
        anything not understood is rejected, not passed through."""
        errors = []
        if not isinstance(page, dict):
            return None, ["page must be an object"]
        title = str(page.get("title") or "").strip()
        if not title or len(title) > 80:
            errors.append("title is required (max 80 characters)")
        theme = page.get("theme") or "auto"
        if theme not in ("auto", "dark", "light"):
            errors.append("theme must be auto, dark or light")
        accent = str(page.get("accent") or "").strip()
        if accent and not re.match(r"^#[0-9a-fA-F]{3,8}$", accent):
            errors.append("accent must be a hex colour like #2b6cb0")
        icon = str(page.get("icon") or "").strip()[:4]
        tiles_in = page.get("tiles")
        if not isinstance(tiles_in, list) or not 1 <= len(tiles_in) <= 60:
            return None, errors + ["tiles must be a list of 1-60 tiles"]
        tiles = []
        for i, t in enumerate(tiles_in):
            n = i + 1
            if not isinstance(t, dict):
                errors.append(f"tile {n}: must be an object")
                continue
            ttype = t.get("type")
            if ttype not in self._TILE_TYPES:
                errors.append(f"tile {n}: unknown type {ttype!r}")
                continue
            clean = {"type": ttype}
            label = str(t.get("label") or "").strip()
            if len(label) > 60:
                errors.append(f"tile {n}: label too long")
            elif label:
                clean["label"] = label
            if ttype == "heading":
                text = str(t.get("text") or "").strip()
                if not text or len(text) > 80:
                    errors.append(f"tile {n}: heading needs text (max 80)")
                clean["text"] = text
            elif ttype == "camera":
                host = str(t.get("host") or "").strip()
                if not re.match(r"^[A-Za-z0-9_.-]{1,80}$", host):
                    errors.append(f"tile {n}: camera needs a valid host")
                clean["host"] = host
            else:
                try:
                    clean["id"] = int(t.get("id"))
                except (TypeError, ValueError):
                    errors.append(f"tile {n}: needs a numeric Indigo id")
                    continue
                if ttype == "chart":
                    state = str(t.get("state") or "").strip()
                    if not re.match(r"^[A-Za-z0-9_.]{1,60}$", state):
                        errors.append(f"tile {n}: chart needs a state name")
                    clean["state"] = state
                    try:
                        hours = int(t.get("hours") or 24)
                    except (TypeError, ValueError):
                        hours = 24
                    clean["hours"] = max(1, min(720, hours))
            tiles.append(clean)
        clean_page = {"title": title, "theme": theme, "tiles": tiles}
        if accent:
            clean_page["accent"] = accent
        if icon:
            clean_page["icon"] = icon
        return clean_page, errors

    def handleCustomPages(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/customPages/
        Bearer-authenticated by IWS (same bar as device control).
        Body: {"op": "list"} | {"op": "save", "slug": s, "page": {...}}
              | {"op": "delete", "slug": s}"""
        body = action.props.get("request_body") or ""
        if len(body) > 100_000:
            return self._evo_reply({"ok": False, "error": "page too large (100KB cap)"}, status=400)
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)
        op = payload.get("op")

        if op == "list":
            store = self._custom_pages_dir()
            out = []
            for f in sorted(os.listdir(store)):
                if f.endswith(".page.json"):
                    try:
                        with open(os.path.join(store, f), encoding="utf-8") as fh:
                            page = json.load(fh)
                        out.append({"slug": f[:-len(".page.json")],
                                    "title": page.get("title", ""),
                                    "icon": page.get("icon") or "📄",
                                    "tiles": len(page.get("tiles") or [])})
                    except Exception:
                        pass
            return self._evo_reply({"ok": True, "pages": out})

        slug = str(payload.get("slug") or "").strip().lower()
        if not self._SLUG_RE.match(slug):
            return self._evo_reply(
                {"ok": False, "error": "slug must be 1-41 chars: a-z, 0-9, hyphens"}, status=400)
        if slug in self._reserved_slugs():
            return self._evo_reply(
                {"ok": False, "error": f"'{slug}' is a built-in page name — pick another"}, status=400)
        path = os.path.join(self._custom_pages_dir(), f"{slug}.page.json")

        if op == "save":
            clean, errors = self._validate_page_def(payload.get("page"))
            if errors:
                return self._evo_reply({"ok": False, "error": "; ".join(errors)}, status=400)
            self._write_atomic(path, json.dumps(clean, indent=1).encode("utf-8"))
            self._mirror_custom_pages()
            log(f"[Pages] custom page saved: {slug} ({len(clean['tiles'])} tiles)")
            return self._evo_reply({"ok": True, "slug": slug,
                                    "url": f"custom.html?page={slug}"})

        if op == "delete":
            if not os.path.isfile(path):
                return self._evo_reply({"ok": False, "error": "no such page"}, status=404)
            os.remove(path)
            self._mirror_custom_pages()
            log(f"[Pages] custom page deleted: {slug}")
            return self._evo_reply({"ok": True, "deleted": slug})

        return self._evo_reply({"ok": False, "error": f"unknown op {op!r}"}, status=400)

    def handleChangedSince(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/changedSince/
        Body: {"since": <server epoch float>}  (Bearer-authenticated by IWS)
        Returns the device IDs that changed/were deleted after `since`, plus
        the current server clock for the next poll. Tells the client to do a
        full refetch when `since` is missing/stale or the change set is large."""
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
            since   = float(payload.get("since") or 0)
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)
        if self._refuse_reflector(action):
            return self._refuse_reflector(action)
        payload = self._changed_since_payload(since)
        if self._note_reflector_use(action):
            payload["via"] = "reflector"       # the pages slow down on this even when the address lies
        return self._evo_reply(payload)

    # The ledger policy lives ONCE (v2.95.1). It used to be copied into the
    # guest route on :8177, so a change to one copy would have quietly given
    # the guest tablet a different idea of "stale" from the main pages.
    CHANGED_SINCE_STALE_S = 600      # older than this: the client refetches all
    CHANGED_SINCE_MAX_IDS = 40       # more than this: cheaper to refetch all

    REFLECTOR_WARN_S = 3600     # one line per device per hour, no more

    def _reflector_blocked(self):
        """True when the user has asked for the reflector to be refused.

        Off by default: plenty of installs have no other way in from outside,
        and silently breaking them would be worse than the bandwidth. CliveS
        turned it on here after Indigo Domotics wrote twice about this server's
        usage and Tailscale replaced the reflector for every away-from-home
        case (v3.1.0)."""
        prefs = getattr(self, "pluginPrefs", None) or {}
        try:
            from plugin_utils import as_bool
            return as_bool(prefs.get("reflectorBlock"), False)
        except Exception:
            return str(prefs.get("reflectorBlock", "")).strip().lower() in ("true", "1", "yes", "on")

    def _refuse_reflector(self, action):
        """A 403 reply when this request came through the reflector and the
        user has asked for that to be refused — otherwise None (v3.1.0).

        Every handler starts with this, so no dashboard data of any kind
        crosses the reflector: not devices, not history, not the Sigen feed.
        The reply names the way in that does work, because a bare 403 on a
        phone tells the owner nothing about what to do next.
        """
        if not self._reflector_blocked():
            return None
        if not self._note_reflector_use(action):
            return None
        lan = (f"http://{self.lan_ip}:8176{INDEX_PATH}" if getattr(self, "lan_ip", "")
               else self._dashboard_url())
        return self._evo_reply({
            "ok": False,
            "error": "the dashboards are not served over the Indigo reflector",
            "reason": "reflector_blocked",
            "lanURL": lan,
        }, status=403)

    def _note_reflector_use(self, action):
        """True when this /message/ request arrived through the Indigo
        reflector, and WARN once an hour per device when it did (v2.96.1).

        Indigo Domotics wrote on 02-Sep-2026: the reflector was carrying "a
        lot of bandwidth". The address it saw was this house's own line — a
        device on the home wi-fi had been paired with the reflector address
        and every camera still it asked for went out to Indigo's servers and
        back. IWS logs nothing for /public files or authenticated calls, so
        nothing on the server could say which device. The request headers
        can: the reflector forwards the caller's address, and the browser
        names itself. The log line names both and gives the LAN address."""
        try:
            hdrs = dict(getattr(action, "props", {}).get("headers") or {})
            hdrs = {str(k).lower(): str(v) for k, v in hdrs.items()}
        except Exception:
            return False
        if not getattr(self, "_hdr_keys_logged", False):
            self._hdr_keys_logged = True
            self.logger.debug(f"[Reflector] first /message request headers: {sorted(hdrs)}")
        xff  = (hdrs.get("x-forwarded-for") or hdrs.get("x-real-ip") or "").split(",")[0].strip()
        host = (hdrs.get("host") or "").strip("[]").rsplit(":", 1)[0].lower()
        refl = getattr(self, "_reflector_host", None)
        if refl is None:
            try:
                url  = str(indigo.server.getReflectorURL() or "")
                refl = url.split("//", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].lower()
            except Exception:
                refl = ""
            self._reflector_host = refl
        via = bool(xff) or (bool(refl) and host == refl)
        if not via:
            return False
        ua   = hdrs.get("user-agent", "")[:120]
        key  = (xff, ua)
        now  = time.time()
        seen = getattr(self, "_reflector_seen", None)
        if seen is None:
            seen = self._reflector_seen = {}
        if now - seen.get(key, 0.0) >= self.REFLECTOR_WARN_S:
            seen[key] = now
            lan = (f"http://{self.lan_ip}:8176{INDEX_PATH}" if getattr(self, "lan_ip", "")
                   else self._dashboard_url())
            self.logger.warning(
                f"[Reflector] The dashboards are being used through the Indigo reflector "
                f"from {xff or host} ({ua or 'unknown browser'}). If that device is at home, "
                f"open them on {lan} instead — every byte through the reflector is carried "
                f"by Indigo's own servers.")
        return True

    def _changed_since_payload(self, since, now=None):
        """The changedSince reply for a client whose last poll was at `since`
        (server epoch). Full refetch when the client is new, stale, or the
        change set is large; else the changed + deleted ids since then."""
        now = time.time() if now is None else now
        if since <= 0 or (now - since) > self.CHANGED_SINCE_STALE_S:
            return {"ok": True, "now": now, "full": True}
        # list() snapshots guard against concurrent ledger writes mid-iteration.
        changed = [i for i, ts in list(self._dev_changes.items()) if ts > since]
        deleted = [i for i, ts in list(self._dev_deleted.items()) if ts > since]
        if len(changed) > self.CHANGED_SINCE_MAX_IDS:
            return {"ok": True, "now": now, "full": True}
        return {"ok": True, "now": now, "changed": changed, "deleted": deleted}

    def menuTestHistory(self, valuesDict=None, typeId=None):
        """Check the configured SQL Logger backend and report what it found.

        Dumps the full banner first so a forum post carries the environment and
        the test result in one paste — the convention for every diagnostic
        menu item.
        """
        self.showPluginInfo()
        try:
            hist = self._history()
        except Exception as exc:
            self.logger.error(f"History test FAILED — {exc}")
            return
        ok, detail = hist.check()
        if not ok:
            self.logger.error(f"History test FAILED ({hist.backend}) — {detail}")
            return
        self.logger.info(f"History test PASSED — {detail}")
        try:
            with hist.connect() as conn:
                ids = hist.device_tables(conn)
                self.logger.info(f"  {len(ids)} device(s) have recorded history")
                dropped = shown = 0
                for dev_id in ids:
                    real = len(hist.columns(conn, dev_id))
                    allc = len(hist.columns(conn, dev_id, include_artefacts=True))
                    shown += real
                    dropped += (allc - real)
                self.logger.info(f"  {shown} real state column(s) offered for charting")
                if dropped:
                    self.logger.info(
                        f"  {dropped} SQL Logger artefact column(s) hidden — "
                        f"type-change leftovers the logger cannot remove itself")
        except Exception as exc:
            self.logger.warning(f"History test connected but could not enumerate: {exc}")

    def _setup_checks(self):
        """Every check Test Dashboards Setup performs, as (label, ok, detail,
        optional) tuples, in the order the menu prints them. The menu item logs
        them; the run_setup_check MCP tool (v3.12.0) returns them as data. One
        builder, so the two can never report different verdicts."""
        checks = []

        def chk(label, ok, detail="", optional=False):
            # optional=True: reported as SKIP at INFO and left out of the tally.
            # Five missing optional scripts used to print five red FAIL lines
            # on a brand-new, perfectly healthy install.
            checks.append((label, bool(ok), detail, optional))

        chk("Config source", True,
            "settings store" if self.cfg_loaded else "IndigoSecrets/PluginConfig (legacy)")
        chk("Indigo API URL", self.api_url, self.api_url or "not set — pages need it")
        chk("API key", self.api_key,
            "present" if self.api_key else "missing — pages cannot authenticate")
        pub = self._public_dashboards_dir()
        chk("Public pages dir writable", os.path.isdir(pub) and os.access(pub, os.W_OK), pub)
        chk("config.js written", os.path.isfile(self._config_js_path()))
        try:
            fresh = (os.path.isfile(self._stamp_path())
                     and time.time() - os.path.getmtime(self._stamp_path()) < 10)
        except OSError:
            fresh = False
        chk("Liveness stamp beating", fresh,
            "" if fresh else "stale/missing — restart gating will not work")
        chk("Cameras configured", True, f"{len(CAMERAS)} camera(s)")
        if CAMERAS:
            proc = getattr(self, "_go2rtc_proc", None)
            chk("go2rtc running", proc is not None and proc.poll() is None,
                getattr(self, "_go2rtc_bin", GO2RTC_BIN))
            chk("Camera credentials", self.cam_user and self.cam_pass,
                "" if (self.cam_user and self.cam_pass) else "DAHUA_USER/DAHUA_PASS not set")
            ff = shutil.which("ffmpeg") or next((c for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
                                                 if os.path.exists(c)), None)
            chk("ffmpeg found", bool(ff), ff or "brew install ffmpeg — go2rtc needs it to transcode")
        # Rooms: the one thing a fresh install most often gets wrong, silently.
        try:
            names = list(self._room_folders())
            existing = {f.name for f in indigo.devices.folders}
            hit = [n for n in names if n in existing]
            chk("Room folders", bool(hit),
                f"{len(hit)} of {len(names)} configured folder names exist in Indigo"
                + ("" if hit else " — tick your room folders on the Settings page (Rooms card)"))
        except Exception as exc:
            chk("Room folders", False, f"could not read device folders: {exc}")
        sem = self._sigen_available()
        chk("SigenEnergyManager", sem,
            "present — the Energy, Cost and Laundry pages are shown" if sem
            else "not installed — the Energy, Cost and Laundry pages hide themselves",
            optional=True)
        db = self._history_db_path()
        chk("SQL Logger history", os.path.isfile(db),
            db if os.path.isfile(db) else "not found — Graphs, Timeline and Insights need the SQL Logger plugin",
            optional=True)
        scripts_dir = self._scripts_dir()
        for name in (v[0] for v in self.COMPANION_SCRIPTS.values()):
            chk(name, os.path.isfile(os.path.join(scripts_dir, name)),
                "optional companion script — repo scripts/ folder", optional=True)
        return checks

    def menuTestSetup(self, valuesDict=None, typeId=None):
        """Menu: one PASS/FAIL sweep of everything a stuck install needs
        checked — the single log dump a support post wants. Banner first (the
        estate convention for diagnostic menus)."""
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion)
        checks = self._setup_checks()
        fails = counted = 0
        for label, ok, detail, optional in checks:
            if optional and not ok:
                line = f"[Setup] SKIP — {label}"
            else:
                counted += 1
                fails += 0 if ok else 1
                line = f"[Setup] {'PASS' if ok else 'FAIL'} — {label}"
            if detail:
                line += f" ({detail})"
            (self.logger.error if (not ok and not optional) else self.logger.info)(line)
        self.logger.info(f"[Setup] {counted - fails} of {counted} checks passed"
                         + (f", {len(checks) - counted} optional item(s) skipped" if len(checks) != counted else ""))
        return True

    def showPluginInfo(self, valuesDict=None, typeId=None):
        extras = [
            ("Dashboards URL:",    self._dashboard_url()),
            ("Indigo URL:",        self.api_url or "(unset)"),
            ("API key source:",    self._secrets_state()),
            ("Cameras:",           self._camera_state()),
            ("History backend:",   str((self.pluginPrefs or {}).get("historyBackend") or "sqlite")),
            ("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"),
        ]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")
            for label, value in extras:
                indigo.server.log(f"  {label} {value}")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        # pluginPrefs only flush to disk on a CLEAN shutdown — without an
        # explicit save the toggle is lost on any crash or force-quit.
        try:
            self.savePluginPrefs()
        except Exception:
            pass
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")

    # --------------------------------------------------------
    # Menu callbacks
    # --------------------------------------------------------

    def _dashboard_url(self, include_api_key=False):
        """The dashboard hub URL. The `?api-key=` form was removed in v2.38.0
        and the branch that built it went in v2.95.2 — the pages seed their
        key from the :8177 bootstrap or a setup link, never from a URL that
        ends up in browser history and server logs."""
        base = self.api_url or "http://localhost:8176"
        return f"{base}{INDEX_PATH}"

    def menuOpenDashboards(self, valuesDict=None, typeId=None):
        """Menu: open the dashboards hub in the default browser.

        Note: this opens the browser on the Indigo SERVER. If the Indigo
        client is running on a different Mac, the dashboard appears on the
        server's screen, not the client's. The URL (without api-key) is also
        logged so it can be clicked from the event log on any client.
        """
        # v2.38.0: open WITHOUT the key in the query string (it would land in
        # the server browser's history/logs). The server Mac is on the LAN, so
        # dashboards-auth.js seeds the key from :8177/bootstrap on first load
        # (or, if key auto-seed is disabled, the Connect form prompts once).
        url_log = self._dashboard_url(include_api_key=False)
        log(f"[Menu] Dashboards: {url_log}")
        try:
            import webbrowser
            opened = webbrowser.open(url_log, new=2)
            if not opened:
                log("[Menu] Could not auto-open browser — open the URL above manually",
                    level="WARNING")
        except Exception as exc:
            log(f"[Menu] Browser launch failed ({exc}) — open the URL above manually",
                level="WARNING")
        return True

    def menuOpenSigenLegacy(self, valuesDict=None, typeId=None):
        """Menu: open the legacy Sigenergy mini-dashboard (configurable URL).

        Resolved from IndigoSecrets.SIGEN_DASHBOARD_URL first, PluginConfig
        `sigenLegacyUrl` next. If neither is set we log a hint and return —
        the menu item still exists but is a no-op for users who don't run a
        Sigen dashboard.
        """
        if not self.sigen_legacy_url:
            log("[Menu] No Sigen dashboard URL configured. Set SIGEN_DASHBOARD_URL "
                "in IndigoSecrets.py OR fill in Sigen Dashboard URL under Plugins "
                "-> Dashboards -> Configure.", level="WARNING")
            return True
        log(f"[Menu] Legacy Sigen dashboard: {self.sigen_legacy_url}")
        try:
            import webbrowser
            opened = webbrowser.open(self.sigen_legacy_url, new=2)
            if not opened:
                log("[Menu] Could not auto-open browser — open the URL above manually",
                    level="WARNING")
        except Exception as exc:
            log(f"[Menu] Browser launch failed ({exc}) — open the URL above manually",
                level="WARNING")
        return True

    # -----------------------------------------------------------------------
    # EvoHome proxy — hidden HTTP endpoint for the heating dashboard
    # -----------------------------------------------------------------------

    _EVO_PLUGIN_ID      = "com.clives.indigoplugin.evohomecontrol"
    _EVO_ALLOWED_ACTIONS = frozenset({
        "startTimedBoost1h",
        "startTimedBoost2h",
        "cancelTimedBoost",
        "forceHeatingOn24h",
        "cancelForcedHeating",
        "showSummerStatus",
    })

    def handleEvoHomeAction(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/evoHomeAction/
        Body: {"action_id": "<actionId>"}
        Validates the action ID against an allowlist, then delegates to the
        EvoHome Heating Controller plugin via executeAction().
        """
        body = action.props.get("request_body") or ""
        try:
            payload    = json.loads(body) if body else {}
            action_id  = (payload.get("action_id") or "").strip()
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)

        if action_id not in self._EVO_ALLOWED_ACTIONS:
            return self._evo_reply(
                {"ok": False, "error": f"unknown action: {action_id!r}",
                 "allowed": sorted(self._EVO_ALLOWED_ACTIONS)},
                status=400,
            )

        evo = indigo.server.getPlugin(self._EVO_PLUGIN_ID)
        # isRunning, not isEnabled (v2.95.2): an enabled-but-crashed plugin
        # reads enabled, and executeAction on a stopped host does not raise,
        # so a boost press logged 'triggered' and nothing happened.
        if not evo or not evo.isInstalled() or not evo.isRunning():
            return self._evo_reply(
                {"ok": False, "error": "EvoHome plugin not running"}, status=503
            )

        try:
            evo.executeAction(action_id)
        except Exception as exc:
            self.logger.error(f"[EvoHome proxy] executeAction({action_id!r}) failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

        self.logger.info(f"[EvoHome proxy] {action_id} triggered via dashboard")
        return self._evo_reply({"ok": True, "action": action_id})

    @staticmethod
    def _evo_reply(obj, status=200):
        return {
            "status":  status,
            "headers": {
                "Content-Type":  "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            "content": json.dumps(obj),
        }

    # -----------------------------------------------------------------------
    # Sigenergy data proxy — reflector-reachable, login-gated access to the
    # SigenEnergyManager :8179 data API, so the energy/power-flow page works
    # away from home too (not just on the LAN). The browser hits IWS (reflector)
    # → this handler → localhost:8179, so the LAN-only :8179 port is never
    # exposed. Single source of the flow card lives in energy.html now.
    # -----------------------------------------------------------------------
    _SIGEN_API_BASE      = "http://127.0.0.1:8179/api"
    _SIGEN_ALLOWED_PATHS = frozenset({
        "status", "history", "daily", "export-sync", "years", "calendar",
        # v2.84.0 — the VPP earnings ledger. Its own path rather than a
        # widening of `status`, because it carries the per-event list and the
        # status payload is polled every few seconds by three pages.
        "vpp",
    })

    def handleSigenApi(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/sigenApi/
        Body: {"path": "status"|..., "query": {"hours": 24}}
        Fetches the SigenEnergyManager :8179 data API (localhost) and returns
        its JSON. Path is allow-listed and the upstream host is fixed (no SSRF);
        only int hours/days/year query params are forwarded. Bearer-authed by
        IWS upstream.
        """
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        if not self._sigen_available():
            # No SigenEnergyManager on this server (v3.13.0): say so at once
            # rather than dial a port nothing listens on — a fresh install
            # without it used to WARN on every hub poll, thirty seconds apart.
            return self._evo_reply({"error": "SigenEnergyManager is not installed",
                                    "reason": "sem_absent"}, status=503)
        import urllib.request
        import urllib.parse
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"error": f"bad JSON: {exc}"}, status=400)

        path = str(payload.get("path") or "status").strip().lower()
        if path not in self._SIGEN_ALLOWED_PATHS:
            return self._evo_reply({"error": f"unknown path: {path!r}"}, status=400)

        # Only forward the handful of numeric params the data API accepts.
        query = payload.get("query") or {}
        qs = {}
        for k in ("hours", "days", "year"):
            if k in query:
                try:
                    qs[k] = int(query[k])
                except (TypeError, ValueError):
                    pass
        url = f"{self._SIGEN_API_BASE}/{path}"
        if qs:
            url += "?" + urllib.parse.urlencode(qs)

        # Micro-cache (v2.72.0): the dispatch thread is SINGLE — while one
        # 12 s upstream fetch runs, every queued duplicate (the hub, energy
        # and cost pages all poll `status`) used to wait its turn and then
        # spend ANOTHER 12 s asking the identical question. A 2.5 s TTL on
        # successful replies answers the queue from the first result.
        cache = getattr(self, "_sigen_reply_cache", None)
        if cache is None:
            cache = self._sigen_reply_cache = {}
        hit = cache.get(url)
        if hit and time.time() - hit[0] < 2.5:
            return {"status": 200,
                    "headers": {"Content-Type": "application/json; charset=utf-8",
                                "Cache-Control": "no-store"},
                    "content": hit[1]}

        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"Dashboards/{PLUGIN_VERSION}"})
            # 12s, not 8s: SigenEnergyManager serves /api/status from the same
            # process that runs its periodic EMS-control cycle, which pushes a
            # burst of serial modbus writes (set EMS mode + discharge/charge
            # limits, ~8-10s in total). At 8s the status fetch occasionally
            # times out mid-cycle and the energy tile drops to a 502; 12s rides
            # the burst out. (Diagnosed 18-Jul-2026 — the timeouts correlated to
            # the second with SEM's "Setting ESS max discharge/charge limit".)
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as exc:
            # A 404 from upstream is not a fault — it means this SigenEnergyManager
            # is older than the path being asked for, which is the ordinary state
            # of affairs between the two plugins being upgraded. The page already
            # degrades by hiding the card, so warning about it once every poll
            # would put an amber line in the log for a system working exactly as
            # designed. Everything else is a genuine failure and still warns.
            not_found = getattr(exc, "code", None) == 404
            msg = f"[SigenProxy] {path} fetch failed: {exc}"
            if not_found:
                self.logger.debug(msg + " — upstream plugin has no such path (optional)")
            else:
                self.logger.warning(msg)
            return self._evo_reply(
                {"error": "Sigenergy data API unavailable", "detail": str(exc)},
                status=502)

        # Pass the upstream JSON text straight through (and remember it
        # briefly — see the micro-cache above). Cap the cache so a burst of
        # distinct history queries cannot grow it without bound.
        if len(cache) > 32:
            cache.clear()
        cache[url] = (time.time(), raw)
        return {
            "status":  200,
            "headers": {
                "Content-Type":  "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            "content": raw,
        }

    # -----------------------------------------------------------------------
    # System-health endpoint — Mac vitals + storage + device-health census.
    # Powers system-health.html. Everything is computed server-side in ONE
    # round-trip because a browser can't read host stats (disk/RAM/swap) or
    # the SQL history DB size, and shipping ~190 devices' full JSON over the
    # reflector just to count them would be wasteful. Bearer-authed by IWS.
    # -----------------------------------------------------------------------
    def handleSystemHealth(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/systemHealth/
        Returns {mac, storage, devices}. No request params. Each section is
        computed defensively so one failure degrades to a partial answer."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time()}
        for key, fn in (("mac",      self._mac_vitals),
                        ("storage",  self._storage_breakdown),
                        ("devices",  self._device_health),
                        ("services", self._service_health)):
            try:
                out[key] = fn()
            except Exception as exc:
                self.logger.warning(f"[SystemHealth] {key} section failed: {exc}")
                out[key] = {"error": str(exc)}
        return self._evo_reply(out)

    def _service_health(self):
        """This plugin's own background services (v2.33.0) — the page can then
        say whether the camera pipeline is actually alive, not just assumed."""
        go2 = getattr(self, "_go2rtc_proc", None)
        mj  = getattr(self, "_mjpeg_server", None)
        return {
            "plugin_version": PLUGIN_VERSION,
            "go2rtc":         bool(go2 is not None and go2.poll() is None),
            "mjpeg_proxy":    bool(mj is not None),
            "cameras":        len(CAMERAS),
        }

    def _mac_vitals(self):
        """Host vitals: disk, RAM (+swap), load, uptime, OS/Python. RAM total
        comes from os.sysconf (authoritative, no subprocess); the breakdown
        from vm_stat. subprocess uses ABSOLUTE binary paths — the plugin-host
        PATH omits /usr/sbin, so a bare 'sysctl' raises FileNotFoundError."""
        import platform
        import subprocess

        def _sh(args):
            try:
                return subprocess.run(args, capture_output=True, text=True,
                                      timeout=5).stdout.strip()
            except Exception:
                return ""

        out = {
            "hostname": platform.node(),
            "macos":    platform.mac_ver()[0] or "",
            "python":   platform.python_version(),
            "arch":     platform.machine(),
            "cores":    os.cpu_count() or 0,
        }
        try:
            out["indigo"] = str(indigo.server.version)
            out["api"]    = str(indigo.server.apiVersion)
        except Exception:
            pass
        try:
            l1, l5, l15 = os.getloadavg()
            out["load"] = [round(l1, 2), round(l5, 2), round(l15, 2)]
        except Exception:
            out["load"] = []
        try:
            du = shutil.disk_usage("/")
            out["disk"] = {
                "total_gb": round(du.total / 1e9, 1),
                "used_gb":  round(du.used / 1e9, 1),
                "free_gb":  round(du.free / 1e9, 1),
                "used_pct": round(du.used / du.total * 100, 1),
            }
        except Exception:
            out["disk"] = {}

        ram = {}
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            vm = _sh(["/usr/bin/vm_stat"])
            m = re.search(r"page size of (\d+) bytes", vm)
            psize = int(m.group(1)) if m else 4096

            def _pg(label):
                mm = re.search(rf"{re.escape(label)}:\s+(\d+)\.", vm)
                return int(mm.group(1)) if mm else 0

            # "Memory Used" as Activity Monitor reports it: app (active) +
            # wired + compressed. Free/inactive/speculative are reclaimable.
            used = (_pg("Pages active") + _pg("Pages wired down")
                    + _pg("Pages occupied by compressor")) * psize
            # RAM in binary GiB (2**30) — the convention the hardware is sold
            # in. The old decimal /1e9 made an 8 GB Mac mini report "8.6 GB
            # total". Disk stays decimal (matches Finder/Apple SSD specs).
            ram = {
                "total_gb": round(total / 2**30, 1),
                "used_gb":  round(used / 2**30, 1),
                "free_gb":  round(max(0, total - used) / 2**30, 1),
                "used_pct": round(used / total * 100, 1) if total else 0,
            }
            sw = _sh(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
            st = re.search(r"total = ([\d.]+)M", sw)
            su = re.search(r"used = ([\d.]+)M", sw)
            if st:
                ram["swap_total_mb"] = round(float(st.group(1)))
            if su:
                ram["swap_used_mb"] = round(float(su.group(1)))
        except Exception:
            pass
        # Memory-pressure verdict. On an 8 GB Mac, heavy swap is the real
        # signal — a high used_pct alone is normal for macOS.
        up = ram.get("used_pct", 0)
        swu = ram.get("swap_used_mb", 0)
        if "used_pct" not in ram:
            # The measurement itself failed (vm_stat/sysctl timed out — which
            # is exactly what a starved Mac does). Unknown, never 'normal'.
            ram["pressure"] = "unknown"
        elif swu >= 1500 or up >= 92:
            ram["pressure"] = "high"
        elif swu >= 400 or up >= 82:
            ram["pressure"] = "elevated"
        else:
            ram["pressure"] = "normal"
        out["ram"] = ram

        out["uptime_text"] = ""
        try:
            up_txt = _sh(["/usr/bin/uptime"])
            mm = re.search(r"\bup\s+(.+?),\s+\d+\s+user", up_txt)
            out["uptime_text"] = mm.group(1).strip() if mm else up_txt
        except Exception:
            pass
        try:
            bt = _sh(["/usr/sbin/sysctl", "-n", "kern.boottime"])
            mm = re.search(r"sec\s*=\s*(\d+)", bt)
            if mm:
                out["boot_epoch"] = int(mm.group(1))
        except Exception:
            pass
        return out

    def _storage_breakdown(self):
        """SQL history DB size (the dominant, actionable chunk of a near-full
        disk) plus the biggest items in the Logs dir. Cached for 5 minutes so
        the 30 s page poll doesn't re-walk the tree every tick."""
        cache = getattr(self, "_storage_cache", None)
        nowm = time.time()
        if cache and (nowm - cache[0]) < 300:
            return cache[1]
        base = indigo.server.getInstallFolderPath()
        logs = os.path.join(base, "Logs")
        sqlp = os.path.join(logs, "indigo_history.sqlite")
        out = {
            "sql_history_gb":   round(os.path.getsize(sqlp) / 1e9, 2) if os.path.exists(sqlp) else 0.0,
            "sql_history_path": sqlp,
            "logs_total_gb":    0.0,
            "top_items":        [],
        }
        items = []
        try:
            with os.scandir(logs) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            sz = e.stat(follow_symlinks=False).st_size
                            is_dir = False
                        else:
                            sz = 0
                            for root, _dirs, files in os.walk(e.path):
                                for f in files:
                                    try:
                                        sz += os.path.getsize(os.path.join(root, f))
                                    except OSError:
                                        pass
                            is_dir = True
                        items.append((e.name, sz, is_dir))
                    except OSError:
                        pass
        except OSError:
            pass
        out["logs_total_gb"] = round(sum(s for _n, s, _d in items) / 1e9, 2)
        items.sort(key=lambda x: -x[1])
        out["top_items"] = [
            {"name": n, "gb": round(s / 1e9, 2), "dir": d}
            for n, s, d in items[:6] if s > 50e6   # only items over ~50 MB
        ]
        self._storage_cache = (nowm, out)
        return out

    @staticmethod
    def _battery_pct(dev):
        """Battery reading for a device, covering the estate's three battery
        idioms: the native batteryLevel property (Z-Wave etc.), the z2m custom
        `battery` state (guarded >0 — mains z2m devices report 0), and the
        boolean `batteryLow` alarm. Returns (pct_or_None, alarm_bool) — the
        same coverage as overview.html's batteryInfo(), which caught a 1%
        sensor the native-only check missed."""
        bl = getattr(dev, "batteryLevel", None)
        if isinstance(bl, (int, float)) and not isinstance(bl, bool):
            return int(bl), False
        try:
            states = dev.states
        except Exception:
            return None, False
        try:
            bf = float(states.get("battery"))
            if bf > 0:
                return int(bf), False
        except (TypeError, ValueError):
            pass
        if str(states.get("batteryLow", "")).strip().lower() in ("true", "on", "yes", "1"):
            return None, True
        return None, False

    def _device_health(self):
        """Per-device alerts + per-plugin census, computed over the live IOM.
        'In error' uses dev.errorState (the reliable liveness signal); 'quiet'
        uses lastChanged age (not a true comms probe — framed as such on the
        page) with a configurable threshold."""
        try:
            stale_hours = int(self.pluginPrefs.get("healthStaleHours", 48) or 48)
        except (TypeError, ValueError):
            stale_hours = 48
        try:
            low_batt_pct = int(self.pluginPrefs.get("healthLowBatteryPct", 20) or 20)
        except (TypeError, ValueError):
            low_batt_pct = 20

        now = indigo.server.getTime()
        in_error, low_batt, stale = [], [], []
        census = {}
        total = enabled = 0
        # len() and iteration disagree: iteration skips unconfigured devices
        # (measured 209 vs 211 here). Publish both so the page can show the gap.
        try:
            known = len(indigo.devices)
        except Exception:
            known = None

        for d in indigo.devices:
            total += 1
            is_on = bool(d.enabled)
            if is_on:
                enabled += 1
            pid = d.pluginId or "(native/built-in)"
            c = census.setdefault(pid, {"count": 0, "enabled": 0})
            c["count"] += 1
            if is_on:
                c["enabled"] += 1

            es = (d.errorState or "").strip()
            if es:
                in_error.append({"id": d.id, "name": d.name, "plugin": pid, "error": es})

            bl, alarm = self._battery_pct(d)
            if alarm or (bl is not None and bl <= low_batt_pct):
                low_batt.append({"id": d.id, "name": d.name, "plugin": pid,
                                 "battery": bl, "alarm": alarm})

            # "Quiet" only means something for BATTERY devices — silence from a
            # battery sensor can be a flat battery or a dropped mesh link. Mains
            # devices, virtuals and timers are legitimately quiet for days, and
            # some carry an unset/epoch lastChanged (a bogus multi-year age), so
            # they are excluded and implausible ages (>1yr) are dropped.
            if is_on and (alarm or bl is not None):
                try:
                    age_h = (now - d.lastChanged).total_seconds() / 3600.0
                    if stale_hours <= age_h <= 24 * 365:
                        stale.append({"id": d.id, "name": d.name, "plugin": pid,
                                      "age_hours": round(age_h, 1), "battery": bl,
                                      "alarm": alarm})
                except Exception:
                    pass

        plugins = []
        for pid, c in census.items():
            disp, running, plugin_enabled = pid, None, None
            try:
                p = indigo.server.getPlugin(pid)
                if p:
                    disp = p.pluginDisplayName or pid
                    # isRunning, NOT isEnabled (v2.95.1): a plugin that is
                    # enabled and has crashed reads True from isEnabled(), so
                    # this page — the one built to say something is down —
                    # showed a dead device-owning plugin as healthy for 20 h
                    # during the ShellyDirect outage of 16-17 Aug. Both are
                    # returned so the page can tell "stopped" (red) from
                    # "disabled on purpose" (grey). NB getPlugin() of an
                    # unknown id does not raise — it reads all-False — so a
                    # built-in pseudo-id keeps None rather than a false red.
                    if p.isInstalled():
                        running = bool(p.isRunning())
                        plugin_enabled = bool(p.isEnabled())
            except Exception:
                pass
            plugins.append({"plugin": pid, "name": disp, "count": c["count"],
                            "enabled": c["enabled"], "running": running,
                            "pluginEnabled": plugin_enabled})

        in_error.sort(key=lambda x: x["name"].lower())
        # None battery = a batteryLow alarm with no % — sort those first (-1).
        low_batt.sort(key=lambda x: x["battery"] if x["battery"] is not None else -1)
        stale.sort(key=lambda x: -x["age_hours"])
        plugins.sort(key=lambda x: (-x["count"], x["name"].lower()))

        return {
            "total":        total,
            "known":        known,
            "enabled":      enabled,
            "disabled":     total - enabled,
            "stale_hours":  stale_hours,
            "low_batt_pct": low_batt_pct,
            "in_error":     in_error[:50],
            "low_battery":  low_batt[:50],
            "stale":        stale[:30],
            "stale_count":  len(stale),
            "by_plugin":    plugins,
        }

    # -----------------------------------------------------------------------
    # Carbon-aware advisor — combines UK grid carbon intensity (free public
    # API), the live solar surplus and the tariff into a "good time to run a
    # load" recommendation. Powers carbon.html. Carbon data is cached 10 min
    # (it only refreshes every 30 min upstream); solar/tariff are read fresh
    # each call so the advice tracks a passing cloud. Bearer-authed by IWS.
    # -----------------------------------------------------------------------
    _CARBON_API      = "https://api.carbonintensity.org.uk"
    _SIGEN_PLUGIN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"

    def handleCarbonAdvisor(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/carbonAdvisor/
        Returns {carbon, solar, tariff, advice}. Each section is defensive so a
        single failure degrades to a partial answer (e.g. carbon API down still
        yields a solar-only recommendation)."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time()}
        try:
            out["carbon"] = self._carbon_intensity()
        except Exception as exc:
            self.logger.warning(f"[Carbon] intensity fetch failed: {exc}")
            out["carbon"] = {"error": str(exc)}
        try:
            out["solar"] = self._carbon_solar()
        except Exception as exc:
            self.logger.warning(f"[Carbon] solar read failed: {exc}")
            out["solar"] = {}
        try:
            out["tariff"] = self._carbon_tariff()
        except Exception:
            out["tariff"] = {}
        try:
            out["advice"] = self._carbon_advice(
                out.get("carbon") or {}, out.get("solar") or {}, out.get("tariff") or {})
        except Exception as exc:
            self.logger.warning(f"[Carbon] advice failed: {exc}")
            out["advice"] = {}
        return self._evo_reply(out)

    def _carbon_intensity(self):
        """Current + 48h regional carbon intensity, stale-while-revalidate.
        The reply always comes from cache; an expired cache returns the STALE
        payload at once and refreshes on a daemon worker. The refresh used to
        run its two 10 s fetches synchronously on the single dispatch thread,
        freezing every other handler and callback for up to 20 s per miss."""
        cache = getattr(self, "_carbon_cache", None)
        nowm = time.time()
        if cache and nowm < cache[0]:
            return cache[1]
        if not getattr(self, "_carbon_refreshing", False):
            self._carbon_refreshing = True

            def _work():
                try:
                    payload = self._carbon_fetch()
                    ttl = 120 if "error" in payload else 600
                    self._carbon_cache = (time.time() + ttl, payload)
                except Exception as exc:
                    self._carbon_cache = (time.time() + 120,
                                          {"error": f"carbon refresh failed: {exc}"})
                finally:
                    self._carbon_refreshing = False

            threading.Thread(target=_work, name="dashboards-carbon",
                             daemon=True).start()
        if cache:
            return cache[1]
        return {"error": "carbon data is being fetched — try again shortly",
                "warming": True}

    def _carbon_fetch(self):
        """One full carbon-API round trip → payload. Runs on the refresh
        worker, NEVER on the dispatch thread. Cached 10 min on success,
        2 min on failure (a down API isn't re-hit by every tab's poll)."""
        import urllib.request
        import calendar
        nowm = time.time()
        try:
            region = int(self.pluginPrefs.get("carbonRegionId", 4) or 4)
        except (TypeError, ValueError):
            region = 4
        if region <= 0:
            # "Off (not in Great Britain)" — the API covers GB only.
            return {"off": True, "error": "carbon data is switched off in Configure"}

        def _get(path):
            req = urllib.request.Request(
                f"{self._CARBON_API}{path}",
                headers={"User-Agent": f"Dashboards/{PLUGIN_VERSION}",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))

        try:
            cur = _get(f"/regional/regionid/{region}")["data"][0]
        except Exception as exc:
            return {"error": f"carbon API unavailable: {exc}"}
        region_name = cur.get("shortname", f"Region {region}")
        cur_block = cur["data"][0]
        current = {"intensity": cur_block["intensity"]["forecast"],
                   "index":     cur_block["intensity"]["index"]}
        mix = [{"fuel": m["fuel"], "perc": m["perc"]}
               for m in cur_block.get("generationmix", [])]

        from_iso = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
        try:
            fc_raw = _get(f"/regional/intensity/{from_iso}/fw48h/regionid/{region}")
            fdata = fc_raw["data"]
            fdata = fdata["data"] if isinstance(fdata, dict) else fdata
        except Exception:
            fdata = []          # keep the current reading even if the forecast leg fails
        forecast = [{"from": e["from"], "to": e["to"],
                     "intensity": e["intensity"]["forecast"],
                     "index": e["intensity"]["index"]}
                    for e in fdata
                    if e.get("intensity", {}).get("forecast") is not None]

        # Cleanest slot within the next 16h (an actionable "when to run" horizon).
        best = None
        horizon = nowm + 16 * 3600
        for e in forecast:
            try:
                t = calendar.timegm(time.strptime(e["from"], "%Y-%m-%dT%H:%MZ"))
            except Exception:
                continue
            if t < nowm - 1800 or t > horizon:
                continue
            if best is None or e["intensity"] < best["intensity"]:
                best = {"from": e["from"], "intensity": e["intensity"],
                        "index": e["index"],
                        "in_hours": round(max(0.0, (t - nowm) / 3600.0), 1)}

        return {"region": region_name, "region_id": region, "current": current,
                "mix": mix, "forecast": forecast, "best": best}

    def _carbon_solar(self):
        """Live solar/grid state from the Sigenergy inverter device (found by
        its pvPowerWatts state, so no hardcoded id). Empty dict if absent — the
        advisor then falls back to a carbon-only recommendation."""
        inv = None
        try:
            for d in indigo.devices.iter(self._SIGEN_PLUGIN_ID):
                if "pvPowerWatts" in d.states:
                    inv = d
                    break
        except Exception:
            return {}
        if inv is None:
            return {}
        # A disabled device's states are FROZEN and an errored one's are
        # STALE (v2.95.2) — a midday freeze kept advising loads onto 4 kW of
        # export that had stopped hours before. Unknown is the honest answer,
        # and the advice already handles 'no solar data'.
        if not getattr(inv, "enabled", True) or (getattr(inv, "errorState", "") or "").strip():
            return {}
        st = inv.states

        def g(key):
            v = st.get(key)
            if v is None or str(v).strip() == "":
                return None                 # absent is not zero
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        pv = g("pvPowerWatts")
        home = g("homePowerWatts")
        grid = g("gridPowerWatts")          # negative = exporting to grid
        if pv is None or home is None or grid is None:
            return {}
        soc = g("batterySoc")
        batt = g("batteryPowerWatts")
        return {"pv_w":      round(pv),
                "home_w":    round(home),
                "grid_w":    round(grid),
                "export_w":  round(max(0.0, -grid)),
                "battery_w": round(batt) if batt is not None else None,
                "soc":       round(soc, 1) if soc is not None else None}

    def _carbon_tariff(self):
        """Current import unit rate + tariff name from the published variables."""
        rate, name = None, ""
        try:
            rate = round(float(indigo.variables["elec_unit_rate_p"].value), 2)
        except Exception:
            pass
        try:
            name = indigo.variables["elec_tariff_name"].value
        except Exception:
            pass
        return {"import_p": rate, "name": name}

    @staticmethod
    def _carbon_hhmm(iso):
        """A UTC 'YYYY-MM-DDThh:mmZ' forecast time as a local HH:MM (with a
        'tomorrow' suffix when it rolls past midnight)."""
        import calendar
        try:
            t = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%MZ"))
            lt = time.localtime(t)
            hh = time.strftime("%H:%M", lt)
            now = time.localtime()
            # Strictly LATER than today — a slot from late yesterday (the
            # fetch admits one up to 30 min old) read "23:30 tomorrow" just
            # after midnight (v2.95.4).
            if (lt.tm_year, lt.tm_yday) > (now.tm_year, now.tm_yday):
                return f"{hh} tomorrow"
            return hh
        except Exception:
            return iso

    def _carbon_advice(self, carbon, solar, tariff):
        """Rank the signals the way CliveS's self-sufficiency KPI wants: soak up
        spare solar first (free AND zero-carbon), then a genuinely clean grid,
        then wait for the cleanest window. Tariff is broadly flat on Tracker so
        it informs the wording, not the timing."""
        cur = carbon.get("current") or {}
        cur_int = cur.get("intensity")
        cur_idx = (cur.get("index") or "").lower()
        export_w = solar.get("export_w", 0) or 0
        pv_w = solar.get("pv_w", 0) or 0
        home_w = solar.get("home_w", 0) or 0
        soc = solar.get("soc")
        best = carbon.get("best") or {}
        clean_now = cur_idx in ("very low", "low")

        # 1) Exporting solar — running a load soaks up energy you'd otherwise sell.
        if export_w >= 500:
            return {"action": "run_now", "level": "good",
                    "headline": f"Run it now — exporting {export_w/1000:.1f} kW of solar",
                    "detail": "Spare solar is going to the grid. A load now runs on free, "
                              "zero-carbon energy instead of selling it and buying back later."}
        # 2) Strong solar covering the house with headroom.
        if (pv_w - home_w) >= 1000 and (soc is None or soc < 99):
            return {"action": "run_now", "level": "good",
                    "headline": f"Good time — {(pv_w - home_w)/1000:.1f} kW of spare solar",
                    "detail": "Solar is covering the house with room to spare, so a load runs "
                              "mostly on sunshine."}
        # 3) No solar spare, but the grid itself is clean right now.
        if clean_now and cur_int is not None:
            return {"action": "anytime", "level": "good",
                    "headline": f"Grid is clean now — {cur_int} gCO₂/kWh ({cur_idx})",
                    "detail": "Little solar spare, but the grid is unusually clean right now, "
                              "so it is a fine time to run a load."}
        # 4) Wait for the cleanest window ahead.
        if best and cur_int and best.get("intensity") is not None and best["intensity"] < cur_int:
            saved = round((1 - best["intensity"] / cur_int) * 100)
            when = self._carbon_hhmm(best["from"])
            return {"action": "wait_carbon", "level": "wait",
                    "headline": f"Hold off if you can — cleanest around {when}",
                    "detail": f"The grid is {cur_int} gCO₂/kWh now. Around {when} it drops to "
                              f"{best['intensity']} ({saved}% cleaner)."}
        return {"action": "anytime", "level": "neutral",
                "headline": (f"Grid at {cur_int} gCO₂/kWh" if cur_int is not None
                             else "No strong preference"),
                "detail": "No solar spare and no clearly cleaner window ahead — run whenever suits."}

    # -----------------------------------------------------------------------
    # Activity feed + automation health — a curated "house diary" from the
    # event log (comings/goings, safety, system events), collapsed alerts, and
    # an automation panel (what fires next, what watches for problems, what's
    # switched off, who holds a door code). Powers activity.html. The event log
    # is very chatty (per-sensor motion spam), so the diary is curated by source
    # + pattern rather than dumped raw. Bearer-authed by IWS upstream.
    # -----------------------------------------------------------------------
    _ACTIVITY_NOISE_SRC = ("Device Activity Monitor",)      # motion/CLEAR spam
    _ACTIVITY_SAFETY_RE = re.compile(r"leak|flood|water detect|smoke|\balarm\b|power ?cut", re.I)
    # A script reasoning aloud is not a house event. The battery optimiser
    # narrates its working with bracketed tags — "[FLOOD-GATE ] solar 36.7 kWh
    # / need 21.9 = 1.68x vs 3.0x gate -> NOT eligible" — and the safety regex
    # above matches "flood" and "power cut" in every one of them, so a single
    # evening's run put a dozen near-identical debug lines in the house diary.
    _ACTIVITY_TRACE_RE = re.compile(
        r"^\[[A-Z][A-Z0-9 _-]{2,}\]"          # [FLOOD-GATE ] / [POWERCUT ]
        r"|^(?:calculating|checking|phase \d)"  # running commentary
        r"|^(?:flood prevention|power cut min)", re.I)
    _ACTIVITY_MAX_MSG = 220                     # a Pushover body is not a diary entry

    def handleActivityFeed(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/activityFeed/
        Returns {alerts, diary, automation}. Each section is defensive."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        out = {"ok": True, "now": time.time()}
        try:
            out["alerts"], out["diary"] = self._activity_events()
        except Exception as exc:
            self.logger.warning(f"[Activity] events section failed: {exc}")
            out["alerts"], out["diary"] = [], []
        try:
            out["automation"] = self._activity_automation()
        except Exception as exc:
            self.logger.warning(f"[Activity] automation section failed: {exc}")
            out["automation"] = {}
        return self._evo_reply(out)

    # -----------------------------------------------------------------------
    # Hourly log-error watch feed. The judgement (what is new, what is still
    # unresolved, what is muted noise) belongs to Python Scripts/
    # Log_Error_Watch.py — this only serves the state file it writes, so the
    # page and the Pushover can never disagree about what is wrong.
    #
    # The file deliberately lives in Python Scripts/, NOT /public: that folder
    # is anonymous and reflector-reachable, and raw event-log text carries
    # hostnames, IPs and traceback fragments. This route is Bearer-authed by
    # IWS upstream, which is the whole reason for going through /message/.
    # -----------------------------------------------------------------------
    def handleLogErrors(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/logErrors/
        Returns {ok, feed:{generatedLocal, errors, warnings, rows[]}, lastRun}."""
        out = {"ok": True, "now": time.time(), "feed": None, "lastRun": None}
        try:
            path = os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                                "Python Scripts", "log_error_watch_state.json")
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            out["feed"] = state.get("feed") or {}
            out["lastRun"] = state.get("last_run")
            out["seededAt"] = state.get("seeded_at")
        except FileNotFoundError:
            # Not an error — the watch simply has not run yet.
            out["feed"] = {}
            out["note"] = "log error watch has not run yet"
        except Exception as exc:
            self.logger.warning(f"[LogWatch] feed read failed: {exc}")
            out["ok"] = False
            out["error"] = "feed unavailable"
        return self._evo_reply(out)

    def handlePresenceData(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/presenceData/
        Serves the presence timelines Presence_Watch.py writes to
        Python Scripts/presence_data.json. The file deliberately lives there,
        NOT in /public: that namespace is anonymous and reflector-reachable,
        and this payload is 14 nights of room occupancy and bedroom sleep
        timing. This route is Bearer-authed by IWS upstream (v2.71.0 — the
        same move logErrors made for raw log text in v2.48.0)."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        try:
            path = os.path.join(os.path.dirname(indigo.server.getInstallFolderPath()),
                                "Python Scripts", "presence_data.json")
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            payload["ok"] = True
            return self._evo_reply(payload)
        except FileNotFoundError:
            # Not an error — the watch simply has not run (or is not installed).
            return self._evo_reply({"ok": False, "error": "presence data not built yet",
                                    "note": "Presence_Watch.py has not run on this install"})
        except Exception as exc:
            self.logger.warning(f"[Presence] data read failed: {exc}")
            return self._evo_reply({"ok": False, "error": "presence data unavailable"})

    def _activity_events(self):
        """Turn the raw event log into (alerts, diary). Alerts = errors/warnings
        collapsed by source+message with a repeat count. Diary = a curated,
        low-noise stream of comings/goings, safety and system events."""
        try:
            rows = indigo.server.getEventLogList(returnAsList=True, lineCount=500)
        except Exception:
            rows = []

        def _clean(m):
            m = str(m or "").strip()
            return re.sub(r"^\[\d\d:\d\d:\d\d(?:\.\d+)?\]\s*", "", m).strip()

        today = datetime.now().date()
        alerts, diary, diary_seen = {}, [], {}
        for r in rows:
            msg = _clean(r.get("Message"))
            if not msg:
                continue
            src = str(r.get("TypeStr", "")).strip()
            tv = r.get("TypeVal")
            t = r.get("TimeStamp")
            try:
                epoch = time.mktime(t.timetuple()) if hasattr(t, "timetuple") else 0
                # Bare HH:MM for today; "Mon 14:01" once the log window spans days.
                fmt = "%H:%M" if (hasattr(t, "date") and t.date() == today) else "%a %H:%M"
                hhmm = t.strftime(fmt) if hasattr(t, "strftime") else ""
            except Exception:
                epoch, hhmm = 0, ""
            base_src = src.replace(" Error", "").replace(" Warning", "").strip()
            # A core-server message carries the BARE level as its source, and
            # the replace above is a no-op on that (no leading space) — so those
            # rows used to be attributed to a plugin called "Error"/"Warning".
            if base_src in ("", "Error", "Warning"):
                base_src = "Indigo Server"
            level = ("error" if (tv == 1 or src.endswith("Error"))
                     else "warn" if (tv == 3 or src.endswith("Warning")) else "info")

            # Alerts — collapse errors + warnings so 50 identical lines read as
            # one. Digits are normalised in the KEY (not the display) so variants
            # of the same fault merge too — "read error regs 30220-30223" and
            # "regs 30216-30219" become one row with a count.
            if level in ("error", "warn"):
                key = base_src + "|" + re.sub(r"\d+", "#", msg)[:80]
                a = alerts.get(key)
                if a is None:
                    disp = (msg[:157] + "…") if len(msg) > 158 else msg
                    alerts[key] = {"src": base_src, "message": disp, "level": level,
                                   "count": 1, "last": hhmm, "_ep": epoch}
                else:
                    a["count"] += 1
                    if epoch >= a["_ep"]:
                        a["last"], a["_ep"] = hhmm, epoch

            # Diary — curated by source + pattern (skip motion spam entirely).
            if base_src in self._ACTIVITY_NOISE_SRC:
                continue
            low = msg.lower()
            cat = None
            if "lock" in src.lower():
                # The readable "... Lock Manager: Door unlocked ..." line. The raw
                # "Z-Wave: received ... status update" echo of the SAME event is
                # deliberately not matched here, so a lock event is one diary row.
                cat = "lock"
            elif "garage door" in low:
                cat = "lock"
            elif self._ACTIVITY_SAFETY_RE.search(msg):
                cat = "safety"
            elif src == "Application" and low.startswith("started plugin"):
                cat = "system"          # one clean line per restart, not the full 5-line lifecycle
            if cat and not self._ACTIVITY_TRACE_RE.search(msg):
                disp = (msg[:self._ACTIVITY_MAX_MSG - 1] + "…") if len(msg) > self._ACTIVITY_MAX_MSG else msg
                # Collapse repeats the same way alerts do: digits normalised in
                # the KEY only, so "Door locked manually [Node: 44]" three times
                # is one row with a count rather than three identical rows.
                dkey = base_src + "|" + cat + "|" + re.sub(r"\d+", "#", msg)[:80]
                d = diary_seen.get(dkey)
                if d is None:
                    diary_seen[dkey] = {"time": hhmm, "epoch": epoch, "src": base_src,
                                        "msg": disp, "level": level, "cat": cat, "count": 1}
                    diary.append(diary_seen[dkey])
                else:
                    d["count"] += 1
                    if epoch >= d["epoch"]:
                        d["time"], d["epoch"] = hhmm, epoch

        alert_list = sorted(alerts.values(), key=lambda a: -a["_ep"])[:15]
        for a in alert_list:
            a.pop("_ep", None)
        diary = sorted(diary, key=lambda d: -d["epoch"])[:40]
        return alert_list, diary

    @staticmethod
    def _parse_lock_code_trigger(name):
        """Parse a 'Lock <person> Front Door Unlock Code (<slot>) <label>'
        trigger name into {person, slot, label}, or None if it doesn't match.
        PIN digits are NEVER surfaced to the browser: any run of 3+ digits in
        the free-text label is scrubbed (a wholly-numeric label OR an embedded
        number like 'code 4471' — the whole label needn't be numeric)."""
        m = re.match(r"Lock (.+?) Front Door Unlock Code \((\d+)\)\s*(.*)$", name or "")
        if not m:
            return None
        lbl = m.group(3).strip()
        # Three or more digits ANYWHERE in the label ('19 81', '4-4-7-1') is
        # a PIN reminder; the roster only needs person + slot, so drop it.
        if sum(c.isdigit() for c in lbl) >= 3:
            lbl = ""
        return {"person": m.group(1).strip(), "slot": int(m.group(2)), "label": lbl}

    def _activity_automation(self):
        """Schedules due next, the error-watch triggers, what's switched off,
        and the per-person door-code roster (parsed from trigger names)."""
        now_epoch = time.time()
        next_up, disabled = [], []
        sched_total = sched_off = 0
        for s in indigo.schedules:
            sched_total += 1
            if not s.enabled:
                sched_off += 1
                disabled.append({"name": s.name, "kind": "schedule"})
                continue
            try:
                ne = s.nextExecution
                if ne and ne.year > 2000:          # skip the 0001 "not armed" sentinel
                    ep = time.mktime(ne.timetuple())
                    next_up.append({"name": s.name, "epoch": ep,
                                    "when": ne.strftime("%a %H:%M"),
                                    "in_min": round((ep - now_epoch) / 60.0)})
            except Exception:
                pass
        next_up = sorted(next_up, key=lambda x: x["epoch"])[:8]

        watchers, codes = [], []
        trig_total = trig_off = 0
        for t in indigo.triggers:
            trig_total += 1
            if not t.enabled:
                trig_off += 1
                disabled.append({"name": t.name, "kind": "trigger"})
                continue
            if (getattr(t, "pluginTypeId", "") or "") == "eventLogError":
                watchers.append({"name": t.name})
            info = self._parse_lock_code_trigger(t.name)
            if info:
                codes.append(info)
        codes.sort(key=lambda c: c["slot"])
        return {
            "next":     next_up,
            "watchers": watchers,
            "disabled": disabled,
            "codes":    codes,
            "counts": {"schedules": sched_total, "schedules_off": sched_off,
                       "triggers": trig_total, "triggers_off": trig_off},
        }

    def _apply_log_level(self, value):
        """Point the logLevel pref at the EVENT-LOG handler, not at the logger.

        Indigo hands every plugin two handlers and plugin_base.py says plainly
        why: the logger sits at THREADDEBUG "so everything gets to each
        handler - the handlers can then filter messages at the levels they
        want". indigo_log_handler echoes to the shared Indigo event log and
        starts at Info; plugin_file_handler writes this plugin's own file and
        takes everything.

        Setting the level on the LOGGER, which is what this did until now,
        gates before BOTH handlers. At the default logLevel of Info that threw
        every Debug record away before the file handler ever saw it - measured
        06-09-2026, the live plugin.log held 5 Info and 3 Warning lines and no
        Debug line at all. That is harmless while nothing logs at Debug, and
        the moment the routine narration moved there it would have DESTROYED
        it rather than redirecting it to this plugin's own log. Guarded
        coerce: a blank or non-numeric field falls back to Info.

        This pref therefore decides how much of the ROUTINE traffic reaches the
        shared event log, and it is a second switch on the narration alongside
        the logActivityToEventLog checkbox: at Debug the _activity() lines
        reach the event log whether that box is ticked or not, and at Warning
        they do not reach it even when it is. Both field helps say so.

        Faults are outside its remit, which is why the floor is capped at
        WARNING. Picking "Error" would otherwise have set indigo_log_handler
        to 40 and silently dropped all 28 self.logger.warning() lines out of
        the event log - and Log_Error_Watch.py reads the event log and nothing
        else, so that setting would have blinded the estate's only watcher to
        every warning this plugin raises. (The 56 faults raised through the
        module log() helper were never at risk: indigo.server.log bypasses the
        handlers entirely.) The cap makes "Error" behave as "Warning", which is
        a smaller cost than a fault nobody sees.
        """
        try:
            # int() alone: blank, None and junk all raise and land on the
            # fallback below, so an "is it blank" test in front of it would be
            # a guard that can never be the one that speaks.
            lvl = int(value)
        except (ValueError, TypeError):
            lvl = 20
        handler = getattr(self, "indigo_log_handler", None)
        if handler is not None:
            handler.setLevel(min(lvl, logging.WARNING))
        # Leave the logger itself wide open, so this plugin's own file keeps
        # receiving everything whatever the user picks for the event log.
        file_handler = getattr(self, "plugin_file_handler", None)
        self.logger.setLevel(getattr(file_handler, "level", None) or logging.DEBUG)

    def _activity(self, message):
        """Routine narration: per-restart plumbing, per-file writes, thread
        start and stop. Info when the user has asked for it, otherwise Debug.
        Both reach this plugin's own log file; which of them ALSO reaches the
        shared Indigo event log is the Log Level pref's business, so at Debug
        even the quiet form gets through and at Warning even the loud form does
        not. Never call this for a fault - see the logActivityToEventLog note
        in __init__ for why.

        getattr() rather than self.log_activity so a half-built instance (a
        test's bare plugin, or a failure part-way through __init__) still logs
        rather than raising inside a logging call.
        """
        if getattr(self, "log_activity", False):
            self.logger.info(message)
        else:
            self.logger.debug(message)

    def _startup_summary(self):
        """The ONE event-log line startup is worth. Indigo already logs
        "Starting plugin" and "Started plugin" either side of it, so this only
        has to say what the plugin ended up running - which is exactly what
        the nine demoted start-up lines used to convey between them."""
        bits = []
        if getattr(self, "cam_user", "") and getattr(self, "cam_pass", "") and CAMERAS:
            bits.append(f"{len(CAMERAS)} camera{'' if len(CAMERAS) == 1 else 's'}")
        elif CAMERAS:
            bits.append(f"{len(CAMERAS)} camera(s) configured but no credentials")
        else:
            bits.append("no cameras")
        if getattr(self, "_mjpeg_server", None) is not None:
            bits.append(f"MJPEG proxy on :{MJPEG_PROXY_PORT}")
        if getattr(self, "_go2rtc_proc", None) is not None:
            bits.append("go2rtc running")
        return f"{self.pluginDisplayName} started - {', '.join(bits)}"

    def _note_bootstrap_seed(self, client_ip):
        """True the FIRST time this plugin run hands the API key to `client_ip`.

        A repeat seed to a browser that already has it is routine; a seed to an
        address never seen before is worth a line in the shared log, because it
        is the only record that a new device on the LAN was given the key. The
        latch is per plugin run, so a restart re-announces every device once.
        """
        seen = self.__dict__.setdefault("_bootstrap_seen", set())
        if client_ip in seen:
            return False
        seen.add(client_ip)
        return True

    def _resolve_credentials(self, prefs, secrets_mod=None):
        """One home for the credential resolution __init__ performs:
        IndigoSecrets first, PluginConfig fallback. `secrets_mod` is the
        (possibly freshly reloaded) IndigoSecrets module, or None for a
        GUI-only install — the prefs fallback then carries everything."""
        g = (lambda n: (getattr(secrets_mod, n, "") or "")) if secrets_mod else (lambda n: "")
        p = lambda n: (prefs.get(n, "") or "")
        self.api_url  = (g("INDIGO_URL") or p("indigoUrl")).strip() or "http://127.0.0.1:8176"
        self.api_key  = (g("INDIGO_API_KEY") or g("CLAUDEBRIDGE_BEARER_TOKEN")
                         or p("indigoApiKey")).strip()
        self.cam_user = (g("DAHUA_USER") or p("dahuaUser")).strip()
        self.cam_pass = (g("DAHUA_PASS") or p("dahuaPass")).strip()
        self.sigen_legacy_url = (g("SIGEN_DASHBOARD_URL") or p("sigenLegacyUrl")).strip()

    def menuRegenerateConfig(self, valuesDict=None, typeId=None):
        """Menu: re-read IndigoSecrets, rewrite config.js AND re-sync the HTML
        pages into Web Assets/public/ without a restart. Useful after editing
        IndigoSecrets.py or any page in the bundle's static/pages/ folder.
        GUI-only installs (no IndigoSecrets.py) keep their PluginConfig
        credentials — the old version dropped them and wiped api_url/api_key
        to empty strings here."""
        import importlib
        secrets_mod = None
        try:
            import IndigoSecrets
            importlib.reload(IndigoSecrets)
            secrets_mod = IndigoSecrets
        except ImportError:
            pass    # GUI-only install — PluginConfig fallback below
        except Exception as exc:
            log(f"[Menu] Reload IndigoSecrets failed: {exc} — "
                f"using PluginConfig values", level="WARNING")
        self._resolve_credentials(self.pluginPrefs, secrets_mod)
        self._sync_pages_to_public()
        self._mirror_custom_pages()
        self._write_config_js()
        self._sync_pages_to_domio()
        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        """Apply Configure changes LIVE. Every pref cached at __init__ was
        previously restart-only — including the bootstrapKeySeed security
        toggle, which read as saved-and-done in the dialog while the old value
        stayed in force. Camera list/swap-out changes still need a restart
        (they rebuild go2rtc + the pollers) and say so."""
        if userCancelled:
            return
        prefs = valuesDict or {}
        self._apply_log_level(prefs.get("logLevel", 20))
        self.bootstrap_key_seed = as_bool(prefs.get("bootstrapKeySeed"), True)
        self.log_activity = as_bool(prefs.get("logActivityToEventLog"), False)
        secrets_mod = None
        try:
            import IndigoSecrets as secrets_mod
        except ImportError:
            pass
        old_creds = (self.cam_user, self.cam_pass)
        self._resolve_credentials(prefs, secrets_mod)
        try:
            self._write_config_js()
        except Exception as exc:
            self.logger.warning(f"[Prefs] config.js rewrite failed: {exc}")
        # Weather fields were startup-only and the dialog never said so
        # (v2.95.2): re-arm the thread so a key or coordinate entered here
        # takes effect now. _start_weather_thread is a no-op on blank values.
        try:
            self._stop_weather_thread()
            self._weather_stop = threading.Event()
            self._weather_thread = None
            self._start_weather_thread()
        except Exception as exc:
            self.logger.warning(f"[Prefs] weather thread restart failed: {exc}")
        if not self.cfg_loaded:
            # Compare against what is IN FORCE, not against pluginPrefs — the
            # host may have merged the dialog's values into pluginPrefs before
            # this callback, in which case the two always matched and the
            # notice could never appear.
            try:
                new_cams = _parse_cameras(prefs.get("camerasJson", ""))
            except Exception:
                new_cams = None
            old_cams = new_cams is not None and new_cams != CAMERAS
            old_swap = (prefs.get("swapOutHost", "") or "").strip() != SWAP_OUT_HOST
            if old_cams or old_swap:
                self.logger.info("[Prefs] camera changes apply on the next plugin restart")
        if (self.cam_user, self.cam_pass) != old_creds and CAMERAS:
            self.logger.info("[Prefs] camera credentials changed — go2rtc and the snapshot "
                             "poller pick them up on the next plugin restart")

    # --------------------------------------------------------
    # One-time setup links (v1.20.1)
    # --------------------------------------------------------
    # A setup link seeds a browser that can't reach the :8177 /bootstrap
    # endpoint (i.e. anything arriving over the Indigo reflector). The menu
    # item writes setup-<token>.json (the key payload) plus setup-qr-<token>.svg
    # (a QR of the redeem URL) into the public folder under a high-entropy
    # unguessable name. setup.html redeems the token: it fetches the JSON,
    # stores the key in localStorage, then calls the burnSetupToken endpoint
    # (now authenticated — it has the key) so the files are deleted on first
    # use. Unredeemed links are swept by TTL from the camera poll loop.

    SETUP_LINK_TTL_SECONDS = 600          # unredeemed links die after 10 min
    _SETUP_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

    def _cleanup_setup_links(self, force_all=False):
        """Delete expired (or all, on shutdown/startup) setup-link artefacts."""
        pub = self._public_dashboards_dir()
        try:
            names = os.listdir(pub)
        except Exception:
            return
        now = time.time()
        for name in names:
            if not (name.startswith("setup-") and name.endswith((".json", ".svg"))):
                continue
            path = os.path.join(pub, name)
            try:
                expired = (now - os.path.getmtime(path)) > self.SETUP_LINK_TTL_SECONDS
                if force_all or expired:
                    os.remove(path)
                    log(f"[SetupLink] Removed {'stale ' if not force_all else ''}{name}")
            except Exception:
                pass

    # --------------------------------------------------------
    # Plugin-provided MCP tools (v3.12.0)
    # --------------------------------------------------------

    def handle_mcp_tool_invoke(self, action, dev=None, callerWaitingForResult=True):
        """The hidden mcp_tool_invoke action. An Indigo MCP server that reads
        Contents/Resources/mcp-manifest.json calls it with props
        {"tool": <bare name>, "arguments": <JSON string>} and gets a JSON-string
        envelope back; the work is done by mcp_tools.dispatch(), imported here
        and nowhere else so a fault in it can never reach startup.

        Every hidden action is also an IWS endpoint. A request arriving that
        way carries IWS's request props and no "tool", and is answered with a
        404 reply dict rather than a tool: the tools are for a co-operating
        plugin, not for a browser with the API key."""
        try:
            props = dict(getattr(action, "props", None) or {})
        except Exception:
            props = {}
        if "tool" not in props and any(
                k in props for k in ("incoming_request_method", "incoming_request_id",
                                     "request_body", "url_query_args", "request_headers")):
            return self._evo_reply({"error": "not an HTTP endpoint"}, status=404)
        try:
            import mcp_tools
            raw = props.get("arguments", "{}")
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception as exc:
                return mcp_tools.err("validation", f"arguments must be a JSON object string: {exc}")
            return mcp_tools.dispatch(self, str(props.get("tool") or ""), arguments)
        except Exception as exc:
            self.logger.error(f"[MCP] tool invocation failed: {exc}")
            return json.dumps({"status": "error",
                               "error": {"type": "internal", "message": str(exc)}})

    def handleGetDashboardsConfig(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/getDashboardsConfig/
        Returns the config currently in force plus where it came from, and a
        device index for the editor's pickers. Bearer-authenticated by IWS."""
        try:
            # ONE walk over indigo.devices. The old code zipped a second
            # iteration against the first's list — a device added or removed
            # between the walks shifted every later pairing, silently
            # attaching wrong folder names.
            try:
                folder_names = {f.id: f.name for f in indigo.devices.folders}
            except Exception:
                folder_names = {}
            devices = [{"id": d.id, "name": d.name,
                        "folder": folder_names.get(d.folderId, "")}
                       for d in indigo.devices]
            # Full action-group list (UNfiltered — scenes.json excludes hidden
            # entries, so the editor needs this to be able to un-hide them).
            ag_folders = {}
            try:
                ag_folders = {f.id: f.name for f in indigo.actionGroups.folders}
            except Exception:
                pass
            action_groups = [
                {"id": ag.id, "name": ag.name,
                 "folder": ag_folders.get(ag.folderId, "") or "General"}
                for ag in indigo.actionGroups
            ]
            return self._evo_reply({
                "ok":           True,
                "source":       "store" if self.cfg_loaded else "legacy",
                "config":       self._redact_pin(self._effective_config()),
                "devices":      sorted(devices, key=lambda x: x["name"].lower()),
                "actionGroups": sorted(action_groups,
                                       key=lambda x: (x["folder"].lower(), x["name"].lower())),
                "guestToken":   self.guest_token,   # full-auth callers only (settings page)
                # v2.96.0: what the Rooms card's folder picker draws from.
                "folders":      sorted({f for f in folder_names.values() if f}, key=str.lower),
                "roomFoldersEffective": list(self._room_folders()),
            })
        except Exception as exc:
            self.logger.error(f"[Config] getDashboardsConfig failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    def handleSaveDashboardsConfig(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/saveDashboardsConfig/
        Body: {"config": {cameras, mainCameras, swapOutHost, roomExtras,
        hiddenScenes}}. Validates, persists dashboards_config.json (which then
        becomes the single source of truth) and applies what can be applied
        live. Camera changes need a plugin restart (go2rtc / pollers / proxy
        are built at startup) — the reply says so."""
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
            cfg     = payload.get("config")
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)
        if not isinstance(cfg, dict):
            return self._evo_reply({"ok": False, "error": "config must be an object"}, status=400)
        return self._apply_config(cfg)

    def _apply_config(self, cfg):
        """Validate an editor-shaped config dict, persist it as
        dashboards_config.json and apply what applies live. Returns the IWS
        reply dict the settings endpoint sends: 200 with {ok: true,
        cameraRestartNeeded} or 400/500 with {ok: false, error}. The endpoint
        above and the plugin-provided MCP tools (v3.12.0, mcp_tools.py) both
        come through here, so there is ONE validation path and they cannot
        drift apart. `cfg` must already be a dict."""
        # ── validate ────────────────────────────────────────────────────
        errors  = []
        cameras = cfg.get("cameras") or []
        if not isinstance(cameras, list):
            errors.append("cameras must be a list")
            cameras = []
        # Hosts are later interpolated into go2rtc.yaml RTSP producer lines
        # and MJPEG proxy URLs — an arbitrary string here is a config/URL
        # injection. IP addresses or plain hostnames only.
        _host_ok = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")
        for i, c in enumerate(cameras):
            if not isinstance(c, dict) or not all(c.get(k) for k in ("host", "name", "vendor")):
                errors.append(f"camera {i + 1} needs host, name and vendor")
            elif c.get("vendor") not in ("dahua", "hikvision"):
                errors.append(f"camera {i + 1}: vendor must be dahua or hikvision")
            elif not _host_ok.match(str(c.get("host") or "")):
                errors.append(f"camera {i + 1}: host must be an IP address or "
                              f"plain hostname (letters, digits, dots, hyphens)")
        _slugs = {}
        for i, c in enumerate(cameras):
            if isinstance(c, dict) and c.get("name"):
                slug = self._cam_slug(str(c.get("name")))
                if not slug:
                    errors.append(f"camera {i + 1}: the name must contain letters or digits "
                                  f"(it becomes the go2rtc stream name)")
                elif slug in _slugs:
                    errors.append(f"camera {i + 1}: name {c.get('name')!r} makes the same "
                                  f"stream name as camera {_slugs[slug] + 1} — rename one")
                else:
                    _slugs[slug] = i
        _hosts_seen = [str(c.get("host")) for c in cameras if isinstance(c, dict) and c.get("host")]
        for h in {h for h in _hosts_seen if _hosts_seen.count(h) > 1}:
            errors.append(f"camera host {h} appears more than once — each "
                          f"host becomes one go2rtc stream slug and duplicates "
                          f"break the whole camera config")
        extras = cfg.get("roomExtras")
        if extras is not None and not isinstance(extras, dict):
            errors.append("roomExtras must be an object keyed by room name")
        hidden = cfg.get("hiddenScenes")
        if hidden is not None and not isinstance(hidden, list):
            errors.append("hiddenScenes must be a list")
        main_cams = cfg.get("mainCameras") or []
        cam_hosts = {c.get("host") for c in cameras if isinstance(c, dict)}
        for h in main_cams:
            if h not in cam_hosts:
                errors.append(f"mainCameras entry {h} is not in the cameras list")
        if errors:
            return self._evo_reply({"ok": False, "error": "; ".join(errors)}, status=400)

        pin_req = cfg.get("pinRequired") or []
        if not isinstance(pin_req, list):
            return self._evo_reply({"ok": False, "error": "pinRequired must be a list"}, status=400)
        _pin_in = str(cfg.get("controlPin") or "").strip()
        if _pin_in and not _pin_in.isascii():
            return self._evo_reply({"ok": False, "error": "the control PIN must be plain "
                                    "ASCII (digits or letters)"}, status=400)
        # Start from a copy of any keys the incoming config carries that this
        # handler doesn't model, so a key added via the settings raw-JSON escape
        # hatch survives the save instead of being whitelisted away (v2.37.0
        # round-trip fix — the client now preserves them too). The validated
        # known keys below overwrite their own entries.
        _known = {"cameras", "mainCameras", "swapOutHost", "roomExtras",
                  "hiddenScenes", "controlPin", "pinRequired", "favourites",
                  "customLinks"}
        clean = {k: v for k, v in cfg.items() if k not in _known}
        clean.update({
            "cameras":      cameras,
            "mainCameras":  list(main_cams),
            "swapOutHost":  (cfg.get("swapOutHost") or "").strip(),
            "roomExtras":   extras if isinstance(extras, dict) else {},
            "hiddenScenes": [str(x) for x in (hidden or [])],
            "controlPin":   self._resolve_pin_save(str(cfg.get("controlPin") or "").strip()),
            "pinRequired":  _safe_int_list(pin_req),
        })
        # v2.96.0 keys. Each passes through the unknown-key round trip above;
        # here they are CLEANED so a bad value cannot reach the pages.
        rf = cfg.get("roomFolders")
        if rf is not None:
            if not isinstance(rf, list) or any(not isinstance(x, str) for x in rf):
                return self._evo_reply({"ok": False, "error": "roomFolders must be a list of folder names"}, status=400)
            clean["roomFolders"] = [x.strip()[:60] for x in rf if x.strip()][:100]
        sn = cfg.get("siteName")
        if sn is not None:
            clean["siteName"] = str(sn).strip()[:40]
        veh = cfg.get("vehicles")
        if veh is not None:
            if not isinstance(veh, list):
                return self._evo_reply({"ok": False, "error": "vehicles must be a list"}, status=400)
            out_v = []
            for v in veh:
                if not isinstance(v, dict):
                    continue
                try:
                    out_v.append({"id": int(v.get("id")), "label": str(v.get("label") or "").strip()[:40]})
                except (TypeError, ValueError):
                    continue           # a row without a device id is dropped, like a bad favourite
            clean["vehicles"] = out_v
        # Favourites (v2.10.0): list of {type:"device"|"scene", id:int, label?}.
        # Anything malformed is silently dropped rather than failing the save.
        # v2.76.0 adds {type:"door", id:<door device>, openAction:int,
        # closeAction:int, label?, state?} — the hub's state-driven door tile.
        def _opt_int(v):
            """None for an absent/blank value; int otherwise (raising on junk
            so the caller can drop the whole entry rather than half-save it)."""
            if v is None or str(v).strip() == "":
                return None
            return int(v)

        favs_in = cfg.get("favourites")
        favs_clean = []
        if isinstance(favs_in, list):
            for f in favs_in:
                if not isinstance(f, dict):
                    continue
                ftype = f.get("type")
                if ftype not in ("device", "scene", "door", "room", "group"):
                    continue
                # Group favourite (v2.93.0): ONE tile driving several devices —
                # the living room's three lamps and the fire behind a single
                # press. It has no id of its own, so it is handled before the
                # int(id) below. Each member is {id, onLevel?, openLoop?}:
                # onLevel asks a dimmer for a specific brightness on the way up
                # (the colour lamp wants 100, not wherever it was left), and
                # openLoop marks a device whose state is a belief rather than a
                # reading, so it is counted in the tile's label but never
                # decides which way a press goes. A member with a junk id is
                # dropped alone; a group left with no members is dropped whole,
                # because a tile that commands nothing is a trap, not a tile.
                if ftype == "group":
                    members = []
                    for m in (f.get("devices") or []):
                        if not isinstance(m, dict):
                            continue
                        try:
                            mid = int(m.get("id"))
                        except (TypeError, ValueError):
                            continue
                        member = {"id": mid}
                        lvl = m.get("onLevel")
                        if lvl is not None and str(lvl).strip() != "":
                            try:
                                lvl = int(round(float(lvl)))
                            except (TypeError, ValueError):
                                lvl = None
                            if lvl is not None and 1 <= lvl <= 100:
                                member["onLevel"] = lvl
                        if as_bool(m.get("openLoop"), False):
                            member["openLoop"] = True
                        members.append(member)
                    if not members:
                        continue
                    group_item = {"type": "group", "devices": members}
                    group_label = str(f.get("label") or "").strip()
                    if group_label:
                        group_item["label"] = group_label[:60]
                    favs_clean.append(group_item)
                    continue
                # Room shortcut (v2.89.0): a link to room.html, not a device.
                # It is keyed by the room NAME because that is what rooms.json
                # is keyed by — there is no device id to point at, and a room
                # renamed in Indigo should follow rather than dangle on an id
                # that no longer means anything.
                if ftype == "room":
                    room_name = str(f.get("room") or "").strip()
                    if not room_name:
                        continue
                    room_item = {"type": "room", "room": room_name[:60]}
                    room_label = str(f.get("label") or "").strip()
                    if room_label:
                        room_item["label"] = room_label[:60]
                    favs_clean.append(room_item)
                    continue
                try:
                    fid = int(f.get("id"))
                except (TypeError, ValueError):
                    continue
                item = {"type": ftype, "id": fid}
                if ftype == "door":
                    # An open action always, then a close action, a lockId
                    # (v2.77.0 lock-style door), or both — never neither. A
                    # present-but-junk key drops the entry whole: half a door
                    # saved is a trap, not a tile.
                    try:
                        item["openAction"] = int(f.get("openAction"))
                        close_a = _opt_int(f.get("closeAction"))
                        lock_id = _opt_int(f.get("lockId"))
                    except (TypeError, ValueError):
                        continue
                    if close_a is None and lock_id is None:
                        continue
                    if close_a is not None:
                        item["closeAction"] = close_a
                    if lock_id is not None:
                        item["lockId"] = lock_id
                label = str(f.get("label") or "").strip()
                if label:
                    item["label"] = label[:60]
                # Reading favourites (v2.19.0): a device favourite may pin a
                # specific state to show as a read-only value tile on the hub.
                # A door favourite may override the state it watches (default
                # doorState; onOffState of the contact for lock-style) via the
                # same key.
                fstate = str(f.get("state") or "").strip()
                if ftype in ("device", "door") and fstate:
                    item["state"] = fstate[:60]
                # Colour bands (v2.77.0): a reading tile may colour its value
                # — red below badBelow, amber below warnBelow, green above.
                # A junk band is dropped alone; the reading itself still saves.
                if ftype == "device" and item.get("state"):
                    for band_key in ("warnBelow", "badBelow"):
                        band_val = f.get(band_key)
                        if band_val is None or str(band_val).strip() == "":
                            continue
                        try:
                            item[band_key] = float(band_val)
                        except (TypeError, ValueError):
                            pass
                favs_clean.append(item)
        clean["favourites"] = favs_clean

        # Custom links (v2.x): full-size hub tiles opening an arbitrary URL.
        # {title, url, desc?, icon?}. Only http(s)/relative URLs are accepted —
        # javascript:/data: etc. are rejected (the URL becomes an <a href> on a
        # public page). Anything malformed is dropped rather than failing the save.
        links_in = cfg.get("customLinks")
        links_clean = []
        if isinstance(links_in, list):
            for l in links_in:
                if not isinstance(l, dict):
                    continue
                title = str(l.get("title") or "").strip()
                url   = str(l.get("url") or "").strip()
                if not title or not url:
                    continue
                low = url.lower()
                if not (low.startswith("http://") or low.startswith("https://")
                        or (url.startswith("/") and not url.startswith("//")
                            and not url.startswith("/\\"))):
                    continue               # '//host' is protocol-relative, i.e. off-site
                item = {"title": title[:40], "url": url[:300]}
                desc = str(l.get("desc") or "").strip()
                icon = str(l.get("icon") or "").strip()
                if desc:
                    item["desc"] = desc[:60]
                if icon:
                    item["icon"] = icon[:8]
                links_clean.append(item)
        clean["customLinks"] = links_clean

        # ── persist + apply live ────────────────────────────────────────
        old_cams = [dict(c) for c in CAMERAS]
        try:
            self.cfg_store  = self._save_config_store(clean)
            self.cfg_loaded = True
        except Exception as exc:
            self.logger.error(f"[Config] Could not write dashboards_config.json: {exc}")
            return self._evo_reply({"ok": False, "error": f"write failed: {exc}"}, status=500)

        self.room_extras  = clean["roomExtras"]
        self.main_cameras = clean["mainCameras"]
        self.control_pin  = clean["controlPin"]
        self.pin_required = clean["pinRequired"]
        self.favourites   = clean["favourites"]
        self.custom_links = clean["customLinks"]
        # Normalise BOTH sides through _parse_cameras before comparing —
        # the raw client dicts differ from the normalised CAMERAS list in key
        # order/optional keys, so an unchanged save read as "restart needed".
        camera_restart    = (_parse_cameras(clean["cameras"]) != _parse_cameras(old_cams)
                             or (clean["swapOutHost"] or "") != (SWAP_OUT_HOST or ""))
        try:
            self._write_config_js()
            self._build_rooms_json()
            self._build_scenes_json()
        except Exception as exc:
            self.logger.warning(f"[Config] Post-save refresh failed: {exc}")

        self.logger.info(
            "[Config] dashboards_config.json saved from the settings editor — "
            "now the single source of truth"
            + (" (camera changes need a plugin restart)" if camera_restart else ""))
        return self._evo_reply({"ok": True, "cameraRestartNeeded": camera_restart})

    # --------------------------------------------------------
    # History queries (v2.4.0) — read-only over SQL Logger's DB
    # --------------------------------------------------------
    # Indigo's stock SQL Logger plugin has been recording every device state
    # change into Logs/indigo_history.sqlite all along (one table per device,
    # lowercased state names as TEXT columns, UTC ts). These queries are
    # strictly READ-ONLY (sqlite URI mode=ro) so we can never disturb the
    # logger, and column names are validated against the live table schema
    # so no caller-supplied identifier ever reaches SQL.

    def _history_db_path(self):
        base = indigo.server.getInstallFolderPath()
        return os.path.join(base, "Logs", "indigo_history.sqlite")

    def _history(self):
        """The SQL Logger history, on whichever backend is configured.

        SQLite by default. A user whose SQL Logger writes to PostgreSQL sets
        the backend in Configure; credentials come from IndigoSecrets.py first
        and fall back to the dialog, per the secrets policy.
        """
        if _history_db is None:
            raise ValueError("history_db.py is missing from the plugin bundle")
        # getattr, not attribute access — this has to work before the prefs
        # dict exists (a never-configured install, and the contract tests).
        prefs = getattr(self, "pluginPrefs", None) or {}
        backend = str(prefs.get("historyBackend") or "sqlite").strip().lower()

        def _pick(secret, pref_key, default=""):
            v = secret or prefs.get(pref_key) or default
            return str(v).strip()

        port = _pick(HISTORY_PG_PORT, "pgPort", "5432")
        try:
            port = int(port)
        except (TypeError, ValueError):
            # Guard the coercion — a blank or non-numeric port must not kill
            # the page, it should fall back and say so.
            lg = getattr(self, "logger", None)
            if lg:
                lg.warning(f"[History] pgPort {port!r} is not a number — using 5432")
            port = 5432
        return _history_db.HistoryDB(
            backend=backend,
            sqlite_path=self._history_db_path(),
            pg_config={
                "host":     _pick(HISTORY_PG_HOST, "pgHost", "127.0.0.1"),
                "port":     port,
                "user":     _pick(HISTORY_PG_USER, "pgUser", "postgres"),
                "password": _pick(HISTORY_PG_PASSWORD, "pgPassword"),
                "database": _pick(HISTORY_PG_DATABASE, "pgDatabase", "indigo_history"),
            },
            logger=getattr(self, "logger", None),
        )

    def _history_query(self, params):
        """Shared core for the Bearer endpoint and the guest passthrough.
        params: {action: "states"|"series", deviceId, state?, hours?, maxPoints?}
        Returns a JSON-able dict; raises ValueError with a friendly message."""
        try:
            dev_id = int(params.get("deviceId") or 0)
        except (ValueError, TypeError):
            raise ValueError("deviceId must be an integer")
        if dev_id <= 0:
            raise ValueError("deviceId required")

        hist = self._history()
        table = hist.quote(f"device_history_{dev_id}")
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            # Real states only. The SQL Logger leaves an epoch-suffixed copy of
            # a column behind whenever a logged state changes type, so the
            # picker used to offer "batterysoc" alongside a dead
            # "batterysoc_1782308459229" — 17 such on the Sigen inverter alone.
            cols = hist.columns(conn, dev_id)
            if not cols:
                raise ValueError(f"no history recorded for device {dev_id}")
            by_name = {c["name"]: c for c in cols}

            if (params.get("action") or "series") == "states":
                # count/min/max with no ts index is a FULL TABLE SCAN — on the
                # multi-million-row inverter table that is a multi-second read
                # lock against the logger, fired from the Graphs state picker.
                # ts is monotone in id, so the PK endpoints answer first/last
                # in two B-tree seeks; the row count becomes the id-span
                # estimate (display-only, slightly high across rowid gaps).
                try:
                    first = conn.execute(
                        f'SELECT id, ts FROM {table} ORDER BY id LIMIT 1')[0]
                    last = conn.execute(
                        f'SELECT id, ts FROM {table} ORDER BY id DESC LIMIT 1')[0]
                    rows_est = int(last[0]) - int(first[0]) + 1
                    first_ts, last_ts = first[1], last[1]
                except (IndexError, TypeError, ValueError):
                    rows_est, first_ts, last_ts = 0, "", ""
                return {"ok": True, "deviceId": dev_id,
                        "states": [c["name"] for c in cols],
                        # Types let the page step a boolean instead of sloping
                        # a line between 0 and 1.
                        "types": {c["name"]: c["type"] for c in cols},
                        "backend": hist.backend,
                        "rows": rows_est, "firstTs": first_ts, "lastTs": last_ts}

            requested = str(params.get("state") or "").strip().lower()
            requested = re.sub(r"[^a-z0-9_]", "", requested)
            if requested not in by_name:
                raise ValueError(f"state {requested!r} not recorded for device {dev_id}")
            col = hist.quote(requested)
            try:
                hours = min(2160.0, max(0.25, float(params.get("hours") or 24)))
            except (ValueError, TypeError):
                hours = 24.0
            try:
                max_points = min(1000, max(20, int(params.get("maxPoints") or 240)))
            except (ValueError, TypeError):
                max_points = 240
            bucket = max(60, int(hours * 3600 / max_points))

            # PK-range the window before touching it. The ts filter stays as
            # the correctness boundary; the rowid bound is what stops the
            # query full-scanning a multi-million-row table and locking the
            # SQL Logger out of its own writes (see _pk_window).
            cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
                      - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            lo, _hi = self._pk_window(hist, conn, f"device_history_{dev_id}", cutoff)
            pk_sql, pk_args = self._pk_clause(lo, None)

            # `requested` is guaranteed to be an existing column name (checked
            # against the live column list above), so interpolating it is
            # injection-safe. Same for the bucket size, which is an int.
            num = hist.as_real(col, by_name[requested]["type"])
            rows = conn.execute(
                f'SELECT ({hist.epoch()} / {bucket}) * {bucket} AS bucket, '
                f'       avg({num}), '
                f'       min({num}), '
                f'       max({num}), count(*) '
                f'FROM {table} '
                f'WHERE ts >= {hist.utc_now_minus(hours)} '
                f"  AND {col} IS NOT NULL AND CAST({col} AS TEXT) != '' "
                f'{pk_sql} '
                f'GROUP BY bucket ORDER BY bucket', tuple(pk_args))
            def _f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            return {"ok": True, "deviceId": dev_id, "state": requested,
                    "type": by_name[requested]["type"], "backend": hist.backend,
                    "hours": hours, "bucketSeconds": bucket,
                    "points": [{"t": int(r[0]), "avg": _f(r[1]), "min": _f(r[2]),
                                "max": _f(r[3]), "n": int(r[4])} for r in rows]}
        finally:
            conn.close()

    def handleHistoryQuery(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/historyQuery/
        Body: {"action": "states"|"series", "deviceId": N, "state": "...",
        "hours": N, "maxPoints": N}. Bearer-authenticated by IWS."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        body = action.props.get("request_body") or ""
        try:
            params = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        try:
            return self._evo_reply(self._history_query(params))
        except ValueError as exc:
            return self._evo_reply({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self.logger.error(f"[History] query failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    # --------------------------------------------------------
    # Timeline replay (v2.40.0) — assemble one local day of the house's
    # activity into lanes (presence, lights, doors, heating) + a battery/solar
    # trace, from the SQL Logger history. Powers timeline.html.
    # --------------------------------------------------------

    def _timeline_active_spans(self, hist, conn, dev_id, col, bounds):
        """Return active spans [[startMin, endMin], ...] (minutes from local
        midnight, 0-1440) for a device's boolean column on the given day.
        `bounds` = (start_epoch, start_utc, end_utc). Filters on the RAW ts
        (UTC, index-friendly) — wrapping ts in datetime(...,'localtime') in the
        WHERE would defeat the index and full-scan multi-million-row tables.
        Local minutes come from epoch arithmetic. `col` is caller-validated."""
        start_epoch, start_utc, end_utc = bounds
        table = f"device_history_{dev_id}"
        # PK-range the day before scanning it — see _pk_window. Without this
        # a timeline load full-scans every lane's table on the request thread.
        lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
        pk_sql, pk_args = self._pk_clause(lo, hi)
        # State as of the start of the day (last transition strictly before it).
        # Bounded by the rowid of the day's first row: ts is monotone in id, so
        # the newest row with id < lo IS the last one before midnight, and the
        # planner answers it with a reverse B-tree seek. Until 2.95.1 this one
        # query ran BEFORE the PK window, unbounded and ts-ordered, once per
        # lane device — the full-scan-under-read-lock shape the PK-range work
        # removed everywhere else, left on the page most likely to be scrubbed
        # through a month of days.
        if lo is not None:
            carry = conn.execute(
                f'SELECT "{col}" FROM "{table}" '
                f'WHERE id < ? AND "{col}" IS NOT NULL '
                f'ORDER BY id DESC LIMIT 1', (lo,)).fetchone()
        else:
            carry = conn.execute(
                f'SELECT "{col}" FROM "{table}" '
                f'WHERE "{col}" IS NOT NULL AND ts < ? '
                f'ORDER BY ts DESC LIMIT 1', (start_utc,)).fetchone()
        state = self._as_bool01(carry[0]) if carry else 0
        rows = conn.execute(
            f'SELECT ({hist.epoch()} - {start_epoch}) / 60.0, "{col}" '
            f'FROM "{table}" '
            f'WHERE "{col}" IS NOT NULL AND ts >= ? AND ts < ?{pk_sql} '
            f'ORDER BY ts ASC', (start_utc, end_utc, *pk_args)).fetchall()
        spans, open_at = [], (0 if state else None)
        for mn, v in rows:
            b = self._as_bool01(v)
            mn = max(0.0, min(1440.0, mn))
            if b and open_at is None:
                open_at = mn
            elif not b and open_at is not None:
                if mn > open_at:
                    spans.append([round(open_at, 1), round(mn, 1)])
                open_at = None
        if open_at is not None:
            spans.append([round(open_at, 1), 1440])   # still active at day end
        return [s for s in spans if s[1] > s[0]]

    @staticmethod
    def _as_bool01(v):
        s = str(v).strip().lower()
        if s in ("1", "true", "on", "yes"):
            return 1
        try:
            return 1 if float(s) != 0 else 0
        except (ValueError, TypeError):
            return 0

    def _timeline_day(self, date_str):
        """Build the timeline payload for one LOCAL day (YYYY-MM-DD)."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str or ""):
            raise ValueError("date must be YYYY-MM-DD")
        hist = self._history()

        # UTC bounds of the LOCAL day. time.mktime honours the DST that was in
        # force on that date, so BST/GMT is handled. We filter the raw UTC ts
        # against these (index-friendly) and derive local minutes from the
        # start_epoch offset.
        import time as _t
        naive = datetime.strptime(date_str, "%Y-%m-%d")
        start_epoch = int(_t.mktime(naive.timetuple()))
        # The NEXT local midnight, not +86400: a clock-change day is 23 or 25
        # hours long, and a fixed day put the last hour in the wrong bucket.
        end_epoch = int(_t.mktime((naive + timedelta(days=1)).timetuple()))
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = datetime.fromtimestamp(end_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        bounds = (start_epoch, start_utc, end_utc)

        # Device sets from the rooms map (already classified). Fall back to a
        # live rebuild if the file isn't there yet.
        try:
            with open(os.path.join(self._public_dashboards_dir(), "rooms.json"),
                      encoding="utf-8") as _f:
                rooms = json.load(_f).get("rooms", {})
        except Exception:
            rooms = (self._build_rooms_json() or {}).get("rooms", {})

        lanes_cfg = [
            ("presence", "Presence",       "motion",    "onoffstate",     "#34a0d6"),
            ("lights",   "Lights",         "lights",    "onoffstate",     "#ff9f0a"),
            ("doors",    "Doors & windows","windows",   "onoffstate",     "#af52de"),
            ("heating",  "Heating",        "radiators", "hvacheaterison", "#ff453a"),
        ]
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            def has_col(dev_id, want):
                # Artefact-filtered, so the prefix fallback below can no longer
                # land on a dead "<state>_<epoch>" type-change duplicate — it
                # only ever finds a real variant such as "batterysoc_ui".
                cols = hist.column_names(conn, dev_id)
                if want in cols:
                    return want
                for c in cols:
                    if c.startswith(want):
                        return c
                return None

            lanes = []
            for key, label, cat, col, colour in lanes_cfg:
                ids = []
                for r in rooms.values():
                    ids += (r.get(cat) or [])
                rows = []
                for dev_id in dict.fromkeys(ids):     # de-dup, keep order
                    real = has_col(dev_id, col)
                    if not real:
                        continue
                    spans = self._timeline_active_spans(hist, conn, dev_id, real, bounds)
                    if spans:
                        rows.append({"id": dev_id,
                                     "name": self._device_name(dev_id),
                                     "spans": spans})
                rows.sort(key=lambda x: x["name"].lower())
                lanes.append({"key": key, "label": label,
                              "colour": colour, "devices": rows})

            energy = self._timeline_energy(hist, conn, bounds)
        finally:
            conn.close()
        return {"ok": True, "date": date_str, "lanes": lanes, "energy": energy}

    def _timeline_energy(self, hist, conn, bounds):
        """Battery SOC + solar-power trace for the day, 5-min samples. Uses the
        same raw-ts / epoch approach as the lanes (index-friendly)."""
        start_epoch, start_utc, end_utc = bounds
        inv = None
        for d in indigo.devices:
            st = getattr(d, "states", {}) or {}
            if "batterySoc" in st and "pvPowerWatts" in st:
                inv = d.id
                break
        if inv is None:
            return None
        table = f"device_history_{inv}"
        # Artefact-filtered, so the startswith fallbacks below cannot land on a
        # dead "batterysoc_<epoch>" left behind by a logged type change.
        cols = hist.column_names(conn, inv)
        soc = "batterysoc" if "batterysoc" in cols else \
            next((c for c in cols if c.startswith("batterysoc") and not c.endswith("_ui")), None)
        pv = "pvpowerwatts" if "pvpowerwatts" in cols else \
            next((c for c in cols if c.startswith("pvpowerwatts") and not c.endswith("_ui")), None)
        if not soc:
            return None
        pv_sel = f', avg(CAST("{pv}" AS REAL))' if pv else ", NULL"
        # The inverter is the largest table in the DB — this is the single
        # worst offender for the lock-the-logger-out scan. PK-range it.
        lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
        pk_sql, pk_args = self._pk_clause(lo, hi)
        rows = conn.execute(
            f'SELECT (({hist.epoch()} - {start_epoch}) / 300) AS b5, '
            f'       avg(CAST("{soc}" AS REAL)){pv_sel} '
            f'FROM "{table}" WHERE ts >= ? AND ts < ? AND "{soc}" IS NOT NULL'
            f'{pk_sql} '
            f'GROUP BY b5 ORDER BY b5', (start_utc, end_utc, *pk_args)).fetchall()
        pts = [{"m": int(b5) * 5,
                "soc": round(soc_v, 1) if soc_v is not None else None,
                "pv": round(pv_v) if pv_v is not None else None}
               for b5, soc_v, pv_v in rows]
        return {"points": pts}

    def _device_name(self, dev_id):
        try:
            return indigo.devices[dev_id].name
        except Exception:
            return f"#{dev_id}"

    # --------------------------------------------------------
    # Solar string hours (v2.79.0) — per-hour per-string energy for the
    # Energy page's stacked hourly chart, integrated from the SQL-logged
    # pv1Watts..pv4Watts states (SigenEnergyManager v5.67.0).
    # --------------------------------------------------------

    @staticmethod
    def _hour_frac(hb, now_hour, now_frac):
        """Elapsed fraction of hour `hb`, or None when it hasn't started.

        A mean over an hour's samples only covers the part that HAS happened,
        so the current hour's energy is that mean scaled by how much of the
        hour has run. now_hour None = the day is not today, all hours whole."""
        if now_hour is None:
            return 1.0
        if hb > now_hour:
            return None                      # the future has no samples
        if hb == now_hour:
            return max(0.0, min(1.0, now_frac))
        return 1.0

    @staticmethod
    def _sane_avg_sql(col):
        """SQL for the mean of `col` over a group, ignoring impossible samples.

        Valid on both SQLite and PostgreSQL: BETWEEN, CASE and CAST are
        standard, and avg() skips NULLs on both. See PV_STRING_SANE_MAX_W for
        why a reader has to filter at all and how the bound was measured.
        """
        cast = f'CAST("{col}" AS REAL)'
        return (f'avg(CASE WHEN {cast} BETWEEN {-PV_STRING_SANE_MAX_W} '
                f'AND {PV_STRING_SANE_MAX_W} THEN {cast} END)')

    @staticmethod
    def _string_hours_payload(hour_rows, now_hour, now_frac):
        """Pure: hour-bucket rows -> (strings, site) 24-entry lists.

        hour_rows: [(hb, avg_w1..avg_w4, avg_site_w), ...] — hb is the local
        hour 0-23, avgs are mean watts over that hour's samples (None when a
        column had none). Mean power over the hour IS the hour's kWh at /1000
        — exact only if the samples are evenly spaced, which they effectively
        are while PV is moving (the logger writes on change, and PV changes
        every poll in daylight). Verified against the day's own total.

        An hour with no row stays None in BOTH lists — the page draws a gap
        rather than a fabricated zero (absent is never a reading). A row
        whose per-string columns are all absent still yields its site figure,
        which is what covers the days before per-string logging began.
        """
        strings = [None] * 24
        site = [None] * 24
        for row in hour_rows or []:
            try:
                hb = int(row[0])
            except (TypeError, ValueError):
                continue
            if not (0 <= hb <= 23):
                continue
            frac = Plugin._hour_frac(hb, now_hour, now_frac)
            if frac is None:
                continue

            def _kwh(v):
                try:
                    return round(float(v) / 1000.0 * frac, 3)
                except (TypeError, ValueError):
                    return None

            parts = [_kwh(v) for v in row[1:5]]
            if all(p is not None for p in parts):
                strings[hb] = parts
            if len(row) > 5:
                s = _kwh(row[5])
                if s is not None:
                    site[hb] = s
        return strings, site

    def _solar_string_hours(self, date_str):
        """Per-string AND site-total kWh per LOCAL hour of one day, from the
        inverter's pv1watts..pv4watts + pvpowerwatts history columns.
        PK-ranged like every other read of this DB.

        The site series matters as much as the strings: it has been logged
        for years, so it covers every hour of every day including those
        before per-string logging began — which is what lets BOTH pages draw
        a full day from this ONE call, with no second history fetch and no
        slot-midpoint approximation. hours=[] only when even the site column
        is missing."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str or ""):
            raise ValueError("date must be YYYY-MM-DD")
        hist = self._history()

        import time as _t
        naive = datetime.strptime(date_str, "%Y-%m-%d")
        start_epoch = int(_t.mktime(naive.timetuple()))
        # The NEXT local midnight, not +86400: a clock-change day is 23 or 25
        # hours long, and a fixed day put the last hour in the wrong bucket.
        end_epoch = int(_t.mktime((naive + timedelta(days=1)).timetuple()))
        start_utc = datetime.fromtimestamp(start_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = datetime.fromtimestamp(end_epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        inv = None
        for d in indigo.devices:
            st = getattr(d, "states", {}) or {}
            if "pvPowerWatts" in st and "batterySoc" in st:
                inv = d.id
                break
        if inv is None:
            return {"ok": True, "date": date_str, "hours": [], "site": []}

        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            cols = hist.column_names(conn, inv)
            if "pvpowerwatts" not in cols:
                return {"ok": True, "date": date_str, "hours": [], "site": []}
            pv_cols = [f"pv{i}watts" for i in range(1, 5)]
            have_strings = all(c in cols for c in pv_cols)
            # NULL placeholders keep the row shape fixed at 6 columns, so the
            # pure decoder never has to know whether strings are logged here.
            #
            # _sane_avg_sql nulls an implausible sample BEFORE avg(), which
            # ignores NULLs — so an hour keeps the mean of its real samples,
            # and an hour with nothing left yields NULL, which the page draws
            # as a gap rather than a fabricated figure.
            _sane_avg = self._sane_avg_sql
            sel = ", ".join(_sane_avg(c) if have_strings else "NULL"
                            for c in pv_cols)
            table = f"device_history_{inv}"
            lo, hi = self._pk_window(hist, conn, table, start_utc, end_utc)
            pk_sql, pk_args = self._pk_clause(lo, hi)
            rows = conn.execute(
                f'SELECT (({hist.epoch()} - {start_epoch}) / 3600) AS hb, {sel}, '
                f'       {_sane_avg("pvpowerwatts")} '
                f'FROM "{table}" WHERE ts >= ? AND ts < ? AND "pvpowerwatts" IS NOT NULL'
                f'{pk_sql} '
                f'GROUP BY hb ORDER BY hb', (start_utc, end_utc, *pk_args)).fetchall()
        finally:
            conn.close()

        now = datetime.now()
        if date_str == now.strftime("%Y-%m-%d"):
            # Same arithmetic as the SQL bucket (epoch - local midnight), so
            # the two agree on the 25-hour October day where now.hour does not.
            since_midnight = _t.time() - start_epoch
            now_hour = int(since_midnight // 3600)
            now_frac = (since_midnight % 3600) / 3600.0
        else:
            now_hour, now_frac = None, 1.0
        strings, site = self._string_hours_payload(rows, now_hour, now_frac)
        return {"ok": True, "date": date_str, "hours": strings, "site": site}

    def handleLaundryPlan(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/laundryPlan/
        Serves the laundry plan the companion script last worked out. Bearer-authed
        upstream by IWS like every /message route — see _run_appliance_scheduler for why
        this is not a static file under /public."""
        if not self._sigen_available():
            return self._evo_reply(
                {"ok": False, "reason": "sem_absent",
                 "error": "the Laundry page needs the SigenEnergyManager plugin, which is "
                          "not installed on this server"}, status=200)
        plan = self._read_laundry_plan()
        if plan is None:
            return self._evo_reply(
                {"ok": False,
                 "error": "no plan yet — Appliance_Scheduler.py has not run, or could not "
                          "see the solar forecast"}, status=200)
        plan = dict(plan)
        plan["ok"] = True
        return self._evo_reply(plan)

    def handleLaundryDeadline(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/laundryDeadline/
        Body: {"appliance": "washing_machine", "deadline": "HH:MM"} to say when that
        appliance must be finished by, or {"deadline": ""} to go back to the default.
        The appliance key defaults to washing_machine for older callers.

        Replans immediately and returns the new plan, so the page shows the answer to the
        question just asked rather than the previous one until the next tick.
        """
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be an object"}, status=400)

        wanted = normalise_deadline(payload.get("deadline", ""))
        if wanted is None:
            return self._evo_reply(
                {"ok": False, "error": "deadline must be a time like 16:00, or empty"},
                status=400)

        # Which appliance. The key names the variable, so it has to be checked as tightly as
        # the time is: this writes an Indigo variable, and a key of "../../x" or one carrying
        # a space would create a variable nothing can ever read back.
        key = normalise_appliance_key(payload.get("appliance", "washing_machine"))
        if key is None:
            return self._evo_reply(
                {"ok": False, "error": "appliance must be a key like washing_machine"},
                status=400)

        name = f"{key}_deadline"
        try:
            if name in indigo.variables:
                indigo.variable.updateValue(indigo.variables[name].id, wanted)
            else:
                indigo.variable.create(name, wanted)
        except Exception as exc:
            self.logger.error(f"[Laundry] could not set the deadline: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

        self._run_appliance_scheduler()
        return self._evo_reply({"ok": True, "appliance": key, "deadline": wanted,
                                "plan": self._read_laundry_plan()})

    def handleSolarStringHours(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/solarStringHours/
        Body: {"date": "YYYY-MM-DD"} (default: today, local). Bearer-authed
        upstream by IWS like every /message route. Cached 120 s — the chart
        polls with the page's 5-min history cycle, but several open pages
        must not each pay a history query."""
        body = action.props.get("request_body") or ""
        try:
            params = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        date_str = str(params.get("date") or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        cache = getattr(self, "_sol_hours_cache", None)
        if cache and cache[0] == date_str and time.time() < cache[1]:
            return self._evo_reply(cache[2])
        try:
            payload = self._solar_string_hours(date_str)
        except ValueError as exc:
            return self._evo_reply({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self.logger.error(f"[SolarHours] build failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)
        self._sol_hours_cache = (date_str, time.time() + 120, payload)
        return self._evo_reply(payload)

    def handleTimelineDay(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/timelineDay/
        Body: {"date": "YYYY-MM-DD"} (default: today, local). Bearer-authed."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        body = action.props.get("request_body") or ""
        try:
            params = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        date_str = str(params.get("date") or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            return self._evo_reply(self._timeline_day(date_str))
        except ValueError as exc:
            return self._evo_reply({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self.logger.error(f"[Timeline] build failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    # --------------------------------------------------------
    # Home Insights (v2.42.0) — auto-surface anomalies vs each device's OWN
    # norms, computed from the history the SQL Logger already keeps. Not a
    # status page (system-health owns live errors): these are "different from
    # usual" findings — a battery falling fast, a normally-chatty motion
    # sensor gone silent, a room off its usual temperature, a device on far
    # longer than its daily norm. Powers the hub's Insights card.
    # --------------------------------------------------------

    # Thresholds — deliberately conservative so the card stays quiet unless
    # something is genuinely off. Tweak here, not in the evaluators.
    _INS_BATT_WEEK_DROP   = 12     # pts fallen in 7 days before we care
    _INS_BATT_WARN_DAYS   = 21     # projected days-to-empty for a warn
    _INS_QUIET_EXPECTED   = 6.0    # events expected so far today before silence is odd
    _INS_TEMP_NOTE_DELTA  = 2.5    # degC off the same-hour norm
    _INS_TEMP_WARN_DELTA  = 4.0
    _INS_TEMP_MIN_SAMPLES = 12     # history rows needed for a meaningful norm
    _INS_ON_MIN_EXTRA     = 90.0   # minutes beyond the daily norm
    _INS_ON_RATIO         = 2.0    # and at least this multiple of the norm

    @staticmethod
    def _insight_battery_trend(name, dev_id, now_pct, week_ago_pct):
        """A battery that has fallen fast over the last week, with a
        days-to-empty projection. Returns an insight dict or None."""
        if now_pct is None or week_ago_pct is None:
            return None
        drop = week_ago_pct - now_pct
        if drop < Plugin._INS_BATT_WEEK_DROP:
            return None
        per_day = drop / 7.0
        days_left = int(now_pct / per_day) if per_day > 0 else 999
        level = "warn" if (days_left <= Plugin._INS_BATT_WARN_DAYS or now_pct <= 20) else "note"
        return {"kind": "battery", "level": level, "icon": "battery",
                "title": f"{name} battery falling fast",
                "detail": f"{week_ago_pct:.0f}% a week ago, {now_pct:.0f}% now — "
                          f"about {days_left} days left at this rate.",
                "deviceId": dev_id}

    @staticmethod
    def _insight_quiet_sensor(name, dev_id, today_events, daily_avg, hours_elapsed):
        """A motion/presence sensor that normally logs plenty but has logged
        NOTHING today. Expected-so-far scales the norm by the elapsed part of
        the day, so an early-morning check doesn't cry wolf."""
        if today_events > 0 or daily_avg <= 0 or hours_elapsed <= 0:
            return None
        expected_so_far = daily_avg * (min(hours_elapsed, 24.0) / 24.0)
        if expected_so_far < Plugin._INS_QUIET_EXPECTED:
            return None
        return {"kind": "quiet", "level": "warn", "icon": "walk",
                "title": f"{name} has gone quiet",
                "detail": f"No events today; it normally logs about "
                          f"{daily_avg:.0f} a day. It may be stuck or offline.",
                "deviceId": dev_id}

    @staticmethod
    def _insight_room_temp(room, temp_now, usual, samples):
        """A room materially off its own same-hour-of-day fortnight norm."""
        if temp_now is None or usual is None or samples < Plugin._INS_TEMP_MIN_SAMPLES:
            return None
        delta = temp_now - usual
        if abs(delta) < Plugin._INS_TEMP_NOTE_DELTA:
            return None
        level = "warn" if abs(delta) >= Plugin._INS_TEMP_WARN_DELTA else "note"
        word = "warmer" if delta > 0 else "colder"
        return {"kind": "temp", "level": level, "icon": "thermo",
                "title": f"{room} is {word} than usual",
                "detail": f"{temp_now:.1f}°C now against a usual "
                          f"{usual:.1f}°C at this time of day "
                          f"({abs(delta):.1f}°C {word}).",
                "room": room}

    @staticmethod
    def _insight_on_too_long(name, dev_id, on_min_today, daily_avg_min):
        """A device that is ON and has already clocked far more ON-time today
        than its daily norm. Absolute + ratio guard so a usually-off device
        needs a real stretch, not 10 minutes vs 2."""
        extra = on_min_today - daily_avg_min
        if extra < Plugin._INS_ON_MIN_EXTRA:
            return None
        if daily_avg_min > 0 and on_min_today < daily_avg_min * Plugin._INS_ON_RATIO:
            return None
        level = "warn" if (extra >= 180 and
                           (daily_avg_min <= 0 or on_min_today >= daily_avg_min * 3)) else "note"
        hrs = on_min_today / 60.0
        avg_h = daily_avg_min / 60.0
        return {"kind": "onlong", "level": level, "icon": "bulb",
                "title": f"{name} has been on longer than usual",
                "detail": f"On for {hrs:.1f}h so far today; "
                          f"its daily norm is {avg_h:.1f}h.",
                "deviceId": dev_id}

    @staticmethod
    def _active_minutes_per_day(initial_on, rows, days, now_min=None):
        """Total ON-minutes per fixed 1440-min day across a multi-day window.
        `rows` = [(minute_offset_from_window_start, value), ...] sorted by time;
        `initial_on` = carry-in state at the window start; `now_min` = the
        current moment as a minute offset — a still-open trailing span closes
        THERE, not at the window end, because the window's last day runs to
        tomorrow midnight and closing at the end credited a device that is ON
        NOW with hours that have not happened yet. Pure — testable without a
        database. (Fixed-length days means a DST boundary is off by an hour
        that day — fine for a norm comparison.)"""
        total = days * 1440.0
        spans = []
        open_at = 0.0 if initial_on else None
        for mn, v in rows:
            b = Plugin._as_bool01(v)
            mn = max(0.0, min(total, mn))
            if b and open_at is None:
                open_at = mn
            elif not b and open_at is not None:
                if mn > open_at:
                    spans.append((open_at, mn))
                open_at = None
        if open_at is not None:
            end = total if now_min is None else max(0.0, min(total, now_min))
            if end > open_at:
                spans.append((open_at, end))
        per_day = [0.0] * days
        for s, e in spans:
            first = int(s // 1440)
            last = min(days - 1, int((e - 0.001) // 1440))
            for d in range(first, last + 1):
                lo, hi = d * 1440.0, (d + 1) * 1440.0
                per_day[d] += max(0.0, min(e, hi) - max(s, lo))
        return per_day

    def _pk_window(self, hist, conn, table, start_utc, end_utc=None):
        """Rowid bounds for a ts window, so a query can be PK-RANGED rather
        than ts-scanned. Returns (lo, hi); either may be None meaning
        "unbounded that end".

        This is not an optimisation, it is the difference between a query that
        holds a read lock for milliseconds and one that holds it for the whole
        table. `indigo_history.sqlite` has NO index on ts and runs
        journal_mode=delete, so a ts-filtered query full-scans AND blocks the
        SQL Logger's writes for the duration — that is exactly what wedged
        IWS and MCP for ~3 minutes on 15-Jul-2026. `_rowid_for_ts` was written
        then to fix it, but only Home Insights was ever moved onto it; Graphs
        and Timeline kept scanning, which is the wedge still being seen.

        Both backends (v2.95.1). This used to exempt Postgres on the belief
        that the SQL Logger indexes ts there — it does not; its Postgres DDL
        is `ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP` with no index, so every
        ts-filtered query was a sequential scan inside a 10 s-capped psql
        subprocess on the plugin's one dispatch thread. The probes here are
        PK seeks, cheap on either engine. The ONE difference is the ts
        convention: `ts` is UTC on SQLite and session-LOCAL on Postgres, so
        _rowid_for_ts asks the connection to translate the bound (ts_key).
        """
        try:
            lo = self._rowid_for_ts(conn, table, start_utc)
            hi = self._rowid_for_ts(conn, table, end_utc) if end_utc else None
            return lo, hi
        except Exception as exc:
            # A probe failure must not cost the caller its data — fall back to
            # the ts filter, which is slow but correct.
            self.logger.debug(f"[History] PK-range probe failed on {table}: {exc}")
            return None, None

    @staticmethod
    def _pk_clause(lo, hi, alias="id"):
        """SQL fragment + params for the bounds _pk_window returned."""
        parts, args = [], []
        if lo is not None:
            parts.append(f" AND {alias} >= ?")
            args.append(lo)
        if hi is not None:
            parts.append(f" AND {alias} < ?")
            args.append(hi)
        return "".join(parts), args

    @staticmethod
    def _rowid_for_ts(conn, table, ts_utc):
        """Smallest rowid whose ts >= ts_utc, found by BINARY SEARCH on the
        integer PK. The SQL Logger appends chronologically, so ts is monotone
        in id — and the history DB has NO ts index and journal_mode=delete,
        meaning any full-table scan holds a read lock that BLOCKS the logger's
        writes (live-confirmed 15-Jul-2026: the first insights build wedged
        IWS + MCP for ~3 min doing exactly that on the 1.5GB DB). Every probe
        here is a PK-ranged point query, so locks stay microscopic.
        Returns None for an empty table; max(id)+1 if every row is older.
        `ts_utc` is UTC; the Python-side comparisons use the connection's own
        ts convention (ts_key) so the same code binary-searches a Postgres
        table, whose ts is session-local, correctly. A bare sqlite3 connection
        (the tests pass one) has no ts_key and compares UTC to UTC."""
        ts_key = conn.ts_key(ts_utc) if hasattr(conn, "ts_key") else ts_utc
        # min() and max() are fetched SEPARATELY on purpose. SQLite rewrites a
        # lone min()/max() over an INTEGER PRIMARY KEY into a B-tree seek, but
        # asking for BOTH in one statement defeats that and it full-scans —
        # measured on the 1.5M-row table here: `min(id), max(id)` together is
        # a SCAN at 96 ms, each alone is a SEARCH at 0.01 ms. Since this
        # function exists precisely to avoid full scans, having one on its
        # first line made every caller pay the cost it was written to remove.
        lo_row = conn.execute(f'SELECT min(id) FROM "{table}"').fetchone()
        if not lo_row or lo_row[0] is None:
            return None
        hi_row = conn.execute(f'SELECT max(id) FROM "{table}"').fetchone()
        lo, hi = int(lo_row[0]), int(hi_row[0])

        def probe(i):
            r = conn.execute(
                f'SELECT id, ts FROM "{table}" WHERE id >= ? ORDER BY id LIMIT 1',
                (i,)).fetchone()
            return (int(r[0]), r[1]) if r else None

        first = probe(lo)
        if first and str(first[1]) >= ts_key:      # ISO strings compare chronologically
            return first[0]
        last = conn.execute(
            f'SELECT id, ts FROM "{table}" WHERE id <= ? ORDER BY id DESC LIMIT 1',
            (hi,)).fetchone()
        if not last or str(last[1]) < ts_key:
            return hi + 1
        # Invariant: ts at lo < ts_key <= ts at hi. Ids may have gaps — each
        # probe lands on the first real row at/after the midpoint.
        while hi - lo > 1:
            mid = (lo + hi) // 2
            p = probe(mid)
            if p is None or str(p[1]) >= ts_key:
                hi = p[0] if (p and p[0] < hi) else mid
            else:
                lo = p[0]
        return hi

    def _home_insights(self):
        """Gather the data and run every evaluator. Each section is isolated —
        one failure logs and skips, never blanks the card. Returns the full
        payload dict. ALL history reads are PK-ranged via _rowid_for_ts — see
        its docstring for why a ts-filtered scan is never acceptable here."""
        import time as _t
        hist = self._history()

        now = _t.time()
        lt = datetime.now()
        midnight = datetime(lt.year, lt.month, lt.day)
        start_epoch = int(_t.mktime(midnight.timetuple()))
        hours_elapsed = (now - start_epoch) / 3600.0

        def utc(epoch):
            return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        today_utc = utc(start_epoch)
        fortnight_utc = utc(start_epoch - 14 * 86400)
        week_epoch = start_epoch - 7 * 86400
        week_utc = utc(week_epoch)

        # Device sets from the rooms map (already classified).
        try:
            with open(os.path.join(self._public_dashboards_dir(), "rooms.json"),
                      encoding="utf-8") as _f:
                rooms = json.load(_f).get("rooms", {})
        except Exception:
            rooms = (self._build_rooms_json() or {}).get("rooms", {})

        insights = []
        checked = {"batteries": 0, "sensors": 0, "rooms": 0, "devices": 0}
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            raise ValueError(str(exc))
        try:
            def has_col(dev_id, want):
                # Artefact-filtered — see the note in _timeline_day.
                cols = hist.column_names(conn, dev_id)
                if want in cols:
                    return want
                return next((c for c in cols if c.startswith(want)), None)

            def battery_col(dev_id):
                # Exact names first, prefix last — 'battery' prefix-matched
                # 'batterylow' before 'batterylevel' was ever tried.
                cols = hist.column_names(conn, dev_id)
                return (next((c for c in ("battery", "batterylevel") if c in cols), None)
                        or next((c for c in cols if c.startswith("battery")
                                 and c not in ("batterylow",) and not c.endswith("_ui")), None))

            def readable(dev_id):
                # A disabled device's states are frozen; an errored one's are
                # stale. Neither is evidence about the house.
                try:
                    d = indigo.devices[dev_id]
                except Exception:
                    return None
                if not getattr(d, "enabled", True) or (getattr(d, "errorState", "") or "").strip():
                    return None
                return d

            # ── batteries falling fast ──────────────────────────────────
            try:
                for d in indigo.devices:
                    pct, _alarm = self._battery_pct(d)
                    if pct is None:
                        continue
                    if readable(d.id) is None:
                        continue
                    checked["batteries"] += 1
                    col = battery_col(d.id)
                    if not col:
                        continue
                    table = f"device_history_{d.id}"
                    b_week = self._rowid_for_ts(conn, table, week_utc)
                    if b_week is None:
                        continue
                    row = conn.execute(
                        f'SELECT "{col}" FROM "{table}" '
                        f'WHERE id < ? AND "{col}" IS NOT NULL AND "{col}" != "" '
                        f'ORDER BY id DESC LIMIT 1', (b_week,)).fetchone()
                    if not row:
                        continue          # < a week of history — no trend yet
                    try:
                        week_pct = float(row[0])
                    except (TypeError, ValueError):
                        continue
                    ins = self._insight_battery_trend(d.name, d.id, float(pct), week_pct)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] battery section failed: {exc}")

            # ── motion sensors gone quiet ───────────────────────────────
            try:
                motion_ids = []
                for r in rooms.values():
                    motion_ids += (r.get("motion") or [])
                for dev_id in dict.fromkeys(motion_ids):
                    if readable(dev_id) is None:
                        continue               # disabled on purpose is not 'gone quiet'
                    col = has_col(dev_id, "onoffstate")
                    if not col:
                        continue
                    table = f"device_history_{dev_id}"
                    b_fort = self._rowid_for_ts(conn, table, fortnight_utc)
                    b_today = self._rowid_for_ts(conn, table, today_utc)
                    if b_fort is None or b_today is None:
                        continue
                    checked["sensors"] += 1
                    today_n = conn.execute(
                        f'SELECT count(*) FROM "{table}" '
                        f'WHERE id >= ? AND "{col}" IS NOT NULL',
                        (b_today,)).fetchone()[0]
                    prior_n = conn.execute(
                        f'SELECT count(*) FROM "{table}" '
                        f'WHERE id >= ? AND id < ? AND "{col}" IS NOT NULL',
                        (b_fort, b_today)).fetchone()[0]
                    ins = self._insight_quiet_sensor(
                        self._device_name(dev_id), dev_id,
                        today_n, prior_n / 14.0, hours_elapsed)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] quiet-sensor section failed: {exc}")

            # ── rooms off their usual temperature ───────────────────────
            try:
                utc_hour = datetime.fromtimestamp(now, timezone.utc).strftime("%H")
                for room, cfg in rooms.items():
                    for dev_id in (cfg.get("sensors") or []):
                        d_now = readable(dev_id)
                        if d_now is None:
                            continue
                        try:
                            temp_now = float(d_now.states.get("temperature"))
                        except Exception:
                            continue
                        col = has_col(dev_id, "temperature")
                        if not col:
                            continue
                        table = f"device_history_{dev_id}"
                        b_fort = self._rowid_for_ts(conn, table, fortnight_utc)
                        b_today = self._rowid_for_ts(conn, table, today_utc)
                        if b_fort is None or b_today is None:
                            continue
                        checked["rooms"] += 1
                        usual, samples = conn.execute(
                            f'SELECT avg(CAST("{col}" AS REAL)), count(*) '
                            f'FROM "{table}" '
                            f'WHERE id >= ? AND id < ? AND {hist.hour_of()} = ? '
                            f'  AND "{col}" IS NOT NULL AND "{col}" != ""',
                            (b_fort, b_today, utc_hour)).fetchone()
                        ins = self._insight_room_temp(room, temp_now, usual, samples or 0)
                        if ins:
                            insights.append(ins)
                        break     # one representative sensor per room
            except Exception as exc:
                self.logger.warning(f"[Insights] room-temp section failed: {exc}")

            # ── devices on longer than usual (only those ON now) ────────
            try:
                light_ids = []
                for r in rooms.values():
                    light_ids += (r.get("lights") or []) + (r.get("extras") or [])
                for dev_id in dict.fromkeys(light_ids):
                    d_now = readable(dev_id)
                    if d_now is None:
                        continue               # a lamp disabled while on is not 'on too long'
                    try:
                        if not bool(d_now.onState):
                            continue
                    except Exception:
                        continue
                    col = has_col(dev_id, "onoffstate")
                    if not col:
                        continue
                    table = f"device_history_{dev_id}"
                    b_week = self._rowid_for_ts(conn, table, week_utc)
                    if b_week is None:
                        continue
                    checked["devices"] += 1
                    carry = conn.execute(
                        f'SELECT "{col}" FROM "{table}" '
                        f'WHERE id < ? AND "{col}" IS NOT NULL '
                        f'ORDER BY id DESC LIMIT 1', (b_week,)).fetchone()
                    rows = conn.execute(
                        f'SELECT ({hist.epoch()} - {week_epoch}) / 60.0, '
                        f'       "{col}" FROM "{table}" '
                        f'WHERE id >= ? AND "{col}" IS NOT NULL '
                        f'ORDER BY id ASC', (b_week,)).fetchall()
                    per_day = self._active_minutes_per_day(
                        self._as_bool01(carry[0]) if carry else 0, rows, 8,
                        now_min=(now - week_epoch) / 60.0)
                    # Day 8 is today (partial); days 1-7 are the norm.
                    ins = self._insight_on_too_long(
                        self._device_name(dev_id), dev_id,
                        per_day[7], sum(per_day[:7]) / 7.0)
                    if ins:
                        insights.append(ins)
            except Exception as exc:
                self.logger.warning(f"[Insights] on-too-long section failed: {exc}")
        finally:
            conn.close()

        insights.sort(key=lambda i: (0 if i["level"] == "warn" else 1, i["title"]))
        return {"ok": True, "generated": now, "insights": insights[:8],
                "checked": checked}

    def _insights_build_bg(self):
        """Background build on a daemon thread — a slow build must NEVER hold
        an IWS worker (the first synchronous build wedged IWS for ~3 min)."""
        try:
            out = self._home_insights()
            self._insights_cache = (time.time() + 900, out)
        except Exception as exc:
            self.logger.warning(f"[Insights] background build failed: {exc}")
            # Negative-cache the failure. Without it a SQL-Logger-less install
            # spawned a fresh failing build thread (and a warning line) every
            # 20 s for ever — the page retries fast while it sees "building".
            self._insights_cache = (time.time() + 300,
                                    {"ok": False, "insights": [], "checked": {},
                                     "error": f"insights unavailable: {exc}"})

    def handleHomeInsights(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/homeInsights/
        Bearer-authed by IWS. Stale-while-revalidate: always answers instantly
        from the cache (15-min TTL); a stale/missing cache kicks ONE background
        rebuild and, until the first build lands, replies {building: true} so
        the page just tries again on its next poll."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        cache = getattr(self, "_insights_cache", None)
        nowm = time.time()
        if cache and cache[0] > nowm:
            return self._evo_reply(cache[1])
        th = getattr(self, "_insights_thread", None)
        if not (th and th.is_alive()):
            th = threading.Thread(target=self._insights_build_bg,
                                  name="insights-build", daemon=True)
            self._insights_thread = th
            th.start()
        if cache:
            return self._evo_reply(cache[1])      # stale beats blocking
        return self._evo_reply({"ok": True, "building": True,
                                "insights": [], "checked": {}})

    # --------------------------------------------------------
    # Mains metering (v3.7.0) — the instrument page.
    #
    # This house measures its 240 V loads with four different families of
    # meter and they DISAGREE. Paired ten-minute means over September 2026,
    # each against the Sigenergy inverter's grid voltage:
    #
    #     Athom (ESPHome) #1   -1.70 V   (-0.68 %)
    #     Athom (ESPHome) #2   -0.93 V   (-0.37 %)
    #     Shelly Plus Plug     +1.96 V   (+0.79 %)
    #
    # a spread of about 3.7 V, or 1.5 %. None of them is calibrated, and the
    # Shelly exposes no trim (97 RPC methods, the only calibration-shaped one
    # is Shelly.FactoryReset). So this page does NOT present a single truth:
    # it shows each meter's measured offset against a stated reference and
    # lets the reader see the disagreement. Reading 252.6 V and acting on it
    # is exactly how a wrong figure nearly reached the DNO on 08-09-2026.
    # --------------------------------------------------------

    # A reading older than this is a LAST KNOWN VALUE, not a measurement.
    # 15 min is comfortably longer than every polling interval in the house
    # (the Shellys land ~35 s apart) and short enough to catch a plug that
    # has gone off the network.
    MAINS_STALE_SECONDS = 900
    # Offsets move with the hardware, not the hour — a long TTL keeps the
    # history sweep rare. Rebuilt in the background, never on a request.
    MAINS_OFFSET_TTL_SECONDS = 6 * 3600
    MAINS_OFFSET_DAYS = 7
    # Below this the pairing is too thin to quote an offset from.
    MAINS_OFFSET_MIN_PAIRS = 50

    @staticmethod
    def _mains_power_factor(watts, volts, amps, reported=None):
        """Power factor, or (None, reason) when it cannot honestly be known.

        NEVER used to derive watts. These meters report REAL power and RMS
        current from separate channels and the gap between them is genuine
        power factor: the Samsung TV measures 253.5 V x 0.218 A = 55.3 VA
        against 34.6 W, i.e. PF 0.62, steady across every sample. Computing
        watts as volts x amps would overstate that television by 60 %.
        """
        if reported is not None:
            try:
                pf = float(reported)
            except (TypeError, ValueError):
                pf = None
            if pf is not None and 0.0 < pf <= 1.05:
                return (round(min(pf, 1.0), 3), "reported")
        try:
            w, v, a = float(watts), float(volts), float(amps)
        except (TypeError, ValueError):
            return (None, "no reading")
        va = v * a
        # A load drawing almost nothing gives a meaningless ratio: at 0.02 A
        # the current channel's own error is most of the number.
        if va <= 5.0 or w <= 0.5:
            return (None, "load too small to judge")
        pf = w / va
        if pf > 1.05:
            # Above unity is impossible; it means the two channels disagree by
            # more than their error budget. Say so rather than printing it.
            return (None, "channels disagree")
        return (round(min(pf, 1.0), 3), "derived")

    @staticmethod
    def _mains_liveness(age_seconds, owner_running, continuous=True,
                        error_state="", online=None, stale_after=None):
        """('live'|'stale'|'dead', reason). A value is not a measurement.

        The Kitchen Extractor reported 291.0 V on 08-09-2026 — impossible, and
        frozen, because its plugin has not been installed since July. A page
        that shows a number without its age would have presented that as a
        dangerous over-voltage. A stopped owning plugin makes every one of its
        devices' readings historical whatever the timestamp says.

        AGE ONLY MEANS SOMETHING FOR A METER THAT POLLS. A Shelly answers every
        ~35 s, so silence is a fault. A Z-Wave dimmer reports ON CHANGE, so
        silence means nothing changed — and the first live run of this page
        greyed out the Kitchen Cupboard Lights as "stale, 10 days" while they
        were drawing 75.9 W in front of everyone. `lastSuccessfulComm` is not
        health on Z-Wave; errorState is. Callers pass continuous=False for a
        report-on-change device, and its freshness is judged by errorState and
        the owning plugin's own online flag instead.
        """
        if owner_running is False:
            return ("dead", "its plugin is not running")
        if online is False:
            return ("dead", "the device is not answering")
        if error_state:
            return ("dead", str(error_state))
        if not continuous:
            # Quiet is the normal state here, and saying otherwise is worse
            # than saying nothing: it hides a real fault among false ones.
            return ("live", "")
        limit = Plugin.MAINS_STALE_SECONDS if stale_after is None else stale_after
        # The coercion IS the guard: float(None) raises, so a device that has
        # never reported lands here with everything else that is not a number.
        # An explicit `is None` check above this was dead code — a mutation
        # sweep removed it and the tests never noticed, which is the tell.
        try:
            age = float(age_seconds)
        except (TypeError, ValueError):
            return ("dead", "never reported")
        if age > limit:
            return ("stale", f"last heard {Plugin._mains_ago(age)} ago")
        return ("live", "")

    @staticmethod
    def _mains_ago(seconds):
        """A duration the way a person says it."""
        try:
            s = int(float(seconds))
        except (TypeError, ValueError):
            return "an unknown time"
        if s < 1:
            # "last heard 0 seconds ago" is not how anyone says it, and a
            # meter polling every second lands here constantly. Only zero:
            # "1 second ago" is natural, and swallowing it would take away
            # the singular branch two lines below.
            return "a moment"
        if s < 90:
            # "1 seconds ago" reached the detail page's hero. Every other
            # branch here got its singular right and this one was missed,
            # which is what a parametrised test with no n=1 case looks like.
            return f"{s} second" + ("" if s == 1 else "s")
        # Switch to hours AT the hour: "60 minutes ago" is not how anyone
        # says it, and the tests caught exactly that.
        if s < 3600:
            m = round(s / 60.0)
            return f"{m} minute" + ("" if m == 1 else "s")
        if s < 172800:
            h = round(s / 3600.0)
            return f"{h} hour" + ("" if h == 1 else "s")
        d = round(s / 86400.0)
        return f"{d} day" + ("" if d == 1 else "s")

    @staticmethod
    def _mains_offset_stats(deltas):
        """Mean/min/max of one meter's differences from the reference.

        Returns None below MAINS_OFFSET_MIN_PAIRS: a handful of samples cannot
        separate a calibration offset from a busy afternoon, and quoting one
        from six pairs is how a measurement becomes a guess.
        """
        vals = [d for d in deltas if isinstance(d, (int, float))]
        if len(vals) < Plugin.MAINS_OFFSET_MIN_PAIRS:
            return None
        vals.sort()
        n = len(vals)
        mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        return {"pairs": n,
                "mean": round(sum(vals) / n, 2),
                "median": round(mid, 2),
                "min": round(vals[0], 2),
                "max": round(vals[-1], 2)}

    @staticmethod
    def _mains_spread(offsets):
        """How far apart the fleet is, which is the number that matters.

        `offsets` is {meter: mean_volts_vs_reference}. The spread is what says
        'no reading here is better than about this much', and it is the whole
        argument for showing raw values rather than a corrected single truth.
        """
        vals = [v for v in offsets.values() if isinstance(v, (int, float))]
        if len(vals) < 2:
            return None
        return {"meters": len(vals), "low": round(min(vals), 2),
                "high": round(max(vals), 2),
                "spread": round(max(vals) - min(vals), 2)}

    @staticmethod
    def _mains_unmetered(house_watts, metered_watts):
        """What the house is drawing that no meter can see.

        Steps in this residual are the unmetered appliances announcing
        themselves — oven, kettle, shower. A NEGATIVE residual is not a
        reading, it is the instruments disagreeing by more than the load, so
        it is returned as None with a reason rather than shown as a number.
        """
        try:
            house = float(house_watts)
            metered = float(metered_watts)
        except (TypeError, ValueError):
            return (None, "no whole-house reading")
        residual = house - metered
        if residual < -50.0:
            return (None, "meters read higher than the house total")
        return (round(max(residual, 0.0), 1), "")

    # Which state each family of meter puts its readings in. Written as an
    # ordered list because the same quantity has a different name in every
    # plugin, and a device is matched on the FIRST name it actually carries.
    MAINS_STATE_NAMES = {
        "watts":  ("powerWatts", "curEnergyLevel", "power"),
        # Read ONLY on a device that already reports a mains-range voltage —
        # see _mains_live. An ESPHome power monitor with no relay puts its real
        # power in the NATIVE sensorValue and carries none of the names above.
        "watts_native": ("sensorValue",),
        "volts":  ("voltage",),
        "amps":   ("currentAmps", "current"),
        "pf":     ("powerFactor",),
        "today":  ("energyKwhToday", "energyToday"),
        "total":  ("accumEnergyTotal", "totalEnergy", "energyKwhMonth"),
    }
    # A z2m battery sensor also carries a `voltage` state — in MILLIVOLTS,
    # around 3000. Requiring a POWER state is what separates a mains meter
    # from a coin cell; this band is the second guard, and it is deliberately
    # wide because the point of the page is to show readings, not hide them.
    MAINS_VOLTS_SANE = (150.0, 300.0)
    # UK statutory is 230 V +10 %/-6 %, i.e. 216.2 to 253.0. Outside this
    # wider band a reading is not a supply problem, it is a broken instrument:
    # the Kitchen Extractor sat at 291.0 V for weeks with its plugin gone.
    MAINS_VOLTS_PLAUSIBLE = (200.0, 270.0)

    @staticmethod
    def _mains_pick(states, names):
        """First of `names` the device actually carries, as a float, else None."""
        for n in names:
            if n in states:
                try:
                    v = float(states[n])
                except (TypeError, ValueError):
                    continue
                return v
        return None

    # A device's own configuration goes to the browser on the detail page, and
    # at least one family keeps a real credential in it — an ESPHome node
    # carries `encryptionKey`. Measured, not guessed. The endpoint is
    # Bearer-authed, but the page it feeds is served from /public, which is
    # anonymous, so nothing that could ever be a secret leaves this process.
    MAINS_SECRET_HINTS = ("password", "passwd", "secret", "token", "credential",
                          "cookie", "authorization", "apikey", "api_key",
                          "privatekey", "private_key")

    @staticmethod
    def _mains_is_secret(key):
        """True for a props key whose VALUE must never reach the browser.

        `endswith("key")` rather than `"key" in ...` on purpose: it catches
        encryptionKey, apiKey and privateKey while leaving the ESPHome
        `entityKeyMap` and the Z-Wave `zwEndpointClassMap` alone, which are
        routing tables and are exactly the sort of detail this page is for.
        """
        k = str(key).lower()
        return k.endswith("key") or any(h in k for h in Plugin.MAINS_SECRET_HINTS)

    @staticmethod
    def _mains_jsonable(value):
        """`value` if json can carry it, else its string form.

        Indigo hands plugin props back as its own `indigo.Dict` and
        `indigo.List` types, and `json.dumps` refuses both with "Object of
        type Dict is not JSON serializable" — a 500 from the whole endpoint
        because of one prop. A Z-Wave dimmer carries eight of them
        (zwClassCmdMap, zwAssociationsMap, zwEndpointClassMap and the rest),
        so every Z-Wave meter's detail page failed while all three other
        families were fine. Ask json rather than listing the types: anything
        it cannot take is shown as text, which is all a display table needs.
        """
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _mains_redact(props):
        """A device's props with every credential replaced, order preserved.

        A redacted key is KEPT and marked rather than dropped: "this device
        holds an encryption key and you are not being shown it" is useful,
        and silently omitting the row would read as the device not having one.
        """
        out = {}
        for k in sorted(props or {}, key=lambda x: str(x).lower()):
            out[str(k)] = ("(hidden)" if Plugin._mains_is_secret(k)
                           else Plugin._mains_jsonable(props[k]))
        return out

    @staticmethod
    def _mains_source(states, names):
        """WHICH of `names` this device actually answers with, or None.

        The detail page charts a meter's history, and every family keeps its
        power somewhere different — powerWatts on a Shelly, curEnergyLevel on
        Z-Wave, power on a z2m relay, the native sensorValue on a relay-less
        Athom. Naming the column is what lets one chart serve all four without
        the page holding a family list of its own.
        """
        for n in names:
            if n in states:
                try:
                    float(states[n])
                except (TypeError, ValueError):
                    continue
                return n
        return None

    @staticmethod
    def _mains_watts(states, volts):
        """This device's real power, or None if it is not a mains meter.

        Lifted out of _mains_live so a test can drive it. Left inline it was
        reachable only by a structural assertion, and it was wrong: both Athom
        freezer plugs were MISSING from the census while appearing in the trust
        panel, which is built from history. The page named seventeen meters and
        listed fifteen, and the voltage map's visible spread read 1.8 V against
        a measured 3.7 V, because the two absentees were the lowest readers in
        the fleet.

        They are relay-less ESPHome power monitors: the real power lands in the
        NATIVE `sensorValue` and none of the usual names exists on them.
        `sensorValue` is generic, so it is read as watts ONLY where the device
        also reports a mains-range voltage — a lux or temperature sensor does
        not. Measured estate-wide 08-09-2026: 17 devices carry sensorValue
        (6 lux, 5 degC, 4 with no unit, 2 watts) and only the two Athoms pass
        the voltage gate.

        NEVER V x A. On the Samsung television that reads 55 VA against a real
        34.6 W, and a page that overstates a load by 60% is worse than one that
        leaves it out.
        """
        watts = Plugin._mains_pick(states, Plugin.MAINS_STATE_NAMES["watts"])
        if watts is None and volts is not None:
            watts = Plugin._mains_pick(states, Plugin.MAINS_STATE_NAMES["watts_native"])
        return watts

    # Every family says "I am reachable" in its own words, and one of them says
    # it in a STRING. Measured across all 35 meters here on 08-09-2026:
    #   ShellyDirect       deviceOnline   bool
    #   ESPHomeBridge      connected      bool  (+ status Online/Disconnected)
    #   TasmotaBridge      availability   "Offline"
    #   Zigbee2MQTTBridge  availability   "online"
    #   Indigo Z-Wave      nothing at all — and quiet is normal there anyway
    MAINS_ONLINE_STATES = ("deviceOnline", "connected", "availability",
                           "online", "reachable")
    _MAINS_ONLINE_WORDS = {"online": True, "true": True, "on": True,
                           "connected": True, "available": True, "yes": True, "1": True,
                           "offline": False, "false": False, "off": False,
                           "disconnected": False, "unavailable": False,
                           "no": False, "0": False}

    @staticmethod
    def _mains_online(states):
        """True / False / None — does the device itself say it is reachable?

        Only ShellyDirect's `deviceOnline` was read before, so an ESPHome plug
        that dropped off the wi-fi kept its last reading and the census counted
        it. Live case 08-09-2026: an Athom freezer monitor went `connected =
        False` at 21:06 and the page went on reporting **793.79 W** for it —
        so the metered total was 794 W high and the unmetered residual short by
        the same, which is a far larger error than the 76 W the switched-off
        rule had just removed.

        A STRING IS NEVER COERCED. `bool("Offline")` is True, and "Offline" is
        precisely the value the check exists to catch. An unrecognised word
        returns None rather than a guess: not knowing is not the same as being
        well, and the liveness rule treats the two differently.
        """
        for name in Plugin.MAINS_ONLINE_STATES:
            if name not in states:
                continue
            v = states[name]
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            return Plugin._MAINS_ONLINE_WORDS.get(str(v).strip().lower())
        return None

    @staticmethod
    def _mains_reading_is_stale_off(watts, volts, states):
        """True when a power figure is a leftover from when the load was on.

        A meter that reports ON CHANGE may never send the zero. Read from the
        Kitchen Cupboard Lights' own history (Fibaro FGD212, 08-09-2026):
        switched ON at 09:30:47, reported 75.9 W at 09:30:53, switched OFF at
        09:30:57 — and said nothing further. Ten days on, the census was still
        counting 75.9 W for a light that was off, so the metered total was 76 W
        high and the unmetered residual, which is house minus meters, was short
        by exactly the same amount on the page whose whole point is honest
        measurement.

        Restricted to meters that do NOT poll, using the same discriminator as
        the liveness rule. A Shelly re-reads every ~35 s, so when it reports
        off and 0.4 W that 0.4 W was measured moments ago and is real; only a
        silent device can be frozen.

        Two devices estate-wide at the time of writing: this one and the Garage
        Salus Mains Plug at 0.1 W.
        """
        if volts is not None or "onOffState" not in states:
            return False
        try:
            if float(watts) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        return not states["onOffState"]

    @staticmethod
    def _mains_settled_watts(watts, volts, states):
        """(what to count, what the meter last said) for one reading.

        The correction lived inline in _mains_row, where no test could reach
        it, and a mutation that threw the old figure away instead of recording
        it survived the sweep. Keeping it is the difference between a tile
        saying "off" and a tile that has silently lost 75.9 W.
        """
        if Plugin._mains_reading_is_stale_off(watts, volts, states):
            return 0.0, round(float(watts), 1)
        return watts, None

    def _mains_owner_running(self, pid, cache):
        """Is the plugin that owns this device actually running?

        NOT installed counts as dead, and that is a deliberate departure from
        the fail-open rule used where a script HARDCODES a plugin id. This id
        is read off a live device, so it cannot be a typo: an uninstalled
        plugin means the device is orphaned and nothing is maintaining its
        states. That is the Kitchen Extractor, frozen at an impossible 291 V
        since TasmotaBridge was removed. Measured 08-09-2026 across every
        plugin owning a device here: all report installed=True, INCLUDING
        Indigo's own Z-Wave core, so this cannot mark a working family dead.
        """
        if pid not in cache:
            try:
                plug = indigo.server.getPlugin(pid)
                cache[pid] = bool(plug.isInstalled() and plug.isRunning())
            except Exception:
                cache[pid] = True
        return cache[pid]

    def _mains_row(self, dev, running, now):
        """One meter's live reading, or None if this device is not a mains
        meter. Lifted out of _mains_live so the per-device detail endpoint
        reads the SAME row the census does — two renderings of one meter that
        disagreed about its state would be the 17-versus-15 fault again."""
        try:
            states = dev.states
        except Exception:
            return None
        volts = self._mains_pick(states, self.MAINS_STATE_NAMES["volts"])
        if volts is not None and not (self.MAINS_VOLTS_SANE[0] <= volts
                                      <= self.MAINS_VOLTS_SANE[1]):
            volts = None                      # a battery sensor's millivolts
        watts = self._mains_watts(states, volts)
        if watts is None:
            return None                       # no power reading: not a meter
        # Believe the switch over a frozen number — see the helpers above.
        watts, last_known_watts = self._mains_settled_watts(watts, volts, states)
        amps = self._mains_pick(states, self.MAINS_STATE_NAMES["amps"])
        pf, pf_source = self._mains_power_factor(
            watts, volts, amps, self._mains_pick(states, self.MAINS_STATE_NAMES["pf"]))

        pid = getattr(dev, "pluginId", "") or ""
        owner_running = self._mains_owner_running(pid, running)
        age = None
        try:
            if dev.lastSuccessfulComm:
                age = (now - dev.lastSuccessfulComm).total_seconds()
        except Exception:
            age = None
        # A meter that reports VOLTAGE is one that polls continuously (Shelly,
        # Athom, Tasmota all do); a Z-Wave dimmer or a Zigbee relay reports
        # only when something changes, so its silence is not a fault and must
        # not be dressed up as one.
        state, why = self._mains_liveness(
            age, owner_running, continuous=(volts is not None),
            error_state=(getattr(dev, "errorState", "") or ""),
            online=self._mains_online(states))

        implausible = (volts is not None
                       and not (self.MAINS_VOLTS_PLAUSIBLE[0] <= volts
                                <= self.MAINS_VOLTS_PLAUSIBLE[1]))
        return {
            "id": dev.id, "name": dev.name, "plugin": pid,
            "type": getattr(dev, "deviceTypeId", ""),
            "enabled": bool(getattr(dev, "enabled", True)),
            "watts": round(watts, 1),
            "volts": None if volts is None else round(volts, 1),
            "amps": None if amps is None else round(amps, 3),
            "pf": pf, "pfSource": pf_source,
            "todayKwh": self._mains_pick(states, self.MAINS_STATE_NAMES["today"]),
            "totalKwh": self._mains_pick(states, self.MAINS_STATE_NAMES["total"]),
            "state": state, "why": why,
            "ageSeconds": None if age is None else int(age),
            "ago": self._mains_ago(age) if age is not None else None,
            "voltsImplausible": implausible,
            "lastKnownWatts": last_known_watts,
            "onState": (None if "onOffState" not in states
                        else bool(states["onOffState"])),
            "sources": {
                "watts": (self._mains_source(states, self.MAINS_STATE_NAMES["watts"])
                          or (self._mains_source(states, self.MAINS_STATE_NAMES["watts_native"])
                              if volts is not None else None)),
                "volts": self._mains_source(states, self.MAINS_STATE_NAMES["volts"]),
                "amps":  self._mains_source(states, self.MAINS_STATE_NAMES["amps"]),
                "pf":    self._mains_source(states, self.MAINS_STATE_NAMES["pf"]),
                # The detail page LABELS the energy rows from these. The
                # "total" list falls back to energyKwhMonth, which is a month
                # and not a lifetime, so a fixed caption called a Shelly's
                # 0.10 kWh month its lifetime total.
                "today": self._mains_source(states, self.MAINS_STATE_NAMES["today"]),
                "total": self._mains_source(states, self.MAINS_STATE_NAMES["total"]),
            },
        }

    def _mains_live(self):
        """Every device that measures a 240 V load, read from live state.

        Cheap by construction — no history, no network — so it can answer a
        request directly. The expensive half (calibration offsets) is built on
        a background thread and merged in by the handler.
        """
        now = datetime.now()
        running = {}
        rows, metered_w = [], 0.0
        for dev in indigo.devices:
            row = self._mains_row(dev, running, now)
            if row is None:
                continue
            if row["state"] == "live":
                metered_w += max(row["watts"], 0.0)
            rows.append(row)
        rows.sort(key=lambda r: (-r["watts"], r["name"]))
        return rows, round(metered_w, 1)

    def _mains_reference(self):
        """The Sigenergy inverter — house power and the voltage every meter is
        compared against. It is not calibrated either; it is the best-specified
        instrument here (it must measure accurately to stay grid-connected) and
        it sits in the middle of the fleet, which is where a median would put
        it. The page says so rather than implying it is truth."""
        for dev in indigo.devices:
            if getattr(dev, "deviceTypeId", "") == "sigenergyInverter":
                s = dev.states
                return {"id": dev.id, "name": dev.name,
                        "houseWatts": self._mains_pick(s, ("homePowerWatts",)),
                        "volts": self._mains_pick(s, ("gridVoltageV",))}
        return None

    def _mains_bucketed_volts(self, conn, hist, dev_id, column, since_utc):
        """{10-minute bucket: mean volts} for one meter, PK-RANGED.

        Never ts-filtered. indigo_history.sqlite has no index on ts and runs
        journal_mode=delete, so a scan holds a read lock that blocks the SQL
        Logger's writes — that is what wedged IWS for three minutes in July.
        """
        table = f"device_history_{dev_id}"
        lo = self._rowid_for_ts(conn, table, since_utc)
        if lo is None:
            return {}
        out = {}
        for ts, v in conn.execute(
                f"SELECT ts, {column} FROM {table} "
                f"WHERE id >= ? AND {column} IS NOT NULL", (lo,)):
            if v is None:
                continue
            key = str(ts)[:15]          # 'YYYY-MM-DD HH:M' — a 10-minute bucket
            acc = out.setdefault(key, [0.0, 0])
            acc[0] += float(v)
            acc[1] += 1
        return {k: a[0] / a[1] for k, a in out.items() if a[1]}

    def _mains_offsets(self):
        """Each voltage-capable meter's measured offset against the reference.

        This is the page's whole point. The meters disagree by about 1.5 %, no
        two agree, and nothing here is calibrated — so the honest presentation
        is every meter's own offset plus the fleet spread, not one corrected
        number wearing an authority none of them has.
        """
        ref = self._mains_reference()
        if not ref:
            return {"ok": False, "error": "no inverter to compare against"}
        hist = self._history()
        try:
            conn = hist.connect()
        except _history_db.HistoryUnavailable as exc:
            return {"ok": False, "error": f"history unavailable: {exc}"}
        try:
            since = (datetime.now(timezone.utc).replace(tzinfo=None)
                     - timedelta(days=self.MAINS_OFFSET_DAYS)
                     ).strftime("%Y-%m-%d %H:%M:%S")
            try:
                ref_cols = hist.column_names(conn, ref["id"])
            except Exception:
                ref_cols = []
            ref_col = "gridvoltagev" if "gridvoltagev" in ref_cols else None
            if not ref_col:
                return {"ok": False, "error": "the inverter logs no grid voltage"}
            ref_series = self._mains_bucketed_volts(conn, hist, ref["id"], ref_col, since)
            if not ref_series:
                return {"ok": False, "error": "no reference history in the window"}

            offsets, meters = {}, {}
            for dev in indigo.devices:
                if dev.id == ref["id"]:
                    continue
                try:
                    cols = hist.column_names(conn, dev.id)
                except Exception:
                    continue
                if "voltage" not in cols:
                    continue
                series = self._mains_bucketed_volts(conn, hist, dev.id, "voltage", since)
                if not series:
                    continue
                deltas = [series[k] - ref_series[k] for k in series if k in ref_series
                          # A battery sensor's millivolts share the column name.
                          and self.MAINS_VOLTS_SANE[0] <= series[k] <= self.MAINS_VOLTS_SANE[1]]
                stats = self._mains_offset_stats(deltas)
                if stats is None:
                    continue
                stats["percent"] = round(100.0 * stats["mean"]
                                         / (sum(ref_series.values()) / len(ref_series)), 3)
                meters[str(dev.id)] = dict(stats, name=dev.name)
                offsets[str(dev.id)] = stats["mean"]
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {"ok": True, "generated": time.time(), "days": self.MAINS_OFFSET_DAYS,
                "reference": {"id": ref["id"], "name": ref["name"]},
                "meters": meters, "spread": self._mains_spread(offsets)}

    def _mains_offsets_cached(self):
        """The offsets cache, starting the background build when it is cold.

        BOTH the census and the per-meter page need this, and a page opened
        straight onto a meter — a bookmark, or a tile tapped after a restart —
        must not sit for ever on an empty answer because only the census ever
        kicked the build off. A missing cache is reported as `building`, never
        as "this meter has no offset": those are different facts and rendering
        them the same way is how an absence starts reading as a measurement.
        """
        cache = getattr(self, "_mains_cache", None)
        if cache and cache[0] > time.time():
            return cache[1]
        th = getattr(self, "_mains_thread", None)
        if not (th and th.is_alive()):
            th = threading.Thread(target=self._mains_offsets_bg,
                                  name="mains-offsets", daemon=True)
            self._mains_thread = th
            th.start()
        # An EXPIRED cache still beats nothing while the rebuild runs: a
        # calibration offset measured six hours ago has not moved since.
        return (cache[1] if cache else {"ok": True, "building": True,
                                        "meters": {}, "spread": None})

    def _mains_offsets_bg(self):
        """Background build — a multi-table history sweep must NEVER hold an
        IWS worker. Failures are negative-cached so a history-less install does
        not spawn a fresh failing thread on every poll."""
        try:
            self._mains_cache = (time.time() + self.MAINS_OFFSET_TTL_SECONDS,
                                 self._mains_offsets())
        except Exception as exc:
            self.logger.warning(f"[Mains] offset build failed: {exc}")
            self._mains_cache = (time.time() + 600,
                                 {"ok": False, "meters": {}, "spread": None,
                                  "error": f"offsets unavailable: {exc}"})

    def handleMainsMeters(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/mainsMeters/
        Bearer-authed by IWS. Live readings are computed per request (cheap —
        state reads only); the calibration offsets come from a cache rebuilt on
        a background thread, so the page answers instantly from the first load
        and fills the trust panel in when the sweep lands."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        try:
            rows, metered = self._mains_live()
            ref = self._mains_reference()
            unmetered, unmetered_why = self._mains_unmetered(
                (ref or {}).get("houseWatts"), metered)
            offsets = self._mains_offsets_cached()
            return self._evo_reply({
                "ok": True, "generated": time.time(),
                "meters": rows, "meteredWatts": metered,
                "reference": ref,
                "unmeteredWatts": unmetered, "unmeteredWhy": unmetered_why,
                "offsets": offsets,
                "staleAfterSeconds": self.MAINS_STALE_SECONDS,
            })
        except Exception as exc:
            self.logger.error(f"[Mains] query failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    # ── one meter, everything known about it (v3.8.0) ────────────────────
    # CliveS could not tell his two Athom plugs apart — both carry their
    # ESPHome discovery name (athom-without-relay-plug-574f8d / -574eeb) and
    # nothing on the census said which was which. The page that answers that
    # question has to show the things that identify a physical plug: its
    # address, its network name, how long it has been up, its lifetime energy,
    # and the shape of its load over the last day.

    @staticmethod
    def _mains_states(states):
        """Every reading a device publishes, with its own display string.

        Indigo keeps the formatted value in a sibling `<name>.ui` state, so the
        units come free and there is no unit table to keep in step with four
        families of meter. The `.ui` rows themselves are folded in rather than
        listed, or every reading appears twice.
        """
        out = []
        for name in sorted(states, key=lambda x: str(x).lower()):
            if str(name).endswith(".ui"):
                continue
            value = states[name]
            display = states.get(f"{name}.ui")
            out.append({"name": str(name),
                        "value": Plugin._mains_jsonable(value),
                        "display": None if display is None else str(display)})
        return out

    def _mains_detail(self, dev_id):
        """Everything this process knows about one meter."""
        try:
            dev_id = int(dev_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "a device id is required"}
        if dev_id not in indigo.devices:
            return {"ok": False, "error": f"there is no device {dev_id}"}
        dev = indigo.devices[dev_id]
        row = self._mains_row(dev, {}, datetime.now())
        if row is None:
            # Deliberately not a 404. The device is real and the page can still
            # say what it is; refusing outright would leave the reader unable
            # to tell a wrong link from a device that stopped reporting power.
            return {"ok": True, "isMeter": False, "meter": None,
                    "identity": self._mains_identity(dev),
                    "states": self._mains_states(dev.states),
                    "props": self._mains_redact(dict(dev.globalProps.get(dev.pluginId, {}))),
                    "offset": None, "reference": None,
                    "why": "this device reports no power, so it is not a mains meter"}

        offsets = self._mains_offsets_cached() or {}
        offset = (offsets.get("meters") or {}).get(str(dev_id))
        ref = self._mains_reference()
        # No `fleet` here any more: the voltage map it fed was removed from this
        # page at CliveS's request, and building it cost a whole extra
        # _mains_live() sweep of 227 devices on every detail request.
        return {"ok": True, "isMeter": True, "generated": time.time(),
                "meter": row,
                "identity": self._mains_identity(dev),
                # globalProps, not pluginProps: read from THIS plugin's host a
                # foreign device's pluginProps comes back empty, which reads
                # exactly like a device with no configuration at all.
                "props": self._mains_redact(dict(dev.globalProps.get(dev.pluginId, {}))),
                "states": self._mains_states(dev.states),
                "offset": offset,
                "offsetDays": offsets.get("days"),
                "offsetBuilding": bool(offsets.get("building")),
                "spread": offsets.get("spread"),
                "reference": ref,
                "staleAfterSeconds": self.MAINS_STALE_SECONDS}

    def _mains_identity(self, dev):
        """The things that tell you WHICH physical plug this is."""
        pid = getattr(dev, "pluginId", "") or ""
        plug_name, plug_ver, running = pid, None, None
        try:
            plug = indigo.server.getPlugin(pid)
            plug_name = plug.pluginDisplayName or pid
            plug_ver = plug.pluginVersion
            running = bool(plug.isInstalled() and plug.isRunning())
        except Exception:
            pass
        folder = ""
        try:
            if dev.folderId:
                folder = indigo.devices.folders[dev.folderId].name
        except Exception:
            folder = ""
        def _iso(v):
            try:
                return v.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        return {
            "id": dev.id, "name": dev.name,
            "description": getattr(dev, "description", "") or "",
            "model": getattr(dev, "model", "") or "",
            "subModel": getattr(dev, "subModel", "") or "",
            "protocol": str(getattr(dev, "protocol", "") or ""),
            "deviceTypeId": getattr(dev, "deviceTypeId", ""),
            "address": getattr(dev, "address", "") or "",
            "folder": folder,
            "enabled": bool(getattr(dev, "enabled", True)),
            "configured": bool(getattr(dev, "configured", True)),
            "errorState": str(getattr(dev, "errorState", "") or ""),
            "lastSuccessfulComm": _iso(getattr(dev, "lastSuccessfulComm", None)),
            "lastChanged": _iso(getattr(dev, "lastChanged", None)),
            "pluginId": pid, "pluginName": plug_name,
            "pluginVersion": plug_ver, "pluginRunning": running,
        }

    def handleMainsMeter(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/mainsMeter/
        Body: {"id": <deviceId>}. Bearer-authed by IWS. Everything known about
        ONE meter — live reading, identity, offset, states and configuration.
        Reads live state only, so it is cheap enough to answer per request; the
        page fetches its own history through the existing historyQuery."""
        _refused = self._refuse_reflector(action)
        if _refused:
            return _refused
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)
        try:
            out = self._mains_detail(payload.get("id"))
            return self._evo_reply(out, status=200 if out.get("ok") else 404)
        except Exception as exc:
            self.logger.error(f"[Mains] detail query failed: {exc}")
            return self._evo_reply({"ok": False, "error": str(exc)}, status=500)

    def handleVerifyPin(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/verifyPin/
        Body: {"pin": "<entered>"}. Server-side comparison so the PIN value
        never reaches the browser. NOTE: this is a speed bump for paired
        devices (kids on the iPad), NOT a security boundary — a paired
        browser already holds the full API key."""
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
            pin     = str(payload.get("pin") or "")
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)
        if not self.control_pin:
            return self._evo_reply({"ok": True, "valid": True, "note": "no PIN configured"})
        import hmac
        # Brute-force friction WITHOUT time.sleep — every handler and callback
        # shares ONE dispatch thread, so sleeping here froze the whole plugin
        # for half a second per wrong guess: a self-DoS anyone with the API
        # key could drive. A timestamp lockout gives the same pacing for free.
        nowp = time.time()
        if nowp < getattr(self, "_pin_locked_until", 0):
            return self._evo_reply({"ok": True, "valid": False,
                                    "note": "try again in a moment"})
        # bytes, not str: compare_digest() raises TypeError on a str with any
        # non-ASCII character, and a stray "é" in the PIN box 500'd the
        # endpoint rather than answering "no" (v2.95.1).
        valid = hmac.compare_digest(pin.encode("utf-8"),
                                    str(self.control_pin).encode("utf-8"))   # constant-time (v2.38.0)
        if not valid:
            self._pin_locked_until = nowp + 0.5
            self.logger.warning("[PIN] Incorrect control PIN entered")
        return self._evo_reply({"ok": True, "valid": valid})

    # ── applyColour (v2.94.0) ────────────────────────────────────────────
    # The colour sequence used to run in the BROWSER: turnOn, then
    # setBrightness, then setColorLevels, three separate round trips in a fixed
    # order, each in an empty `catch {}`. A phone that locked, backgrounded the
    # tab or lost signal between them left the lamp half-set — the wrong colour,
    # or full brightness with last night's film colour still on it — and nothing
    # anywhere said so. Ordered multi-step work belongs on the server, where the
    # steps cannot be interrupted by the screen going off.
    #
    # No sleeps anywhere in here on purpose. Every handler and callback in this
    # plugin shares ONE dispatch thread, so a blocking pause would freeze the
    # whole plugin — and the three IOM calls queue to the owning plugin and
    # return at once, so none is needed.
    @staticmethod
    def _colour_levels_from(payload):
        """Pull the setColorLevels keys out of a request body, validating each.

        Returns (levels, error). A bad key or an out-of-range value is an
        ERROR, never a clamp: clamping turns a caller's mistake into a light
        that quietly did something else, which is much harder to notice than a
        refusal."""
        levels = {}
        for key, (lo, hi) in _COLOUR_LEVEL_KEYS.items():
            if key not in payload or payload[key] is None or str(payload[key]).strip() == "":
                continue
            try:
                val = float(payload[key])
            except (TypeError, ValueError):
                return None, f"{key} is not a number"
            if not (lo <= val <= hi):
                return None, f"{key} must be between {lo} and {hi}"
            levels[key] = int(round(val))
        return levels, None

    def _device_command_blocked(self, dev):
        """(reason, http_status) if a command to `dev` would be SWALLOWED, else
        (None, None). Indigo does not raise for either case: a device whose
        communication is disabled ignores the action and logs 'Ignored'; a
        device whose owning plugin is stopped gets 'unable to execute action'
        in the log and nothing else. Both used to come back as ok:true."""
        if not getattr(dev, "enabled", True):
            return "device communication is disabled in Indigo — the command would be ignored", 409
        pid = getattr(dev, "pluginId", "") or ""
        if pid:
            try:
                owner = indigo.server.getPlugin(pid)
                # Fail OPEN on an unknown id: getPlugin() reads all-False for a
                # typo, and a typo must never be what refuses a command.
                if owner.isInstalled() and not owner.isRunning():
                    disp = getattr(owner, "pluginDisplayName", "") or pid
                    return f"{disp} is not running — the command would be swallowed", 503
            except Exception:
                pass
        return None, None

    def handleApplyColour(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/applyColour/

        Body, either:
            {"deviceId": N, "preset": "warm"}
            {"deviceId": N, "brightness": 0-100, "<levelKey>": v, ...}

        Runs turn-on -> brightness -> colour IN ORDER on the server and reports
        what actually happened, step by step. Each step is attempted even if an
        earlier one failed — a colour command works on a lamp that is off, it
        just is not visible yet — but a failure is RECORDED and returned, never
        swallowed the way the browser used to swallow it."""
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be an object"}, status=400)

        try:
            dev_id = int(payload.get("deviceId"))
        except (TypeError, ValueError):
            return self._evo_reply({"ok": False, "error": "deviceId must be a number"}, status=400)
        # `in` on the devices collection returns False for an unknown id rather
        # than raising, so this is a real existence check.
        if dev_id not in indigo.devices:
            return self._evo_reply({"ok": False, "error": f"no device {dev_id}"}, status=404)
        dev = indigo.devices[dev_id]
        blocked, status = self._device_command_blocked(dev)
        if blocked:
            self.logger.warning(f"[Colour] {dev.name}: refused — {blocked}")
            return self._evo_reply({"ok": False, "device": dev.name, "error": blocked},
                                   status=status)

        preset_key = str(payload.get("preset") or "").strip()
        if preset_key:
            preset = COLOUR_PRESETS.get(preset_key)
            if preset is None:
                return self._evo_reply({"ok": False, "error": f"unknown preset {preset_key!r}"},
                                       status=400)
            source = preset
        else:
            source = payload

        levels, err = self._colour_levels_from(source)
        if err:
            return self._evo_reply({"ok": False, "error": err}, status=400)

        brightness = None
        if source.get("brightness") is not None and str(source.get("brightness")).strip() != "":
            try:
                brightness = float(source["brightness"])
            except (TypeError, ValueError):
                return self._evo_reply({"ok": False, "error": "brightness is not a number"},
                                       status=400)
            if not (0 <= brightness <= 100):
                return self._evo_reply({"ok": False, "error": "brightness must be 0-100"},
                                       status=400)
            brightness = int(round(brightness))

        if not levels and brightness is None:
            return self._evo_reply({"ok": False, "error": "nothing to apply"}, status=400)

        steps = []

        def _step(name, fn):
            try:
                fn()
                steps.append({"step": name, "ok": True})
                return True
            except Exception as exc:            # noqa: BLE001 — report, never swallow
                steps.append({"step": name, "ok": False, "error": str(exc)})
                return False

        # Turn on first. A colour command lands on a lamp that is off, but it
        # is not visible until something switches it on, and the point of a
        # preset button is that the room changes.
        _step("turnOn", lambda: indigo.device.turnOn(dev.id))
        if brightness is not None:
            _step("setBrightness", lambda: indigo.dimmer.setBrightness(dev.id, value=brightness))
        if levels:
            _step("setColorLevels", lambda: indigo.dimmer.setColorLevels(dev.id, **levels))

        failed = [st for st in steps if not st["ok"]]
        if failed:
            self.logger.warning(
                f"[Colour] {dev.name}: "
                + ", ".join(f"{st['step']} failed ({st['error']})" for st in failed))
        return self._evo_reply({
            "ok": not failed,
            "device": dev.name,
            "preset": preset_key or None,
            "applied": {"brightness": brightness, "levels": levels},
            "steps": steps,
        }, status=200 if not failed else 502)

    def menuShowGuestInfo(self, valuesDict=None, typeId=None):
        """Menu: log everything needed to provision a guest (read-only)
        device — the guest token and the pairing URL."""
        base = self.api_url or "http://localhost:8176"
        log("[Guest] Guest access — read-only, LAN/Tailscale only (port 8177 "
            "is never reachable from the internet):")
        log(f"[Guest]   Pairing URL (open ON the guest device): {base}/public/dashboards/guest.html")
        # The token is a persistent credential and the event log is a 0644
        # file that gets pasted into forum posts — only its tail is shown.
        _tok = self.guest_token or ""
        log(f"[Guest]   Guest token: ends …{_tok[-4:]} (the pairing page enters it for you; "
            f"the full value is in the Settings page's Security card)")
        log("[Guest]   Guest devices cannot control anything — they hold no API key.")
        return True

    def _prune_change_ledger(self):
        """Drop ledger entries no client could still ask about — changedSince
        forces a full refetch for anything older than 600s, so an hour's grace
        is plenty. Keeps both dicts bounded."""
        cutoff = time.time() - 3600
        for ledger in (self._dev_changes, self._dev_deleted):
            for dev_id, ts in list(ledger.items()):
                # Re-check the LIVE value before popping: deviceUpdated (main
                # thread) can refresh an entry between our snapshot and the
                # pop, and blindly popping would delete a fresh change — the
                # client would then miss it until the 5-min full resync.
                if ts < cutoff and ledger.get(dev_id, cutoff) < cutoff:
                    ledger.pop(dev_id, None)

    def menuGenerateSetupLink(self, valuesDict=None, typeId=None):
        """Menu: generate a one-time setup link (+ QR) that seeds a browser
        with the API key. Single-use (burned on redeem) and TTL-limited."""
        if not self.api_key:
            log("[SetupLink] No API key available (IndigoSecrets/PluginConfig) — "
                "cannot generate a setup link", level="ERROR")
            return False

        token = _stdlib_secrets.token_urlsafe(24)
        pub   = self._public_dashboards_dir()
        try:
            with open(os.path.join(pub, f"setup-{token}.json"), "w", encoding="utf-8") as f:
                json.dump({"apiKey": self.api_key}, f)
        except Exception as exc:
            log(f"[SetupLink] Could not write setup payload: {exc}", level="ERROR")
            return False

        # Redeem URLs — LAN always, reflector too if configured. The QR encodes
        # the reflector URL when available (phones scanning a QR are usually
        # the away-from-home case), falling back to the LAN URL.
        # A loopback api_url (which the config help itself recommends) makes
        # a useless pairing link — the PHONE scanning the QR is not the
        # server. Substitute the detected LAN address in that case.
        base = (self.api_url or "").strip()
        if not base or "127.0.0.1" in base or "localhost" in base:
            base = f"http://{self.lan_ip}:8176" if getattr(self, "lan_ip", "") \
                else (base or "http://localhost:8176")
        lan_url = f"{base}/public/dashboards/setup.html#{token}"
        refl_url = ""
        try:
            refl = (indigo.server.getReflectorURL() or "").rstrip("/")
            if refl:
                refl_url = f"{refl}/public/dashboards/setup.html#{token}"
        except Exception:
            pass

        qr_note = "QR not generated (qrcode package not installed yet — restart plugin to pip-install)"
        try:
            import qrcode
            import qrcode.image.svg
            # The QR carries the LAN address (v2.96.1). It used to carry the
            # reflector address on the theory that a phone scanning a QR is
            # away from home — but a phone is paired ONCE and keeps that
            # origin for ever, so a phone paired at home fetched every camera
            # still through Indigo's servers from the sofa. The reflector
            # link is still in the log for pairing a device that is away.
            img = qrcode.make(lan_url,
                              image_factory=qrcode.image.svg.SvgPathImage)
            img.save(os.path.join(pub, f"setup-qr-{token}.svg"))
            qr_base = base
            qr_note = f"QR (open on this Mac, scan with the phone): {qr_base}/public/dashboards/setup-qr-{token}.svg"
        except Exception as exc:
            qr_note = f"QR not generated ({exc})"

        log("[SetupLink] One-time setup link created — single use, expires in "
            f"{self.SETUP_LINK_TTL_SECONDS // 60} minutes:")
        log(f"[SetupLink]   LAN:       {lan_url}")
        if refl_url:
            log(f"[SetupLink]   Reflector: {refl_url}")
        log(f"[SetupLink]   {qr_note}")
        return True

    def handleBurnSetupToken(self, action, dev=None, callerWaitingForResult=True):
        """POST /message/com.clives.indigoplugin.dashboards/burnSetupToken/
        Body: {"token": "<token>"}  (Bearer-authenticated by IWS upstream)
        Deletes the one-time setup files so a redeemed link cannot be reused."""
        body = action.props.get("request_body") or ""
        try:
            payload = json.loads(body) if body else {}
            token   = (payload.get("token") or "").strip()
        except Exception as exc:
            return self._evo_reply({"ok": False, "error": f"bad JSON: {exc}"}, status=400)
        if not isinstance(payload, dict):
            return self._evo_reply({"ok": False, "error": "body must be a JSON object"}, status=400)

        if not self._SETUP_TOKEN_RE.match(token):
            return self._evo_reply({"ok": False, "error": "bad token format"}, status=400)

        pub = self._public_dashboards_dir()
        removed = 0
        for name in (f"setup-{token}.json", f"setup-qr-{token}.svg"):
            try:
                os.remove(os.path.join(pub, name))
                removed += 1
            except FileNotFoundError:
                pass
            except Exception as exc:
                self.logger.warning(f"[SetupLink] Could not remove {name}: {exc}")
        if removed:
            self.logger.info(f"[SetupLink] Setup link redeemed and burned ({removed} file(s))")
        return self._evo_reply({"ok": True, "removed": removed})
