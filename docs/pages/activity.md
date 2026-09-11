---
title: Activity
parent: Every page
nav_order: 17
---

# Activity — `activity.html`

![The Activity page](../screenshots/activity.png)

Three cards: what has gone wrong, what has happened, and what is about to happen.

## Down the page

**Alerts.** Errors and warnings from the Indigo event log, collapsed by signature. Each row gives
the message, a repeat-count badge, the source plugin, and the time of the most recent occurrence,
with a red or amber edge for the level. Collapsing matters: one stall can produce a dozen
near-identical lines milliseconds apart, and without it the card would be nothing but that. It is
also what turns ten symptoms into one cause — a plugin that was stopped shows as one server line
above the run of unreachable-device errors it explains.

**House diary.** Curated events only — locks, doors, leaks, safety events, plugin restarts. When
there is nothing, it says so; its empty-state line is the page's whole editorial policy: *"A script
talking to itself does not."*

**Automation.** A header count of schedules, triggers and how many are switched off. Then "Coming
up": the next schedules due, each with its name, the day and time, and how long until it fires.
Below that, three collapsible sections — Watching for problems, Switched off, and Door codes with
the per-person roster (PIN digits are scrubbed server-side and never reach the browser).

**Footer.** Last update and a countdown to the next refresh.

## Where the data comes from

`activityFeed`, which builds the whole page server-side from the Indigo event log plus the schedule
and trigger definitions. `logErrors` supplies the muting judgement — which signatures are live and
which are known noise — from the state file the hourly `Log_Error_Watch.py` companion script writes.

## Refresh

Every 30 s, with a countdown in the header and footer.

## What you can do here

Expand the three collapsible sections, and follow an event to that moment on the
[Timeline](timeline.md). Read-only otherwise.

## Worth knowing

- Reading the event log has traps the server side handles for you: the in-memory buffer is capped
  rather than honouring a requested line count, a wrapped multi-line message arrives as separate
  rows a millisecond apart, and a core-server message carries the bare level as its source where a
  plugin carries "Source Error".
- Collapsing by signature needs the message normalised for paths, plugin ids and interpolated
  names, or one stall keys as a dozen separate faults. It also refuses to merge two messages whose
  openings match, or a burst of complete messages gets welded into one composite that can never
  recur and therefore always looks new.
- The "off" count in the Automation header is worth watching. A disabled trigger is invisible
  everywhere else until something it was supposed to catch goes wrong.
