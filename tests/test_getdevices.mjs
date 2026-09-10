// Filename:    test_getdevices.mjs
// Description: Node contract test for dashboard.js getDevices() delta-merge —
//              the module-level device cache + changedSince cursor logic. Locks
//              the v2.37.0 fix: the delta cursor (sinceTs) only advances after
//              every changed device is refetched successfully, so a transient
//              getDevice failure re-requests that window instead of leaving the
//              device silently stale until the 5-min full resync.
// Author:      CliveS & Claude Fable 5
// Date:        15-07-2026
// Version:     1.0
//
// Run: node tests/test_getdevices.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboard.js");

// A controllable clock so we can drive the 5-minute safety-refresh branch.
let NOW = 1_000_000;
const FakeDate = { now: () => NOW };

function loadApi() {
    const ctx = {
        window: { INDIGO_CONFIG: null },
        location: { protocol: "http:", hostname: "192.168.1.10" },
        localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
        sessionStorage: { getItem: () => null, setItem: () => {} },
        fetch: async () => { throw new Error("no network in test"); },
        Date: FakeDate,
        console,
    };
    vm.createContext(ctx);
    const code = fs.readFileSync(SRC, "utf8") +
        "\n;globalThis.__t = { IndigoAPI, IndigoAPIError, _INDIGO_STORE, __win: window };";
    vm.runInContext(code, ctx);
    return ctx.__t;
}

const T = loadApi();
const STORE = T._INDIGO_STORE;
const WIN = T.__win;   // the vm's `window` — lets tests install a fake DashGate

function newApi() {
    const api = new T.IndigoAPI({ apiKey: "k", baseURL: "x" });
    // Neutralise the network-facing methods; each test overrides as needed.
    api._fetch = async () => { throw new Error("unexpected _fetch"); };
    api.getDevice = async () => { throw new Error("unexpected getDevice"); };
    api._fullDeviceFetch = async () => {
        STORE.devices = new Map([[1, { id: 1, name: "full" }]]);
        STORE.lastFull = FakeDate.now();
        api._fullCalls = (api._fullCalls || 0) + 1;
        return Array.from(STORE.devices.values());
    };
    return api;
}

function resetStore() {
    STORE.devices = null; STORE.sinceTs = 0; STORE.lastFull = 0;
    delete WIN.DashGate;   // gate absent unless a test installs one
}

const tests = {
    async "first call with empty cache does a full fetch"() {
        resetStore();
        const api = newApi();
        // A healthy delta reply, but no cache yet — must still full-fetch.
        api._fetch = async () => ({ ok: true, now: 5, changed: [], deleted: [] });
        const out = await api.getDevices();
        assert.equal(api._fullCalls, 1);
        assert.equal(out.length, 1);
    },

    async "resp.full:true forces a full refetch"() {
        resetStore();
        STORE.devices = new Map([[9, { id: 9 }]]);
        STORE.lastFull = FakeDate.now();
        const api = newApi();
        api._fetch = async () => ({ ok: true, full: true, now: 5 });
        await api.getDevices();
        assert.equal(api._fullCalls, 1);
    },

    async "delta merges changed and removes deleted, advancing the cursor"() {
        resetStore();
        STORE.devices = new Map([[3, { id: 3 }], [5, { id: 5, name: "old" }]]);
        STORE.lastFull = FakeDate.now();
        STORE.sinceTs = 10;
        const api = newApi();
        api._fetch = async () => ({ ok: true, now: 42, changed: [7], deleted: [3] });
        api.getDevice = async (id) => ({ id, name: "fresh" + id });
        const out = await api.getDevices();
        assert.equal(api._fullCalls || 0, 0, "must NOT full-fetch");
        assert.ok(!STORE.devices.has(3), "deleted id removed");
        assert.equal(STORE.devices.get(7).name, "fresh7", "changed id merged");
        assert.equal(STORE.sinceTs, 42, "cursor advanced to resp.now");
        assert.equal(out.length, 2);
    },

    async "a transient getDevice failure does NOT advance the cursor"() {
        resetStore();
        STORE.devices = new Map([[5, { id: 5 }]]);
        STORE.lastFull = FakeDate.now();
        STORE.sinceTs = 10;
        const api = newApi();
        api._fetch = async () => ({ ok: true, now: 99, changed: [7], deleted: [] });
        api.getDevice = async () => { throw new Error("transient"); };
        await api.getDevices();
        assert.equal(STORE.sinceTs, 10, "cursor stays put so the window re-requests");
    },

    async "a 401 from the delta endpoint rethrows"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        const api = newApi();
        api._fetch = async () => { throw new T.IndigoAPIError("auth", 401); };
        await assert.rejects(() => api.getDevices(), /auth/);
    },

    // v2.70.0: ONLY a 404/405 (older plugin without the endpoint) may fall
    // back to a full fetch. A network error or 5xx is an OUTAGE — falling back
    // there was the amplifier that fired a 685 kB full fetch every 3 s from
    // every open tab for the whole ~5-min IWS wedge.
    async "a 404 from the delta endpoint falls back to a full fetch (legacy plugin)"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        const api = newApi();
        api._fetch = async () => { throw new T.IndigoAPIError("HTTP 404", 404); };
        await api.getDevices();
        assert.equal(api._fullCalls, 1);
    },

    async "a network error from the delta endpoint rethrows and does NOT full-fetch"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        const api = newApi();
        api._fetch = async () => { throw new T.IndigoAPIError("Network error: x", 0); };
        await assert.rejects(() => api.getDevices(), /Network error/);
        assert.equal(api._fullCalls || 0, 0, "no same-tick full fetch into an outage");
    },

    async "a 500 from the delta endpoint rethrows and does NOT full-fetch"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        const api = newApi();
        api._fetch = async () => { throw new T.IndigoAPIError("HTTP 500", 500); };
        await assert.rejects(() => api.getDevices(), /HTTP 500/);
        assert.equal(api._fullCalls || 0, 0);
    },

    async "a stale cache older than 5 minutes triggers a full refresh"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now() - 300001;   // just past _FULL_REFRESH_MS
        STORE.sinceTs = 10;
        const api = newApi();
        api._fetch = async () => ({ ok: true, now: 50, changed: [], deleted: [] });
        await api.getDevices();
        assert.equal(api._fullCalls, 1);
    },

    // ── v2.55.0: the full-fetch path must SEED the delta cursor ──────────
    // These drive the REAL _fullDeviceFetch. Every test above stubs it out,
    // which is precisely how the cursor bug survived them: the cursor is only
    // ever wrong inside the function they replaced.
    async "the real full fetch seeds the cursor from the server clock"() {
        resetStore();
        const api = newApi();
        delete api._fullDeviceFetch;                 // use the shipped one
        api._fetch = async (p) => (String(p).includes("changedSince")
            ? { ok: true, full: true, now: 1234 }
            : [{ id: 1, name: "a" }, { id: 2, name: "b" }]);
        await api.getDevices();
        assert.equal(STORE.sinceTs, 1234,
            "cursor must take the server clock, else it stays 0 for ever");
    },

    async "a second poll after a full fetch uses the DELTA, not another full fetch"() {
        // The regression that matters: before v2.55.0 the cursor never left 0,
        // the server answered since<=0 with full:true, and every 3s poll
        // refetched the whole device list — measured at 685 kB a time against
        // a 498-byte delta reply.
        resetStore();
        const api = newApi();
        delete api._fullDeviceFetch;
        let fullFetches = 0, deltaCalls = 0, lastSince = null;
        api._fetch = async (p, opts) => {
            if (String(p).includes("changedSince")) {
                deltaCalls++;
                lastSince = JSON.parse(opts.body).since;
                return lastSince <= 0
                    ? { ok: true, full: true, now: 1000 }     // server's rule
                    : { ok: true, now: 1001, changed: [], deleted: [] };
            }
            fullFetches++;
            return [{ id: 1, name: "a" }];
        };
        await api.getDevices();                      // cold: full fetch
        assert.equal(fullFetches, 1);
        await api.getDevices();                      // warm: must be delta only
        assert.equal(deltaCalls, 2);
        assert.ok(lastSince > 0, "second poll must ask with a real cursor");
        assert.equal(fullFetches, 1, "second poll must NOT refetch everything");
        assert.equal(STORE.sinceTs, 1001);
    },

    async "a legacy plugin (delta 404) still seeds a usable cursor"() {
        // No server clock available. Falling back to the local clock is
        // slightly wrong but recoverable; leaving the cursor at 0 is not.
        resetStore();
        const api = newApi();
        delete api._fullDeviceFetch;
        api._fetch = async (p) => {
            if (String(p).includes("changedSince")) throw new T.IndigoAPIError("HTTP 404", 404);
            return [{ id: 1, name: "a" }];
        };
        await api.getDevices();
        assert.ok(STORE.sinceTs > 0, "cursor must not be left pinned at 0");
    },

    // ── v2.70.0: the DashGate liveness gate ──────────────────────────────
    async "gate down serves the cached list with zero network calls"() {
        resetStore();
        STORE.devices = new Map([[4, { id: 4, name: "cached" }]]);
        STORE.lastFull = FakeDate.now();
        WIN.DashGate = { check: async () => "down", bootChanged: () => false };
        const api = newApi();   // _fetch/getDevice/_fullDeviceFetch all throw if touched
        api._fullDeviceFetch = async () => { throw new Error("must not full-fetch"); };
        const out = await api.getDevices();
        assert.equal(out.length, 1);
        assert.equal(out[0].name, "cached");
    },

    async "gate down with an empty cache throws rather than calling /message/"() {
        resetStore();
        WIN.DashGate = { check: async () => "down", bootChanged: () => false };
        const api = newApi();
        await assert.rejects(() => api.getDevices(), /restarting/);
    },

    async "gate nogate proceeds exactly as before"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        STORE.sinceTs = 10;
        WIN.DashGate = { check: async () => "nogate", bootChanged: () => false };
        const api = newApi();
        api._fetch = async () => ({ ok: true, now: 42, changed: [], deleted: [] });
        await api.getDevices();
        assert.equal(STORE.sinceTs, 42);
    },

    async "a boot change drops the cursor so the server answers full:true"() {
        resetStore();
        STORE.devices = new Map([[1, { id: 1 }]]);
        STORE.lastFull = FakeDate.now();
        STORE.sinceTs = 10;
        let fired = false;
        WIN.DashGate = { check: async () => "ok",
                         bootChanged: () => { const f = !fired; fired = true; return f; } };
        const api = newApi();
        let lastSince = null;
        api._fetch = async (p, opts) => {
            lastSince = JSON.parse(opts.body).since;
            return { ok: true, full: true, now: 77 };
        };
        await api.getDevices();
        assert.equal(lastSince, 0, "cursor must reset after a plugin restart");
        assert.equal(api._fullCalls, 1, "and the reply's full:true resyncs the cache");
    },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
    try { await fn(); console.log("  ok  - " + name); }
    catch (e) { failed++; console.error("  FAIL - " + name + "\n        " + e.message); }
}
console.log(`\n${Object.keys(tests).length - failed}/${Object.keys(tests).length} node tests passed`);
process.exit(failed ? 1 : 0);
