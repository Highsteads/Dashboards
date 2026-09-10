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
// Version:     2.0
//
// Run: node tests/test_hub_lean_away.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

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

let failed = 0;
function check(name, ok, why) {
    console.log((ok ? "  ok   " : "  FAIL ") + name + (why ? "   " + why : ""));
    if (!ok) failed++;
}

console.log("\nthe light hub is gone, root and branch");
check("no light-hub notice element", !/id="hub-lean-note"/.test(src),
      "the element the whole feature hung off");
check("no notice renderer", !/_renderLeanNote/.test(src));
check("no lean CSS left behind", !/\.hub-lean-note/.test(src));
check("_leanHub is a constant false, not a decision",
      /let _leanHub = false;/.test(src),
      "applyHubLayout still reads it, so it has to be false rather than absent");

console.log("\n_goFull shows everything, on every verdict");
{
    const fn = extractFn(src, "_goFull");
    const calls = [];
    const ctx = {
        _leanHub: true, _heavyStarted: false,
        applyHubLayout: () => calls.push("layout"),
        startHeavyRefreshers: () => calls.push("heavy"),
        stopHeavyRefreshers: () => calls.push("stop"),
        console: { warn() {} },
    };
    vm.createContext(ctx);
    vm.runInContext(fn + "\n_goFull(null);", ctx);          // measurement FAILED
    check("a failed measurement still starts the heavy refreshers",
          calls.includes("heavy") && ctx._leanHub === false,
          "unknown used to mean lean, which hid the cameras on a slow probe");
    calls.length = 0;
    vm.runInContext("_goFull('reflector');", ctx);
    check("so does a reflector verdict", calls.includes("heavy") && ctx._leanHub === false);
    check("and nothing is ever stopped to save data", !calls.includes("stop"),
          "the cameras throttle themselves now — the page does not go away");
}

console.log("\nthe saving moved to the cameras, and it is MEASURED");
check("the strip asks DashUI.streamBudget", /DashUI\.streamBudget\(\)/.test(src),
      "bandwidth, not an address and not latency");
check("the budget is null until measured, and null means no streams",
      /let _liveBudget = null;/.test(src) && /_liveBudget == null \? 0 : _liveBudget/.test(src),
      "boot must not open a stream it has not yet shown the link can carry");
check("a changed budget re-renders the strip",
      /if \(n === _liveBudget\) return;[\s\S]{0,200}renderCamerasOnce\(\);/.test(src),
      "THE re-render: without it the strip keeps the pre-measurement guess for ever");
check("returning to the tab re-measures", /DashUI\.forgetBw\(\);\s*\n\s*_applyStreamBudget\(\);/.test(src),
      "the network may be a different one now");
check("the reflector is zero whatever the measurement says",
      /link === "reflector" \? 0 :/.test(src),
      "the stream port is not fronted by the reflector at all");

console.log("\nstill idempotent");
{
    const fn = extractFn(src, "startHeavyRefreshers");
    let n = 0;
    const ctx = {
        _heavyStarted: false, _heavyTimers: [],
        _refreshStringHours: () => {}, _refreshInsights: () => {}, _refreshLogWatch: () => {},
        renderCamerasOnce: () => n++, setInterval: () => 0,
    };
    vm.createContext(ctx);
    vm.runInContext(fn + "\nstartHeavyRefreshers(); startHeavyRefreshers();", ctx);
    check("calling it twice renders the strip once", n === 1);
}

process.exit(failed ? 1 : 0);
