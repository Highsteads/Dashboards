// Filename:    test_alerts_shared.mjs
// Description: The Alerts rules fire from every main page, once (3.46.0).
//              The watcher lived inline in alerts.html, so a rule only ever
//              fired while that one page was open, whatever the page and
//              the docs said. It is dashboards-alerts.js now, loaded by the
//              hub, the room pages, Energy and Alerts. These checks drive
//              the shipped file: the evaluators, a second rule on the same
//              device (which the inline watcher never fired), two tabs that
//              both see one change raising ONE notification, the per-rule
//              cooldown across tabs, a tab standing by while another polls,
//              and a browser whose storage throws still alerting on its own.
// Author:      CliveS & Claude Opus 5.5
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_alerts_shared.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const SRC = fs.readFileSync(path.join(PAGES, "dashboards-alerts.js"), "utf8");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function sharedStorage() {
    const m = new Map();
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), _m: m };
}
const throwingStorage = {
    getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("SecurityError"); },
};

// One browser tab: its own module instance, a storage it may share.
function tab(storage) {
    const shown = [];
    function Notification(title, opts) { shown.push({ title, body: opts.body }); }
    Notification.permission = "granted";
    const win = { localStorage: storage, Notification, INDIGO_CONFIG: { siteName: "Home" },
                  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
                  Map, JSON, Math, Date, Object, String, Array, Promise,
                  navigator: {} };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(SRC, win, { filename: "dashboards-alerts.js" });
    return { win, A: win.DashAlerts, shown };
}
function api(devs, vars = []) {
    return { getDevices: async () => devs.map(d => ({ ...d })), getVariables: async () => vars.map(v => ({ ...v })) };
}

// ── the evaluators ──
{
    const { A } = tab(sharedStorage());
    const r = (cond) => ({ kind: "device", id: 1, name: "Lamp", cond });
    const off = { on: false, ui: "off" }, on = { on: true, ui: "on" };
    check("turns on: off -> on fires", A.judgeDevice(r("on"), off, on) === "Lamp turned on");
    check("turns on: on -> on is quiet", A.judgeDevice(r("on"), on, on) === null);
    check("turns off: on -> off fires", A.judgeDevice(r("off"), on, off) === "Lamp turned off");
    check("changes: a new display value fires", A.judgeDevice(r("change"), { on: true, ui: "40%" }, { on: true, ui: "60%" }) === "Lamp: 60%");
    check("no earlier reading is never a change", A.judgeDevice(r("on"), undefined, on) === null);
    const v = { kind: "variable", id: 9, name: "Mode", cond: "change" };
    check("a variable that changed fires", A.judgeVariable(v, { val: "home" }, "away") === "Mode is now away");
    check("a variable that did not is quiet", A.judgeVariable(v, { val: "home" }, "home") === null);
    check("deviceNow reads onState and the display value", JSON.stringify(A.deviceNow({ onState: 1, displayStateValUi: null })) === '{"on":true,"ui":""}');
}

// ── one tab: two rules on one device both fire ──
{
    const store = sharedStorage();
    const t = tab(store);
    t.A.save({ rules: [{ kind: "device", id: 5, name: "Hall", cond: "on", enabled: true },
                       { kind: "device", id: 5, name: "Hall", cond: "off", enabled: true }], active: true });
    const devs = [{ id: 5, onState: false, displayStateValUi: "off" }];
    const w = t.A.watch({ api: api(devs) });
    await w.pollDevices();                                   // seeds
    devs[0].onState = true; devs[0].displayStateValUi = "on";
    await w.pollDevices();
    await sleep(300);
    check("the first poll only seeds: nothing fired for the current state", t.shown.length === 1, JSON.stringify(t.shown));
    check("turns on fired", t.shown.some(s => s.body === "Hall turned on"));
    devs[0].onState = false; devs[0].displayStateValUi = "off";
    await w.pollDevices();
    await sleep(300);
    check("the SECOND rule on the same device fires too (the inline watcher never did)",
          t.shown.some(s => s.body === "Hall turned off"), JSON.stringify(t.shown));
    check("the alert is logged where Alerts can read it", t.A.readLog().length === 2);
    check("the title is the site name", t.shown[0].title === "Home");
    w.stop();
}

// ── two tabs, one change, one notification ──
{
    const store = sharedStorage();
    const a = tab(store), b = tab(store);
    a.A.save({ rules: [{ kind: "device", id: 7, name: "Door", cond: "on", enabled: true }], active: true });
    const devs = [{ id: 7, onState: false, displayStateValUi: "closed" }];
    // Both poll (Alerts always does; the other is the tab that polled first).
    const wa = a.A.watch({ api: api(devs), alwaysPoll: true });
    const wb = b.A.watch({ api: api(devs), alwaysPoll: true });
    await wa.pollDevices(); await wb.pollDevices();
    devs[0].onState = true;
    await Promise.all([wa.pollDevices(), wb.pollDevices()]);
    await sleep(300);
    const total = a.shown.length + b.shown.length;
    check("two tabs that both saw the change raise ONE notification", total === 1, `a=${a.shown.length} b=${b.shown.length}`);
    check("and log it once", a.A.readLog().length === 1, JSON.stringify(a.A.readLog()));
    // the cooldown holds across tabs
    devs[0].onState = false; await wa.pollDevices(); await wb.pollDevices();
    devs[0].onState = true; await wa.pollDevices(); await wb.pollDevices();
    await sleep(300);
    check("inside the 30 s cooldown neither tab raises it again", a.shown.length + b.shown.length === 1);
    wa.stop(); wb.stop();
}

// ── a tab stands by while another polls ──
{
    const store = sharedStorage();
    const a = tab(store), b = tab(store);
    let asked = 0;
    const counting = { getDevices: async () => { asked++; return []; }, getVariables: async () => [] };
    a.A.save({ rules: [{ kind: "device", id: 1, name: "X", cond: "on", enabled: true }], active: true });
    const wa = a.A.watch({ api: { getDevices: async () => [], getVariables: async () => [] } });
    await wa.pollDevices();
    const wb = b.A.watch({ api: counting });
    await wb.pollDevices();
    check("a second hub tab does not poll while the first one is", asked === 0, `asked ${asked}`);
    // the first tab goes quiet: its beat ages past the window
    const beat = JSON.parse(store.getItem("dash_alerts_beat"));
    store.setItem("dash_alerts_beat", JSON.stringify({ tab: beat.tab, t: beat.t - a.A.BEAT_STALE_MS - 1 }));
    await wb.pollDevices();
    check("and takes over once the first one has gone quiet", asked === 1, `asked ${asked}`);
    wa.stop(); wb.stop();
}

// ── the master switch and storage that throws ──
{
    const store = sharedStorage();
    const t = tab(store);
    t.A.save({ rules: [{ kind: "device", id: 2, name: "Fan", cond: "on", enabled: true }], active: false });
    check("the alerts-active switch is kept with the rules", t.A.load().active === false);
    const devs = [{ id: 2, onState: false }];
    const w = t.A.watch({ api: api(devs) });
    await w.pollDevices(); devs[0].onState = true; await w.pollDevices(); await sleep(300);
    check("switched off, nothing fires", t.shown.length === 0);
    w.stop();

    const lone = tab(throwingStorage);
    check("storage that throws loads as no rules, not an exception", lone.A.load().rules.length === 0);
    check("a claim still works on its own", lone.A.claim("device:1:on", "me", 1000, throwingStorage) === true);
    check("and its own cooldown still holds", lone.A.claim("device:1:on", "me", 2000, throwingStorage) === false);
    check("and it still counts as ours", lone.A.stillOurs("device:1:on", "me", throwingStorage) === true);
}

// ── the pages ──
{
    const alerts = fs.readFileSync(path.join(PAGES, "alerts.html"), "utf8");
    check("alerts.html loads the shared watcher", alerts.includes('<script src="dashboards-alerts.js"></script>'));
    check("alerts.html no longer carries its own watcher",
          !/setInterval\(pollDevices/.test(alerts) && !/function fire\(/.test(alerts));
    check("alerts.html starts it with alwaysPoll", /DashAlerts\.watch\(\{[^}]*alwaysPoll:\s*true/.test(alerts));
    check("alerts.html no longer says only this page counts",
          !/While this page —\s*or the dashboard installed on your home screen/.test(alerts));
    for (const page of ["index.html", "room.html", "energy.html"]) {
        const src = fs.readFileSync(path.join(PAGES, page), "utf8");
        const iDash = src.indexOf('src="dashboard.js"'), iAl = src.indexOf('src="dashboards-alerts.js"');
        check(`${page} loads dashboards-alerts.js after dashboard.js`, iDash >= 0 && iAl > iDash);
    }
    const guest = fs.readFileSync(path.join(PAGES, "guest.html"), "utf8");
    check("the guest page does not", !guest.includes("dashboards-alerts.js"));
    check("autoStart never runs for a guest or the demo",
          /if \(!cfg\.apiKey \|\| cfg\.apiKey === 'demo'\) return;/.test(SRC));
}

done();
