// Filename:    test_camera_watch.mjs
// Description: Pages tell the plugin which cameras they are showing (3.48.0),
//              because it now takes stills only of those. Runs the real
//              DashUI.noteStillWanted against a fake plugin: a new camera is
//              reported at once, the report repeats while stills are being
//              fetched, stops when they stop, says nothing from a hidden tab
//              or the demo, and refreshStill and the Cameras page both feed
//              it. The page wiring is read with comments stripped.
// Author:      CliveS & Claude Opus 5.5
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_camera_watch.mjs

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/.*$/gm, "");

// A controllable clock and timers, so ten seconds pass in no time.
let clock = 1_000_000;
let timers = [];
let nextId = 1;
const fakeSetTimeout = (fn, ms) => { const id = nextId++; timers.push({ id, at: clock + ms, fn, every: 0 }); return id; };
const fakeSetInterval = (fn, ms) => { const id = nextId++; timers.push({ id, at: clock + ms, fn, every: ms }); return id; };
const fakeClear = id => { timers = timers.filter(t => t.id !== id); };
// Let every pending promise (the fake plugin's reply) finish before time moves.
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise(r => setImmediate(r)); };
async function advance(ms) {
    const end = clock + ms;
    for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const t = timers[0];
        if (!t || t.at > end) break;
        clock = t.at;
        if (t.every) t.at += t.every; else timers.shift();
        t.fn();
        await settle();
    }
    clock = end;
    await settle();
}

const sent = [];
let failNext = false;
const doc = { hidden: false, createElement: () => ({ style: {} }), documentElement: {} };
const w = {
    document: doc,
    INDIGO_CONFIG: { apiKey: "k" },
    matchMedia: () => ({ matches: true }),
    getComputedStyle: () => ({ position: "relative", objectFit: "cover" }),
    requestAnimationFrame: f => f(),
    setTimeout: fakeSetTimeout, clearTimeout: fakeClear,
    setInterval: fakeSetInterval, clearInterval: fakeClear,
    AbortController,
    fetch: async (url, opts) => {
        if (!/\/message\//.test(url)) return { status: 304, ok: false, headers: { get: () => null } };
        const name = url.split("/").filter(Boolean).pop();
        sent.push({ name, body: JSON.parse(opts.body), at: clock });
        if (failNext) { failNext = false; throw new Error("network down"); }
        return { status: 200, ok: true, headers: { get: () => "application/json" },
                 json: async () => ({ ok: true }), text: async () => '{"ok":true}' };
    },
    URL: { createObjectURL: () => "blob:1", revokeObjectURL: () => {} },
    Image: function () {},
};
w.window = w;
const c = { window: w, self: w, globalThis: w, console, navigator: {}, location: { hostname: "x" },
            Date: class extends Date { static now() { return clock; } } };
Object.assign(c, w);
vm.createContext(c);
vm.runInContext(read("dashboards-ui.js"), c);
const DashUI = c.DashUI || w.DashUI;

const reports = () => sent.filter(s => s.name === "watchCameras");

console.log("\nwhich host a still is for");
checkEq("full picture", DashUI.stillHost("stills-abc/cam-192.0.2.10.jpg"), "192.0.2.10");
checkEq("thumbnail", DashUI.stillHost("stills-abc/cam-192.0.2.10-thumb.jpg"), "192.0.2.10");
checkEq("a host name with a query", DashUI.stillHost("/public/dashboards/stills-x/cam-drive-cam.local.jpg?x=1"), "drive-cam.local");
checkEq("not a still", DashUI.stillHost("streams.json"), null);

console.log("\na new camera is reported at once, then every ten seconds");
DashUI.noteStillWanted("stills-x/cam-192.0.2.10-thumb.jpg");
await advance(300);
checkEq("one report within a quarter of a second", reports().length, 1);
checkEq("naming the camera", JSON.stringify(reports()[0].body), JSON.stringify({ hosts: ["192.0.2.10"] }));

DashUI.noteStillWanted("192.0.2.11");              // a bare host, as the Cameras page passes
await advance(300);
checkEq("a second camera goes out at once too", reports().length, 2);
checkEq("with both in it", JSON.stringify(reports()[1].body.hosts), JSON.stringify(["192.0.2.10", "192.0.2.11"]));

// Keep "fetching" both for a while: the report repeats on the interval, and
// an already-reported camera does not trigger an early one.
for (let i = 0; i < 6; i++) {           // twelve seconds: past the first ten-second report
    DashUI.noteStillWanted("192.0.2.10"); DashUI.noteStillWanted("192.0.2.11");
    await advance(2000);
}
const n = reports().length;
check("repeats about every ten seconds while stills are fetched", n === 3, `got ${n}`);

console.log("\nit stops when the page stops fetching");
await advance(30000);
const after = reports().length;
check("at most one more report, then silence", after - n <= 1, `got ${after - n} more`);
const lastHosts = reports()[after - 1].body.hosts;
await advance(60000);
checkEq("nothing at all once the stills have stopped", reports().length, after);
check("and the last report named only cameras still being fetched", lastHosts.length <= 2);

console.log("\na hidden tab says nothing");
doc.hidden = true;
DashUI.noteStillWanted("192.0.2.12");
await advance(20000);
checkEq("no report from a hidden tab", reports().length, after);
doc.hidden = false;
DashUI.noteStillWanted("192.0.2.12");
await advance(300);
checkEq("back on screen, reported at once", reports().length, after + 1);

console.log("\na failed report is tried again");
DashUI.noteStillWanted("192.0.2.12");
failNext = true;
await advance(10100);
const failedAt = reports().length;
DashUI.noteStillWanted("192.0.2.12");
await advance(10100);
check("the next ping goes out after a failure", reports().length > failedAt);

console.log("\nrefreshStill feeds it");
const before = reports().length;
await advance(30000);                               // let everything lapse
const img = { isConnected: true, parentElement: {}, src: "", getAttribute: () => null };
await DashUI.refreshStill(img, "stills-x/cam-192.0.2.13-thumb.jpg", {
    fetch: async () => ({ status: 304, ok: false, headers: { get: () => null } }) });
await advance(300);
const last = reports()[reports().length - 1];
check("a refreshed still is reported", reports().length > before && last.body.hosts.includes("192.0.2.13"));

console.log("\nthe demo has no plugin to tell");
w.INDIGO_CONFIG.apiKey = "demo";
const demoBefore = sent.length;
DashUI.noteStillWanted("192.0.2.14");
await advance(20000);
checkEq("nothing sent in the demo", sent.length, demoBefore);
w.INDIGO_CONFIG.apiKey = "k";

console.log("\nthe Cameras page reports what it fetches");
const cams = strip(read("cameras.html"));
const i = cams.indexOf("if (DashUI.noteStillWanted) DashUI.noteStillWanted(host);");
check("fetchFrame names the camera", i > 0);
check("before the in-flight guard, so a slow link still counts as watching",
      i > 0 && i < cams.indexOf("if (st.fetching) return Promise.resolve();"));
check("after the reflector idle pause, so a paused page lets the camera go",
      i > cams.indexOf("if (_idlePaused) return Promise.resolve();"));

done();
