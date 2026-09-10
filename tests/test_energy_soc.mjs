// Filename:    test_energy_soc.mjs
// Description: Node contract test for energy.html's handling of an UNKNOWN
//              battery SOC. Extracts the real update() out of the shipped
//              page and drives it against a stub DOM, so this locks what
//              ships rather than a copy of it.
//
//              Two things are being pinned, and the second matters as much as
//              the first:
//
//              1. update() must not THROW. `soc.toFixed(1)` on a null ran
//                 before anything below the flow diagram was drawn, so one
//                 null reading froze the whole lower page while the header
//                 kept saying "live".
//
//              2. An unknown SOC must not RENDER AS ZERO. A partial Modbus
//                 read drops the key; painting a red ring and "0.0%" on a
//                 pack that is actually full is the phantom-zero-SOC fault
//                 SigenEnergyManager v5.26.0 had to remove at source, and it
//                 must not reappear in the display layer. tweenNumber()
//                 coerces null to 0, so "did not crash" alone would have let
//                 the lie straight through.
// Author:      CliveS & Claude Opus 5
// Date:        29-07-2026
// Version:     1.0
//
// Run: node tests/test_energy_soc.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "energy.html");
const src  = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in energy.html`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// ── stub DOM ───────────────────────────────────────────────────────────────
// Deliberately permissive: update() touches a great many elements and this
// test is about the SOC path only. Every element records what was written so
// the assertions can read it back.
const els = {};
function el(id) {
    if (!els[id]) {
        els[id] = {
            id, textContent: "", innerHTML: "", className: "",
            style: new Proxy({}, { set(t, k, v) { t[k] = v; return true; } }),
            dataset: {}, classList: { add() {}, remove() {}, toggle() {} },
            appendChild() {}, querySelector: () => null,
            querySelectorAll: () => [], addEventListener() {},
            getAttribute: () => null, setAttribute() {}, remove() {},
        };
    }
    return els[id];
}
globalThis.document = {
    getElementById: (id) => el(id),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => el("_tmp" + Math.random()),
    addEventListener() {},
};
globalThis.window = globalThis;
globalThis.location = { hostname: "192.168.1.10", origin: "http://192.168.1.10" };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#000000" });

// Helpers update() closes over, stubbed to the real contract.
globalThis.setText = (id, v) => { el(id).textContent = v; };
globalThis.cssVar = (name, fallback) => fallback || name;
globalThis.fmtKw = (w) => (Math.abs(w) / 1000).toFixed(2) + " kW";
globalThis.esc = (s) => String(s);
// The real tweenNumber coerces null/NaN to 0 — reproduced exactly, because
// that coercion is precisely what would turn an unknown SOC into "0.0%".
globalThis.tweenNumber = (e, target, opts) => {
    if (!e) return;
    opts = opts || {};
    const to = (target === null || target === undefined || isNaN(target)) ? 0 : Number(target);
    e.textContent = (opts.prefix || "") + to.toFixed(opts.decimals || 0) + (opts.suffix || "");
};
let flowArgs = null;
globalThis.heroFlow = { update: (a) => { flowArgs = a; } };
globalThis.DashCalc = {
    BACKUP_RESERVE_PCT: 5,
    backupRuntime: () => null,
    fmtKw: globalThis.fmtKw,
};
globalThis.DashUI = { tweenNumber: globalThis.tweenNumber };
globalThis.Chart = function () { return { destroy() {}, update() {} }; };
globalThis.Chart.getChart = () => null;
globalThis.BATTERY_KWH = 35.04;
globalThis._lastStatus = null;
// Page-level tables and section renderers update() reaches for. Stubbed, not
// exercised — this test owns the SOC path only, and a renderer that throws on
// its own account would mask the very thing being measured.
globalThis.ACTION_LABELS = {};
globalThis.ACTION_CLASS = {};
globalThis._findInverter = () => null;
globalThis._lastDevices = [];
for (const fn of ["renderWhole", "renderPeriods", "renderMonths",
                  "renderExportSync", "drawSoc", "drawForecast",
                  "renderEconomics", "renderEnvironment", "renderForecast",
                  "renderSankey", "renderSolarCard", "updateAlerts"]) {
    globalThis[fn] = () => {};
}

// update() reaches for a long tail of page-level helpers and lookup tables
// that have nothing to do with SOC. Rather than stub each one — and re-stub
// whenever the page grows another — resolve any identifier this test has not
// deliberately provided to a harmless no-op. The functions that MATTER here
// are all defined above, so a silent no-op can only ever hide unrelated work.
// The function's own parameters still shadow this scope, so `d` is unaffected.
const scope = new Proxy({}, {
    has: () => true,
    get(_t, k) {
        if (k === Symbol.unscopables) return undefined;
        if (k in globalThis) return globalThis[k];
        return () => {};
    },
    set(_t, k, v) { globalThis[k] = v; return true; },
});
const update = new Function("scope",
    `with (scope) { ${grab("update")}; return update; }`)(scope);

// ── payloads ───────────────────────────────────────────────────────────────
const base = {
    timestamp: "12:00:00",
    solar:  { power_w: 2400 },
    grid:   { power_w: -800 },
    home:   { load_w: 900 },
    today_summary: { pv_kwh: 21.4, home_kwh: 9.9 },
};
const known   = { ...base, battery: { soc_pct: 83.5, power_w: -664, capacity_kwh: 35.04 } };
// The real shape of a partial Modbus read: the battery block is present, the
// SOC key is not.
const unknown = { ...base, battery: { power_w: -664, capacity_kwh: 35.04 } };
const nulled  = { ...base, battery: { soc_pct: null, power_w: -664, capacity_kwh: 35.04 } };

let pass = 0, fail = 0;
function ok(name, cond, extra) {
    if (cond) { pass++; console.log(`  ok   ${name}`); }
    else { fail++; console.log(`  FAIL ${name}${extra ? " — " + extra : ""}`); }
}

console.log("\n1. a known SOC still renders normally");
update(known);
ok("hero shows the percentage", el("hs-soc").textContent === "83.5%", el("hs-soc").textContent);
ok("ring figure shows the percentage", el("soc-pct").textContent === "83.5%", el("soc-pct").textContent);
ok("stored kWh computed", el("soc-kwh").textContent === "29.3 kWh", el("soc-kwh").textContent);
ok("flow sub quotes the level", /83\.5% · 29\.3 kWh stored/.test(flowArgs.subs.bat), flowArgs.subs.bat);

for (const [label, payload] of [["missing", unknown], ["explicitly null", nulled]]) {
    console.log(`\n2. SOC ${label} — update() must survive AND not fabricate a zero`);
    let threw = null;
    try { update(payload); } catch (e) { threw = e; }
    ok("update() does not throw", threw === null, threw && threw.message);
    if (threw) continue;
    ok("hero reads as unknown, not 0.0%", el("hs-soc").textContent === "—", el("hs-soc").textContent);
    ok("ring figure reads as unknown", el("soc-pct").textContent === "—", el("soc-pct").textContent);
    ok("stored kWh reads as unknown", el("soc-kwh").textContent === "—", el("soc-kwh").textContent);
    ok("flow sub says level unknown", flowArgs.subs.bat === "level unknown", flowArgs.subs.bat);
    ok("no phantom 0% anywhere in the SOC fields",
       ![el("hs-soc").textContent, el("soc-pct").textContent, el("soc-kwh").textContent]
           .some(t => /^0\.0/.test(t)));
}

console.log("\n3. power readings still drive the diagram when SOC is unknown");
update(unknown);
ok("pv passed through", flowArgs.pv === 2400, String(flowArgs.pv));
ok("home passed through", flowArgs.home === 900, String(flowArgs.home));
ok("battery power passed through", flowArgs.bat === -664, String(flowArgs.bat));

console.log("\n4. a wholly absent battery block is survivable too");
let threw2 = null;
try { update({ ...base }); } catch (e) { threw2 = e; }
ok("update() does not throw", threw2 === null, threw2 && threw2.message);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
