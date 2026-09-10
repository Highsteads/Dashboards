# Companion scripts

Seven standalone Python scripts the plugin executes from `Python Scripts/`
(the folder at the Perceptive Automation root, shared across Indigo versions).
The plugin ships and documents features that depend on them, so they live here
in the repo rather than only on one machine.

None runs from inside the bundle — copy them into
`/Library/Application Support/Perceptive Automation/Python Scripts/` and the
plugin picks them up on its next tick (it checks for the file every time; no
restart needed). At startup it logs one line naming whichever are missing.
All seven are optional — the dashboards work without any of them; two of them
are lighting automations for one house that you may not want at all.

`Appliance_Scheduler.py` is the one exception to "copy one file": it needs
`appliance_planner.py` beside it, which holds the thinking. Copy both. Their
test suite (`test_appliance_planner.py`) sits alongside them here and is run by
the plugin's own gate and by CI.

## Appliance_Scheduler.py (+ appliance_planner.py)

Powers the Laundry page. Works out when to run each metered appliance so it
costs the least grid import, from the solar forecast, the house's own measured load
profile, the battery and the live half-hourly prices, and says it in a sentence.
The plugin runs it every 15 minutes and serves the result over the Bearer-authed
`laundryPlan` endpoint — deliberately not from `/public`, since when a household
does its washing is behavioural.

**It advises. It never switches anything on.** A washing machine has to be
loaded by a person anyway, so a person is standing in front of it at exactly the
moment the advice is useful. It tells them when to press start, or what to set a
delay timer to.

**Nothing to edit.** It finds every enabled Appliance Monitor device by itself
and measures each machine's cycle profile from that device's own logged history
— the median duration, energy and peak of its finished cycles, ignoring the
lifetime meter totals that occasionally land in those columns. Add a machine and
it appears, and there is no device id anywhere in the file.

A machine that has finished fewer than five cycles gets **no profile at all**,
and the page says so. That is deliberate: a median of two is not a measurement,
and a nameplate rating is not what a cycle actually draws.

The deadline for each machine lives in an Indigo variable named from the
appliance — `washing_machine_deadline`, `tumble_dryer_deadline` — holding a time
like `16:00`, or nothing for the default. The page's chips write it for you.
Profiles are cached in `appliance_profiles.json` and re-derived daily. The
history queries are primary-key ranged, so they do not lock the SQL Logger out
the way a timestamp filter would.

It also wants two files the SigenEnergyManager plugin writes,
`openmeteo_forecast.json` and `sigen_site_config.json`, and the
`elec_rates_today_json` / `elec_rates_tomorrow_json` variables. Without them it
says so plainly and offers no advice, rather than guessing: a forecast that has
not arrived is not a forecast of no sun.

## Presence_Watch.py

Builds the Presence page's data: per-night presence-sensor timelines, an
agreement/disagreement track for each sensor pair, dropout callouts, a PIR
movement strip and a bedroom sleep proxy, from the SQL Logger history. The
plugin runs it every 5 minutes and serves its output over the Bearer-authed
`presenceData` endpoint — deliberately not from `/public`, which is anonymous
and reflector-reachable.

**Edit the `ROOMS` block before use** — it names your rooms, watch windows and
presence-sensor device ids. The shipped values are this author's house and
will produce empty timelines anywhere else.

All its history reads are PK-ranged (rowid binary search): the SQL Logger DB
has no `ts` index and `journal_mode=delete`, so a ts-filtered query full-scans
the table while holding a read lock against the logger's writes. Do not
"simplify" the queries back to `WHERE datetime(ts,'localtime') ...`.

## Log_Error_Watch.py

Hourly watch on the Indigo event log. Collapses errors into signatures
(source + digit-normalised message) and alerts — Pushover headline plus a full
email — only on what is new or has gone unresolved for a day. Warnings are
recorded for the Alerts page but never pushed. Its first run seeds the state
file and deliberately alerts nothing, so an existing install's background
noise never pages anyone. State lives beside the script (again not `/public`:
raw log text carries hostnames, IPs and traceback fragments) and is served by
the Bearer-authed `logErrors` endpoint.

Credentials come from `IndigoSecrets.py` (`PUSHOVER_USER_TOKEN`,
`LOG_WATCH_EMAIL` / `DIGEST_EMAIL`) with blank-safe fallbacks.

## Reflector_Bandwidth_Watch.py

Measures how much data the Indigo reflector is actually carrying, and says so
before anyone else has to.

Indigo Domotics wrote twice about this server's reflector usage and
deactivated the reflector the second time, and nothing here could answer "how
much, and since when". The web server logs no successful request, so a page
quietly pulling camera pictures through the reflector leaves no trace at all,
and the tunnel itself does not show up in `lsof` or `netstat`. It does show up
in `nettop`: the reflector is a single SSH reverse tunnel
(`ssh -N -R1234:127.0.0.1:8176 prism@...`), so every byte in and out of that
one process is the reflector and nothing else is.

The script samples that process every five minutes, accumulates the deltas
into hourly buckets, logs a line for each finished hour, and warns when an
hour exceeds 20 MB outbound — with the figure, so the message is evidence
rather than a hunch. It keeps a week of hourly buckets in
`reflector_bandwidth_state.json` beside itself, so a spike can be dated after
the event instead of guessed at.

A tunnel restart resets the counters, and the script re-bases rather than
reading the reset as a huge negative. No tunnel running at all is normal, not
an error: the reflector may simply be switched off.

Nothing to edit. It needs no credentials and changes nothing.

## FP300_Config_Watch.py

Hourly watch on the device-side configuration of Aqara FP300 (PS-S04D)
presence sensors. Those settings live on the sensor, not in Indigo, so a
battery change or a button reset silently returns them to the firmware
defaults and nothing notices. That is exactly what happened here: adaptive
sensitivity was switched off deliberately, went back on with a battery change,
and stayed wrong for four weeks while presence fragmented through every night.

The script compares the live states against the intended values, warns on
drift, and re-asserts them over MQTT — but only while a sensor reports
presence. An FP300 is a sleepy battery device, zigbee2mqtt will not reliably
queue a write for one, and an asleep sensor silently ignores the message, so
the correction lands the next time somebody is in the room. It also watches
`powerOutageCount`, which is the earliest sign a sensor has been reset.

**Edit the `SENSOR_IDS` and `DESIRED` blocks before use.** `SENSOR_IDS` names
your own Indigo device ids. `DESIRED` carries the intended settings —
adaptive sensitivity off and a 120-second absence delay are what suit a
bedroom, and a room you only ever walk through wants something shorter.

The MQTT topic is read from each device's `friendly_name` plugin prop rather
than pinned in the script, because an Indigo device name and its zigbee2mqtt
name can disagree — here the two bedroom sensors are bound to each other's
names, so a hardcoded topic would address the wrong sensor.

Credentials come from `IndigoSecrets.py` (`MQTT_BROKER`, `MQTT_PORT`,
`MQTT_USERNAME`, `MQTT_PASSWORD`) with blank-safe fallbacks. paho-mqtt is
loaded from the Zigbee2MQTTBridge plugin's bundled `Packages` folder.

## Drive_Lights_Sun.py

The drive lights on at full from sunset to sunrise and off the rest of the
time. One script owns them; it replaced seven separate pieces of automation
that used to share the job. The plugin ticks it every two minutes alongside
the night sweep.

**Edit the device ids at the top before use** — they name this author's two
drive lights.

## Night_Lights_Sweep.py

The overnight backstop. Every couple of minutes it checks that no light is
burning in an empty room and that the living-room fire is out, and turns off
what it finds. Everything else in a house turns lights off in response to a
human event; this is what notices a bulb that came back on by itself at four
in the morning. The plugin ticks it every two minutes.

**Edit the room table before use** — it names this author's rooms, lights and
presence sensors, and the living-room override device.

