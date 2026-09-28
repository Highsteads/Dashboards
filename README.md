# Dashboards for Indigo

**Your house on a screen — energy, cameras, heating, every room, and the whole day replayed.**

**Version:** 3.56.0 | **Author:** CliveS & Claude | **Needs:** Indigo 2025.2

**[Read the full guide](https://highsteads.github.io/Dashboards/)** — setting up, a page of notes for every one of the 20 pages, and what to do when something goes wrong.

<img src="https://img.shields.io/badge/version-3.56.0-5856d6" alt="Version 3.56.0">
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

**3.56.0** (28-Sep-2026) - **The hub shows the car charger too.** When Indigo has a myenergi Zappi from the Zappi plugin, a Car charger strip sits under the Energy, Solar and Weather cards: the charger's own status line, the power going into the car, the charge added and what the export guard is doing. Tapping it opens the Car charger card on the Energy page, which now scrolls into view when you arrive that way. Like the Energy page, it holds the readings back when the charger cannot be reached or has not reported for ten minutes, and without a Zappi device it does not appear.

**3.55.0** (28-Sep-2026) - **The Energy page shows the car charger.** When Indigo has a myenergi Zappi from the Zappi plugin, a Car charger card sits under the Battery card: whether a car is plugged in, the charging mode, the power going into the car, what this session has added and what the export guard is doing. When the guard has stopped the charger because the house battery is selling to the grid, the card says so and names the mode it will go back to. If myenergi cannot reach the charger, or it has not reported for ten minutes, the card says that and holds the readings back rather than show an old figure as live. Without a Zappi device the card does not appear.

**3.54.1** (28-Sep-2026) - **The Garage door tile shows its colour.** On a room page that has cameras, the door tile sits beside them, and its picture area kept a white background over the red of an open door, the blue of a moving one and the amber of a stuck one. The state words are white, so "Open", "Closing" and "Stuck" could not be read. The colour now shows through and the words with it. The hub favourite was never affected.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
