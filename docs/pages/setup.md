---
title: Setup
parent: Every page
nav_order: 24
---

# Setup — `setup.html`

The way a new browser gets its API key without anyone typing one. Generate a link from **Plugins →
Dashboards → Generate One-Time Setup Link (+QR)**, open it on the device, and this page stores the
key and forwards to the hub.

## What it shows

A single card. On a valid link it reads the token, stores the key and moves on. On an invalid or
spent link: **"Setup link not valid"**, with instructions to generate a fresh one, and a link to the
hub for entering the key by hand instead.

## How it works

The token is in the query string. The page fetches the token's file, takes the API key out of it,
stores the key, then calls `burnSetupToken` to delete the file so the link cannot be used again. The
burn authenticates with the key it has just received. It checks the plugin's liveness gate first; if
the plugin is restarting it skips the burn and waits, since an unredeemed link is swept by its own
time-to-live within ten minutes anyway.

## Worth knowing

- There is no screenshot of a successful redemption on purpose: a valid setup link is a working
  credential with a one-time life, and redeeming one to take the picture would also destroy it.
- The hub's own Connect form is the manual alternative, and the error card links straight to it.
- Auto-seeding (*Auto-seed the API key to LAN browsers* under Configure) makes this page unnecessary
  for a browser on the home network or the tailnet.
