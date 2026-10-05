---
title: When something goes wrong
nav_order: 12
---

# When something goes wrong

## Start with the setup check

**Plugins → Dashboards → Test Dashboards Setup** checks everything in one go and writes a line for
each check into the Indigo event log, marked PASS, FAIL or SKIP. A missing optional piece, such as
SigenEnergyManager or a companion script, shows as SKIP, not as a fault. [The plugin
menu](plugin-menu.md#what-test-dashboards-setup-checks) lists what it looks at.

**Plugins → Dashboards → Show Plugin Info** writes the versions of everything involved into the log.
Paste that, with the setup check, into any request for help.

## Pages and pairing

| What you see | What it means | What to do |
|---|---|---|
| A page asks you to connect, or shows nothing | This browser has not been paired, so it has no Indigo API key to read your devices with | Pair it with **Plugins → Dashboards → Generate One-Time Setup Link (+QR)**, or type the key into the Connect form. See [Pairing a browser](getting-started.md#pairing-a-browser). From 3.46.0 a new install no longer hands the key out by itself |
| Every paired browser asks to connect again | The Indigo API key has changed | Pair each device again. The *Reset connection* link at the foot of every page makes a browser forget the old key |
| "out of date" or "not updating for four minutes" in amber beside the Updated time | The page has had no fresh data for a while, usually because the plugin is restarting | Wait for the next good update, which clears it. If it stays amber, check the plugin is running and look in the event log |
| Every page, and every other plugin's web page, goes quiet for about five minutes just after a plugin restart | A page left open for days, still running old code, asked the plugin a question in the middle of the restart and held up Indigo's web server | It clears by itself. Reload any dashboard that has been open for days so it picks up the newer pages, which wait for the restart to finish |
| The Settings page will not save | The plugin is restarting, and Save waits until it is running again | Wait a few seconds and press Save again. A refused save says what is wrong |
| A guest device will not pair | Guest pairing only works from the Indigo Mac's own network, over Tailscale, or from a network added under Configure → Extra trusted networks | Connect the device to the main Wi-Fi or to Tailscale and open the guest address again |
| A device on another network in the house (an IoT or guest Wi-Fi, say) no longer pairs itself or shows live video | From 3.60.0 the plugin's port 8177 answers only the Mac's own network and Tailscale, not every private network | If it is one of your own devices, add its network under **Plugins → Dashboards → Configure → Extra trusted networks**, or pair it with a one-time setup link. See [Which networks are trusted](getting-started.md#which-networks-are-trusted) |
| The event log says the plugin "could not work out which network this Mac is on" | Port 8177 is trusting only the Mac and Tailscale until it can | Add your home network under **Configure → Extra trusted networks**, written like `192.168.1.0/24` |

## Rooms

| What you see | What it means | What to do |
|---|---|---|
| No rooms on the menu | No room folders have been ticked, so the plugin is looking for another house's folder names | On the Settings page's Rooms card, tick the Indigo device folders that are your rooms, and save |
| A device in the wrong section of a room | The plugin has guessed wrongly from what the device is and what it is called | Use that room's overrides on the Rooms card to move it, hide it or put it first. See [Room extras](configuration.md#room-extras). Each room on the card shows what it has found, such as "1 doors · 0 appliances", so check that first |

## Cameras

| What you see | What it means | What to do |
|---|---|---|
| No camera pictures anywhere, and a warning in the log | ffmpeg or go2rtc is missing | Install both, as [Getting started](getting-started.md) describes, and restart the plugin. If go2rtc lives somewhere unusual, put its location under Configure |
| One camera never shows a picture | Its make, the shared camera login or its settings are wrong | Check its make on the Settings page, and read that make's catches under [Camera makes](cameras.md#camera-makes) — several makes ship with the stream switched off or need a separate camera account. Check that its login under Configure is right — Camera User and Password, or its entry in Camera Logins — and that the camera has RTSP — its video streaming — switched on. After adding or changing a camera, press Save under Configure and restart the plugin |
| A tile shows an error for a moment and then a picture | The camera did not answer the first request in time | Nothing. The plugin tries again and the second attempt works |
| Tiles say "2s" or "5s" at home | The page thinks the connection is slow | Tap "this device is" at the bottom of the Cameras page to tell it you are at home. Check the device was paired using the home address, not the reflector |
| Only some tiles are live video | The page measures the connection and allows as many live tiles as it can carry, six at most unless you change it. The rest show still pictures | Nothing, unless the connection is fast and you want more. The Cameras page footer shows the measured speed |
| On an iPhone or iPad, the cameras only go live after you touch the page | Auto-Play Video Previews is off, and iOS will not start any video on a web page without it | Turn on **Auto-Play Video Previews** in the iPhone's Settings, Accessibility, Motion |
| Live tiles never start, or fall back to stills | The live video needs ports 8177 and 8555 on the Indigo Mac, and nothing else reaches them from outside the house | At home, check nothing on the Mac blocks port 8555. Away, use Tailscale. Over the Indigo reflector you get still pictures only, by design |

## Missing pages and cards

| What you see | What it means | What to do |
|---|---|---|
| Energy and Cost are missing from the menu | They need the SigenEnergyManager plugin | Install or enable it. Dashboards notices within thirty seconds |
| The Heating page has no boost or force buttons | These are EvoHomeControl's own actions | Install and enable EvoHomeControl. Temperatures and setpoints work with any thermostat without it |
| The Timeline, a chart or the Meter page's history is empty | They read the SQL Logger's history database | Check the SQL Logger plugin is running, and that the history setting under Configure matches where it writes — SQLite unless you changed it. Run **Test History Connection**. A state that has never been logged is not offered for a chart |
| The Wi-Fi page is empty | It shows what the UniFiHealth plugin reports | Install UniFiHealth 0.2.0 or later |
| The Nights view is missing from the Timeline | It needs the `Presence_Watch.py` companion script | Copy it from the download's `scripts` folder into Indigo's `Python Scripts` folder and edit it for your rooms |

## Alerts

Start with **Send test** on the Alerts page, or **Plugins → Dashboards → Send Test Alert**. Each
channel says whether it sent, and if not, why.

| What it says | What to do |
|---|---|
| Pushover: no user key | Put your Pushover user key in the Pushover User Key field under Configure, or in `IndigoSecrets.py` as `PUSHOVER_USER_TOKEN` |
| Pushover: plugin not running | The message goes through the Pushover plugin, so install, enable or restart it. The log repeats this at most once every half hour while it is not running |
| Email: no address | Set an address under Where alerts go on the Alerts page. If an address is set and the test still fails, check Indigo's own mail settings |
| No browser notification | Browser notifications need one of the hub, a room page, the Energy page or the Alerts page open on that device, by a secure `https://` address. Pushover and email do not |

A rule fires when something changes, not while it stays that way, so "turns on" says nothing about a
light that is already on. After a rule fires it waits thirty seconds before it can fire again. A rule
stays quiet while "alerts active" is off, while the rule is paused, or while its device is disabled
in Indigo, and one whose device has been deleted is marked "target gone".

## Nothing above fits

- Look in the Indigo event log for this plugin's warnings and errors.
- The Alerts page's Indigo log errors card lists Indigo's errors, one row per fault however often it
  has repeated, if the `Log_Error_Watch.py` companion script is installed.
- [Open an issue](https://github.com/Highsteads/Dashboards/issues) on GitHub with the setup check and
  the Show Plugin Info lines.
