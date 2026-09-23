// Filename:    test_camera_still_period.mjs
// Description: The cameras page works out a still tile's refresh period in ONE
//              function, stillPeriodFor, used by both the poller and the chip
//              on the tile (v3.25.0). The chip had its own copy with no
//              reflector branch, so over the reflector it read "every 1 s"
//              while the tile really polled every 3 or 10 seconds.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0
//
// Run: node tests/test_camera_still_period.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                                      "Resources", "static", "pages", "cameras.html"), "utf8");

let failed = 0;
function check(name, ok) { console.log((ok ? "PASS" : "FAIL") + "  " + name); if (!ok) failed++; }

function constOf(name) {
    const m = new RegExp(`const ${name}\\s*=\\s*(\\d+)`).exec(src);
    if (!m) throw new Error("no " + name);
    return Number(m[1]);
}
const start = src.indexOf("function stillPeriodFor(");
check("the page has one stillPeriodFor", start > 0 && src.indexOf("function stillPeriodFor(", start + 1) < 0);
let depth = 0, end = src.indexOf("{", start);
for (let i = end; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) { end = i + 1; break; }
}
const C = {};
C.POLL_MS = 2000;      // config-driven on the page (pollSeconds), so fixed here
for (const k of ["REMOTE_POLL_MS", "DEGRADED_POLL_MS", "FOCUS_POLL_MS",
                 "REFLECTOR_POLL_MS", "REFLECTOR_FOCUS_MS"]) C[k] = constOf(k);
const ctx = { ...C, LINK: "home", focusedHost: "cam1" };
vm.createContext(ctx);
vm.runInContext(src.slice(start, end), ctx);
const f = (host, st) => vm.runInContext(`stillPeriodFor(${JSON.stringify(host)}, ${JSON.stringify(st)})`, ctx);

ctx.LINK = "reflector";
check("reflector, focused tile", f("cam1", {}) === C.REFLECTOR_FOCUS_MS);
check("reflector, other tile", f("cam2", {}) === C.REFLECTOR_POLL_MS);
ctx.LINK = "vpn";
check("vpn, focused tile", f("cam1", {}) === C.FOCUS_POLL_MS);
check("vpn, other tile", f("cam2", {}) === C.REMOTE_POLL_MS);
ctx.LINK = "home";
check("home", f("cam2", {}) === C.POLL_MS);
check("a degraded tile is slow whatever the link", f("cam1", { autoDegraded: true }) === C.DEGRADED_POLL_MS);

// Both the poller and the chip go through it: no second hand-written ladder.
const ladders = (src.match(/LINK === "home" \? POLL_MS/g) || []).length;
check("no second copy of the ladder (only stillPeriodFor and the footer's own)", ladders <= 2);
check("the chip uses it", /const stillPeriod = stillPeriodFor\(host, st\)/.test(src));
check("the poller uses it", /const period = stillPeriodFor\(host, st\)/.test(src));

process.exit(failed ? 1 : 0);
