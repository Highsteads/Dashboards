// Filename:    test_pending_retry_client.mjs
// Description: dashboard.js's _fetch must wait out a "pending" 503 rather than
//              reporting it as an error.
//
//              WHY (v3.20.0). historyQuery moved onto the off-path worker pool:
//              measured with the parameters the Graphs page actually sends
//              (action=series, maxPoints=240, the 720 h chip, biggest table at
//              4.0 M rows) it cost 5.2-6.1 SECONDS on every call, on the thread
//              IWS serves every other page from. A cold chart therefore now
//              answers 503 + {"pending": true} while a worker builds it — and a
//              client that treats that as an error trades a six-second stall
//              for a broken Graphs page.
//
//              The retry lives in _fetch, the single choke point for every
//              /message/ call the class makes, so endpoints added later inherit
//              it. Pinned: pending is retried, a real error is not, the retry
//              gives up rather than polling for ever, and the deadline is not
//              restarted by each attempt.
// Author:      CliveS & Claude Opus 5
// Date:        18-09-2026
// Version:     1.0
//
// Run: node tests/test_pending_retry_client.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "dashboard.js");
const src  = fs.readFileSync(SRC, "utf8");

let failures = 0;
const check = (label, cond) => {
    console.log(`  ${cond ? "ok  " : "FAIL"} ${label}`);
    if (!cond) failures++;
};

console.log("dashboard.js — _fetch waits out a pending reply");

// The class is an ES module body with other deps; drive _fetch directly by
// pulling it out and giving it the handful of things it touches.
function grabMethod(name) {
    const start = src.indexOf(`    async ${name}(`);
    if (start < 0) throw new Error(`could not find ${name} in dashboard.js`);
    // Skip the PARAMETER LIST before counting braces. _fetch's signature is
    // (path, opts = {}, pendingUntil = 0) — starting at the first "{" grabs
    // the default value and stops one character later, which is a whole class
    // of silently-wrong extraction the sibling tests get away with only
    // because their functions take no object defaults.
    let p = src.indexOf("(", start), depth = 0, bodyStart = -1;
    for (let j = p; j < src.length; j++) {
        if (src[j] === "(") depth++;
        else if (src[j] === ")") { depth--; if (depth === 0) { bodyStart = src.indexOf("{", j); break; } }
    }
    depth = 0;
    let end = -1;
    for (let j = bodyStart; j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    const sig = src.slice(start, bodyStart);
    if (!sig.includes("pendingUntil")) {
        throw new Error("extracted the wrong thing: " + sig.trim());
    }
    return src.slice(start, end);
}

const consts = (src.match(/^const _PENDING_(POLL|TIMEOUT)_MS\s*=\s*\d+;$/gm) || []).join("\n");
check("the poll interval and ceiling are declared", consts.split("\n").length === 2);

const body = grabMethod("_fetch").replace(/^    async _fetch/, "async function _fetch");
const make = (fetchImpl) => {
    const ctx = {
        _base: "", _key: "k", _errH: [], _authH: [],
        DashGate: null, IndigoAPIError: class extends Error {
            constructor(m, s) { super(m); this.status = s; } },
    };
    const fn = new Function(
        "fetch", "AbortController", "setTimeout", "clearTimeout",
        "IndigoAPIError", "window", "_FETCH_TIMEOUT_MS", "_PENDING_POLL_MS",
        "_PENDING_TIMEOUT_MS",
        consts.replace(/^const /gm, "var _unused_") + "\n" + body + "; return _fetch;"
    )(fetchImpl, AbortController, setTimeout, clearTimeout, ctx.IndigoAPIError,
      {}, 5000, 5, 200);
    // _fetch recurses through `this._fetch`, so the context has to carry it.
    const bound = fn.bind(ctx);
    ctx._fetch = bound;
    return bound;
};

const reply = (status, obj, json = true) => ({
    status, ok: status >= 200 && status < 300,
    headers: { get: () => (json ? "application/json" : "text/plain") },
    clone() { return this; },
    async json() { if (obj === undefined) throw new Error("no body"); return obj; },
});

// 1. pending is retried until the data lands
{
    let n = 0;
    const f = make(async () => (++n < 4 ? reply(503, { pending: true })
                                        : reply(200, { ok: true, points: [1] })));
    const out = await f("/message/x/");
    check("polls a pending 503 until the chart is built", out.ok === true && n === 4);
}

// 2. a real error is NOT retried
for (const [status, obj, label] of [
    [400, { ok: false, error: "deviceId required" }, "a 400 throws at once"],
    [500, { ok: false, error: "database is locked" }, "a 500 throws at once"],
    [503, { ok: false, error: "something else" },     "a 503 that is not ours throws at once"],
    [503, undefined,                                  "a 503 with no JSON body throws at once"],
]) {
    let n = 0;
    const f = make(async () => { n++; return reply(status, obj); });
    let threw = false;
    try { await f("/message/x/"); } catch (e) { threw = e.status === status; }
    check(label, threw && n === 1);
}

// 3. it gives up rather than polling for ever, and the deadline does not reset
{
    // The stub refuses after a generous number of attempts. Without that, a
    // regression that restarts the deadline on each try makes this test HANG
    // rather than fail — and a hanging test is not a failing test, it is a
    // stuck CI job nobody reads.
    let n = 0;
    const CAP = 60;
    const f = make(async () => {
        if (++n > CAP) throw new Error("retried " + n + " times — no deadline is being honoured");
        return reply(503, { pending: true });
    });
    let gaveUp = false, ranAway = false;
    try { await f("/message/x/"); }
    catch (e) { ranAway = /no deadline/.test(e.message); gaveUp = !ranAway; }
    check("gives up on a build that never finishes", gaveUp);
    check("and the deadline is not restarted by each attempt", !ranAway && n <= CAP);
}

console.log(failures ? `\n${failures} failure(s)` : "\nAll pending-retry checks passed.");
process.exit(failures ? 1 : 0);
