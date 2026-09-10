// Filename:    test_shared_ui_present.mjs
// Description: Every user-facing page must load dashboards-ui.js (v2.97.0).
//              It is not optional decoration any more: it carries the press
//              feedback CliveS asked for on every page, and the bandwidth
//              probe that decides whether a camera tile streams. room.html
//              called DashUI.streamBudget() while never loading the file, and
//              the call is guarded — so the room pages silently measured
//              nothing and never showed a live camera. A guard that hides a
//              missing dependency is exactly why this is asserted rather than
//              left to be noticed.
// Author:      CliveS & Claude Opus 5
// Date:        02-09-2026
// Version:     1.0
//
// Run: node tests/test_shared_ui_present.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages");
// demo/setup/webrtc-test are standalone utilities; guest.html is the pared-down
// guest view and deliberately loads as little as it can.
const EXEMPT = new Set(["demo.html", "setup.html", "webrtc-test.html", "guest.html"]);

let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

const pages = fs.readdirSync(DIR).filter(f => f.endsWith(".html")).sort();
console.log("\nevery page carries the shared UI library");
let missing = [];
for (const f of pages) {
    if (EXEMPT.has(f)) continue;
    if (!fs.readFileSync(path.join(DIR, f), "utf8").includes("dashboards-ui.js")) missing.push(f);
}
check("no page is missing dashboards-ui.js", missing.length === 0, missing.join(", "));
check("and the check actually looked at some pages", pages.length > 10,
      "a glob that matches nothing passes every assertion after it");

console.log("\nanything that USES DashUI must also load it");
for (const f of pages) {
    const s = fs.readFileSync(path.join(DIR, f), "utf8");
    if (!/\bDashUI\./.test(s)) continue;
    check(f + " loads what it calls", s.includes("dashboards-ui.js"),
          "the calls are guarded, so a missing file fails silently");
}

process.exit(failed ? 1 : 0);
