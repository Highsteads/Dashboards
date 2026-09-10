// Filename:    test_camera_frame_age.mjs
// Description: Contract test for the per-tile frame-age readout and the
//              honest Updated clock.
//
//              WHY THIS EXISTS
//              Every latency conversation about the cameras page ran on
//              guesses: the page-wide "Updated" clock was stamped by ANY
//              tile's load (including synthetic ones), and nothing reported
//              the age of the frame being looked at. The readout closes
//              that. Design note: the skew-free source (server Date header −
//              Last-Modified) is IMPOSSIBLE here — measured 30-Jul-2026, IWS
//              sends no Date header on static responses — so age is client
//              clock vs Last-Modified, with a rolling-minimum age-at-receipt
//              as the clock-skew tell (a frame cannot arrive before it was
//              written). These tests pin the formula, the 304 rule, the tell,
//              and exactly who may stamp the Updated clock.
// Author:      CliveS & Claude Fable 5
// Date:        30-07-2026
// Version:     1.0
//
// Run: node tests/test_camera_frame_age.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "cameras.html");
const src = fs.readFileSync(SRC, "utf8");

// Strip comments so a rule can never be satisfied by prose that describes it.
const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function fn(name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in cameras.html`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}
const countMatches = (hay, re) => (hay.match(re) || []).length;

let pass = 0, fail = 0;
const check = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + detail : ""}`);
};

// ── Execute the real age functions ─────────────────────────────
const ctx = { Math, Date, localStorage: { getItem: () => null } };
vm.createContext(ctx);
vm.runInContext(fn("frameAgeMs") + "\n" + fn("fmtAge") + "\n" + fn("noteAgeAtReceipt")
                + "\nlet _minAgeAtReceipt = null;"
                + "\nglobalThis.frameAgeMs = frameAgeMs; globalThis.fmtAge = fmtAge;", ctx);

console.log("\nframeAgeMs, executed for real");
{
    const NOW = 1_800_000_000_000;
    check(ctx.frameAgeMs(null, NOW) === null, "null tile state -> null");
    check(ctx.frameAgeMs({}, NOW) === null, "no dated frame yet -> null",
          "an undated frame must show a bound, not a number");
    check(ctx.frameAgeMs({ frameModMs: NOW - 2300 }, NOW) === 2300,
          "age is now minus the frame's own Last-Modified");
    check(ctx.frameAgeMs({ frameModMs: NOW + 900 }, NOW) === 0,
          "clock skew cannot show a negative age",
          "sub-second NTP disagreement is real; a negative age readout is not");
    check(ctx.fmtAge(2340) === "2.3s" && ctx.fmtAge(-50) === "0.0s",
          "fmtAge renders tenths and clamps below zero");
}

console.log("\nthe 304 rule: nothing new means the picture keeps aging");
{
    const still = fn("startStill");
    const s304 = still.indexOf("status === 304");
    const promote = still.indexOf("st.frameModMs = st._mod200");
    check(s304 >= 0 && promote > s304,
          "frameModMs is only promoted in the delivered-frame path, after the 304 return");
    const dateSites = countMatches(code, /st\.frameModMs\s*=(?!=)/g);
    check(dateSites === 1,
          "exactly one place may date a frame",
          `found ${dateSites} — a 304 or error re-dating the on-screen frame lies about freshness`);
    check(/st\._mod200\s*!=\s*null\s*&&\s*!isNaN\(st\._mod200\)/.test(still),
          "an unparseable Last-Modified never becomes a date");
}

console.log("\nthe skew tell");
{
    check(/noteAgeAtReceipt\(st\.lastFrameAt - st\.frameModMs\)/.test(fn("startStill")),
          "every delivered frame feeds the rolling minimum");
    check(/Math\.min\(_minAgeAtReceipt,/.test(fn("noteAgeAtReceipt")),
          "the tell is a MINIMUM, not a latest",
          "the minimum is what bounds the skew; the latest is just one sample");
    const ages = fn("tickAges");
    check(/_minAgeAtReceipt\s*<\s*-1500/.test(ages),
          "the clock? flag asserts the comparison, not just the variable name");
}

console.log("\nwho may stamp the Updated clock");
{
    // Exactly three stampers, each a REAL frame arriving: the still blob
    // path, the live onload guarded to live mode, and the webrtc
    // first-frame callback. Count the call sites — a "appears somewhere"
    // assert survives a stripped site.
    const sites = countMatches(code, /(?<!function )markRefreshed\(\)/g);
    check(sites === 3, "exactly three markRefreshed call sites",
          `found ${sites}`);
    const still = fn("startStill");
    check(/markRefreshed\(\)/.test(still),
          "one is the still blob path");
    const loadHandler = code.slice(code.indexOf("onFrameLoad = () => {"),
                                   code.indexOf("onFrameError = () => {"));
    check(/if\s*\(\s*st\.mode\s*===\s*["']live["']\s*\)\s*markRefreshed\(\)/.test(loadHandler),
          "another is the onload handler, guarded to live mode",
          "an unguarded onload stamp fires for objectURL swaps of already-stamped frames");
    const rtc = fn("startWebrtc");
    const ffStart = rtc.indexOf("const firstFrame");
    check(ffStart >= 0 && rtc.indexOf("markRefreshed()", ffStart) > ffStart,
          "the third is the webrtc FIRST-FRAME callback, nowhere earlier",
          `startWebrtc must not stamp before a frame renders`);
    check(rtc.indexOf("markRefreshed()") >= ffStart,
          "…and startWebrtc has no stamp outside that callback");
    check(!/markRefreshed/.test(fn("startLive")),
          "starting a stream is not a frame — startLive no longer stamps");
}

console.log("\nrendering");
{
    check(/<span class="age"><\/span>/.test(src),
          "the tile template carries the age chip");
    check(/ageEl\s*=\s*wrap\.querySelector\(["']\.age["']\)/.test(code),
          "and buildGrid wires it to tile state");
    const ages = fn("tickAges");
    check(/!dbg\s*&&\s*host\s*!==\s*focusedHost/.test(ages),
          "without debug, only the focused tile shows an age");
    check(/st\.lastChangeAt/.test(ages) && /["']live · ["']/.test(ages),
          "a live tile shows time since last visible CHANGE, labelled as such",
          "live has no Last-Modified — pretending otherwise is a different lie");
    check(/age ≥/.test(fn("tickAges")),
          "an undated frame shows a lower bound, not a made-up number");
    check(/tickRefreshStatus\(\);\s*tickAges\(\);/.test(code),
          "the age ticker runs on the same 1 s beat as the clock");
    check(/dash_cam_debug/.test(code) && /policyLine\.addEventListener\(["']click["']/.test(code),
          "tapping the footer policy line toggles the debug view");
}

console.log("\na missed connect window joins the retry ladder");
{
    const live = fn("startLive");
    const timeoutBlock = live.slice(live.indexOf("st.liveTimeout = setTimeout"));
    check(/degradeToStill\(host,/.test(timeoutBlock),
          "the 10 s connect timeout routes through degradeToStill",
          "a bare startStill left autoDegraded unset and the tile was never retried");
    check(!/startStill\(host\)/.test(timeoutBlock),
          "…and the bare startStill call is gone from that path");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
