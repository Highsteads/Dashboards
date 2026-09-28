// Filename:    test_car_charger.mjs
// Description: Node contract test for DashCalc.chargerDevices / chargerView,
//              the Energy page's car charger card (v3.55.0) and the hub's
//              car charger strip (v3.56.0), the mode buttons (v3.57.0) and
//              the boost buttons (v3.58.0). The fixture is
//              the Zappi device exactly as /v2/api/indigo.devices returned it
//              on 28-09-2026 (states only, address left out), so it tests
//              what the Zappi plugin really writes.
// Author:      CliveS & Claude Opus 5.5
// Date:        28-09-2026
// Version:     1.3
//
// Run: node tests/test_car_charger.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const ctx = { window: {}, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "energy-calc.js"), "utf8"), ctx);
const C = ctx.window.DashCalc;

const NOW = new Date(2026, 8, 28, 18, 30, 0).getTime();
const stamp = (msAgo) => {
    const d = new Date(NOW - msAgo), p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

// Measured 28-09-2026 18:2x from the live plugin (Zappi 1.0).
function zappi(overrides = {}, top = {}) {
    return Object.assign({
        id: 58134337, name: "Zappi", enabled: true, errorState: "",
        pluginId: "com.clives.indigoplugin.zappi", deviceTypeId: "zappi",
        states: Object.assign({
            status: "Unplugged, Eco+", plugState: "unplugged", chargeState: "paused",
            mode: "ecoPlus", chargePowerW: 0, sessionKwh: 0.0, online: true,
            guardState: "exporting", guardPausedFrom: "", minGreenLevel: 50,
            lastReport: stamp(20 * 1000),
        }, overrides),
    }, top);
}
const tile = (v, lab) => v.tiles.find((t) => t.lab === lab);

// ── which devices ──
const other = { id: 1, name: "Sigenergy Inverter", pluginId: "com.clives.indigoplugin.sigenergy-energy-manager",
                deviceTypeId: "sigenergyInverter", states: {} };
check("no Zappi device -> no card", C.chargerDevices([other]).length === 0);
check("finds the Zappi", C.chargerDevices([other, zappi()]).length === 1);
check("a disabled Zappi is left out", C.chargerDevices([zappi({}, { enabled: false })]).length === 0);
check("copes with no device list", C.chargerDevices(null).length === 0);
check("two chargers sorted by name",
      C.chargerDevices([zappi({}, { name: "Zappi 2" }), zappi({}, { name: "Drive" })]).map((d) => d.name).join() === "Drive,Zappi 2");

// ── the real device today ──
let v = C.chargerView(zappi(), NOW);
check("headline is the plugin's own status line", v.headline === "Unplugged, Eco+");
check("live", v.live === true && v.tiles.length === 5);
check("car tile", tile(v, "Car").val === "Unplugged" && tile(v, "Car").sub === "nothing connected");
check("mode tile", tile(v, "Mode").val === "Eco+" && tile(v, "Mode").sub === "surplus only");
check("not charging", tile(v, "Into the car").val === "Not charging");
check("session", tile(v, "This session").val === "0.0 kWh");
check("guard exporting, nothing to pause", tile(v, "Export guard").val === "Battery exporting");

// ── charging ──
v = C.chargerView(zappi({ status: "Charging, Fast", plugState: "charging", chargeState: "charging",
                          mode: "fast", chargePowerW: 7123, sessionKwh: 12.46, guardState: "watching" }), NOW);
check("charging power in kW", tile(v, "Into the car").val === "7.12 kW" && tile(v, "Into the car").cls === "good");
check("session to one place", tile(v, "This session").val === "12.5 kWh");
check("charging tone", v.tone === "good" && tile(v, "Car").sub === "charging");
check("charging state with no power is not 'charging at 0 W'",
      tile(C.chargerView(zappi({ plugState: "charging", chargeState: "charging", chargePowerW: 0 }), NOW), "Into the car").val === "Not charging");

// ── the guard holding it ──
v = C.chargerView(zappi({ status: "Paused while the battery exports", plugState: "connected", mode: "stopped",
                          guardState: "paused", guardPausedFrom: "ecoPlus" }), NOW);
check("paused says what it goes back to", tile(v, "Export guard").sub === "back to Eco+ after the export");
check("paused mode explains itself", tile(v, "Mode").val === "Stopped" && tile(v, "Mode").sub === "held by the export guard");
check("paused note + tone", v.tone === "warn" && /selling to the grid/.test(v.note));
check("guard off", tile(C.chargerView(zappi({ guardState: "off" }), NOW), "Export guard").val === "Off");
check("guard cannot read", tile(C.chargerView(zappi({ guardState: "unknown" }), NOW), "Export guard").cls === "warn");

// ── readings withheld ──
v = C.chargerView(zappi({ online: false, plugState: "charging", chargeState: "charging", chargePowerW: 7000 }), NOW);
check("offline hides the readings", !v.live && v.tiles.length === 0 && v.headline === "Not reachable through myenergi");
check("the string 'False' is not online", !C.chargerView(zappi({ online: "False" }), NOW).live);
check("the string 'True' is online", C.chargerView(zappi({ online: "True" }), NOW).live);
check("an error state hides the readings", !C.chargerView(zappi({}, { errorState: "offline" }), NOW).live);
check("login refused is named", C.chargerView(zappi({}, { errorState: "login refused" }), NOW).headline === "myenergi refused the login");
v = C.chargerView(zappi({ lastReport: stamp(11 * 60 * 1000) }), NOW);
check("an old report hides the readings", !v.live && /11 minutes ago/.test(v.note));
check("nine minutes is still live", C.chargerView(zappi({ lastReport: stamp(9 * 60 * 1000) }), NOW).live);
check("no report time hides the readings", !C.chargerView(zappi({ lastReport: "" }), NOW).live);

// ── a value the page does not know yet shows, never vanishes ──
v = C.chargerView(zappi({ mode: "turbo", plugState: "docked" }), NOW);
check("unknown mode shown in quotes", tile(v, "Mode").val === '"turbo"');
check("unknown plug state shown in quotes", tile(v, "Car").val === '"docked"');
check("fault", C.chargerView(zappi({ plugState: "fault" }), NOW).tone === "warn");

// ── the page is wired to it ──
const html = fs.readFileSync(path.join(PAGES, "energy.html"), "utf8");
check("card is on the page, hidden to start", /<section class="card" id="ev-card" style="display:none">/.test(html));
check("the title is the charger's own name, not a second \"Car charger\"", /<span id="ev-title">/.test(html) && /chargers\[0\]\.name/.test(html));
check("the device poll draws it", /renderBattHealth\(\);[\s\S]{0,120}renderCharger\(\)/.test(html));

// ── mode buttons (v3.57.0) ──
let live = C.chargerView(zappi(), NOW);
let mb = C.chargerModeButtons(live, null, NOW);
check("four buttons in order", mb.buttons.map((b) => b.mode).join() === "fast,eco,ecoPlus,stopped");
check("the current mode is marked and not pressable", mb.buttons[2].current && mb.buttons[2].disabled);
check("the others are pressable", !mb.buttons[0].disabled && !mb.buttons[3].disabled && mb.note === "");
mb = C.chargerModeButtons(live, { mode: "fast", sentAt: NOW - 3000 }, NOW);
check("while sending, the asked-for button is busy", mb.waiting && mb.buttons[0].busy && /Asking the charger for Fast/.test(mb.note));
check("while sending, nothing else can be pressed", mb.buttons.every((b) => b.disabled));
check("the old mode stays marked until the charger says otherwise", mb.buttons[2].current && !mb.buttons[0].current);
let done1 = C.chargerModeButtons(C.chargerView(zappi({ mode: "fast" }), NOW), { mode: "fast", sentAt: NOW - 8000 }, NOW);
check("confirmed by the device: no note, Fast is current", !done1.waiting && done1.note === "" && done1.buttons[0].current);
mb = C.chargerModeButtons(live, { mode: "fast", sentAt: NOW - C.CHARGER_CONFIRM_MS - 1 }, NOW);
check("not confirmed in time: says so and allows another try", !mb.waiting && /not confirmed Fast/.test(mb.note) && !mb.buttons[0].disabled);
mb = C.chargerModeButtons(C.chargerView(zappi({ online: false }), NOW), null, NOW);
check("readings withheld -> every button off", mb.buttons.every((b) => b.disabled));
check("the page sends chargerMode through DashUI.message", /DashUI\.message\('chargerMode', \{ deviceId: id, mode \}\)/.test(html));
check("the page looks again after the plugin's check", /setTimeout\(refreshDevices, 7000\)/.test(html));

// ── boost (v3.58.0) ──
let bv = C.chargerBoostView(C.chargerView(zappi({ boostActive: false, boostKwh: 0 }), NOW), null, NOW);
check("boost: three amounts in Eco+", bv.chips.map((c) => c.kwh).join() === "5,10,20" && bv.chips.every((c) => !c.disabled));
check("boost: no stop button when none is set", !bv.stop.show && bv.note === "");
bv = C.chargerBoostView(C.chargerView(zappi({ mode: "fast", boostActive: false }), NOW), null, NOW);
check("boost: off in Fast, and says why", bv.chips.every((c) => c.disabled) && bv.note === "A boost works in Eco or Eco+.");
let set = C.chargerView(zappi({ boostActive: true, boostKwh: 10, chargeState: "boosting" }), NOW);
bv = C.chargerBoostView(set, null, NOW);
check("boost set: stop shown, amounts off", bv.stop.show && !bv.stop.disabled && bv.chips.every((c) => c.disabled));
check("boost set: a Boost tile on the card", set.tiles.some((x) => x.lab === "Boost" && x.val === "10 kWh"));
// Measured: a boost with no car reads Boosting. That is not charging.
let noCar = C.chargerView(zappi({ plugState: "unplugged", chargeState: "boosting", boostActive: true, boostKwh: 1 }), NOW);
check("boost with no car: not shown as charging", noCar.tone === "" && tile(noCar, "Car").cls === "" && tile(noCar, "Into the car").val === "Not charging");
check("boost with no car: says so", C.chargerBoostView(noCar, null, NOW).note === "A 1 kWh boost is set. No car is plugged in.");
let withCar = C.chargerView(zappi({ plugState: "charging", chargeState: "boosting", chargePowerW: 7200, boostActive: true, boostKwh: 10 }), NOW);
check("boost with a car: charging and boosting", withCar.tone === "good" && /Boosting 10 kWh at full power/.test(C.chargerBoostView(withCar, null, NOW).note));
bv = C.chargerBoostView(C.chargerView(zappi({ boostActive: false }), NOW), { action: "start", kwh: 10, sentAt: NOW - 3000 }, NOW);
check("boost sending: the chip is busy", bv.waiting && bv.chips[1].busy && /10 kWh boost/.test(bv.note));
bv = C.chargerBoostView(set, { action: "start", kwh: 10, sentAt: NOW - 8000 }, NOW);
check("boost confirmed by boostActive + boostKwh", !bv.waiting && bv.active && /10 kWh boost is set/.test(bv.note));
bv = C.chargerBoostView(C.chargerView(zappi({ boostActive: true, boostKwh: 5 }), NOW), { action: "start", kwh: 10, sentAt: NOW - 8000 }, NOW);
check("a different amount is not the one asked for", bv.waiting);
bv = C.chargerBoostView(set, { action: "stop", sentAt: NOW - 2000 }, NOW);
check("stopping: the stop button is busy", bv.waiting && bv.stop.busy && bv.stop.show);
bv = C.chargerBoostView(C.chargerView(zappi({ boostActive: false }), NOW), { action: "stop", sentAt: NOW - 8000 }, NOW);
check("stop confirmed when the boost clears", !bv.waiting && !bv.stop.show && bv.note === "");
bv = C.chargerBoostView(C.chargerView(zappi({ boostActive: false }), NOW), { action: "start", kwh: 5, sentAt: NOW - C.CHARGER_CONFIRM_MS - 1 }, NOW);
check("boost not confirmed in time says so", !bv.waiting && /not confirmed the boost/.test(bv.note));
bv = C.chargerBoostView(C.chargerView(zappi(), NOW), { action: "start", kwh: 5, sentAt: NOW - 2000 }, NOW);
check("old Zappi plugin: shown as sent, never as confirmed", !bv.waiting && /cannot report a boost/.test(bv.note));
bv = C.chargerBoostView(C.chargerView(zappi({ online: false, boostActive: true }), NOW), null, NOW);
check("boost buttons off while the readings are held back", bv.chips.every((c) => c.disabled) && bv.stop.disabled);
check("the page sends chargerBoost", /DashUI\.message\('chargerBoost'/.test(html));

// ── the hub strip (v3.56.0), run from index.html itself ──
const hub = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");
function extractFn(src, name) {
    const i = src.indexOf("function " + name + "(");
    if (i < 0) throw new Error("not found in index.html: " + name);
    let d = 0, j = src.indexOf("{", i);
    do { if (src[j] === "{") d++; else if (src[j] === "}") d--; j++; } while (d > 0);
    return src.slice(i, j);
}
const els = {};
const el = (id) => (els[id] = els[id] || { id, style: {}, innerHTML: "" });
// The hub reads Date.now(); pin it to the fixture's clock, or the test's
// report times age with the wall clock and go stale after ten minutes.
class FixedDate extends Date { static now() { return NOW; } }
const hubCtx = { window: ctx.window, DashCalc: C, Date: FixedDate,
                 document: { getElementById: (id) => (["charger-row", "charger-card"].includes(id) ? el(id) : null) } };
vm.createContext(hubCtx);
vm.runInContext(extractFn(hub, "escapeAttr") + "\n" + extractFn(hub, "renderChargerCard")
                + "\nthis.renderChargerCard = renderChargerCard;", hubCtx);

hubCtx.renderChargerCard([other]);
check("hub: no Zappi -> strip hidden", els["charger-row"].style.display === "none");
hubCtx.renderChargerCard([other, zappi({ lastReport: stamp(5000) })]);
const card = els["charger-card"].innerHTML;
check("hub: strip shown with a Zappi", els["charger-row"].style.display === "");
check("hub: headline is the plugin's status", card.includes("Unplugged, Eco+"));
check("hub: car and mode are not repeated as rows", !card.includes('class="key">Car<') && !card.includes('class="key">Mode<'));
check("hub: guard row keeps its explanation", card.includes("Battery exporting · nothing to pause"));
check("hub: other rows carry no tile caption", card.includes(">Not charging<") && !card.includes("charging power"));
hubCtx.renderChargerCard([zappi({ online: false })]);
check("hub: offline shows the reason and no rows",
      els["charger-card"].innerHTML.includes("Not reachable through myenergi") && !els["charger-card"].innerHTML.includes('class="row"'));
hubCtx.renderChargerCard([zappi({ status: "<b>x</b>" })]);
check("hub: the status text is escaped", els["charger-card"].innerHTML.includes("&lt;b&gt;x&lt;/b&gt;"));
check("hub: drawn on the device poll", /renderChargerCard\(devices\)/.test(hub));
check("hub: links to the Energy page's card", /id="charger-card" class="dash-card" href="energy\.html#ev-card"/.test(hub));
check("energy: scrolls to the card when linked to it", /location\.hash === '#ev-card'/.test(html));

done();
