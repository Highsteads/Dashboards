---
title: Graphs
parent: Every page
nav_order: 22
---

# Graphs — `history.html`

![The Graphs page](../screenshots/history.png)

Pick a device, pick one of its recorded states, pick a window, get a chart. Anything the SQL Logger
has been recording can be drawn here without setting anything up first. Needs the SQL Logger.

## Down the page

**Picker card.** A device field with type-ahead over the whole estate, a "Recorded state" dropdown
listing only the states that device actually has history for, and four window pills: 6 h, 24 h,
7 days, 30 days.

**Chart.** A line for the bucketed average with a lighter band around it for the minimum and maximum
inside each bucket — so a spike is visible as a spike rather than being averaged flat. The strip
underneath gives the latest value, the minimum and maximum over the window, and the number of
buckets.

## Deep links

```
history.html?device=123456&state=batteryPowerWatts
```

The device parameter is an Indigo device id. A link that names a state opens that state; one that
does not opens the device's first recorded state.

## Where the data comes from

`historyQuery`. The plugin does the bucketing server-side, and it queries by primary-key range
rather than by timestamp. That is a requirement, not an optimisation: the history database has no
index on the timestamp column, so a timestamp filter scans the whole table and stalls the SQL
Logger's own writes.

## Refresh

None. The chart is drawn once per selection. Changing device, state or window fetches again.

## What you can do here

Choose a device, a state and a window. Nothing else.

## Worth knowing

- The state dropdown is populated from the history table's real columns, which the SQL Logger
  stores lowercased. A state that exists on the device but has never been logged will not appear,
  and that is the correct answer rather than a gap.
- History rows are sparse: the logger only writes a value when it changes, so any single row is
  never a full snapshot. The server side forward-fills before bucketing.
- Timestamps in the database are UTC on SQLite. Everything drawn on this page is local, converted
  on the way out.
- A device with a very long history and a 30-day window is the heaviest single query the plugin
  serves. It is still bounded, because the window is converted to a row-id range before anything is
  read.
