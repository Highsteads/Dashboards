// Filename:    test_camera_boot_policy.mjs
// Description: Contract test for the camera page's BOOT POLICY and the
//              degrade-state machinery around it.
//
//              WHY THIS EXISTS
//              The page's address is always the LAN address, and over a
//              Tailscale subnet route that address says "home" from a 5G
//              connection. Booting on it started six MJPEG streams into a
//              mobile link (~17 Mbit/s of video the correcting probes then
//              queued behind), and if the 9 s stall watchdog fired before the
//              measurement landed, tiles latched autoDegraded and sat at 5 s
//              polls indefinitely. The fix has three legs, each pinned here:
//                1. boot on the last MEASURED verdict (cached, bounded 60 s),
//                   conservative all-stills when there is none;
//                2. every policy re-layout clears the degrade state, and a
//                   tile that loses its live entitlement has its still chain
//                   REBUILT, not just its flag cleared;
//                3. a paused tile can never fire a synthetic "frame arrived"
//                   (pauseTile detaches handlers before poking src), and a
//                   wedged still fetch is aborted rather than holding the
//                   in-flight guard forever.
//              Mutation lessons applied throughout: assert the COMPARISON,
//              not the constant's name; COUNT call sites.
// Author:      CliveS & Claude Fable 5
// Date:        30-07-2026
// Version:     1.0
//
// Run: node tests/test_camera_boot_policy.mjs   (exit 0 = pass)

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

// ── Execute the real bootPolicy against stubs ──────────────────
// Extracted source, run for real: the cache decision is behavioural, and a
// regex cannot tell "<=" from "always true".
function runBoot({ addrClass, stored, now }) {
    const calls = [];
    const dashUI = { linkClass: () => addrClass };
    const ctx = {
        window: { DashUI: dashUI },
        DashUI: dashUI,
        JSON,
        Date: { now: () => now },
        localStorage: { getItem: () => stored, setItem: () => {} },
        POLICY_CACHE_KEY: "dash_cam_policy",
        POLICY_CACHE_MS: 60000,
        setPolicy: (cls, ms) => calls.push([cls, ms]),
    };
    vm.createContext(ctx);
    vm.runInContext(fn("bootPolicy") + "\nbootPolicy();", ctx);
    return calls;
}
const NOW = 1_800_000_000_000;
const cacheJson = (cls, ms, atDelta) =>
    JSON.stringify({ cls, ms, at: NOW - atDelta });

console.log("\nbootPolicy decides from the cached MEASURED verdict, executed for real");
{
    check(JSON.stringify(runBoot({ addrClass: "home", stored: null, now: NOW }))
              === JSON.stringify([["vpn", null]]),
          "no cache -> conservative all-stills, even on a home address",
          "the home address is exactly what lies over a Tailscale subnet route");
    check(JSON.stringify(runBoot({ addrClass: "home",
                                   stored: cacheJson("home", 21, 1000), now: NOW }))
              === JSON.stringify([["home", 21]]),
          "a fresh cached verdict is trusted");
    check(JSON.stringify(runBoot({ addrClass: "vpn",
                                   stored: cacheJson("home", 116, 1000), now: NOW }))
              === JSON.stringify([["home", 116]]),
          "the cache beats the address class for non-reflector addresses");
    check(JSON.stringify(runBoot({ addrClass: "home",
                                   stored: cacheJson("home", 21, 61000), now: NOW }))
              === JSON.stringify([["vpn", null]]),
          "a cache older than 60 s is IGNORED",
          "an unbounded 'home' verdict re-opens six streams on 5G hours later");
    check(JSON.stringify(runBoot({ addrClass: "reflector",
                                   stored: cacheJson("home", 21, 1000), now: NOW }))
              === JSON.stringify([["reflector", undefined]]),
          "a reflector address is authoritative, whatever the cache says",
          "no probe can make a reflector address local");
    check(JSON.stringify(runBoot({ addrClass: "home", stored: "{corrupt", now: NOW }))
              === JSON.stringify([["vpn", null]]),
          "a corrupt cache falls through to conservative, not a throw");
}

console.log("\nthe boot path itself can no longer act on the address guess");
{
    check(!/setPolicy\(\s*LINK\s*\)/.test(code),
          "the bare setPolicy(LINK) boot call is gone");
    const bootStart = code.indexOf("buildGrid();");
    const bootEnd   = code.indexOf("startBandwidthPoll()", bootStart);
    const boot = code.slice(bootStart, bootEnd);
    check(bootStart >= 0 && bootEnd > bootStart && /relayoutAll\(\)/.test(boot),
          "boot lays out through relayoutAll under the boot policy");
    check(!/startLive\(/.test(boot),
          "no direct startLive in the boot block",
          "live tiles must only ever come from a decided policy");
    const bp = fn("bootPolicy");
    check(/Date\.now\(\)\s*-\s*c\.at\s*<=\s*POLICY_CACHE_MS/.test(bp),
          "the cache-age COMPARISON exists in bootPolicy",
          "a mutant replacing the check with `true` must not survive");
    check(/DashUI\.linkClass\s*\(\)/.test(bp) && !/[^.\w]LINK[^\w]/.test(bp),
          "bootPolicy re-derives the ADDRESS class, never reads mutable LINK",
          "LINK holds the last measurement — exactly what must not leak into a boot");
}

console.log("\nmeasureAndApply feeds the cache and is single-flight");
{
    const ma = fn("measureAndApply");
    const cacheAt = ma.indexOf("cachePolicy(effective, ms)");
    // v2.95.1: setPolicy is the ONE owner of the derivation. It is applied
    // unconditionally and the relayout decision compares the tuple it sets
    // (LINK, LIVE_POOL_SIZE, WEBRTC_FOCUS) before and after — a live COUNT
    // compare could never see the WebRTC band engage, because that band has
    // a live count of zero, the same as the conservative boot policy.
    const applyAt  = ma.indexOf("setPolicy(effective, ms)");
    const decideAt = ma.indexOf("before.some(");
    check(cacheAt >= 0, "the verdict is cached");
    check(decideAt >= 0 && cacheAt < decideAt,
          "…and cached BEFORE the changed-policy check",
          "an unchanged verdict must still refresh the cache");
    check(applyAt >= 0 && applyAt < decideAt,
          "setPolicy is applied unconditionally, then the tuple is compared",
          "a count compare misses the WebRTC band, whose live count is zero");
    check(/const before = \[LINK, LIVE_POOL_SIZE, WEBRTC_FOCUS\]/.test(ma),
          "the compared tuple includes WEBRTC_FOCUS");
    check(/if\s*\(\s*_measureInflight\s*\)\s*return\s*_measureInflight/.test(ma),
          "concurrent callers share the in-flight run");
    check(/\.finally\(\s*\(\)\s*=>\s*\{\s*_measureInflight\s*=\s*null/.test(ma),
          "the in-flight marker clears on every exit path");
    check(/relayoutAll\(\)/.test(ma) && !/startLive\(/.test(ma),
          "a policy change re-lays-out through relayoutAll");
}

console.log("\nevery policy re-layout clears the degrade state");
{
    const rl = fn("relayoutAll");
    check(/st\.autoDegraded\s*=\s*false/.test(rl), "autoDegraded cleared");
    check(/st\.degradeCount\s*=\s*0/.test(rl),     "degradeCount cleared");
    check(/st\.retryAfterMs\s*=\s*0/.test(rl),     "retryAfterMs cleared");
    // Count the CALL sites (the definition doesn't count): boot,
    // visibilitychange resume, measureAndApply. A stripped call site is
    // invisible to a "does it appear somewhere" test.
    const callSites = countMatches(code, /(?<!function )relayoutAll\(\)/g);
    check(callSites === 3,
          "exactly three relayoutAll call sites (boot, resume, measure)",
          `found ${callSites}`);
    const vis = code.slice(code.indexOf('"visibilitychange"'),
                           code.indexOf("buildGrid();"));
    const a = vis.indexOf("bootPolicy()"), b = vis.indexOf("relayoutAll()"),
          c = vis.indexOf("measureAndApply()");
    check(a >= 0 && b > a && c > b,
          "resume re-decides policy BEFORE laying out, then re-measures",
          "resuming into the last policy was six live streams on 5G");
    check(/document\.hidden\s*\)\s*\{\s*stopAll\(\);\s*return/.test(vis),
          "hiding the tab still pauses everything");
}

console.log("\na tile that loses its live entitlement is rebuilt, not just unflagged");
{
    const tr = fn("tryRestoreLive");
    const branch = tr.slice(tr.indexOf("!mayHoldLive"), tr.indexOf("st.lastSig"));
    const clearAt = branch.indexOf("st.autoDegraded = false");
    const rebuildAt = branch.indexOf("startStill(host)");
    check(clearAt >= 0 && rebuildAt > clearAt,
          "not-entitled path clears the flag AND restarts the still chain",
          "the old chain captured DEGRADED_POLL_MS in its closure — 5 s forever");
    check(/if\s*\(\s*!st\.paused\s*&&\s*st\.mode\s*===\s*["']still["']\s*\)\s*startStill/.test(branch),
          "…but never restarts a paused tile");
}

console.log("\na wedged still fetch cannot hold the in-flight guard forever");
{
    const still = fn("startStill");
    check(/new AbortController\(\)/.test(still), "AbortController created per fetch");
    check(/setTimeout\(\s*\(\)\s*=>\s*ctrl\.abort\(\)\s*,\s*STILL_FETCH_TIMEOUT_MS\s*\)/.test(still),
          "the abort is armed with the timeout constant");
    check(/signal:\s*ctrl\.signal/.test(still),
          "and the signal is actually passed to fetch",
          "an unused controller is a mutant that changes nothing");
    check(/\.finally\(\s*\(\)\s*=>\s*\{\s*st\.fetching\s*=\s*false;\s*clearTimeout\(abortTimer\)/.test(still),
          "the timer is disarmed on every exit path, beside the guard");
}

console.log("\npaused tiles can never fire a synthetic 'frame arrived'");
{
    const pt = fn("pauseTile");
    const detachLoad  = pt.indexOf(".onload");
    const capture     = pt.indexOf("captureLastFrame");
    const pixel       = pt.indexOf("TRANSPARENT_PIXEL");
    check(detachLoad >= 0 && capture > detachLoad && pixel > capture,
          "pauseTile detaches handlers BEFORE the data-URL and the pixel",
          "both assignments fire onload; nine of them stamped 'Updated' per tab-hide");
    check(/\.onerror\s*=\s*null/.test(pt), "onerror detached too");
    const ri = fn("replaceImg");
    check(/st\.onFrameLoad/.test(ri) && !/=\s*oldImg\.onload/.test(ri),
          "replaceImg takes handlers from tile state, never off the old element",
          "copying a detached element's null handlers killed resumed tiles");
    check(/camState\[host\]\.onFrameLoad\s*=/.test(code),
          "buildGrid stores the canonical handlers on the tile state");
    const ss = fn("startStill");
    check(/st\.onFrameLoad/.test(ss),
          "startStill re-attaches them on resume",
          "a resume-from-paused skips replaceImg entirely");
}

console.log("\nboot-time execution order (the v2.64.0 page-killer)");
{
    // renderPolicy() runs once at boot and reads _lastPresence. A `let`
    // declared BELOW that call is in its temporal dead zone, and the
    // ReferenceError killed the entire page script on every fresh load of
    // v2.64.0 — no grid, no cameras, nothing. Order is load-bearing.
    const decl = code.indexOf("let _lastPresence");
    const bootCall = code.indexOf("renderPolicy();");
    check(decl >= 0 && bootCall >= 0 && decl < bootCall,
          "_lastPresence is declared before the boot-time renderPolicy() call",
          "a let below the call is TDZ — one dead variable, no cameras at all");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
