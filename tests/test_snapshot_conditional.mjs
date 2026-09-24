// Filename:    test_snapshot_conditional.mjs
// Description: Contract test for the camera still-refresh mechanism — the
//              conditional-request path that carries the frames off-LAN.
//
//              WHY THIS EXISTS
//              The lag CliveS felt away from home was three additive phases:
//              the camera->server poll, the server->page poll, and the link.
//              The middle one was the page guessing when a new frame might
//              exist, on a 3 s beat, and paying 21-26 KB every time to find
//              out. Asking conditionally instead means an unchanged frame
//              answers 304 in 53 BYTES, so the page can afford to poll faster
//              than frames are produced and pick each one up almost as it
//              lands. MEASURED over the reflector, nine tiles, 30 s:
//
//                unique ?t= url @ 3 s   90 reqs, 0 x 304,  561 kbit/s, age 1.79s
//                conditional    @ 2 s  135 reqs, 1 x 304,  843 kbit/s, age 1.36s
//                conditional    @ 1 s  252 reqs, 117 x 304, 827 kbit/s, age 1.22s
//                unique ?t= url @ 1 s  243 reqs, 0 x 304, 1479 kbit/s, age 1.69s
//
//              The whole thing rests on the snapshot URL being STABLE. A
//              "?t=<now>" cache-buster — which is what the code did before, and
//              the obvious thing for someone to re-add when a tile looks stale
//              — makes every URL unique, so nothing can ever be revalidated and
//              every single poll costs a full frame again. That failure is
//              INVISIBLE: the pictures still update, they just cost 44% more
//              data. Hence a test rather than a comment.
// Author:      CliveS & Claude Opus 5; Claude Opus 5.5 (2.0)
// Date:        23-09-2026
// Version:     2.0 - the still refresh is now run, not read (fake network and clock)
//
// Run: node tests/test_snapshot_conditional.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
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

const num = re => { const m = re.exec(code); return m ? Number(m[1]) : null; };

// ── THE STILL REFRESH, RUN FOR REAL (23-09-2026) ────────────────────────
// Until 23-09-2026 every check below was a regular expression over the source, so
// a harmless reformat turned the test red and a real regression written in a
// different shape could pass. These run the page's own snapshotUrl,
// wantsFullSize, startStill and clearTileTimers in a sandbox with a fake
// network and a fake clock, and look at what they actually DO.
function makeSandbox({ thumbs = true, hidden = false, swap = null } = {}) {
    let now = 1_700_000_000_000;
    const timers = [];                 // {id, at, fn}
    let nextId = 1;
    const requests = [];               // {url, opts, resolve, reject}
    const revoked = [];
    const created = [];
    function makeImg() {
        const listeners = {};
        return {
            src: "", crossOrigin: "", onload: null, onerror: null,
            getAttribute(k) { return k === "src" ? this.src : null; },
            addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
            fire(t) { const l = listeners[t] || []; listeners[t] = []; l.forEach(fn => fn()); },
        };
    }
    const img = makeImg();
    const st = {
        mode: "still", imgEl: img,
        frameEl: { classList: { remove() {}, add() {} } },
        bwEl: { style: {} },
    };
    const ctx = {
        console, Math, JSON, Promise, Number, isNaN, String, Object, Error,
        AbortController,
        Date: Object.assign(function () {}, { now: () => now, parse: Date.parse }),
        setTimeout: (fn, ms) => { const id = nextId++; timers.push({ id, at: now + (ms || 0), fn }); return id; },
        clearTimeout: id => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); },
        document: { hidden },
        window: swap ? { DashUI: { swapImage: swap } } : {},
        URL: { createObjectURL: b => { const u = "blob:" + created.length; created.push(u); return u; },
               revokeObjectURL: u => revoked.push(u) },
        fetch: (url, opts) => new Promise((resolve, reject) => requests.push({ url, opts, resolve, reject })),
        camState: { "10.0.0.1": st },
        hosts: ["10.0.0.1"],
        imgPattern: "cam-{host}.jpg", thumbPattern: "cam-{host}-thumb.jpg",
        thumbsAvailable: thumbs, focusedHost: null, _idlePaused: false,
        STILL_FETCH_TIMEOUT_MS: 10000, MIN_GAP_MS: num(/MIN_GAP_MS\s*=\s*(\d+)/),
        NO_THUMB_RETRY_MS: num(/NO_THUMB_RETRY_MS\s*=\s*(\d+)/) * 60 * 1000,
        _rxBytes: 0,
        stopWebrtc() {}, replaceImg: s => s.imgEl, setMode() {},
        stillPeriodFor: () => 1000, noteAgeAtReceipt() {}, markRefreshed() {},
        _stillOk() {}, _stillFailed(s, why) { s.lastFailure = why; },
        DashUI: { stillUrl: (p, h) => (p ? String(p).split("{host}").join(String(h)) : "") },
    };
    vm.createContext(ctx);
    vm.runInContext(["snapshotUrl", "wantsFullSize", "clearTileTimers", "releaseFrameUrl", "startStill"]
        .map(fn).join("\n") +
        "\nglobalThis.__api = { snapshotUrl, wantsFullSize, startStill, clearTileTimers," +
        " get thumbs() { return thumbsAvailable; }, set focus(h) { focusedHost = h; } };", ctx);
    const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };
    return {
        api: ctx.__api, st, img, ctx, requests, revoked, created,
        settle,
        advance: async ms => {
            const until = now + ms;
            for (;;) {
                timers.sort((a, b) => a.at - b.at);
                const t = timers[0];
                if (!t || t.at > until) break;
                timers.shift();
                now = t.at;
                t.fn();
                await settle();
            }
            now = until;
        },
        pendingTimers: () => timers.map(t => t.at - now),
        answer: async (req, status, lastMod, size = 1000) => {
            req.resolve({
                status, ok: status >= 200 && status < 300,
                headers: { get: k => (k === "Last-Modified" ? lastMod : null) },
                blob: async () => ({ size }),
            });
            await settle();
        },
        fail: async (req, err = new Error("down")) => { req.reject(err); await settle(); },
    };
}

console.log("\nsnapshot URL must stay revalidatable");
{
    const sb = makeSandbox();
    const a = sb.api.snapshotUrl("10.0.0.1", false), b = sb.api.snapshotUrl("10.0.0.1", false);
    check(a === b && !a.includes("?"), "the same picture has the same URL every time", a);
    check(sb.api.snapshotUrl("10.0.0.1", true) !== a, "and the two sizes are different URLs");
}

console.log("\nthe still refresh asks conditionally and reads the answer");
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    const first = sb.requests[0];
    check(first && !first.opts.headers["If-Modified-Since"], "the first request is unconditional");
    check(first && first.opts.cache === "no-store", "no-store, so the browser's cache cannot hide a 304");
    await sb.answer(first, 200, "Wed, 23 Sep 2026 10:00:00 GMT", 21000);
    check(sb.st.lastMod === "Wed, 23 Sep 2026 10:00:00 GMT", "a 200 stores its Last-Modified");
    check(sb.ctx._rxBytes === 21000, "and counts the bytes this page downloaded", String(sb.ctx._rxBytes));
    check(sb.img.src === "blob:0", "and shows the new frame", sb.img.src);

    await sb.advance(1000);
    const second = sb.requests[1];
    check(second && second.opts.headers["If-Modified-Since"] === "Wed, 23 Sep 2026 10:00:00 GMT",
          "the next request sends that time back");
    await sb.answer(second, 304, null);
    check(sb.st.lastMod === "Wed, 23 Sep 2026 10:00:00 GMT",
          "a 304 keeps the held time (it carries none of its own)");
    check(sb.img.src === "blob:0", "and leaves the picture alone");
    check(sb.st.lastFailure === undefined, "and is not counted as a failure", String(sb.st.lastFailure));
    await sb.advance(1000);
    check(sb.requests[2] && sb.requests[2].opts.headers["If-Modified-Since"],
          "so the request after a 304 is still conditional");
}

console.log("\npolling faster than frames arrive needs a pile-up guard");
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.advance(1000);            // the first request never comes back
    check(sb.requests.length === 1, "no second request while the first is in flight",
          `${sb.requests.length} requests`);
    await sb.fail(sb.requests[0]);
    check(sb.st.fetching === false && sb.st.lastFailure === "unreachable",
          "a failed request clears the in-flight flag and says why");
    await sb.advance(1000);
    check(sb.requests.length === 2, "so the tile keeps refreshing after a failure");
}

console.log("\nthe poll reschedules itself from the end of each request");
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 200, "Wed, 23 Sep 2026 10:00:00 GMT");
    await sb.advance(0);               // the stagger offset (0 for the only tile) fires the chain
    const req = sb.requests[1];
    await sb.advance(400);             // this request takes 400 ms
    await sb.answer(req, 304, null);
    const waits = sb.pendingTimers();
    check(waits.includes(600), "it waits out the REMAINDER of the period, not a fresh one",
          JSON.stringify(waits));
    await sb.advance(2000);
    const slow = sb.requests[sb.requests.length - 1];
    await sb.advance(5000);            // a request slower than the whole period
    await sb.answer(slow, 304, null);
    check(sb.pendingTimers().includes(sb.ctx.MIN_GAP_MS),
          "and never spins when a request outlasts the period", JSON.stringify(sb.pendingTimers()));
}

console.log("\ntearing a tile down stops its chain");
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 200, "Wed, 23 Sep 2026 10:00:00 GMT");
    await sb.advance(0);
    const inFlight = sb.requests[1];
    sb.api.clearTileTimers(sb.st);     // torn down while a request is out
    await sb.answer(inFlight, 304, null);
    check(sb.pendingTimers().length === 0,
          "a chain caught mid-request does not schedule a successor",
          `${sb.pendingTimers().length} timers left`);
    await sb.advance(5000);
    check(sb.requests.length === 2, "and nothing more is fetched", `${sb.requests.length} requests`);
    // NB the guard at the TOP of tick is defensive: every path that starts a
    // new chain clears the old timer first, so no test can reach it.
}

console.log("\nthumbnail for the grid, full size for the focused tile");
{
    const sb = makeSandbox();
    check(!sb.api.wantsFullSize("10.0.0.1"), "a grid tile wants the thumbnail");
    sb.api.focus = "10.0.0.1";
    check(sb.api.wantsFullSize("10.0.0.1"), "the focused tile wants the full picture");
    sb.api.focus = null;
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    check(sb.requests[0].url.endsWith("-thumb.jpg"), "the grid asks for the thumbnail", sb.requests[0].url);
    await sb.answer(sb.requests[0], 200, "Wed, 23 Sep 2026 10:00:00 GMT");
    sb.api.focus = "10.0.0.1";         // promoted
    await sb.advance(1000);
    const promoted = sb.requests[1];
    check(!promoted.url.endsWith("-thumb.jpg") && !promoted.opts.headers["If-Modified-Since"],
          "a promoted tile asks for the full picture WITHOUT the thumbnail's time",
          "otherwise it 304s against the thumb and never sharpens");
}
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 404, null);
    // lows batch [68]: one camera's missing thumbnail moves only its own tile.
    check(sb.api.thumbs === true, "one camera's missing thumbnail does not turn thumbnails off for the page");
    await sb.advance(1000);
    check(!sb.requests[1].url.endsWith("-thumb.jpg"), "but that tile's next request is the full picture");
}
{
    // Two of three cameras with no thumbnail: the server cannot make them.
    const sb = makeSandbox();
    sb.ctx.hosts = ["10.0.0.1", "10.0.0.2", "10.0.0.3"];
    sb.ctx.camState["10.0.0.2"] = { noThumbUntil: Date.now() * 2 };
    sb.ctx.camState["10.0.0.3"] = {};
    check(!sb.api.wantsFullSize("10.0.0.3"), "another camera keeps its thumbnail");
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 404, null);
    check(sb.api.thumbs === false, "most cameras missing thumbnails turns them off for the page");
}

console.log("\nblob lifetime — a frame a second leaks fast if this slips");
{
    const sb = makeSandbox();
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 200, "A");
    sb.img.fire("load");
    await sb.advance(1000);
    await sb.answer(sb.requests[1], 200, "B");
    check(sb.revoked.length === 0, "the previous frame is kept until the new one has decoded");
    sb.img.fire("load");
    check(sb.revoked.includes("blob:0"), "and let go once it has");
    await sb.advance(1000);
    await sb.answer(sb.requests[2], 200, "C");
    sb.img.fire("error");
    check(sb.revoked.includes("blob:2"), "a frame that fails to decode is let go too");
}

console.log("\nthe cross-fade path keeps the same blob discipline (v3.38.0)");
{
    const answers = [];
    const swap = (img, url) => new Promise((ok, bad) => answers.push({ img, url, ok, bad }));
    const sb = makeSandbox({ swap });
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    await sb.answer(sb.requests[0], 200, "A");
    sb.img.fire("load");                         // first frame: no picture yet, so a plain swap
    check(sb.img.src === "blob:0" && answers.length === 0, "the first frame is shown directly", `${sb.img.src} ${answers.length}`);
    await sb.advance(1000);
    await sb.answer(sb.requests[1], 200, "B");
    check(answers.length === 1 && answers[0].url === "blob:1", "the next one cross-fades");
    check(sb.revoked.length === 0, "the old frame is held while it fades");
    answers[0].img.src = "blob:1"; answers[0].ok(true); await sb.settle();
    check(sb.revoked.includes("blob:0") && !sb.revoked.includes("blob:1"), "and let go once the fade is done");
    await sb.advance(1000);
    await sb.answer(sb.requests[2], 200, "C");
    answers[1].ok(false); await sb.settle();
    check(sb.revoked.includes("blob:2"), "a frame skipped mid-fade is handed straight back");
    await sb.advance(1000);
    await sb.answer(sb.requests[3], 200, "D");
    answers[2].bad(new Error("x")); await sb.settle();
    check(sb.revoked.includes("blob:3") && !sb.revoked.includes("blob:1"), "a frame that fails is let go, the shown one kept");
}

console.log("\na hidden tab spends nothing but keeps its place");
{
    const sb = makeSandbox({ hidden: true });
    sb.api.startStill("10.0.0.1");
    await sb.settle();
    check(sb.requests.length === 1, "the first frame is fetched even when hidden");
    await sb.answer(sb.requests[0], 200, "A");
    await sb.advance(3000);
    check(sb.requests.length === 1, "later ticks fetch nothing while hidden");
    check(sb.pendingTimers().length === 1, "but the chain is still scheduled");
}

console.log("\npoll periods");
{
    const remote = num(/REMOTE_POLL_MS\s*=\s*(\d+)/);
    const focus  = num(/FOCUS_POLL_MS\s*=\s*(\d+)/);
    // The server writes new frames every ~2.03 s (measured). Overshooting that
    // is the point: the surplus polls are 53-byte 304s and they are what pulls
    // the client's share of the lag down. If someone slows these back past the
    // production rate the conditional machinery is pointless.
    check(remote !== null && remote <= 2000,
          `REMOTE_POLL_MS polls at least as fast as frames appear`, `${remote} ms vs ~2030 ms`);
    check(focus !== null && focus <= remote,
          `focused tile is no slower than the thumbnails`, `${focus} ms vs ${remote} ms`);
    check(remote >= 500,
          "not so fast that 9 tiles saturate the 6 connection slots", `${remote} ms`);
}

console.log("\nsaving a picture");
check(/a\.href\s*=\s*snapshotUrl\(host,\s*true\)/.test(code),
      "the download link always saves the full-size picture");

console.log("\nthe hub strip — smallest tiles, landing page, biggest win");
{
    const hub = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin",
        "Contents", "Resources", "static", "pages", "index.html"), "utf8");
    const hubCode = hub.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    check(/pats\.thumbPattern/.test(hubCode) && !/cfg\.(thumb|image)Pattern/.test(hubCode),
          "the hub's four camera tiles use the thumbnail, from cameraStills, not config.js");
    check(/still\s*=\s*full/.test(hubCode),
          "and fall back to the full picture if a thumbnail will not load");
    // Since 24-09-2026 the first picture is fetched at once through the same
    // DashUI.refreshStill path (its 404 falls back), not by an <img src> with
    // an inline onerror, so there is one fallback rule rather than two.
    check(/imgs\.forEach\(img => swapIn\(img, true\)\);\s*imgs\.forEach\(\(img, i\) =>/.test(hubCode)
          && /e\.status === 404 && still !== full\) \{ still = full; swapIn\(img, first\)/.test(hubCode),
          "including on the FIRST paint, before any refresh timer has run",
          "otherwise a server with no thumbnails shows an empty strip for a whole poll period");
}

console.log("\nthe bandwidth figure must describe THIS DEVICE");
{
    // REPORTED: the footer read "3.0 MB/s total" on a phone on mobile data.
    // It was summing go2rtc's bytes_recv on the *_mjpeg producers — the RTSP
    // the SERVER pulls from the cameras across the house LAN, which happens
    // whether or not anyone is watching and has nothing to do with the phone.
    // Real figure was ~130 kB/s: wrong by roughly twenty times, and wrong in
    // the direction that frightens someone on a metered plan.
    const bw = code.slice(code.indexOf("function startBandwidthPoll"));
    check(/_rxBytes\s*\+=\s*blob\.size/.test(code),
          "counts the bytes this page actually downloaded");
    const fnBody = bw.slice(0, bw.indexOf("\n    }\n"));
    check(!/bytes_recv|_mjpeg|producers/.test(fnBody),
          "no server-side counter is added to the total at all (v3.36.0)",
          "every byte this page downloads is already counted on arrival");
    check(/\(Date\.now\(\) - _healthLastFetch\) > 30000/.test(fnBody),
          "streams.json is read at most every 30 s, for camera health only");
    check((fnBody.match(/_rxBytes\s*-\s*_rxLast/g) || []).length === 1
          && /_setBw\(ownKBs/.test(fnBody),
          "our own bytes are counted exactly once per tick");
}

console.log("\na still tile's status dot must reflect the TILE, not the server");
{
    const bw = code.slice(code.indexOf("function startBandwidthPoll"));
    check(/st\.lastFrameAt/.test(bw) && /st\.mode\s*!==\s*"still"/.test(bw),
          "still tiles are judged fresh by their own last delivered frame",
          "judging them by go2rtc's ingest let a frozen tile show a green dot");
    check(/st\.lastFrameAt\s*=\s*Date\.now\(\)/.test(code),
          "and something actually stamps that time when a frame arrives");
}

done();
