// Filename:    test_dash_tile.mjs
// Description: One tile system (v3.37.0). Runs the shipped dashboards-controls.js
//              with the real dashboards-action.js reader and checks: one on/off
//              rule, the toggle confirmed from the device, the heating zone
//              tile (the room page's old copy missed the heater flag in the
//              states and never read a setpoint back), and that the pages no
//              longer carry their own copies of any of it.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.1 (v3.41.0: the hub's device press, one door memory, reading tiles)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

const timers = [];
const els = {};
const box = {
    console, Date, Promise, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    document: { getElementById: id => els[id] || null, createElement: () => ({ style: {} }),
                head: { appendChild() {} }, querySelectorAll: () => [] },
    DashUI: { esc: s => String(s == null ? "" : s).replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`), ago: () => "5m" },
    DashIcons: { svg: n => `<svg data-n="${n}"></svg>` },
};
box.window = box; box.globalThis = box;
vm.createContext(box);
vm.runInContext(read("dashboards-action.js"), box);
vm.runInContext(read("dashboards-controls.js"), box);
const T = box.DashTile;
const flush = async () => { while (timers.length) { const t = timers.shift(); await t.fn(); } await new Promise(r => setImmediate(r)); };

console.log("\none on/off rule");
checkEq("true", T.isOn(true), true);
checkEq("the v2 API's string True", T.isOn("True"), true);
checkEq("1 and on", T.isOn(1) && T.isOn("on"), true);
checkEq("false and False", T.isOn(false) || T.isOn("False"), false);
checkEq("missing is not on", T.isOn(undefined), false);
checkEq("but state() says it cannot tell", T.state(undefined), null);
checkEq("and says so for rubbish too", T.state("maybe"), null);
checkEq("it is DashAction's reader, not a second copy", T.state("yes"), box.DashAction.truthy("yes"));

console.log("\na toggle is confirmed from the device");
{
    const notes = [];
    box.DashAction.note = (k, ph, txt) => notes.push([k, ph, txt]);
    let deviceOn = false;
    T.bind({ toggle: async () => {}, getDevice: async () => ({ onState: deviceOn }) });
    const el = { dataset: { id: "7" }, checked: true, disabled: false };
    await T.toggle(el);
    check("the switch is held while it sends", el.disabled === true);
    await flush();
    check("the device did not follow, so the switch goes back", el.checked === false);
    check("and says so on the tile", notes.some(n => n[0] === "device:7" && n[1] === "timeout"));
    check("and is usable again", el.disabled === false);
    notes.length = 0; deviceOn = true;
    const el2 = { dataset: { id: "8" }, checked: true, disabled: false };
    await T.toggle(el2); await flush();
    check("a device that did follow is left alone", el2.checked === true && !notes.length);
    T.bind({ toggle: async () => { throw new Error("no"); }, getDevice: async () => ({}) });
    const el3 = { dataset: { id: "9" }, checked: true, disabled: false };
    await T.toggle(el3); await flush();
    check("a failed send puts the switch back at once", el3.checked === false);
}

console.log("\nthe heating zone");
{
    const Z = T.zone;
    const trv = (states, extra) => Object.assign({ id: 5, name: "Hall Radiator", hvacMode: "Heat",
        setpointHeat: 20, states: Object.assign({ temperature: "18.5" }, states) }, extra || {});
    check("the heater flag in the STATES counts (the room page's copy missed it)",
          Z.heating(trv({ hvacHeaterIsOn: "True" })) === true);
    check("the flag on the device still counts", Z.heating(trv({}, { hvacHeaterIsOn: true })) === true);
    check("an open valve is heating whatever the flag says", Z.heating(trv({ valvePosition: "40" })) === true);
    check("calling but already warm enough is not heating", Z.heating(trv({ hvacHeaterIsOn: "True", temperature: "20" })) === false);
    const html = Z.render(trv({ hvacHeaterIsOn: "True", humidityInput1: "55", valvePosition: "30",
                                 lastSeen: "2026-09-23 10:00:00" }), { name: "Hall", info: true });
    check("heating class and flame", /class="zone heating"/.test(html) && /zone-flame on/.test(html));
    check("the name the page asked for", /zone-name">Hall</.test(html));
    check("the details button when asked", /openDeviceDetails\(5\)/.test(html));
    check("humidity, valve and last heard in the meta line",
          /55% RH/.test(html) && /valve 30%/.test(html) && /heard 5m/.test(html));
    check("the tile carries the key a note lands on", /data-dsh-act-key="device:5"/.test(html));
    check("the buttons call the shared bump", /DashTile\.zone\.bump\(5, 1\)/.test(html));
    check("no setpoint, no buttons", /setpoint-btn"[^>]*disabled/.test(Z.render(trv({}, { setpointHeat: null }))));
    check("off says Off", /<span>Off<\/span>/.test(Z.render(trv({}, { hvacMode: "Off" }))));
}

console.log("\na setpoint step is read back");
{
    const notes = [];
    box.DashAction.note = (k, ph, txt) => notes.push([k, ph, txt]);
    let reported = 20, sent = [];
    T.bind({ setHeatSetpoint: async (id, v) => { sent.push(v); }, getDevice: async () => ({ setpointHeat: reported }) });
    els["sp-5"] = { dataset: { sp: "20" }, textContent: "20.0°" };
    await T.zone.bump(5, 1);
    checkEq("steps by a whole degree", sent[0], 21);
    checkEq("shows it at once", els["sp-5"].textContent, "21°");
    await T.zone.bump(5, 1);
    checkEq("a second tap chains from the pending value", sent[1], 22);
    await flush();
    check("the plugin kept 20, so the tile says 20 again", els["sp-5"].textContent === "20.0°");
    check("and says why", notes.some(n => n[0] === "device:5" && n[1] === "error"));
    els["sp-6"] = { dataset: { sp: "28" }, textContent: "28.0°" };
    checkEq("at the ceiling nothing is sent", await T.zone.bump(6, 1), false);
    els["sp-7"] = { dataset: { sp: "17.5" }, textContent: "17.5°" };
    sent.length = 0; await T.zone.bump(7, 1);
    checkEq("a half degree rounds in the direction tapped", sent[0], 18);
    await flush();          // let its read-back fire here, not in the next section
}

console.log("\na device tile pressed on the hub (v3.41.0)");
{
    const notes = [];
    box.DashAction.note = (k, ph, txt) => notes.push([k, ph, txt]);
    const mkTile = on => { const st = { textContent: on ? "On" : "Off" }; const cls = new Set(on ? ["on"] : []);
        return { isConnected: true, st, classList: { contains: c => cls.has(c), add: c => cls.add(c), remove: c => cls.delete(c),
                 toggle: (c, f) => (f === undefined ? (cls.has(c) ? cls.delete(c) : cls.add(c)) : (f ? cls.add(c) : cls.delete(c))) },
                 querySelector: () => st, cls }; };
    let reported = true;
    const api = { toggle: async () => {}, getDevice: async () => ({ onState: reported }) };
    const t = mkTile(false);
    const p = T.pressDevice(t, 5, { api, key: "device:5" });
    check("busy while it sends", t.cls.has("busy"));
    await p;
    check("flips at once", t.cls.has("on") && t.st.textContent === "On");
    check("and is no longer busy", !t.cls.has("busy"));
    await flush();
    check("a device that followed is left alone", t.cls.has("on") && !notes.length, JSON.stringify(notes) + " " + [...t.cls]);
    reported = false;
    const t2 = mkTile(false);
    await T.pressDevice(t2, 6, { api, key: "device:6" });
    await flush();
    check("a device that did not follow is put back", !t2.cls.has("on") && t2.st.textContent === "Off");
    check("and says so", notes.some(n => n[0] === "device:6" && n[1] === "timeout"));
    notes.length = 0;
    const t3 = mkTile(true);
    const ok = await T.pressDevice(t3, 7, { api: { toggle: async () => { throw Object.assign(new Error("offline"), { status: 0 }); } }, key: "device:7" });
    check("a failed send changes nothing", ok === false && t3.cls.has("on"));
    check("and names the failure", notes.some(n => n[0] === "device:7" && n[1] === "error" && /offline/.test(n[2])));
    notes.length = 0;
    await T.pressDevice(mkTile(true), 8, { api: { toggle: async () => { throw Object.assign(new Error("x"), { status: 401 }); } } });
    check("an auth failure is left to the page", !notes.length);
}

console.log("\none memory of each door (v3.41.0)");
{
    const A = box.DashAction;
    A.reset();
    checkEq("closed", A.doorTileRemembered(9, "closed").label, "Closed");
    checkEq("then moving is Opening", A.doorTileRemembered(9, "moving").label, "Opening…");
    checkEq("open", A.doorTileRemembered(9, "open").label, "Open");
    checkEq("then moving is Closing", A.doorTileRemembered(9, "moving").label, "Closing…");
    checkEq("another door keeps its own memory", A.doorTileRemembered(10, "moving").label, "Moving…");
    A.reset();
    checkEq("reset forgets", A.doorTileRemembered(9, "moving").label, "Moving…");
}

console.log("\nthe pages carry no copies");
for (const page of ["room.html", "active.html", "heating.html"]) {
    const src = read(page);
    check(`${page} loads the shared module`, src.includes('<script src="dashboards-controls.js"></script>'));
    check(`${page} has no toggle or zone copy of its own`,
          !/function (onToggle|_confirmToggle|onSliderCommit|renderZone|bumpSetpoint|isHeating|getSetpoint)\(/.test(src));
    check(`${page} links the shared tile stylesheet`, src.includes('href="dashboards-controls.css"'));
}
{
    const css = read("dashboards-controls.css");
    for (const sel of [".light-card", ".toggle .slider", ".zone", ".setpoint-btn", ".cur-temp.cold"]) {
        check(`the stylesheet has ${sel}`, css.includes(sel + " {"));
    }
    for (const page of ["room.html", "heating.html", "active.html", "ecowitt.html"]) {
        const style = (read(page).match(/<style>([\s\S]*?)<\/style>/) || ["", ""])[1];
        check(`${page} no longer defines .toggle or .zone itself`, !/^\s*\.(toggle|zone) \{/m.test(style));
    }
}
check("the room page's own three-state reader is gone", !/_threeState/.test(read("room.html")));
{
    const hub = read("index.html");
    check("the hub loads the tile module after DashAction",
          hub.indexOf('<script src="dashboards-action.js">') < hub.indexOf('<script src="dashboards-controls.js">')
          && hub.includes('<script src="dashboards-controls.js">'));
    check("the hub's favourite press is the shared one", hub.includes("DashTile.pressDevice(tile, id,"));
    check("no page keeps its own door memory", !/_doorLast/.test(hub) && !/_doorLast/.test(read("room.html")));
    check("a reading tile is not a button", /<div class="fav-tile fav-reading" role="group"/.test(hub)
          && !/<button class="fav-tile fav-reading"/.test(hub));
}
check("no page tests on/off with === true any more",
      ["room.html", "active.html"].every(p => !/onState === true/.test(read(p))));

done();
