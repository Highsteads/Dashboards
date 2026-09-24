// Filename:    test_still_conditional_refresh.mjs
// Description: The hub strip and the room tiles added a ?_t= cache-buster to
//              every still and downloaded the whole picture each tick. Only
//              the Cameras page asked with If-Modified-Since, which IWS
//              answers with a 53-byte 304 when nothing has changed (an offline
//              camera, a paused poller). DashUI.refreshStill now does that for
//              both. This runs the real function against a fake fetch, and
//              reads the two pages' wiring with comments stripped.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_still_conditional_refresh.mjs

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/.*$/gm, "");

// ── the helper itself ──────────────────────────────────────────────────────
const made = [], revoked = [];
let nextBlob = 0;
const w = {
    document: { createElement: () => ({ style: {} }), documentElement: {} },
    matchMedia: () => ({ matches: true }),                 // reduced motion: plain swap
    getComputedStyle: () => ({ position: "relative", objectFit: "cover" }),
    requestAnimationFrame: f => f(),
    setTimeout, clearTimeout, AbortController,
    URL: { createObjectURL: () => { const u = "blob:" + (++nextBlob); made.push(u); return u; },
           revokeObjectURL: u => revoked.push(u) },
    Image: function () {
        const self = this;
        Object.defineProperty(self, "src", { set(v) { self._s = v; setTimeout(() => self.onload(), 0); },
                                             get() { return self._s; } });
    },
};
w.window = w;
const c = { window: w, self: w, globalThis: w, console, navigator: {}, location: { hostname: "x" } };
Object.assign(c, w);
vm.createContext(c);
vm.runInContext(read("dashboards-ui.js"), c);
const DashUI = c.DashUI || w.DashUI;

const calls = [];
let reply = null;
const fakeFetch = async (url, opts) => {
    calls.push({ url, ims: (opts.headers || {})["If-Modified-Since"] || null, cache: opts.cache });
    const r = reply;
    return { status: r.status, ok: r.status >= 200 && r.status < 300,
             headers: { get: k => (k === "Last-Modified" ? r.mod || null : null) },
             blob: async () => ({ size: 10 }) };
};
const img = { isConnected: true, attrs: {}, parentElement: {}, src: "",
              getAttribute(k) { return k === "src" ? this.src || null : null; } };

console.log("\nDashUI.refreshStill asks with If-Modified-Since");
check("exported", typeof DashUI.refreshStill === "function");

reply = { status: 200, mod: "Wed, 24 Sep 2026 10:00:00 GMT" };
let out = await DashUI.refreshStill(img, "stills-x/cam-1-thumb.jpg", { fetch: fakeFetch });
checkEq("a first picture is fetched and shown", out, true);
check("with no conditional header and no cache-buster", calls[0].ims === null && !/_t=/.test(calls[0].url), JSON.stringify(calls[0]));
check("and the browser cache kept out of it", calls[0].cache === "no-store");
checkEq("the tile shows it", img.src, "blob:1");

reply = { status: 304 };
out = await DashUI.refreshStill(img, "stills-x/cam-1-thumb.jpg", { fetch: fakeFetch });
checkEq("an unchanged picture is a 304", out, "same");
checkEq("asked with the Last-Modified it was given", calls[1].ims, "Wed, 24 Sep 2026 10:00:00 GMT");
check("and nothing is decoded or swapped", img.src === "blob:1" && made.length === 1);

reply = { status: 200, mod: "Wed, 24 Sep 2026 10:00:02 GMT" };
out = await DashUI.refreshStill(img, "stills-x/cam-1-thumb.jpg", { fetch: fakeFetch });
check("a new picture replaces it", out === true && img.src === "blob:2");
check("and the old picture's blob is let go", revoked.includes("blob:1") && !revoked.includes("blob:2"));

reply = { status: 200, mod: "Wed, 24 Sep 2026 10:00:03 GMT" };
await DashUI.refreshStill(img, "stills-x/cam-1.jpg", { fetch: fakeFetch });
checkEq("another size starts afresh, with no conditional header", calls[3].ims, null);

reply = { status: 404 };
let err = null;
await DashUI.refreshStill(img, "stills-x/cam-9-thumb.jpg", { fetch: fakeFetch }).catch(e => { err = e; });
check("a missing picture rejects with its status, so the caller can fall back", err && err.status === 404);

let release;
const slow = () => new Promise(r => { release = () => r({ status: 304, ok: false, headers: { get: () => null } }); });
const p1 = DashUI.refreshStill(img, "stills-x/cam-1.jpg", { fetch: slow });
checkEq("a second request while one is in flight is skipped", await DashUI.refreshStill(img, "stills-x/cam-1.jpg", { fetch: slow }), false);
release(); await p1;

// ── the two pages use it ───────────────────────────────────────────────────
console.log("\nthe hub strip and room tiles use it, not a cache-buster");
for (const page of ["index.html", "room.html"]) {
    const src = strip(read(page));
    check(`${page} adds no ?_t= cache-buster`, !/_t=/.test(src));
    check(`${page} refreshes through DashUI.refreshStill`, /DashUI\.refreshStill\(img, /.test(src));
    check(`${page} falls back to the full picture only on a 404`, /e\.status === 404/.test(src));
}

done();
