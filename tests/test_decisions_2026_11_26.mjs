// Filename:    test_decisions_2026_11_26.mjs
// Description: The page side of CliveS's answers to the deep review's
//              questions (3.74.0, 26-Nov-2026):
//                - a floor probe is left out of the Heating page's average,
//                  coldest and warmest;
//                - a window or door sensor not heard from for longer than its
//                  limit is "not heard from", named on the hub and left out
//                  of "All closed";
//                - an open window or door says for how long, from the
//                  plugin's own record;
//                - the Energy, Flow and hub pages say what the Flux
//                  controller is doing while it holds the inverter;
//                - the hub's VPP row says the figure is the month's;
//                - the Wi-Fi page does not print a failed speed test as 0;
//                - the Settings page sends back the store's revision.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_decisions_2026_11_26.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
function extractFn(s, name) {
    const start = s.indexOf("function " + name + "(");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}
// The shared helpers, loaded whole, as a page loads them.
function loadShared(cfg) {
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, Intl,
                  INDIGO_CONFIG: Object.assign({ serverUtcOffsetMin: 0 }, cfg || {}),
                  document: { addEventListener() {}, querySelectorAll: () => [], getElementById: () => null, body: {} } };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    vm.runInContext(read("dashboards-controls.js"), win);
    return win;
}
const NOW = Date.UTC(2026, 10, 26, 12, 0, 0);
const stamp = ms => new Date(ms).toISOString().slice(0, 19).replace("T", " ");

console.log("a window or door sensor that has gone quiet");
{
    const win = loadShared({ contactSilent: { hours: 13, byDevice: { "7": 4 } } });
    const T = win.DashTile;
    const contact = (id, hoursAgo, extra) => Object.assign({ id, name: "Window " + id, enabled: true, errorState: "",
        deviceTypeId: "z2mContactSensor", onState: false, states: { lastSeen: stamp(NOW - hoursAgo * 3600000) } }, extra);
    checkEq("heard five hours ago, limit 13: counted", T.silentHours(contact(1, 5), NOW), 0);
    check("heard twenty hours ago, limit 13: silent for twenty", Math.round(T.silentHours(contact(1, 20), NOW)) === 20);
    check("one of the fast sensors, limit 4, heard five hours ago: silent", T.silentHours(contact(7, 5), NOW) > 4);
    checkEq("a sensor that gives no last-heard time is not judged", T.silentHours(contact(1, 0, { states: {} }), NOW), 0);
    checkEq("nor is a device that is not a contact sensor",
            T.silentHours({ id: 3, deviceTypeId: "z2mRelay", states: { lastSeen: stamp(NOW - 99 * 3600000) } }, NOW), 0);
    const real = Date.now; Date.now = () => NOW;
    vm.runInContext("Date.now = () => " + NOW + ";", win);
    checkEq("every tile then calls it unknown", T.unknownReason(contact(1, 20)), "not heard from");
    checkEq("and a healthy one is not", T.unknownReason(contact(1, 5)), "");
    Date.now = real;
    const off = loadShared({ contactSilent: { hours: 0, byDevice: {} } });
    checkEq("0 hours switches the check off", off.DashTile.silentHours(contact(1, 500), NOW), 0);
    checkEq("an older plugin that sends no limit judges nothing", loadShared({}).DashTile.silentHours(contact(1, 500), NOW), 0);

    const hub = read("index.html");
    const c = vm.createContext({ console, DashTile: T, Math });
    vm.runInContext(extractFn(hub, "contactsNote") + "\nglobalThis.N = contactsNote;", c);
    const a = contact(1, 5), b = contact(2, 20, { name: "Kitchen Window" }), d = contact(3, 1, { enabled: false });
    checkEq("every sensor counted: no note", c.N([a], [a], NOW), "");
    checkEq("one silent sensor is named, with how long",
            c.N([a, b], [a], NOW), "Kitchen Window has not been heard from for 20 hours. Not counted above.");
    checkEq("a silent one and an unreadable one",
            c.N([a, b, d], [a], NOW), "Kitchen Window has not been heard from for 20 hours, and 1 sensor cannot be read. Not counted above.");
    checkEq("two silent", c.N([a, b, contact(4, 30)], [a], NOW), "2 sensors have not been heard from. Not counted above.");
    check("the hub shows it under an all-closed line and under an open list",
          (hub.match(/note \? `<div class="row"><span class="warn">\$\{escapeAttr\(note\)\}<\/span><\/div>` : ""/g) || []).length === 2);
}

console.log("\nan open window or door says for how long");
{
    const win = loadShared({});
    const U = win.DashUI;
    checkEq("before the plugin has said anything: not known", U.openFor(5, NOW), null);
    U.noteOpenSince({ "5": 1000, "6": 4000 }, 4600, NOW);                 // server clock 4600 s at the reply
    checkEq("opened an hour ago by the server's clock", U.openFor(5, NOW), 3600000);
    checkEq("and it keeps counting on this device's clock", U.openFor(5, NOW + 120000), 3720000);
    checkEq("one the plugin did not see open", U.openFor(9, NOW), null);
    checkEq("in words", [U.openWords(6, NOW), U.openWords(5, NOW), U.openWords(9, NOW)],
            ["open for 10 minutes", "open for 1 hour", "open"]);
    const hub = read("index.html"), room = read("room.html"), api = read("dashboard.js");
    check("the change poll hands the times over", /window\.DashUI\.noteOpenSince\(resp\.openSince, resp\.now\);/.test(api));
    check("the hub's list uses them, not the device's last change",
          /DashUI\.openWords\(d\.id\)/.test(hub) && !/class="when warn">\$\{escapeAttr\(relTime\(d\.lastChanged\)\)\}/.test(hub));
    check("so does a room's window tile", /`Open for \$\{DashUI\.ago\(openMs, \{ words: true \}\)\}`/.test(room));
}

console.log("\nHeating: a floor probe is not a room");
{
    const win = loadShared({ notRoomTemp: [9] });
    const heat = read("heating.html");
    const ctx = vm.createContext({ console, Math, String, parseFloat, isFinite, isNaN, JSON, Object, Number, Set, Date,
        DashTile: win.DashTile, DashUI: win.DashUI, window: { INDIGO_CONFIG: { notRoomTemp: [9] } } });
    vm.runInContext(`const getCurrentTemp = DashTile.zone.currentTemp; const TRV_STALE_MS = DashTile.zone.TRV_STALE_MS;
        function cleanZoneName(s) { return String(s || ""); } function escapeHtml(s) { return String(s); } function I() { return ""; }
        ${extractFn(heat, "houseSummaryCard")}
        globalThis.H = houseSummaryCard;`, ctx);
    const secs = Math.floor(Date.now() / 1000);
    const zone = (id, name, t) => ({ id, name, enabled: true, errorState: "", pluginId: "uk.co.clives.ramses.esp",
        states: { temperatureInput1: t, temperatureSeenEpoch: secs - 60, setpointHeat: 18 }, temperatures: [t] });
    const zones = [zone(1, "Hall", 18), zone(2, "Kitchen", 20), zone(9, "En Suite Floor", 8)];
    const withFloor = ctx.H(zones, zones);
    check("the average is of the two rooms", /19\.0°<\/div><div class="h-mlab">House avg/.test(withFloor), (/[\d.]+°<\/div><div class="h-mlab">House avg/.exec(withFloor) || [])[0]);
    check("the coldest is a room, not the floor", /Coldest<span class="h-msub">Hall/.test(withFloor) && !/En Suite Floor/.test(withFloor.split("Coldest")[1].split("</div>")[0]));
    ctx.window.INDIGO_CONFIG.notRoomTemp = [];
    const all = ctx.H(zones, zones);
    check("unticked, the floor counts as before", /15\.3°<\/div><div class="h-mlab">House avg/.test(all) && /Coldest<span class="h-msub">En Suite Floor/.test(all));
}

console.log("\nwhat the Flux controller is doing");
{
    const win = loadShared({});
    const F = win.DashUI.fluxDoing;
    checkEq("an older manager sends no flux block", F({ decision: { action: "self_consumption" } }), null);
    checkEq("Flux not in charge", F({ flux: { owns: false, mode: "charge" } }), null);
    checkEq("the 2am charge", F({ flux: { owns: true, mode: "charge", status: "charge: buying 20 kWh" } }).label, "Charging from the grid");
    checkEq("the peak sale", F({ flux: { owns: true, mode: "export" } }).doing, "Selling to the grid at the peak rate");
    checkEq("a mode this page does not know says nothing rather than something wrong", F({ flux: { owns: true, mode: "brand_new" } }), null);
    const box = { console, Math, Number, String, isFinite, parseFloat, Date, DashUI: win.DashUI };
    box.window = box; vm.createContext(box);
    vm.runInContext(read("flow-popups.js"), box);
    const view = st => box.FlowPopups.batteryView(st, NOW).lines.find(l => l.key === "doing").text;
    const base = { battery: { soc_pct: 40, capacity_kwh: 35, power_w: 9800 }, decision: { action: "self_consumption" } };
    check("without Flux in charge the old line stands", /solar is charging it/.test(view(base)), view(base));
    checkEq("a Flux grid charge is not called solar",
            view(Object.assign({}, base, { flux: { owns: true, mode: "charge" } })),
            "Charging from the grid on the cheap rate, taking 9.8 kW.");
    checkEq("a Flux sale", view({ battery: { soc_pct: 80, capacity_kwh: 35, power_w: -10000 }, decision: { action: "self_consumption" }, flux: { owns: true, mode: "export" } }),
            "Selling to the grid at the peak rate, giving 10 kW.");
    const energy = read("energy.html"), hub = read("index.html");
    check("the Energy page's chip, badge, reason and flow line ask the same question",
          (energy.match(/DashUI\.fluxDoing/g) || []).length >= 4);
    check("so does the hub's Now row", /const fxHub = \(window\.DashUI && DashUI\.fluxDoing\) \? DashUI\.fluxDoing\(_sigen\(\)\) : null;/.test(hub));
}

console.log("\nsmall wording");
{
    const hub = read("index.html");
    const c = vm.createContext({ console, Number });
    vm.runInContext(extractFn(hub, "vppEarningsRow") + "\nglobalThis.V = vppEarningsRow;", c);
    check("the VPP row says its figure is the month's", />VPP earned this month</.test(c.V({ earnings: { month_to_date_gbp: 16.02, lifetime_gbp: 135.48 } })));
    check("with only a lifetime figure it does not claim a month", />VPP earned</.test(c.V({ earnings: { lifetime_gbp: 135.48 } })));
    const wifi = read("wifi.html");
    const w = vm.createContext({ console, String, num: v => (v == null || v === "" ? null : Number(v)), fmtNum: v => String(v) });
    vm.runInContext(extractFn(wifi, "speedTestWords") + "\nglobalThis.S = speedTestWords;", w);
    checkEq("a test that worked", w.S({ speedtestDown: 512.3, speedtestUp: 110 }), { down: "512.3", up: "110", failed: false });
    checkEq("0 down and 0 up is a failed test, not a dead line", w.S({ speedtestDown: 0, speedtestUp: 0 }), { down: "—", up: "—", failed: true });
    checkEq("the router's own word for it wins", w.S({ speedtestDown: 3, speedtestUp: 1, speedtestStatus: "Error" }).failed, true);
    // 3.74.1: UniFi Health 0.10.0 sends the word, and where there is one the
    // page no longer guesses from the figures.
    checkEq("a word that is not a failure is believed over two noughts",
        w.S({ speedtestDown: 0, speedtestUp: 0, speedtestStatus: "Success" }), { down: "0", up: "0", failed: false });
    checkEq("the real failed record: Error with two noughts",
        w.S({ speedtestDown: 0, speedtestUp: 0, speedtestStatus: "Error" }), { down: "—", up: "—", failed: true });
    checkEq("a blank word is no word: an older UniFi Health is still judged on the figures",
        w.S({ speedtestDown: 0, speedtestUp: 0, speedtestStatus: "" }).failed, true);
    checkEq("a blank word with real figures is a test that worked",
        w.S({ speedtestDown: 512.3, speedtestUp: 110, speedtestStatus: "  " }).failed, false);
    check("the not-live card shows a failed last test as dashes too",
        /const last = speedTestWords\(s\);/.test(wifi) && /\$\{last\.down\}/.test(wifi) && !/\$\{fmtNum\(s\.speedtestDown\)\}/.test(wifi));
    check("the card says the last test failed", /st\.failed \? 'Last test failed' : 'Tested'/.test(wifi));
}

console.log("\nSettings: an old tab cannot overwrite a newer save");
{
    const set = read("settings.html");
    check("the page keeps the revision it loaded", /window\._cfgRev = \(typeof res\.rev === "string"\) \? res\.rev : "";/.test(set));
    check("and sends it back with the save", /api\("saveDashboardsConfig", \{ config: cfg, rev: window\._cfgRev \}\)/.test(set));
    check("the new card is on the page", /main\.appendChild\(renderHeatingSensors\(\)\);/.test(set));
    const els = { hours: { value: " 13 " }, ticks: [{ dataset: { id: "9" } }, { dataset: { id: "x" } }] };
    const c = vm.createContext({ console, Array, Number, Object, isNaN, cfg: { contactSilent: { hours: 25, byDevice: { "7": 4 } } } });
    vm.runInContext(extractFn(set, "collectHeatingSensors") + "\nglobalThis.C = collectHeatingSensors;", c);
    const root = { querySelector: s => (s === "#silent-hours" ? els.hours : null), querySelectorAll: () => els.ticks };
    checkEq("the form's values, with a sensor's own limit kept",
            c.C(root), { notRoomTemp: [9], contactSilent: { hours: 13, byDevice: { "7": 4 } } });
    els.hours.value = "";
    checkEq("a blank limit goes back to the default", c.C(root).contactSilent, { byDevice: { "7": 4 } });
    checkEq("with the card not on the page the stored values are left alone", c.C({ querySelector: () => null, querySelectorAll: () => [] }), null);
}

done();
