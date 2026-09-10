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
// Author:      CliveS & Claude Opus 5
// Date:        30-07-2026
// Version:     1.0
//
// Run: node tests/test_snapshot_conditional.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
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

const num = re => { const m = re.exec(code); return m ? Number(m[1]) : null; };

let pass = 0, fail = 0;
const check = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + detail : ""}`);
};

console.log("\nsnapshot URL must stay revalidatable");
{
    const s = fn("snapshotUrl");
    check(!/[?&]t=/.test(s) && !/Date\.now\(\)/.test(s) && !/Math\.random/.test(s),
          "no cache-buster in snapshotUrl",
          "a unique url per poll defeats If-Modified-Since entirely");
}

console.log("\nthe still refresh must ask conditionally, and read the answer");
{
    const still = fn("startStill");
    check(/If-Modified-Since/.test(still),
          "sends If-Modified-Since");
    check(/lastMod/.test(still) && /Last-Modified/.test(still),
          "stores the server's Last-Modified to send back next time");
    check(/status\s*===\s*304/.test(still),
          "handles 304 explicitly",
          "without this a 304 would be treated as an empty frame and blank the tile");
    // The 304 branch must NOT reach the line that reads Last-Modified off the
    // response — a 304 does not carry one, so that would blank the timestamp
    // and the next poll would go out unconditional, silently reverting to
    // full-frame-every-time. Anchored on the assignment FROM THE RESPONSE
    // specifically: `st.lastMod = null` also appears earlier, deliberately, to
    // drop the timestamp when a tile changes between thumbnail and full size,
    // and a plain search for "st.lastMod =" finds that one instead.
    const i304 = still.indexOf("304");
    const iFromResponse = still.indexOf("st.lastMod = r.headers");
    check(i304 >= 0 && iFromResponse > i304,
          "304 returns before Last-Modified is read off the response");
    check(/cache:\s*["']no-store["']/.test(still),
          "no-store, so the browser's own cache cannot hide the 304 from us");
}

console.log("\npolling faster than frames are produced needs a pile-up guard");
{
    const still = fn("startStill");
    check(/st\.fetching/.test(still) && /if\s*\(\s*st\.fetching\s*\)\s*return/.test(still),
          "skips a tick while the previous poll is still in flight",
          "HTTP/1.1 allows 6 connections per origin; 9 tiles at 1 s would queue");
    check(/\.finally\(\s*\(\)\s*=>\s*\{\s*st\.fetching\s*=\s*false/.test(still),
          "clears the flag on EVERY exit path",
          "a throw that skipped this would stop the tile refreshing for good");
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

console.log("\nblob lifetime — a frame per second leaks fast if this slips");
{
    const still = fn("startStill");
    check(/createObjectURL/.test(still) && /revokeObjectURL/.test(still),
          "creates and revokes object URLs");
    // Revoking the OLD url only after the NEW one has decoded is what stops the
    // tile blanking between frames; revoking eagerly is the bug this replaced.
    const done = /const done = \(\) => \{[\s\S]*?\}/.exec(still);
    check(done && /st\.objUrl\)\s*URL\.revokeObjectURL\(st\.objUrl\)/.test(done[0]),
          "revokes the PREVIOUS frame inside the load handler, not before it");
    check(/addEventListener\("error"[\s\S]{0,80}revokeObjectURL/.test(still),
          "revokes on decode failure too, or a broken frame leaks");
    const live = fn("startLive");
    check(/releaseFrameUrl\(st\)/.test(live),
          "a tile switching to live hands its last blob back");
}

console.log("\nthumbnail for the grid, full size for the focused tile");
{
    // The saving is 70% (measured: 33.2 KB per full picture, 12.3 KB per
    // thumbnail, nine cameras). It rests on the grid asking for the small one
    // and the focused tile — the only one big enough to show the difference —
    // asking for the large one.
    const url = fn("snapshotUrl");
    check(/thumbPattern/.test(url) && /imgPattern/.test(url),
          "snapshotUrl can serve either size");
    const wants = fn("wantsFullSize");
    check(/focusedHost/.test(wants),
          "the focused tile is the one that gets the full-size picture");
    check(/thumbsAvailable/.test(wants),
          "and everything falls back to full size when there are no thumbs");

    const still = fn("startStill");
    // The two sizes are different FILES written in the same pass, so their
    // timestamps sit within a second of each other — close enough that a
    // carried-over If-Modified-Since produces a wrong 304 and a promoted tile
    // keeps showing its thumbnail. This is the subtle one.
    check(/st\.srcFull\s*!==\s*full/.test(still) && /st\.lastMod\s*=\s*null/.test(still),
          "the held timestamp is dropped when the tile changes size",
          "otherwise a promoted tile 304s against the thumb's timestamp and never sharpens");
    check(/status\s*===\s*404[\s\S]{0,120}thumbsAvailable\s*=\s*false/.test(still),
          "a missing thumbnail demotes the whole page to full-size pictures",
          "a server without Pillow must show pictures, not eight empty tiles");

    // Saving a picture should give you the real one, not the thumbnail.
    const camSrc = code;
    check(/a\.href\s*=\s*snapshotUrl\(host,\s*true\)/.test(camSrc),
          "the download link always saves the full-size picture");
}

console.log("\nthe hub strip — smallest tiles, landing page, biggest win");
{
    const hub = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin",
        "Contents", "Resources", "static", "pages", "index.html"), "utf8");
    const hubCode = hub.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    check(/cfg\.thumbPattern/.test(hubCode),
          "the hub's four camera tiles use the thumbnail");
    check(/still\s*=\s*full/.test(hubCode),
          "and fall back to the full picture if a thumbnail will not load");
    check(/data-full=/.test(hubCode) && /onerror=/.test(hubCode),
          "including on the FIRST paint, before any refresh timer has run",
          "otherwise a server with no thumbnails shows an empty strip for a whole poll period");
}

console.log("\nthe still poll must reschedule itself, not run on a fixed beat");
{
    // REPORTED as "the refresh jumps between 3 and 7 seconds", and measured NOT
    // to be the server: over three minutes the nine snapshot files were
    // rewritten 797 times at a mean of 2.04 s, worst gap 2.5 s, none over 3 s.
    // It was setInterval. A fixed beat fires whether or not the last request
    // has come back, the in-flight guard throws that tick away, and a fetch
    // that overran by 50 ms therefore costs a WHOLE second. At a 1 s interval
    // over a link with a ~0.9 s round trip, ordinary jitter drops ticks and the
    // rate visibly sawtooths. Scheduling from the END of each request cannot
    // sawtooth and cannot overlap itself.
    const still = fn("startStill");
    check(!/setInterval/.test(still),
          "no setInterval in the still poll",
          "a fixed beat turns a slightly-slow fetch into a whole skipped period");
    check(/setTimeout\(tick/.test(still),
          "the next poll is scheduled by the previous one finishing");
    check(/Math\.max\(MIN_GAP_MS,\s*period\s*-\s*spent\)/.test(still),
          "it waits out the REMAINDER of the period, not a fresh full one",
          "otherwise the effective rate is period + round-trip, not period");
    const gap = num(/MIN_GAP_MS\s*=\s*(\d+)/);
    check(gap !== null && gap >= 100,
          "and never spins when a fetch takes longer than the whole period", `${gap} ms`);

    // A chain has no timer to cancel while it is waiting inside its own .then(),
    // so clearing timers alone would let one more poll through. The generation
    // counter is what actually stops it.
    // TWO guards, and the test must require both — an earlier version of this
    // check accepted either, so deleting one passed a mutation run. They do
    // different jobs: the one at the top of `tick` stops a stale timeout that
    // is already pending from firing a fetch, and the one inside `.then()`
    // stops a stale chain from scheduling its successor. Only the second
    // prevents chains multiplying, but the first is what stops a torn-down
    // tile sending one last request.
    const guards = (still.match(/st\.gen\s*!==\s*gen/g) || []).length;
    check(guards >= 2,
          "a stale chain stands down BOTH before fetching and before rescheduling",
          `found ${guards} of 2`);
    const clear = fn("clearTileTimers");
    check(/st\.gen\s*=/.test(clear),
          "tearing a tile down bumps the generation",
          "clearTimeout cannot stop a chain that is mid-request");
    check(/clearTimeout\(st\.stillTimer\)/.test(clear),
          "and clears it as a timeout, which is what it now is");

    // The chain can only wait for the fetch if the fetch is handed back to it.
    check(/return fetch\(snapshotUrl/.test(still),
          "fetchFrame returns its promise so the chain can wait on it",
          "without this every tick reschedules immediately and it is a tight loop");
    check(/document\.hidden\s*\?\s*Promise\.resolve\(\)/.test(still),
          "a hidden tab resolves at once rather than stalling the chain");
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
    check(/st\.mode\s*===\s*"live"\)\s*total\s*\+=/.test(bw),
          "go2rtc's counter is only credited to tiles that really are streaming",
          "a still tile downloads a small JPEG a second while go2rtc pulls RTSP regardless");
    // Off-LAN nothing is live, so the whole streams.json poll is dead weight —
    // one request per second, per phone, for a number nothing reads.
    check(/anyLive/.test(bw) && /if\s*\(!anyLive\)/.test(bw),
          "skips the per-second streams.json poll when no tile is live");
    // Counting the same bytes at both ends of the tick doubled the figure.
    check((bw.match(/total\s*\+=\s*ownKBs/g) || []).length === 1
          && (bw.match(/_rxBytes\s*-\s*_rxLast/g) || []).length === 1,
          "our own bytes are added exactly once per tick");
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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
