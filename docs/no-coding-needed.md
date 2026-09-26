---
title: Start with nothing but Claude
nav_order: 2
---

# Start with nothing but Claude

This page is for the person who runs Indigo, has never written a line of code, has looked at
the rest of this site and thought "that is far too complicated for me". It is not, and this
page is the proof: **every page on this site, every line of the plugin behind it, and every
word of these docs was written by Claude.** I did not type any of it. I said what I wanted, in
plain English, looked at what came back, and said what was wrong. That is the whole method.

## First, an honest word about what you are looking at

**These dashboards are my interpretation of my house.** The rooms are my rooms, the energy
pages exist because I have solar and a battery, the When to run it card exists because I got fed up
guessing when to put the washing on, and the Mains page exists because I wanted to know which
of my plugs was telling the truth. Yours will be different, and they should be.

You can go as deep as you want on any Indigo device. A page can show or control any of it:
switch things on and off, dim them, open and close them, change a light's colour, show which
doors and windows are open, run a trigger, a schedule, an action group or a Python script. If
Indigo can do it, you can ask for a page that does it.

Nothing here is a template you have to live inside. It shows what is possible when you can
describe a page and have it built for you, and the sensible way to use it is to look through
[every page](pages/index.md), decide which ideas suit your house, ignore the rest, and then ask
for the pages you actually want — including ones I never thought of.

## What you need

- **A Mac running Indigo 2025.2.** The plugin lives on it; the pages are served by Indigo's own
  web server.
- **A Claude subscription.** Claude Code — the version of Claude that can actually do things
  on your Mac — is **not on the free plan**. It is included in every paid plan (Pro is the
  cheapest, and it is what I would start with; what it costs is under "Things worth knowing"
  below) and it shares that plan's usage limits, so a long evening of building may hit the limit
  and ask you to wait a while. There is also a
  pay-as-you-go route through an Anthropic Console account with pre-paid credits.
  [Anthropic's pricing page](https://claude.com/pricing) has the current details.
- **Nothing else.** No MCP server, no Tailscale, no Homebrew, no camera tools. Claude installs
  each of those for you when you get to it.

## What "Claude Code" is, in one paragraph

The Claude you may know is a chat window. Claude Code is the same Claude with hands: it runs on
your Mac, it can read and write files, run commands, download things, install software and
check what happened. It asks before doing anything that matters, it shows you what it is about
to run, and it never needs your passwords — when something needs signing in, it opens the page
and waits for you. It comes as a Mac app (the Code tab in the Claude desktop app) and as a
terminal command; either is fine, and it does not matter which.

## Can I use Claude chat instead of Claude Code?

Partly, and it is worth knowing exactly where the line is, because the chat version is on the
free plan and Claude Code is not.

**Claude chat** — the claude.ai website or the Chat tab of the desktop app — can explain every
step on this page, write anything for you to paste, and answer questions about what a page is
showing. What it cannot do is touch your Mac: it cannot install the plugin, the camera tools, an
MCP server or Tailscale, it cannot read a log file, restart a plugin, or put a page into the
plugin. It hands you the commands and you type them, or double-click the bundle yourself.

**Claude chat with an MCP server** gets much further. The Claude desktop app can run an Indigo
MCP server as a local connector, and Anthropic's pricing page lists connectors as available on
every plan, the free one included (free accounts are limited to one custom connector). With one
connected, the chat can see your devices by name, read their states and the event log, run
actions, and use this plugin's own tools — set your rooms, add or remove cameras, run the setup
check, read the plugin's log. "The kitchen light" works from a chat window too. The desktop app
has to be on a Mac at home (or on your tailnet), because the server is on your network:
claude.ai's "custom connectors" connect from Anthropic's cloud and would need your Indigo MCP
server reachable from the internet, which none of the three is set up for and which you should
not want.

**Claude Code** is the one that acts. It installs things, edits and builds pages, restarts the
plugin, reads whatever it needs on the Mac, and checks what happened. Everything in "The path"
below that says *install* or *build* needs it.

| | Claude chat | Chat + an MCP server | Claude Code + an MCP server |
|---|---|---|---|
| Plan | Free upwards | Free upwards | Pro upwards |
| Runs where | anywhere | the desktop app, at home | on the Indigo Mac |
| Install the plugin, camera tools, Tailscale | tells you how | tells you how | does it |
| See devices by name, read logs | no | yes | yes |
| Change rooms and cameras | via the Settings page | yes, directly | yes |
| Build or change a page | writes it, you copy it in | the same | does it |
| Fix something in the plugin itself | no | no | yes |

So a free-plan reader with the desktop app and an MCP server can run the dashboards, keep the
rooms and cameras right, and get real help when something is wrong. Building your own pages is
where Claude Code earns its subscription.

## The path, step by step

You do not have to do all of this in one go. Each step is useful on its own.

### 1. Install Claude Code on the Indigo Mac

Download the Claude desktop app from [claude.com/claude-code](https://claude.com/claude-code),
sign in with your subscription, and open the Code tab. Point it at a folder — any folder — and
say hello. If it answers, you are done with the only step that needs you to install anything.

### 2. Ask it to install this plugin

> *"Install the Dashboards plugin for Indigo from github.com/Highsteads/Dashboards — get the
> latest release, and tell me what to click."*

It will download the release zip, unzip it, and hand you the bundle to double-click (Indigo
installs a plugin when you double-click it, and Claude will open the folder for you). Then it
will tell you the plugin needs an Indigo API key, and where that comes from: the
[Authorizations page of your Indigo account](https://www.indigodomo.com/account/authorizations).
You make the key, you paste it into **Plugins → Dashboards → Configure**. Then pair each device
you will use once: **Plugins → Dashboards → Generate One-Time Setup Link (+QR)** writes a link and a
QR code into the Indigo log; open the link, or point the phone's camera at the QR, and that device
is paired with nothing to type. (A browser that is not paired shows a Connect form that says the
same.) Open `http://<your-indigo-mac>:8176/public/dashboards/index.html` and there is your hub.

### 3. Tell it about your rooms

> *"My rooms are the device folders Kitchen, Hall, Lounge and Bedroom. Set the dashboards up to
> use those."*

Without an MCP server (next step) Claude walks you through the Settings page. With one, it does
it directly, and because it can see your folders it will find the right ones even if you have got
a name slightly wrong.

### 4. Give Claude eyes on Indigo — the MCP server

This is the step that changes everything, and it is the one that sounds most technical, so here
is what it actually means. Out of the box Claude Code can see files and run commands, but it
cannot see Indigo: it does not know you have a device called Kitchen Light, what state it is in,
or what your event log said at three this morning. An **MCP server** is a small plugin that
lets Claude ask Indigo those questions.

| | Claude Code alone | Claude Code with an Indigo MCP server |
|---|---|---|
| "Make the kitchen light a favourite on the hub" | You have to find the device's id number in Indigo and tell it | It finds the device itself, by name |
| "Why is the garden camera not streaming?" | It can read the plugin's log file | It can read the log, the event log, the camera device's state, and run the plugin's own setup check |
| "Which of my sensors have gone quiet?" | It cannot know | It asks Indigo |
| "Restart the plugin" | It tells you where the menu is | It does it |
| "Turn the landing light off" | It cannot | It can, if you let it |

There are three to choose from, and any of them will do. Ask Claude to read the README of the
one you pick and install it:

- [Claude Bridge](https://github.com/Highsteads/ClaudeBridge) — mine, and what these dashboards
  were built with.
- [mlamoure's Indigo MCP Server](https://github.com/mlamoure/indigo-mcp-server).
- Simon's MCP Lite, in [Simon's plugins](https://github.com/simons-plugins).

Each README says what it needs (Indigo version, Mac type, any keys). The prompt is the same
whichever you choose — put the GitHub address of the one you picked where the brackets are:

> *"Read the README at [GitHub address] and install that MCP server for me, then connect Claude
> Code to it."*

From v3.12.0 this plugin adds its own tools to whichever server you install, so Claude can also
check the dashboards' setup, list and change your rooms and cameras, and read the plugin's log
without you finding a single file. See [Claude Code and MCP tools](claude-code.md).

### 5. Cameras, if you have them

They need to be IP cameras: the kind with an address on your home network and a video stream of
its own, which is most Dahua, Hikvision, Reolink and Amcrest models and plenty of others. A
camera that only talks to its maker's cloud app will not do.

> *"Install ffmpeg and go2rtc with Homebrew so the camera grid works, then add my front door
> camera at 192.168.1.50 — it is a Dahua."*

It installs both, and (with an MCP server) adds the camera; without one it tells you which
fields to fill on the Settings page.

### 6. Reach it from anywhere — Tailscale

> *"Install Tailscale on this Mac and set it up so I can open the dashboards from my phone when
> I am out. Then tell me how to set up the iPhone."*

Ask the same for Android, Windows, Linux or a NAS; Tailscale runs on all of them. Claude
installs it on the Mac with Homebrew (`brew install --cask tailscale-app`), opens it for you to
sign in, and explains the phone side: install the Tailscale app, sign in with the same account,
leave it switched on. From then on your phone is "at home" wherever it is, and the cameras work
too — they only ever work remotely this way. I have checked on the house from Perth, Australia,
and at 36,000 feet over the Indian Ocean I could still watch the cameras, thanks to Tailscale.
If you want to keep using the same
address you use at home (mine is a `192.168.` address, yours will be different), ask Claude to
make the Mac a Tailscale **subnet router** for your home network; that is one setting, and the
[Remote access](remote-access.md) page explains the three ways of addressing the Mac.

### 7. Now make it yours

This is the part that matters. Everything above is the plumbing; this is why you did it.

> *"Add a page for the conservatory with its lights, the two window sensors and the
> temperature."*
>
> *"I do not have solar. Hide everything to do with energy."*
>
> *"The hub should show the garage door first, then the front door, then the cameras."*
>
> *"Make the whole thing blue instead of purple."*
>
> *"I want a page that shows the fish tank temperature and warns me if the filter stops."*
>
> *"The weather page is showing wind in miles an hour and I want kilometres."*

Say it, look at the result, and say what is wrong. That is the loop, and it is the same loop
this whole site came out of. You do not need to know what an endpoint is, and you will not be
asked.

## What Claude will ask you to do yourself

- Sign in to things — your Claude account, Tailscale, GitHub if it needs it. It opens the page;
  you type the password. It never wants a password in the chat.
- Paste your Indigo API key into Configure. Claude can tell you where the box is, and it can
  put the key into a settings file if you would rather, but it does not go and fetch it.
- Double-click the plugin bundle. Indigo installs plugins that way and only that way.
- Say yes. It shows you each command before it runs one that changes anything, and you can
  say no.

## Things worth knowing before you start

- **Keep Time Machine on.** Claude is careful, and it is still software changing your Mac.
- **A wrong result costs one more sentence.** If a page comes out wrong, say so and it tries
  again. You are not expected to get the ask right first time — I never did.
- **Claude makes mistakes.** I have not found it a problem. It keeps a copy of what it changes,
  it can put things back exactly as they were, and more often than not it simply repairs the
  error when you point at it.
- **What Pro costs, and what you get for it.** At the time of writing Pro is £18 a month billed
  monthly, or £15 a month if you pay a year up front, VAT included —
  [the pricing page](https://claude.com/pricing) has today's figure. You can cancel at any time
  during the month, so one month is enough to have Claude build your pages. Be warned: it is
  addictive. Ten months ago I had no plugins at all, mainly because I cannot write one. I now
  have 32, mostly for my own use and some private. The scripts I had for turning room lights on
  and off, and the pile of triggers that ran them, have been streamlined down to a single
  trigger, and my heating, which ran as three separate scripts, is now a plugin. I even get
  Claude to write my triggers and schedules: Indigo has no way for a program to create those,
  so the Claude desktop app drives the Indigo app itself to make them, and everything after
  that — changing them, switching them on and off, testing them, writing the scripts they run —
  goes through the MCP server.
- **Usage limits are real on the Pro plan.** A long building session can run into them; the app
  tells you when, and the work is still there when the limit resets.
- **The dashboards themselves never need Claude.** Once a page exists, it is a plain web page
  served by Indigo. Claude is how you build and change things, not how you use them.
