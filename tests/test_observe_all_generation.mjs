// Filename:    test_observe_all_generation.mjs
// Description: observeAll used to JSON.stringify the whole device list (685 kB
//              here) every 3 s to find out whether anything had changed. It
//              now re-renders when a generation counter on the SHARED store
//              moves. The counter has to live on the store, not the call:
//              another IndigoAPI's delta cycle (DashAction.selfPoll, the hub's
//              own) can absorb a change first, and this observer's next cycle
//              then sees nothing changed. These drive two real IndigoAPI
//              instances against one store with a fake network and fake timers.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_observe_all_generation.mjs

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboard.js");

let listStringified = 0;
const JSONspy = {
    parse: JSON.parse,
    stringify(v, ...rest) {
        if (Array.isArray(v)) listStringified++;
        return JSON.stringify(v, ...rest);
    },
};
const ticks = [];
const ctx = {
    window: { INDIGO_CONFIG: null },
    location: { protocol: "http:", hostname: "192.0.2.1" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
    setInterval: (fn) => { ticks.push(fn); return ticks.length; },
    clearInterval() {},
    fetch: async () => { throw new Error("no network"); },
    console, Date, Promise, JSON: JSONspy,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(SRC, "utf8") +
    "\n;globalThis.__t = { IndigoAPI, STORE: _INDIGO_STORE };", ctx);
const { IndigoAPI, STORE } = ctx.__t;

// The server: a device table, and the changedSince reply each cycle reads.
const server = new Map([[1, { id: 1, name: "Lamp", onState: false }],
                        [2, { id: 2, name: "Fan",  onState: false }]]);
let pending = { changed: [], deleted: [] };
let clock = 100;
function api() {
    const a = new IndigoAPI({ apiKey: "k", baseURL: "x" });
    a._fetch = async (p) => {
        if (p === "/v2/api/indigo.devices") return Array.from(server.values()).map(d => ({ ...d }));
        // changedSince: hand the pending window to whichever cycle asks first
        const r = { ok: true, now: ++clock, changed: pending.changed, deleted: pending.deleted };
        pending = { changed: [], deleted: [] };
        return r;
    };
    a.getDevice = async (id) => ({ ...server.get(id) });
    return a;
}
const flush = () => new Promise(r => setImmediate(r));

const hub = api();
const other = api();                       // e.g. DashAction.selfPoll
const drawn = [];
hub.observeAll(list => drawn.push(list.map(d => `${d.id}:${d.onState}`).join(",")));
await flush();
const tick = ticks[0];

check("first poll draws the list", drawn.length === 1, JSON.stringify(drawn));

await tick(); await flush();
await tick(); await flush();
check("nothing changed: no redraw", drawn.length === 1, JSON.stringify(drawn));

// A change the OTHER instance's cycle absorbs first.
server.get(1).onState = true;
pending = { changed: [1], deleted: [] };
await other.getDevices();
await tick(); await flush();
check("a change absorbed by another caller's cycle still redraws",
      drawn.length === 2 && drawn[1] === "1:true,2:false", JSON.stringify(drawn));

// A deletion.
server.delete(2);
pending = { changed: [], deleted: [2] };
await tick(); await flush();
check("a deleted device redraws", drawn.length === 3 && drawn[2] === "1:true", JSON.stringify(drawn));

// Deleting an id the cache never held is not a change.
pending = { changed: [], deleted: [99] };
await tick(); await flush();
check("deleting an unknown id does not redraw", drawn.length === 3, JSON.stringify(drawn));

// A forced full resync is a new list.
STORE.lastFull = 0;
await tick(); await flush();
check("a full refresh redraws", drawn.length === 4, JSON.stringify(drawn));

check("the device list is never serialised to detect change", listStringified === 0,
      `${listStringified} stringify calls on a list`);

done();
