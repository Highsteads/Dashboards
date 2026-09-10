// Filename:    test_stamp_gate.mjs
// Description: Node contract test for dashboards-gate.js (v2.70.0) — the
//              liveness gate that keeps every /message/ poller away from a
//              stopping plugin host (a request in flight there at host-stop
//              wedges the whole IWS event loop for ~298 s). Pins: verdicts
//              for run/stopping/404/unreachable, the memoised fetch window,
//              the SKEW-IMMUNE 12 s staleness edge (both sides), the
//              exponential backoff to its 60 s cap and its reset, and the
//              one-shot boot-change flag.
// Author:      CliveS & Claude Fable 5
// Date:        31-07-2026
// Version:     1.0
//
// Run: node tests/test_stamp_gate.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboards-gate.js");

let NOW = 1_000_000;
let FETCHES = 0;
let RESPONDER = null;   // async () => Response-like; set per test

function mkResp(status, obj) {
    return { status, ok: status >= 200 && status < 300, json: async () => obj };
}

function loadGate() {
    const win = {};
    const ctx = {
        window: win,
        Date: { now: () => NOW },
        fetch: async (...a) => { FETCHES++; return RESPONDER(...a); },
        AbortController: class { constructor() { this.signal = {}; } abort() {} },
        setTimeout: () => 0,
        clearTimeout: () => {},
        console,
    };
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(SRC, "utf8"), ctx);
    return win.DashGate;
}

// Fresh gate per test — module state is deliberately sticky in production.
function fresh() {
    FETCHES = 0;
    RESPONDER = async () => { throw new Error("no responder set"); };
    return loadGate();
}

const C = loadGate()._constants;   // FETCH_MS, STALE_MS, BACKOFF_BASE_MS, BACKOFF_MAX_MS

const tests = {
    async "a live run stamp with an advancing ts is ok"() {
        const g = fresh();
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: 500, state: "run" });
        assert.equal(await g.check(), "ok");
    },

    async "checks inside the memoise window share one fetch"() {
        const g = fresh();
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: 500, state: "run" });
        await g.check();
        NOW += C.FETCH_MS - 1;
        assert.equal(await g.check(), "ok");
        assert.equal(FETCHES, 1, "second check must reuse the memoised verdict");
    },

    async "a stopping sentinel is down"() {
        const g = fresh();
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: 500, state: "stopping" });
        assert.equal(await g.check(), "down");
    },

    async "a 404 is nogate — never down"() {
        const g = fresh();
        RESPONDER = async () => mkResp(404, {});
        assert.equal(await g.check(), "nogate");
        assert.equal(g._state.backoffMs, 0, "nogate must not start a backoff");
    },

    async "nogate rechecks lazily — IWS logs a warning per 404"() {
        const g = fresh();
        RESPONDER = async () => mkResp(404, {});
        await g.check();
        NOW += C.NOGATE_RECHECK_MS - 1;
        assert.equal(await g.check(), "nogate");
        assert.equal(FETCHES, 1, "no refetch inside the lazy window");
        NOW += 2;
        await g.check();
        assert.equal(FETCHES, 2, "and it does eventually recheck");
    },

    async "an unreachable stamp is down"() {
        const g = fresh();
        RESPONDER = async () => { throw new Error("net down"); };
        assert.equal(await g.check(), "down");
    },

    async "a 5xx is down"() {
        const g = fresh();
        RESPONDER = async () => mkResp(500, {});
        assert.equal(await g.check(), "down");
    },

    async "a ts frozen for exactly STALE_MS is still ok (strict edge)"() {
        const g = fresh();
        // Seed: the value 500 was first seen STALE_MS ago on the client clock.
        g._state.lastTs = 500;
        g._state.lastAdvance = NOW - C.STALE_MS;
        g._state.boot = 10;
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: 500, state: "run" });
        assert.equal(await g.check(), "ok");
    },

    async "a ts frozen for STALE_MS+1 is down"() {
        const g = fresh();
        g._state.lastTs = 500;
        g._state.lastAdvance = NOW - C.STALE_MS - 1;
        g._state.boot = 10;
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: 500, state: "run" });
        assert.equal(await g.check(), "down");
    },

    async "backoff doubles to the cap and answers from memory meanwhile"() {
        const g = fresh();
        RESPONDER = async () => { throw new Error("still down"); };
        const seen = [];
        for (let i = 0; i < 7; i++) {
            NOW += C.BACKOFF_MAX_MS + C.FETCH_MS;   // past any backoff window
            await g.check();
            seen.push(g._state.backoffMs);
        }
        assert.deepEqual(seen, [3000, 6000, 12000, 24000, 48000, 60000, 60000],
            "3 s base, doubling, capped at 60 s");
        // Inside the window: instant "down", zero fetches.
        const before = FETCHES;
        NOW += 1;
        assert.equal(await g.check(), "down");
        assert.equal(FETCHES, before, "no fetch while backing off");
    },

    async "an advancing ts resets the backoff and returns ok"() {
        const g = fresh();
        RESPONDER = async () => { throw new Error("down"); };
        NOW += C.FETCH_MS + 1; await g.check();
        NOW += C.BACKOFF_MAX_MS; await g.check();
        assert.ok(g._state.backoffMs > 0);
        let ts = 900;
        RESPONDER = async () => mkResp(200, { v: 1, boot: 10, ts: ++ts, state: "run" });
        NOW += C.BACKOFF_MAX_MS;
        assert.equal(await g.check(), "ok");
        assert.equal(g._state.backoffMs, 0, "recovery must clear the backoff");
    },

    async "bootChanged fires once per boot change, never on first sight"() {
        const g = fresh();
        let ts = 100;
        let boot = 111;
        RESPONDER = async () => mkResp(200, { v: 1, boot, ts: ++ts, state: "run" });
        await g.check();
        assert.equal(g.bootChanged(), false, "first sight of a boot is not a change");
        boot = 222;
        NOW += C.FETCH_MS + 1;
        await g.check();
        assert.equal(g.bootChanged(), true, "restart must be reported");
        assert.equal(g.bootChanged(), false, "and reported exactly once");
    },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
    try { await fn(); console.log("  ok  - " + name); }
    catch (e) { failed++; console.error("  FAIL - " + name + "\n        " + e.message); }
}
console.log(`\n${Object.keys(tests).length - failed}/${Object.keys(tests).length} node tests passed`);
process.exit(failed ? 1 : 0);
