---
title: The plugin menu
nav_order: 8
---

# The plugin menu

Everything below is under **Plugins → Dashboards** in Indigo. **Configure…** at the top opens the
plugin's settings, which the [Configuration](configuration.md) page covers field by field. The rest
are listed here in the order Indigo shows them. Most of them write their answer into the Indigo
event log, so keep the log window open when you use them.

| Menu item | What it does |
|---|---|
| **Open Dashboards in Browser** | Opens the hub in the web browser on the Mac that runs Indigo, and writes its address into the log so you can copy it to another device. If the Indigo window you are using is on a different Mac, the page opens on the server's screen, not yours |
| **Regenerate Config + Resync Pages** | Reads your credentials again, from `IndigoSecrets.py` and from Configure, copies the pages into Indigo's web folder again and rewrites the small settings file the pages load, all without restarting the plugin. Use it after you have edited `IndigoSecrets.py` |
| **Generate One-Time Setup Link (+QR)** | Pairs a phone, tablet or computer with nothing to type. It writes a link into the log, plus a second link to a QR code you can open on the Mac and scan with the phone's camera. Each link works once and stops working after ten minutes if nobody uses it. It needs the Indigo API key to be set, and says so in red if it is not |
| **Show Guest Access Info** | Writes into the log the address to open on a guest device, such as a wall tablet or a visitor's phone, which can then look at every page but switch nothing. It also says what a guest can see, how many Indigo variables you have shared with guests, and warns you if *Auto-seed the API key to LAN browsers* is ticked, because a guest link means nothing while it is |
| **Rotate Guest Link and Camera-Stills Folder** | Takes back everything you have handed out. Every guest device is un-paired at once, and the camera pictures move to a new hidden folder while the old one is deleted. Reload any dashboard page that is open afterwards, or its camera pictures stop. Your own paired devices carry on working, because the API key does not change |
| **Toggle Timestamps in Log (on/off)** | Turns on or off the time, to the thousandth of a second, at the start of each of this plugin's log lines. The choice is kept across restarts |
| **Test History Connection** | Checks that the plugin can read the SQL Logger's history, from SQLite or PostgreSQL, whichever you picked under Configure. It says PASSED or FAILED with the reason, then how many devices have recorded history and how many of their states can be charted. Run it after changing the history settings |
| **Send Test Alert** | Sends "Test from Dashboards" by Pushover and by email, whichever of the two is set up, and writes each result into the log. If neither is set up it says what is missing. It does the same as **Send test** on the Alerts page |
| **Test Dashboards Setup** | Checks everything a new install needs, one line each, marked PASS, FAIL or SKIP, and ends with a count. See below |
| **Show Plugin Info** | Writes the plugin's version and your Indigo, Python and macOS versions into the log, with the hub's address, the Indigo address, where the API key comes from, how many cameras are set up, which history database it reads and whether log timestamps are on. Paste this into any request for help |

## What Test Dashboards Setup checks

It starts with the same lines as **Show Plugin Info**, then checks, in this order:

- that the Indigo API address and the API key are set,
- that the plugin can write to Indigo's public web folder and has written the pages' settings file,
- that the plugin's heartbeat file is being updated, which the pages use to tell whether the plugin is running,
- how many cameras are set up and, if there are any, that the streaming program (go2rtc) is running, that the camera user name and password are set, and that ffmpeg is installed,
- that at least one of the folders you ticked as rooms exists in Indigo,
- whether SigenEnergyManager is installed, which decides whether the Energy and Cost pages appear,
- whether the SQL Logger's history database is there, for the Timeline, the hub's Home Insights and the history on the Mains and Meter pages,
- whether the Script Ticker plugin is running, which decides whether it or Dashboards runs the companion scripts,
- which of the seven optional companion scripts are in Indigo's `Python Scripts` folder.

The last four are optional, so a missing one shows as SKIP rather than FAIL, and does not count
against the total. A FAIL line is red in the log and names what to do about it.
