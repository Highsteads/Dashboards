// Filename:    test_tiles_not_live.mjs
// Description: A tile must not show a reading nobody has measured (3.73.4).
//              Found in the 25/26-Nov-2026 review:
//                1. room.html handed Array.map's index to renderMotion as its
//                   wording, so every motion tile after the first had no
//                   state word at all ("· 3m ago").
//                2. Only "disabled" and "error" marked a tile as not live. A
//                   Shelly that has dropped off the network keeps its last
//                   on/off and watts with an empty errorState, and read as
//                   live on room tiles, hub favourites, doors and locks.
//                3. The heating zone tile drew a disabled or silent zone as
//                   live, with its buttons on.
//                4. Indigo's times carry no zone and were read in the
//                   BROWSER's zone, so from Australia every age was eleven
//                   hours out and every radiator read as stale.
//              Runs the shipped room.html, index.html, dashboards-ui.js,
//              dashboards-action.js and dashboards-controls.js.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_tiles_not_live.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

// The viewer is in Sydney for every check below; the server is in London.
process.env.TZ = "Australia/Sydney";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

function extractFn(src, name) {
    const start = src.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("function not found: " + name);
    let depth = 0;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (!depth) return src.slice(start, j + 1); }
    }
    throw new Error("unbalanced braces in " + name);
}

// ── the shared pieces, as the pages load them ────────────────────────────
function loadShared(config) {
    const box = {
        console, Promise, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN,
        setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
        AbortController,
        document: { getElementById: () => null, createElement: () => ({ style: {} }),
                    head: { appendChild() {} }, querySelectorAll: () => [],
                    addEventListener() {}, documentElement: { style: {} } },
        INDIGO_CONFIG: Object.assign({ apiKey: "k" }, config || {}),
        DashIcons: { svg: n => `<svg data-n="${n}"></svg>`, has: () => false },
    };
    box.window = box; box.globalThis = box;
    vm.createContext(box);
    vm.runInContext(read("dashboards-ui.js"), box);
    vm.runInContext(read("dashboards-action.js"), box);
    vm.runInContext(read("dashboards-controls.js"), box);
    return box;
}

const LONDON = { serverTz: "Europe/London", serverUtcOffsetMin: 0 };
const box = loadShared(LONDON);
const UI = box.DashUI, T = box.DashTile;

console.log("\nIndigo's times are read in the server's zone, not the viewer's");
check("the helper exists", typeof UI.serverTime === "function");
if (typeof UI.serverTime === "function") {
    checkEq("a winter time with a T", UI.serverTime("2026-11-25T23:12:32"), Date.UTC(2026, 10, 25, 23, 12, 32));
    checkEq("the same with a space (RAMSES lastSeen)", UI.serverTime("2026-11-25 23:12:32"), Date.UTC(2026, 10, 25, 23, 12, 32));
    checkEq("a summer time is an hour ahead of UTC", UI.serverTime("2026-07-01T12:00:00"), Date.UTC(2026, 6, 1, 11, 0, 0));
    checkEq("a time that names its zone is left alone", UI.serverTime("2026-11-25T23:12:32Z"), Date.UTC(2026, 10, 25, 23, 12, 32));
    checkEq("and one with an offset", UI.serverTime("2026-11-25T23:12:32+11:00"), Date.UTC(2026, 10, 25, 12, 12, 32));
    check("rubbish is not a time", isNaN(UI.serverTime("Excellent")) && isNaN(UI.serverTime("")) && isNaN(UI.serverTime(null)));
    const now = Date.UTC(2026, 10, 25, 23, 15, 32);
    checkEq("an age is right from Sydney", UI.ago("2026-11-25T23:12:32", { now }), "3m ago");
    // An older plugin publishes no zone: only the offset, then nothing.
    const offOnly = loadShared({ serverUtcOffsetMin: 60 });
    checkEq("with only an offset, that offset is used", offOnly.DashUI.serverTime("2026-07-01T12:00:00"), Date.UTC(2026, 6, 1, 11, 0, 0));
    const none = loadShared({});
    checkEq("with neither, it falls back to the browser's reading", none.DashUI.serverTime("2026-11-25T23:12:32"),
            new Date(2026, 10, 25, 23, 12, 32).getTime());
}

console.log("\none rule for a tile that cannot be believed");
checkEq("disabled", T.unknownReason({ enabled: false, states: {} }), "disabled");
checkEq("an error", T.unknownReason({ errorState: "no ack", states: {} }), "error");
checkEq("a Shelly off the network", T.unknownReason({ errorState: "", states: { deviceOnline: false } }), "not answering");
checkEq("the v2 API's string", T.unknownReason({ states: { deviceOnline: "False" } }), "not answering");
checkEq("Tasmota availability", T.unknownReason({ states: { availability: "Offline" } }), "not answering");
checkEq("ESPHome connected", T.unknownReason({ states: { connected: false } }), "not answering");
checkEq("a live device", T.unknownReason({ enabled: true, errorState: "", states: { deviceOnline: true } }), "");

console.log("\nthe heating zone tile");
const zone = extra => Object.assign({ id: 7, name: "En Suite Radiator", enabled: true, errorState: "", hvacMode: "Heat",
    setpointHeat: 22, states: { temperatureInput1: 17.4, hvacHeaterIsOn: true, lastSeen: "2026-11-25 23:10:00" } }, extra);
const realNow = Date.now;
vm.runInContext("Date.now = function () { return " + Date.UTC(2026, 10, 25, 23, 15, 0) + "; };", box);
const live = T.zone.render(zone({}));
check("a live zone calls for heat", /Calling for heat/.test(live) && /class="zone heating"/.test(live));
check("and was heard five minutes ago, even from Sydney", /heard 5m ago/.test(live) && !/trv-age stale/.test(live), live.match(/heard[^<]*/));
const off = T.zone.render(zone({ enabled: false }));
check("a disabled zone says so", /Disabled in Indigo/.test(off), off.match(/zone-meta.*/));
check("claims no heat", !/Calling for heat/.test(off) && !/class="zone heating/.test(off) && !/zone-flame on/.test(off));
check("is marked unknown", /class="zone unknown"/.test(off));
check("and its buttons are off", (off.match(/setpoint-btn"[^>]*disabled/g) || []).length === 2);
const err = T.zone.render(zone({ errorState: "valve silent" }));
check("a zone in error says so", /reports an error/.test(err) && !/Calling for heat/.test(err));
const gw = T.zone.render(zone({ states: { temperatureInput1: 17.4, hvacHeaterIsOn: true, gatewayStatus: "offline" } }));
check("a zone behind an offline gateway says so", /Heating gateway offline/.test(gw) && !/Calling for heat/.test(gw) && /class="zone unknown"/.test(gw));
check("its buttons stay, so the press can explain itself", !/setpoint-btn"[^>]*disabled/.test(gw));
checkEq("a setpoint that is not a number is no setpoint", T.zone.setpoint({ setpointHeat: "n/a", states: {} }), null);
vm.runInContext("Date.now = " + "function () { return " + realNow() + "; };", box);

console.log("\nthe group tile leaves out a member that cannot be believed");
const byId = new Map([[1, { id: 1, onState: true, states: {} }],
                      [2, { id: 2, onState: true, enabled: false, states: {} }],
                      [3, { id: 3, onState: false, states: { deviceOnline: false } }]]);
const g = box.DashAction.groupTile([{ id: 1 }, { id: 2 }, { id: 3 }], byId);
checkEq("one believed, two unknown", [g.on, g.total, g.unknown], [1, 1, 2]);

// ── room.html ────────────────────────────────────────────────────────────
console.log("\nroom page");
const room = read("room.html");
{
    const ctx = vm.createContext({ console, DashTile: T, DashUI: UI,
        escapeHtml: s => String(s == null ? "" : s), prettyMotionName: n => n,
        formatWhen: () => "3m ago" });
    vm.runInContext(extractFn(room, "_motionWording"), ctx);
    vm.runInContext(extractFn(room, "tileAge"), ctx);
    vm.runInContext(extractFn(room, "renderMotion"), ctx);
    // The page's own call, lifted from its Motion section.
    const call = /html \+= '<div class="grid">' \+ (motion\.map\([^;]*\))\.join\(""\)/.exec(room);
    check("the Motion section's call was found", !!call);
    ctx.motion = [{ id: 1, name: "Left Presence", onState: false, lastChanged: "x", states: {} },
                  { id: 2, name: "Right Presence", onState: false, lastChanged: "x", states: {} },
                  { id: 3, name: "Twigs Presence", onState: true, lastChanged: "x", states: {} }];
    const tiles = call ? vm.runInContext(call[1], ctx) : [];
    const word = h => (/motion-state">\s*([^·<]*)·/.exec(h) || [])[1].trim();
    checkEq("every motion tile says its state, not only the first", tiles.map(word), ["Clear", "Clear", "Motion"]);
    ctx.d = { id: 4, name: "Left Window", onState: false, lastChanged: "2026-11-25T23:12:32",
              states: { lastSeen: "2026-11-25 22:36:04" } };
    ctx.formatWhen = v => "<" + v + ">";
    const win = vm.runInContext('renderMotion(d, { on: "Open", off: "Closed" })', ctx);
    check("a sensor that says when it was last heard shows that, not the record's last write",
          /Closed · heard <2026-11-25 22:36:04>/.test(win), (/motion-state">([^<]*)/.exec(win) || [])[1]);
    ctx.d = { id: 5, name: "Rear Garage Person", onState: false, lastChanged: "2026-11-25T23:12:32", states: {} };
    const plain = vm.runInContext("renderMotion(d)", ctx);
    check("one that does not keeps the record's time", /Clear · <2026-11-25T23:12:32>/.test(plain), (/motion-state">([^<]*)/.exec(plain) || [])[1]);
}
{
    // The door tile that follows a door device.
    const ctx = vm.createContext({ console, DashTile: T, window: { DashAction: box.DashAction }, DashAction: box.DashAction,
        escapeHtml: s => String(s == null ? "" : s) });
    vm.runInContext(extractFn(room, "renderStateDoorTile"), ctx);
    ctx.door = { label: "Garage Door", deviceId: 9, openAction: 11, closeAction: 12 };
    ctx.devs = [{ id: 9, name: "Garage Door", enabled: true, errorState: "", states: { doorState: "closed" } }];
    const ok = vm.runInContext("renderStateDoorTile(door, devs, true)", ctx);
    check("a live closed door offers Press to Open", />Press to Open</.test(ok) && !/disabled/.test(ok));
    ctx.devs = [{ id: 9, name: "Garage Door", enabled: false, errorState: "", states: { doorState: "closed" } }];
    const dead = vm.runInContext("renderStateDoorTile(door, devs, true)", ctx);
    check("a disabled door device is not called Closed", !/>Closed</.test(dead) && /Disabled/.test(dead), (/door-status">([^<]*)/.exec(dead) || [])[1]);
    check("and its button is off", /<button class="door-btn"[^>]*disabled/.test(dead));
}
check("the TV and Lights buttons decide from believable devices only",
      /function decides\(d\)/.test(room) && /tv\.filter\(decides\)/.test(room) && /others\.filter\(d => !OPEN_LOOP_IDS\.has\(d\.id\) && decides\(d\)\)/.test(room));
{
    // toggleTv decides from the feed, by the same rule as its label.
    const sent = [];
    const ctx = vm.createContext({ console, DashTile: T, TV_IDS: new Set([1, 2]),
        window: { __lastDevices: [{ id: 1, onState: false, states: {} },
                                  { id: 2, onState: true, enabled: false, states: {} }] },
        document: { querySelector: () => ({ checked: true }) },
        sendToAll: async (key, ids, fn) => { sent.push(fn); } });
    vm.runInContext(extractFn(room, "decides"), ctx);
    vm.runInContext(extractFn(room, "toggleTv"), ctx);
    await vm.runInContext("toggleTv()", ctx);
    checkEq("a disabled set frozen 'on' does not turn All On into All Off", sent, ["turnOn"]);
}

// ── index.html (the hub) ─────────────────────────────────────────────────
console.log("\nhub favourites");
const hub = read("index.html");
{
    const host = { id: "favourites", innerHTML: "", style: { display: "" } };
    const ctx = vm.createContext({ console,
        document: { getElementById: id => (id === "favourites" ? host : null) },
        window: { INDIGO_CONFIG: { favourites: [] }, DashAction: box.DashAction },
        escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
        DashAction: box.DashAction, DashTile: T, DashIcons: { has: () => false, svg: () => "" } });
    vm.runInContext(extractFn(hub, "spokenWhen"), ctx);
    vm.runInContext(extractFn(hub, "hidePinnedNavCards"), ctx);
    vm.runInContext(extractFn(hub, "favNotLive"), ctx);
    vm.runInContext(extractFn(hub, "renderFavouritesCard"), ctx);
    const render = (favs, devices) => {
        ctx.window.INDIGO_CONFIG.favourites = favs; ctx.__d = devices;
        vm.runInContext("renderFavouritesCard(__d)", ctx);
        return host.innerHTML;
    };
    const car = { id: 5, name: "Qashqai Battery Monitor", enabled: true, errorState: "unreachable",
                  states: { voltage: 12.12, "voltage.ui": "12.12 V" } };
    const reading = [{ type: "device", id: 5, label: "Qashqai 12V", state: "voltage", warnBelow: 12.2, badBelow: 11.8 }];
    const away = render(reading, [car]);
    check("a reading from a device in error is not shown as a reading", !/12\.12/.test(away) && /Not answering|Error/i.test(away), (/fav-state[^>]*>([^<]*)/.exec(away) || [])[1]);
    check("and carries no colour band", !/fav-val-(good|warn|bad)/.test(away) && /off-line/.test(away));
    const home = render(reading, [Object.assign({}, car, { errorState: "" })]);
    check("a live reading still shows, with its band", /12\.12 V/.test(home) && /fav-val-warn/.test(home));
    const blank = render(reading, [Object.assign({}, car, { errorState: "", states: { voltage: "" } })]);
    check("an empty reading gets a dash and no colour", /fav-state val">—</.test(blank), (/fav-state[^>]*>[^<]*/.exec(blank) || [])[0]);
    const sw = render([{ type: "device", id: 6 }], [{ id: 6, name: "Twigs", onState: true, enabled: true, errorState: "", states: { deviceOnline: false } }]);
    check("a switch that is not answering does not read On", !/>On</.test(sw) && /Not answering/.test(sw) && /data-fav-dead="1"/.test(sw));
    const lock = [{ type: "door", id: 7, lockId: 8, openAction: 1, label: "Front Door" }];
    const locked = render(lock, [{ id: 7, enabled: true, errorState: "", states: { onOffState: false } },
                                 { id: 8, enabled: true, errorState: "", states: { onOffState: true } }]);
    check("a live locked door reads Locked", />Locked</.test(locked));
    const silent = render(lock, [{ id: 7, enabled: true, errorState: "", states: { onOffState: false } },
                                 { id: 8, enabled: true, errorState: "no ack", states: { onOffState: true } }]);
    check("a lock in error is not called Locked", !/>Locked</.test(silent) && /data-door-intent=""/.test(silent), (/fav-state">([^<]*)/.exec(silent) || [])[1]);
    const garage = [{ type: "door", id: 9, openAction: 1, closeAction: 2, label: "Garage" }];
    const gone = render(garage, [{ id: 9, enabled: false, errorState: "", states: { doorState: "closed" } }]);
    check("a disabled door device is not called Closed", !/>Closed</.test(gone) && /data-door-intent=""/.test(gone), (/fav-state">([^<]*)/.exec(gone) || [])[1]);
}
check("the hub's Not live row no longer says 'ago ago'", !/DashUI\.ago\(sigen\.lastChanged\)\) \+ " ago"/.test(hub));
check("the hub reads the Sigen device's time in the server's zone", /DashUI\.serverTime\(sigen\.lastChanged\)/.test(hub));

// ── nothing parses a server time in the browser's zone any more ──────────
console.log("\nno page reads a zone-less server time with Date.parse");
check("dashboards-controls.js", /root\.DashUI\.serverTime\(v\)/.test(read("dashboards-controls.js")));
for (const [file, bad] of [["heating.html", /Date\.parse\(String\(out\.lastSuccessfulComm/],
                           ["ecowitt.html", /Date\.parse\(String\(dev\.lastSuccessfulComm/],
                           ["index.html", /Date\.parse\((sigen|a|b)\.lastChanged/]]) {
    check(file, !bad.test(read(file)));
}
{
    const calc = read("energy-calc.js");
    const ctx = vm.createContext({ console, DashUI: UI });
    vm.runInContext(extractFn(calc, "localStamp"), ctx);
    checkEq("the car charger's last report is read in the server's zone",
            vm.runInContext('localStamp("2026-11-25 23:12:32")', ctx), Date.UTC(2026, 10, 25, 23, 12, 32));
}

done();
