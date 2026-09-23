# Dashboards — contract test suite

A no-hardware test layer that pins the plugin's trickiest logic so a future
change can't silently regress it. Runs entirely outside the Indigo host.

## Run

```bash
tests/run.sh                 # the gate: pytest + every tests/*.mjs + compileall + ruff (what CI runs)
python3 -m pytest tests -q   # Python only
for f in tests/*.mjs; do node "$f"; done   # the node suites
```

## How it works

`conftest.py` mock-imports `plugin.py` with `indigo` (and optional third-party
deps) stubbed in `sys.modules`, so the plugin's helpers can be unit-tested
without a running server. Two helpers back the tests:

- `bare_plugin()` — a `Plugin` instance built via `__new__` (skips the heavy
  `__init__`); attach only what a method reads.
- `FakeDev(...)` — an attribute-bag device whose class name is spoofable
  (`DimmerDevice` / `RelayDevice` / …) for the classifier.

## Coverage

Generated from each file's `Description:` header (`ls tests/` is the truth; this table follows it).

| File | Locks |
|------|-------|
| `test_action_note_targets.py` | A DashAction.note(key, ...) is painted only on an element that |
| `test_action_watch.mjs` | Contract test for DashAction — how the dashboard's control |
| `test_alerts_settled_rows.mjs` | Node contract test for alerts.html's log-watch row renderer. |
| `test_apply_colour.py` | Contract test for Plugin.handleApplyColour — the v2.94.0 endpoint |
| `test_battery_pct.py` | Truth-table test for Plugin._battery_pct — the estate's three |
| `test_bulk_lights_open_loop.mjs` | Contract test for the Lights section's "All On / All Off" when |
| `test_camera_boot_policy.mjs` | Contract test for the camera page's BOOT POLICY and the |
| `test_camera_frame_age.mjs` | Contract test for the per-tile frame-age readout and the |
| `test_camera_stall_watchdog.mjs` | Node contract test for the cameras.html slow-link stall |
| `test_camera_still_period.mjs` | The cameras page works out a still tile's refresh period in ONE |
| `test_camera_thumbs.py` | Contract test for the grid thumbnail — the second, smaller copy |
| `test_camera_webrtc.mjs` | Contract test for the away-from-home WebRTC focused tile |
| `test_carbon_advice.py` | Decision-table test for Plugin._carbon_advice — the run-a-load |
| `test_carbon_hhmm.py` | _carbon_hhmm — a UTC forecast slot as local HH:MM, with |
| `test_change_stamp.py` | Contract tests for the v2.70.0 liveness stamp — the tiny |
| `test_changed_since.py` | The changedSince ledger policy — ONE implementation (v2.95.1) |
| `test_classify_device.py` | Truth-table contract test for Plugin._classify_device — the |
| `test_closed_prefs.py` | The credential resolution every NON-IndigoSecrets user relies |
| `test_colour_one_call.mjs` | Contract test for the browser half of the v2.94.0 colour move — |
| `test_command_guards.py` | applyColour must refuse a command Indigo would swallow |
| `test_config_js_no_secrets.py` | Pins the plugin's single most important security invariant: |
| `test_cost_rate_tiers.mjs` | Contract tests for the Cost page's Rates tiles. |
| `test_dash_message.mjs` | Contract test for DashUI.message (v3.28.0) — the one way a page |
| `test_dash_poll.mjs` | Contract test for DashUI.poll (v3.28.0): one polling loop for |
| `test_demo_fixture_is_sanitised.py` | The demo fixture (demo-data/devices.json) is a snapshot of a |
| `test_docs_site.py` | The documentation site (docs/, GitHub Pages) and the README |
| `test_door_tile.mjs` | Contract test for the hub's state-driven door favourite — |
| `test_energy_alert_bar.mjs` | Node contract test for energy.html's alert bar. Extracts the |
| `test_energy_cost.mjs` | Node contract test for energy-calc.js — the shared arithmetic |
| `test_energy_soc.mjs` | Node contract test for energy.html's handling of an UNKNOWN |
| `test_escape_helpers.mjs` | DashUI.esc escapes all five characters that matter, DashUI.ago |
| `test_event_log_quiet.py` | The Indigo event log is shared by every plugin on the server and |
| `test_fav_device_label.mjs` | Contract test for the label on a plain on/off device favourite |
| `test_fav_group_tile.mjs` | Contract test for the group favourite (v2.93.0) — ONE hub tile |
| `test_fav_room_shortcuts.mjs` | Contract test for room shortcuts in the Favourites card |
| `test_fav_spoken_when.mjs` | Contract test for spokenWhen() (v3.23.0) — a reading favourite |
| `test_fire_heater_chip.mjs` | Contract test for the hub's fire-heater chip (index.html |
| `test_fire_heater_line.mjs` | Contract test for the living room fire's tile line (room.html |
| `test_footer_stable_height.mjs` | The cameras page footer must not change height (v2.99.1). |
| `test_freshness_indicator.mjs` | Contract test for the "not updating" status line on mains.html |
| `test_getdevices.mjs` | Node contract test for dashboard.js getDevices() delta-merge — |
| `test_glance_row_layout.mjs` | The hub's glance row holds THREE cards in a TWO-column grid, so |
| `test_go2rtc_log_datestamp.py` | go2rtc stamps its log lines with the TIME only and cannot be |
| `test_go2rtc_supervise.py` | The go2rtc supervisor must keep trying after a FAILED restart. |
| `test_guest_scrub.py` | A guest-token holder must never receive plugin props. The |
| `test_history_db.py` | Contract tests for history_db.py — the SQL Logger artefact |
| `test_history_pk_range.py` | Contract test for the PK-range window helpers — the mechanism |
| `test_history_query.py` | Contract test for Plugin._history_query against a fixture SQL |
| `test_home_insights.py` | Contract tests for the Home Insights evaluators (v2.42.0) — the |
| `test_hub_attention.mjs` | The hub's "needs a look" chip (v3.35.0). Devices in error, low |
| `test_hub_lean_away.mjs` | Contract test for the hub's REGION POLICY (v2.97.0). The light |
| `test_hub_saving_session_chip.mjs` | Contract test for the Octopus Saving Session chip in the hub's |
| `test_hub_saving_session_row.mjs` | Contract test for the Octopus Saving Session row on the hub's |
| `test_hub_vpp_and_version.mjs` | Node contract test for the v2.66.0 hub changes — the VPP chip |
| `test_hub_vpp_rows.mjs` | Contract tests for the hub's VPP status and earnings rows. |
| `test_idle_guard.mjs` | Contract test for DashUI.idleGuard, DashUI.lanUrl and the |
| `test_immediate_numbers.mjs` | Numeric readings update synchronously, while graphical callbacks may animate. |
| `test_laundry_deadline.py` | Contract test for the Laundry page's deadline validation. |
| `test_laundry_replan_offpath.py` | A laundry deadline replans on the off-path pool, not on IWS's |
| `test_legacy_config_import.py` | One settings store (v3.27.0). A first start with no |
| `test_link_class.mjs` | Contract test for DashUI.linkClass / measuredClass — how the |
| `test_log_watch_alive.py` | The plugin ticks Log_Error_Watch.py hourly, so the plugin is |
| `test_mains_meters.py` | Contract tests for the Mains instrument page's pure helpers |
| `test_mcp_manifest.py` | The plugin-provided MCP tool contract (v3.12.0), checked from |
| `test_mcp_tools.py` | Behaviour of the plugin-provided MCP tools (v3.12.0): the |
| `test_no_orphan_pages.py` | Every page can be reached from another page (v3.33.0). The |
| `test_no_private_strings.py` | This repository is public. Nothing in it may carry a real |
| `test_offpath_pool.py` | No /message/ handler may do slow work on the dispatch path. One |
| `test_page_count_claims.py` | Every place the docs say how many pages the plugin ships agrees |
| `test_page_frame.py` | Every page's top bar matches the Energy page (v3.29.0): one |
| `test_parse_cameras.py` | Contract test for the module-level _parse_cameras — JSON-string vs |
| `test_pending_retry_client.mjs` | dashboard.js's _fetch must wait out a "pending" 503 rather than |
| `test_pin_redaction.py` | Security contract test for Plugin._parse_lock_code_trigger — the |
| `test_poller_auth_and_hidden.mjs` | Contract test for the hub's four side pollers — sigen, string |
| `test_presence_endpoint.py` | Contract tests for the v2.71.0 presence-data privacy fix — the |
| `test_pv_string_sanity.py` | The solarStringHours reader must reject the impossible |
| `test_reflector_block.mjs` | Contract test for "refuse the reflector" (v3.1.0). Indigo |
| `test_reflector_guard.py` | Every browser-facing handler refuses the reflector when the |
| `test_reflector_note.py` | Contract test for Plugin._note_reflector_use (v2.96.1) — a |
| `test_release_versions.py` | Keep every user-visible Dashboards version declaration in lock-step. |
| `test_repo_notes_size.py` | The repo's CLAUDE.md holds CURRENT facts only. It had grown to |
| `test_room_door_device.mjs` | Contract test for the ROOM page's state-driven door tile |
| `test_room_extras_isolation.py` | One room's roomExtras entry of the wrong shape must cost that |
| `test_rtt_estimator.mjs` | Contract test for the estimator inside DashUI.probeRtt — which |
| `test_save_config.py` | Contract test for Plugin.handleSaveDashboardsConfig — the settings |
| `test_saving_session_banner.mjs` | Contract test for the Octopus Saving Session banner on the |
| `test_script_ticker_handover.py` | v3.31.0 — while the Script Ticker plugin is RUNNING, Dashboards |
| `test_scripts_match_live.py` | The companion scripts this repo ships in scripts/ must be the |
| `test_security.py` | Regression tests for the /public credential-leak fixes — the |
| `test_settings_fav_passthrough.mjs` | Contract test for the settings editor carrying favourites it |
| `test_shared_ui_present.mjs` | Every user-facing page must load dashboards-ui.js (v2.97.0). |
| `test_shutdown_budget.py` | shutdown() must not wait on the snapshot pool. Until 2.95.1 |
| `test_sigen_available.py` | The server half of "the Sigenergy pages hide themselves when |
| `test_sigen_visibility.mjs` | The browser half of "the Sigenergy pages hide themselves when |
| `test_snapshot_conditional.mjs` | Contract test for the camera still-refresh mechanism — the |
| `test_snapshot_failure_wording.py` | A snapshot warning must say what went wrong in words a person |
| `test_solar_card_split.mjs` | Solar is its own hub card (v2.98.0). It used to be drawn inside |
| `test_solar_hours_chart.mjs` | Contract test for DashUI.solarHoursChart — the stacked hourly |
| `test_solar_string_hours.py` | Contract tests for Plugin._string_hours_payload — the pure half |
| `test_stamp_gate.mjs` | Node contract test for dashboards-gate.js (v2.70.0) — the |
| `test_sync_pages.py` | _sync_pages_to_public — the startup copy of the bundle's pages |
| `test_tap_guard.mjs` | Contract test for the tap guard and press feedback in |
| `test_test_index.py` | tests/README.md lists every test file (v3.25.0). It had fallen |
| `test_tick_script.py` | The shared companion-script runner (v2.95.2) and the poller's |
| `test_timeline.py` | Contract test for the timeline-replay helpers (v2.40.0): |
| `test_timeline_carry.py` | The Timeline page's "state at the start of the day" query must |
| `test_timeline_views.mjs` | Timeline as the one history page (v3.33.0): the four tabs, the |
| `test_verify_pin.py` | handleVerifyPin — the control-PIN speed bump. Had no tests at |
| `test_version_consistency.py` | Fails when the version signals disagree — the bundle's |
| `test_vpp_card.mjs` | Contract tests for the Cost page's Grid events (Axle VPP) card. |
| `test_weather_thread_restart.py` | A Configure save that restarts the weather thread while a fetch |
| `test_webrtc_route.py` | Contract tests for the WHEP signalling forward (v2.68.0) — |
| `test_when_to_run.mjs` | The "When to run it" card on the Energy page (v3.34.0), which |
