// Filename:    test_sigen_flow_bridge.mjs
// Description: Node contract test for SigenFlowBridge (sigen-flow-bridge.js),
//              the stand-in `hass` that runs the vendored Sigenergy Flow Card
//              on the Flow page (3.66.0). The status fixture is shaped as
//              SigenEnergyManager's /api/status returns it (measured
//              29-10-2026); slots as /api/history; daily as /api/daily.
// Author:      CliveS & Claude Opus 5.5
// Date:        29-10-2026
// Version:     1.0
//
// Run: node tests/test_sigen_flow_bridge.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkOk as check, checkEq as eqLabelFirst, done } from "./lib/check.mjs";

const checkEq = (got, want, label) => eqLabelFirst(label, got, want);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const ctx = { window: {}, console, Intl, Date, Math, JSON };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "sigen-flow-bridge.js"), "utf8"), ctx);
const B = ctx.window.SigenFlowBridge;
const T = B._t;
const E = B.E;
const CARD = fs.readFileSync(path.join(PAGES, "sigenergy-flow-card.js"), "utf8");

const STATUS = {
    battery: { soc_pct: 57.2, power_w: -388, capacity_kwh: 35.04 },
    solar: { power_w: 388, lifetime_kwh: 8847.36, strings: [
        { n: 1, label: "West", v: 194.5, a: 0.46, w: 89 },
        { n: 2, label: "East", v: 265.8, a: 1.03, w: 274 },
    ] },
    grid: { power_w: 4 },
    home: { load_w: 780 },
    today_summary: { pv_kwh: 0.29, import_kwh: 16.91, export_kwh: 0.01,
                     battery_charge_kwh: 14.22, battery_discharge_kwh: 4.32 },
    hourly_forecast: { "08:00": 0.5, "09:00": 2.11, "23:00": 0.0 },
};
const NOW = new Date(2026, 9, 29, 9, 0, 0).getTime();
const stamp = (h, m) => `2026-10-29T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:12`;

// ── every entity the bridge writes is one his card actually reads ─────────
for (const [key, id] of Object.entries(E)) {
    if (key === "sun") continue;
    check(CARD.includes(`'${id}'`), `card reads ${id} (${key})`);
}
check(CARD.includes("sensor.sigen_inverter_pv${n}_${key}"), "card's PV string pattern is still sensor.sigen_inverter_pv<n>_<key>");

// ── states ────────────────────────────────────────────────────────────────
{
    const s = T.buildStates({ status: STATUS, nowMs: NOW });
    checkEq(s[E.pv].state, "388", "solar watts");
    checkEq(s[E.battery].state, "-388", "battery negative while discharging, as the card wants");
    checkEq(s[E.gridImport].state, "4", "grid import from a positive grid reading");
    checkEq(s[E.gridExport].state, "0", "no export while importing");
    checkEq(s[E.home].state, "780", "house load");
    checkEq(s[E.capacity].state, "35.04", "battery capacity in kWh");
    checkEq(s[E.dayCharge].state, "14.22", "today's battery charge");
    checkEq(s["sensor.sigen_inverter_pv2_power"].state, "274", "second string power");
    checkEq(s["sensor.sigen_inverter_pv1_daily_energy"].state, "unavailable", "no string energy given: unavailable, never 0");
    check(!s[E.acPower], "no Zappi: no AC charger on the picture");
    check(!s[E.weather], "no weather.json: no weather");
    const exp = T.buildStates({ status: { ...STATUS, grid: { power_w: -2500 } }, nowMs: NOW });
    checkEq(exp[E.gridExport].state, "2500", "export from a negative grid reading");
    checkEq(exp[E.gridImport].state, "0", "no import while exporting");
    const blank = T.buildStates({ status: {}, nowMs: NOW });
    checkEq(blank[E.pv].state, "unavailable", "a missing reading is unavailable, never 0");
}

// ── the Zappi ───────────────────────────────────────────────────────────
{
    const zappi = (states, top = {}) => [Object.assign({ id: 9, name: "Zappi", enabled: true, errorState: "",
        pluginId: "com.clives.indigoplugin.zappi", deviceTypeId: "zappi",
        states: Object.assign({ online: "True", lastReport: "2026-10-29 08:59:00", plugState: "unplugged",
                                chargeState: "paused", chargePowerW: 0 }, states) }, top)];
    checkEq(T.chargerReading(zappi({}), NOW).words, "No car", "unplugged reads No car");
    const ch = T.chargerReading(zappi({ plugState: "connected", chargeState: "charging", chargePowerW: 7000 }), NOW);
    checkEq(ch.watts, 7000, "charging power");
    checkEq(ch.words, "Charging", "charging words");
    check(!/-/.test(ch.words), "no hyphen: the card shows only the part before one");
    checkEq(T.chargerReading(zappi({ online: "False" }), NOW).watts, null, "string False is offline, not truthy");
    checkEq(T.chargerReading(zappi({ lastReport: "2026-10-29 08:40:00" }), NOW).words, "Not reachable", "a report 20 minutes old is held back");
    const s = T.buildStates({ status: STATUS, charger: ch, nowMs: NOW });
    checkEq(s[E.home].state, "0", "the car's draw comes off the house load (clamped at 0)");
    checkEq(s[E.acPower].state, "7000", "charger power on the picture");
    checkEq(T.chargerReading([], NOW), null, "no Zappi device: null");
}

// ── HOME breakdown ─────────────────────────────────────────────────────
{
    const loads = T.homeLoads([
        { id: 1, name: "Kettle Plug", states: { powerWatts: "1800" } },
        { id: 2, name: "Garage Mains Meter", states: { powerWatts: "300" } },
        { id: 3, name: "Sigen Inverter", pluginId: "com.clives.indigoplugin.sigenergy-energy-manager", states: { power: 5 } },
        { id: 4, name: "Lamp", states: { onOffState: true } },
        { id: 5, name: "Fridge", enabled: false, states: { powerWatts: 90 } },
        { id: 6, name: "Freezer", states: { curEnergyLevel: -0.5 } },
    ]);
    checkEq(loads.map(l => l.name).join(","), "Freezer,Kettle Plug", "metered loads only; mains, Sigen, unmetered and disabled left out");
    checkEq(loads[0].watts, 0, "a negative reading is clamped to 0");
    const s = T.buildStates({ status: STATUS, loads, nowMs: NOW });
    checkEq(s["sensor.indigo_1_power"].state, "1800", "a load becomes an entity the card can list");
}

// ── weather ────────────────────────────────────────────────────────────
{
    checkEq(T.condition("01d"), "sunny", "clear day");
    checkEq(T.condition("01n"), "clear-night", "clear night");
    checkEq(T.condition("10n"), "rainy", "rain");
    checkEq(T.condition("50d"), "fog", "mist");
    checkEq(T.condition("zz"), null, "unknown icon: null");
    const rise = new Date(2026, 9, 29, 7, 6).getTime() / 1000, set = new Date(2026, 9, 29, 16, 37).getTime() / 1000;
    const s = T.buildStates({ status: STATUS, weather: { now_icon: "03d", sunrise: String(rise), sunset: String(set) },
                              outdoorC: 8.53, nowMs: NOW });
    checkEq(s[E.weather].state, "cloudy", "weather condition");
    checkEq(s[E.weather].attributes.temperature, 8.5, "temperature to one place");
    checkEq(s[E.sun].state, "above_horizon", "between sunrise and sunset");
    const night = T.buildStates({ status: STATUS, weather: { now_icon: "03n", sunrise: String(rise), sunset: String(set) }, nowMs: NOW + 9 * 3600e3 });
    checkEq(night[E.sun].state, "below_horizon", "after sunset");
    const f = T.outdoorC([{ name: "Indoor", states: { temperature: 70, humidity: 40, dewPoint: 50, temperatureUnit: "F" } },
                          { name: "Outdoor", states: { temperature: 50, humidity: 80, dewPoint: 45, temperatureUnit: "F" } }],
                         { tempC: (v, st) => /f/i.test(st.temperatureUnit) ? (v - 32) / 1.8 : v });
    checkEq(Math.round(f), 10, "the outdoor sensor, converted from F");
}

// ── location from sun times reproduces those times ───────────────────────
{
    const rise = Date.UTC(2026, 9, 29, 7, 3, 58), set = Date.UTC(2026, 9, 29, 16, 37, 50);
    const loc = T.locate(rise, set);
    check(loc && loc.latitude > 50 && loc.latitude < 60, "latitude in the north of England");
    check(loc && Math.abs(loc.longitude + 1.8) < 0.3, "longitude near 1.8 W");
    const s = T.solarDay((rise + set) / 2);
    const half = T.halfDayDeg(loc.latitude, s.dec) * 8;   // minutes of daylight
    check(Math.abs(half - (set - rise) / 60000) < 2, "the found latitude gives the same day length");
    checkEq(T.locate(0, 0), null, "no times: no location");
    const south = T.locate(Date.UTC(2026, 9, 29, 19, 0), Date.UTC(2026, 9, 30, 8, 30));
    check(south && south.latitude < 0, "a long day in October is the southern hemisphere");
}

// ── history and statistics ───────────────────────────────────────────────
const SLOTS = [
    { t: stamp(0, 33), soc_end: 50, pv_kwh: 0, import_kwh: 3.0, export_kwh: 0, home_kwh: 0.5 },
    { t: stamp(1, 3), soc_end: 55, pv_kwh: 0, import_kwh: 0.2, export_kwh: 0, home_kwh: 0.4 },
    { t: "nonsense" },
];
{
    const figs = T.slotFigures(SLOTS);
    checkEq(figs.length, 2, "an unreadable slot is dropped");
    checkEq(figs[0].charge, 2.5, "battery charge is the balance");
    checkEq(figs[1].discharge, 0.2, "battery discharge is the balance");
    checkEq(figs[0].end - figs[0].start, 1800000, "slot t is its end, half an hour after its start");

    const from = new Date(2026, 9, 29).toISOString();
    const q = `history/period/${encodeURIComponent(from)}?filter_entity_id=${encodeURIComponent([E.pv, E.battery, E.soc, "sensor.unknown"].join(","))}&minimal_response&no_attributes`;
    const h = T.historyPeriod(q, figs, null, null);
    checkEq(h.length, 3, "one list per known entity, unknown ones left out");
    checkEq(h[1][0].state, "5000", "2.5 kWh in half an hour is 5 kW of charging");
    checkEq(h[1][0].entity_id, E.battery, "each row names its entity");
    checkEq(h[2][1].state, "55", "SOC at the slot end");

    const hours = Array(24).fill(null); hours[9] = [0.1, 0.2, 0.3, 0.4];
    const hp = T.historyPeriod(`history/period/${encodeURIComponent(from)}?filter_entity_id=${encodeURIComponent("sensor.sigen_inverter_pv3_power")}`, figs, { hours }, null);
    checkEq(hp[0].length, 1, "string power only for hours that have it");
    checkEq(hp[0][0].state, "300", "0.3 kWh in an hour is 300 W");

    const day = new Date(2026, 9, 29);
    const st = T.statistics({ start_time: day.toISOString(), end_time: new Date(day.getTime() + 86400e3).toISOString(),
                              statistic_ids: [E.statImport, E.statCharge, "sensor.x"], period: "5minute", types: ["change"] }, figs, null);
    checkEq(st[E.statImport].map(r => r.change).join(","), "3,0.2", "a day's import per slot");
    checkEq(st[E.statCharge][0].change, 2.5, "a day's charge per slot");
    check(!st["sensor.x"], "an unknown statistic is left out");

    const DAILY = [{ date: "2026-10-27", pv_kwh: 5, grid_import_kwh: 10 }, { date: "2026-10-28", pv_kwh: 6, grid_import_kwh: 11 },
                   { date: "2026-09-01", pv_kwh: 40 }];
    const wk = T.statistics({ start_time: new Date(2026, 9, 26).toISOString(), end_time: new Date(2026, 10, 2).toISOString(),
                              statistic_ids: [E.statPv], period: "hour", types: ["change"] }, [], DAILY);
    checkEq(wk[E.statPv].map(r => r.change).join(","), "5,6", "a week from the daily records, outside days left out");

    checkEq(Object.keys(T.statistics({ start_time: day.toISOString(), end_time: new Date(day.getTime() + 86400e3).toISOString(),
                                      statistic_ids: [E.pv], period: "5minute", types: ["mean"] }, figs, null)).length,
            0, "5-minute means refused, so the card asks by the hour");
    const mean = T.statistics({ start_time: day.toISOString(), end_time: new Date(day.getTime() + 86400e3).toISOString(),
                                statistic_ids: [E.home], period: "hour", types: ["mean"] }, figs, null);
    checkEq(mean[E.home].length, 1, "hourly means: both slots start in the midnight hour");
    checkEq(mean[E.home][0].mean, 900, "the hour's mean of 1 kW and 0.8 kW");
}

// ── solar forecast ───────────────────────────────────────────────────────
{
    const f = T.solarForecast(STATUS.hourly_forecast, NOW).sigenergy_manager.wh_hours;
    checkEq(f[new Date(2026, 9, 29, 9).toISOString()], 2110, "kWh per hour -> Wh at that hour");
    checkEq(Object.keys(T.solarForecast({}, NOW)).length, 0, "no forecast: none offered");
}

// ── the page carries the licence and the credit ──────────────────────────
{
    const page = fs.readFileSync(path.join(PAGES, "flow.html"), "utf8");
    check(page.includes("sigenergy-flow-card.LICENSE.txt"), "page links the Apache licence");
    check(/Jean-Yves Avenard/.test(page), "page credits the author");
    const lic = fs.readFileSync(path.join(PAGES, "sigenergy-flow-card.LICENSE.txt"), "utf8");
    check(/Apache License\s+Version 2\.0/.test(lic), "licence file is the Apache 2.0 text");
    check(/Copyright 2025-2026 Jean-Yves Avenard/.test(CARD), "vendored card keeps its copyright header");
    // 3.66.1: a tap on the AC charger opens the Zappi card on the Energy page.
    check(CARD.includes('id="acNode"'), "the card still names its charger reading acNode");
    check(/const CHARGER_TARGETS = \["acNode"\]/.test(page), "the page catches taps on acNode");
    check(page.includes('location.href = "energy.html#ev-card"'), "a charger tap opens the Zappi card");
    check(/function configure\(\)[\s\S]*markCharger\(\);[\s\S]*return true;/.test(page), "the charger is marked tappable after every setConfig");
    const energy = fs.readFileSync(path.join(PAGES, "energy.html"), "utf8");
    check(energy.includes('id="ev-card"') && /#ev-card\{scroll-margin-top:\d+px\}/.test(energy), "the Zappi card exists and clears the top bar");
}

done();
