---
title: Heating
parent: Every page
nav_order: 10
---

# Heating — `heating.html`

![The Heating page](../screenshots/heating.png)

Every radiator zone with its live temperature and a working setpoint control, plus the two
timed controls where the heating plugin supports them.

## Down the page

**Controls card.** Drawn only when the EvoHomeControl plugin is installed and enabled — the buttons
are wired to that plugin's own actions. Two rows: *Timed boost* (22 °C for one hour, 22 °C for two
hours, Cancel boost) and *Summer shut-off override* (bypass summer shut-off for 24 hours, Cancel override, and a link that
writes the current heating state into the Indigo event log). Each of them asks for the control
PIN, once per session, when any heating zone on the page is on the PIN list (Settings → Security),
as the zones' own buttons do, before 3.46.0 they skipped it.

Active buttons turn red and show the time left, counting down every second. Both a boost and
the summer bypass can be active together. These are the controller's saved timers, so they
survive a page reload. If their status cannot be read, the page says so. A red button means
the timer is active, not that a radiator must be heating.

**Summary strip.** Zones calling for heat, the house average, the coldest zone with its name, the
warmest with its name, and the outside temperature. A coloured edge on the strip reflects whether
anything is calling.

**Zone grid.** One card per zone: the name, the current temperature large, a setpoint stepper with
minus and plus, the valve state, and how long ago the zone was last heard from. A zone at an unusual
temperature is coloured — blue when cold, amber when warm — so the grid reads at a glance.

**Footer.** Last update and the refresh cadence.

## Where the numbers come from

| Part | Source |
|---|---|
| Zone temperatures, setpoints, valve state, last heard | Indigo thermostat devices via `/v2/api`, through the shared delta cache |
| Room membership and titles | `rooms.json` |
| Timer status | `evoHomeStatus`, reading only the timer fields from EvoHomeControl's saved state |
| Boost and summer bypass buttons | `evoHomeAction`, which passes the call through to the EvoHomeControl plugin |

Zone temperatures and setpoints work with any Indigo thermostat device. Only the boost and force
buttons are plugin-specific.

## Refresh

Zone readings and timer status refresh every three seconds. The countdown ticks every second.

## What you can do here

- Step any zone's setpoint up or down. Steps are whole degrees, because Indigo's REST setpoint call
  is integer-only.
- Boost the rooms configured in EvoHomeControl for one or two hours. With EvoHomeControl 1.23.0 or later, Cancel Boost sets all radiators to 12 degrees until each room's next scheduled temperature change; open-window protection still wins. Natural expiry returns to the schedule.
- Bypass summer shut-off for 24 hours, allowing normal scheduled heating, and cancel it.
- Write the current heating status to the Indigo log.

## Worth knowing

- A setpoint change is read back after being sent. A stopped heating plugin swallows the command
  without an error, so the tile would otherwise show the new number as if it had landed when
  nothing moved.
- "Last heard" is the honest clock for a battery radiator valve. One that has not spoken for hours
  is a valve to go and look at, whatever its temperature reads.
