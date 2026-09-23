// Filename:    test_escape_helpers.mjs
// Description: DashUI.esc escapes all five characters that matter, DashUI.ago
//              says "how long ago" one way (v3.28.0), and no page
//              escapes through textContent -> innerHTML any more (v3.25.0).
//              That trick leaves quote marks alone, and the pages put its
//              output inside attributes, so a device or camera name holding a
//              double quote broke the markup around it.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0
//
// Run: node tests/test_escape_helpers.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");

let failed = 0;
function check(name, ok) { console.log((ok ? "PASS" : "FAIL") + "  " + name); if (!ok) failed++; }

const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math };
win.window = win;
vm.createContext(win);
vm.runInContext(fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8"), win);
const esc = win.DashUI.esc;

check("escapes all five", esc(`<a href="x" title='y'>&</a>`) ===
      "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
check("null and undefined are empty", esc(null) === "" && esc(undefined) === "");
check("numbers pass through as text", esc(42) === "42");
check("a quote cannot close an attribute", !esc('Dave "The Shed" Light').includes('"'));

const DOM_ESCAPE = /document\.createElement\(["']div["']\)\s*;?\s*\w+\.textContent\s*=/;
const offenders = fs.readdirSync(PAGES).filter(f => f.endsWith(".html"))
    .filter(f => DOM_ESCAPE.test(fs.readFileSync(path.join(PAGES, f), "utf8")));
check("no page escapes through textContent -> innerHTML" + (offenders.length ? ": " + offenders.join(", ") : ""),
      offenders.length === 0);

// ── DashUI.ago (v3.28.0): one wording for "how long ago", rounding down ──
const ago = win.DashUI.ago;
const NOW = Date.parse("2026-09-23T12:00:00Z");
const at = (mins) => new Date(NOW - mins * 60000).toISOString();
check("under a minute is 'just now'", ago(at(0.5), { now: NOW }) === "just now");
check("minutes", ago(at(12), { now: NOW }) === "12m ago");
check("1 h 40 m reads 1h, never 2h", ago(at(100), { now: NOW }) === "1h ago");
check("days, rounded down", ago(at(60 * 47), { now: NOW }) === "1d ago");
check("an age in ms works the same", ago(100 * 60000) === "1h ago");
check("words: seconds", ago(45000, { words: true }) === "45 seconds");
check("words: singular", ago(60000 * 60, { words: true }) === "1 hour");
check("words: 2 h 30 m is 2 hours", ago(150 * 60000, { words: true }) === "2 hours");
check("not a time: the value itself by default", ago("soon") === "soon");
check("not a time: or what the page asks for", ago("", { bad: "—" }) === "—");
check("a clock that ran backwards is not negative", ago(-5000) === "just now");

// No page keeps its own copy of the ladder any more.
const LADDER = /return\s+\w+\s*\+\s*"m ago"/;
const copies = fs.readdirSync(PAGES).filter(f => f.endsWith(".html"))
    .filter(f => LADDER.test(fs.readFileSync(path.join(PAGES, f), "utf8")));
check("no page carries its own 'Nm ago' ladder" + (copies.length ? ": " + copies.join(", ") : ""), copies.length === 0);

process.exit(failed ? 1 : 0);
