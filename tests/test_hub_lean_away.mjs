// Filename:    test_hub_lean_away.mjs
// Description: Contract test for the hub's REGION POLICY (v2.97.0). The light
//              hub is GONE: the landing page shows every region on every link,
//              because a region that quietly removes itself reads as a broken
//              one — it was reported as "the 4 cameras have disappeared" the
//              first time, and the notice added to explain it did not stop the
//              next person reading a gap as a fault.
//
//              WHAT REPLACED IT, AND WHAT THIS LOCKS
//              1. NO LEAN MODE. There is no light-hub notice, no stored
//                 override, and startHeavyRefreshers must run whatever the
//                 measured link class turns out to be — including a failed
//                 measurement, which used to be the "stay lean" case.
//              2. THE SAVING MOVED TO THE CAMERAS, where the data actually is:
//                 how many tiles stream is decided by MEASURED BANDWIDTH
//                 (DashUI.streamBudget), not by an address and not by latency.
//              3. The heavy refreshers stay idempotent — _goFull can be called
//                 more than once, and stacking a second set of intervals would
//                 double every poll for the life of the page.
// Author:      CliveS & Claude Opus 5
// Date:        02-09-2026
// Version:     2.3 (v3.45.0: live video on the strip is decided by measured speed, see test_live_bandwidth.mjs); 2.2 (v3.35.0: the strip is stills only, so the budget checks became stills checks); 2.1 (v3.26.0: the constant-false _leanHub went; this now checks it stays gone)
//
// Run: node tests/test_hub_lean_away.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
const src = fs.readFileSync(PAGE, "utf8");

function extractFn(s, name) {
    const start = s.indexOf("function " + name + "(");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}


console.log("\nthe light hub is gone, root and branch");
check("no light-hub notice element", !/id="hub-lean-note"/.test(src),
      "the element the whole feature hung off");
check("no notice renderer", !/_renderLeanNote/.test(src));
check("no lean CSS left behind", !/\.hub-lean-note/.test(src));
check("no lean-mode machinery left at all (v3.26.0)",
      !/_leanHub|applyHubLayout|HEAVY_REGIONS|stopHeavyRefreshers/.test(src),
      "a switch fixed at off since v2.97.0 is dead code, not a safeguard");

console.log("\n_goFull shows everything, on every verdict");
{
    const fn = extractFn(src, "_goFull");
    const calls = [];
    const ctx = {
        _heavyStarted: false,
        startHeavyRefreshers: () => calls.push("heavy"),
        console: { warn() {} },
    };
    vm.createContext(ctx);
    vm.runInContext(fn + "\n_goFull();", ctx);
    check("_goFull starts the heavy refreshers", calls.includes("heavy"));
    check("the page calls _goFull on a failed measurement too",
          /\.catch\(\(\) => \{ _goFull\(\); \}\)/.test(src),
          "unknown used to mean lean, which hid the cameras on a slow probe");
}

console.log("\nthe strip's stills (v3.35.0; live video over them since v3.45.0 is test_live_bandwidth.mjs)");
check("no live MJPEG address is built on the hub", !/mjpegPort|mjpegPath/.test(src),
      "four live tiles were about 17 Mbit/s on the landing page");
check("no stream budget machinery left", !/_liveBudget|_applyStreamBudget|streamBudget|_hubDemoteTile/.test(src));
check("frames are fetched only when changed, and cross-faded (DashUI.refreshStill)", /DashUI\.refreshStill\(img, next\)/.test(src));
check("the poll rate still follows the MEASURED link",
      /const link\s+= _measuredLink \|\| \(guess === "home" \? "vpn" : guess\);/.test(src) &&
      // The 2 / 3 / 15 s rule moved into DashUI.stillPollMs (24-09-2026) so
      // the room page shares it; test_page_shared_helpers pins the values.
      /const pollMs = DashUI\.stillPollMs\(link\);/.test(src),
      "a guessed LAN address may be a Tailscale route");
check("the strip is drawn after the measurement lands",
      /\.then\(cls => \{ _measuredLink = cls; _goFull\(\); \}\)/.test(src));

console.log("\nstill idempotent");
{
    const fn = extractFn(src, "startHeavyRefreshers");
    let n = 0;
    const ctx = {
        _heavyStarted: false, _heavyTimers: [],
        _refreshStringHours: () => {}, _refreshInsights: () => {}, _refreshLogWatch: () => {}, _refreshCamHealth: () => {},
        renderCamerasOnce: () => { n++; return Promise.resolve(); }, setInterval: () => 0, console,
    };
    vm.createContext(ctx);
    vm.runInContext(fn + "\nstartHeavyRefreshers(); startHeavyRefreshers();", ctx);
    check("calling it twice renders the strip once", n === 1);
}

done();
