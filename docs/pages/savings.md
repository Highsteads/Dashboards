---
title: Savings
parent: Every page
nav_order: 29
---

# Savings — `savings.html`

What the solar panels and battery have saved, worked out step by step from your own meters, against the same house with neither on the standard capped tariff. Reach it from the **Savings** tile on the menu, or from the foot of the Cost page. It needs SigenEnergyManager 5.146.0 or later.

## Down the page

**What was saved.** The total for the period you pick (the last month, three months, this year, or since records began), and how much of the electricity the house used came from its own panels, straight away or through the battery. The page remembers the period you last picked.

**Step by step.** Six bars, each starting where the last one ended. Tap a bar to have it explained in words.

1. **No kit.** The electricity the house really used, every kWh bought at the standard capped price (Flexible Octopus), with its daily standing charge.
2. **Solar.** The same use with the panels and no battery. Each half hour the house uses what the panels are making, buys any shortfall at the standard price and sells what is left at the standard export price (Outgoing Octopus).
3. **Tariff.** That same energy, priced at the tariffs you were really on, half hour by half hour, with their standing charges.
4. **Battery.** What the meters really recorded, at those prices. On any day Octopus has billed, Octopus's own bill is used instead.
5. **Extras.** Money paid for helping the grid: Axle's grid events and monthly top-ups, and Octopus's free-hour credits.
6. **Paid.** What the electricity really cost, or how much it paid you if you ended in credit.

Each step changes one thing, so every pound lands in exactly one bar and the bars always add up to the saving.

**Your own solar, Price per kWh, Paid on top.** How much of the house ran on its own sun, with the figure it would have reached with no battery; what each kWh cost on average, against the standard price; and the money paid on top.

**Paying for itself.** How much of what the system cost has come back, and when it should be paid off at this pace. If you have entered what the installer's quote promised, a table sets each promise beside what the system is on course for. Months not yet on record are taken at the pace of the slowest month so far, so for a system started in spring the figure is a best case: December and January are darker still.

**Week by week.** The saving each week as bars, with the solar made each week as a line, so a poor week shows whether the sky was to blame. A paler bar is a week with fewer than seven days in it. Under it, the best and the poorest day.

**Tariff by tariff.** Each tariff you have been on, its days, what it saved in all and a day, and the solar a day it had to work with.

**Every kWh.** Where the house's electricity came from (solar as it was made, solar through the battery, grid through the battery, grid as it was used) and where the solar went (used straight away, stored, sold). The battery is treated as a mixed store: energy bought from the grid at night and put in the battery comes out as grid energy, not solar.

**Paid on top, line by line.** Each Axle payment and Octopus free-hour credit, newest first. A referral credit from Axle is listed but not counted, because the kit did not earn it, and a payment dated on a day with no usable record is listed but not counted either.

**How this is worked out.** Which days the figures cover, and anything left out or estimated.

## Settings

On the **Settings** page, under **Savings**, enter what the system cost, the date it started working, and, if you have them, the yearly saving, yearly solar and payback the installer's quote promised. All of them are optional: without a cost the page leaves out how far it has paid back.

## Where the numbers come from

- **Energy** comes from SigenEnergyManager: its daily records, and its half-hourly records for the half-by-half-hour sums.
- **Standard prices** are Octopus's own published Flexible Octopus and Outgoing Octopus prices for your region, read from Octopus's public price list (no account needed, only the region letter) and kept for a day. If Octopus cannot be reached, the last copy is used and the page says how old it is.
- **Your prices** are the ones SigenEnergyManager recorded for each half hour, and Octopus's published Flux export bands while you are on Flux.
- **Octopus's bill** is used for every day Octopus has billed. The page says how close its own sums came to Octopus's on those days, which is a fair guide to the days not billed yet.
- **Axle payments and free-hour credits** come from SigenEnergyManager's records of them.

## Worth knowing

- Electricity only: gas is not counted, and nor is battery wear.
- A day recorded only as a daily total (before SigenEnergyManager kept half-hourly records) is estimated, and the page says how many there are.
- A day whose record does not add up, typically one rebuilt from the Sigenergy app with the solar missing, is left out and counted.
- The figures are worked out at most every 15 minutes.
