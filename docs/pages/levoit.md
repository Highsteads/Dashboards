---
title: Air
parent: Every page
nav_order: 26
---

# Air — `levoit.html`

Levoit air purifiers, added to Indigo with the [Levoit Purifier plugin](https://github.com/Highsteads/Levoit). The page finds every purifier by the states that plugin writes, so it shows one card per purifier on any install, and the **Air** tile on the menu only appears where that plugin is installed.

## Down the page

For each purifier:

**The air.** PM2.5 large, in micrograms per cubic metre, with the purifier's own verdict beside it: Excellent or Good in green, Moderate in amber, Poor in red. A line under the name says when the purifier was last read, or that it is not connected to VeSync. When it is switched off the number is the last reading before it stopped, and the page says so.

**Power.** The switch top right turns it on and off, the same as any switch in Indigo.

**Mode.** Auto, Manual or Sleep, the current one in blue. In Auto a second row chooses how hard it works: Default, Efficient or Quiet.

**Fan speed.** 1 to 4. Choosing a speed puts the purifier in manual mode, which the page says under the buttons while it is in another mode.

**Filter life**, as a bar. Below 10% the bar turns red and the page says it is time to order a new filter. Resetting the count after fitting one is an action in Indigo, not a button here, so it cannot be pressed by mistake.

**Power and cost**, when the purifier's settings in Indigo name the plug it runs from (Levoit Purifier plugin, "Plug it is on"): what it is drawing now, then what it has cost today and over the last seven days, with the kWh beside each. Every unit is priced at Flux's cheap 2am to 5am rate, because the purifier runs from the battery and the battery is filled at that rate; the page says which rate it used. The rate is the cheapest of today's prices that SigenEnergyManager publishes, so it follows Octopus. Without published prices it shows the kWh alone. The week comes from the SQL Logger; if the plug has less than a week of history the page says since when.

**Child lock** and **Display light**, as switches.

**PM2.5 chart** for the last day or week, with the range the readings covered in each slot shaded behind the line. It comes from the SQL Logger, so it needs that plugin (it ships with Indigo) and fills in as the purifier reports.

## What happens when you press something

Every control except power goes to the Dashboards plugin, which checks it — only a Levoit purifier, only the values that purifier takes — and hands it to the Levoit Purifier plugin's own action. That plugin sends it to VeSync and shows the new setting straight away, holding it while VeSync's own status catches up, which can take a few minutes. The setting the purifier is on shows in blue. A button you press turns red straight away and stays red until the purifier shows the change, then turns blue; a switch you flick turns red the same way. Pressing the same red button again does nothing more. If nothing has shown after 45 seconds the page says so; VeSync can be slow, and the change appears when it lands. A refused command says why.

Controls go through the same PIN and guest rules as every other control on the dashboard. While a purifier is not connected to VeSync its controls are greyed out.

## Worth knowing

- Readings come from VeSync, refreshed by the Levoit Purifier plugin every minute unless its settings say otherwise, so a number can be up to a minute old.
- The page refreshes every three seconds, and the chart every five minutes.
