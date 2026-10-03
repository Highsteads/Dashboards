# Dashboards for Indigo

**Your house on a screen — energy, cameras, heating, every room, and the whole day replayed.**

**Version:** 3.59.1 | **Author:** CliveS & Claude | **Needs:** Indigo 2025.2

**[Read the full guide](https://highsteads.github.io/Dashboards/)** — setting up, a page of notes for every one of the 20 pages, and what to do when something goes wrong.

<img src="https://img.shields.io/badge/version-3.59.1-5856d6" alt="Version 3.59.1">
<img src="https://img.shields.io/badge/Indigo-2025.2-2a2a2e" alt="Indigo 2025.2">
<img src="https://img.shields.io/badge/pages-20-0a84ff" alt="20 pages">
<img src="https://img.shields.io/badge/licence-MIT-8e8e93" alt="MIT licence">

<img src="docs/screenshots/index.png" width="860" alt="The hub — whether anything needs a look, who is home, the heating, the battery and a strip of camera stills">

---

## What it does

This plugin gives [Indigo](https://www.indigodomo.com) a set of web pages for your house, built for an iPad on the wall, a phone in your pocket and a Mac on the desk. Indigo's own web server hands them out, so there is no app to install, no cloud account, and nothing leaves the house.

- **A hub page** says at a glance whether anything needs a look, who is home, how the heating is doing, and shows your favourite controls and a strip of camera pictures.
- **A page for every room**, built from your Indigo device folders, with lights, sockets, blinds, sensors, doors and cameras, and buttons that check the device really did what you asked.
- **Live camera video** from any IP camera with a video stream, which drops to still pictures on a slow connection so it does not run up a bill.
- **The solar and battery picture, and what the house costs to run**, for anyone with a Sigenergy solar and battery system, through my free SigenEnergyManager plugin.
- **Any day replayed** — presence, lights, doors and heating hour by hour, and a chart of anything Indigo has recorded, from the SQL Logger that comes with Indigo.
- **Alerts** when a device or variable changes, sent to your phone by Pushover or by email with no page open, or shown as a browser notification.
- **Heating, weather, Wi-Fi, every mains meter and the Indigo server's own health**, each on a page of its own.
- **A read-only guest link** for a wall tablet or a visitor's phone, which can look at every page but switch nothing.

Every page is my interpretation of my own house — my rooms, my solar and battery, my washing machine. Yours will be different, so take the ideas that suit your house and leave the rest. Every page, the plugin and the guide were written by Claude from conversation, and [Start with nothing but Claude](https://highsteads.github.io/Dashboards/no-coding-needed.html) shows how to have it build the pages you want without writing a line yourself.

## What it works with

It needs Indigo 2025.2 and nothing else. Each of these adds to it, and a page that needs one that you do not have says so or leaves itself out:

| Add this | And you get |
|---|---|
| **ffmpeg** and **go2rtc**, two free programs installed with Homebrew | The cameras. Both are needed |
| The **SQL Logger** plugin, which comes with Indigo | The Timeline, charts, and the history on the meter pages |
| My free **SigenEnergyManager** plugin, for any Sigenergy solar and battery system | The Energy and Cost pages, and the hub's energy cards |
| **EvoHomeControl** | The boost and force buttons on the Heating page. Temperatures and setpoints work with any thermostat |
| **UniFiHealth** 0.2.0 or later | The Wi-Fi pages |
| The **Pushover** plugin and a Pushover user key | Alerts on your phone. Without it an alert can still go by email |
| An **OpenWeatherMap** key | Sunset, the day's high and low, UV and conditions on the hub's Weather card |
| [Tailscale](https://tailscale.com) | The dashboards, live cameras included, away from home, with nothing opened up to the internet |

## The pages

Sixteen pages you use, plus four that hold the whole thing together (the menu, Settings, Setup and Guest). Each one has its own page of notes in the guide.

| Page | What it is for |
|---|---|
| **[Hub](docs/pages/hub.md)** | The front page: whether anything needs a look, who is home, the heating, your favourites, the cameras, the battery and the solar day so far |
| **[Menu](docs/pages/menu.md)** | Every page in one list, with each room as its own entry |
| **[Room](docs/pages/room.md)** | One room end to end — lights and sockets with real controls, blinds, sensors, cameras and doors |
| **[Active](docs/pages/active.md)** | Everything that is on right now, across the whole house |
| **[Scenes](docs/pages/scenes.md)** | Every Indigo action group as a button, each saying what actually happened |
| **[Energy](docs/pages/energy.md)** | The solar and battery picture, and when to run the washing. Needs SigenEnergyManager |
| **[Cost](docs/pages/cost.md)** | What the house costs to run, day by day. Needs SigenEnergyManager |
| **[Mains](docs/pages/mains.md)** | Every mains meter and how far each one disagrees with the others |
| **[Meter](docs/pages/meter.md)** | One meter in detail — its live reading, its rank and its history |
| **[Timeline](docs/pages/timeline.md)** | A day replayed, presence night by night, a chart of anything recorded, and the house diary |
| **[Heating](docs/pages/heating.md)** | Every heating zone, its temperature and its setpoint, with controls |
| **[Cameras](docs/pages/cameras.md)** | Every camera as live video, tap to enlarge |
| **[Weather](docs/pages/ecowitt.md)** | The weather station in full |
| **[System](docs/pages/system-health.md)** | The Indigo Mac's own health, devices in trouble, and what the automation is about to do |
| **[Wi-Fi](docs/pages/wifi.md)** | Every access point and how hard it is working, with [a page for each one](docs/pages/wifi-ap.md). Needs UniFiHealth |
| **[Alerts](docs/pages/alerts.md)** | The alert rules, how each one reaches you, and Indigo's recent errors |
| **[Settings](docs/pages/settings.md)** | Favourites, links, cameras, rooms, scenes and security, set in the browser |
| **[Setup](docs/pages/setup.md)** and **[Guest](docs/pages/guest.md)** | Pairing a browser, and pairing a look-only guest device |

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/Dashboards/releases/latest) and download `Dashboards.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `Dashboards.indigoPlugin`
3. Double-click `Dashboards.indigoPlugin` — Indigo will install it automatically

For the cameras, also install ffmpeg and go2rtc on the Indigo Mac, which the [guide](https://highsteads.github.io/Dashboards/getting-started.html) explains.

## Setting it up

1. Open **Plugins → Dashboards → Configure**, fill in **Indigo API Key** with an API key from your Indigo account, add the **Camera User** and **Camera Password** your cameras share if you have cameras (a camera with a different login gets its own under **Camera Logins**), and click **Save**.
2. Pair each phone, tablet or computer once with **Plugins → Dashboards → Generate One-Time Setup Link (+QR)** — open the link on the device, or scan the QR code with its camera, and it is paired with nothing to type.
3. Open the hub, go to the Settings page, and on the Rooms card tick the Indigo device folders that are your rooms. Until you do, there are no room pages.
4. Run **Plugins → Dashboards → Test Dashboards Setup**, which checks the lot and writes a line for each check into the Indigo event log.

The [Getting started](https://highsteads.github.io/Dashboards/getting-started.html) page goes through each step, and adding cameras, guest devices and the home-screen app.

## What's new

The three most recent releases, word for word. Every release before these is in
**[the version history](https://highsteads.github.io/Dashboards/changelog.html)**.

**3.59.1** (03-Oct-2026) - **The main page's Saving Session chip names every booked free hour too.** The chip at the top of the main page showed only the soonest stretch, so with free hours at 11:00-12:00 and 14:00-15:00 it said nothing about the afternoon one. It now lists every booked stretch, the same as the line lower down.

**3.59.0** (03-Oct-2026) - **Booked free hours show a day earlier, and the main page lists every one.** A booked free hour now appears on the main page and the Energy page 48 hours ahead instead of 24, so you know it is due. The main page's Saving Session line named only the soonest stretch, so with free hours at 11:00-12:00 and 14:00-15:00 the afternoon one stayed hidden until the morning one had finished. It now lists every booked stretch, for example "Free hours · 11:00-12:00, 14:00-15:00 · booked". Saving Sessions and Power Ups keep their 24-hour window.

**3.58.3** (03-Oct-2026) - **A booked free hour is no longer cut off at the edge of the day-ahead window.** Two booked free hours tomorrow, 11:00 to 13:00, showed as only 11:00 to 12:00 on the main page and the Energy page. Both pages only list sessions starting within 24 hours, and at 11:40 the first hour began 23 hours 20 minutes away while the second began 24 hours 20 minutes away, so the second was dropped before the two could be joined. A booked free hour that starts exactly where a shown one ends now stays with it, so the pair reads as one row, 11:00-13:00.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
