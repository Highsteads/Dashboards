---
title: Carbon
parent: Every page
nav_order: 5
---

# Carbon — `carbon.html`

![The Carbon page](../screenshots/carbon.png)

One question, answered at the top: is now a good time to run a load. Everything below is the
working. Needs nothing beyond a region setting — the data is the free UK
[Carbon Intensity API](https://carbonintensity.org.uk), no key required.

## Down the page

**Verdict.** A coloured card with a timing word, a heading and a sentence explaining it. In daylight
with spare solar it reads **RUN NOW** and names the spare kilowatts; with a clean grid and no
surplus it reads **ANYTIME**; otherwise it names the cleanest window ahead. The advice ranks spare
solar first, then a genuinely clean grid, then waiting for the cleanest window in the next sixteen
hours.

**Three tiles.** Grid carbon for your region in gCO₂/kWh with a plain-English band, solar now with
the battery percentage beside it (a dash after dark rather than a zero), and the import rate with a
note on how it moves through the day. Daylight alone does not make it RUN NOW: solar the house and
battery are already using is not spare.

**Grid carbon, next 24 hours.** A half-hourly forecast bar chart, greener meaning cleaner, with the
current half-hour outlined and the cleanest upcoming window called out.

**Where the grid's power is coming from.** The live generation mix as labelled bars, ordered by
share. Categories at zero drop out, so the list is shorter after dark.

**How this is worked out.** The reasoning in full, including the part that matters most: on a flat
tariff the cost is much the same whenever you run, so carbon and solar drive the timing rather than
price.

## Where the numbers come from

`carbonAdvisor`. The plugin fetches your region's intensity, the 48-hour forecast and the generation
mix, caches them for ten minutes server-side, and combines them with the live solar surplus and
tariff (from the energy plugin, when present) before handing over a recommendation.

## Refresh

Every 60 s, with the header counting down to the next one. The carbon data behind it only moves
every ten minutes because of the server-side cache. A fetch landing just after a plugin restart
retries quickly instead of waiting out the full poll.

## What you can do here

Read the verdict and follow the link to the Energy page. No controls.

## Worth knowing

- The region matters. Carbon intensity is regional, and yours may be considerably cleaner or dirtier
  than the national figure. Set it under Configure.
- The advice deliberately prefers spare solar over a clean grid even when the grid is very clean,
  because spare solar is free and would otherwise be exported for pennies.
- On a flat tariff the page is about carbon, not money.
