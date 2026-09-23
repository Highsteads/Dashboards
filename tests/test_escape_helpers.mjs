// Filename:    test_escape_helpers.mjs
// Description: DashUI.esc escapes all five characters that matter, and no page
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

process.exit(failed ? 1 : 0);
