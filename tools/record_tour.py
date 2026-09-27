#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    record_tour.py
# Description: Record a narrated video tour of the live dashboards for the docs
#              site, through the same sanitising proxy as capture_screenshots.py.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026 22:30 BST
# Version:     1.0
#
# WHAT IT DOES
# Reads a tour script (tools/tour.json): a list of pages, each with a list of
# "beats" — one spoken sentence or two, and the place on the page to scroll to
# while it is spoken. Then:
#
#   1. speaks every beat to an audio file with macOS `say`, and times it;
#   2. starts the sanitising proxy from capture_screenshots.py, so every
#      private address, MAC and renamed person is rewritten before the browser
#      sees it, and token/PIN fields are blanked;
#   3. opens each page in a headless Chrome over the DevTools protocol, lets it
#      settle in REAL time (the one-shot --screenshot mode uses virtual time,
#      which never lets the live pages converge), then records Chrome's own
#      screencast while scrolling to each beat's target as its sentence starts;
#   4. joins the frames into video at a constant 30 fps, lays the speech on
#      the same clock, and writes an MP4, a WebVTT caption file and a poster.
#
# Because each beat's scroll is scheduled from the length of its own speech,
# picture and voice cannot drift apart, however long a sentence turns out.
#
#   python3 tools/record_tour.py --host 192.168.1.10 \
#       --rename Alice=Alex --out docs/video
#   python3 tools/record_tour.py --scout index energy     # list scroll targets
#
# The recording is only as clean as the proxy. The run refuses to write the
# video if the proxy's own residue check found anything, and a publish should
# still be preceded by a look at the frames (see --keep-frames).

import argparse
import asyncio
import base64
import json
import os
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

FPS         = 30
LEAD_IN     = 0.8                                  # seconds before the first beat
BEAT_GAP    = 0.45                                 # silence between beats
TAIL        = 0.9                                  # after the last beat of a page
SCROLL_MS   = 1400                                 # one eased scroll
SCROLL_EARLY = 0.25                                # scroll starts this far ahead of speech
FADE        = 0.3
DEBUG_PORT  = 9335

# Injected once per page. find() takes the first VISIBLE text node that starts
# with the wanted words (case-insensitive — most card labels are upper-cased by
# CSS, not in the text), so a tour script names what a viewer can read rather
# than a class name that the next redesign renames.
TOUR_JS = r"""
window.__tour = {
  find(t) {
    // Curly quotes in the page, straight ones in the script: compare as straight.
    const norm = x => x.replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase();
    const want = norm(t);
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const s = norm(n.textContent);
      if (!s || !s.startsWith(want)) continue;
      const el = n.parentElement;
      const r = el.getBoundingClientRect();
      if (r.height > 0 && getComputedStyle(el).visibility !== 'hidden') return r.top + scrollY;
    }
    return null;
  },
  go(target, ms, offset) {
    let y;
    if (typeof target === 'number') y = target;
    else if (target === 'top') y = 0;
    else if (target === 'bottom') y = 1e9;
    else y = this.find(target);
    if (y === null) return Promise.resolve('missing: ' + target);
    const max = document.documentElement.scrollHeight - innerHeight;
    y = Math.max(0, Math.min(y - (offset == null ? 90 : offset), max));
    const from = scrollY, t0 = performance.now();
    return new Promise(res => {
      const step = now => {
        const p = Math.min(1, (now - t0) / ms);
        const e = p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
        scrollTo(0, from + (y - from) * e);
        if (p < 1) requestAnimationFrame(step); else res('ok');
      };
      requestAnimationFrame(step);
    });
  },
  headings() {
    const out = [];
    document.querySelectorAll('h1,h2,h3,h4,*').forEach(el => {
      if (el.children.length) return;
      const s = el.textContent.replace(/\s+/g, ' ').trim();
      if (!s || s.length > 48) return;
      const cs = getComputedStyle(el);
      const head = /^H[1-4]$/.test(el.tagName) || cs.textTransform === 'uppercase';
      const r = el.getBoundingClientRect();
      if (head && r.height > 0) out.push([Math.round(r.top + scrollY), s]);
    });
    return {height: document.documentElement.scrollHeight, headings: out};
  },
};
'ready';
"""


# --------------------------------------------------------------------- speech

def speak(text, path, voice, rate):
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", path, text],
                   check=True)
    return media_duration(path)


def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def plan(tour, work, voice, rate):
    """Speak every beat and lay the whole film out on one clock."""
    t = 0.0
    segments = []
    for si, seg in enumerate(tour["segments"]):
        beats = []
        local = LEAD_IN
        for bi, beat in enumerate(seg["beats"]):
            wav = os.path.join(work, f"s{si:02d}b{bi:02d}.aiff")
            dur = speak(beat["say"], wav, voice, rate)
            beats.append({**beat, "audio": wav, "start": local, "dur": dur})
            local += dur + BEAT_GAP
        length = local - BEAT_GAP + TAIL
        segments.append({**seg, "beats": beats, "offset": t, "length": length})
        t += length
    return segments, t


# ----------------------------------------------------------------- signalling

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

    The arrival time is no good: on a heavy page the frames queue behind the
    acknowledgements and arrive seconds late, so a clip timed by arrival
    showed each scroll well after the sentence that asked for it. Chrome's
    own timestamp is wall-clock seconds, the clock the beats run on.

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
            await cdp.send("Page.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=args.width,
                           height=args.height, deviceScaleFactor=args.scale,
                           mobile=False)
            await cdp.send("Page.startScreencast", format="jpeg", quality=92,
                           maxWidth=int(args.width * args.scale),
                           maxHeight=int(args.height * args.scale))
            for seg in segments:
                url = f"{origin}/public/dashboards/{seg['page']}"
                print(f"  {seg['page']:<34} {seg['length']:5.1f}s ", end="",
                      flush=True)
                await cdp.send("Page.navigate", url=url)
                await asyncio.sleep(seg.get("settle", args.settle))
                await cdp.js(TOUR_JS)
                start_at = seg.get("start", "top")
                r = await cdp.js(f"__tour.go({json.dumps(start_at)}, 1, "
                                 f"{json.dumps(seg.get('offset'))})")
                if r != "ok":
                    problems.append(f"{seg['page']}: start {r}")
                await asyncio.sleep(0.6)
                t0 = time.time()
                for beat in seg["beats"]:
                    when = t0 + max(0.0, beat["start"] - SCROLL_EARLY)
                    await asyncio.sleep(max(0.0, when - time.time()))
                    if "to" in beat:
                        r = await cdp.js(
                            f"__tour.go({json.dumps(beat['to'])}, "
                            f"{beat.get('ms', SCROLL_MS)}, "
                            f"{json.dumps(beat.get('offset'))})")
                        if r != "ok":
                            problems.append(f"{seg['page']}: {r}")
                await asyncio.sleep(max(0.0, t0 + seg["length"] - time.time()))
                await asyncio.sleep(1.5)           # frames still on their way
                seg["frames"] = rec.take(t0, t0 + seg["length"])
                if not seg["frames"]:
                    problems.append(f"{seg['page']}: no frames at all")
                    continue
                seg["frames"].append((seg["length"], None))
                lag = sorted(rec.lag)
                print(f"{len(seg['frames']) - 1} frames, worst frame "
                      f"{lag[-1] if lag else 0:.2f}s late")
                rec.lag = []
            await cdp.send("Page.stopScreencast")
            pump.cancel()
    finally:
        chrome.close()
    return problems


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
                await cdp.send("Page.navigate",
                               url=f"{origin}/public/dashboards/{page}")
                await asyncio.sleep(args.settle)
                await cdp.js(TOUR_JS)
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

def encode_segment(seg, out, width, height):
    """Frames at their real times -> constant-rate video, faded at both ends."""
    listing = out + ".txt"
    frames = seg["frames"]
    with open(listing, "w") as fh:
        for (t, path), (t_next, _) in zip(frames, frames[1:]):
            if path is None:
                continue
            fh.write(f"file '{path}'\nduration {max(0.001, t_next - t):.4f}\n")
        # the concat demuxer ignores the last duration unless the file repeats
        last = [p for _, p in frames if p][-1]
        fh.write(f"file '{last}'\n")
    fade_out = max(0.0, seg["length"] - FADE)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", listing,
         "-vf", (f"scale={width}:{height}:flags=lanczos,fps={FPS},"
                 f"fade=in:st=0:d={FADE},fade=out:st={fade_out:.3f}:d={FADE},"
                 "format=yuv420p"),
         "-t", f"{seg['length']:.3f}", "-an",
         "-c:v", "libx264", "-preset", "slow", "-crf", "23",
         "-r", str(FPS), out], check=True)


def build_audio(segments, total, out):
    inputs, chains, labels = [], [], []
    for seg in segments:
        for beat in seg["beats"]:
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
                    "-ac", "2", "-c:a", "aac", "-b:a", "128k", out], check=True)


def vtt_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_vtt(segments, out):
    lines = ["WEBVTT", ""]
    n = 0
    for seg in segments:
        for beat in seg["beats"]:
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
    ap.add_argument("--scout-shots", metavar="DIR",
                    help="with --scout, also save a whole-page picture of each")
    ap.add_argument("--tour", default=os.path.join(here, "tour.json"))
    ap.add_argument("--host", default="192.168.1.10", help="Indigo server")
    ap.add_argument("--iws-port", type=int, default=8176)
    ap.add_argument("--port", type=int, default=8898, help="local proxy port")
    ap.add_argument("--out", default="docs/video")
    ap.add_argument("--name", default="tour")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--scale", type=float, default=1.5,
                    help="device pixel ratio while recording; frames are scaled "
                         "back to --width, which keeps small text sharp")
    ap.add_argument("--settle", type=float, default=7.0,
                    help="real seconds a page gets to load its data before "
                         "recording starts")
    ap.add_argument("--voice", default="Daniel")
    ap.add_argument("--rate", type=int, default=178, help="words per minute")
    ap.add_argument("--scheme", choices=("light", "dark"), default="light")
    ap.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    ap.add_argument("--keep-frames", action="store_true",
                    help="keep the working folder (frames, speech) and print it")
    args = ap.parse_args()
    if connect is None:
        sys.exit("needs the 'websockets' package (pip install websockets)")

    renames = []
    for spec in args.rename:
        if "=" not in spec:
            sys.exit(f"--rename wants OLD=NEW, got {spec!r}")
        renames.append(tuple(spec.split("=", 1)))

    sanitiser = cs.Sanitiser(renames)
    lock = threading.Lock()
    leaks = []
    api_key = cs.fetch_api_key(args.host, cs.BOOTSTRAP_PORT)
    if not api_key:
        sys.exit("no API key — every page would record as the Connect form")
    srv = cs.serve(args.port, f"http://{args.host}:{args.iws_port}", sanitiser,
                   lock, api_key, None, leaks, True, True, args.scheme)
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

        with open(args.tour, encoding="utf-8") as fh:
            tour = json.load(fh)
        print("speaking the script ...")
        segments, total = plan(tour, work, args.voice, args.rate)
        print(f"  {sum(len(s['beats']) for s in segments)} beats, {total:.1f}s")
        print("recording ...")
        problems = asyncio.run(record(args, segments, origin, work))
        if problems:
            sys.exit("scroll targets not found — fix tour.json:\n  " +
                     "\n  ".join(problems))
        if leaks:
            sys.exit(f"LEAK — {sorted(set(leaks))} survived the proxy. "
                     "Nothing written; do not publish frames from this run.")

        print("assembling ...")
        os.makedirs(args.out, exist_ok=True)
        parts = []
        for i, seg in enumerate(segments):
            part = os.path.join(work, f"seg{i:02d}.mp4")
            encode_segment(seg, part, args.width, args.height)
            parts.append(part)
        with open(os.path.join(work, "parts.txt"), "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in parts)
        video = os.path.join(work, "video.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", os.path.join(work, "parts.txt"), "-c", "copy", video],
                       check=True)
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
        if sanitiser.map:
            print(f"rewrote {len(sanitiser.map)} address(es); "
                  "self-check: nothing survived the rewrite")
        else:
            print("NO addresses were rewritten — check the proxy served the pages")
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
