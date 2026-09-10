// Filename:    test_energy_cost.mjs
// Description: Node contract test for energy-calc.js — the shared arithmetic
//              behind the Energy and Cost pages. Locks the v2.46.0 audit fixes:
//              the half-hourly chart no longer double-counts export and import,
//              the Sankey accounts for every kWh it draws, a null SOC slot no
//              longer reads as 0%, and a history row with no saved standing
//              charge falls back instead of billing £0.00.
// Author:      CliveS & Claude Opus 5
// Date:        25-07-2026
// Version:     1.0
//
// Run: node tests/test_energy_cost.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "energy-calc.js");

const ctx = { window: {}, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(SRC, "utf8"), ctx);
const C = ctx.window.DashCalc;
assert.ok(C, "energy-calc.js must publish window.DashCalc");

let passed = 0, failed = 0;
function test(name, fn) {
    try { fn(); passed++; }
    catch (e) { failed++; console.error(`  FAIL  ${name}\n        ${e.message}`); }
}
const near = (a, b, tol = 1e-6) =>
    assert.ok(Math.abs(a - b) <= tol, `expected ${b}, got ${a}`);

/* ───────── computeFlows: every kWh has to go somewhere ───────── */

// A real day off the live system: 25-Jul-2026 to mid-afternoon.
const LIVE_DAY = { pv_kwh: 34.36, home_kwh: 19.99, import_kwh: 0.08, export_kwh: 12.53 };

test("flows: both sides of the diagram balance", () => {
    const f = C.computeFlows(LIVE_DAY, 8, 8);
    near(f.totalIn, f.totalOut, 1e-9);
});

test("flows: solar ribbons sum to the solar node", () => {
    const f = C.computeFlows(LIVE_DAY, 8, 8);
    // Whatever solar is not matched to a sink lands in `loss`, so the node is
    // never drawn taller than the ribbons leaving it.
    assert.ok(f.s2l + f.s2b + f.s2g <= f.pv + 1e-9);
});

test("flows: the live day's residual is the ~1.9 kWh that used to vanish", () => {
    const f = C.computeFlows(LIVE_DAY, 8, 8);
    near(f.loss, 1.92, 0.01);
});

test("flows: solar covers the house before it charges the battery", () => {
    const f = C.computeFlows({ pv_kwh: 10, home_kwh: 4, import_kwh: 0, export_kwh: 0 }, 6, 0);
    near(f.s2l, 4);
    near(f.s2b, 6);
});

test("flows: cannot allocate more solar than was generated", () => {
    // THE OLD BUG: s2b = chg - g2b was never capped at pv. When the charge
    // figure and the meters disagree — they come from different sources, the
    // inverter's daily counters vs the half-hour totals — the shortfall was
    // charged to solar that was never generated. Here: 10 kWh into the battery
    // on a day with no sun and only 3 kWh imported drew 7 kWh of phantom solar.
    const f = C.computeFlows({ pv_kwh: 0, home_kwh: 5, import_kwh: 3, export_kwh: 0 }, 10, 0);
    near(f.s2b, 0);
    near(f.s2l, 0);
    assert.ok(f.unmet > 0, "the mismatch should be reported, not absorbed");
});

test("flows: grid charging is still attributed to the grid", () => {
    const f = C.computeFlows({ pv_kwh: 0, home_kwh: 5, import_kwh: 15, export_kwh: 0 }, 10, 0);
    near(f.g2b, 10);
    near(f.g2l, 5);
    near(f.s2b, 0);
});

test("flows: battery discharge covers what solar could not", () => {
    const f = C.computeFlows({ pv_kwh: 2, home_kwh: 10, import_kwh: 3, export_kwh: 0 }, 0, 5);
    near(f.s2l, 2);
    near(f.b2l, 5);
    near(f.g2l, 3);
    near(f.loss, 0);
});

test("flows: an all-zero day does not divide by anything", () => {
    const f = C.computeFlows({}, 0, 0);
    near(f.totalIn, 0);
    near(f.totalOut, 0);
    near(f.loss, 0);
});

test("flows: negative inputs are clamped, not propagated", () => {
    const f = C.computeFlows({ pv_kwh: -5, home_kwh: 3, import_kwh: 3, export_kwh: 0 }, 0, 0);
    near(f.pv, 0);
    near(f.g2l, 3);
});

/* ───────── buildBalanceSeries: sources up, sinks down ───────── */

const SLOT = (pv, home, imp, exp, s0, s1) =>
    ({ pv_kwh: pv, home_kwh: home, import_kwh: imp, export_kwh: exp,
       soc_start: s0, soc_end: s1 });

test("balance: export is not stacked on top of solar", () => {
    // The old chart's positive stack was pv + exp. Here the positive stack is
    // solar + battery discharge + import, and export sits on the NEGATIVE side.
    const b = C.buildBalanceSeries([SLOT(4, 1, 0, 3, 50, 50)], 35.04);
    near(b.solar[0], 4);
    near(b.gridOut[0], -3);
    assert.ok(b.gridOut[0] < 0, "export must be a sink");
});

test("balance: import is not stacked under home", () => {
    const b = C.buildBalanceSeries([SLOT(0, 2, 2, 0, 50, 50)], 35.04);
    near(b.gridIn[0], 2);      // a source, positive
    near(b.home[0], -2);       // a sink, negative
});

test("balance: a balanced slot sums to zero", () => {
    // 4 kWh solar: 1 to the house, 3 exported. Nothing from or to the battery.
    const b = C.buildBalanceSeries([SLOT(4, 1, 0, 3, 50, 50)], 35.04);
    const total = b.solar[0] + b.batteryOut[0] + b.gridIn[0]
                + b.home[0] + b.batteryIn[0] + b.gridOut[0];
    near(total, 0, 1e-9);
});

test("balance: a rising SOC is a sink, a falling SOC is a source", () => {
    const cap = 35.04;
    const up = C.buildBalanceSeries([SLOT(5, 0, 0, 0, 40, 50)], cap);
    near(up.batteryIn[0], -(10 / 100 * cap));
    near(up.batteryOut[0], 0);
    const down = C.buildBalanceSeries([SLOT(0, 5, 0, 0, 50, 40)], cap);
    near(down.batteryOut[0], 10 / 100 * cap);
    near(down.batteryIn[0], 0);
});

test("balance: a battery slot balances end to end", () => {
    const cap = 35.04;
    const charge = 10 / 100 * cap;                        // 3.504 kWh
    const b = C.buildBalanceSeries([SLOT(charge + 1, 1, 0, 0, 40, 50)], cap);
    const total = b.solar[0] + b.batteryOut[0] + b.gridIn[0]
                + b.home[0] + b.batteryIn[0] + b.gridOut[0];
    near(total, 0, 1e-9);
});

test("balance: a missing SOC reading means no battery bar, not a wrong one", () => {
    const b = C.buildBalanceSeries([SLOT(4, 4, 0, 0, null, null)], 35.04);
    near(b.batteryIn[0], 0);
    near(b.batteryOut[0], 0);
});

test("balance: capacity comes from the caller, not a constant", () => {
    const small = C.buildBalanceSeries([SLOT(0, 0, 0, 0, 40, 50)], 10);
    near(small.batteryIn[0], -1);          // 10% of 10 kWh
});

/* ───────── socSeries: nulls break the line ───────── */

test("soc: a null slot does not become 0%", () => {
    const s = C.socSeries([{ soc_end: 80 }, { soc_end: null }, { soc_end: 75 }]);
    assert.equal(s.points[1], null);
    assert.equal(s.min, 75);            // NOT 0
    assert.equal(s.max, 80);
});

test("soc: a missing field is treated as a gap", () => {
    const s = C.socSeries([{ soc_end: 60 }, {}, { soc_end: 62 }]);
    assert.equal(s.points[1], null);
    assert.equal(s.count, 2);
});

test("soc: an all-null run reports nothing rather than zero", () => {
    const s = C.socSeries([{ soc_end: null }, {}]);
    assert.equal(s.min, null);
    assert.equal(s.max, null);
    assert.equal(s.count, 0);
});

test("soc: a genuine 0% is kept", () => {
    const s = C.socSeries([{ soc_end: 0 }, { soc_end: 40 }]);
    assert.equal(s.min, 0);
    assert.equal(s.count, 2);
});

/* ───────── winMoney: the standing-charge fallback ───────── */

function byDateOf(rows) { return new Map(rows.map(r => [r.date, r])); }
const ANCHOR = Date.parse("2026-07-24") + 43200000;   // noon, DST-safe

function week(startBack, standingPerDay) {
    const rows = [];
    for (let i = 0; i < 7; i++) {
        const d = C.isoOffset(ANCHOR, startBack + i);
        const r = { date: d, grid_import_kwh: 5, rate_today_p: 20,
                    grid_export_kwh: 10, export_rate_p: 12 };
        if (standingPerDay !== null) r.elec_standing_p_day = standingPerDay;
        rows.push(r);
    }
    return rows;
}

test("money: a saved standing charge is used", () => {
    const w = C.winMoney(byDateOf(week(0, 61.5)), ANCHOR, 0, null);
    near(w.bill, 7 * (5 * 0.20 + 0.615), 1e-9);
    assert.equal(w.standingKnown, 7);
});

test("money: a missing standing charge falls back instead of billing zero", () => {
    // THE BUG: 87 of the first 121 live rows have no elec_standing_p_day, so
    // those weeks were billed with no standing charge at all.
    const w = C.winMoney(byDateOf(week(0, null)), ANCHOR, 0, 61.5);
    near(w.bill, 7 * (5 * 0.20 + 0.615), 1e-9);
    assert.equal(w.standingKnown, 0);
});

test("money: with no fallback either, it degrades to unit only", () => {
    const w = C.winMoney(byDateOf(week(0, null)), ANCHOR, 0, null);
    near(w.bill, 7 * 5 * 0.20, 1e-9);
});

test("money: old and new weeks compare on the same footing", () => {
    // The comparison that was pure data-vintage artefact: recent rows carried a
    // standing charge, older ones did not, so the bill "rose" by ~£4.31/week.
    const rows = [...week(0, 61.5), ...week(7, null)];
    const map = byDateOf(rows);
    const cur  = C.winMoney(map, ANCHOR, 0, 61.5);
    const prev = C.winMoney(map, ANCHOR, 7, 61.5);
    near(cur.bill, prev.bill, 1e-9);
    assert.equal(C.pctDelta(cur.bill, prev.bill), 0);
});

test("money: export revenue uses the day's own rate", () => {
    const w = C.winMoney(byDateOf(week(0, 61.5)), ANCHOR, 0, null);
    near(w.exp, 7 * 10 * 0.12, 1e-9);
    near(w.net, w.exp - w.bill, 1e-9);
});

test("money: an empty window reports nothing found", () => {
    const w = C.winMoney(new Map(), ANCHOR, 0, 61.5);
    assert.equal(w.found, 0);
    near(w.bill, 0);
});

test("money: latestStandingP finds the newest saved value", () => {
    assert.equal(C.latestStandingP([
        { elec_standing_p_day: 50 }, { elec_standing_p_day: null },
        { elec_standing_p_day: 61.5 }, { elec_standing_p_day: null },
    ]), 61.5);
    assert.equal(C.latestStandingP([{ elec_standing_p_day: null }]), null);
    assert.equal(C.latestStandingP([]), null);
});

test("money: a year window needs 364 days of history to reach", () => {
    // Pairs with the SigenEnergyManager clamp lift (365 -> 800). With 365 days
    // only offset 364 is reachable, which is why the column never unlocked.
    const d364 = C.isoOffset(ANCHOR, 364);
    const d370 = C.isoOffset(ANCHOR, 370);
    assert.equal(d364, "2025-07-25");
    assert.equal(d370, "2025-07-19");
});

/* ───────── pctDelta ───────── */

test("delta: a zero baseline has no percentage", () => {
    assert.equal(C.pctDelta(5, 0), null);
    assert.equal(C.pctDelta(null, 5), null);
    assert.equal(C.pctDelta(5, null), null);
});

test("delta: a negative baseline uses its magnitude", () => {
    near(C.pctDelta(-5, -10), 50);
});

/* ───────── formatters ───────── */

test("fmt: watts below a kilowatt read in watts", () => {
    // fmtKw(30) used to return "0.03 kW".
    assert.equal(C.fmtKw(30), "30 W");
    assert.equal(C.fmtKw(1500), "1.50 kW");
    assert.equal(C.fmtKw(12345), "12.3 kW");
    assert.equal(C.fmtKw(-2500), "-2.50 kW");
    assert.equal(C.fmtKw(null), "—");
    assert.equal(C.fmtKw(undefined), "—");
});

test("fmt: money keeps the sign outside the pound sign", () => {
    assert.equal(C.gbp(1.5), "£1.50");
    assert.equal(C.gbp(-1.5), "−£1.50");
    assert.equal(C.gbp(1.5, { signed: true }), "+£1.50");
    assert.equal(C.gbp(0), "£0.00");
    assert.equal(C.gbp(null), "—");
});

test("fmt: a half-penny rate is not rounded away", () => {
    // toFixed(0) turned 12.5p into "13p" while the maths used 12.5.
    assert.equal(C.fmtPence(12), "12");
    assert.equal(C.fmtPence(12.5), "12.5");
    assert.equal(C.fmtPence(20.02), "20.02");
    assert.equal(C.fmtPence(null), "—");
});

test("fmt: kWh and percentages handle nulls", () => {
    assert.equal(C.fmtKwh(12.34), "12.3 kWh");
    assert.equal(C.fmtKwh(null), "—");
    assert.equal(C.fmtPct(99.64), "99.6%");
    assert.equal(C.fmtPct(100), "100.0%");
    assert.equal(C.fmtPct(null), "—");
});

/* ───────── backup runtime ───────── */

test("backup: reserve floor is honoured and configurable", () => {
    const r = C.backupRuntime(50, 1000, 40, 5);
    near(r.hours, (50 - 5) / 100 * 40 / 1);        // 18 h
    assert.equal(r.state, "ok");
});

test("backup: at or below the reserve there is no runtime", () => {
    assert.equal(C.backupRuntime(5, 1000, 40, 5), null);
    assert.equal(C.backupRuntime(3, 1000, 40, 5), null);
});

test("backup: no load means no honest estimate", () => {
    assert.equal(C.backupRuntime(80, 0, 40, 5), null);
    assert.equal(C.backupRuntime(80, null, 40, 5), null);
    assert.equal(C.backupRuntime(null, 500, 40, 5), null);
});

test("backup: a low runtime is flagged", () => {
    assert.equal(C.backupRuntime(10, 5000, 40, 5).state, "warn");
});

/* ───────── self-sufficiency ───────── */

test("self-sufficiency: share of use that did not come off the grid", () => {
    near(C.selfSufficiency(20, 0.08), (20 - 0.08) / 20 * 100);
    assert.equal(C.selfSufficiency(0, 0), null);       // not 100% at 00:05
    assert.equal(C.selfSufficiency(null, 1), null);
    near(C.selfSufficiency(10, 20), 0);                // clamped, never negative
});

/* ───────── buildSolarProgress (v1.1): today vs the forecast ─────────
   Fixtures mirror the REAL shapes checked live on 13-08-2026: /api/history
   slots carry local ISO `t` + per-slot pv_kwh; hourly_forecast is a
   {"HH:00": kWh} dict whose bucket is the kWh generated DURING that hour. */

const TODAY = "2026-08-13";
const slot = (hhmm, pv) => ({ t: `${TODAY}T${hhmm}:00`, pv_kwh: pv });
const SLOTS = [
    slot("06:35", 0.1), slot("07:05", 0.5), slot("07:35", 0.9),
    slot("08:05", 1.2),
    { t: "2026-08-12T12:05:00", pv_kwh: 99 },          // yesterday — ignored
];
const HOURLY = { "05:00": 0, "06:00": 0.4, "07:00": 1.6, "08:00": 2.6, "09:00": 3.2 };

test("solar progress: actual line accumulates today's slots only", () => {
    const p = C.buildSolarProgress(SLOTS, HOURLY, null, 500, TODAY);
    const last = p.actual[p.actual.length - 1];
    near(last.kwh, 0.1 + 0.5 + 0.9 + 1.2);             // yesterday's 99 excluded
    assert.equal(p.actual[0].m, 0);                     // anchored at midnight
});

test("solar progress: the authoritative total pins the line at now", () => {
    // slots reach 08:05 / 2.7 kWh; the running total says 3.1 at 08:30
    const p = C.buildSolarProgress(SLOTS, HOURLY, 3.1, 8 * 60 + 30, TODAY);
    const last = p.actual[p.actual.length - 1];
    assert.equal(last.m, 8 * 60 + 30);
    near(last.kwh, 3.1);
});

test("solar progress: a pinned total BEHIND the slots is refused", () => {
    // the line must never step backwards off a stale status payload
    const p = C.buildSolarProgress(SLOTS, HOURLY, 1.0, 8 * 60 + 30, TODAY);
    const last = p.actual[p.actual.length - 1];
    near(last.kwh, 2.7);
});

test("solar progress: expected line is the cumulative forecast at hour ends", () => {
    const p = C.buildSolarProgress([], HOURLY, null, 0, TODAY);
    near(p.expectedTotal, 0.4 + 1.6 + 2.6 + 3.2);
    const at9 = p.expected.find(pt => pt.m === 9 * 60);  // end of the 08:00 hour
    near(at9.kwh, 0.4 + 1.6 + 2.6);
});

test("solar progress: expected-at-now interpolates inside the hour", () => {
    // 07:30 sits halfway through the 07:00 bucket: the cumulative at the
    // 06:00 hour's END is 0.4, plus half of the 07:00 hour's 1.6.
    const p = C.buildSolarProgress([], HOURLY, null, 7 * 60 + 30, TODAY);
    near(p.expectedNow, 0.4 + 1.6 / 2, 0.01);
});

test("solar progress: delta is actual minus expected-at-now", () => {
    const p = C.buildSolarProgress(SLOTS, HOURLY, 3.1, 8 * 60 + 30, TODAY);
    near(p.deltaKwh, 3.1 - p.expectedNow, 0.01);
});

test("solar progress: before dawn everything is zero, nothing invented", () => {
    const p = C.buildSolarProgress([], HOURLY, 0, 120, TODAY);
    near(p.expectedNow, 0);
    near(p.deltaKwh, 0);
});

test("solar progress: malformed slots and junk hours are skipped", () => {
    const p = C.buildSolarProgress(
        [null, {}, { t: 42, pv_kwh: 1 }, slot("07:05", "junk"), slot("07:35", 1.0)],
        { junk: 1, "26:00": 5, "07:00": 2.0 }, null, 480, TODAY);
    const last = p.actual[p.actual.length - 1];
    near(last.kwh, 1.0);
    near(p.expectedTotal, 2.0);
});

test("solar progress: no slots and no forecast still returns a safe shape", () => {
    const p = C.buildSolarProgress(null, null, null, 600, TODAY);
    assert.equal(p.actual.length, 1);
    assert.equal(p.expected.length, 1);
    assert.equal(p.deltaKwh, null);
});

test("solar typical range derives an honest bounded band from MAPE", () => {
    const r = C.solarTypicalRange(20, 12);
    assert.equal(r.fraction, 0.12);
    assert.equal(r.low, 17.6);
    assert.equal(r.high, 22.4);
    assert.equal(C.solarTypicalRange(20, 1).fraction, 0.05);   // no false precision
    assert.equal(C.solarTypicalRange(20, 90).fraction, 0.5);   // no unusable band
    assert.equal(C.solarTypicalRange(20, null), null);
});

/* ───────── buildSolarHours (v1.2): the stacked hourly chart's rows ─────────
   stringHours mirrors the solarStringHours endpoint: 24-array, null for an
   hour with no per-string samples, else [kWh x4] in PV-input order
   [West, East, South, Garage]. */

const SH = (() => {
    const a = new Array(24).fill(null);
    a[10] = [0.3, 0.9, 1.1, 0.4];      // 2.7 total
    a[11] = [0.4, 0.8, 1.3, 0.5];      // 3.0 total
    return a;
})();
const SITE_SLOTS = [
    slot("09:05", 1.0), slot("09:35", 1.2),   // midpoints 08:50, 09:20 -> hours 8 and 9
    slot("10:05", 1.3),                        // midpoint 09:50 -> hour 9
];
const FC = { "08:00": 2.0, "09:00": 2.4, "10:00": 2.9, "11:00": 3.2, "12:00": 3.4 };

test("solar hours: a string hour stacks and sums", () => {
    const m = C.buildSolarHours(SH, null, [], FC, 12 * 60 + 30, TODAY);
    const r10 = m.rows[10];
    assert.equal(r10.mode, "past");
    assert.deepEqual(r10.parts, [0.3, 0.9, 1.1, 0.4]);
    near(r10.total, 2.7);
});

test("solar hours: the endpoint's site series covers hours the strings can't", () => {
    // This is what lets BOTH pages draw a full day from one call: pv power
    // has been logged for years, so the morning before per-string logging
    // began is still real data, not a gap.
    const site = new Array(24).fill(null);
    site[8] = 2.5; site[9] = 3.1; site[10] = 2.7;
    const m = C.buildSolarHours(SH, site, [], FC, 12 * 60, TODAY);
    near(m.rows[8].total, 2.5);
    assert.equal(m.rows[8].parts, null);        // site only — a plain bar
    near(m.rows[10].total, 2.7 + 0);            // hour 10 HAS strings…
    assert.notEqual(m.rows[10].parts, null);    // …so it stacks, site ignored
});

test("solar hours: site series beats the half-hour slots", () => {
    // Exact hour buckets from the endpoint outrank the slot midpoint
    // approximation, which is only there for an install with no SQL Logger.
    const site = new Array(24).fill(null);
    site[9] = 9.9;
    const m = C.buildSolarHours(null, site, SITE_SLOTS, FC, 12 * 60, TODAY);
    near(m.rows[9].total, 9.9);
});

test("solar hours: site slots fall back by MIDPOINT, not stamp", () => {
    const m = C.buildSolarHours(null, null, SITE_SLOTS, FC, 12 * 60, TODAY);
    // the 09:05 slot's energy is mostly 08:35-09:05 -> hour 8;
    // 09:35 and 10:05 both land in hour 9
    near(m.rows[8].total, 1.0);
    near(m.rows[9].total, 1.2 + 1.3);
    assert.equal(m.rows[8].parts, null);
});

test("solar hours: strings win over site slots for the same hour", () => {
    const withBoth = C.buildSolarHours(SH, null, SITE_SLOTS, FC, 12 * 60, TODAY);
    assert.notEqual(withBoth.rows[10].parts, null);
    near(withBoth.rows[10].total, 2.7);           // not the slot figure
});

test("solar hours: future is forecast-only, current is its own mode", () => {
    const m = C.buildSolarHours(SH, null, [], FC, 11 * 60 + 20, TODAY);
    assert.equal(m.rows[11].mode, "current");
    assert.equal(m.rows[12].mode, "future");
    assert.equal(m.rows[12].total, null);
    near(m.rows[12].forecast, 3.4);
});

test("solar hours: scoreboard counts completed daylight hours only", () => {
    // at 12:30 — hours 10 (2.7 vs 2.9 = miss) and 11 (3.0 vs 3.2 = miss)
    // are past-with-data; dark hours have neither side and prove nothing.
    const m = C.buildSolarHours(SH, null, [], FC, 12 * 60 + 30, TODAY);
    assert.equal(m.played, 2);
    assert.equal(m.won, 0);
});

test("solar hours: beating the tick counts, near-equal counts as hit", () => {
    const a = new Array(24).fill(null);
    a[10] = [1.0, 1.0, 1.0, 0.5];      // 3.5 vs forecast 2.9 = won
    a[11] = [1.0, 1.0, 1.0, 0.17];     // 3.17 vs 3.2 — within tolerance = won
    const m = C.buildSolarHours(a, null, [], FC, 12 * 60 + 30, TODAY);
    assert.equal(m.played, 2);
    assert.equal(m.won, 2);
});

test("solar hours: a past hour with no data at all stays null, not played", () => {
    const m = C.buildSolarHours(null, null, [], FC, 12 * 60, TODAY);
    assert.equal(m.rows[10].total, null);      // gap drawn as a gap
    assert.equal(m.played, 0);
});

test("solar hours: the current hour never counts as lost while running", () => {
    const a = new Array(24).fill(null);
    a[11] = [0.1, 0.1, 0.1, 0.1];              // 0.4 so far vs 3.2 forecast
    const m = C.buildSolarHours(a, null, [], FC, 11 * 60 + 10, TODAY);
    assert.equal(m.rows[11].mode, "current");
    assert.equal(m.played, 0);
});

/* ───────── pack balance + grid frequency (v1.4) ───────── */

test("pack balance: a hot outlier is named with its gap", () => {
    // the live reading: avg 34.9, max 39.0, min 32.4 over four packs
    const t = C.packBalanceText({ verdict: "one_hot", spread_c: 6.6,
                                  hot_gap_c: 4.9, cold_gap_c: 1.7 });
    assert.ok(t.text.includes("4.9°C above the others"));
});

test("pack balance: a big gap is flagged, a modest one is not", () => {
    const mild = C.packBalanceText({ verdict: "one_hot", spread_c: 5,
                                     hot_gap_c: 3.0, cold_gap_c: 1.0 });
    const bad  = C.packBalanceText({ verdict: "one_hot", spread_c: 9,
                                     hot_gap_c: 7.0, cold_gap_c: 1.0 });
    assert.equal(mild.tone, "");
    assert.equal(bad.tone, "warn");
});

test("pack balance: an even battery says so, with its spread", () => {
    const t = C.packBalanceText({ verdict: "even", spread_c: 1.4,
                                  hot_gap_c: 0.7, cold_gap_c: 0.7 });
    assert.equal(t.tone, "good");
    assert.ok(t.text.includes("1.4°C apart"));
});

test("pack balance: no verdict means NO reassurance", () => {
    // the plugin returns null when the aggregates cannot support an
    // inference — the card must then say nothing, never "healthy"
    assert.equal(C.packBalanceText(null), null);
    assert.equal(C.packBalanceText({}), null);
});

test("grid frequency: the normal band, the edges and the nonsense", () => {
    assert.equal(C.gridFrequencyState(49.96).tone, "good");   // as measured
    assert.equal(C.gridFrequencyState(50.35).tone, "warn");
    assert.equal(C.gridFrequencyState(49.2).tone, "bad");
    assert.equal(C.gridFrequencyState(null), null);
    assert.equal(C.gridFrequencyState(0), null);              // not "0 Hz"
});

test("grid voltage: the live reading sits just under the statutory ceiling", () => {
    // 252.21 V measured 13-Aug-2026 against a 253.0 V limit — inside, but
    // close enough that the tile should say so rather than read as fine.
    const s = C.gridVoltageState(252.21, 253.0, 216.2);
    assert.equal(s.tone, "warn");
    near(s.headroom, 0.79, 0.01);
});

test("grid voltage: over the ceiling is a curtailment risk, not a warning", () => {
    assert.equal(C.gridVoltageState(254.0, 253.0, 216.2).tone, "bad");
    assert.equal(C.gridVoltageState(215.0, 253.0, 216.2).tone, "bad");
});

test("grid voltage: a comfortable reading is good", () => {
    assert.equal(C.gridVoltageState(240.0, 253.0, 216.2).tone, "good");
});

test("grid voltage: limits come from the payload, not hardcoded here", () => {
    // a different network's limits must change the verdict
    assert.equal(C.gridVoltageState(252.21, 260.0, 216.2).tone, "good");
});

test("grid voltage: absent or nonsense readings say nothing", () => {
    assert.equal(C.gridVoltageState(null, 253, 216.2), null);
    assert.equal(C.gridVoltageState(0, 253, 216.2), null);
});

test("grid frequency: the offset carries its sign", () => {
    near(C.gridFrequencyState(49.96).offset, -0.04, 1e-9);
    near(C.gridFrequencyState(50.10).offset, 0.10, 1e-9);
});

test("solar hours: malformed inputs degrade, never throw", () => {
    const m = C.buildSolarHours([{}, "junk"], null, [null, {t: 9}], { junk: 1 }, NaN, TODAY);
    assert.equal(m.rows.length, 24);
    assert.equal(m.won, 0);
});

const total = passed + failed;
console.log(`${passed}/${total} node tests passed`);
if (failed) process.exit(1);
