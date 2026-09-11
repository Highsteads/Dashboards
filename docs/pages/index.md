---
title: Every page
nav_order: 5
has_children: true
---

# Every page

Twenty-two pages you use, plus five that hold the whole thing together. Every one is a plain HTML
file, and every one reads live Indigo data through the same Bearer-authed API. Each has a page of
notes here: what is on it, where the numbers come from, how often it refreshes, what you can do,
and the things worth knowing before you trust it.

## Start here

| Page | File | What it is for |
|---|---|---|
| [Hub](hub.md) | `index.html` | The front page. Who is home, the heating, the battery, today's carbon, a strip of live cameras, your favourites, and a way into everything else |
| [Menu](menu.md) | `menu.html` | Every page in one grouped list, with each room as its own entry |

## Energy and money

| Page | File | What it is for |
|---|---|---|
| [Energy](energy.md) | `energy.html` | The whole solar and battery picture. Needs SigenEnergyManager |
| [Cost](cost.md) | `cost.html` | What the house costs to run, from bill-exact economics. Needs SigenEnergyManager |
| [Carbon](carbon.md) | `carbon.html` | How dirty the grid is now and over the next day, and when to run a load |
| [Mains](mains.md) | `mains.html` | Every mains meter in the house and how far each disagrees with the others |
| [Meter](meter.md) | `meter.html?id=N` | One meter in detail |
| [Laundry](laundry.md) | `laundry.html` | When to run each metered appliance so it costs the least. Needs SigenEnergyManager |

## The house

| Page | File | What it is for |
|---|---|---|
| [Room](room.md) | `room.html?room=Name` | One room end to end — lights and sockets with real controls, blinds, sensors, cameras, doors |
| [Heating](heating.md) | `heating.html` | Every zone, its temperature and its setpoint, with controls |
| [Cameras](cameras.md) | `cameras.html` | Every camera as a live stream, tap to enlarge |
| [Active](active.md) | `active.html` | Everything currently on, across the whole house |
| [Scenes](scenes.md) | `scenes.html` | Every Indigo action group as a button, grouped by folder |
| [Weather](ecowitt.md) | `ecowitt.html` | The weather station in full |
| [Timeline](timeline.md) | `timeline.html` | Any day replayed on one scrubbable timeline |
| [Presence](presence.md) | `presence.html` | Per-night presence-sensor timelines, and whether the sensors agreed |

## Keeping watch

| Page | File | What it is for |
|---|---|---|
| [Activity](activity.md) | `activity.html` | A house diary from the event log, and what the automation is about to do |
| [Alerts](alerts.md) | `alerts.html` | Notification rules for this browser, and the server-side error watch |
| [System health](system-health.md) | `system-health.html` | The Indigo server's own vitals and a device-health census |
| [Wi-Fi](wifi.md) | `wifi.html` | Every access point and how hard it is working. Needs UniFiHealth |
| [Wi-Fi AP](wifi-ap.md) | `wifi-ap.html?id=N` | One access point in detail |
| [Graphs](history.md) | `history.html` | Time-series charts of any recorded device state |

## Setup and access

| Page | File | What it is for |
|---|---|---|
| [Settings](settings.md) | `settings.html` | The forms-based configuration editor |
| [Setup](setup.md) | `setup.html` | First-run pairing from a one-time link |
| [Guest](guest.md) | `guest.html` | Pairing for a read-only device |
| [Demo](demo.md) | `demo.html` | The whole thing running on fixtures, with no Indigo behind it |
| [WebRTC test](webrtc-test.md) | `webrtc-test.html` | A bench for one camera stream, for diagnosing the away path |
