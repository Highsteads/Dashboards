#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    theme_shots.py
# Description: Mechanical theme regression check — renders every dashboard
#              page in BOTH colour schemes through headless Chrome and judges
#              the pixels: background matches the scheme, the page is not
#              blank, and dark genuinely differs from light. Optionally diffs
#              against a saved baseline set from a previous run.
# Author:      CliveS & Claude Fable 5
# Date:        28-07-2026
# Version:     1.0
#
# WHY THIS EXISTS
# The v2.51.0 sweep moved the palette of 23 pages into dashboards-theme.css.
# A model re-reading the CSS is the wrong check — the right check is to render
# every page in both schemes and look. This does that without eyes: the proxy
# forces the scheme by rewriting `prefers-color-scheme` media queries on the
# way to the browser (plus a matchMedia shim for any JS that asks), so the
# page's own dark rules are exercised exactly as a real dark-mode browser
# would apply them. No CDP session, no Chrome flags of dubious support.
#
#   python3 tools/theme_shots.py                      # all pages, both schemes
#   python3 tools/theme_shots.py index cameras        # a subset
#   python3 tools/theme_shots.py --baseline shots/A --compare shots/B
#
# Output PNGs stay local (screenshots are of the LIVE house — do not publish).

import argparse
import http.server
import json
import os
import re
import shutil
import socketserver
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BOOTSTRAP_PORT = 8177

# Pages that never render real content without a one-time token — captured
# anyway (their error state should still be styled) but exempt from the
# "content present" check.
TOKEN_PAGES = {"setup", "guest"}

# Skipped by default: guest/demo redirect to the Connect form without a
# pairing token, so a default run would only ever capture the bounce.
DEFAULT_SKIP = {"guest", "demo"}

# Pages that need a query string to render anything at all. Without these the
# page loads, renders an empty shell, and looks exactly like a styling
# regression — so the harness supplies real deep links.
PAGE_QUERY = {
    "room": "?room=Kitchen",
    "wifi-ap": "?id=1802440778",
    "history": "?device=1563154425&state=batterysoc",
}

# The media-query rewrite, per target scheme. `all` always matches; `not all`
# never does — so the page's dark block either becomes unconditional or inert.
DARK_RE = re.compile(rb"\(\s*prefers-color-scheme\s*:\s*dark\s*\)")
LIGHT_RE = re.compile(rb"\(\s*prefers-color-scheme\s*:\s*light\s*\)")


def scheme_rewrite(body, scheme):
    if scheme == "dark":
        body = DARK_RE.sub(b"all", body)
        body = LIGHT_RE.sub(b"not all", body)
    else:
        body = DARK_RE.sub(b"not all", body)
        body = LIGHT_RE.sub(b"all", body)
    return body


def head_inject(api_key, scheme):
    """Inline <head> payload: seed the credential store synchronously (the
    pages guard on it at script time) and shim matchMedia so JS asking about
    the colour scheme gets the forced answer."""
    dark = "true" if scheme == "dark" else "false"
    seed = ""
    if api_key:
        seed = ("try{localStorage.setItem('indigo_config',JSON.stringify("
                "{baseURL:location.origin,apiKey:'%s'}));}catch(e){}" % api_key)
    shim = (
        "const _mm=window.matchMedia.bind(window);"
        "window.matchMedia=function(q){"
        "if(/prefers-color-scheme/.test(q)){"
        "const wantsDark=/dark/.test(q);"
        "return{matches:wantsDark===%s,media:q,onchange:null,"
        "addEventListener(){},removeEventListener(){},"
        "addListener(){},removeListener(){},"
        "dispatchEvent(){return false}};}"
        "return _mm(q);};" % dark
    )
    return ("<script>%s%s</script>" % (seed, shim)).encode()


def make_handler(upstream, api_key, scheme, lock, seen_paths):
    class Proxy(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _relay(self, method):
            url = upstream + self.path
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
            except Exception as e:
                body, status, headers = str(e).encode(), 502, {}

            ctype = headers.get("Content-Type", "")
            if any(t in ctype for t in ("text", "javascript", "json", "xml")):
                body = scheme_rewrite(body, scheme)
            if "html" in ctype:
                inj = head_inject(api_key, scheme)
                if b"<head>" in body:
                    body = body.replace(b"<head>", b"<head>" + inj, 1)
                else:
                    body = inj + body
            if seen_paths is not None:
                bare = self.path.split("?")[0]
                if bare.endswith(".html"):
                    with lock:
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


def fetch_api_key(host):
    try:
        with urllib.request.urlopen(
                f"http://{host}:{BOOTSTRAP_PORT}/bootstrap", timeout=8) as res:
            return (json.load(res) or {}).get("apiKey") or ""
    except Exception as e:
        print(f"warning: no API key from /bootstrap ({e}) — credentialled "
              f"pages will capture as the Connect form")
        return ""


# ---------------------------------------------------------------- PNG reading
# Minimal stdlib PNG decoder: enough for Chrome's 8-bit RGB/RGBA screenshots.

def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, width, height, bitd, ctype, idat = 8, 0, 0, 0, 0, []
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            width, height, bitd, ctype = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if bitd != 8 or ctype not in (2, 6):
        raise ValueError(f"unsupported PNG (bitdepth {bitd} colour {ctype})")
    ch = 3 if ctype == 2 else 4
    raw = zlib.decompress(b"".join(idat))
    stride = width * ch
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        filt = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if filt == 1:                                        # Sub
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif filt == 2:                                      # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:                                      # Average
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:                                      # Paeth
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, ch, bytes(out)


def luma_grid(path, cells=24):
    """Downsample to a cells×cells grid: mean luminance per cell (for
    background and baseline diffing) and the min/max luminance seen in each
    cell (for occupancy). Cell MEANS alone cannot answer "is anything on this
    page" — a card of text averages back to nearly its own background."""
    w, h, ch, px = read_png(path)
    grid, spread = [], []
    for gy in range(cells):
        row, srow = [], []
        y0, y1 = h * gy // cells, h * (gy + 1) // cells
        for gx in range(cells):
            x0, x1 = w * gx // cells, w * (gx + 1) // cells
            total = n = 0
            lo, hi = 255, 0
            for y in range(y0, y1, max(1, (y1 - y0) // 10)):
                base = y * w * ch
                for x in range(x0, x1, max(1, (x1 - x0) // 10)):
                    o = base + x * ch
                    v = (px[o] * 299 + px[o + 1] * 587
                         + px[o + 2] * 114) // 1000
                    total += v
                    lo = v if v < lo else lo
                    hi = v if v > hi else hi
                    n += 1
            row.append(total // max(n, 1))
            srow.append((lo, hi))
        grid.append(row)
        spread.append(srow)
    return grid, spread


def judge(grid, spread, scheme, content_exempt):
    """Verdicts. Background = median of border cells. Occupancy = fraction of
    CELLS holding anything clearly off-background.

    Measured as occupancy rather than pixel density on purpose: a short page
    on a 2400px viewport is mostly empty by construction, and a density metric
    reads that as a regression. The first version of this check did exactly
    that and called a perfectly good room page blank."""
    border = (grid[0] + grid[-1]
              + [r[0] for r in grid] + [r[-1] for r in grid])
    border.sort()
    bg = border[len(border) // 2]
    cells = [c for row in spread for c in row]
    occupied = sum(1 for lo, hi in cells
                   if abs(lo - bg) > 40 or abs(hi - bg) > 40)
    content = occupied / max(len(cells), 1)
    problems = []
    if scheme == "light" and bg < 160:
        problems.append(f"light background too dark (luma {bg})")
    if scheme == "dark" and bg > 96:
        problems.append(f"dark background too light (luma {bg})")
    if content < 0.02 and not content_exempt:
        problems.append(f"page looks blank ({content:.1%} of cells hold "
                        f"anything)")
    return bg, content, problems


def grid_diff(a, b):
    fa = [v for r in a for v in r]
    fb = [v for r in b for v in r]
    return sum(abs(x - y) for x, y in zip(fa, fb)) / len(fa)


# ------------------------------------------------------------------- capture

def capture(url, out_png, profile, width, height, budget):
    if os.path.exists(out_png):
        os.remove(out_png)
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--user-data-dir={profile}",
         f"--window-size={width},{height}",
         f"--virtual-time-budget={budget}",
         f"--screenshot={out_png}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.exists(out_png) and os.path.getsize(out_png) > 0:
            time.sleep(1.5)
            break
        time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return os.path.exists(out_png) and os.path.getsize(out_png) > 0


def discover_pages(pages_dir):
    return sorted(p[:-5] for p in os.listdir(pages_dir)
                  if p.endswith(".html"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", help="page names; default = all")
    ap.add_argument("--host", default="192.168.1.10")
    ap.add_argument("--iws-port", type=int, default=8176)
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("--out", default="screenshots/theme")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=2400)
    ap.add_argument("--budget", type=int, default=12000)
    ap.add_argument("--baseline", help="previous run dir to diff against")
    ap.add_argument("--diff-threshold", type=float, default=6.0,
                    help="mean per-cell luma delta that counts as a change")
    args = ap.parse_args()

    if not os.path.exists(CHROME):
        sys.exit(f"Google Chrome not found at {CHROME}")

    here = os.path.dirname(os.path.abspath(__file__))
    pages_dir = os.path.join(
        here, "..", "Dashboards.indigoPlugin", "Contents", "Resources",
        "static", "pages")
    pages = args.pages or [p for p in discover_pages(pages_dir)
                           if p not in DEFAULT_SKIP]

    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, ".tmp")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    subprocess.run(["pkill", "-f", "Google Chrome.*headless"],
                   capture_output=True)
    api_key = fetch_api_key(args.host)

    lock = threading.Lock()
    results, failures = [], []

    for scheme in ("light", "dark"):
        seen = []
        srv = Threaded(("127.0.0.1", args.port), make_handler(
            f"http://{args.host}:{args.iws_port}", api_key, scheme, lock, seen))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"— {scheme} pass on 127.0.0.1:{args.port} —")
        for page in pages:
            url = (f"http://127.0.0.1:{args.port}/public/dashboards/"
                   f"{page}.html{PAGE_QUERY.get(page, '')}")
            png = os.path.join(args.out, f"{page}--{scheme}.png")
            with lock:
                seen.clear()
            ok = capture(url, png, os.path.join(work, f"{page}-{scheme}"),
                         args.width, args.height, args.budget)
            notfound = bounced = None
            with lock:
                notfound = [st for p, st in seen
                            if p.endswith(f"/{page}.html") and st != 200]
                bounced = (page != "index"
                           and any(p.endswith("index.html") for p, _ in seen))
            if not ok:
                failures.append((page, scheme, "no PNG written"))
                print(f"  {page:<16} FAILED (no PNG)")
                continue
            if notfound:
                failures.append((page, scheme, f"HTTP {notfound[0]}"))
                print(f"  {page:<16} FAILED (HTTP {notfound[0]})")
                continue
            if bounced:
                failures.append((page, scheme, "bounced to Connect form"))
                print(f"  {page:<16} FAILED (Connect form)")
                continue
            grid, spread = luma_grid(png)
            bg, content, problems = judge(grid, spread, scheme,
                                          page in TOKEN_PAGES)
            results.append({"page": page, "scheme": scheme, "bg": bg,
                            "content": round(content, 3), "grid": grid,
                            "problems": problems})
            flag = " !! " + "; ".join(problems) if problems else ""
            print(f"  {page:<16} bg={bg:<3} content={content:>6.2%}{flag}")
        srv.shutdown()
        srv.server_close()      # shutdown() alone leaves the socket bound —
                                # the second pass then cannot rebind the port

    subprocess.run(["pkill", "-f", "Google Chrome.*headless"],
                   capture_output=True)
    shutil.rmtree(work, ignore_errors=True)

    # Cross-scheme check: a page whose dark render matches its light render
    # never implemented dark mode (or lost it in the sweep).
    by_key = {(r["page"], r["scheme"]): r for r in results}
    same = []
    for page in pages:
        a, b = by_key.get((page, "light")), by_key.get((page, "dark"))
        if a and b and grid_diff(a["grid"], b["grid"]) < 4.0:
            same.append(page)

    # Baseline diff (styling regressions between versions).
    changed = []
    if args.baseline:
        for r in results:
            old = os.path.join(args.baseline,
                               f"{r['page']}--{r['scheme']}.png")
            if os.path.exists(old):
                d = grid_diff(luma_grid(old)[0], r["grid"])
                if d > args.diff_threshold:
                    changed.append((r["page"], r["scheme"], round(d, 1)))

    report = {
        "captured": len(results),
        "failed": failures,
        "problems": [{k: r[k] for k in ("page", "scheme", "bg", "content",
                                        "problems")}
                     for r in results if r["problems"]],
        "dark_equals_light": same,
        "changed_vs_baseline": changed,
    }
    with open(os.path.join(args.out, "report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print(f"\ncaptured {len(results)} renders "
          f"({len(failures)} capture failures)")
    if report["problems"]:
        print("PROBLEMS:")
        for p in report["problems"]:
            print(f"  {p['page']} [{p['scheme']}]: {'; '.join(p['problems'])}")
    if same:
        print(f"DARK==LIGHT (no dark mode?): {', '.join(same)}")
    if changed:
        print("CHANGED vs baseline:")
        for page, scheme, d in changed:
            print(f"  {page} [{scheme}] delta {d}")
    if failures or report["problems"] or same:
        sys.exit(1)
    print("theme check: all pages render correctly in both schemes")


if __name__ == "__main__":
    main()
