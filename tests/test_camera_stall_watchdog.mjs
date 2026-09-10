// Filename:    test_camera_stall_watchdog.mjs
// Description: Node contract test for the cameras.html slow-link stall
//              watchdog (v2.49.0). Extracts the REAL function source out of
//              the shipped HTML and drives it against stubs, so this locks the
//              behaviour that ships rather than a copy of it.
//
//              Why the watchdog exists: the kB/s telemetry reads go2rtc's
//              bytes_recv, which counts the CAMERA->go2rtc leg. Over a weak
//              mobile link that counter keeps advancing while the
//              go2rtc->BROWSER leg stalls, so the old freshness check could
//              never see the failure the user was actually looking at — a
//              frozen first frame. The watchdog samples the rendered image
//              instead, which is bottleneck-agnostic.
// Author:      CliveS & Claude Opus 5
// Date:        27-07-2026
// Version:     1.0
//
// Run: node tests/test_camera_stall_watchdog.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "cameras.html");
const src  = fs.readFileSync(SRC, "utf8");

// ── pull the functions under test out of the page, verbatim ────────────────
function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in cameras.html`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}
function grabConst(name) {
    const m = new RegExp(`const\\s+${name}\\s*=\\s*([0-9]+)`).exec(src);
    if (!m) throw new Error(`could not find const ${name} in cameras.html`);
    return Number(m[1]);
}

const LIVE_PROBE_MS      = grabConst("LIVE_PROBE_MS");
const LIVE_STALL_MS      = grabConst("LIVE_STALL_MS");
const DEGRADED_POLL_MS   = grabConst("DEGRADED_POLL_MS");
const LIVE_RETRY_BASE_MS = grabConst("LIVE_RETRY_BASE_MS");
const LIVE_RETRY_MAX_MS  = grabConst("LIVE_RETRY_MAX_MS");

// ── stub world ─────────────────────────────────────────────────────────────
let NOW = 1_000_000;
const realDateNow = Date.now;
Date.now = () => NOW;

const hosts = ["camA", "camB"];
const DEFAULT_LIVE_SET = new Set(hosts);
const camState = {};
const calls = [];

let SIG = { camA: 1, camB: 1 };
let SIG_NULL = false;
const frameSignature = (img) => (SIG_NULL ? null : SIG[img.__host]);
const startStill = (h) => { calls.push(["startStill", h]); camState[h].mode = "still"; };
const startLive  = (h) => { calls.push(["startLive",  h]); camState[h].mode = "live";  };
const setMode    = (h, m) => { calls.push(["setMode", h, m]); };

let _timer = null;
const setIntervalStub   = (fn, ms) => { _timer = { fn, ms }; return _timer; };
const clearIntervalStub = () => { _timer = null; };

const body = [grab("mayHoldLive"), grab("degradeToStill"), grab("tryRestoreLive"),
              grab("startStallWatchdog")].join("\n");
const factory = new Function(
    "hosts", "camState", "DEFAULT_LIVE_SET", "DEFAULT_LIVE", "LIVE_FOLLOWS_FOCUS",
    "FOCUS_INIT", "frameSignature", "startStill", "startLive",
    "setMode", "console", "setInterval", "clearInterval",
    "LIVE_PROBE_MS", "LIVE_STALL_MS", "DEGRADED_POLL_MS", "LIVE_RETRY_BASE_MS", "LIVE_RETRY_MAX_MS",
    // `_stallTimer` and `focusedHost` are module-scope bindings on the page;
    // declare them here so the extracted functions close over them exactly as
    // they do in the browser (focusedHost is REASSIGNED by focusTile, so it
    // cannot be a plain factory argument — the setter stands in for that).
    // WEBRTC_FOCUS is pinned false here: the MJPEG watchdog behaviour under
    // test predates the webrtc slot and must be unchanged when it is off
    // (webrtc-path behaviour has its own suite, test_camera_webrtc.mjs).
    "let _stallTimer = null;\nlet focusedHost = FOCUS_INIT;\n"
    + "let WEBRTC_FOCUS = false;\n"
    + "const startWebrtc = () => { throw new Error('startWebrtc must be unreachable with WEBRTC_FOCUS off'); };\n"
    + "const webrtcFallback = () => { throw new Error('webrtcFallback must be unreachable with WEBRTC_FOCUS off'); };\n"
    + body +
    "\nreturn { mayHoldLive, degradeToStill, tryRestoreLive, startStallWatchdog,"
    + " setFocus(h) { focusedHost = h; } };"
);
const quiet = { warn() {}, info() {}, log() {} };
const mkApi = (followsFocus, focusInit) => factory(
    hosts, camState, DEFAULT_LIVE_SET, hosts, followsFocus, focusInit,
    frameSignature, startStill, startLive,
    setMode, quiet, setIntervalStub, clearIntervalStub,
    LIVE_PROBE_MS, LIVE_STALL_MS, DEGRADED_POLL_MS,
    LIVE_RETRY_BASE_MS, LIVE_RETRY_MAX_MS);
const api = mkApi(false, "camA");   // at-home: fixed pool, focus irrelevant

const mkTile = () => ({ mode: "live", paused: false, lastSig: null, lastChangeAt: null,
                        autoDegraded: false, degradeCount: 0, imgEl: {}, modeEl: {}, bwEl: {} });
function reset() {
    for (const h of hosts) { camState[h] = mkTile(); camState[h].imgEl.__host = h; }
    SIG = { camA: 1, camB: 1 }; SIG_NULL = false; calls.length = 0;
}
reset();
api.startStallWatchdog();
const tick    = () => _timer.fn();
const advance = (ms) => { NOW += ms; };

let passed = 0, failed = 0;
function check(name, cond) {
    if (cond) { passed++; console.log(`  ok   ${name}`); }
    else      { failed++; console.log(`  FAIL ${name}`); }
}

console.log(`constants: probe=${LIVE_PROBE_MS} stall=${LIVE_STALL_MS} `
          + `degradedPoll=${DEGRADED_POLL_MS} retry=${LIVE_RETRY_BASE_MS}..${LIVE_RETRY_MAX_MS}`);

console.log("\n1. a moving stream is left alone (the at-home case)");
reset();
// advance BOTH tiles — a frozen camB would correctly degrade and pollute the
// "nothing was degraded" assertion.
for (let i = 0; i < 20; i++) { SIG.camA++; SIG.camB++; advance(LIVE_PROBE_MS); tick(); }
check("stays live", camState.camA.mode === "live");
check("never degraded", !camState.camA.autoDegraded);
check("no fallback triggered", !calls.some((c) => c[0] === "startStill"));

console.log("\n2. a frozen stream degrades once past the stall threshold");
reset();
tick();
advance(LIVE_STALL_MS - 1000); tick();
check("holds live before the threshold", camState.camA.mode === "live");
advance(2000); tick();
check("degrades to stills", camState.camA.mode === "still");
check("marks the drop as automatic", camState.camA.autoDegraded === true);
check("first backoff is the base delay", camState.camA.retryAfterMs === LIVE_RETRY_BASE_MS);

console.log("\n3. a degraded tile retries live after the backoff");
advance(LIVE_RETRY_BASE_MS - 5000); tick();
check("no retry before the backoff elapses", !calls.some((c) => c[0] === "startLive"));
advance(6000); tick();
check("retries live once it has", calls.some((c) => c[0] === "startLive"));

console.log("\n4. recovery clears the degraded marker");
camState.camA.mode = "live";
SIG.camA = 99;  advance(LIVE_PROBE_MS); tick();
SIG.camA = 100; advance(LIVE_PROBE_MS); tick();
check("marker cleared", camState.camA.autoDegraded === false);
check("back to live", camState.camA.mode === "live");

console.log("\n5. repeated failure backs off, and the backoff is capped");
reset();
let last = 0;
for (let n = 1; n <= 8; n++) {
    camState.camA.mode = "live";
    camState.camA.lastSig = null;
    camState.camA.lastChangeAt = null;
    tick(); advance(LIVE_STALL_MS + 1000); tick();
    last = camState.camA.retryAfterMs;
}
check("backoff grew past the base", last > LIVE_RETRY_BASE_MS);
check("backoff capped at the max", last === LIVE_RETRY_MAX_MS);

console.log("\n6. an unsampleable image never degrades (tainted canvas)");
reset();
SIG_NULL = true;
for (let i = 0; i < 20; i++) { advance(LIVE_PROBE_MS); tick(); }
check("stays live", camState.camA.mode === "live");
check("not degraded", !camState.camA.autoDegraded);

console.log("\n7. a paused tile is left alone");
reset();
camState.camA.paused = true;
tick(); advance(LIVE_STALL_MS + 5000); tick();
check("untouched", !camState.camA.autoDegraded);

console.log("\n8. tiles degrade independently");
reset();
tick();
for (let i = 0; i < 10; i++) { SIG.camB++; advance(LIVE_PROBE_MS); tick(); }
check("the frozen tile degraded", camState.camA.mode === "still");
check("the moving tile stayed live", camState.camB.mode === "live");

// ── v2.55.0: off-LAN, the single live slot follows the FOCUS ───────────────
// DEFAULT_LIVE_SET still holds every host here (the page builds it from
// hosts.slice(0, LIVE_POOL_SIZE)), but with a pool of one only hosts[0] would
// be in it. The entitlement question is therefore "is this the focused tile",
// not "is this in the default set" — and getting that wrong produced both a
// tile that could never regain live and a demoted tile that could restore
// itself behind the user's back.
const focusApi = mkApi(true, "camA");
focusApi.startStallWatchdog();          // rebind the stub timer to this copy

console.log("\n9. off-LAN, a promoted focused tile CAN regain live after a stall");
reset();
focusApi.setFocus("camB");              // user focused the second camera
camState.camB.autoDegraded = true;      // it stalled and dropped to stills
camState.camB.mode         = "still";
camState.camB.degradedAt   = NOW;
camState.camB.retryAfterMs = LIVE_RETRY_BASE_MS;
advance(LIVE_RETRY_BASE_MS + 1); tick();
check("the focused tile went live again", camState.camB.mode === "live");
// The marker deliberately SURVIVES the retry — it is cleared by the watchdog
// only once frames actually move again, which is what emits the "recovered"
// line and forgives the backoff. Clearing it here would call the retry a
// success before anything had been received.
check("still marked degraded until frames actually move", camState.camB.autoDegraded);
SIG.camB++; advance(LIVE_PROBE_MS); tick();   // first fresh frame
SIG.camB++; advance(LIVE_PROBE_MS); tick();
check("marker cleared once frames flow", !camState.camB.autoDegraded);

console.log("\n10. off-LAN, a DEMOTED tile never restores itself behind the user");
reset();
focusApi.setFocus("camB");              // live slot has moved to camB
camState.camA.autoDegraded = true;      // camA degraded before the handover
camState.camA.mode         = "still";
camState.camA.degradedAt   = NOW;
camState.camA.retryAfterMs = LIVE_RETRY_BASE_MS;
advance(LIVE_RETRY_BASE_MS + 1); tick();
check("stays on stills", camState.camA.mode === "still");
check("no second live socket opened", !calls.some((c) => c[0] === "startLive" && c[1] === "camA"));
check("stops retrying (marker cleared)", !camState.camA.autoDegraded);

console.log("\n11. entitlement follows focus, not the default set");
check("focused tile may hold live", focusApi.mayHoldLive("camB") === true);
check("unfocused tile may not", focusApi.mayHoldLive("camA") === false);
check("at home the whole pool may", api.mayHoldLive("camA") === true
                                  && api.mayHoldLive("camB") === true);

Date.now = realDateNow;
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
