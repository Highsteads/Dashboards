---
title: Energy
parent: Every page
nav_order: 3
---

# Energy — `energy.html`

![The Energy page](../screenshots/energy.png)

Everything the solar and battery system knows, on one long page in labelled bands. The hub's energy
card is the summary; this is the whole thing. **Needs the SigenEnergyManager plugin.** Without it
the menu drops the tile, the hub leaves out its energy cards, and a bookmark to this page opens the
hub instead; nothing else on the dashboards depends on the plugin.

## Down the page

**VPP banner.** When the energy plugin has a demand-response event announced but not started, a
full-width strip under the header says so, and the status pills carry a matching chip.

**Live power flow.** The same diagram as the hub, larger, with status pills top right: grid state,
days of backup at the current draw, and the inverter's working mode. Solar, grid, home and battery
each show instantaneous watts and today's running total; the battery also shows percentage and kWh
stored. Dots travel along each line in the direction the power is going, faster and thicker
the more there is, easing when it changes and slowing to a stop before a flow turns round. Four tiles under it: self-sufficiency today (which says "grid charged the battery" when a night's cheap-rate charge is why it reads low), solar today against forecast, benefit today,
and battery state of charge with what it is doing.

**Today.** A Sankey of where every kWh since midnight came from and went, with a note stating the
round-trip loss and warning that the two sides disagree by that amount, because the split is a best
fit to the daily totals and not a metered figure. It sits under the solar card, full width.

**Battery.** A ring for state of charge, what it is doing now in kW, and a 24 h sparkline with the
day's low and high. Then a grid of tiles: state of health, pack
temperature with the cell spread, pack balance, grid frequency and voltage banded against the
statutory range (the limit comes from the plugin, never hardcoded), inverter temperature, PV
insulation resistance shown with no verdict because the manufacturer's threshold is not public,
the inverter's own alarm state, cell voltage, and today's charge and discharge. A tile that cannot
know does not appear. The dawn reserve is on the Manager card.

**Money.** Saved today from solar and battery against what a grid-only day would have cost, with
import paid, export earned and net grid, and a link across to the [Cost](cost.md) page for the full
breakdown. Energy only: standing charges and gas live on the Cost page.

**Solar.** Today's kWh against forecast with a progress bar, remaining, expected total, tomorrow
and the forecast bias. Then the stacked hourly chart: elapsed hours as per-array actuals, each with
a dashed forecast tick at the height it was promised — a stack topping or missing its tick is the
beat-or-miss verdict, drawn as geometry rather than colour so it survives colour-blindness — and a
scoreboard line counting it. Future hours are pale forecast bars. Where a past hour has no history
it stays a gap rather than becoming a fabricated zero. Below that a cumulative chart, solid for
banked so far and dashed for the corrected forecast, with an ahead / behind / on-forecast chip;
then tiles for now, tomorrow's surplus, yield per kWp, forecast accuracy and lifetime generation;
then a per-array strip with each array's share of its own rating, live watts and kWh today.

**Manager.** What the energy plugin is deciding and why: the current mode, whether dawn is viable,
the projected dawn state of charge and the reasoning in the plugin's own words; the tariff, with
tomorrow's rate and direction; and the system card — connection, VPP state, storm watch, export
lockout, and a short log of recent grid events.

**When to run it** (from 3.34.0, when the Carbon and Laundry pages merged into it). Two halves:

- *Laundry.* For each metered appliance, one sentence ("Put the washing machine on now and it
  should finish about 4:31pm"), deadline chips (noon, 2pm, 4pm, 7pm, 10pm, no deadline) that replan
  it on the spot, a sun / battery / grid bar for the recommended run, and, folded away, every half
  hour to the deadline (said once when they all cost the same). The machine's own measured cycle is
  named underneath, "not the manual". Needs the `Appliance_Scheduler.py` companion script, which
  finds every enabled ApplianceMonitor device and measures each machine from its own history; a
  machine needs about five logged cycles first. Nothing here switches a machine on.
- *Grid carbon.* The advice (run now, wait, any time) with its reason, grid carbon for your region
  with a plain-English band, the cleanest half hour in the next day, a 24-hour forecast chart, and,
  folded away, the live generation mix and how the advice is worked out: spare solar first, then a
  clean grid, then the cleanest window in the next 16 hours. Great Britain only, from the free UK
  Carbon Intensity API; switch it off under Configure. Like the rest of this page it needs
  SigenEnergyManager, and without it the plugin makes no carbon lookups at all.

Each half hides itself when it has nothing to say, and the card goes when both do. The old
`carbon.html` and `laundry.html` addresses land here.

**Environment.** Lifetime CO₂ avoided, expressed several ways.

**History.** Energy per half-hour as a stacked chart above and below the axis — supplied above, used
below — with 24 h / 48 h / 7 d buttons. To replay a day minute by minute, use the
[Timeline](timeline.md) page. Then daily totals for the last 30 days, then week on week against the previous week and the
same week last year (the year-on-year column stays empty until a full year exists, and says so).

**Records.** Export sync — the plugin's own reading against the supplier's, day by day, with the
difference and an in-sync verdict.

## Where the numbers come from

Almost all of it arrives through one endpoint: `sigenApi`, the plugin's server-side proxy to
SigenEnergyManager's data API. It is a proxy rather than a direct call so the page works away from
home as well as on the LAN — the browser never needs to reach the energy plugin itself. The path is
allow-listed and the upstream host is fixed.

The When to run it card reads `laundryPlan` (and `laundryDeadline` for a chip) and `carbonAdvisor`,
which caches the carbon data for ten minutes server-side. The stacked hourly chart is the other
exception: it reads `solarStringHours`, which integrates per-hour
per-array kWh out of the SQL Logger history, PK-ranged and cached, and returns null for an hour with
no samples so the page falls back rather than inventing zeros.

## Refresh

- Live flow and status every 5 s.
- Charts and summaries every 20 s.
- Half-hourly history every 5 minutes.
- Daily totals every 30 minutes.
- The lifetime and records blocks hourly.
- When to run it every minute, and on demand when a deadline chip is tapped.

## What you can do here

Nearly nothing: control of the battery lives in the energy plugin itself. The interactions are the
chart range buttons, the laundry deadline chips and the link to the Cost page.

## Worth knowing

- The Sankey's note about the two sides disagreeing is not a bug being apologised for. The split is
  fitted to the daily totals, so it is a picture of the day rather than a meter reading.
- Forecast accuracy compares the day's forecast against what arrived, so a low number after an
  unusual sky is the forecast being wrong rather than the array underperforming.
- The manager's reasoning line is worth reading before wondering why the battery is doing what it
  is doing. It says which of the plugin's rules is currently in charge.
