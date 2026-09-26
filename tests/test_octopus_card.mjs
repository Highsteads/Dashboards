// Filename:    test_octopus_card.mjs
// Description: Contract test for the Energy page's Octopus sessions card (3.49.0):
//              every joined event with Octopus's own result, the balances, and the
//              money Octopus owes for a booked free hour, shown until it is paid.
//              The words live in DashCalc (energy-calc.js) and are tested here
//              against payload shapes taken from the live account on 26-Sep-2026;
//              the render is driven against a stub DOM.
// Author:      CliveS & Claude Opus 5.5
// Date:        26-09-2026
// Version:     1.0
//
// Run: node tests/test_octopus_card.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { checkOk as check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");
const require_ = createRequire(import.meta.url);
require_(path.join(PAGES, "energy-calc.js"));
const DashCalc = globalThis.DashCalc;

console.log("Octopus sessions card");

const NOW = Date.parse("2026-09-30T12:00:00Z");

// ── words ──────────────────────────────────────────────────────
check(DashCalc.penceWords(80) === "80p", "pence under a pound", DashCalc.penceWords(80));
check(DashCalc.penceWords(779) === "£7.79", "pounds above", DashCalc.penceWords(779));
check(DashCalc.kwhWords(6) === "6 kWh" && DashCalc.kwhWords(15.25) === "15.3 kWh",
      "kWh without a trailing .0", DashCalc.kwhWords(15.25));
check(DashCalc.netKwhWords(-3.9) === "3.9 kWh out" && DashCalc.netKwhWords(0.5) === "0.5 kWh in",
      "negative net usage is export", DashCalc.netKwhWords(-3.9));

// ── history: Octopus's own record ──────────────────────────────
const history = [
    { id: 6541, start: "2026-09-27T13:00:00+00:00", end: "2026-09-27T14:00:00+00:00",
      direction: "WEEKEND_HAPPY_HOUR", status: "DONE", results: "SUCCESS", points: 0, pence: 0 },
    { id: 6400, start: "2026-09-25T17:00:00+00:00", end: "2026-09-25T18:00:00+00:00",
      direction: "TURN_DOWN", status: "DONE", results: "CALCULATING", points: null },
    { id: 6300, start: "2026-09-21T17:00:00+00:00", end: "2026-09-21T18:00:00+00:00",
      direction: "TURN_DOWN", status: "DONE", results: "SUCCESS", points: 256, pence: null,
      energy_delta_kwh: 3.4133, baseline_kwh: -0.53, consumption_kwh: -3.9,
      results_set_at: "2026-09-25T18:43:00+00:00" },
    { id: 6200, start: "2026-09-18T17:00:00+00:00", end: "2026-09-18T18:00:00+00:00",
      direction: "TURN_DOWN", status: "DONE", results: "FAIL", points: 0 },
];
const rows = DashCalc.sessionHistoryRows(history, NOW);
check(rows.length === 4, "one row per joined event", rows.length);
check(rows[0].kind === "Free hour" && rows[0].result === "Used" && rows[0].reward === ""
      && rows[0].counted === "", "a free hour shows no reward or baseline here", rows[0]);
check(rows[1].result === "Being scored" && rows[1].reward === "—",
      "not scored yet is a dash, not zero", rows[1]);
check(rows[2].result === "Won" && rows[2].cls === "good" && rows[2].reward === "32p",
      "256 points shown as 32p, never as points", rows[2].reward);
check(rows[2].usual === "0.5 kWh out" && rows[2].actual === "3.9 kWh out"
      && rows[2].counted === "3.4 kWh", "usual, this time and counted", rows[2]);
check(/^scored /.test(rows[2].scored), "the scoring date is carried", rows[2].scored);
check(rows[3].result === "Missed" && rows[3].cls === "", "a miss is plain, not amber", rows[3]);

// ── summary ────────────────────────────────────────────────────
const credits = [
    { date: "2026-09-27", state: "awaiting", start: "2026-09-27T12:00:00+00:00",
      end: "2026-09-27T14:00:00+00:00", hours: 2, kwh: 31.5, kwh_source: "inverter",
      rate_p: [24.35], expected_p: 767, paid_p: 0, owed_p: 767, days_waiting: 3,
      credits: [], other_credits: [] },
    { date: "2026-09-13", state: "late", start: "2026-09-13T12:00:00+00:00",
      end: "2026-09-13T13:00:00+00:00", hours: 1, kwh: 16, kwh_source: "meter",
      rate_p: [24.35], expected_p: 390, paid_p: 0, owed_p: 390, days_waiting: 17,
      credits: [], other_credits: [{ posted: "2026-09-20", amount_p: 412, title: "Adjustment" }] },
    { date: "2026-09-06", state: "short", start: "2026-09-06T12:00:00+00:00",
      end: "2026-09-06T13:00:00+00:00", hours: 1, kwh: 16, kwh_source: "meter",
      rate_p: [24.35], expected_p: 390, paid_p: 300, owed_p: 90, days_waiting: 24,
      credits: [{ posted: "2026-09-15", amount_p: 300 }], other_credits: [] },
    { date: "2026-08-30", state: "paid", start: "2026-08-30T12:00:00+00:00",
      end: "2026-08-30T13:00:00+00:00", hours: 1, kwh: 16, kwh_source: "meter",
      rate_p: [24.35], expected_p: 390, paid_p: 390, owed_p: 0, days_waiting: 31,
      credits: [{ posted: "2026-09-04", amount_p: 390 }],
      other_credits: [{ posted: "2026-09-01", amount_p: 5, title: "x" }] },
];
const sum = DashCalc.octopusSummary({ token_balance: 5, points_balance: 3524,
                                      free_hour_credits: credits });
check(sum.hoursLeft === 2 && sum.pointsText === "£4.41", "5 tokens is 2 hours; 3524 points is £4.41", sum);
check(sum.owedP === 767 + 390 + 90 && sum.openClaims === 3, "owed counts open claims only", sum);
check(DashCalc.octopusSummary({}).hoursLeft === null, "tokens not reported is not zero hours");

// ── free-hour credit lines ─────────────────────────────────────
const lines = DashCalc.freeHourCreditLines(credits, NOW);
check(/owes £7\.67/.test(lines[0].text) && /Not paid yet, 3 days so far\./.test(lines[0].text)
      && /our own reading/.test(lines[0].text) && lines[0].cls === "",
      "awaiting says what is owed, for how long, and that it is an estimate", lines[0].text);
check(lines[1].cls === "warn" && /Still not paid after 17 days\./.test(lines[1].text)
      && /Adjustment/.test(lines[1].others), "late is amber and shows other credits", lines[1]);
check(lines[2].cls === "warn" && /90p is still owed\./.test(lines[2].text), "short says what is left", lines[2].text);
check(lines[3].cls === "good" && /has paid £3\.90/.test(lines[3].text) && lines[3].others === "",
      "paid is green and needs no other-credits line", lines[3]);
for (const l of lines) {
    const t = l.head + " " + l.text + " " + l.others;
    check(!/[|=]/.test(t) && /\.$/.test(l.text) && !/\d\.0 kWh/.test(t),
          "plain English: sentences, no value-dump punctuation", t);
}

// ── savingSessions takes a longer look ahead for the card ──────
const oct = { upcoming: [{ id: 9, start: "2026-10-04T12:00:00+00:00", end: "2026-10-04T13:00:00+00:00",
                           direction: "WEEKEND_HAPPY_HOUR", joined: true }] };
check(DashCalc.savingSessions(oct, NOW).length === 0, "the alert bar still looks one day ahead");
check(DashCalc.savingSessions(oct, NOW, 8 * 24 * 3600e3).length === 1, "the card looks eight days ahead");

// ── the render, against a stub DOM ─────────────────────────────
const raw = fs.readFileSync(path.join(PAGES, "energy.html"), "utf8");
const code = raw.replace(/\/\*[\s\S]*?\*\//g, "");
function fn(name) {
    const start = code.indexOf(`function ${name}(`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(name);
}
const els = {};
const doc = { getElementById: (id) => (els[id] = els[id] || { id, style: {}, textContent: "", innerHTML: "", className: "" }) };
const ctx = { Date, Math, Number, String, DashCalc, document: doc,
              esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;") };
vm.createContext(ctx);
vm.runInContext("const OCT_LOOKAHEAD_MS = 8 * 24 * 3600 * 1000;\n" + fn("renderOctopusCard")
                + "\nglobalThis.renderOctopusCard = renderOctopusCard;", ctx);
ctx.renderOctopusCard({});
check(els["oct-card"].style.display === "none", "nothing to say hides the card");
ctx.renderOctopusCard({ token_balance: 5, points_balance: 3524, history, free_hour_credits: credits });
check(els["oct-card"].style.display === "", "something to say shows it");
check(els["oct-hours"].textContent === "2" && els["oct-points"].textContent === "£4.41",
      "tiles carry the balances");
check(els["oct-owed"].className.includes("warn"), "the owed tile goes amber when a claim is late or short");
check(els["oct-credits"].innerHTML.includes("Free-hour credits")
      && els["oct-history"].innerHTML.includes("Being scored"), "lists render");
check(!els["oct-credits"].innerHTML.includes("<script"), "text is escaped");

done();
