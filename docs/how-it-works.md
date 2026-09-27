---
title: How it works
nav_order: 6
---

# How it works

This page explains, without the technical detail, what goes on between Indigo and the screen in
your hand. The [Technical notes](architecture.md) page has the file names and the detail for anyone
who wants them.

## The pages are ordinary web pages

Each dashboard page is a single web page file that ships inside the plugin. Every time the plugin
starts, it copies them into the public folder of Indigo's own web server, the one that answers on
port 8176, so any browser on your home network can open them. There is no app to install, nothing
to build, and nothing goes to the internet.

A page on its own knows nothing about your house. When it opens, it asks Indigo for your devices,
using the Indigo API key — the long password-like code Indigo gives you for other programs to use —
which the browser keeps once you have paired it. That is why each phone, tablet or computer has to
be paired once, with a setup link from the plugin menu, and why the key itself is never written into
any of the public files. Guest pairing, and automatic pairing if you turn it on, go through the
plugin's own port 8177, which only answers devices on your home network or on Tailscale.

## Keeping up with the house

A page fetches every device once when it opens, and after that, each time it refreshes, asks only
which devices have changed since it last looked, with a full refresh every five minutes to be safe. So a room page stays current without pulling the
whole house across the network each time. Where a page needs something Indigo cannot give it
directly, such as the server's own health, the history of a sensor or the plan for the washing
machine, it asks the plugin, which works the answer out on the Indigo Mac and hands it back.

Before a page asks the plugin anything, it checks a small file the plugin rewrites every two
seconds while it is running, and marks as stopping when it shuts down. If the plugin is restarting,
the page waits, because a question that reaches the plugin in the middle of a restart can hold up
Indigo's whole web server for about five minutes.

## Rooms come from your folders

The room pages are built from Indigo's device folders. You tick the folders that are rooms on the
Settings page, and the plugin sorts each device in them into lights, sensors, blinds, radiators and
so on from what kind of device it is and what it is called. When it guesses wrong, the Settings page
lets you move a device, hide it or put it first, room by room.

## Controls that check the result

When you press a button, the page sends the command and then watches the device until it really has
changed. A device whose plugin has stopped can accept a command and do nothing at all, so the page
checks again a few seconds later and puts the button back, with a warning, if the device disagrees.

## Cameras

The cameras need two free programs on the Indigo Mac, ffmpeg and go2rtc, which the plugin starts and
looks after. go2rtc talks to each camera, and passes the camera's own video straight on to your
browser without changing it, which is what makes live tiles possible. When the connection is too
slow for video, the pages show still pictures instead, taken every couple of seconds from the same
streams. The pictures sit in a hidden folder whose name only a paired browser is told. The
[Cameras](cameras.md) page explains the rest.

## History

The Timeline, the charts and the history on the Meter page all read the SQL Logger's database, which
comes with Indigo and records every change of every device you log. The plugin only ever reads it,
and reads it in small pieces, because that database can be several gigabytes.

## Alerts

The alert rules you set on the Alerts page are kept and watched by the plugin on the Indigo Mac, so
they work with no dashboard open. When a device or variable changes the way a rule says, the plugin
sends the message by Pushover or email. A rule can also raise a browser notification on a device that
has the hub, a room page, the Energy page or the Alerts page open, as long as that page was opened
by a secure `https://` address.

## Companion scripts

A few optional Python scripts in the `scripts` folder of the download add things the pages can
show: the night-by-night presence view on the Timeline, the hourly check of Indigo's log for errors,
and the laundry advice on the Energy page, among others. Copy the ones you want into Indigo's
`Python Scripts` folder, and the plugin runs them for you on its own timer, with nothing to set up in
Indigo. If you also run my Script Ticker plugin, it runs them instead and Dashboards leaves them
alone.

## Your settings

What you change on the Settings page and the Alerts page is kept in one file in the plugin's own
folder in Indigo's Preferences, which is never served to a browser. Passwords and keys stay in the
**Configure** dialog, or in `IndigoSecrets.py` if you use one, where no web page can change them.
