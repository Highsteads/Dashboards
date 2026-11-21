// Filename:    test_savings_view.mjs
// Description: Node contract test for the Savings page's words and drawing
//              (savings-view.js, 3.71.0): money as a person writes it, every
//              step explained with its own figure, a credit called a credit,
//              the payback card without a cost, and the page drawn for every
//              period and step without throwing.
// Author:      CliveS & Claude Opus 5.5
// Date:        21-11-2026
// Version:     1.0
//
// Run: node tests/test_savings_view.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkOk as check, checkEq as eqLabelFirst, done } from "./lib/check.mjs";

const checkEq = (got, want, label) => eqLabelFirst(label, got, want);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const ctx = {};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "savings-view.js"), "utf8"), ctx);
const V = ctx.SavingsView;
const T = V._t;

// ── money and words ──────────────────────────────────────────────────────
checkEq(T.gbp(1834.36), "£1,834", "big sums have no pence");
checkEq(T.gbp(-398.18), "£398", "the size only: callers say which way");
checkEq(T.gbp(13.3), "£13.30", "small sums keep their pence");
checkEq(T.gbp(0.42), "42p", "under a pound is pence");
checkEq(T.gbp(null), "—", "nothing to show is a dash");
checkEq(T.pence(-7.6), "7.6p", "pence keep one place");
checkEq(T.pence(27.5), "27.5p", "and do not round 27.5 up to 28");
checkEq(T.tariffName("flux"), "Octopus Flux", "tariff names translated");
checkEq(T.tariffName("weird"), "\"weird\"", "an unknown tariff is quoted, not dropped");
checkEq(T.listWords(["a", "b", "c"]), "a, b and c", "lists join with and");
checkEq(T.plural(1, "day"), "one day", "one day");
checkEq(T.plural(24, "grid event"), "24 grid events", "numbers over ten as figures");
checkEq(T.dateWords("2026-03-27"), "27 March", "dates as a person says them");

// ── a reply shaped like the server's ──────────────────────────────────────
const steps = { nokit: 1436.18, solar: 1321.07, tariff: 13.3, battery: 362.62, extras: 137.36, paid: -398.18 };
const energy = { home: 5220.7, pv: 8318.2, imp: 1299.5, exp: 4245.9, direct: 2556.7, solar_stored: 2726.2,
                 solar_exported: 3035.3, home_solar: 4372.8, home_grid_direct: 256.8, home_grid_battery: 591.2,
                 batt_export: 799.7 };
const period = (over) => Object.assign({
  days: 237, estimatedDays: 41, unpricedDays: 0, missingDays: 3, first: "2026-03-27", last: "2026-11-20",
  saved: 1834.36, steps, events: 114.49, credits: 22.87, energy, selfSufficiencyPct: 83.8,
  solarOnlySelfUsePct: 49.0, pricePaidP: -7.6, priceNoKitP: 27.5, billedDays: 168,
  billCheck: { model: -136.6, octopus: -143.09 },
  eras: [{ name: "tracker", days: 163, first: "2026-03-27", last: "2026-09-07", saved: 1345.09, tariffEffect: 14.64, pv: 7005.2 },
         { name: "flux", days: 65, first: "2026-09-17", last: "2026-11-20", saved: 425.56, tariffEffect: 8.42, pv: 1016.1 }],
  weeks: [{ week: "2026-11-16", days: 5, saved: 20.1, pv: 30.2, estimated: false }],
  best: { date: "2026-04-30", saved: 18.85, pv: 64.0 }, worst: { date: "2026-11-15", saved: 0.5, pv: 4.7 },
  extrasList: [{ date: "2026-11-18", kind: "grid_event", gbp: 4.01, kwh: 4.01, counted: true },
               { date: "2026-03-19", kind: "other", gbp: 25, kwh: null, counted: false, why: "not earned by the kit", label: "Referred Credit" }],
}, over || {});
const reply = {
  ok: true, at: 1763750000, first: "2026-03-27", last: "2026-11-20",
  periods: { "1m": period({ saved: 166.99, steps: Object.assign({}, steps, { tariff: -3.1, paid: 35.02 }) }), all: period() },
  projection: { saved: 2495.82, pv: 9130.2, filled: [1, 2, 3, 12], basis: "2026-11" },
  payback: { cost: 26470, savedSoFar: 1834.36, pct: 6.9, yearsTotal: 10.6, paidOffDate: "2036-10-04" },
  quote: { annualSaving: 2352, annualKwh: 9112, paybackYears: 12 },
  installDate: "2026-03-12", daysBeforeRecords: 15, missing: [], rates: {},
};

// ── every step has its own figure, and the waterfall carries each bar ──────
for (const s of ["nokit", "solar", "tariff", "battery", "extras", "paid"]) {
  const w = T.stepWords(s, Object.assign({ _key: "all" }, reply.periods.all));
  check(w.head && w.fig && w.text, `step ${s} has a heading, a figure and words`);
  check(!/undefined|NaN/.test(w.text + w.fig), `step ${s} has no undefined or NaN`);
}
checkEq(T.stepWords("paid", Object.assign({ _key: "all" }, reply.periods.all)).fig, "£398 in credit", "a negative bill is a credit");
checkEq(T.stepWords("tariff", Object.assign({ _key: "1m" }, reply.periods["1m"])).fig, "£3.10 more", "a dearer tariff says more");
const svg = T.waterfall(reply.periods.all, "battery");
checkEq((svg.match(/data-step="/g) || []).length, 6, "six bars");
check(svg.includes('aria-pressed="true"'), "the chosen bar is marked pressed");
check(svg.includes("−£1,321"), "the solar bar shows what it took off");
check(/>Credit</.test(svg) && !svg.includes("credit</text>"), "a negative bill is labelled Credit under the bar");
check(T.waterfall(reply.periods.all, "nokit", true).includes('viewBox="0 0 380 '), "a phone gets the narrower canvas");

// ── the whole page, every period and step ──────────────────────────────────
for (const key of ["1m", "all"]) {
  for (const s of ["nokit", "solar", "tariff", "battery", "extras", "paid", "nonsense"]) {
    const html = V.page(reply, key, s, false);
    check(!/undefined|NaN/.test(html), `page ${key}/${s} has no undefined or NaN`);
  }
}
const html = V.page(reply, "all", "paid", true);
check(html.includes("On course for"), "the quote is compared");
check(html.includes("not counted, not earned by the kit"), "a referral is listed but not counted");
check(html.includes("Gas is not counted") || html.includes("gas is not counted"), "the notes say gas is left out");
check(html.includes("Battery wear is not counted"), "the notes say battery wear is left out");
check(/15 days before that/.test(html), "days before the records are disclosed");

// ── no cost set: the payback card points at Settings ──────────────────────
const bare = Object.assign({}, reply, { payback: null, quote: null });
check(T.payback(bare).includes("settings.html"), "without a cost, the card says where to put it");

// ── names in the data are escaped ──────────────────────────────────────────
const evil = Object.assign({}, reply, { periods: { all: period({ eras: [{ name: "<img>", days: 1, first: "2026-01-01", last: "2026-01-01", saved: 1, pv: 1 }] }) } });
for (const s of ["nokit", "tariff", "paid"]) {
  check(!V.page(evil, "all", s, false).includes("<img>"), `a tariff name cannot inject markup (${s})`);
}

// ── the notes read as sentences and name products, not codes ──────────────
const notes = T.notesCard(Object.assign({}, reply, { rates: { fetched: 1763750000, products: { standard: "VAR-22-11-01", export: "OUTGOING-VAR-24-10-26", region: "F" } } }),
                          Object.assign({}, reply.periods.all, { missingDays: 3 }));
check(!/VAR-22-11-01|OUTGOING-VAR/.test(notes), "the notes name Octopus's products, not their codes");
check(/>Three days had records/.test(notes), "a note that starts with a number word starts with a capital");

done();
