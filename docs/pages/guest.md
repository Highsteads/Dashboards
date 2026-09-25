---
title: Guest
parent: Every page
nav_order: 25
---

# Guest — `guest.html`

Open it on a device you want to be able to look but not touch. It pairs, then forwards to the hub
about a second later. The pairing URL is on the Settings page under Security, and **Plugins →
Dashboards → Show Guest Access Info** logs it too.

## What it shows

A single card, in one of three states, before the page forwards on:

- **Setting up guest access…** — a spinner while it pairs, which takes well under a second.
- **Guest access ready** — "This device can view the dashboards but control nothing." Then it
  forwards to the hub.
- **Pairing failed** — with the reason in brackets. Guest pairing works on the home network and
  Tailscale only.

## How it works

It fetches `guest-bootstrap` from the plugin's proxy on port 8177, with a four-second abort. On
success it stores the returned guest token in `localStorage` and removes any full API key that was
there — so a device that previously held the key is demoted rather than left holding both. The proxy
refuses any non-private source address, which is what makes guest access home-network and Tailscale
only by construction.

## What a guest device can do

View every page. Control nothing: the tiles render, the toggles do not act.

A guest device cannot switch anything: it holds no API key, so that is not a matter of the
interface politely hiding buttons. It is not a private view, though. It reads every device's name
and state through the plugin, which tells whoever holds it who is home, which doors and windows are
open and when the house is empty, and it sees the camera pictures. Indigo variables are hidden from
it unless you name them in `guestVariables` (Settings → Raw JSON; none by default, from 3.46.0). So
give a guest link to a device you would let watch the house, not to anyone passing through, and
withdraw it with **Plugins → Dashboards → Rotate Guest Link and Camera-Stills Folder**, which cuts
off every guest device at once.

A guest link only means something while *Auto-seed the API key to LAN browsers* is off (the default
for a new install from 3.46.0): with it on, any device on your network, a guest's included, can ask
the plugin for the full key instead.

## Worth knowing

- Pairing is per-browser. Clearing site data un-pairs the device and it will need the URL again.
- Rotating the guest link (the menu item above) un-pairs every guest device together; each needs
  the URL again, which is the same address, with a new token behind it.
- A wall tablet is the intended case. A visitor's phone on your Wi-Fi is the other.
