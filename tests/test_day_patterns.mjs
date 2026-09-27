// Filename:    test_day_patterns.mjs
// Description: Node contract test for DashCalc.dayPattern / dayPatternCaption /
//              hourWords — the Energy page's "Through the day" card (v3.51.0),
//              fed by SigenEnergyManager 5.122.0's /api/day-patterns.
// Author:      CliveS & Claude Opus 5.5
// Date:        27-09-2026
// Version:     1.0
//
// Run: node tests/test_day_patterns.mjs   (exit 0 = pass)

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

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error("FAIL", name, "\n ", e.message); }
}

const flat = Array(48).fill(0.45);                       // 21.6 kWh, even
function withHump(from, to, extra, less) {              // hours [from, to) get `extra`
  const out = flat.slice();
  for (let h = from; h < to; h++) { out[2 * h] += extra / 2; out[2 * h + 1] += extra / 2; }
  if (less) for (let h = less[0]; h < less[1]; h++) { out[2 * h] -= less[2] / 2; out[2 * h + 1] -= less[2] / 2; }
  return out;
}
const sunday = { key: "sun", label: "Sundays", weekdays: [6], own_pattern: true,
                 days_used: 17, min_days: 6, total_kwh: 21.6,
                 kwh: withHump(14, 16, 0.5, [10, 12, 0.25]), everyday_kwh: flat };
const payload = { available: true, away: false, window_days: 126, today_weekday: 6,
                  groups: [sunday] };

test("hourWords says hours the way people do", () => {
  assert.equal(C.hourWords(0), "midnight");
  assert.equal(C.hourWords(12), "midday");
  assert.equal(C.hourWords(9), "9am");
  assert.equal(C.hourWords(14), "2pm");
  assert.equal(C.hourWords(24), "midnight");
});

test("half-hours become hours", () => {
  const p = C.dayPattern(sunday);
  assert.equal(p.hours.length, 24);
  assert.equal(p.hours[14], 1.4);
  assert.equal(p.everyday[14], 0.9);
});

test("the biggest stretch each way is found", () => {
  const p = C.dayPattern(sunday);
  assert.deepEqual([p.more.from, p.more.to], [14, 16]);
  assert.deepEqual([p.less.from, p.less.to], [10, 12]);
});

test("a small wobble is not a finding", () => {
  const p = C.dayPattern({ ...sunday, kwh: withHump(14, 15, 0.15) });
  assert.equal(p.more, null);                            // 0.15 kWh in one hour < 0.3
  assert.equal(p.less, null);
});

test("the caption says where the day differs, in words", () => {
  const t = C.dayPatternCaption(sunday, payload);
  assert.equal(t, "Sundays use about 21.6 kWh a day. Compared with the everyday pattern, " +
                  "more of it goes between 2pm and 4pm, and less between 10am and midday. " +
                  "Measured from 17 Sundays over the last 18 weeks.");
});

test("a group of days is counted as 'of those days'", () => {
  const g = { ...sunday, key: "tue-fri", label: "Tuesdays to Fridays", weekdays: [1, 2, 3, 4],
              days_used: 63 };
  assert.match(C.dayPatternCaption(g, payload), /Measured from 63 of those days/);
});

test("a day without its own pattern says what it needs", () => {
  const g = { ...sunday, own_pattern: false, kwh: flat, days_used: 3, label: "Mondays",
              weekdays: [0] };
  assert.equal(C.dayPatternCaption(g, payload),
               "Mondays use about 21.6 kWh a day, planned from the everyday pattern for now: " +
               "3 whole Mondays recorded, 6 needed for their own.");
  const p = C.dayPattern(g);
  assert.equal(p.more, null);
});

test("an empty house says so instead", () => {
  assert.match(C.dayPatternCaption(sunday, { ...payload, away: true }), /marked as empty/);
});

test("a group that runs like the everyday pattern says so", () => {
  const g = { ...sunday, kwh: flat };
  assert.match(C.dayPatternCaption(g, payload), /runs much like the everyday pattern/);
});

test("an unusable group gives nothing, not a crash", () => {
  assert.equal(C.dayPattern(null), null);
  assert.equal(C.dayPattern({ kwh: [1, 2] }), null);
  assert.equal(C.dayPatternCaption({ kwh: [] }, payload), "");
});

test("the caption is plain: no pipes, no equals signs", () => {
  for (const t of [C.dayPatternCaption(sunday, payload)]) {
    assert.ok(!/[|=]/.test(t), t);
  }
});

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
