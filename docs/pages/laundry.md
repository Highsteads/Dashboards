---
title: Laundry
parent: Every page
nav_order: 8
---

# Laundry — `laundry.html`

![The Laundry page](../screenshots/laundry.png)

One question per appliance, answered in a sentence: put it on now, or wait. Everything below is the
working, not a control — nothing on this page switches a machine on. **Needs the SigenEnergyManager
plugin** for the forecast, the battery and the prices; without it the page shows one card saying so.

## Down the page

One card per metered appliance, each with:

**Verdict.** One sentence in bold — "Put the washing machine on now and it should finish about
4:31pm" — followed by where the energy for that run would come from and how much difference the
deadline actually makes. On a night with the battery near full it usually says plainly that timing
makes very little difference, which is the honest answer rather than a manufactured urgency.

**Finish by.** Deadline chips — noon, 2pm, 4pm, 7pm, 10pm, no deadline. Picking one replans that
appliance on the spot.

**Where its kWh would come from.** A single stacked bar — sun, battery, grid — for the recommended
run, with the split named underneath.

**Every half hour between now and the deadline.** Where slots genuinely differ in cost it lists each
one. Where every slot costs the same it says so once and explains why, rather than listing
forty-odd identical rows.

**Footer note.** The appliance's own measured cycle — how long, how many kWh — and how many real
cycles that figure is drawn from, with an explicit "not the manual".

## Where the numbers come from

The `Appliance_Scheduler.py` companion script, ticked by the plugin. It finds every enabled
ApplianceMonitor device in the house by itself and measures each machine's cycle length and energy
from that device's own logged history — no per-machine configuration. A machine needs at least five
logged cycles before it gets a profile at all; fewer than that and the page says there is not enough
history yet rather than quoting a guess, and it gets no deadline chips because there is nothing yet
to schedule. The plan itself weighs the solar forecast, the house's own measured hourly load, the
battery's state and the live half-hourly price against the chosen deadline.

The plan is served through `laundryPlan`, over the same Bearer-authed route as everything else,
never from the anonymous public folder — when a household does its washing is nobody else's
business. A deadline goes back through `laundryDeadline`.

## Refresh

Every 60 s, and on demand whenever a deadline chip is tapped.

## What you can do here

Pick a deadline. Nothing here switches anything on — a machine has to be loaded by a person anyway,
so a person is standing in front of it at exactly the moment the advice is useful.

## Worth knowing

- Adding a dishwasher or a dryer is a metering plug and an ApplianceMonitor device, not an edit.
  It turns up here on its own once it has run about five cycles.
- Expect "makes very little difference" on a summer night with a nearly full battery. It earns its
  keep on dull days, through the winter, and once the price starts moving through the day.
