#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# Filename:    build_examples_site.py
# Description: Build the private Examples reference into one self-contained
#              HTML page with a wiki-style sidebar, and regenerate the page
#              table in Examples/README.md from the same list.
# Author:      CliveS & Claude Opus 5
# Date:        16-08-2026
# Version:     1.0
#
# WHY THIS EXISTS
# Examples/pages/ holds one markdown write-up per dashboard page. Read on
# github.com that is a list of files; read from Finder it is 23 separate
# documents. Neither reads like a reference you can move around in.
#
# This turns them into a single page: sidebar down the left, content on the
# right, deep-linkable by #slug. One file, no server, no dependencies — it
# opens by double-clicking it out of Finder and works offline. Screenshots are
# REFERENCED, not embedded, so the page stays small and the images stay in one
# place.
#
#   python3 tools/build_examples_site.py
#
# The PAGES list below is the single source of truth for order, grouping and
# one-line descriptions. The README table is generated from it too, between the
# PAGES:START / PAGES:END markers, so the two cannot drift apart.
#
# The markdown converter is deliberately small and handles exactly what these
# documents use. Reaching for a library was the first instinct and the wrong
# one: neither markdown nor mistune is installed in this Python, and adding a
# dependency to read a private document set is a poor trade.

import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(HERE, "Examples")
PAGES_DIR = os.path.join(EXAMPLES, "pages")
SITE_DIR = os.path.join(EXAMPLES, "site")
SHOTS = os.path.join(EXAMPLES, "screenshots")

# slug, group, one-line description. Order here is the order everywhere.
PAGES = [
    ("index",         "Start here",     "The hub — everything else hangs off it"),
    ("menu",          "Start here",     "Every page in one grouped list — what House/Rooms/Tools open"),
    ("energy",        "Energy",         "Sigenergy solar, battery and grid in full"),
    ("cost",          "Energy",         "Money — bills, export earnings, solar savings, VPP settlement"),
    ("carbon",        "Energy",         "Grid carbon and the best time to run a load"),
    ("mains",         "Energy",         "Every 240 V meter, and how far it can be trusted"),
    ("meter",         "Energy",         "One meter, in as much detail as the house holds on it"),
    ("laundry",       "Energy",         "When to run the washing machine for least grid import"),
    ("heating",       "The house",      "Evohome zones with setpoint control"),
    ("cameras",       "The house",      "Nine cameras, live at home and WebRTC away"),
    ("room",          "The house",      "One room — lights, motion, radiators, windows"),
    ("presence",      "The house",      "Room occupancy, night by night"),
    ("timeline",      "The house",      "Scrub back through a whole day"),
    ("active",        "The house",      "Every device currently on, with toggles"),
    ("scenes",        "The house",      "Action groups, grouped by folder"),
    ("ecowitt",       "The house",      "The weather station in full"),
    ("activity",      "Keeping watch",  "House diary and automation health"),
    ("alerts",        "Keeping watch",  "Per-device notification rules on this browser"),
    ("system-health", "Keeping watch",  "Mac vitals, storage, device health"),
    ("wifi",          "Keeping watch",  "UniFi access-point health and config audit"),
    ("wifi-ap",       "Keeping watch",  "Everything about one access point"),
    ("history",       "Keeping watch",  "Graph any recorded device state"),
    ("settings",      "Setup & access", "The configuration editor"),
    ("guest",         "Setup & access", "Pairs a device for read-only viewing"),
    ("setup",         "Setup & access", "Redeems a one-time setup link"),
    ("demo",          "Setup & access", "Turns on demo mode and forwards to the hub"),
    ("webrtc-test",   "Setup & access", "A bench for one WebRTC camera stream"),
]

GROUP_ORDER = ["Start here", "Energy", "The house", "Keeping watch", "Setup & access"]


# ── markdown ────────────────────────────────────────────────────────────────

INLINE_CODE = re.compile(r"`([^`]+)`")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")


def inline(text):
    """Escape, then apply the inline rules.

    Code spans are lifted out first and put back last, so a backticked
    `**not bold**` stays literal — several of these documents quote markup and
    state names that would otherwise be eaten.
    """
    spans = []

    def stash(m):
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = INLINE_CODE.sub(stash, text)
    text = html.escape(text, quote=False)
    text = IMAGE.sub(
        lambda m: f'<a href="{html.escape(m.group(2))}" target="_blank">'
                  f'<img src="{html.escape(m.group(2))}" '
                  f'alt="{html.escape(m.group(1))}"></a>', text)
    text = LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = ITALIC.sub(r"<em>\1</em>", text)
    for i, code in enumerate(spans):
        text = text.replace(f"\x00{i}\x00",
                            f"<code>{html.escape(code, quote=False)}</code>")
    return text


def table(rows):
    """Render a GFM pipe table. The separator row is dropped by the caller."""
    out = ['<div class="tw"><table>']
    for n, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        tag = "th" if n == 0 else "td"
        out.append("<tr>" + "".join(
            f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
    out.append("</table></div>")
    return "".join(out)


def render(md):
    """Markdown to HTML, for the subset these documents use."""
    lines = md.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):                      # fenced code
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>"
                       + html.escape("\n".join(body), quote=False)
                       + "</code></pre>")
            continue

        if re.match(r"^\|.*\|\s*$", line):              # table
            rows = []
            while i < len(lines) and re.match(r"^\|.*\|\s*$", lines[i]):
                rows.append(lines[i])
                i += 1
            # row 1 is the separator (|---|---|) and carries no content
            rows = [r for n, r in enumerate(rows)
                    if not (n == 1 and set(r) <= set("|-: "))]
            out.append(table(rows))
            continue

        if re.match(r"^#{1,4} ", line):                 # heading
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
            i += 1
            continue

        if line.strip() in ("---", "***"):
            out.append("<hr>")
            i += 1
            continue

        if re.match(r"^\s*[-*] ", line):                # list
            items, indent_stack = [], None
            while i < len(lines) and (re.match(r"^\s*[-*] ", lines[i])
                                      or (lines[i].startswith("  ")
                                          and lines[i].strip()
                                          and items)):
                if re.match(r"^\s*[-*] ", lines[i]):
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    if indent_stack is None:
                        indent_stack = indent
                    items.append((indent, lines[i].strip()[2:]))
                else:                                   # wrapped continuation
                    items[-1] = (items[-1][0],
                                 items[-1][1] + " " + lines[i].strip())
                i += 1
            out.append(render_list(items, indent_stack or 0))
            continue

        if not line.strip():
            i += 1
            continue

        para = [line]                                   # paragraph
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,4} |```|\||\s*[-*] |---$)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(x.strip() for x in para))}</p>")

    return "\n".join(out)


def render_list(items, base):
    """Nested unordered list, one level deep — which is all these use."""
    out, open_sub = ["<ul>"], False
    for indent, text in items:
        if indent > base:
            if not open_sub:
                out.append("<ul>")
                open_sub = True
        elif open_sub:
            out.append("</ul>")
            open_sub = False
        out.append(f"<li>{inline(text)}</li>")
    if open_sub:
        out.append("</ul>")
    out.append("</ul>")
    return "".join(out)


# ── the page ────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg:#f4f4f7; --panel:#fff; --ink:#1b1b1f; --muted:#66666e; --line:#e3e3ea;
  --accent:#4f46e5; --code:#f1f1f6; --shadow:0 1px 3px rgba(0,0,0,.07);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#131316; --panel:#1c1c20; --ink:#e6e6ea; --muted:#9a9aa4;
    --line:#2c2c33; --accent:#8b85f5; --code:#26262c;
    --shadow:0 1px 3px rgba(0,0,0,.4);
  }
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.6 -apple-system, system-ui, "Segoe UI", sans-serif;
  -webkit-font-smoothing:antialiased;
}
#wrap { display:flex; min-height:100vh; align-items:flex-start; }
#side {
  width:264px; flex:0 0 264px; position:sticky; top:0; height:100vh;
  overflow-y:auto; background:var(--panel); border-right:1px solid var(--line);
  padding:20px 0 40px;
}
#side h1 { font-size:15px; margin:0 20px 4px; letter-spacing:-.01em; }
#side .sub { font-size:12px; color:var(--muted); margin:0 20px 14px; }
#q {
  width:calc(100% - 40px); margin:0 20px 16px; padding:7px 10px;
  border:1px solid var(--line); border-radius:8px; background:var(--bg);
  color:var(--ink); font-size:13px;
}
#side .grp {
  font-size:11px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--muted); margin:16px 20px 6px;
}
#side a {
  display:block; padding:5px 20px; color:var(--ink); text-decoration:none;
  font-size:13.5px; border-left:2px solid transparent;
}
#side a small { display:block; color:var(--muted); font-size:11.5px; }
#side a:hover { background:var(--bg); }
#side a.on { border-left-color:var(--accent); color:var(--accent);
             background:var(--bg); font-weight:600; }
#side a.on small { color:var(--muted); font-weight:400; }
main { flex:1 1 auto; min-width:0; padding:34px 40px 90px; max-width:1000px; }
section { display:none; }
section.on { display:block; }
h1,h2,h3 { letter-spacing:-.015em; line-height:1.25; }
h1 { font-size:27px; margin:0 0 6px; }
h2 { font-size:18px; margin:30px 0 8px; padding-top:14px;
     border-top:1px solid var(--line); }
h3 { font-size:15px; margin:20px 0 6px; }
p, li { color:var(--ink); }
a { color:var(--accent); }
img { max-width:100%; border-radius:10px; border:1px solid var(--line);
      box-shadow:var(--shadow); display:block; margin:14px 0; }
code { background:var(--code); padding:1px 5px; border-radius:4px;
       font:12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { background:var(--code); padding:12px 14px; border-radius:9px;
      overflow-x:auto; }
pre code { background:none; padding:0; }
.tw { overflow-x:auto; margin:12px 0; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line);
         vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:12px;
     text-transform:uppercase; letter-spacing:.05em; }
hr { border:0; border-top:1px solid var(--line); margin:26px 0; }
blockquote { margin:12px 0; padding:2px 14px; border-left:3px solid var(--line);
             color:var(--muted); }
.meta { color:var(--muted); font-size:13px; margin:0 0 18px; }
@media (max-width: 860px) {
  #wrap { flex-direction:column; }
  #side { position:static; width:100%; flex:none; height:auto;
          border-right:0; border-bottom:1px solid var(--line); }
  main { padding:22px 18px 60px; }
}
"""

JS = """
(function () {
  var links = [].slice.call(document.querySelectorAll('#side a[data-slug]'));
  function show(slug) {
    var found = false;
    [].forEach.call(document.querySelectorAll('section'), function (s) {
      var on = s.id === slug;
      s.classList.toggle('on', on);
      if (on) found = true;
    });
    links.forEach(function (a) {
      a.classList.toggle('on', a.dataset.slug === slug);
    });
    if (found) { document.scrollingElement.scrollTop = 0; }
    return found;
  }
  function fromHash() {
    var slug = (location.hash || '').replace(/^#/, '') || 'overview';
    if (!show(slug)) { show('overview'); }
  }
  window.addEventListener('hashchange', fromHash);
  fromHash();

  var q = document.getElementById('q');
  q.addEventListener('input', function () {
    var t = q.value.trim().toLowerCase();
    links.forEach(function (a) {
      a.style.display = !t || a.textContent.toLowerCase().indexOf(t) >= 0
        ? '' : 'none';
    });
    [].forEach.call(document.querySelectorAll('#side .grp'), function (g) {
      var any = false, n = g.nextElementSibling;
      while (n && n.classList.contains('grp') === false) {
        if (n.tagName === 'A' && n.style.display !== 'none') { any = true; }
        n = n.nextElementSibling;
      }
      g.style.display = any ? '' : 'none';
    });
  });
})();
"""


def plugin_version():
    plist = os.path.join(HERE, "Dashboards.indigoPlugin", "Contents",
                         "Info.plist")
    try:
        return subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print :PluginVersion", plist],
            capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def build():
    if not os.path.isdir(PAGES_DIR):
        sys.exit(f"no {PAGES_DIR} — nothing to build")
    os.makedirs(SITE_DIR, exist_ok=True)
    version = plugin_version()

    missing = [s for s, _, _ in PAGES
               if not os.path.exists(os.path.join(PAGES_DIR, s + ".md"))]
    if missing:
        sys.exit("no write-up for: " + ", ".join(missing))
    # A page file nobody lists would silently never appear in the sidebar,
    # which is the failure that looks most like success.
    listed = {s for s, _, _ in PAGES}
    stray = sorted(f[:-3] for f in os.listdir(PAGES_DIR)
                   if f.endswith(".md") and f[:-3] not in listed)
    if stray:
        sys.exit("write-up not in PAGES, so it would not appear: "
                 + ", ".join(stray))
    # Same rule for the images, and it earned its place: 21 files named
    # "<page> 2.png" — stale duplicates of an earlier sweep — sat in this
    # directory long enough to be committed. A one-off check before the commit
    # is not enough, because anything can appear after it runs; the build is
    # the last thing to touch this directory, so the check belongs here.
    shot_stray = sorted(f for f in os.listdir(SHOTS)
                        if f.endswith(".png") and f[:-4] not in listed)
    if shot_stray:
        sys.exit("screenshot(s) not in PAGES — stale duplicates or a bad "
                 "alias, delete or rename before committing: "
                 + ", ".join(shot_stray))

    side = ['<h1>Dashboards</h1>',
            f'<p class="sub">Page reference · v{version}</p>',
            '<input id="q" type="search" placeholder="Filter pages" '
            'autocomplete="off">',
            '<div class="grp">Overview</div>',
            '<a href="#overview" data-slug="overview">About this reference'
            '<small>How the captures were made</small></a>']
    for group in GROUP_ORDER:
        side.append(f'<div class="grp">{html.escape(group)}</div>')
        for slug, grp, blurb in PAGES:
            if grp != group:
                continue
            side.append(
                f'<a href="#{slug}" data-slug="{slug}">{slug}.html'
                f'<small>{html.escape(blurb)}</small></a>')

    body = []
    readme = os.path.join(EXAMPLES, "README.md")
    overview = open(readme, encoding="utf-8").read() if os.path.exists(readme) \
        else "# Examples"
    # The README's own page table is a list of links to the markdown files,
    # which are the wrong target from inside the site — the sidebar is the
    # index here, so the table is dropped rather than shown broken.
    overview = re.sub(r"<!-- PAGES:START -->.*?<!-- PAGES:END -->", "",
                      overview, flags=re.S)
    body.append(f'<section id="overview">{render(overview)}</section>')

    for slug, _, _ in PAGES:
        md = open(os.path.join(PAGES_DIR, slug + ".md"), encoding="utf-8").read()
        body.append(f'<section id="{slug}">{render(md)}</section>')

    doc = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboards page reference</title>
<style>{CSS}</style>
</head>
<body>
<div id="wrap">
<nav id="side">{''.join(side)}</nav>
<main>{''.join(body)}</main>
</div>
<script>{JS}</script>
</body>
</html>
"""
    out = os.path.join(SITE_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)

    write_readme_table(readme)
    print(f"wrote {os.path.relpath(out, HERE)} "
          f"({len(doc) / 1024:.0f} kB, {len(PAGES)} pages, v{version})")
    shots = [s for s, _, _ in PAGES
             if not os.path.exists(os.path.join(SHOTS, s + ".png"))]
    if shots:
        print("WARNING — no screenshot for: " + ", ".join(shots))


def write_readme_table(readme):
    """Regenerate the README's page table between its markers."""
    if not os.path.exists(readme):
        return
    src = open(readme, encoding="utf-8").read()
    if "<!-- PAGES:START -->" not in src:
        return
    rows = ["| Page | Notes | Height | What it is |", "|---|---|---|---|"]
    for slug, _, blurb in PAGES:
        png = os.path.join(SHOTS, slug + ".png")
        height = "—"
        if os.path.exists(png):
            height = f"{png_height(png)}px"
        rows.append(f"| `{slug}.html` | [{slug}](pages/{slug}.md) | {height} "
                    f"| {blurb} |")
    table_md = "\n".join(rows)
    # The newlines are OPTIONAL in the pattern and supplied in the replacement.
    # Requiring them meant an empty pair of markers on consecutive lines never
    # matched, and re.sub's answer to no match is to change nothing and say
    # nothing — the table stayed empty through a build that reported success.
    src, hits = re.subn(
        r"<!-- PAGES:START -->\n?.*?\n?<!-- PAGES:END -->",
        lambda m: "<!-- PAGES:START -->\n" + table_md + "\n<!-- PAGES:END -->",
        src, flags=re.S)
    if hits != 1:
        sys.exit(f"README markers matched {hits} times, expected 1 — "
                 f"the page table was not written")
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(src)


def png_height(path):
    """Height straight out of the PNG header — no image library needed."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    return int.from_bytes(head[20:24], "big")


if __name__ == "__main__":
    build()
