#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    capture_screenshots.py
# Description: Screenshot a live dashboard page with every private IP address
#              rewritten to an RFC 5737 documentation address before the browser
#              ever renders it. For README captures of the pages that hold real
#              network config.
# Author:      CliveS & Claude Sonnet 5
# Date:        10-09-2026
# Version:     1.2
#
# WHY THIS EXISTS
# The Settings page shows the camera hosts, the router admin link and any
# device address pinned as a favourite; the Activity page quotes plugin errors
# that carry device IPs. Both are real network layout, and the estate rule is
# that a published file uses 192.168.1.x or RFC 5737 — never the live subnets.
# Two captures were dropped from the v2.x README set for exactly this.
#
# Redacting the PNG afterwards is the obvious approach and the wrong one: it is
# manual, it has to be redone every time a page changes, and a missed box ships
# the leak. This sanitises the DATA instead — a local reverse proxy rewrites the
# responses on the way to a headless Chrome, so the page renders sanitised and
# the screenshot is clean by construction.
#
# Nothing on the Indigo server is touched. The proxy is a separate process, so
# it is also clear of the "never call IWS from inside a plugin host" deadlock.
#
#   python3 tools/capture_screenshots.py --host 192.168.1.10 \
#       --out screenshots settings activity
#
# Addresses are mapped deterministically and per-subnet, so the picture stays
# coherent: the cameras still look like a camera subnet, and the same real host
# is always the same fake host.
#
# v1.1 (06-08-2026) adds three things, for the private Examples/ reference set:
#
#   --full-page   Measure the document height first, then size the window to it,
#                 so the capture holds the WHOLE page rather than the top 2400px.
#                 The old fixed --height silently cropped every long page.
#   --no-sanitise Serve the pages untouched. Only ever for a PRIVATE destination.
#   page?query    A page entry may carry a query string and an output alias, for
#                 the four pages that render nothing without one —
#                 room, history, wifi-ap and a camera detail view. Syntax:
#                 [alias:]page[?query], e.g. room-lounge:room?room=Living%20Room
#
#   python3 tools/capture_screenshots.py --full-page --no-sanitise \
#       --out Examples/screenshots index energy cost
#
# v1.2 (10-09-2026) fixes the camera tiles IN SANITISED MODE — they had 404'd
# on every capture since v1.0 and it read as a --no-sanitise-only limitation,
# which is what the note this replaces used to say. The stills are named
# cam-<ip>.jpg / cam-<ip>-thumb.jpg (cameras.html), so a browser that only
# ever saw the FAKE host (scrub() had already run on the config JSON before
# the page built that URL) asks the real Indigo server for a file it has
# never had. Sanitiser.unscrub_path() reverses the substitution on the way
# INTO the proxy, for the REQUEST PATH only — nothing that reaches the
# browser or the PNG is any less scrubbed than before. Confirmed against a
# capture from before this proxy existed (08-Jun-2026, real MJPEG frames,
# no redaction): the cameras really did work, the sanitising proxy just
# never carried the fix its own --no-sanitise note implied was needed.
#
# STILL TRUE AFTER v1.2: a single one-shot capture can catch a tile between
# its own polls, showing "Connecting..." rather than a frame. Live-verified
# this is Chrome's own virtual-time budget racing the still poller's retry
# timers against real network completion (an actual open browser tab
# converges every tile within ~20s of real time; headless virtual time does
# not reliably reach the same state, and does not improve monotonically
# with a bigger --budget — 4/9, 4/9, 6/9 and 3/9 real frames were measured
# at 12s/25s/50s/100s budgets on the same live cameras, in that order). A
# "Connecting..." tile is an honest, correctly-labelled non-error state, not
# a regression of this fix — 404 is gone either way. Fixing the remaining
# race properly needs a CDP session (navigate, wait for `load`, sleep in
# REAL time, then screenshot) rather than a `--screenshot`-flag one-shot;
# out of scope here. Mitigate by taking a couple of tries at a mid-size
# --budget (25000-50000) and keeping whichever came back with fewer
# "Connecting..." tiles.

import argparse
import http.server
import ipaddress
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# RFC 5737 documentation ranges — reserved precisely so they can appear in
# published material without pointing at anything real.
DOC_NETS = ["192.0.2.", "198.51.100.", "203.0.113."]

IP_RE = re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Endless responses. See _relay for why they have to be refused rather than
# relayed.
STREAM_RE = re.compile(r"^/(mjpeg|stream)/")

# The dashboards' own auto-seed asks this fixed port for an API key, building
# the URL from location.hostname — so it has to answer on the proxy's host too.
BOOTSTRAP_PORT = 8177


class Sanitiser:
    """Maps each real private address to a stable documentation address.

    One documentation net per real /24, so a capture that shows cameras on one
    subnet and IoT kit on another still reads that way. Public addresses are
    left alone: they are not the estate's to leak, and rewriting them would
    make an unrelated screenshot wrong.
    """

    def __init__(self):
        self.map = {}
        self.reverse = {}
        self._nets = {}
        self._hosts = {}

    def _fake_for(self, real):
        if real in self.map:
            return self.map[real]
        net = real.rsplit(".", 1)[0]
        if net not in self._nets:
            self._nets[net] = DOC_NETS[len(self._nets) % len(DOC_NETS)]
            self._hosts[net] = 0
        self._hosts[net] += 1
        fake = f"{self._nets[net]}{self._hosts[net]}"
        self.map[real] = fake
        self.reverse[fake] = real
        return fake

    def _sub(self, m):
        raw = m.group(0).decode()
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            return m.group(0)
        # Leave loopback alone or the page cannot talk to its own proxy.
        if addr.is_loopback or not addr.is_private:
            return m.group(0)
        return self._fake_for(raw).encode()

    def scrub(self, body):
        return IP_RE.sub(self._sub, body)

    def residue(self, body):
        """Private addresses still present AFTER scrubbing.

        The point of a self-check: a rewrite that silently misses something
        looks exactly like a page that was already clean, and the difference
        only shows up once the screenshot is published.

        NB the RFC 5737 ranges we substitute IN are themselves `is_private` as
        far as Python is concerned — they sit in the IANA special-purpose
        registry — so they have to be excluded explicitly or this reports every
        successful rewrite as a leak. It did, first time out.
        """
        out = []
        for m in IP_RE.finditer(body):
            raw = m.group(0).decode()
            try:
                addr = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if addr.is_loopback or not addr.is_private:
                continue
            if any(raw.startswith(n) for n in DOC_NETS):
                continue                           # one of ours
            out.append(raw)
        return out

    def unscrub_path(self, path):
        """Reverse the rewrite in a REQUEST PATH, not a response body.

        scrub() only ever touches what comes BACK from Indigo — the config
        JSON a camera tile reads its host from gets the real address
        replaced with a fake one, same as everything else. But a still
        image's filename carries that host baked into it (cam-<ip>.jpg,
        cam-<ip>-thumb.jpg — see cameras.html), and by the time the page
        builds that URL it only ever holds the fake address; the real one
        was gone before the browser saw it. Forwarding the fake filename
        upstream asks the real Indigo server for a file it has never had,
        and IWS's 404 for that is genuine — it just isn't the fault the
        screenshot ends up shipping. Swap it back before the request
        leaves the proxy so the still loads and the address a viewer can
        actually see stays exactly as scrubbed as before: this never
        touches anything that reaches the browser or the PNG.
        """
        def _sub(m):
            raw = m.group(0).decode()
            return self.reverse.get(raw, raw).encode()
        return IP_RE.sub(_sub, path.encode()).decode()


# Stamps the settled document height onto <html> so the measuring pass can read
# it back out of --dump-dom. Re-stamped on a few timers because a dashboard
# keeps growing after load: charts draw, the activity list fills, camera tiles
# arrive. Under --virtual-time-budget these fire almost immediately.
#
# The min-height override is the whole trick. Every page sets `min-height:100vh`
# on the body, so scrollHeight can never report less than the viewport and a
# short page measures as exactly the measuring window — the first run gave three
# different pages the same 2353px and a third of each capture was empty. Zeroing
# it inline (inline beats the stylesheet) makes the page report the height of
# its actual content, and it is put straight back so nothing else sees it.
# documentElement.scrollHeight is left out of the maximum for the same reason:
# it can never report less than the viewport, so including it put the floor
# straight back.
MEASURE_JS = (
    b"<script>(function(){function s(){"
    b"var d=document.documentElement,b=document.body;if(!b)return;"
    b"var pd=d.style.minHeight,pb=b.style.minHeight;"
    b"d.style.minHeight='0';b.style.minHeight='0';"
    b"var h=Math.max(b.scrollHeight,b.offsetHeight);"
    b"[].forEach.call(b.children,function(c){var r=c.getBoundingClientRect();"
    b"if(getComputedStyle(c).position!=='fixed')"
    b"h=Math.max(h,r.bottom+window.scrollY);});"
    b"d.style.minHeight=pd;b.style.minHeight=pb;"
    b"d.setAttribute('data-cap-height',Math.ceil(h));}"
    b"addEventListener('load',s);[400,1200,2500,5000,8000].forEach("
    b"function(t){setTimeout(s,t);});})();</script>"
)


# Blanks any field whose own label calls it a token, key, PIN, password or
# secret. The Settings page renders the live guest token into a readonly input,
# so a capture of it puts a working credential into an image file — and an image
# is the one place nobody thinks to grep for one. Runs on a timer because the
# cards are built by script well after the document loads.
MASK_JS = (
    b"<script>(function(){var RE=/token|api ?key|password|secret|\\bpin\\b/i;"
    b"function m(){document.querySelectorAll('input,textarea').forEach("
    b"function(i){var f=i.closest('.field'),l=f&&f.querySelector('label');"
    b"var t=(l?l.textContent:'')+' '+(i.name||'')+' '+(i.id||'');"
    b"if(RE.test(t)&&i.value)i.value='\\u2022'.repeat(16);});}"
    b"[600,1500,3000,6000,9000].forEach(function(t){setTimeout(m,t);});})();"
    b"</script>"
)


# Forcing the colour scheme, borrowed from theme_shots.py rather than reinvented: rewrite
# the media queries on the way to the browser so the page's OWN rules are exercised exactly
# as a real light-mode browser would apply them. `all` always matches, `not all` never does.
# No CDP session and no Chrome flag of dubious support.
_DARK_RE = re.compile(rb"\(\s*prefers-color-scheme\s*:\s*dark\s*\)")
_LIGHT_RE = re.compile(rb"\(\s*prefers-color-scheme\s*:\s*light\s*\)")


def scheme_rewrite(body, scheme):
    if scheme == "dark":
        return _LIGHT_RE.sub(b"not all", _DARK_RE.sub(b"all", body))
    return _LIGHT_RE.sub(b"all", _DARK_RE.sub(b"not all", body))


def scheme_shim(scheme):
    """matchMedia lies to match, for any JS that asks rather than relying on CSS."""
    wants_dark = "true" if scheme == "dark" else "false"
    return ("<script>(function(){const _mm=window.matchMedia.bind(window);"
            "window.matchMedia=function(q){if(/prefers-color-scheme/.test(q)){"
            "const d=/dark/.test(q);return{matches:d===%s,media:q,onchange:null,"
            "addEventListener(){},removeEventListener(){},addListener(){},"
            "removeListener(){},dispatchEvent(){return false}};}"
            "return _mm(q);};})();</script>" % wants_dark).encode()


def make_handler(upstream, sanitiser, seen_lock, api_key=None, seen_paths=None,
                 leaks=None, sanitise=True, mask=True, scheme=None):
    class Proxy(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass                                   # quiet; the caller reports

        def _inject_key(self, body):
            """Seed the browser's credential store before the page checks it.

            The pages' own auto-seed is asynchronous — fetch, then reload — but
            every page guards on the key SYNCHRONOUSLY at script time, so on a
            cold profile it redirects to the Connect form before the seed ever
            lands, and the capture is a login box. Writing localStorage inline
            ahead of dashboards-auth.js closes that race. The key stays on
            127.0.0.1 and is not rendered, so it cannot reach the screenshot.
            """
            seed = MEASURE_JS + (MASK_JS if mask else b"")
            if api_key:
                seed = (
                    "<script>try{localStorage.setItem('indigo_config',"
                    "JSON.stringify({baseURL:location.origin,apiKey:'%s'}));}"
                    "catch(e){}</script>" % api_key
                ).encode() + seed
            if b"<head>" in body:
                return body.replace(b"<head>", b"<head>" + seed, 1)
            return seed + body

        def _relay(self, method):
            # An MJPEG stream is an HTTP response that never ends, and Chrome
            # holds virtual time still while any request is in flight — so the
            # hub page, which opens up to four of them, never settled and the
            # run produced neither a DOM nor a PNG. Refusing them lets the
            # tiles' own onerror fall back to the still image, which is all a
            # screenshot could ever have shown.
            if STREAM_RE.search(self.path):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # The still poller's own filename carries an address the response
            # scrub already replaced with a fake one — see unscrub_path()'s
            # docstring. Un-rewrite it going upstream so the real Indigo
            # server can find the file; nothing that reaches the browser or
            # the PNG changes.
            path = sanitiser.unscrub_path(self.path) if sanitise else self.path
            url = upstream + path
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length) if length else None
            req = urllib.request.Request(url, data=payload, method=method)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "accept-encoding", "connection"):
                    req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=20) as res:
                    body = res.read()
                    status, headers = res.status, dict(res.headers)
            except urllib.error.HTTPError as e:
                body, status, headers = e.read(), e.code, dict(e.headers)
            except Exception as e:                 # upstream down / refused
                body, status, headers = str(e).encode(), 502, {}

            ctype = headers.get("Content-Type", "")
            # Only rewrite text. Touching an image or a font would corrupt it,
            # and an address cannot be read off a PNG anyway.
            if sanitise and any(t in ctype
                                for t in ("json", "text", "javascript", "xml")):
                with seen_lock:
                    body = sanitiser.scrub(body)
                    if leaks is not None:
                        leaks.extend(sanitiser.residue(body))
            # CSS and HTML carry the media queries; the shim goes in the head.
            if scheme and any(t in ctype for t in ("html", "css")):
                body = scheme_rewrite(body, scheme)
            if "html" in ctype:
                body = self._inject_key(body)
                if scheme and b"<head>" in body:
                    body = body.replace(b"<head>", b"<head>" + scheme_shim(scheme), 1)
            # Record every .html request and its status, NOT only the ones that
            # came back as HTML: IWS answers a missing page with a 404 whose
            # content-type is text/plain, so an html-only check never saw it.
            if seen_paths is not None:
                bare = self.path.split("?")[0]
                if bare.endswith(".html"):
                    with seen_lock:
                        seen_paths.append((bare, status))

            self.send_response(status)
            for k, v in headers.items():
                if k.lower() in ("content-length", "transfer-encoding",
                                 "content-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._relay("GET")

        def do_POST(self):
            self._relay("POST")

    return Proxy


class Threaded(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port, upstream, sanitiser, lock, api_key=None, seen_paths=None,
          leaks=None, sanitise=True, mask=True, scheme=None):
    srv = Threaded(("127.0.0.1", port),
                   make_handler(upstream, sanitiser, lock, api_key, seen_paths,
                                leaks, sanitise, mask, scheme))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def fetch_api_key(host, port):
    """Ask the plugin's own LAN bootstrap for the key, as a browser would.

    Fetched here rather than passed on the command line so the key never sits
    in a shell history or a script argument.
    """
    try:
        with urllib.request.urlopen(
                f"http://{host}:{port}/bootstrap", timeout=8) as res:
            import json
            return (json.load(res) or {}).get("apiKey") or ""
    except Exception as e:
        print(f"warning: could not read the API key from {host}:{port} "
              f"/bootstrap ({e}) — pages needing credentials will capture as "
              f"the Connect form")
        return ""


# Fractional too: getBoundingClientRect returns sub-pixel values, and an
# integer-only pattern failed to match a page that measured 4377.203125 —
# reporting "never reported its height" for a page that had reported it.
HEIGHT_RE = re.compile(rb'data-cap-height="(\d+)(?:\.\d+)?"')

# Chrome cannot back a window taller than its maximum texture, and the failure
# is a silently truncated or empty PNG rather than an error. Stop short of it
# and say so, because a quiet truncation looks exactly like a successful shot.
MAX_WINDOW = 15000
MIN_WINDOW = 900


def measure(url, profile, width, budget):
    """Return the settled document height in CSS pixels, or None.

    Only the page can answer this, so the proxy stamps the height onto <html>
    and this run reads it back out of --dump-dom. --screenshot is passed
    alongside, to a throwaway file, purely to force real painting: without it
    Chrome never runs requestAnimationFrame, so anything a chart draws from a
    rAF loop has no height yet and the page measures short.
    """
    throwaway = profile + "-measure.png"
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--user-data-dir={profile}",
         f"--window-size={width},2400",
         f"--virtual-time-budget={budget}",
         f"--screenshot={throwaway}", "--dump-dom", url],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # Chrome writes the DOM once the virtual-time budget is spent and then, more
    # often than not, does not exit — so the timeout is the normal path, not the
    # error path, and the buffered stdout after the kill is the real answer.
    # Waiting the old 90s for that added a minute of nothing to every page.
    try:
        dom, _ = proc.communicate(timeout=max(30, budget / 1000 + 20))
    except subprocess.TimeoutExpired:
        proc.kill()
        dom, _ = proc.communicate()
    finally:
        if os.path.exists(throwaway):
            os.remove(throwaway)
    found = HEIGHT_RE.search(dom or b"")
    return int(found.group(1)) if found else None


def capture(url, out_png, profile, width, height, budget, real_time=False):
    """Drive headless Chrome once. Poll for the file rather than trusting the
    exit code — --headless=new often does not exit after writing the PNG.

    Chrome writes into an empty scratch directory and the result is moved into
    place afterwards. Pointing --screenshot straight at the destination looked
    fine and was not: rather than overwrite, Chrome sidesteps to `name 2.png`,
    so the poll found the PREVIOUS run's file still sitting there and reported
    a successful capture over a stale image. Four of those reached the output
    directory before the pattern showed itself.
    """
    os.makedirs(profile, exist_ok=True)
    shot = os.path.join(profile, "shot.png")
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}"]
    if not real_time:
        args.append(f"--virtual-time-budget={budget}")
    args += [f"--screenshot={shot}", url]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.exists(shot) and os.path.getsize(shot) > 0:
            time.sleep(1.5)                        # let the write settle
            break
        time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not (os.path.exists(shot) and os.path.getsize(shot) > 0):
        return False
    shutil.move(shot, out_png)
    return True


def parse_entry(entry):
    """Split `[alias:]page[?query]` into (alias, page, query).

    The alias exists so two captures of the same page with different query
    strings do not overwrite each other's PNG. The colon is split before the
    question mark so a query value may itself contain a colon.
    """
    alias = None
    head = entry
    if ":" in head.split("?")[0]:
        alias, head = head.split(":", 1)
    page, _, query = head.partition("?")
    return (alias or page), page, query


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pages", nargs="+",
                    help="page entries, [alias:]page[?query] — e.g. settings "
                         "activity room-lounge:room?room=Living%%20Room")
    ap.add_argument("--host", default="192.168.1.10", help="Indigo server")
    ap.add_argument("--iws-port", type=int, default=8176)
    ap.add_argument("--port", type=int, default=8899, help="local proxy port")
    ap.add_argument("--out", default="screenshots")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=2400,
                    help="window height; ignored when --full-page measures one")
    ap.add_argument("--budget", type=int, default=12000)
    ap.add_argument("--full-page", action="store_true",
                    help="measure the document height first and capture all of "
                         "it, instead of cropping at --height")
    ap.add_argument("--no-sanitise", dest="sanitise", action="store_false",
                    help="serve the pages untouched, real addresses and all — "
                         "ONLY for a private destination")
    ap.add_argument("--no-mask-secrets", dest="mask", action="store_false",
                    help="leave token / key / PIN fields showing (they are "
                         "blanked in the capture by default)")
    ap.add_argument("--direct", action="store_true",
                    help="bypass the proxy and load straight from the server. "
                         "The guest page needs this: it fetches :8177 from a "
                         "page served on :8176, and through the proxy that "
                         "becomes a cross-origin request the plugin will not "
                         "answer, so it always captures as 'Pairing failed'. "
                         "Nothing is injected in this mode, so there is no "
                         "height measurement, no key seeding and no secret "
                         "masking — use it only on a page that needs none.")
    ap.add_argument("--scheme", choices=("light", "dark"), default=None,
                    help="force the page's colour scheme (default: whatever Chrome asks for, "
                         "which is dark). Rewrites the media queries on the way through, so "
                         "the page's own rules are exercised.")
    ap.add_argument("--real-time", action="store_true",
                    help="drop --virtual-time-budget, for a page that races a "
                         "wall-clock timer against a real fetch. Virtual time "
                         "spends the guest page's 4s AbortController before the "
                         "pairing request can answer, so it always captures as "
                         "'Pairing failed'. Measurement is skipped in this "
                         "mode — the window is --height.")
    args = ap.parse_args()

    if not os.path.exists(CHROME):
        sys.exit(f"Google Chrome not found at {CHROME}")

    # Refuse rather than quietly do nothing: --direct never sees a response, so
    # it cannot rewrite one, and a run that claimed to sanitise while serving
    # the real addresses is the one mistake this tool exists to prevent.
    if args.direct and args.sanitise:
        sys.exit("--direct cannot sanitise — nothing passes through the proxy. "
                 "Add --no-sanitise if the destination is private.")

    sanitiser = Sanitiser()
    lock = threading.Lock()
    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, ".capture-tmp")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    subprocess.run(["pkill", "-f", "Google Chrome.*headless"],
                   capture_output=True)

    api_key = fetch_api_key(args.host, BOOTSTRAP_PORT)
    seen_paths = []
    leaks = []

    main_srv = serve(args.port, f"http://{args.host}:{args.iws_port}",
                     sanitiser, lock, api_key, seen_paths, leaks,
                     args.sanitise, args.mask, args.scheme)
    # The pages' auto-seed builds its bootstrap URL from location.hostname, so
    # it lands on 127.0.0.1:8177 — which has to answer, as a fallback for any
    # page the inline seed above does not cover.
    try:
        boot_srv = serve(BOOTSTRAP_PORT, f"http://{args.host}:{BOOTSTRAP_PORT}",
                         sanitiser, lock, None, None, leaks, args.sanitise,
                         args.mask)
    except OSError as e:
        sys.exit(f"could not bind 127.0.0.1:{BOOTSTRAP_PORT} — {e}")

    print(f"proxy  127.0.0.1:{args.port} -> {args.host}:{args.iws_port}")
    print(f"boot   127.0.0.1:{BOOTSTRAP_PORT} -> {args.host}:{BOOTSTRAP_PORT}")
    print(f"key    {'seeded' if api_key else 'NOT AVAILABLE'}")
    print(f"mode   {'sanitised' if args.sanitise else 'RAW — private use only'}"
          f", {'full page' if args.full_page else f'{args.height}px crop'}"
          f", secrets {'masked' if args.mask else 'VISIBLE'}")
    if args.direct:
        print("       --direct: straight to the server. No injection, so no "
              "measurement, no masking, and the bounce/404 guards are blind.")

    failed = []
    origin = (f"http://{args.host}:{args.iws_port}" if args.direct
              else f"http://127.0.0.1:{args.port}")
    for entry in args.pages:
        alias, page, query = parse_entry(entry)
        url = f"{origin}/public/dashboards/{page}.html"
        if query:
            url += "?" + query
        png = os.path.join(args.out, f"{alias}.png")
        print(f"capturing {alias} ... ", end="", flush=True)
        with lock:
            seen_paths.clear()
        height = args.height
        if args.full_page and not (args.real_time or args.direct):
            measured = measure(url, os.path.join(work, alias + "-m"),
                               args.width, args.budget)
            if measured is None:
                # Never fall through to the crop height silently — a page that
                # would not report its own height is exactly the one whose
                # bottom is about to go missing.
                print("FAILED — the page never reported its height")
                failed.append(alias)
                continue
            height = min(max(measured + 40, MIN_WINDOW), MAX_WINDOW)
            if measured + 40 > MAX_WINDOW:
                print(f"[{measured}px, CAPPED at {MAX_WINDOW}] ",
                      end="", flush=True)
            else:
                print(f"[{height}px] ", end="", flush=True)
        ok = capture(url, png, os.path.join(work, alias),
                     args.width, height, args.budget, args.real_time)
        # A PNG on disk is NOT success: an unauthenticated page redirects to
        # index.html and screenshots the Connect form perfectly happily. Catch
        # the bounce by watching which documents the browser actually asked for.
        # demo.html is exempt for the same reason index.html is — forwarding to
        # the hub after setting the demo flag is the whole of what it does, by
        # design, credentials or none, so seeing index.html requested here is
        # not evidence of anything wrong.
        with lock:
            bounced = any(p.endswith("index.html") for p, _ in seen_paths) \
                and page not in ("index", "demo")
            # A 404 renders perfectly well: IWS serves a styled "Not Found"
            # page and Chrome screenshots it without complaint. Asking for a
            # page name that does not exist (`hub` rather than `index`) wrote
            # the error page straight into the repo and reported ok.
            notfound = [(p, st) for p, st in seen_paths
                        if p.endswith(f"/{page}.html") and st != 200]
        if ok and notfound:
            ok = False
            print(f"FAILED — the page returned HTTP {notfound[0][1]}")
        elif ok and bounced:
            ok = False
            print("FAILED — redirected to the Connect form (no credentials)")
        else:
            print("ok" if ok else "FAILED — no PNG written")
        if not ok:
            failed.append(alias)

    main_srv.shutdown()
    boot_srv.shutdown()
    subprocess.run(["pkill", "-f", "Google Chrome.*headless"],
                   capture_output=True)
    shutil.rmtree(work, ignore_errors=True)

    if not args.sanitise:
        print("\nRAW capture — real addresses are in these PNGs. Private "
              "destinations only.")
    elif sanitiser.map:
        print(f"\nrewrote {len(sanitiser.map)} address(es):")
        for real, fake in sorted(sanitiser.map.items()):
            print(f"  {real:<18} -> {fake}")
    else:
        print("\nNO addresses were rewritten — check the proxy actually served "
              "the page, rather than assuming the pages were already clean.")

    if leaks:
        uniq = sorted(set(leaks))
        sys.exit(f"\nLEAK — {len(uniq)} private address(es) survived the "
                 f"rewrite and may be in the PNG: {', '.join(uniq)}\n"
                 f"Do not publish these captures.")
    if args.sanitise:
        print("self-check: no private address survived the rewrite")

    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
