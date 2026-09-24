// Filename:    test_live_bandwidth.mjs
// Description: Contract test for live camera video decided by MEASURED
//              BANDWIDTH (v3.45.0), and for the shared WebRTC module both
//              camera pages now use.
//
//              WHY THIS EXISTS
//              CliveS: "My dashboards main page has 4 cameras and they are all
//              3 seconds behind, they should be live." Then: "I am always on
//              Tailscale on laptop, iPhone and iPad, so we need to decide by
//              the bandwidth, not Tailscale." His devices always arrive from a
//              tunnel address, at home and away, so the address says nothing
//              about the pipe. For everybody else, live video must still
//              never go over the Indigo reflector.
//
//              Four parts, each run for real against the shipped code:
//                1. dashboards-webrtc.js (DashRTC.start): offer shape, stop
//                   before the offer, failure reported once, stall and
//                   crawl detection.
//                2. DashRTC.decide / measure: fast tunnel -> live, slow ->
//                   stills, reflector -> stills however fast, demo -> stills,
//                   and the cached reading expiring into a new measurement.
//                3. The hub strip (index.html): live -> video over each still,
//                   stills -> no stream, hidden -> every stream stopped,
//                   failure -> the still back and a retry after a back-off.
//                4. The Cameras page (measureAndApply): a fast tunnel gets the
//                   full pool, a slow link stills, the reflector nothing.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_live_bandwidth.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE  = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read  = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const tick  = (ms = 5) => new Promise(r => setTimeout(r, ms));

function extractFn(s, name) {
    const start = s.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}
// Each part runs on its own, so one that cannot even find its code is a
// counted failure rather than the end of the run.
async function section(label, fn) {
    try { await fn(); }
    catch (e) { check(label + " (could not run)", false, e && e.message); }
}

// ── fakes ──────────────────────────────────────────────────────────────────
function makePCClass(pcs) {
    return class FakePC {
        constructor(cfg) {
            this.cfg = cfg; this.listeners = {}; this.signalingState = "stable";
            this.iceGatheringState = "gathering"; this.connectionState = "new";
            this.localDescription = null; this.transceivers = []; this.remote = null;
            pcs.push(this);
        }
        addTransceiver(kind, o) { this.transceivers.push([kind, o]); }
        addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
        fire(t) { (this.listeners[t] || []).forEach(f => f({ streams: [{}] })); }
        async createOffer() { return { type: "offer", sdp: "v=0 bare" }; }
        async setLocalDescription(o) { this.localDescription = { type: "offer", sdp: "v=0 gathered" }; }
        async setRemoteDescription(d) { this.remote = d; }
        close() { this.signalingState = "closed"; }
        finishIce() { this.iceGatheringState = "complete"; this.fire("icegatheringstatechange"); }
        setState(s) { this.connectionState = s; this.fire("connectionstatechange"); }
    };
}
function makeVideoEl() {
    const v = { currentTime: 0, frames: 0, listeners: {}, srcObject: null, removed: false,
                attrs: {}, muted: false, autoplay: false };
    v.setAttribute = (k, val) => { v.attrs[k] = val; };
    v.addEventListener = (t, f) => { (v.listeners[t] = v.listeners[t] || []).push(f); };
    v.fire = t => (v.listeners[t] || []).forEach(f => f());
    v.getVideoPlaybackQuality = () => ({ totalVideoFrames: v.frames });
    v.remove = () => { v.removed = true; };
    return v;
}
function memStorage() {
    const m = new Map();
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), _m: m };
}
// Load the REAL shared module into a fresh context around `win`.
function loadRTC(win) {
    const ctx = { window: win, console, setTimeout, clearTimeout, setInterval, clearInterval,
                  AbortController, Promise };
    vm.createContext(ctx);
    vm.runInContext(read("dashboards-webrtc.js"), ctx);
    return win.DashRTC;
}

// ── 1. the shared module ───────────────────────────────────────────────────
console.log("\n1. DashRTC.start: one live tile, owned by the module");
await section("DashRTC.start", async () => {
    const pcs = [], posts = [];
    let answer = { ok: true, status: 200, text: async () => "v=0 answer" };
    const win = { RTCPeerConnection: makePCClass(pcs), MediaStream: class {},
                  location: { protocol: "http:", hostname: "100.64.0.2", host: "100.64.0.2:8176" },
                  fetch: (u, o) => { posts.push([u, o]); return Promise.resolve(answer); },
                  document: { createElement: () => makeVideoEl() } };
    const R = loadRTC(win);
    check("the module publishes start / stop / decide on window.DashRTC",
          !!R && typeof R.start === "function" && typeof R.decide === "function");
    check("the signalling address is the plugin's port and the config path",
          R.url("10.0.0.5", { proxyPort: 8177, webrtcPath: "/webrtc/{host}" }) === "http://100.64.0.2:8177/webrtc/10.0.0.5");

    // a live tile: offer after ICE, WHEP-shaped, then the first frame
    let live = 0, fails = [];
    const v1 = R.makeVideo();
    check("makeVideo is muted, autoplay and inline (iOS autoplay)", v1.muted && v1.autoplay && "playsinline" in v1.attrs);
    const h1 = R.start("a", v1, { url: "/webrtc/a", onLive: () => live++, onFail: w => fails.push(w) });
    await tick();
    check("no offer goes out before ICE gathering ends", posts.length === 0);
    pcs[0].finishIce();
    await tick();
    const [u, o] = posts[0] || [];
    check("one signalling POST to the page's URL", posts.length === 1 && u === "/webrtc/a" && o.method === "POST");
    check("…as application/sdp with the GATHERED description, no other header",
          o && o.headers["Content-Type"] === "application/sdp" && Object.keys(o.headers).length === 1
            && o.body === "v=0 gathered",
          "any other header fails Safari's CORS preflight on :8177");
    check("…with this attempt's own abort signal", o && o.signal && typeof o.signal.aborted === "boolean");
    check("video only, receive only, no STUN",
          pcs[0].transceivers.length === 1 && pcs[0].transceivers[0][0] === "video"
            && pcs[0].transceivers[0][1].direction === "recvonly" && pcs[0].cfg.iceServers.length === 0);
    check("the answer is applied", pcs[0].remote && pcs[0].remote.sdp === "v=0 answer");
    v1.currentTime = 0.4; v1.fire("timeupdate"); v1.fire("timeupdate");
    check("the first frame is reported once", live === 1 && h1.gotFrame);
    h1.stop(); h1.stop();
    check("stop closes the peer connection, idempotently", pcs[0].signalingState === "closed" && h1.stopped);
    pcs[0].setState("failed");
    check("nothing is reported after stop", fails.length === 0);

    // torn down during the ICE wait: the offer is never sent (3.43.1)
    const h2 = R.start("b", makeVideoEl(), { url: "/webrtc/b", onFail: w => fails.push(w) });
    await tick();
    h2.stop();
    pcs[1].finishIce();
    await tick();
    check("a tile stopped during the ICE wait sends no offer", posts.length === 1, `${posts.length - 1} sent`);

    // signalling refused -> onFail once, everything closed
    answer = { ok: false, status: 502, text: async () => "" };
    const h3 = R.start("c", makeVideoEl(), { url: "/webrtc/c", onFail: w => fails.push(w) });
    await tick(); pcs[2].finishIce(); await tick(); await tick();
    check("a refused offer fails the tile, once, and closes it",
          fails.length === 1 && fails[0] === "signalling 502" && h3.stopped && pcs[2].signalingState === "closed",
          JSON.stringify(fails));
    pcs[2].setState("failed");
    check("…and a later state change cannot report it twice", fails.length === 1);
});

console.log("\n1b. a live tile that stops, or crawls, fails so the still comes back");
await section("DashRTC stall", async () => {
    const pcs = [];
    const win = { RTCPeerConnection: makePCClass(pcs), MediaStream: class {},
                  location: { protocol: "http:", hostname: "x", host: "x" },
                  fetch: () => new Promise(() => {}), document: { createElement: () => makeVideoEl() } };
    const R = loadRTC(win);
    const fails = [];
    const v = makeVideoEl();
    R.start("a", v, { url: "/w", stallMs: 20, onFail: w => fails.push(w) });
    v.currentTime = 1; v.frames = 30; v.fire("timeupdate");
    await tick(80);                                   // clock frozen for several looks
    check("a frozen picture fails as 'video stalled'", fails[0] === "video stalled", JSON.stringify(fails));

    const fails2 = [];
    const v2 = makeVideoEl();
    R.start("b", v2, { url: "/w", stallMs: 20, onFail: w => fails2.push(w) });
    v2.currentTime = 1; v2.frames = 10; v2.fire("timeupdate");
    v2.frames = 40;                                   // the counter is seen to count...
    const crawl = setInterval(() => { v2.currentTime += 0.02; }, 5);   // ...then the clock moves, frames do not
    await tick(120);
    clearInterval(crawl);
    check("a crawling picture (under POOR_FPS) fails as 'video too slow'",
          fails2[0] === "video too slow", JSON.stringify(fails2));

    const fails3 = [];
    const v3 = makeVideoEl();
    const h3 = R.start("c", v3, { url: "/w", stallMs: 20, onFail: w => fails3.push(w) });
    v3.currentTime = 1; v3.fire("timeupdate");
    const healthy = setInterval(() => { v3.currentTime += 0.1; v3.frames += 3; }, 5);
    await tick(120);
    clearInterval(healthy); h3.stop();
    check("a healthy picture is left alone", fails3.length === 0, JSON.stringify(fails3));

    // Safari's engine (24-09-2026): the decoder's frame counter never counts
    // a live stream. The clock moves, so the picture is fine.
    const fails4 = [];
    const v4 = makeVideoEl();
    const h4 = R.start("d", v4, { url: "/w", stallMs: 20, onFail: w => fails4.push(w) });
    v4.currentTime = 1; v4.fire("timeupdate");
    const clockOnly = setInterval(() => { v4.currentTime += 0.1; }, 5);   // frames stay 0 for ever
    await tick(120);
    clearInterval(clockOnly); h4.stop();
    check("a counter that never counts is not a crawl (Safari)", fails4.length === 0, JSON.stringify(fails4));

    // And a clock that does not move while frames are painted is not a stall.
    const fails5 = [];
    const v5 = makeVideoEl();
    let cbs = [];
    v5.requestVideoFrameCallback = f => { cbs.push(f); };
    const h5 = R.start("e", v5, { url: "/w", stallMs: 20, onFail: w => fails5.push(w) });
    const pump = setInterval(() => { const now = cbs; cbs = []; now.forEach(f => f()); }, 5);
    await tick(120);
    clearInterval(pump); h5.stop();
    check("painted frames count as progress when the clock stands still", fails5.length === 0,
          JSON.stringify(fails5));

    // Nothing moving at all is still a stall.
    const fails6 = [];
    const v6 = makeVideoEl();
    let cbs6 = [];
    v6.requestVideoFrameCallback = f => { cbs6.push(f); };
    R.start("f", v6, { url: "/w", stallMs: 20, onFail: w => fails6.push(w) });
    cbs6.splice(0).forEach(f => f());                 // the first frame, then nothing
    await tick(80);
    check("no clock, no paint, no frames: 'video stalled'", fails6[0] === "video stalled", JSON.stringify(fails6));
});

console.log("\n1c. the stream is asked to PLAY: autoplay alone left the hub paused (24-09-2026)");
await section("DashRTC play", async () => {
    const pcs = [];
    const win = { RTCPeerConnection: makePCClass(pcs), MediaStream: class {},
                  location: { protocol: "http:", hostname: "x", host: "x" },
                  fetch: () => new Promise(() => {}), document: { createElement: () => makeVideoEl() } };
    const R = loadRTC(win);

    // A browser that does not autoplay: the video stays paused until play().
    const v = makeVideoEl();
    v.paused = true; v.plays = 0;
    v.play = () => { v.plays++; v.paused = false; return Promise.resolve(); };
    const h = R.start("a", v, { url: "/w", stallMs: 20, onFail: () => {} });
    pcs[0].fire("track");
    check("the stream arriving asks the video to play", v.plays >= 1 && v.paused === false,
          `plays=${v.plays} paused=${v.paused}`);
    h.stop();

    // A browser that refuses to play: the first frame still shows (a paused
    // video draws it), then the check names the real fault, not a stall.
    const fails = [];
    const v2 = makeVideoEl();
    v2.paused = true; v2.plays = 0;
    v2.play = () => { v2.plays++; return Promise.reject(new Error("NotAllowedError")); };
    v2.requestVideoFrameCallback = f => { v2._frame = f; };
    R.start("b", v2, { url: "/w", stallMs: 20, onFail: w => fails.push(w) });
    pcs[1].fire("track");
    v2._frame();
    await tick(80);
    check("a video that will not play fails as 'video would not play'",
          fails[0] === "video would not play", JSON.stringify(fails));
    check("…after asking again on each look", v2.plays >= 2, `plays=${v2.plays}`);
});

console.log("\n1d. iOS: the video is marked for inline autoplay, and a missing frame says why");
await section("DashRTC iOS", async () => {
    const pcs = [];
    const win = { RTCPeerConnection: makePCClass(pcs), MediaStream: class {},
                  location: { protocol: "http:", hostname: "x", host: "x" },
                  fetch: () => new Promise(() => {}), document: { createElement: () => makeVideoEl() } };
    const R = loadRTC(win);
    const v = R.makeVideo();
    check("makeVideo carries the muted, autoplay and inline ATTRIBUTES iOS reads, prefixed one too",
          ["muted", "autoplay", "playsinline", "webkit-playsinline"].every(k => k in v.attrs) && v.defaultMuted === true,
          JSON.stringify(Object.keys(v.attrs)));

    // A refused play() is remembered and named.
    const v2 = makeVideoEl();
    v2.paused = true;
    v2.play = () => Promise.reject(Object.assign(new Error("no"), { name: "NotAllowedError" }));
    R.playVideo(v2);
    await tick();
    check("a refused play() is remembered by name", v2._playRefused === "NotAllowedError");

    // The detail from the connection's own statistics.
    const stats = new Map([
        ["in", { type: "inbound-rtp", kind: "video", bytesReceived: 1300000, framesDecoded: 0, codecId: "c1" }],
        ["c1", { type: "codec", id: "c1", mimeType: "video/H264" }],
    ]);
    const detail = await R.noFrameDetail({ getStats: async () => stats }, v2);
    check("the detail names the refusal, what arrived, what decoded and the codec",
          detail === "playback refused: NotAllowedError, 1.2 MB received, 0 decoded, H264", detail);
    const none = await R.noFrameDetail({ getStats: async () => new Map() }, { paused: true });
    check("…and says when no video arrived at all", none === "paused, no video received", none);

    // A refusal that is NOT the autoplay rule still fails, and says why.
    const fails = [];
    const v3 = makeVideoEl();
    v3.paused = true;
    v3.play = () => Promise.reject(Object.assign(new Error("no"), { name: "AbortError" }));
    R.start("a", v3, { url: "/w", frameMs: 30, iceMs: 1000, onFail: w => fails.push(w) });
    pcs[pcs.length - 1].getStats = async () => stats;
    pcs[pcs.length - 1].fire("track");
    await tick(80);
    check("'no frame' says why", /^no frame in 0\.03s \(playback refused: AbortError/.test(fails[0] || ""),
          JSON.stringify(fails));
    check("…and asks the video to play again once it has data",
          (v3.listeners.loadedmetadata || []).length === 1 && (v3.listeners.canplay || []).length === 1);

    // The autoplay rule (NotAllowedError, iOS Low Power Mode, 24-09-2026):
    // the stream stays connected, the page is told, and a tap starts it.
    const fails4 = [], events = [];
    const v4 = makeVideoEl();
    v4.paused = true;
    let allow = false;
    v4.play = () => allow
        ? (v4.paused = false, Promise.resolve())
        : Promise.reject(Object.assign(new Error("no"), { name: "NotAllowedError" }));
    const h4 = R.start("b", v4, { url: "/w", frameMs: 30, iceMs: 1000,
                                  onFail: w => fails4.push(w), onBlocked: () => events.push("blocked"),
                                  onLive: () => events.push("live") });
    pcs[pcs.length - 1].fire("track");
    await tick(80);
    check("a NotAllowedError is not a failure: the page is told a tap is needed",
          fails4.length === 0 && events[0] === "blocked" && !h4.stopped, JSON.stringify({ fails4, events }));
    check("…and the stream is counted as waiting", R.blockedCount() === 1);
    allow = true;                                     // the user taps
    R.unblockAll();
    await tick();
    v4.currentTime = 0.5; v4.fire("timeupdate");
    check("a tap plays it and it goes live", events.includes("live") && R.blockedCount() === 0,
          JSON.stringify(events));
    h4.stop();
});

console.log("\n1e. the Cameras page names a failed live stream, not the link");
await section("cameras badge", async () => {
    const src = read("cameras.html");
    const i = src.indexOf("function degradeToStill");
    const body = src.slice(i, src.indexOf("\n    }\n", i));
    check("degradeToStill keeps the reason", /st\.degradeWhy\s*=\s*why/.test(body));
    // Run the real label expression against both kinds of reason.
    const m = src.match(/still:\s*st\.autoDegraded\s*\?([\s\S]*?):\s*"↻ " \+ \(stillPeriod \/ 1000\) \+ "s",/);
    check("the still label is where it was", !!m);
    const label = why => new Function("st", "stillPeriod", "return " + m[1])({ autoDegraded: true, degradeWhy: why }, 5000);
    check("a failed WebRTC stream reads 'live failed'", label("WebRTC no frame in 8s") === "↻ 5s · live failed", label("WebRTC no frame in 8s"));
    check("a slow-link degrade still reads 'slow link'", label("stalled 3 times") === "↻ 5s · slow link", label("stalled 3 times"));
});

// ── 2. the bandwidth decision ──────────────────────────────────────────────
console.log("\n2. DashRTC.decide: the speed decides, never the address, never the reflector");
await section("DashRTC.decide", async () => {
    const pcs = [];
    const state = { link: "vpn", demo: false, rtt: 10, roundMs: 40, size: 50000, fetches: [], fail: false };
    let clockT = 0;
    const ui = {
        linkClass: () => state.link,
        isDemo: () => state.demo,
        cameraStills: async () => ({ imagePattern: "stills-x/cam-{host}.jpg" }),
        stillUrl: (p, h) => p.split("{host}").join(h),
        probeRtt: async () => state.rtt,
    };
    const hosts = ["h1", "h2", "h3", "h4"];
    const fakeFetch = (u, o) => {
        state.fetches.push([u, o]);
        if (state.flipAt && state.fetches.length === state.flipAt) state.link = "reflector";
        if (state.fail) return Promise.resolve({ ok: false, status: 500 });
        return Promise.resolve({ ok: true, status: 200,
            blob: async () => { clockT += state.roundMs / hosts.length; return { size: state.size }; } });
    };
    const store = memStorage();
    let wall = 1_800_000_000_000;
    const win = { RTCPeerConnection: makePCClass(pcs), DashUI: ui, fetch: fakeFetch, localStorage: store,
                  location: { protocol: "http:", hostname: "100.64.0.2", host: "100.64.0.2:8176" } };
    const R = loadRTC(win);
    const opts = () => ({ hosts, clock: () => clockT, now: () => wall });

    check("per-stream rate and headroom are named constants (1.4 Mbit/s, x2 or more)",
          R.PER_STREAM_MBPS === 1.4 && R.HEADROOM >= 2);
    check("four hub tiles need about 11 Mbit/s", Math.abs(R.needMbps(4) - 11.2) < 0.01, String(R.needMbps(4)));
    check("11.2 Mbit/s carries exactly four; 11.1 carries three",
          R.tilesCarried(11.2) === 4 && R.tilesCarried(11.1) === 3 && R.tilesCarried(0) === 0);
    check("the asking round trip comes off the time, but never more than MAX_RTT_SHARE of it",
          Math.abs(R.rateOf({ bytes: 200000, ms: 40 }, 10) - 1.6e6 / 30e3) < 0.01
            && Math.abs(R.rateOf({ bytes: 200000, ms: 130 }, 116) - 1.6e6 / 32.5e3) < 0.01);

    // fast tunnel: LIVE
    let v = await R.decide(4, opts());
    check("a FAST Tailscale link (vpn address) -> live", v.live === true && v.tiles >= 4, JSON.stringify(v));
    check("…measured with a warm-up and two timed rounds of every still at once",
          state.fetches.length === 3 * hosts.length, `${state.fetches.length} fetches`);
    const [fu, fo] = state.fetches[0];
    check("…each a fresh full-size still that no cache can answer",
          /stills-x\/cam-h1\.jpg\?bw=/.test(fu) && fo.cache === "no-store" && !(fo.headers && fo.headers["If-Modified-Since"]),
          "If-Modified-Since would get a 53-byte 304, which measures nothing");
    check("…and the reading is cached", !!R.cached({ now: () => wall }));

    // within the cache: no new measurement
    state.fetches = [];
    v = await R.decide(4, opts());
    check("a second ask inside the cache lifetime measures nothing", v.live && state.fetches.length === 0);

    // the reflector: never, however fast the cached reading
    state.link = "reflector";
    v = await R.decide(4, opts());
    check("over the reflector -> stills, even with a fast reading cached", v.live === false && v.why === "reflector");
    check("…and nothing is downloaded to find out", state.fetches.length === 0);
    const m = await R.measure(Object.assign(opts(), { force: true }));
    check("measure refuses outright over the reflector", m === null && state.fetches.length === 0);
    state.link = "vpn";

    // the server says "reflector" while the measurement is in flight
    R.forget({ storage: store }); state.fetches = [];
    state.flipAt = 3 * hosts.length;                  // the last download of the last round
    v = await R.decide(4, opts());
    check("a reflector verdict that lands mid-measurement still means stills",
          v.live === false && v.why === "reflector", JSON.stringify(v));
    state.flipAt = 0; state.link = "vpn"; state.fetches = [];

    // the demo: stills, nothing measured
    state.demo = true;
    v = await R.decide(4, opts());
    check("the demo -> stills", v.live === false && v.why === "demo" && state.fetches.length === 0);
    state.demo = false;

    // cache expiry re-measures, and a slow link gets stills
    wall += R.VERDICT_TTL_MS + 1;
    state.roundMs = 400;                              // 1.6 Mbit in ~390 ms: about 4 Mbit/s
    v = await R.decide(4, opts());
    check("an expired reading is measured again", state.fetches.length === 3 * hosts.length);
    check("a SLOW link -> stills", v.live === false && v.why === "too slow" && v.tiles < 4, JSON.stringify(v));

    // a LAN address measured slow: the address grants nothing
    state.link = "home"; state.fetches = [];
    R.forget({ storage: store });
    v = await R.decide(4, opts());
    check("a LAN address measured slow -> stills too", v.live === false && state.fetches.length > 0);

    // a failed measurement is not cached
    state.fail = true; R.forget({ storage: store }); state.fetches = [];
    v = await R.decide(4, opts());
    check("a failed measurement -> stills, and nothing is cached",
          v.live === false && v.why === "not measured" && R.cached({ now: () => wall }) === null);
    state.fail = false;

    // storage that throws: still decides
    const winT = Object.assign({}, win, { localStorage: { getItem() { throw new Error("x"); },
                                                          setItem() { throw new Error("x"); },
                                                          removeItem() { throw new Error("x"); } } });
    const RT = loadRTC(winT);
    state.roundMs = 40;
    v = await RT.decide(4, opts());
    check("storage that throws does not stop the decision", v.live === true);

    // no WebRTC in this browser
    const winN = Object.assign({}, win); delete winN.RTCPeerConnection;
    const RN = loadRTC(winN);
    v = await RN.decide(4, opts());
    check("no RTCPeerConnection -> stills", v.live === false && v.why === "no webrtc");

    // a network change drops the cached reading and calls back
    let changed = 0; const conn = { l: null, addEventListener(t, f) { this.l = f; }, removeEventListener() {} };
    await R.decide(4, opts());
    R.watchConnection(() => changed++, { navigator: { connection: conn }, storage: store });
    conn.l();
    check("a navigator.connection change forgets the reading and asks again",
          changed === 1 && store.getItem(R.VERDICT_KEY) === null);
});

// ── 3. the hub strip ───────────────────────────────────────────────────────
console.log("\n3. the hub strip: live video over each still, where the connection carries it");
await section("hub strip", async () => {
    const src  = read("index.html");
    const a    = src.indexOf("    // ── Camera strip (rendered ONCE)");
    const b    = src.indexOf("    // Where the pictures are.");
    if (a < 0 || b < a) throw new Error("strip block not found");
    const block = src.slice(a, b);

    const timers = [];
    const listeners = {}, winListeners = {};
    const mkFrame = host => {
        const cls = new Set(), kids = [];
        const img = { dataset: { host }, isConnected: true };
        return { dataset: { host }, isConnected: true, kids, img,
                 classList: { add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) },
                 has: c => cls.has(c),
                 appendChild: el => kids.push(el),
                 querySelector: () => img };
    };
    const frames = ["h1", "h2", "h3", "h4"].map(mkFrame);
    const mount = { querySelectorAll: () => frames };
    const note = { textContent: "", hidden: true };
    const doc = { hidden: false, getElementById: id => (id === "cam-live-note" ? note : mount),
                  addEventListener: (t, f) => { listeners[t] = f; } };
    const started = [], swapped = [];
    let verdict = { live: true, tiles: 20, mbps: 60, needMbps: 11.2, why: "fast enough" };
    const fakeRTC = {
        decide: async () => verdict,
        makeVideo: () => makeVideoEl(),
        url: h => "/webrtc/" + h,
        start: (host, video, opts) => {
            const h = { host, opts, stopped: false, stop() { this.stopped = true; } };
            started.push(h); return h;
        },
        watchConnection: () => () => {},
    };
    const ui = { linkClass: () => "vpn", isDemo: () => false };
    const win = { CAMERA_CONFIG: { mainCameras: ["h1", "h2", "h3", "h4"], webrtcPath: "/webrtc/{host}",
                                   names: { h2: "Front Door" } },
                  DashRTC: fakeRTC, DashUI: ui, RTCPeerConnection: function () {},
                  _hubSwapIn: (img, first) => swapped.push([img.dataset.host, first]),
                  addEventListener: (t, f) => { winListeners[t] = f; } };
    const ctx = {
        window: win, document: doc, DashRTC: fakeRTC, DashUI: ui, console: { info() {}, warn() {} },
        setTimeout: (f, ms) => { timers.push({ f, ms }); return timers.length; }, clearTimeout: () => {},
        loadSummary() {}, _heavyStarted: false, _refreshInsights() {}, _refreshLogWatch() {}, _refreshCamHealth() {},
    };
    vm.createContext(ctx);
    vm.runInContext(block + `
        globalThis.__hub = { decide: _hubDecide, sync: _hubSyncLive, wanted: _hubLiveWanted,
                             live: () => _hubLive, verdict: () => _hubVerdict, stopAll: _hubStopAllLive,
                             RETRY: HUB_LIVE_RETRY_MS };`, ctx);
    const H = ctx.__hub;
    const liveOf = () => started.filter(h => !h.stopped);

    // the pure rule
    const base = { link: "vpn", demo: false, hidden: false, canRtc: true, hasPath: true };
    check("the rule: a live verdict on a tunnel address -> live", H.wanted({ live: true }, base) === true);
    check("…a stills verdict -> no stream", H.wanted({ live: false }, base) === false);
    check("…no verdict yet -> no stream", H.wanted(null, base) === false);
    check("…the reflector -> no stream, whatever the verdict says",
          H.wanted({ live: true }, Object.assign({}, base, { link: "reflector" })) === false);
    check("…the demo, a hidden page or no WebRTC -> no stream",
          !H.wanted({ live: true }, Object.assign({}, base, { demo: true }))
            && !H.wanted({ live: true }, Object.assign({}, base, { hidden: true }))
            && !H.wanted({ live: true }, Object.assign({}, base, { canRtc: false })));

    // live verdict -> one stream per tile, video over the still
    await H.decide();
    check("a live verdict starts a stream on each of the four tiles",
          liveOf().length === 4 && frames.every(f => f.kids.length === 1), `${liveOf().length} started`);
    check("…each asks DashRTC to watch for a stall", started.every(h => h.opts.stallMs > 0));
    started[0].opts.onLive();
    check("the first frame shows the video over the still", frames[0].has("is-live"));
    check("…and no 'why not live' line shows while live", note.hidden === true && note.textContent === "");

    // hidden -> every stream stopped
    doc.hidden = true;
    listeners.visibilitychange();
    check("hiding the page stops every stream", liveOf().length === 0 && !frames[0].has("is-live"));
    check("…and removes the video, so the still shows", frames.every(f => f.kids.every(k => k.removed)));
    doc.hidden = false;
    listeners.visibilitychange();
    await tick();
    check("showing it again asks again and restarts them", liveOf().length === 4);
    winListeners.pagehide();
    check("pagehide stops every stream too", liveOf().length === 0);
    listeners.visibilitychange(); await tick();

    // failure -> the still back at once, and a retry after a back-off
    const victim = liveOf()[1];
    victim.opts.onLive();
    swapped.length = 0; timers.length = 0;
    victim.opts.onFail("video stalled");
    check("a failed stream is stopped and its tile leaves live",
          victim.stopped && !frames[1].has("is-live"));
    check("…a fresh still is asked for at once", swapped.length === 1 && swapped[0][0] === "h2" && swapped[0][1] === true);
    check("…and the line under the strip says which camera stopped and why",
          !note.hidden && /Front Door/.test(note.textContent) && /video stalled/.test(note.textContent),
          note.textContent);
    const retry = timers.find(t => t.ms === H.RETRY);
    check("…and live is tried again after a back-off", !!retry, JSON.stringify(timers.map(t => t.ms)));
    const before = started.length;
    retry.f();
    check("…which starts a new stream on that tile", started.length === before + 1 && started[started.length - 1].host === "h2");
    started[started.length - 1].opts.onFail("no frame in 8s");
    check("a second failure backs off for longer",
          timers.some(t => t.ms === 2 * H.RETRY));

    // a stream the browser will not start by itself -> "tap to start"
    const waiting = liveOf()[0];
    waiting.opts.onBlocked();
    check("a stream waiting for a tap says so under the strip",
          !note.hidden && /Tap anywhere/.test(note.textContent), note.textContent);

    // stills verdict -> no stream at all
    verdict = { live: false, tiles: 1, mbps: 3, needMbps: 11.2, why: "too slow" };
    doc.hidden = true; listeners.visibilitychange(); doc.hidden = false;
    const n = started.length;
    listeners.visibilitychange(); await tick();
    check("a stills verdict opens no stream", started.length === n && liveOf().length === 0);
    check("…and says so under the strip, with the measured and needed speeds",
          !note.hidden && /3 Mbit\/s measured/.test(note.textContent) && /11\.2 needed/.test(note.textContent),
          note.textContent);

    // wiring that is not a function of its own
    check("the strip asks the shared rule, not the address",
          /DashRTC\.decide\(hosts\.length,\s*\{\s*hosts\s*\}\)/.test(block) && !/_measuredLink\s*===?\s*["']home["']/.test(block));
});

// ── 4. the Cameras page ────────────────────────────────────────────────────
console.log("\n4. the Cameras page sizes its live pool from the measured speed");
await section("cameras page", async () => {
    const src = read("cameras.html");
    const RTC = loadRTC({ location: { protocol: "http:", hostname: "x", host: "x" } });
    const run = async ({ cls, bw }) => {
        const ctx = {
            hosts: ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
            cfg: { livePoolSize: 6, webrtcPath: "/webrtc/{host}" },
            LINK: null, LIVE_POOL_SIZE: 0, DEFAULT_LIVE: [], DEFAULT_LIVE_SET: new Set(), LIVE_FOLLOWS_FOCUS: false,
            WEBRTC_FOCUS: false, LAST_RTT: null, LAST_TILES: null, LAST_MBPS: null, RTT_TUNNEL_MS: 150,
            _measureInflight: null, _lastPresence: null, Set, Math, console: { info() {} },
            relayouts: 0, relayoutAll() { ctx.relayouts++; }, renderPolicy() {}, cachePolicy() {},
            homeByPresence: async () => null,
        };
        ctx.window = {
            RTCPeerConnection: function () {},
            DashUI: { measuredClass: async () => cls, probeRtt: async () => 116 },
            DashRTC: { measure: async () => bw, tilesCarried: RTC.tilesCarried },
        };
        ctx.DashUI = ctx.window.DashUI; ctx.DashRTC = ctx.window.DashRTC;
        vm.createContext(ctx);
        vm.runInContext(extractFn(src, "setPolicy") + "\n" + extractFn(src, "measureAndApply")
                        + "\nglobalThis.__m = measureAndApply;", ctx);
        await ctx.__m();
        return ctx;
    };
    let c = await run({ cls: "vpn", bw: { mbps: 60, rttMs: 116 } });
    check("a Tailscale device on a fast link gets the full live pool",
          c.LIVE_POOL_SIZE === 6 && !c.WEBRTC_FOCUS && c.relayouts === 1, `${c.LIVE_POOL_SIZE} live`);
    c = await run({ cls: "vpn", bw: { mbps: 3, rttMs: 245 } });
    check("a link carrying one stream gets the one focused live tile", c.LIVE_POOL_SIZE === 0 && c.WEBRTC_FOCUS);
    c = await run({ cls: "home", bw: { mbps: 1.5, rttMs: 20 } });
    check("a slow link gets stills, whatever its address", c.LIVE_POOL_SIZE === 0 && !c.WEBRTC_FOCUS);
    c = await run({ cls: "vpn", bw: null });
    check("an unmeasured speed opens nothing", c.LIVE_POOL_SIZE === 0 && !c.WEBRTC_FOCUS);
    c = await run({ cls: "reflector", bw: { mbps: 100, rttMs: 30 } });
    check("the reflector opens nothing, even if something reported it fast",
          c.LIVE_POOL_SIZE === 0 && !c.WEBRTC_FOCUS);
});

done();
