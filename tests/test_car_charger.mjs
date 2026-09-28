// Filename:    test_car_charger.mjs
// Description: Node contract test for DashCalc.chargerDevices / chargerView,
//              the Energy page's car charger card (v3.55.0). The fixture is
//              the Zappi device exactly as /v2/api/indigo.devices returned it
//              on 28-09-2026 (states only, address left out), so it tests
//              what the Zappi plugin really writes.
// Author:      CliveS & Claude Opus 5.5
// Date:        28-09-2026
// Version:     1.0
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

done();
