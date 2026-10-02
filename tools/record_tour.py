#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    record_tour.py
# Description: Record a narrated video tour of the live dashboards for the docs
#              site, through the same sanitising proxy as capture_screenshots.py.
# Author:      CliveS & Claude Opus 5.5; Claude Sonnet 5.5 (2.1)
# Date:        02-10-2026
# Version:     2.1 (Kokoro neural voice; set --voice kokoro:bm_george)
#              2.0 (presses, drags, a drawn pointer, zooms, section labels,
#              title and end cards, energy narration from live readings, and a
#              rehearsal mode that sends nothing to the house)
#              1.0 (27-09-2026: narrated scroll-through)
#
# WHAT IT DOES
# Reads a tour script (tools/tour.json): segments, each a page or a title card,
# each made of "beats" — a sentence and the things done while it is spoken
# (scroll, point, press, drag a slider, zoom in, check a tile's text). Then:
#
#   1. reads the live energy figures off the hub, so the energy sentences say
#      what the house is actually doing while it is filmed;
#   2. speaks every beat with macOS `say` and lays the whole film out on one
#      clock, so picture and voice cannot drift apart;
#   3. drives a headless Chrome over the DevTools protocol in REAL time,
#      through the sanitising proxy, and records Chrome's own screencast;
#   4. composites the frames at 30 fps — zooms are crops of the 1.5x-scale
#      frames, so text stays sharp up to 1.5x — and writes an MP4, WebVTT
#      captions and a poster.
#
# REHEARSAL IS THE DEFAULT. Every press really happens in the page, but the
# proxy refuses every command on its way to Indigo and logs it, so a rehearsal
# proves each press hit the device it was meant for while nothing in the house
# moves. --live lets commands through, and then ONLY for the device and action
# group ids listed in the tour's "allow" — anything else is refused, so a
# mis-aimed press cannot unlock a door. --live also checks the house is in the
# starting state the script assumes before it begins.
#
#   python3 tools/record_tour.py --host 192.168.1.10 --rename Alice=Alex
#   python3 tools/record_tour.py --host 192.168.1.10 --live --out docs/video
#   python3 tools/record_tour.py --scout index.html energy.html
#
# The recording is only as clean as the proxy: the run refuses to write the
# video if the proxy's residue check found anything. Look at the frames (an
# OCR pass is quickest) before publishing.

import argparse
import asyncio
import base64
import bisect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_screenshots as cs                   # noqa: E402  (the proxy)

try:
    from websockets.asyncio.client import connect
except ImportError:                                # checked in main(), so the
    connect = None                                 # tests can import without it

FPS          = 30
LEAD_IN      = 0.8                                 # seconds before the first beat
BEAT_GAP     = 0.45                                # silence between beats
TAIL         = 0.9                                 # after the last beat of a segment
SCROLL_MS    = 1400                                # one eased scroll
SCROLL_EARLY = 0.25                                # actions start this far ahead of speech
FADE         = 0.35                                # dip at every cut
ZOOM_RAMP    = 0.7                                 # seconds to ease into / out of a zoom
BG           = (243, 244, 246)                     # the pages' own background: cuts dip to it
DEBUG_PORT   = 9335
ACCENT       = "#5856d6"                           # dashboards-theme.css --accent

# Requests that change something in the house. Everything the pages POST to
# read data is listed; anything else posted to /message/ counts as a command,
# so a new write endpoint is refused in a rehearsal rather than let through.
READ_MESSAGES = {
    "changedSince", "historyQuery", "sigenApi", "laundryPlan", "activityFeed",
    "watchCameras", "solarStringHours", "cameraStills", "timelineDay",
    "systemHealth", "presenceData", "mainsMeters", "logErrors", "carbonAdvisor",
    "alertRules", "getDashboardsConfig", "homeInsights",
}
MESSAGE_RE = re.compile(r"^/message/[^/]+/([A-Za-z0-9_]+)/?$")


# ------------------------------------------------------------ the page script

# Injected into every page once it has settled. find()/el() take what a viewer
# can read, not class names alone, so a script survives a redesign; the
# pointer and the label are drawn above the page with pointer-events off, so
# the real clicks land on the real controls underneath them.
TOUR_JS = r"""
(() => {
const norm = x => String(x || '').replace(/[‘’]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase();
const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
const T = window.__tour = window.__tour || {};
T.find = function (t) {
  const want = norm(t);
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const s = norm(n.textContent);
    if (!s || !s.startsWith(want)) continue;
    const el = n.parentElement;
    if (visible(el) && getComputedStyle(el).visibility !== 'hidden') return el;
  }
  return null;
};
T.el = function (spec) {
  if (spec == null) return null;
  if (typeof spec === 'string') return T.find(spec);
  let scope = document;
  if (spec.within) { scope = T.el(spec.within); if (!scope) return null; }
  let list = [...scope.querySelectorAll(spec.sel || '*')].filter(visible);
  if (spec.title != null) list = list.filter(e => (e.title || e.getAttribute('aria-label') || '') === spec.title);
  if (spec.has != null) { const h = norm(spec.has); list = list.filter(e => norm(e.innerText || e.textContent).includes(h)); }
  return list[spec.nth || 0] || null;
};
T.rect = function (spec) {
  const e = T.el(spec);
  if (!e) return null;
  const r = e.getBoundingClientRect();
  return {x: r.x, y: r.y, w: r.width, h: r.height, text: norm(e.innerText || e.textContent || e.value)};
};
T.checked = function (spec) {
  const e = T.el(spec);
  if (!e) return null;
  const box = e.matches('input') ? e : e.querySelector('input');
  return box ? !!box.checked : null;
};
T.go = function (target, ms, offset) {
  let y;
  if (typeof target === 'number') y = target;
  else if (target === 'top') y = 0;
  else if (target === 'bottom') y = 1e9;
  else { const e = T.el(target); if (!e) return Promise.resolve('missing: ' + JSON.stringify(target)); y = e.getBoundingClientRect().top + scrollY; }
  const max = document.documentElement.scrollHeight - innerHeight;
  y = Math.max(0, Math.min(y - (offset == null ? 90 : offset), max));
  const from = scrollY, t0 = performance.now();
  return new Promise(res => {
    const step = now => {
      const p = ms <= 1 ? 1 : Math.min(1, (now - t0) / ms);
      const k = p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      scrollTo(0, from + (y - from) * k);
      if (p < 1) requestAnimationFrame(step); else res('ok');
    };
    requestAnimationFrame(step);
  });
};
T.headings = function () {
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.children.length) return;
    const s = el.textContent.replace(/\s+/g, ' ').trim();
    if (!s || s.length > 48) return;
    const cs = getComputedStyle(el);
    const head = /^H[1-4]$/.test(el.tagName) || cs.textTransform === 'uppercase';
    const r = el.getBoundingClientRect();
    if (head && r.height > 0) out.push([Math.round(r.top + scrollY), s]);
  });
  return {height: document.documentElement.scrollHeight, headings: out};
};
T.overlay = function (x, y, shown) {
  if (!document.getElementById('__tp')) {
    const st = document.createElement('style');
    st.textContent = `
      #__tp{position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;
            transition:opacity .35s;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));will-change:transform}
      .__tr{position:fixed;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;z-index:2147483646;
            pointer-events:none;border:3px solid ${'__ACCENT__'};background:rgba(88,86,214,.18);
            animation:__tr .65s ease-out forwards}
      @keyframes __tr{from{transform:scale(.3);opacity:1}to{transform:scale(1.7);opacity:0}}
      #__tl{position:fixed;left:28px;bottom:28px;z-index:2147483645;pointer-events:none;display:flex;align-items:center;
            gap:10px;padding:11px 18px 11px 14px;border-radius:14px;background:rgba(17,20,28,.84);color:#fff;
            font:600 18px/1.2 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;letter-spacing:.01em;
            box-shadow:0 8px 24px rgba(0,0,0,.18);opacity:0;transform:translateY(14px);
            transition:opacity .45s ease,transform .45s ease}
      #__tl.on{opacity:1;transform:none}
      #__tl i{width:10px;height:10px;border-radius:50%;background:${'__ACCENT__'};box-shadow:0 0 0 4px rgba(88,86,214,.35)}`;
    document.documentElement.appendChild(st);
    const p = document.createElement('div');
    p.id = '__tp';
    p.innerHTML = '<svg viewBox="0 0 30 30" width="30" height="30"><path d="M3 2 L3 24 L9 18.5 L13 27.5 L17 25.8 L13.2 17 L21 17 Z" fill="#111" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(p);
  }
  T.px = x; T.py = y;
  const p = document.getElementById('__tp');
  p.style.transform = `translate(${x - 3}px, ${y - 2}px)`;
  p.style.opacity = shown ? '1' : '0';
  return 'ok';
};
T.show = function () { document.getElementById('__tp').style.opacity = '1'; return 'ok'; };
T.moveTo = function (x, y, ms) {
  const p = document.getElementById('__tp');
  p.style.opacity = '1';
  const fx = T.px, fy = T.py, t0 = performance.now();
  return new Promise(res => {
    const step = now => {
      const q = ms <= 1 ? 1 : Math.min(1, (now - t0) / ms);
      const k = q < .5 ? 4 * q * q * q : 1 - Math.pow(-2 * q + 2, 3) / 2;
      T.px = fx + (x - fx) * k; T.py = fy + (y - fy) * k;
      p.style.transform = `translate(${T.px - 3}px, ${T.py - 2}px)`;
      if (q < 1) requestAnimationFrame(step); else res('ok');
    };
    requestAnimationFrame(step);
  });
};
T.jump = function (x, y) { T.px = x; T.py = y; document.getElementById('__tp').style.transform = `translate(${x - 3}px, ${y - 2}px)`; return 'ok'; };
T.ripple = function (x, y) {
  const r = document.createElement('div');
  r.className = '__tr'; r.style.left = x + 'px'; r.style.top = y + 'px';
  document.documentElement.appendChild(r);
  setTimeout(() => r.remove(), 800);
  return 'ok';
};
T.label = function (text, ms) {
  let l = document.getElementById('__tl');
  if (!l) { l = document.createElement('div'); l.id = '__tl'; document.documentElement.appendChild(l); }
  l.innerHTML = '<i></i>';
  l.appendChild(document.createTextNode(text));
  requestAnimationFrame(() => l.classList.add('on'));
  clearTimeout(T._lt);
  T._lt = setTimeout(() => l.classList.remove('on'), ms || 3200);
  return 'ok';
};
return 'ready';
})()
""".replace("${'__ACCENT__'}", ACCENT)


def _icon_uri():
    """The plugin's own app icon, inlined: a data: page cannot be relied on to
    fetch anything, and a broken-image square on a title card is worse than
    no icon."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "Dashboards.indigoPlugin", "Contents", "Resources", "static",
                        "pages", "apple-touch-icon.png")
    try:
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    except OSError:
        return ""


ICON_URI = _icon_uri()


def card_html(card, icon_url):
    """A title or end card, drawn in the dashboards' own colours and type."""
    esc = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
                     .replace(">", "&gt;"))
    chips = "".join(f'<span class="chip" style="animation-delay:{0.5 + i * 0.12:.2f}s">'
                    f'{esc(c)}</span>' for i, c in enumerate(card.get("chips", [])))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%}}
body{{display:flex;align-items:center;justify-content:center;color:#1d2129;
  font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;
  background:radial-gradient(1100px 620px at 28% 18%,#e9e8ff 0%,rgba(233,232,255,0) 60%),
             radial-gradient(900px 600px at 82% 88%,#e2f3ea 0%,rgba(226,243,234,0) 55%),#f3f4f6}}
.wrap{{text-align:center;max-width:1000px;padding:0 48px}}
.wrap>*{{animation:up .8s cubic-bezier(.2,.7,.2,1) both}}
img{{width:92px;height:92px;border-radius:22px;box-shadow:0 10px 30px rgba(88,86,214,.25);margin-bottom:26px}}
.kicker{{font-size:15px;letter-spacing:.2em;text-transform:uppercase;color:{ACCENT};font-weight:700;
  margin-bottom:14px;animation-delay:.1s}}
h1{{font-size:66px;line-height:1.05;margin:0 0 20px;font-weight:750;letter-spacing:-.025em;animation-delay:.18s}}
p{{font-size:25px;line-height:1.45;color:#4d535e;margin:0 auto;max-width:860px;animation-delay:.28s}}
.chips{{margin-top:30px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;animation:none}}
.chip{{padding:9px 16px;border-radius:999px;background:#fff;border:1px solid #e1e3ea;font-size:16px;
  font-weight:600;color:#3a3f48;box-shadow:0 1px 3px rgba(0,0,0,.05);animation:up .6s ease both}}
.foot{{margin-top:34px;font-size:18px;color:#7c828d;animation-delay:.45s}}
.foot b{{color:{ACCENT};font-weight:650}}
@keyframes up{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
</style></head><body><div class="wrap">
{f'<img src="{icon_url}" alt="">' if icon_url else ''}
<div class="kicker">{esc(card.get("kicker", ""))}</div>
<h1>{esc(card.get("title", ""))}</h1>
<p>{esc(card.get("subtitle", ""))}</p>
{f'<div class="chips">{chips}</div>' if chips else ''}
{f'<div class="foot">{card["foot"]}</div>' if card.get("foot") else ''}
</div></body></html>"""


# ------------------------------------------------------------ live energy words

_NUM = r"([\d.,]+)\s*(kW|W)\b"


def _kw(num, unit):
    v = float(num.replace(",", ""))
    return v / 1000.0 if unit == "W" else v


def read_energy(text):
    """The hub's Energy card, as the page shows it, into numbers."""
    t = " ".join(text.split())
    out = {}
    m = re.search(r"SOLAR\s+" + _NUM, t, re.I)
    if m:
        out["solar"] = _kw(*m.groups())
    m = re.search(r"HOME\s+" + _NUM, t, re.I)
    if m:
        out["home"] = _kw(*m.groups())
    m = re.search(r"GRID\s+" + _NUM + r"\s+(\w+)", t, re.I)
    if m:
        out["grid"] = _kw(m.group(1), m.group(2))
        out["grid_mode"] = m.group(3).lower()
    m = re.search(r"BATTERY\s+" + _NUM + r"\s+([\d.]+)%", t, re.I)
    if m:
        out["battery"] = _kw(m.group(1), m.group(2))
        out["battery_pct"] = float(m.group(3))
    m = re.search(r"Self-sufficien(?:t|cy)\s+([\d.]+)%", t, re.I)
    if m:
        out["self_sufficiency"] = float(m.group(1))
    out["grid_charged"] = "grid charged the battery" in t.lower()
    return out


def _agree(a, b):
    """Two readings close enough to call the page steady."""
    keys = ("solar", "home", "battery", "battery_pct")
    if not all(k in a and k in b for k in keys):
        return False
    return all(abs(a[k] - b[k]) <= max(0.25 * max(abs(a[k]), abs(b[k])), 0.15) for k in keys)


async def steady_energy(cdp, tries=10, gap=1.5):
    """Read the energy figures until two readings in a row agree.

    A page that has just loaded shows cached figures, then fresh ones a few
    seconds later: one take read 2 kW and a house using 0 W, and the page
    showed 5.3 kW moments after. Returns {} when it never settles, which
    energy_words turns into a sentence with no figures in it.
    """
    last = None
    for _ in range(tries):
        text = await cdp.js("document.body.innerText.slice(0, 6000)") or ""
        now = read_energy(text)
        if last is not None and _agree(last, now) and now.get("home", 0) >= 0.05:
            return now
        last = now
        await asyncio.sleep(gap)
    return {}


def energy_words(e):
    """Sentences for what the energy system is doing right now.

    Only states what the readings show. The battery's direction is worked
    out from the balance (solar less the house, plus imports, less exports),
    because the hub shows the battery's power without a sign.
    """
    need = ("solar", "home", "grid", "grid_mode", "battery", "battery_pct")
    # A house never uses nothing: 0 W for home is a page caught mid-update
    # (a take once said "the house needs only 0 watts"), so say no figures.
    if not all(k in e for k in need) or e["home"] < 0.05:
        return {"energy_now": "The dots show which way the power is flowing right now, and how much."}
    # Half up, as a person rounds: Python's round() makes 54.5% "54".
    s, h, g, b, pct = e["solar"], e["home"], e["grid"], e["battery"], int(e["battery_pct"] + 0.5)
    exporting = e["grid_mode"].startswith("export") and g > 0.1
    importing = e["grid_mode"].startswith("import") and g > 0.1
    net = s - h + (g if importing else 0) - (g if exporting else 0)
    # Relations, not kilowatts: a cloud moved the solar from 7.6 to 5.2 kW
    # while one sentence was being said, and the screen shows the live
    # figures anyway. The battery's percentage moves slowly enough to name.
    much = "far more than" if s >= 2 * h else "more than"
    if s >= 0.3 and net > 0.15 and b > 0.1:
        if exporting:
            now = (f"Right now the sun is making {much} the house needs, so the spare is charging "
                   f"the battery, at {pct} percent, and the rest is being sold to the grid.")
        else:
            now = (f"Right now the sun is making {much} the house needs, so the spare is charging "
                   f"the battery, which is {pct} percent full.")
    elif s >= 0.3 and exporting:
        now = (f"Right now the sun is making {much} the house needs, and with the battery at "
               f"{pct} percent, the spare is being sold to the grid.")
    elif s >= 0.3 and net > -0.15:
        now = (f"Right now the sun is running the house on its own, "
               f"with the battery at {pct} percent.")
    elif s >= 0.3:
        now = (f"Right now the sun is not quite covering what the house needs, so the battery "
               f"is making up the difference, from {pct} percent.")
    elif b > 0.1 and exporting:
        now = (f"The sun has gone for the day, so the battery is powering the house, "
               f"from {pct} percent, and selling the spare to the grid.")
    elif b > 0.1 and not importing:
        now = (f"The sun has gone for the day, so the battery is running the house on its own, "
               f"from {pct} percent.")
    else:
        now = "The dots show which way the power is flowing right now, and how much."
    words = {"energy_now": now}
    if "self_sufficiency" in e:
        ss = int(e["self_sufficiency"] + 0.5)
        words["self_sufficiency"] = (f"how self-sufficient the house has been today, {ss} percent so far"
                                     + (", with a note when an overnight cheap-rate charge is why it"
                                        " reads low" if e.get("grid_charged") else ""))
    else:
        words["self_sufficiency"] = "how self-sufficient the house has been today"
    return words


# --------------------------------------------------------------------- speech

KOKORO_DIR = os.path.expanduser("~/.local/share/kokoro-tts")
KOKORO_PY = os.path.join(KOKORO_DIR, "venv", "bin", "python")
NORMAL_RATE = 178                                  # words a minute `say` speaks at: speed 1.0


def kokoro_installed():
    return os.path.exists(KOKORO_PY) and os.path.exists(os.path.join(KOKORO_DIR, "speak.py"))


def kokoro_speed(rate):
    """Kokoro's speed for a `say`-style words-a-minute rate, kept to its sane range."""
    return round(max(0.7, min(1.4, rate / NORMAL_RATE)), 3)


def speak(text, path, voice, rate):
    """Speak one line to `path`: with Kokoro for "kokoro:<voice>", else macOS say."""
    if voice.startswith("kokoro:"):
        subprocess.run([KOKORO_PY, os.path.join(KOKORO_DIR, "speak.py"),
                        voice.split(":", 1)[1], str(kokoro_speed(rate)), path, text],
                       check=True)
    else:
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", path, text],
                       check=True)
    return media_duration(path)


def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def plan(tour, work, voice, rate, words=None):
    """Speak every beat and lay the whole film out on one clock.

    A beat lasts as long as its sentence, or its "hold" if that is longer —
    a door takes eleven seconds whatever is being said over it. A beat with
    nothing to say is just its hold.
    """
    words = words or {}
    t = 0.0
    segments = []
    for si, seg in enumerate(tour["segments"]):
        beats = []
        local = seg.get("lead_in", LEAD_IN)
        for bi, beat in enumerate(seg["beats"]):
            text = beat.get("say", "").format(**words) if beat.get("say") else ""
            dur, wav = 0.0, None
            if text:
                wav = os.path.join(work, f"s{si:02d}b{bi:02d}.aiff")
                dur = speak(text, wav, voice, rate)
            span = max(dur, float(beat.get("hold", 0)))
            beats.append({**beat, "say": text, "template": beat.get("say", ""),
                          "audio": wav, "start": local, "dur": dur, "span": span})
            local += span + (BEAT_GAP if text else 0)
        last = beats[-1] if beats else None
        length = (local - (BEAT_GAP if last and last["say"] else 0)
                  + seg.get("tail", TAIL))
        segments.append({**seg, "beats": beats, "offset": t, "length": length,
                         "zooms": [], "cut": None})
        t += length
    return segments, t


def respeak(seg, words, voice, rate, work):
    """Rewrite a segment's live lines from fresh readings, inside their slots.

    The figures are read again on the page itself just before it is filmed:
    read at the start, a sentence said 1.7 kilowatts over a picture showing
    5.7, because the sun came out in between. Each slot keeps its planned
    length; a sentence that no longer fits is spoken a little faster.
    """
    changed = []
    for bi, beat in enumerate(seg["beats"]):
        template = beat.get("template", "")
        if "{" not in template:
            continue
        text = template.format(**words)
        if text == beat["say"]:
            continue
        wav = os.path.join(work, f"live-{id(seg)}-{bi}.aiff")
        dur = speak(text, wav, voice, rate)
        if dur > beat["span"]:
            dur = speak(text, wav, voice, min(260, int(rate * dur / beat["span"] * 1.04) + 1))
        if dur > beat["span"] + 0.3:
            changed.append(f"a live line runs {dur - beat['span']:.1f}s over its slot")
        beat.update(say=text, audio=wav, dur=dur)
    return changed


# ------------------------------------------------------------------- the proxy

class Guard:
    """Decides, for every POST the pages make, whether it may reach Indigo."""

    def __init__(self, live, allow_ids=(), allow_messages=()):
        self.live = live
        self.allow_ids = {int(i) for i in allow_ids}
        self.allow_messages = set(allow_messages)
        self.log = []                              # (time, description, let through)

    def check(self, path, body):
        """(is it a command, may it through, a description)."""
        path = path.split("?")[0]
        if path.rstrip("/") == "/v2/api/command":
            try:
                cmd = json.loads(body or b"{}")
            except ValueError:
                cmd = {}
            desc = f"{cmd.get('message')} {cmd.get('objectId')} {cmd.get('parameters') or ''}".strip()
            ok = self.live and _as_int(cmd.get("objectId")) in self.allow_ids
            return True, ok, desc
        m = MESSAGE_RE.match(path)
        if m and m.group(1) not in READ_MESSAGES:
            name = m.group(1)
            return True, self.live and name in self.allow_messages, f"message {name}"
        return False, True, ""


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def serve_guarded(port, upstream, sanitiser, lock, api_key, leaks, scheme, guard):
    Base = cs.make_handler(upstream, sanitiser, lock, api_key, None, leaks,
                           True, True, scheme)

    class Guarded(Base):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            is_cmd, ok, desc = guard.check(self.path, body)
            if is_cmd:
                guard.log.append((time.time(), desc, ok))
            if is_cmd and not ok:
                # 409, not 403: a 401/403 is the pages' cue to drop their key.
                reply = b'{"error": "refused by the tour recorder"}'
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)
                return
            self.rfile = io.BytesIO(body)
            self._relay("POST")

    srv = cs.Threaded(("127.0.0.1", port), Guarded)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def serve_signalling(port, upstream, sanitiser, page_origin):
    """Carry the cameras' live-video handshake, and nothing else.

    The hub and Cameras page post a WebRTC offer to the plugin's camera proxy
    on :8177, built from the page's own hostname — here 127.0.0.1, where
    nothing would answer, so every tile fell back to stills under a "live
    video stopped" note. This answers there and forwards /webrtc/ only.

    The camera address in the path is the FAKE one the page was given, so it
    is swapped back on the way out, as capture_screenshots does for stills.
    The answer is relayed UNscrubbed on purpose: it carries the addresses the
    browser must connect to for the video, and rewriting them would break the
    stream. It is read by the WebRTC stack, never drawn on the page, so it
    cannot reach a frame. Everything else on this port is refused.
    """
    import http.server

    class Relay(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _relay(self, method):
            if not self.path.startswith("/webrtc/"):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length) if length else None
            req = urllib.request.Request(upstream + sanitiser.unscrub_path(self.path),
                                         data=payload, method=method)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "connection", "accept-encoding", "origin"):
                    req.add_header(k, v)
            # The plugin echoes CORS only to a page served from its own host,
            # so it is told the page came from there, and the browser is then
            # answered for the origin it really has.
            req.add_header("Origin", page_origin)
            browser_origin = self.headers.get("Origin", "")
            try:
                with urllib.request.urlopen(req, timeout=20) as res:
                    body, status, headers = res.read(), res.status, dict(res.headers)
            except urllib.error.HTTPError as e:
                body, status, headers = e.read(), e.code, dict(e.headers)
            except Exception as e:
                body, status, headers = str(e).encode(), 502, {}
            self.send_response(status)
            for k, v in headers.items():
                if k.lower() not in ("content-length", "transfer-encoding",
                                     "content-encoding", "connection",
                                     "access-control-allow-origin", "vary"):
                    self.send_header(k, v)
            if browser_origin:
                self.send_header("Access-Control-Allow-Origin", browser_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._relay("GET")

        def do_POST(self):
            self._relay("POST")

        def do_OPTIONS(self):
            self._relay("OPTIONS")

        def do_PATCH(self):
            self._relay("PATCH")

        def do_DELETE(self):
            self._relay("DELETE")

    srv = cs.Threaded(("127.0.0.1", port), Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ recording

class Chrome:
    def __init__(self, width, height, profile):
        self.proc = subprocess.Popen(
            [cs.CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--mute-audio", f"--user-data-dir={profile}",
             f"--remote-debugging-port={DEBUG_PORT}",
             f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def page_ws(self):
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2) as r:
                    for p in json.load(r):
                        if p.get("type") == "page":
                            return p["webSocketDebuggerUrl"]
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("headless Chrome never offered a page")

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending = {}
        self.events = {}

    async def pump(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m)
            elif "method" in m and m["method"] in self.events:
                self.events[m["method"]](m.get("params", {}))

    async def send(self, method, timeout=30, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method,
                                       "params": params}))
        m = await asyncio.wait_for(fut, timeout)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def js(self, expr, timeout=30):
        r = await self.send("Runtime.evaluate", timeout=timeout, expression=expr,
                            awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"page script failed: {r['exceptionDetails']}")
        return r.get("result", {}).get("value")


class Recorder:
    """Keeps every screencast frame with the time Chrome CAPTURED it.

    The arrival time is no good: on a heavy page the frames can queue behind
    the acknowledgements. Chrome's own timestamp is wall-clock seconds, the
    clock the beats run on.

    Chrome only sends a frame when something on screen changes, so a still
    page sends nothing at all; take() therefore starts every clip with the
    newest frame from before it, which is what the screen showed at t=0.
    """

    def __init__(self, cdp, frames_dir):
        self.cdp = cdp
        self.dir = frames_dir
        self.all = []
        self.count = 0
        self.lag = []
        cdp.events["Page.screencastFrame"] = self._frame

    def _frame(self, p):
        asyncio.get_running_loop().create_task(
            self.cdp.send("Page.screencastFrameAck", sessionId=p["sessionId"]))
        self.count += 1
        path = os.path.join(self.dir, f"f{self.count:06d}.jpg")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(p["data"]))
        stamp = p.get("metadata", {}).get("timestamp") or time.time()
        self.lag.append(time.time() - stamp)
        self.all.append((stamp, path))

    def take(self, t0, t1):
        """The clip from t0 to t1, as (seconds from t0, path) pairs."""
        before = [f for f in self.all if f[0] <= t0]
        inside = [f for f in self.all if t0 < f[0] < t1]
        clip = ([(t0, before[-1][1])] if before else []) + inside
        keep = {p for _, p in clip}
        for stamp, path in self.all:
            if stamp < t1 and path not in keep:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.all = [f for f in self.all if f[0] >= t1]
        return [(stamp - t0, path) for stamp, path in clip]


class Director:
    """Carries out a segment's actions in the page, on the film's clock."""

    def __init__(self, cdp, args, problems):
        self.cdp = cdp
        self.args = args
        self.problems = problems
        self.pointer = (args.width * 0.62, args.height * 0.62)
        self.pointer_shown = False

    async def inject(self):
        await self.cdp.js(TOUR_JS)
        x, y = self.pointer
        await self.cdp.js(f"__tour.overlay({x}, {y}, {json.dumps(self.pointer_shown)})")

    async def rect(self, spec, where):
        r = await self.cdp.js(f"__tour.rect({json.dumps(spec)})")
        if not r:
            self.problems.append(f"{where}: nothing matches {json.dumps(spec)}")
        return r

    async def move(self, x, y, ms=650):
        self.pointer_shown = True
        await self.cdp.js(f"__tour.moveTo({x}, {y}, {ms})")
        self.pointer = (x, y)

    async def click(self, x, y, ripple=True):
        if ripple:
            await self.cdp.js(f"__tour.ripple({x}, {y})")
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.cdp.send("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                                button="left" if kind != "mouseMoved" else "none",
                                clickCount=1 if kind != "mouseMoved" else 0)

    async def run(self, seg, action, t0, where):
        """One action. Returns True when it navigated away."""
        kind, rest = action[0], action[1:]
        if kind == "scroll":
            offset = rest[1] if len(rest) > 1 else None
            r = await self.cdp.js(f"__tour.go({json.dumps(rest[0])}, {SCROLL_MS}, {json.dumps(offset)})")
            if r != "ok":
                self.problems.append(f"{where}: {r}")
        elif kind in ("point", "press"):
            opts = rest[1] if len(rest) > 1 else {}
            r = await self.rect(rest[0], where)
            if not r:
                return False
            x = r["x"] + r["w"] * opts.get("fx", 0.5)
            y = r["y"] + r["h"] * opts.get("fy", 0.5)
            await self.move(x, y, opts.get("ms", 650))
            if kind == "press":
                await asyncio.sleep(0.12)
                if opts.get("nav"):
                    # Freeze BEFORE the click: a frame taken after it may
                    # already show the next page half drawn.
                    await self.cdp.js(f"__tour.ripple({x}, {y})")
                    await asyncio.sleep(0.3)
                    seg["cut"] = time.time() - t0
                    await self.click(x, y, ripple=False)
                    return True
                await self.click(x, y)
        elif kind == "drag":
            spec, pct = rest[0], float(rest[1])
            r = await self.rect(spec, where)
            if not r:
                return False
            cur = float(await self.cdp.js(f"(__tour.el({json.dumps(spec)}) || {{}}).value") or 0)
            thumb = 22
            xa = r["x"] + thumb / 2 + (r["w"] - thumb) * cur / 100.0
            xb = r["x"] + thumb / 2 + (r["w"] - thumb) * pct / 100.0
            y = r["y"] + r["h"] / 2
            await self.move(xa, y, 600)
            await self.cdp.send("Input.dispatchMouseEvent", type="mousePressed", x=xa, y=y,
                                button="left", clickCount=1)
            steps = 24
            for i in range(1, steps + 1):
                k = i / steps
                k = k * k * (3 - 2 * k)
                x = xa + (xb - xa) * k
                await self.cdp.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y,
                                    button="left", buttons=1)
                await self.cdp.js(f"__tour.jump({x}, {y})")
                await asyncio.sleep(0.035)
            await self.cdp.send("Input.dispatchMouseEvent", type="mouseReleased", x=xb, y=y,
                                button="left", clickCount=1)
            self.pointer = (xb, y)
        elif kind == "zoom":
            spec = rest[0]
            scale = float(rest[1]) if len(rest) > 1 else 1.5
            r = await self.rect(spec, where)
            if not r:
                return False
            W, H = self.args.width, self.args.height
            fit = min(W / (r["w"] * 1.12), H / (r["h"] * 1.12))
            seg["zooms"].append({"t0": time.time() - t0, "t1": None,
                                 "cx": r["x"] + r["w"] / 2, "cy": r["y"] + r["h"] / 2,
                                 "s": max(1.0, min(scale, fit))})
        elif kind == "unzoom":
            for z in seg["zooms"]:
                if z["t1"] is None:
                    z["t1"] = time.time() - t0
        elif kind == "wait":
            await asyncio.sleep(float(rest[0]))
        elif kind == "label":
            await self.cdp.js(f"__tour.label({json.dumps(rest[0])}, {int(rest[1]) if len(rest) > 1 else 3200})")
        elif kind == "hide":
            await self.cdp.js("document.getElementById('__tp').style.opacity='0'")
            self.pointer_shown = False
        elif kind == "expect":
            if self.args.live:
                spec, want = rest[0], rest[1].lower()
                r = await self.cdp.js(f"__tour.rect({json.dumps(spec)})")
                if not r or want not in r.get("text", ""):
                    self.problems.append(f"{where}: expected {want!r}, the page shows "
                                         f"{(r or {}).get('text', 'nothing')!r}")
        else:
            self.problems.append(f"{where}: unknown action {kind!r}")
        return False


def prepare(host, iws_port, api_key, commands, allow_ids):
    """Put the house in the tour's starting state before a live take.

    Only ids on the tour's allow list, and only in a --live take. Live case: a
    retake started with the colour lamp remembering the 50% the first take
    left it at, so "slide it down to half brightness" moved nothing.
    """
    done = []
    for cmd in commands:
        if _as_int(cmd.get("objectId")) not in allow_ids:
            raise SystemExit(f"prepare: {cmd.get('objectId')} is not on the tour's allow list")
        req = urllib.request.Request(
            f"http://{host}:{iws_port}/v2/api/command", data=json.dumps(cmd).encode(),
            method="POST", headers={"Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as res:
            res.read()
        done.append(f"{cmd.get('message')} {cmd.get('objectId')}")
        time.sleep(float(cmd.get("pause", 1.5)))
    return done


def page_url(origin, page):
    return f"{origin}/public/dashboards/{page}"


async def settle_on(cdp, origin, seg, args, navigated):
    """Arrive at the segment's page — by the press that led here, or directly."""
    if "card" in seg:
        html = card_html(seg["card"], ICON_URI)
        data = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await cdp.send("Page.navigate", url=data)
        await asyncio.sleep(0.6)
        return
    want = seg["page"]
    here = ""
    if navigated:
        for _ in range(40):
            await asyncio.sleep(0.25)
            try:
                here = await cdp.js("location.pathname.split('/').pop() + location.search "
                                    "+ '|' + document.readyState", timeout=5)
            except Exception:
                continue
            if here == f"{want}|complete":
                break
    if here != f"{want}|complete":
        await cdp.send("Page.navigate", url=page_url(origin, want))
    await asyncio.sleep(seg.get("settle", args.settle))
    # A fixed wait is not enough on its own: a room page that met a slow
    # first poll was still saying "Connecting..." when a take began.
    for _ in range(40):
        busy = await cdp.js("/connecting|loading/i.test(document.body.innerText.slice(0, 4000))")
        if not busy:
            break
        await asyncio.sleep(0.5)
    else:
        print("(still loading) ", end="", flush=True)
    # And the page's own sign of life, where the tour names one: the hub's
    # energy card was once still empty when a take began, a page that had
    # stopped saying "Connecting" but had not drawn its data yet.
    if seg.get("ready"):
        await cdp.js(TOUR_JS)
        for _ in range(50):
            if await cdp.js(f"!!__tour.el({json.dumps(seg['ready'])})"):
                break
            await asyncio.sleep(0.5)
        else:
            print("(never ready) ", end="", flush=True)
        await asyncio.sleep(seg.get("after_ready", 1.0))


async def record(args, segments, origin, work):
    profile = os.path.join(work, "profile")
    frames_dir = os.path.join(work, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    chrome = Chrome(args.width, args.height, profile)
    problems = []
    try:
        async with connect(chrome.page_ws(), max_size=None) as ws:
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            rec = Recorder(cdp, frames_dir)
            director = Director(cdp, args, problems)
            await cdp.send("Page.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=args.width,
                           height=args.height, deviceScaleFactor=args.scale,
                           mobile=False)
            await cdp.send("Page.startScreencast", format="jpeg", quality=92,
                           maxWidth=int(args.width * args.scale),
                           maxHeight=int(args.height * args.scale))
            navigated = False
            for n, seg in enumerate(segments):
                name = seg.get("page") or seg["card"].get("title", "card")
                print(f"  {name[:34]:<34} {seg['length']:5.1f}s ", end="", flush=True)
                await settle_on(cdp, origin, seg, args, navigated)
                navigated = False
                if "page" in seg:
                    await director.inject()
                    if seg.get("start") is not None:
                        await cdp.js(f"__tour.go({json.dumps(seg['start'])}, 1, "
                                     f"{json.dumps(seg.get('start_offset'))})")
                if seg.get("live_words"):
                    fresh = await steady_energy(cdp)
                    if not fresh:
                        problems.append(f"{name}: the energy figures never settled; said none")
                    problems.extend(respeak(seg, energy_words(fresh), args.voice, args.rate, work))
                    print("(re-read) ", end="", flush=True)
                await asyncio.sleep(0.5)
                t0 = time.time()
                if seg.get("label"):
                    await cdp.js(f"__tour.label({json.dumps(seg['label'])}, 3400)")
                where = f"segment {n + 1} ({name})"
                for beat in seg["beats"]:
                    when = t0 + max(0.0, beat["start"] - SCROLL_EARLY)
                    late = time.time() - when
                    if late > 0.6:
                        problems.append(f"{where}: a beat started {late:.1f}s late "
                                        f"(\"{beat['say'][:40]}\")")
                    await asyncio.sleep(max(0.0, when - time.time()))
                    if "to" in beat:
                        await director.run(seg, ["scroll", beat["to"], beat.get("offset")], t0, where)
                    for action in beat.get("do", []):
                        if await director.run(seg, action, t0, where):
                            navigated = True
                            break
                    if navigated:
                        break
                await asyncio.sleep(max(0.0, t0 + seg["length"] - time.time()))
                await asyncio.sleep(1.2)           # frames still on their way
                for z in seg["zooms"]:
                    if z["t1"] is None:
                        z["t1"] = seg["length"]
                seg["frames"] = rec.take(t0, t0 + seg["length"])
                if not seg["frames"]:
                    problems.append(f"{where}: no frames at all")
                lag = max(rec.lag) if rec.lag else 0
                rec.lag = []
                print(f"{len(seg['frames'])} frames, worst {lag:.2f}s late")
            await cdp.send("Page.stopScreencast")
            pump.cancel()
    finally:
        chrome.close()
    return problems


async def survey(args, origin, work):
    """What the house is doing before the take: energy words, starting state."""
    chrome = Chrome(args.width, args.height, os.path.join(work, "survey"))
    found = {}
    try:
        async with connect(chrome.page_ws(), max_size=None) as ws:
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            await cdp.send("Page.enable")
            await cdp.send("Page.navigate", url=page_url(origin, "index.html"))
            await asyncio.sleep(args.settle)
            await cdp.js(TOUR_JS)
            found["energy"] = await steady_energy(cdp)
            for key, spec in (args.preflight or {}).items():
                page, what = spec["page"], spec["spec"]
                await cdp.send("Page.navigate", url=page_url(origin, page))
                await asyncio.sleep(args.settle)
                await cdp.js(TOUR_JS)
                if spec.get("checked") is not None:
                    found[key] = await cdp.js(f"__tour.checked({json.dumps(what)})")
                else:
                    r = await cdp.js(f"__tour.rect({json.dumps(what)})")
                    found[key] = (r or {}).get("text")
            pump.cancel()
    finally:
        chrome.close()
    return found


async def scout(args, pages, origin, work):
    chrome = Chrome(args.width, args.height, os.path.join(work, "profile"))
    try:
        async with connect(chrome.page_ws(), max_size=None) as ws:
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            await cdp.send("Page.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=args.width,
                           height=args.height, deviceScaleFactor=1, mobile=False)
            for page in pages:
                await cdp.send("Page.navigate", url=page_url(origin, page))
                await asyncio.sleep(args.settle)
                await cdp.js(TOUR_JS)
                if args.eval:
                    print(f"\n== {page}")
                    print(json.dumps(await cdp.js(args.eval), indent=1)[:6000])
                    if args.scout_shots:
                        await asyncio.sleep(0.5)
                        shot = await cdp.send("Page.captureScreenshot", format="png")
                        os.makedirs(args.scout_shots, exist_ok=True)
                        name = page.split(".html")[0] + "-eval.png"
                        with open(os.path.join(args.scout_shots, name), "wb") as fh:
                            fh.write(base64.b64decode(shot["data"]))
                    continue
                info = await cdp.js("__tour.headings()")
                print(f"\n== {page}  (page height {info['height']}px)")
                for y, s in info["headings"]:
                    print(f"  {y:>6}  {s}")
                if args.scout_shots:
                    os.makedirs(args.scout_shots, exist_ok=True)
                    shot = await cdp.send("Page.captureScreenshot", format="jpeg",
                                          quality=70, captureBeyondViewport=True,
                                          clip={"x": 0, "y": 0, "scale": 0.6,
                                                "width": args.width,
                                                "height": info["height"]})
                    name = page.split(".html")[0] + ".jpg"
                    with open(os.path.join(args.scout_shots, name), "wb") as fh:
                        fh.write(base64.b64decode(shot["data"]))
            pump.cancel()
    finally:
        chrome.close()


# ------------------------------------------------------------------- assembly

def _ease(p):
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def zoom_at(zooms, t, W, H):
    """(zoom factor, centre x, centre y) in page pixels at time t."""
    for z in zooms:
        if z["t0"] <= t <= z["t1"] + ZOOM_RAMP:
            e = _ease(min((t - z["t0"]) / ZOOM_RAMP, (z["t1"] + ZOOM_RAMP - t) / ZOOM_RAMP))
            s = 1 + (z["s"] - 1) * e
            return s, W / 2 + (z["cx"] - W / 2) * e, H / 2 + (z["cy"] - H / 2) * e
    return 1.0, W / 2, H / 2


def crop_box(s, cx, cy, W, H):
    """The part of the page shown at zoom s around (cx, cy), kept on the page."""
    bw, bh = W / s, H / s
    x0 = min(max(cx - bw / 2, 0), W - bw)
    y0 = min(max(cy - bh / 2, 0), H - bh)
    return x0, y0, x0 + bw, y0 + bh


def fade_at(t, length):
    """0 = the picture, 1 = the background colour."""
    return max(0.0, 1 - t / FADE, 1 - (length - t) / FADE)


def compose(segments, out, W, H):
    """Every segment's frames -> one constant-rate video, zooms and fades in."""
    from PIL import Image

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(FPS), out], stdin=subprocess.PIPE)
    bg = Image.new("RGB", (W, H), BG)
    cache = {"path": None, "img": None}
    try:
        for seg in segments:
            frames = seg.get("frames") or []
            if not frames:
                continue
            times = [t for t, _ in frames]
            n = int(round(seg["length"] * FPS))
            for i in range(n):
                t = i / FPS
                shown_t = min(t, seg["cut"]) if seg.get("cut") else t
                path = frames[max(0, bisect.bisect_right(times, shown_t) - 1)][1]
                if path != cache["path"]:
                    cache["img"] = Image.open(path).convert("RGB")
                    cache["path"] = path
                img = cache["img"]
                k = img.width / W
                s, cx, cy = zoom_at(seg["zooms"], t, W, H)
                box = tuple(v * k for v in crop_box(s, cx, cy, W, H))
                frame = img.resize((W, H), Image.LANCZOS, box=box)
                f = fade_at(t, seg["length"])
                if f > 0:
                    frame = Image.blend(frame, bg, min(1.0, f))
                enc.stdin.write(frame.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise RuntimeError("ffmpeg could not encode the video")


def build_audio(segments, total, out):
    inputs, chains, labels = [], [], []
    for seg in segments:
        for beat in seg["beats"]:
            if not beat.get("audio"):
                continue
            i = len(inputs) // 2
            inputs += ["-i", beat["audio"]]
            ms = int(round((seg["offset"] + beat["start"]) * 1000))
            chains.append(f"[{i}:a]aresample=48000,adelay={ms}:all=1[a{i}]")
            labels.append(f"[a{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + \
        f"amix=inputs={len(labels)}:normalize=0,apad,atrim=0:{total:.3f}," \
        "loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", graph, "-map", "[out]",
                    "-ac", "2", "-c:a", "aac", "-b:a", "160k", out], check=True)


def vtt_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_vtt(segments, out):
    lines = ["WEBVTT", ""]
    n = 0
    for seg in segments:
        for beat in seg["beats"]:
            if not beat.get("say"):
                continue
            n += 1
            a = seg["offset"] + beat["start"]
            b = a + beat["dur"]
            lines += [str(n), f"{vtt_time(a)} --> {vtt_time(b)}", beat["say"], ""]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ----------------------------------------------------------------------- main

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Record a narrated tour of the dashboards.")
    ap.add_argument("--scout", nargs="*", metavar="PAGE",
                    help="print each page's headings and their positions, to "
                         "choose scroll targets; records nothing")
    ap.add_argument("--eval", metavar="JS",
                    help="with --scout, print this expression's value on each page instead")
    ap.add_argument("--scout-shots", metavar="DIR",
                    help="with --scout, also save a whole-page picture of each")
    ap.add_argument("--tour", default=os.path.join(here, "tour.json"))
    ap.add_argument("--live", action="store_true",
                    help="let the tour's presses reach the house (only the ids in its "
                         "'allow' list). Without it every command is refused and logged.")
    ap.add_argument("--host", default="192.168.1.10", help="Indigo server")
    ap.add_argument("--iws-port", type=int, default=8176)
    ap.add_argument("--port", type=int, default=8898, help="local proxy port")
    ap.add_argument("--out", default="docs/video")
    ap.add_argument("--name", default="tour")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--scale", type=float, default=1.5,
                    help="device pixel ratio while recording; zooms up to this "
                         "factor stay pixel-sharp")
    ap.add_argument("--settle", type=float, default=7.0,
                    help="real seconds a page gets to load its data before "
                         "recording starts")
    ap.add_argument("--voice", default="kokoro:bm_george",
                    help="'kokoro:<voice>' (local neural voice, ~/.local/share/kokoro-tts) "
                         "or a `say -v '?'` voice. Falls back to Daniel when not installed.")
    ap.add_argument("--rate", type=int, default=178, help="words per minute")
    ap.add_argument("--scheme", choices=("light", "dark"), default="light")
    ap.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    ap.add_argument("--keep-frames", action="store_true",
                    help="keep the working folder (frames, speech) and print it")
    args = ap.parse_args()
    if connect is None:
        sys.exit("needs the 'websockets' package (pip install websockets)")
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if args.voice.startswith("kokoro:"):
        if not kokoro_installed():
            print(f"voice {args.voice!r} is not installed; using Daniel")
            args.voice = "Daniel"
    elif not any(line.startswith(args.voice + " ") for line in voices.splitlines()):
        print(f"voice {args.voice!r} is not installed; using Daniel")
        args.voice = "Daniel"

    renames = []
    for spec in args.rename:
        if "=" not in spec:
            sys.exit(f"--rename wants OLD=NEW, got {spec!r}")
        renames.append(tuple(spec.split("=", 1)))

    tour = {}
    if args.scout is None:
        with open(args.tour, encoding="utf-8") as fh:
            tour = json.load(fh)
    args.preflight = tour.get("preflight", {})

    sanitiser = cs.Sanitiser(renames)
    lock = threading.Lock()
    leaks = []
    guard = Guard(args.live, tour.get("allow", []), tour.get("allow_messages", []))
    api_key = cs.fetch_api_key(args.host, cs.BOOTSTRAP_PORT)
    if not api_key:
        sys.exit("no API key — every page would record as the Connect form")
    srv = serve_guarded(args.port, f"http://{args.host}:{args.iws_port}", sanitiser,
                        lock, api_key, leaks, args.scheme, guard)
    origin = f"http://127.0.0.1:{args.port}"
    try:
        signalling = serve_signalling(cs.BOOTSTRAP_PORT,
                                      f"http://{args.host}:{cs.BOOTSTRAP_PORT}",
                                      sanitiser, f"http://{args.host}:{args.iws_port}")
    except OSError as e:
        signalling = None
        print(f"warning: cannot carry live camera video ({e}); the camera "
              "tiles will record as stills")
    work = tempfile.mkdtemp(prefix="dash-tour-")

    try:
        if args.scout is not None:
            asyncio.run(scout(args, args.scout, origin, work))
            return

        if args.live and tour.get("prepare"):
            print("setting the starting state ...")
            for line in prepare(args.host, args.iws_port, api_key, tour["prepare"], guard.allow_ids):
                print(f"  {line}")
        print("reading the house ...")
        state = asyncio.run(survey(args, origin, work))
        energy = state.get("energy") or {}
        words = energy_words(energy)
        print(f"  energy: {energy}")
        print(f"  says:   {words['energy_now']}")
        wrong = []
        for key, spec in args.preflight.items():
            want = spec.get("checked")
            got = state.get(key)
            if want is not None:
                if got is not want:
                    wrong.append(f"{key}: is {got}, the tour starts from {want}")
            elif spec.get("text", "").lower() not in (got or ""):
                wrong.append(f"{key}: reads {got!r}, the tour starts from {spec.get('text')!r}")
        if wrong:
            msg = "the house is not in the tour's starting state:\n  " + "\n  ".join(wrong)
            if args.live:
                sys.exit(msg)
            print("  (rehearsal, so carrying on) " + msg)

        print(f"speaking the script ({args.voice}) ...")
        segments, total = plan(tour, work, args.voice, args.rate, words)
        print(f"  {sum(1 for s in segments for b in s['beats'] if b['say'])} lines, {total:.1f}s")
        print("recording" + (" LIVE" if args.live else " a rehearsal (nothing reaches the house)") + " ...")
        problems = asyncio.run(record(args, segments, origin, work))

        print("\ncommands the pages sent:")
        start = min((t for t, _, _ in guard.log), default=0)
        for t, desc, ok in guard.log:
            print(f"  +{t - start:6.1f}s  {'SENT   ' if ok else 'refused'}  {desc}")
        if not guard.log:
            print("  none")
        if leaks:
            sys.exit(f"LEAK — {sorted(set(leaks))} survived the proxy. "
                     "Nothing written; do not publish frames from this run.")

        print("assembling ...")
        os.makedirs(args.out, exist_ok=True)
        video = os.path.join(work, "video.mp4")
        compose(segments, video, args.width, args.height)
        audio = os.path.join(work, "audio.m4a")
        build_audio(segments, total, audio)
        mp4 = os.path.join(args.out, f"{args.name}.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio,
                        "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest",
                        "-movflags", "+faststart", mp4], check=True)
        write_vtt(segments, os.path.join(args.out, f"{args.name}.vtt"))
        poster = os.path.join(args.out, f"{args.name}-poster.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss",
                        f"{tour.get('poster_at', 3.0)}", "-i", mp4,
                        "-frames:v", "1", "-q:v", "3", poster], check=True)

        print(f"\nwrote {mp4} ({os.path.getsize(mp4) / 1e6:.1f} MB, "
              f"{media_duration(mp4):.1f}s)")
        print(f"rewrote {len(sanitiser.map)} address(es); self-check: nothing survived")
        if problems:
            print("\nPROBLEMS — look before using this take:\n  " + "\n  ".join(problems))
    finally:
        srv.shutdown()
        if signalling:
            signalling.shutdown()
        if args.keep_frames:
            print(f"working folder kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
