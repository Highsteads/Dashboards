// Filename:    test_camera_webrtc.mjs
// Description: Contract test for the away-from-home WebRTC focused tile
//              (camera plan Phase C1).
//
//              WHY THIS EXISTS
//              Away over the tunnel the focused tile streams WebRTC from
//              go2rtc — spike-proven on the real path (iPhone, 5G+Tailscale,
//              3/3 over UDP, first frame 1.2-2.3 s). These tests pin the
//              policy gates (measured-vpn only, never home/reflector/
//              unmeasured), the negotiation shape (video-only recvonly, no
//              STUN, application/sdp POST), the teardown discipline (never
//              two peer connections, nothing survives pause/pagehide), and
//              the fallback floor (the pre-WebRTC bands, so a WebRTC
//              regression can never make things worse than v2.64.0).
// Author:      CliveS & Claude Fable 5
// Date:        30-07-2026
// Version:     2.0 (v3.36.0: WebRTC is the only live mode; the MJPEG floor is gone)
//
// Run: node tests/test_camera_webrtc.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { checkOk as check, done } from "./lib/check.mjs";

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

// ── setPolicy: when may the webrtc slot exist? Executed for real ──
function runPolicy(cls, rtt, cfgExtra, noRtc) {
    const box = {
        hosts: ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
        cfg: Object.assign({ livePoolSize: 6 }, cfgExtra),
        window: noRtc ? {} : { RTCPeerConnection: function () {} },
        LINK: null, LIVE_POOL_SIZE: null, DEFAULT_LIVE: null,
        DEFAULT_LIVE_SET: null, LIVE_FOLLOWS_FOCUS: null,
        WEBRTC_FOCUS: null, LAST_RTT: null,
        Set, Math, console,
        RTT_TUNNEL_MS: Number(/RTT_TUNNEL_MS\s*=\s*(\d+)/.exec(src)[1]),
    };
    vm.createContext(box);
    vm.runInContext(fn("setPolicy") + `\nsetPolicy(${JSON.stringify(cls)}, ${JSON.stringify(rtt)});`, box);
    return box;
}
const RTC_CFG = { webrtcPath: "/webrtc/{host}" };

console.log("\npolicy: the webrtc slot exists ONLY on a measured tunnel link");
{
    let b = runPolicy("vpn", 245, RTC_CFG);
    check(b.WEBRTC_FOCUS === true && b.LIVE_POOL_SIZE === 0,
          "measured vpn-far -> webrtc focus, no pool",
          "this replaces '9 stills' as the 5G experience");
    b = runPolicy("vpn", 116, RTC_CFG);
    check(b.WEBRTC_FOCUS === true && b.LIVE_POOL_SIZE === 0,
          "measured vpn-near -> webrtc focus too",
          "WebRTC drops instead of queueing");
    b = runPolicy("vpn", null, RTC_CFG);
    check(b.WEBRTC_FOCUS === false && b.LIVE_POOL_SIZE === 0,
          "UNMEASURED vpn never opens the webrtc slot",
          "boot's conservative guess must not start any stream, webrtc included");
    b = runPolicy("home", 21, RTC_CFG);
    check(b.WEBRTC_FOCUS === false && b.LIVE_POOL_SIZE === 6,
          "home: a pool of six live tiles, all WebRTC since v3.36.0");
    b = runPolicy("reflector", 10, RTC_CFG);
    check(b.WEBRTC_FOCUS === false && b.LIVE_POOL_SIZE === 0,
          "the reflector never attempts webrtc",
          "ports 8177/8555 are not fronted by it");
    b = runPolicy("vpn", 116, {});
    check(b.WEBRTC_FOCUS === false && b.LIVE_POOL_SIZE === 0,
          "no webrtcPath in config -> stills, never an MJPEG band (v3.36.0)");
    const noRtc = (cls, rtt) => {
        const box = runPolicy(cls, rtt, RTC_CFG, true);
        return box.LIVE_POOL_SIZE === 0 && box.WEBRTC_FOCUS === false;
    };
    check(noRtc("home", 5) && noRtc("vpn", 116),
          "a browser without WebRTC gets stills everywhere");
}

console.log("\nnegotiation shape");
{
    const rtc = fn("startWebrtc");
    check(/addTransceiver\(\s*["']video["']\s*,\s*\{\s*direction:\s*["']recvonly["']/.test(rtc),
          "video transceiver, recvonly");
    check(!/addTransceiver\(\s*["']audio["']/.test(code),
          "NO audio transceiver anywhere",
          "the cameras' AAC cannot negotiate; audio would stall the offer");
    check(/iceServers:\s*\[\]/.test(rtc),
          "no STUN servers",
          "the only reachable candidate is go2rtc's LAN host candidate");
    check(/video\.muted\s*=\s*true/.test(rtc) && /setAttribute\(\s*["']playsinline["']/.test(rtc),
          "muted + playsinline — iOS autoplay requirements");
    check(/body:\s*pc\.localDescription\.sdp/.test(rtc),
          "POSTs the gathered localDescription, not the pre-gathering offer");
    check(/["']Content-Type["']:\s*["']application\/sdp["']/.test(rtc),
          "with the application/sdp content type the proxy contract expects");
    check(/webrtcUrl\(host\)/.test(rtc) && /cfg\.webrtcPath/.test(fn("webrtcUrl")),
          "signalling goes to the config-published proxy path");
    check(/requestVideoFrameCallback\(firstFrame\)/.test(rtc)
              && /addEventListener\(\s*["']timeupdate["']/.test(rtc)
              && /video\.currentTime\s*>\s*0/.test(rtc),
          "first-frame has BOTH triggers: composited frame AND media clock",
          "rVFC never fires on a hidden page — the 8 s timer would kill a healthy stream");
    check(/if\s*\(st\.webrtcGotFrame\)\s*return/.test(rtc),
          "and firstFrame is idempotent — the two triggers race");
}

console.log("\nteardown discipline — count the call sites");
{
    // stopWebrtc is called from: startWebrtc (restart safety), startStill,
    // pauseTile, and the pagehide loop. webrtcFallback also calls it before
    // falling back. startLive IS startWebrtc since v3.36.0. A stripped site
    // leaks a peer connection.
    const sites = countMatches(code, /(?<!function )stopWebrtc\(/g);
    check(sites === 5, "exactly five stopWebrtc call sites",
          `found ${sites} (startWebrtc, startStill, pauseTile, pagehide, webrtcFallback)`);
    check(/startWebrtc\(host\)/.test(fn("startLive")), "live means WebRTC: startLive opens a peer connection");
    check(/stopWebrtc\(st\)/.test(fn("startStill")), "startStill tears the pc down");
    check(/stopWebrtc\(st\)/.test(fn("pauseTile")),
          "a hidden tab holds no peer connection");
    {
        // Executed, not grepped: a text check survived a mutant that
        // disabled the capture while leaving every string in place.
        const img = { src: "poster.jpg", onload: 1, onerror: 1 };
        const st = { mode: "webrtc", videoEl: { videoWidth: 640, videoHeight: 360 }, imgEl: img,
                     frameEl: { classList: { add() {} } }, bwEl: { style: {} } };
        const box = {
            camState: { h: st }, TRANSPARENT_PIXEL: "pixel",
            clearTileTimers() {}, setMode() {},
            stopWebrtc(t) { t.videoEl = null; },
            captureLastFrame() { img.src = "poster-capture"; },
            document: { createElement: () => ({ getContext: () => ({ drawImage() {} }),
                                                toDataURL: () => "data:video-frame" }) },
        };
        vm.createContext(box);
        vm.runInContext(fn("pauseTile") + "\npauseTile('h');", box);
        check(img.src === "data:video-frame",
              "pausing a live tile keeps the video frame the viewer was looking at",
              `got ${img.src}: the <img> under the video is the poster from before it went live`);
    }
    const ph = code.slice(code.indexOf('"pagehide"'), code.indexOf('"visibilitychange"'));
    check(/stopWebrtc\(st\)/.test(ph), "pagehide closes every pc",
          "iOS kills the JS context but the server-side consumer would linger");
    const sw = fn("stopWebrtc");
    check(/pc\.close\(\)/.test(sw) && /srcObject\s*=\s*null/.test(sw)
              && /st\.videoEl\.remove\(\)/.test(sw),
          "stopWebrtc closes, detaches and removes");
    check(/st\.lastRtcBytes\s*=\s*0/.test(sw),
          "…and zeroes the byte high-water mark",
          "a fresh pc counts from zero; a stale mark makes every delta negative");
    check(/imgEl\.style\.display\s*=\s*["']["']/.test(sw),
          "…and restores the poster img");
}

console.log("\nfocus handover");
{
    const ft = fn("focusTile");
    const block = ft.slice(ft.indexOf("if (WEBRTC_FOCUS)"));
    const stopOld = block.indexOf("startStill(previous)");
    const startNew = block.indexOf("startWebrtc(host)");
    check(stopOld >= 0 && startNew > stopOld,
          "the OLD tile is stopped before the new one starts",
          "never two peer connections on the one link that matters");
}

console.log("\nfailure ladder and the fallback floor");
{
    const fb = fn("webrtcFallback");
    const poolIdx = fb.indexOf("degradeToStill(host");
    const awayIdx = fb.indexOf("startStill(host)");
    check(/LIVE_POOL_SIZE\s*>\s*0\s*&&\s*mayHoldLive\(host\)/.test(fb) && poolIdx >= 0,
          "a pool tile falls back through the degrade ladder",
          "which owns its retry and parks it after six failures");
    check(awayIdx > poolIdx,
          "the single away tile falls to stills with its own backoff");
    check(!/startLive|mjpeg/i.test(fb), "and nothing falls back to a stream");
    check(/LIVE_RETRY_BASE_MS\s*\*\s*st\.webrtcFails/.test(fb)
              && /LIVE_RETRY_MAX_MS/.test(fb),
          "retry backoff reuses the live-retry arithmetic, capped");
    const wd = fn("startStallWatchdog");
    check(/st\.mode\s*===\s*["']webrtc["']/.test(wd)
              && /v\.currentTime\s*>\s*\(st\.lastVideoTime/.test(wd),
          "the watchdog judges a webrtc tile by its video clock advancing");
    check(/st\.webrtcRetryAt\s*&&\s*now\s*>=\s*st\.webrtcRetryAt/.test(wd),
          "…and owns the retry, gated on the backoff comparison");
    check(/host\s*===\s*\(focusedHost\s*\|\|\s*hosts\[0\]\)/.test(wd),
          "…for the entitled tile only");
}

console.log("\ninstrumentation ties in");
{
    const ages = fn("tickAges");
    check(/st\.mode\s*===\s*["']webrtc["']/.test(ages) && !/["']live["']\s*\|\|/.test(ages),
          "the age chip shows a live tile's time since last visible change");
    const bw = fn("startBandwidthPoll");
    check(/inbound-rtp/.test(bw) && /_rxBytes\s*\+=\s*d/.test(bw),
          "webrtc bytes come from the pc's own counters into the page total",
          "exact measurement, not go2rtc's camera-side ingest");
    check(/webrtc:\s*["']live["']/.test(fn("setMode")) && !/\blive:\s*["']/.test(fn("setMode")),
          "the mode chip calls a WebRTC tile live, and there is no other kind");
}

done();
