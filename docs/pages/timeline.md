---
title: Timeline
parent: Every page
nav_order: 15
---

# Timeline — `timeline.html`

![The Timeline page](../screenshots/timeline.png)

Drag along a day and the house tells you what it was doing at that moment. Needs the SQL Logger.

## Down the page

**Day picker.** Previous and next arrows around the date, with a "Today" button.

**Moment card.** The time being examined, large, with the date and whether it is "now". Under it,
pills describing that instant: how many presence sensors were active and which, how many doors and
windows were open and which, the battery state of charge and the solar output.

**Lanes.** One row per category — Presence, Lights, Doors & windows, Heating, and Battery & solar —
each spanning midnight to midnight. The first four are activity bars, coloured per category, with a
count of how many devices were active in that lane. Battery and solar is drawn as a chart instead:
state of charge as a line, solar as a filled area. A vertical marker shows where you are scrubbing,
and a lane with nothing in it says so in words ("none today").

**Legend and hint.** The colour key, and the instruction: tap or drag anywhere to scrub, release to
see the house at that moment.

## Where the data comes from

`timelineDay`, with a body of `{"date": "YYYY-MM-DD"}` defaulting to today, local. The plugin builds
the whole day server-side from the SQL Logger history: each lane is a list of per-device active
spans in minutes from midnight, plus the battery and solar traces.

It has to be server-side. The history database has no index on its timestamp column, so the query
is done by primary-key range after binary-searching the row boundary — a timestamp filter would
scan the whole table and stall the SQL Logger's own writes.

## Refresh

None. The page loads a day and holds it. Changing the date fetches again.

## What you can do here

- Scrub anywhere on the timeline to move the moment card.
- Step between days, or jump back to today.
- Follow the link to the [Presence](presence.md) page.

## Worth knowing

- History timestamps are stored in UTC (on SQLite) while `device.lastChanged` is local, so the
  server side converts. A cross-check against another page that looks an hour out in summer is the
  timezone, not a real delay.
- An empty lane means nothing was logged in that category that day, which for Heating in August is
  the correct answer rather than a gap in the data.
- The day boundary is local midnight, not UTC midnight.
