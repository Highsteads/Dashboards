// Filename:    test_flow_popups.mjs
// Description: Node contract test for FlowPopups (flow-popups.js), the Flow
//              page's SigenStor and GRID pop-ups (3.67.0). The status fixture
//              is shaped as SigenEnergyManager's /api/status returned it on
//              29-10-2026. Every sentence is checked against the estate's
//              plain-English rules: full stops, no "key: value" pipes or
//              equals signs, times as a person says them.
// Author:      CliveS & Claude Opus 5.5
// Date:        29-10-2026
// Version:     1.0
//
// Run: node tests/test_flow_popups.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkOk as check, checkEq as eqLabelFirst, done } from "./lib/check.mjs";

const checkEq = (got, want, label) => eqLabelFirst(label, got, want);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const ctx = { window: {}, console, Date, Math, JSON };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "flow-popups.js"), "utf8"), ctx);
const P = ctx.window.FlowPopups;
const T = P._t;

const NOW = new Date(2026, 9, 29, 9, 30).getTime();
const tier = (label, p, wins) => ({ label, p, current: wins.some(w => w.current), windows: wins });
const STATUS = {
    battery: { soc_pct: 61, power_w: 1600, capacity_kwh: 35.04, soh_pct: 100, temp_min_c: 14.3, temp_max_c: 18.9,
               pack_count: 4, pack_balance: { verdict: "even" } },
    decision: { action: "self_consumption", dawn_viable: true, soc_at_dawn_kwh: 15.9 },
    home: { load_w: 763 },
    grid: { power_w: 4 },
    today_summary: { battery_charge_kwh: 16.02, battery_discharge_kwh: 4.4, import_kwh: 16.91, export_kwh: 0.01 },
    economics: { today: { import_cost_gbp: 2.64, export_revenue_gbp: 0 } },
    grid_quality: { voltage_v: 250.73, frequency_hz: 50.12, statutory_min_v: 216.2, statutory_max_v: 253 },
    tariff: { name: "Octopus Flux",
        import_side: { tiers: [tier("Off-peak", 15.473, [{ start: "02:00", end: "05:00" }]),
                               tier("Day", 25.6271, [{ start: "05:00", end: "16:00", current: true }, { start: "19:00", end: "02:00" }]),
                               tier("Peak", 35.7813, [{ start: "16:00", end: "19:00" }])] },
        export_side: { tiers: [tier("Off-peak", 4.5162, [{ start: "02:00", end: "05:00" }]),
                               tier("Day", 10.6377, [{ start: "05:00", end: "16:00", current: true }]),
                               tier("Peak", 29.0119, [{ start: "16:00", end: "19:00" }])] } },
    power_cut: { ongoing: false, lockout_active: false, lockout_soc_floor: 85,
                 events: ["2026-10-25 12:53 UTC — grid LOST (Off-grid (auto))",
                          "2026-10-25 12:55 UTC — grid RESTORED (duration 80s)",
                          "2026-10-25 18:58 UTC — grid LOST (Off-grid (auto))",
                          "2026-10-25 21:13 UTC — grid RESTORED (duration 2.3 h)"] },
    vpp: { active: false }, storm: { level: "none" },
    octopus_sessions: { upcoming: [] },
};
const text = v => v.lines.map(l => l.text);

function prose(v, label) {
    for (const t of text(v)) {
        check(/[.]$/.test(t), `${label}: ends with a full stop: ${t}`);
        check(!/[|=]/.test(t), `${label}: no pipes or equals: ${t}`);
        check(!/\b\d{2}:\d{2}\b/.test(t), `${label}: no 24-hour clock: ${t}`);
        check(!/\b[A-Z]{4,}\b/.test(t.replace(/\b(VPP|UTC)\b/g, "")), `${label}: no shouting: ${t}`);
        check(!/undefined|NaN|null/.test(t), `${label}: no missing values: ${t}`);
    }
}

// ── helpers ──────────────────────────────────────────────────────────────
checkEq(T.clock(16 * 60), "4pm", "4pm");
checkEq(T.clock(18 * 60 + 58), "6:58pm", "6:58pm");
checkEq(T.clock(2 * 60), "2am", "2am");
checkEq(T.clock(0), "midnight", "midnight");
checkEq(T.clock(12 * 60), "noon", "noon");
checkEq(T.clock(12 * 60 + 30), "12:30pm", "half past noon");
checkEq(T.power(763), "763 W", "watts");
checkEq(T.power(1600), "1.6 kW", "kilowatts");
checkEq(T.kwh(16.02), "16 kWh", "whole kWh above ten");
checkEq(T.kwh(4.4), "4.4 kWh", "one place below ten");
checkEq(T.kwh(6), "6 kWh", "no .0");
checkEq(T.durationWords("80s"), "about a minute", "80 seconds");
checkEq(T.durationWords("2.3 h"), "about 2.3 hours", "hours");
checkEq(T.durationWords("12m"), "about 12 minutes", "minutes");
checkEq(T.hoursWords(26.4), "about 26 hours", "hours of backup");
checkEq(T.hoursWords(60), "about 3 days", "days of backup");
checkEq(T.hoursWords(0.3), "about 20 minutes", "minutes of backup");

// ── SigenStor ────────────────────────────────────────────────────────────
{
    const v = P.batteryView(STATUS, NOW);
    prose(v, "battery");
    checkEq(v.title, "Battery 61%", "battery title");
    checkEq(v.sub, "21 of 35 kWh stored", "stored energy");
    checkEq(text(v)[0], "Running the house on its own, and the solar is charging it at 1.6 kW.", "what it is doing");
    check(text(v).includes("It should last until the sun comes up, with about 16 kWh (45%) left at dawn."), "dawn");
    check(text(v).some(t => /^In a power cut it would run the house for about 26 hours at the 763 W it is using now\.$/.test(t)), "backup time");
    check(text(v).includes("Health 100%, as good as new; cells between 14 and 19 degrees, all four packs evenly matched."), "health");
    check(text(v).includes("Today it has taken in 16 kWh and given out 4.4 kWh."), "today");
    check(!text(v).some(t => /power cut:|VPP|Storm/.test(t)), "nothing unusual: no alert lines");

    const short = P.batteryView({ ...STATUS, decision: { action: "start_import", dawn_viable: false, soc_at_dawn_kwh: 2 },
                                  battery: { ...STATUS.battery, soc_pct: 8, power_w: -900, pack_balance: { verdict: "uneven" } },
                                  home: { load_w: 2000 } }, NOW);
    prose(short, "battery short");
    check(text(short)[0] === "Charging from the grid, supplying 900 W.", "another mode, discharging");
    checkEq(short.lines.find(l => l.key === "dawn").tone, "warn", "running low before dawn is a warning");
    checkEq(short.lines.find(l => l.key === "backup").tone, "warn", "under two hours of backup is a warning");
    check(text(short).some(t => /packs "uneven"/.test(t)), "an unknown pack verdict is quoted, not dropped");

    const odd = P.batteryView({ ...STATUS, decision: { action: "brand_new_mode" } }, NOW);
    check(text(odd)[0].startsWith('The manager says "brand_new_mode"'), "an unknown mode is shown in quotes");

    const alerts = P.batteryView({ ...STATUS, power_cut: { ...STATUS.power_cut, lockout_active: true },
                                   vpp: { active: true, event_str: "until 7pm" },
                                   storm: { level: "amber", export_suppressed: true, export_release_pct: 85 } }, NOW);
    prose(alerts, "battery alerts");
    check(text(alerts).some(t => /export is held off for a while as a precaution, until the battery reaches 85% or the day's solar can refill it/.test(t)), "lockout names both release rules");
    check(text(alerts).includes("Exporting for the VPP: until 7pm."), "VPP");
    check(text(alerts).some(t => /^Storm warning \("amber"\).*no export below 85%\.$/.test(t)), "storm");
    const cut = P.batteryView({ ...STATUS, power_cut: { ongoing: true } }, NOW);
    checkEq(cut.lines.find(l => l.key === "cut").tone, "bad", "a power cut now is bad news");

    const empty = P.batteryView({}, NOW);
    prose(empty, "battery empty");
    checkEq(empty.title, "Battery", "no readings: plain title");
}

// ── GRID ─────────────────────────────────────────────────────────────────
{
    const v = P.gridView(STATUS, NOW);
    prose(v, "grid");
    checkEq(v.title, "Barely using the grid", "a few watts reads as barely");
    checkEq(text(v)[0], "Day rate now: 25.6p a unit to buy and 10.6p to sell, until 4pm.", "price now and when it ends");
    checkEq(text(v)[1], "Then peak: 35.8p to buy and 29p to sell.", "the next band");
    check(text(v).includes("Today the house has bought 17 kWh for £2.64 and sold nothing."), "today, money and energy");
    check(text(v).includes("The supply is at 251 volts, inside the legal 216 to 253, at 50.12 hertz."), "supply");
    check(text(v).some(t => /^The last power cut was 25 October at (6:58pm|7:58pm|6:58am|.*) and lasted about 2\.3 hours\.$/.test(t)), "last cut, the later of two");
    checkEq(v.lines.find(l => l.key === "price").tone, "", "day rate is not a warning");

    const peak = P.gridView({ ...STATUS, grid: { power_w: 2500 },
        tariff: { ...STATUS.tariff, import_side: { tiers: [tier("Peak", 35.78, [{ start: "16:00", end: "19:00", current: true }]),
                                                           tier("Day", 25.6, [{ start: "19:00", end: "02:00" }])] } },
        grid_quality: { voltage_v: 258, frequency_hz: 49.2, statutory_min_v: 216.2, statutory_max_v: 253 } }, NOW);
    prose(peak, "grid peak");
    checkEq(peak.title, "Buying 2.5 kW", "importing title");
    checkEq(peak.lines.find(l => l.key === "price").tone, "warn", "peak rate is a warning");
    check(text(peak)[0].endsWith("until 7pm."), "peak ends at 7pm");
    checkEq(peak.lines.find(l => l.key === "supply").tone, "bad", "voltage over the limit is bad");
    check(/outside the legal 216 to 253/.test(text(peak).join(" ")), "says the voltage is outside the limit");
    check(/outside the normal 49\.5 to 50\.5/.test(text(peak).join(" ")), "says the frequency is outside normal");

    const sell = P.gridView({ ...STATUS, grid: { power_w: -3200 }, today_summary: { ...STATUS.today_summary, export_kwh: 6 },
                              economics: { today: { import_cost_gbp: 1, export_revenue_gbp: 1.74 } } }, NOW);
    checkEq(sell.title, "Selling 3.2 kW", "exporting title");
    check(text(sell).some(t => /and sold 6 kWh for £1\.74\./.test(t)), "export money");

    const tomorrow = new Date(2026, 9, 30, 18, 0).toISOString(), end = new Date(2026, 9, 30, 19, 0).toISOString();
    const sess = P.gridView({ ...STATUS, octopus_sessions: { upcoming: [{ start: tomorrow, end, direction: "TURN_DOWN" }] } }, NOW);
    prose(sess, "grid session");
    check(text(sess).includes("Saving Session (use less) booked tomorrow, 6pm to 7pm."), "booked session");

    const down = P.gridView({ ...STATUS, power_cut: { ongoing: true } }, NOW);
    checkEq(down.title, "Power cut", "power cut title");
    check(!text(down).some(t => /last power cut/.test(t)), "no 'last cut' line during one");

    const empty = P.gridView({}, NOW);
    prose(empty, "grid empty");
    checkEq(empty.lines.length, 0, "no data: no lines, nothing made up");
}

// ── the page wires them up ─────────────────────────────────────────────
{
    const page = fs.readFileSync(path.join(PAGES, "flow.html"), "utf8");
    check(page.includes('<script src="flow-popups.js"></script>'), "the page loads flow-popups.js");
    check(/FlowPopups\.batteryView/.test(page) && /FlowPopups\.gridView/.test(page), "the page uses both views");
    check(/socButton/.test(page), "a tap on the battery % is left to his own history window");
    const card = fs.readFileSync(path.join(PAGES, "sigenergy-flow-card.js"), "utf8");
    check(card.includes('<strong id="battery">') && card.includes('<strong id="grid">'), "his card still names the readings battery and grid");
}

done();
