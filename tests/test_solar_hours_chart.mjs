// Filename:    test_solar_hours_chart.mjs
// Description: Contract test for DashUI.solarHoursChart — the stacked hourly
//              solar chart shared by the Energy card and the hub's Solar ·
//              today block (v2.80.0).
//
//              WHY THIS EXISTS
//              The renderer moved into dashboards-ui.js precisely so the two
//              pages cannot drift apart, which is the fault forecastBars had
//              until v2.50.0 — a duplicate copy kept its light-mode hex
//              colours in dark mode for months. A shared renderer with no
//              tests just moves the risk, so this drives the SHIPPED module
//              with a fake element at BOTH sizes and asserts the things that
//              carry meaning: every string gets its own colour, an elapsed
//              hour carries its forecast tick, a future hour does not, and a
//              gap hour draws nothing at all.
// Author:      CliveS & Claude Opus 5
// Date:        13-08-2026
// Version:     1.0
//
// Run: node tests/test_solar_hours_chart.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages");

/* A document just real enough for the two modules to load. Neither the calc
   nor the chart touches the DOM beyond the element handed in. */
const doc = {
    documentElement: {},
    getElementById: () => null,
    createElement: () => ({ style: {}, setAttribute() {}, appendChild() {} }),
    head: { appendChild() {} },
};
const ctx = {
    console, document: doc,
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    navigator: { userAgent: "" }, location: { hostname: "x" },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "energy-calc.js"), "utf8"), ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8"), ctx);
const UI = ctx.DashUI, C = ctx.DashCalc;
assert.ok(UI && UI.solarHoursChart, "dashboards-ui.js must publish solarHoursChart");

let passed = 0, failed = 0;
function test(name, fn) {
    try { fn(); passed++; }
    catch (e) { failed++; console.error(`  FAIL  ${name}\n        ${e.message}`); }
}
const el = (viewBox) => ({
    innerHTML: "",
    getAttribute: (k) => (k === "viewBox" ? viewBox : null),
});
const count = (h, re) => (h.match(re) || []).length;

/* A day shaped like a real one: two stacked hours, one whole-system hour
   with no per-string history, one gap, and the rest still to come. */
const TODAY = "2026-08-13";
const strings = new Array(24).fill(null);
strings[13] = [0.70, 0.89, 1.05, 0.58];
strings[14] = [0.80, 0.70, 1.20, 0.60];
const site = new Array(24).fill(null);
site[9] = 4.85; site[13] = 3.22; site[14] = 3.30;
const hourly = { "09:00": 4.14, "10:00": 5.17, "13:00": 6.47, "14:00": 5.16, "17:00": 3.43 };
const model = C.buildSolarHours(strings, site, null, hourly, 15 * 60 + 10, TODAY);

const draw = (viewBox, opts) => {
    const e = el(viewBox);
    UI.solarHoursChart(e, model, Object.assign(
        { stringLabels: ["West", "East", "South", "Garage"] }, opts || {}));
    return e.innerHTML;
};

console.log("\n== the stack carries the strings ==");
test("every string is drawn in its own colour", () => {
    const h = draw("0 0 756 190");
    UI.STRING_COLOURS.forEach(c =>
        assert.ok(h.includes(c), `missing string colour ${c}`));
});

test("a stacked hour draws one rect per string, plus its hover target", () => {
    // hour 13 has four non-zero parts
    const h = draw("0 0 756 190");
    UI.STRING_COLOURS.forEach(c =>
        assert.ok(count(h, new RegExp(c, "g")) >= 2, `colour ${c} used for both stacked hours`));
});

test("the stack order is biggest-first so the shape stays stable", () => {
    // Spread it: the module lives in a vm realm, so its Array is not this
    // realm's Array and deepEqual on the raw value fails on the prototype.
    assert.deepEqual([...UI.STRING_STACK_ORDER], [2, 1, 0, 3]);  // S E W G
});

console.log("\n== beat/miss is geometry, not colour ==");
test("forecast is labelled and drawn as a continuous dashed path", () => {
    const h = draw("0 0 756 190");
    assert.ok(h.includes(">Forecast</text>"));
    assert.match(h, /<path d="M[^"]+" fill="none"[^>]+stroke-dasharray="3 3"/);
});

test("future hours retain forecast context without actual data", () => {
    // hour 17 is the only future hour with a forecast in this fixture.
    const only17 = C.buildSolarHours(null, null, null, { "17:00": 3.43 },
                                     15 * 60 + 10, TODAY);
    const e = el("0 0 756 190");
    UI.solarHoursChart(e, only17, {});
    assert.ok(e.innerHTML.includes("17:00 — forecast"));
    assert.ok(!e.innerHTML.includes("= 3.43 kWh"));
});

test("a gap hour draws no data bar (only future background)", () => {
    const gapOnly = C.buildSolarHours(null, null, null, {}, 15 * 60, TODAY);
    const e = el("0 0 756 190");
    UI.solarHoursChart(e, gapOnly, {});
    assert.equal(count(e.innerHTML, /<rect /g), 1);
    assert.equal(count(e.innerHTML, /<title>/g), 0);
});

console.log("\n== the two sizes differ where they must ==");
/* Hour labels are centred, axis labels are end-anchored — counting them
   SEPARATELY is what makes these assertions bite. Counting all <text> instead
   let a mutant that ignored `compact` survive: full's three axis labels made
   its total larger anyway, so the test passed for the wrong reason. */
const hourLabels = (h) => count(h, /text-anchor="middle"/g);
const axisLabels = (h) => count(h, /text-anchor="end"/g);

test("the full chart labels every second hour and carries a kWh axis", () => {
    const full = draw("0 0 756 190");
    assert.equal(hourLabels(full), 12);
    assert.equal(axisLabels(full), 3);
});

test("compact thins the hour labels while retaining the kWh axis", () => {
    const compact = draw("0 0 380 108", { compact: true });
    assert.equal(hourLabels(compact), 4);     // every 6th hour: 0, 6, 12, 18
    assert.equal(axisLabels(compact), 3);     // no room beside 24 columns
});

test("both sizes retain the same labelled scale", () => {
    // Gridlines are the solid <line>s; the forecast ticks are the dashed ones.
    const solidLines = (h) => (h.match(/<line [^>]+>/g) || []).filter(x => !x.includes("stroke-dasharray")).length;
    assert.equal(solidLines(draw("0 0 756 190")), 3);
    assert.equal(solidLines(draw("0 0 380 108", { compact: true })), 3);
});

test("compact still draws the same stacks and ticks", () => {
    const compact = draw("0 0 380 108", { compact: true });
    UI.STRING_COLOURS.forEach(c => assert.ok(compact.includes(c)));
    assert.ok(count(compact, /stroke-dasharray/g) >= 3);
});

test("hit targets appear only when the caller asks for them", () => {
    assert.equal(count(draw("0 0 756 190", { hitTargets: true }), /data-h=/g), 24);
    assert.equal(count(draw("0 0 380 108", { compact: true }), /data-h=/g), 0);
});

console.log("\n== it never throws on the shapes it will really meet ==");
test("no model, no element, empty rows — all no-ops", () => {
    UI.solarHoursChart(null, model, {});
    UI.solarHoursChart(el("0 0 756 190"), null, {});
    const e = el("0 0 756 190");
    UI.solarHoursChart(e, { rows: [] }, {});
    assert.equal(typeof e.innerHTML, "string");
});

test("a missing viewBox falls back rather than drawing nothing", () => {
    const e = { innerHTML: "", getAttribute: () => null };
    UI.solarHoursChart(e, model, {});
    assert.ok(e.innerHTML.length > 100);
});

test("hover titles name every string, its kWh, and the hour's forecast", () => {
    const h = draw("0 0 756 190");
    // Listed in STACK order (South first), which is the order they are drawn
    // bottom-to-top — the tooltip reads the same way round as the bar.
    assert.ok(h.includes("13:00 — South 1.05 · East 0.89 · West 0.70 · Garage 0.58"),
              "title should name each string's kWh in stack order");
    assert.ok(h.includes("= 3.22 kWh (forecast 6.47)"),
              "title should carry the hour's total and its forecast");
});

const total = passed + failed;
console.log(`\n${passed}/${total} node tests passed`);
if (failed) process.exit(1);
