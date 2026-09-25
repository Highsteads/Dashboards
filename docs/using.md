---
title: Using the dashboards
nav_order: 5
---

# Using the dashboards

## The hub, and the menu

The hub (`index.html`) is the page on the wall tablet. It answers "is the house all right" from the
top of the screen — who is home, the heating, the battery, today's carbon, a strip of live cameras —
and then offers a way into everything else through three cards: House, Rooms and Tools. Those open
the menu (`menu.html`), which is the only page that lists every page and every room, so a room added
in Settings appears there without touching any HTML.

Every page has a Home button, and the tiles that look tappable are tappable.

## Things that move

A screenshot cannot show any of this, which is rather the point of the list.

**The power flow really flows.** On the Energy page and on the hub's power card, the sun, the
battery, the house and the grid sit around the inverter and streams of dots run along the links
between them, in the direction the energy is actually going. Reverse the battery from charging to
discharging and the dots turn round. The figures behind it refresh every five seconds, and the
battery ring sweeps to its new level rather than jumping.

**The live dot tells you whether to believe the page.** The hub, Energy, Cost, System, Mains and
Meter pages carry a small green dot beside their "Updated" time that pulses while the data is
arriving. If nothing has arrived for a while (half a minute on the hub and Energy, three missed
polls on the others) it turns amber, stops pulsing, and the words beside it change to "out of date"
(on Mains and Meter, "not updating for four minutes"). It runs on its own timer rather than on the
poll, because a poll that has died cannot be trusted to report that it has died — and only a poll
that actually returned data clears it. The pages that count down to their next refresh instead
(rooms, Heating, Active, Weather, Wi-Fi) have no dot; their Updated time simply stops moving.

**Sensors pulse while they are seeing something.** A motion or presence tile on a room page
breathes gently for as long as the sensor is detecting, so a glance tells you the difference between
"someone is in the kitchen" and "someone was".

**A door in motion sweeps.** Press Open on a garage or a front door and the button takes itself
over: it fills, says what it is doing, counts the seconds, and a light sweep runs across the tile
for as long as the contacts say the door is actually moving. It holds until the sensors confirm the
door really has moved, goes red if it failed, and goes amber and tells you to go and look if nothing
confirmed it either way. It is reporting the door, not the fact that Indigo accepted the request.

**Cameras are live video, not stills.** The camera's own H.264, relayed over WebRTC with no
re-encoding, on the Cameras page and on the hub's camera strip, wherever the connection is fast
enough to carry it (the pages time it); on a slower one they show stills that cross-fade. The room
pages show stills, and a tap opens that camera on the Cameras page. On a slow link — away from home over Tailscale, on mobile data — everything slows
right down and then stops altogether after ten minutes untouched, because somebody is paying for
those bytes.

**Charts redraw rather than reload.** The energy, cost, carbon and history charts update in place
as new figures arrive, and the Timeline's replay control pulses while it is playing.

**Cards animate in once.** A card slides in on the first paint of a page and never again. Identical
output writes nothing to the page at all, so text stays selectable and anything you have opened
stays open.

**And all of it stops if you ask it to.** Every animation sits behind `prefers-reduced-motion`.
Turn motion down in your operating system and the dots, the pulses, the sweeps and the card
entrances all go, while everything keeps working.

## Tap to go deeper

**Tiles that open a page of their own:**

| On this page | Tapping this | Opens |
|---|---|---|
| Hub | a room tile | that room, end to end |
| Hub | the camera strip | the full camera grid |
| Hub | the weather, energy or timeline card | that page |
| Mains | any meter tile | that meter's own page — its live reading, its rank against every other meter, its seven-day offset and its history |
| Wi-Fi | any access-point tile | that AP's own page — per-radio state and every client on it |
| Menu | any room | that room |
| Activity | an event | that moment on the Timeline |
| Timeline | the presence lane | the Presence page |
| Energy | the money figures | the Cost page, and back again |
| Room | a camera | the Cameras page, with that camera enlarged |

**Tiles that open in place, without leaving the page:**

| On this page | Tapping this | Opens |
|---|---|---|
| Room | a light or socket | its own controls, and a full colour picker for anything colour-capable |
| Room | a blind | its position control |
| Weather | any sensor | that sensor's reading and its recent history |
| Cameras | any stream | full screen — tap again to come back |
| Hub | a Favourite | the device's controls, in the tile |
| Laundry | a deadline chip | replans that appliance on the spot |
| Meter, System, Activity, Settings | a fold | the detail underneath, which stays open while you are on the page |

**And two things that look like they should be tappable and deliberately are not.** A meter that is
not answering shows no position on the voltage scale, because a frozen reading cannot be placed on
a scale of live ones. And an appliance that has not run enough times to be measured gets no deadline
chips, because there is nothing yet to schedule.

## Controls, confirmation and the PIN

A control button does not flash a tick because the command was accepted. `dashboards-action.js`
runs the action, takes the button over, and watches the device states until the thing has really
happened — a device whose communication is disabled, or whose plugin has stopped, swallows a command
without an error, and the page would otherwise show a switch flipped for ever while nothing moved.
It checks back a few seconds later and reverts with a warning if the device disagrees.

Devices on the **PIN list** (Settings → Security) ask for the control PIN once per session before
any command. It is a speed bump for a shared tablet, not a lock.

A **guest-paired** browser sees every page and can control nothing. It holds no API key, so the
restriction is not a matter of the interface politely hiding buttons. It can still read every
device's state and see the cameras, so treat a guest link as a view of the house; see
[Guest devices](remote-access.md#guest-devices).

## Alerts

The Alerts page is where you tell the plugin what to watch: pick a device or a variable, choose a
condition ("turns on", "turns off", "changes at all"; a variable fires whenever its value changes),
and choose how you want to be told. From 3.47.0 the **plugin** keeps the rules and watches them on
the Indigo server itself, so they fire whether or not any dashboard is open, with a thirty-second
per-rule cooldown so a chattering sensor cannot spam you. Each rule can go out by:

- **Pushover**, to your phone, through the Pushover plugin (it must be installed, enabled and
  running) and the user key in `IndigoSecrets.py` (`PUSHOVER_USER_TOKEN`) or Configure;
- **email**, through Indigo's own mail settings, to the address on the rule, else the default
  address on the Alerts page, else `DASHBOARDS_ALERT_EMAIL` in `IndigoSecrets.py`;
- **browser**, a notification on any device that has the hub, a room page, Energy or Alerts open.
  This one still needs a page open, and a secure (`https://`) address; see
  [Notifications and install need HTTPS](remote-access.md#notifications-and-install-need-https).
  With several of those pages open, one notification is raised, not one per tab.

The page says which channels are ready ("Pushover: ready", "plugin not running", "no user key"),
has a **Send test** button that reports each channel's result, and lists the plugin's recent
alerts with what each channel did. **Plugins → Dashboards → Send Test Alert** does the same test
from the Indigo menu and writes the result to the log. A channel that fails is logged as a warning
(at most once every half hour for the same reason) and never stops the others.

Before 3.47.0 the rules lived in each browser and only fired while a page was open there. A browser
that still holds rules from then is offered a one-click **Move these rules to the plugin** the first
time it opens the Alerts page, as long as the plugin has none yet; they are removed from the browser
only once the plugin has them. The server-side error watch on the same page is a different thing:
it is always on and sends its own notifications.

## Standalone app

The dashboard ships a web-app manifest, so it can be pinned as a proper standalone app rather than a
browser tab.

- **iPhone / iPad** — open the hub in Safari, tap Share, then **Add to Home Screen**.
- **Mac (Safari)** — **File → Add to Dock…** (macOS Sonoma and later).
- **Mac / Windows (Chrome or Edge)** — the install icon in the address bar, then **Install**, but
  only on a secure address (`https://`, or `localhost` on the Indigo Mac). Over the usual
  `http://…:8176` address Chrome and Edge do not offer it; see
  [Notifications and install need HTTPS](remote-access.md#notifications-and-install-need-https).
  Safari's Add to Home Screen and Add to Dock work over plain http.

Links inside the standalone app stay inside it — tapping through to room pages, the camera grid and
so on does not bounce out to the browser.
