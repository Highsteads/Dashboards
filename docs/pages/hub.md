---
title: Hub
parent: Every page
nav_order: 1
---

# Hub — `index.html`

![The hub](../screenshots/index.png)

The page every other page hangs off, and the one that lives on the wall tablet. It answers "is the
house all right" from the top of the screen, then offers a way into everything else. It is
deliberately short: the House, Rooms and Tools tile walls it used to carry moved to the
[Menu](menu.md), because they were navigation, not status.

## Down the page

**Header.** The site name, the time of the last successful poll, and the live dot. A "Top" button
appears once you scroll.

**Greeting card.** A time-of-day greeting, the date, the running build number, and the current
weather with today's high and low and the sun times. Below that, a row of pills: each person's
presence, how many heating zones are calling for heat, a "Fire heater on" pill with the watts while
a fire's heater runs (Broadlink RF 1.4.0 with a power meter), a low-battery or in-error count, and,
when the energy plugin has one coming, a VPP event pill.

**Favourites.** One-tap tiles in the order set on the Settings page. A tile is a control (toggles a
device or runs a scene), a reading (shows a device state and cannot be tapped), a door tile (shows
the door's state and acts on it), a room shortcut or a group.

**Camera strip.** Up to four tiles from the cameras marked "main". At home the first tile runs live
and the rest poll stills; over the reflector none of them stream. The page assumes it is remote
until it can prove otherwise.

**Energy · now.** The power-flow diagram — solar, grid, home and battery around a central node, the
flowing edges showing which way the power is going and how much. Underneath, today's totals and
today's money. Hidden, with a one-line note saying why, when SigenEnergyManager is not installed.

**Solar · today.** Today's kWh against the forecast with a progress bar, then a stacked hourly
chart of per-array actuals with a dashed forecast tick on each, and a line giving remaining,
tomorrow, and how many daylight hours beat their forecast.

**Weather.** Outdoor temperature, today's range, humidity, wind with gust and maximum, rain today,
pressure, UV index, sunrise and sunset, and the indoor reading.

**House / Rooms / Tools.** Three cards, each a doorway into the menu at that group.

**Doors & windows.** Everything currently open, most recent first, with how long it has been that
way.

**Insights.** Anomalies against the house's own norms — a battery falling fast, a sensor gone
quiet, a room off its usual temperature, something on far longer than it normally is. Each line
says what is unusual and what the norm was. When there is nothing, it says so, with the count of
checks it made.

**Log banner.** Appears only when the hourly event-log watch has something live, headed with the
count and showing the most recent signature. A doorway to the [Activity](activity.md) page.

**Footer.** Last update, the poll cadence, and a *Reset connection* link that clears the stored API
key from this browser.

## Where the numbers come from

| Part | Source |
|---|---|
| Devices, rooms, favourites, doors | Indigo REST `/v2/api`, through the shared delta cache |
| Room list and membership | `rooms.json`, written by the plugin |
| Weather | `weather.json`, written by the plugin from OpenWeatherMap |
| Energy, solar, money, VPP | `sigenApi` — the plugin's proxy to SigenEnergyManager |
| Insights | `homeInsights` |
| Log banner | `logErrors` — the state file the hourly event-log watch writes |
| Camera stills and streams | The plugin's own port 8177 |

## Refresh

- Device summary every 3 s, and only for devices the `changedSince` endpoint says have moved.
- Energy every 30 s.
- Insights and the log watch every 5 minutes.
- Weather every 10 minutes.
- The greeting re-renders every minute so the date rolls over on a page left open overnight.

Before any of that, the gate checks the plugin's liveness stamp. If the plugin is stopping, the page
stops calling it.

## What you can do here

- Tap a favourite to toggle a device, run a scene, or work a door in the direction its own state
  calls for.
- Tap a room, a camera or any card to open its page, or a House / Rooms / Tools card to open the
  menu at that group.

Control tiles honour the PIN if the device is on the PIN list, and a guest-paired browser cannot
control anything at all.

## Worth knowing

- The camera strip is the page's whole bandwidth story. It decides live-versus-poll from how it was
  reached, and gets it wrong in the safe direction.
- The build number under the greeting is the fastest way to tell whether a wall tablet is running
  old JavaScript after an upgrade.
- Demo mode enters through this page, so the hub is also what `demo.html` shows.
