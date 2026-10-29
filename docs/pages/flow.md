---
title: Flow
parent: Every page
nav_order: 27
---

# Flow — `flow.html`

The house, live, drawn the way the Sigenergy app draws it: a picture of a house with solar panels, a SigenStor battery, a gateway and a car charger, with power moving between them. Needs SigenEnergyManager; the **Flow** tile sits beside Energy and Cost on the menu and only appears where that plugin is installed.

The picture and the card are the [Sigenergy Flow Card](https://github.com/jyavenard/sigenergy-flow-card) by Jean-Yves Avenard, written for Home Assistant and used here, unchanged, under the Apache License 2.0. Dashboards gives it the readings it would have had from Home Assistant, taken from SigenEnergyManager, the Zappi plugin and the weather station. The house in the picture is a generic one, not yours.

## Down the page

**The picture.** Solar and Home above the house, SigenStor (with the battery level) and Grid below it, each with its power now. Lines of light run along the cables in the direction power is moving, faster at higher power, and stop when nothing moves. A light look between sunrise and sunset, a night look the rest of the time.

**The weather**, top left: an icon for the conditions now from OpenWeatherMap, with a moon after dark, and the outdoor temperature from the Ecowitt station. Tap it to open the Weather page. Without an OpenWeatherMap key there is no icon and the picture cannot tell day from night by the sun.

**The car charger**, on the garage wall, only when the Zappi plugin has a charger: the power going into the car and whether a car is plugged in. Tap the AC CHARGER reading to open the car charger card on the Energy page, with its mode and boost buttons. The car's draw is taken off the house figure, so Home shows the house on its own, as the Sigenergy app does. A charger that has not reported for ten minutes shows as not reachable, with no power figure.

**Tap SOLAR** for each string: voltage, current, power, what it has made today, and a chart of each string through the day. String names come from SigenEnergyManager.

**Tap HOME** for what is drawing power now: every metered plug and switch in Indigo, highest first, with the share of the house load each one takes and the rest shown as unmeasured. Meters whose name says they measure a whole circuit or the house (mains, grid, solar and the like) are left out, so they do not swamp the list.

**Today's energy**: solar made, grid in and out, battery charged and discharged, and the battery level.

**Battery level**, with the energy stored out of the battery's capacity.

**Power metrics**: the day from midnight, with what supplies the house (solar, battery discharging, grid import) above the line and what uses it (house, battery charging, export, car) below. The rest of the day is a dashed forecast: solar from SigenEnergyManager's forecast, the house from its average at each hour over the last seven days. Hover or tap for the values at any time. Sunrise and sunset are underneath.

**Energy statistics**: where the energy went over a day, week, month, year or all time, as a diagram from sources on the left to uses on the right. Tap a block to see its split.

## Where the numbers come from

- **Now:** SigenEnergyManager's status, every five seconds.
- **The chart and the day's statistics:** SigenEnergyManager's half-hourly records, so the history is in half-hour steps. The line then follows the live readings for as long as the page is open.
- **Longer statistics:** SigenEnergyManager's daily records. Battery charge and discharge in a half hour are worked out from what came in and went out, so they ignore battery losses.
- **Strings:** the SQL Logger's per-string history, by the hour.

## Worth knowing

- The charger drawn on the garage wall is too small to tap; tap its reading instead.
- His card asks Home Assistant for things Indigo does not have. A few taps that open Home Assistant's own details windows (a single reading's history) do nothing here.
- The page needs a browser that shows AVIF pictures: iOS 16, macOS 13 Ventura, or a current Chrome, Edge or Firefox. On older systems the readings work but there is no picture.
- When his card gets a new version, Dashboards can take it as it is; the stand-in that feeds it is `sigen-flow-bridge.js`.
