---
title: Demo
parent: Every page
nav_order: 26
---

# Demo — `demo.html`

Three lines that do the work:

```html
<script>
    sessionStorage.setItem("dash_demo", "1");
    location.replace("index.html");
</script>
```

## What it does

Sets the session demo flag and forwards to the hub. Every page then runs from the canned fixtures in
`demo-data/` with a gentle state simulator behind them — solar wobbles, the battery drifts, motion
flickers, and controls change the local fixture so toggles feel real. No Indigo server, no
credentials, no device touched. An orange banner along the bottom of every page says "DEMO DATA —
none of this is your house. Tap to exit."

## Worth knowing

- The flag lives in `sessionStorage`, so demo mode ends when the tab closes rather than persisting
  on the device.
- The fixtures are a separate data set, generated from a real house by `tools/make_demo_fixtures.py`
  and sanitised on the way: addresses, hardware identifiers, credentials of every kind and a
  household name are all placeholders. A test in the repository keeps them that way.
- Demo mode forces every optional feature on, so it shows the Energy, Cost and Laundry pages
  whatever plugins this server has.
