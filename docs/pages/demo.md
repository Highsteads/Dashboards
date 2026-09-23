---
title: Demo
parent: Every page
nav_order: 26
---

# Demo — `demo.html`

**Try it online: [highsteads.github.io/Dashboards/demo/](https://highsteads.github.io/Dashboards/demo/demo.html)**
— every page, running in your browser from sample data, with nothing to install.

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
- Demo mode forces every optional feature on, so it shows the Energy and Cost pages and the When
  to run it card whatever plugins this server has.
- The plugin's own endpoints (energy, the Timeline, System health, the meters) answer from canned
  files in `demo-data/api/` too, so a demo opened on a real install never mixes that house's
  readings into the made-up ones. `tools/make_demo_api.py` captures them from a live server and
  cuts them down: the Timeline keeps its lights, heating and energy lanes but not presence or
  doors, the Nights view is left out altogether, account figures and outage history are blanked,
  and the activity diary and error log are invented rather than captured.
- The online copy is `docs/demo/`, built by `tools/build_demo_site.sh`. A test fails when it falls
  behind the pages, so it cannot quietly go stale.
