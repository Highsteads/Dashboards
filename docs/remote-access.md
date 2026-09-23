---
title: Remote access
nav_order: 8
---

# Remote access

## Run Tailscale

Away from home, the way to use the dashboards is [Tailscale](https://tailscale.com) — a zero-config
WireGuard VPN whose free tier comfortably covers a family's devices. With it running, your phone or
laptop is effectively "at home" anywhere in the world, and the plugin already treats it that way:
the private-client gate on port 8177 accepts Tailscale's `100.64.0.0/10` range alongside the LAN.

Why this plugin needs it:

- **Live cameras only work remotely this way.** WebRTC is set up on port 8177 and streams on 8555,
  which nothing else fronts — without Tailscale you get every data page and the stills but no live
  video; over Tailscale the tile at the top of the Cameras page goes live.
- **No pairing ceremony.** A new browser on the tailnet auto-pairs on first visit, exactly as at
  home. Any other way in, you would need a one-time setup link or to type the API key.
- **Nothing exposed.** No port forwarding, no public attack surface, WireGuard encryption end to
  end.

Setup:

1. Install Tailscale on the **Indigo Mac**, sign in once, and tick "start on login" — it just sits
   in the menu bar.
2. Install the Tailscale app on the **iPhone / iPad / MacBook**, signed into the same tailnet, and
   enable **MagicDNS** in the admin console.
3. Bookmark the dashboard by one of the three addresses below — that one URL then works
   identically on the sofa and on holiday.
4. On the phone, leave the VPN toggle **on**. WireGuard is idle when unused, so the battery cost is
   negligible — and toggling it on demand is noticeably slow, so always-on is both simpler and
   faster.

Claude Code can do the Mac side for you: *"install Tailscale on this Mac and set it up so I can
open the dashboards from my phone"* — it installs it with Homebrew (`brew install --cask
tailscale-app`), opens it for you to sign in, and tells you what to do on the phone. See
[Start with nothing but Claude](no-coding-needed.md).

### Three ways to address the Mac over Tailscale

- **Its tailnet name**, with MagicDNS on: `http://your-mac-name:8176/public/dashboards/`. The
  simplest, and it never changes.
- **Its Tailscale address**, the `100.x.y.z` one shown in the Tailscale menu. Works without
  MagicDNS.
- **Its ordinary home address — the same `192.168.` address you use on the sofa** (mine is one,
  yours will be a different one) — **if a device on your tailnet advertises your home network as a
  subnet route.** The Indigo Mac can do that itself: Tailscale calls it a subnet router, it is one
  setting (`tailscale set --advertise-routes=<your LAN>/24`, then approve the route in the admin
  console), and Tailscale's guide covers it for macOS. With that in place a bookmark to
  `http://192.168.1.10:8176/public/dashboards/` works on holiday exactly as it does at home, which
  is how this house runs: one address for everything, and no re-pairing when a phone leaves the
  Wi-Fi. The plugin treats any Tailscale source as private either way.

## The Indigo reflector

The pages work over the Indigo reflector (`https://myhouse.indigodomo.net/...`), and my advice is
not to use it: install Tailscale and leave the reflector out of it. Here is why.

**It is metered, and cameras are what spend it.** The reflector relays every byte through Indigo
Domotics' own servers, and they pay their hosting company for it. A Cameras page polling stills
every second is the single easiest way to run through the allowance — about 8 GB a day if left
open — and it does not have to be a phone on mobile data doing it. I found out the hard way: two
emails from Indigo Domotics in a week, the first asking me to look, the second telling me the
reflector was using twice their limit and had been switched off at their end, with the
subscription itself next if that did not stop it. The culprits were one phone on mobile data and
one sitting on my own Wi-Fi that had been paired with the reflector address, so every picture went
out to their servers and back. Neither looked remote to me.

**What the plugin does about it.** A page that can see it was reached through the reflector polls
at a tenth of the home rate, stops altogether after ten minutes untouched, and shows a banner with
the LAN link. The plugin notes each device that arrives over the reflector, once an hour, in its
log, naming the device and the LAN address it should use instead. And **Refuse the reflector**
under Configure turns it away entirely: every page then stops before asking for anything and shows
the LAN address instead. It is off by default, because plenty of installs have no other way in,
and it should go on the day you have Tailscale — which is how this house runs now, with the
reflector switched off in Indigo as well.

**"Remote" can be your own house.** A phone that was paired with the reflector address while
sitting on the home Wi-Fi goes out to Indigo's servers and back for every request, and looks
remote to everyone. Pair with the LAN or Tailscale address. If you must keep a reflector link,
keep it for a device that is genuinely away, and close the page when you have finished with it.

## Guest devices

A wall tablet or a visitor's phone should be able to look and not touch. **Plugins → Dashboards →
Show Guest Access Info** logs a pairing URL; open it on the device and `guest.html` takes a guest
token from the plugin's LAN-only proxy, stores it, and forwards to the hub. The device never holds
the API key, so there is no control surface on it at all. That proxy refuses any non-private source
address, which makes guest access home-network and Tailscale only by construction. Clearing the
browser's site data un-pairs it.

## Ports

| Port | Purpose | Auth |
|---|---|---|
| 8176 | Indigo Web Server — the pages are served here | None for the pages; API key for every data call |
| 8177 | Plugin server — WebRTC set-up, pairing | None (trusted LAN / Tailscale; refuses non-private sources) |
| 1984 | go2rtc HTTP API | Loopback only |
| 8554 | go2rtc RTSP republish | Loopback only |
| 8555 | go2rtc WebRTC media (TCP and UDP) | None |

The proxy and go2rtc ports are intentionally unauthenticated — the same trusted-LAN / Tailscale
threat model as Indigo's `/public/` namespace. Do not expose port 8177 directly to the internet, and
do not put a credential into anything under `/public/`: that namespace is anonymous even over the
reflector.
