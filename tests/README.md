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
| `test_action_watch.mjs` | Contract test for DashAction — how the dashboard's control |
| `test_apply_colour.py` | Contract test for Plugin.handleApplyColour — the v2.94.0 endpoint |
| `test_battery_pct.py` | Truth-table test for Plugin._battery_pct — the estate's three |
| `test_bulk_lights_open_loop.mjs` | Contract test for the Lights section's "All On / All Off" when |
| `test_camera_boot_policy.mjs` | Contract test for the camera page's BOOT POLICY and the |
| `test_camera_frame_age.mjs` | Contract test for the per-tile frame-age readout and the |
| `test_camera_stall_watchdog.mjs` | Node contract test for the cameras.html slow-link stall |
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
| `test_door_tile.mjs` | Contract test for the hub's state-driven door favourite — |
| `test_energy_alert_bar.mjs` | Node contract test for energy.html's alert bar. Extracts the |
| `test_energy_cost.mjs` | Node contract test for energy-calc.js — the shared arithmetic |
| `test_energy_soc.mjs` | Node contract test for energy.html's handling of an UNKNOWN |
| `test_fav_device_label.mjs` | Contract test for the label on a plain on/off device favourite |
| `test_fav_group_tile.mjs` | Contract test for the group favourite (v2.93.0) — ONE hub tile |
| `test_fav_room_shortcuts.mjs` | Contract test for room shortcuts in the Favourites card |
| `test_getdevices.mjs` | Node contract test for dashboard.js getDevices() delta-merge — |
| `test_go2rtc_log_datestamp.py` | go2rtc stamps its log lines with the TIME only and cannot be |
| `test_go2rtc_supervise.py` | The go2rtc supervisor must keep trying after a FAILED restart. |
| `test_guest_scrub.py` | A guest-token holder must never receive plugin props. The |
| `test_history_db.py` | Contract tests for history_db.py — the SQL Logger artefact |
| `test_history_pk_range.py` | Contract test for the PK-range window helpers — the mechanism |
| `test_history_query.py` | Contract test for Plugin._history_query against a fixture SQL |
| `test_home_insights.py` | Contract tests for the Home Insights evaluators (v2.42.0) — the |
| `test_hub_lean_away.mjs` | Contract test for the hub's AWAY LEAN LAYOUT (v2.87.0). Away |
| `test_hub_vpp_and_version.mjs` | Node contract test for the v2.66.0 hub changes — the VPP chip |
| `test_hub_vpp_rows.mjs` |  |
| `test_link_class.mjs` | Contract test for DashUI.linkClass / measuredClass — how the |
| `test_log_watch_alive.py` | The plugin ticks Log_Error_Watch.py hourly, so the plugin is |
| `test_parse_cameras.py` | Contract test for the module-level _parse_cameras — JSON-string vs |
| `test_pin_redaction.py` | Security contract test for Plugin._parse_lock_code_trigger — the |
| `test_poller_auth_and_hidden.mjs` | Contract test for the hub's four side pollers — sigen, string |
| `test_presence_endpoint.py` | Contract tests for the v2.71.0 presence-data privacy fix — the |
| `test_release_versions.py` |  |
| `test_room_door_device.mjs` | Contract test for the ROOM page's state-driven door tile |
| `test_rtt_estimator.mjs` | Contract test for the estimator inside DashUI.probeRtt — which |
| `test_save_config.py` | Contract test for Plugin.handleSaveDashboardsConfig — the settings |
| `test_security.py` | Regression tests for the /public credential-leak fixes — the |
| `test_settings_fav_passthrough.mjs` | Contract test for the settings editor carrying favourites it |
| `test_shutdown_budget.py` | shutdown() must not wait on the snapshot pool. Until 2.95.1 |
| `test_snapshot_conditional.mjs` | Contract test for the camera still-refresh mechanism — the |
| `test_solar_hours_chart.mjs` | Contract test for DashUI.solarHoursChart — the stacked hourly |
| `test_solar_string_hours.py` | Contract tests for Plugin._string_hours_payload — the pure half |
| `test_stamp_gate.mjs` | Node contract test for dashboards-gate.js (v2.70.0) — the |
| `test_sync_pages.py` | _sync_pages_to_public — the startup copy of the bundle's pages |
| `test_tick_script.py` | The shared companion-script runner (v2.95.2) and the poller's |
| `test_timeline.py` | Contract test for the timeline-replay helpers (v2.40.0): |
| `test_timeline_carry.py` | The Timeline page's "state at the start of the day" query must |
| `test_verify_pin.py` | handleVerifyPin — the control-PIN speed bump. Had no tests at |
| `test_version_consistency.py` | Fails when the version signals disagree — the bundle's |
| `test_vpp_card.mjs` |  |
| `test_webrtc_route.py` | Contract tests for the WHEP signalling forward (v2.68.0) — |
