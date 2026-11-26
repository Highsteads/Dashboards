---
title: Plugs
parent: Every page
nav_order: 28
---

# Plugs — `plugs.html`

What every plug that measures its own energy costs a day, one by one and all of them together. It finds the plugs itself: Shelly plugs added with ShellyDirect, Zigbee plugs added with the Zigbee2MQTT Bridge, and ESPHome power monitors, wherever they report their energy. Reach it from the **Plugs** tile on the menu, or from the foot of the Cost page.

## Down the page

**All the plugs together.** What they have cost today so far, yesterday, over the last 7 days and over the last 30 days, with the kWh under each.

**Cost each day.** A bar for each of the last 30 days, today's paler because it is not over yet. Hold or hover over a bar for the day, the cost and the kWh. It shows all the plugs together until you tap a plug in the list, then that plug alone; tap it again, or **Show all the plugs**, to go back.

**Each plug.** One row per plug, dearest first, with its cost and kWh for today, yesterday, the last 7 days and the last 30 days. The chips above the list choose which of the four the order follows. Under the name is the room it is filed in, "not answering" in red when the plug is in error or has dropped off the network (it then shows no figure for today, because its counter has stopped), and "records from" a date when its history starts part way through the 30 days. A plug that has since been disabled or deleted keeps its past days in the totals, under one row called "Plugs since removed" that names them (3.74.0); the row goes once its last day is more than 30 days old. Plugs that used nothing in 30 days are listed by name at the bottom instead of taking a row each, and plugs with no energy on record at all are listed apart from them.

## Where the numbers come from

- **Energy.** A Shelly counts its energy from midnight each day. A Zigbee plug or an ESPHome monitor keeps a running total. The plugin works out each day's use from the readings the SQL Logger records, so a plug that restarted part way through a day is still counted in full. A small step back in a reading, which Shelly plugs make many times a day, is ignored rather than taken for a restart. A count that changes unit (a newly paired Zigbee plug reports watt-hours, then kilowatt-hours) and a jump no supply could carry are taken as a new starting line, not as energy used.
- **Price.** Every kWh is priced at Flux's cheap rate, because the house runs from a battery that is filled in the cheap window. The rate is the cheapest of the prices SigenEnergyManager publishes for the day, and each day is priced at the rate published for that day, so a price change moves only the days after it. Electricity drawn from the grid at another time costs more than the page shows. Without published prices the page shows the kWh alone; a day with no published prices on record shows its kWh and is left out of the money.
- **Past days** need the SQL Logger. Without it the page shows today alone, from each Shelly's own count. A finished day is worked out once and kept, so the page stays quick after its first load.

## Worth knowing

- The figures are worked out every five minutes, and the page asks for them every five minutes.
- A Zigbee plug's running total reaches Indigo only when the plug is set to report it. If a Zigbee plug that is clearly in use shows nothing, add reporting for its energy in Zigbee2MQTT: the device's Reporting tab, cluster `seMetering`, attribute `currentSummDelivered`.
- A plug that is switched off at the wall shows nothing for the days it was off, which is right: it used nothing.
