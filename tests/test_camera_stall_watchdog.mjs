// Filename:    test_camera_stall_watchdog.mjs
// Description: Node contract test for the cameras.html slow-link stall
//              watchdog. Extracts the REAL function source out of the shipped
//              HTML and drives it against stubs, so this locks the behaviour
//              that ships rather than a copy of it.
//
//              A live tile is WebRTC since v3.36.0, and it is judged by what
//              the viewer can see: the <video> clock has to keep advancing.
//              go2rtc's counters only see the camera->go2rtc leg, which keeps
//              flowing while the go2rtc->browser leg stalls. A stalled pool
//              tile drops to stills through degradeToStill and retries live
//              on a growing, capped backoff; six failures with no recovery
//              park it.
// Author:      CliveS & Claude Opus 5 (v1.0); Claude Opus 5.5 (v2.0)
// Date:        23-09-2026
// Version:     2.0 (v3.36.0: the video clock replaces the MJPEG canvas hash)
//
// Run: node tests/test_camera_stall_watchdog.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "cameras.html");
const src  = fs.readFileSync(SRC, "utf8");

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
const DEGRADED_POLL_MS   = grabConst("DEGRADED_POLL_MS");
const LIVE_RETRY_BASE_MS = grabConst("LIVE_RETRY_BASE_MS");
const LIVE_RETRY_MAX_MS  = grabConst("LIVE_RETRY_MAX_MS");

// ── stub world ─────────────────────────────────────────────────────────────
let NOW = 1_000_000;
const realDateNow = Date.now;
Date.now = () => NOW;

const hosts = ["camA", "camB"];
const camState = {};
const calls = [];
const startStill = (h) => { calls.push(["startStill", h]); camState[h].mode = "still"; };
// startLive opens WebRTC; the frame arriving is the test's to simulate.
const startLive  = (h) => { calls.push(["startLive", h]); camState[h].mode = "webrtc"; };
const stopWebrtc = () => {};
const setMode    = (h, m) => { calls.push(["setMode", h, m]); };

let _timer = null;
const setIntervalStub   = (fn, ms) => { _timer = { fn, ms }; return _timer; };
const clearIntervalStub = () => { _timer = null; };

const body = [grab("mayHoldLive"), grab("degradeToStill"), grab("tryRestoreLive"),
              grab("webrtcFallback"), grab("startStallWatchdog")].join("\n");
const factory = new Function(
    "hosts", "camState", "DEFAULT_LIVE_SET", "DEFAULT_LIVE", "LIVE_FOLLOWS_FOCUS", "LIVE_POOL_SIZE",
    "FOCUS_INIT", "startStill", "startLive", "stopWebrtc",
    "setMode", "console", "setInterval", "clearInterval",
    "DEGRADED_POLL_MS", "LIVE_PROBE_MS", "LIVE_RETRY_BASE_MS", "LIVE_RETRY_MAX_MS",
    "let _stallTimer = null;\nlet focusedHost = FOCUS_INIT;\nlet WEBRTC_FOCUS = false;\n"
    + "const startWebrtc = () => { throw new Error('the away slot is off in this suite'); };\n"
    + body
    + "\nreturn { mayHoldLive, degradeToStill, tryRestoreLive, startStallWatchdog,"
    + " setFocus(h) { focusedHost = h; } };"
);
const quiet = { warn() {}, info() {}, log() {} };
const mkApi = (followsFocus, poolSize, focusInit) => factory(
    hosts, camState, new Set(hosts.slice(0, poolSize)), hosts.slice(0, poolSize), followsFocus, poolSize,
    focusInit, startStill, startLive, stopWebrtc,
    setMode, quiet, setIntervalStub, clearIntervalStub,
    DEGRADED_POLL_MS, LIVE_PROBE_MS, LIVE_RETRY_BASE_MS, LIVE_RETRY_MAX_MS);

const mkTile = () => ({ mode: "webrtc", paused: false, webrtcGotFrame: true,
                        videoEl: { currentTime: 1 }, lastVideoTime: 0,
                        autoDegraded: false, degradeCount: 0, modeEl: {}, bwEl: {} });
function reset() { for (const h of hosts) camState[h] = mkTile(); calls.length = 0; }
const advance = (ms) => { NOW += ms; };
const tick    = () => _timer.fn();
const play    = (h) => { camState[h].videoEl.currentTime += 0.5; };

const api = mkApi(false, 2, "camA");      // at home: a fixed pool of two
api.startStallWatchdog();

console.log("\n1. a moving stream is left alone");
reset();
for (let i = 0; i < 20; i++) { play("camA"); play("camB"); advance(LIVE_PROBE_MS); tick(); }
check("stays live", camState.camA.mode === "webrtc");
check("never degraded", !camState.camA.autoDegraded);
check("no fallback", !calls.some((c) => c[0] === "startStill"));

console.log("\n2. a frozen stream degrades after two still ticks");
reset();
play("camA"); play("camB"); tick();            // records the clock
play("camB"); advance(LIVE_PROBE_MS); tick();  // camA: one tick without progress
check("holds on one missed tick", camState.camA.mode === "webrtc");
play("camB"); advance(LIVE_PROBE_MS); tick();  // two
check("degrades to stills", camState.camA.mode === "still");
check("marked as an automatic drop", camState.camA.autoDegraded === true);
check("first backoff is the base delay", camState.camA.retryAfterMs === LIVE_RETRY_BASE_MS);
check("the moving tile stayed live", camState.camB.mode === "webrtc");

console.log("\n3. it retries live after the backoff");
calls.length = 0;
advance(LIVE_RETRY_BASE_MS - 5000); tick();
check("not before the backoff", !calls.some((c) => c[0] === "startLive"));
advance(6000); tick();
check("retries once it has", calls.some((c) => c[0] === "startLive" && c[1] === "camA"));

console.log("\n4. repeated failure backs off, capped, then parks");
reset();
let last = 0;
for (let n = 1; n <= 8; n++) {
    const st = camState.camA;
    st.mode = "webrtc"; st.webrtcGotFrame = true; st.lastVideoTime = st.videoEl.currentTime;
    st.webrtcStallTicks = 0;
    tick(); tick();
    last = st.retryAfterMs;
}
check("backoff grew past the base", last > LIVE_RETRY_BASE_MS);
check("backoff capped at the max", last === LIVE_RETRY_MAX_MS);
calls.length = 0;
advance(LIVE_RETRY_MAX_MS + 1); tick();
check("six failures with no recovery park it", !calls.some((c) => c[0] === "startLive" && c[1] === "camA"));

console.log("\n5. a connecting tile is left to its own timers");
reset();
camState.camA.webrtcGotFrame = false;
for (let i = 0; i < 5; i++) { advance(LIVE_PROBE_MS); tick(); }
check("untouched while connecting", camState.camA.mode === "webrtc");

console.log("\n6. a paused tile is left alone");
reset();
camState.camA.paused = true;
tick(); tick(); tick();
check("untouched", !camState.camA.autoDegraded);

console.log("\n7. a pool of one follows the focus");
const focusApi = mkApi(true, 1, "camA");
focusApi.startStallWatchdog();
reset();
focusApi.setFocus("camB");
camState.camB.autoDegraded = true; camState.camB.mode = "still";
camState.camB.degradedAt = NOW; camState.camB.retryAfterMs = LIVE_RETRY_BASE_MS;
camState.camA.autoDegraded = true; camState.camA.mode = "still";
camState.camA.degradedAt = NOW; camState.camA.retryAfterMs = LIVE_RETRY_BASE_MS;
advance(LIVE_RETRY_BASE_MS + 1); tick();
check("the focused tile goes live again", camState.camB.mode === "webrtc");
check("the demoted tile never restores itself", camState.camA.mode === "still"
      && !calls.some((c) => c[0] === "startLive" && c[1] === "camA"));
check("and stops retrying", !camState.camA.autoDegraded);
check("entitlement: focused yes, other no", focusApi.mayHoldLive("camB") && !focusApi.mayHoldLive("camA"));

console.log("\n8. recovery is recorded when a frame arrives, and forgiven after a good run");
{
    const rtc = grab("startWebrtc");
    const ff = rtc.slice(rtc.indexOf("const firstFrame"));
    check("the first frame clears the degraded marker", /if \(st\.autoDegraded\) \{[\s\S]{0,120}st\.autoDegraded = false;/.test(ff));
    check("and restarts the parking count", /st\.degradesSinceRecovery = 0;/.test(ff));
    const wd = grab("startStallWatchdog");
    check("a long good run forgives the backoff",
          /st\.recoveredAt && \(now - st\.recoveredAt\) > LIVE_RETRY_MAX_MS[\s\S]{0,80}st\.degradeCount = 0;/.test(wd));
    check("no canvas hashing is left", !/frameSignature|getImageData/.test(src));
}

Date.now = realDateNow;
done();
