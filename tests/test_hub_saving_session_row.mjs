// Filename:    test_hub_saving_session_row.mjs
// Description: Contract test for the Octopus Saving Session row on the hub's
//              energy card.
//
//              WHY THIS EXISTS
//              The hub and the Energy page show the same fact in two different
//              shapes, and the failure mode for that is drift: two copies of
//              "are we in this session" that slowly disagree. The decision is
//              therefore shared (DashCalc.savingSessions) and only the wording
//              lives per page — these tests pin the wording AND the sharing.
//              They also pin that the row reaches BOTH layouts: the hub renders
//              a short phone card and a fuller desktop one from separate
//              template literals, so a row added to one silently never appears
//              on the other.
// Author:      CliveS & Claude Opus 5
// Date:        15-09-2026
// Version:     1.0
//
// Run: node tests/test_hub_saving_session_row.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { checkOk as check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages");
const raw = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");
const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function fn(name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in index.html`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

// The REAL shared module, not a stub — a stub would let the hub and the shared
// rule drift apart, which is the whole reason the decision was lifted out.
const require_ = createRequire(import.meta.url);
require_(path.join(PAGES, "energy-calc.js"));
const DashCalc = globalThis.DashCalc;
if (!DashCalc || typeof DashCalc.savingSessions !== "function") {
    throw new Error("energy-calc.js did not export DashCalc.savingSessions");
}

const ctx = { Date, Math, Number, String, window: { DashCalc }, DashCalc,
              escapeAttr: (x) => String(x).replace(/[<>&"]/g, "_") };
vm.createContext(ctx);
vm.runInContext(fn("savingSessionRow") + "\nglobalThis.savingSessionRow = savingSessionRow;", ctx);
const row = ctx.savingSessionRow;

const NOW = Date.parse("2026-09-15T12:00:00Z");
const at = (h, len = 1) => ({
    start: new Date(NOW + h * 3600e3).toISOString(),
    end:   new Date(NOW + (h + len) * 3600e3).toISOString(),
});
const ev = (o = {}) => Object.assign({ id: 1, points: 72, direction: "TURN_DOWN",
                                       joined: true }, at(6), o);
const one = (e) => row({ upcoming: [e] }, NOW);

console.log("Hub saving-session row");

// ── honest silence ─────────────────────────────────────────────
check(row({ upcoming: [] }, NOW) === "", "no session renders NO row at all");
check(row(null, NOW) === "", "a missing payload renders no row");
check(!/None announced/.test(row({ upcoming: [] }, NOW)),
      "and never claims 'none announced' — that payload carries no health field");

// ── the states ─────────────────────────────────────────────────
let h = one(ev({ joined: false }));
check(/NOT OPTED IN/.test(h) && /val warn/.test(h),
      "not opted in says so and is amber", h.slice(-70));
h = one(ev({ joined: true }));
check(/opted in/.test(h) && /val ok/.test(h) && !/NOT OPTED IN/.test(h),
      "opted in reads ok", h.slice(-70));
check(/9p\/kWh/.test(h), "and quotes 72 points as 9p/kWh");
h = one(ev(at(-0.5)));
check(/Running/.test(h) && /val warn/.test(h), "a live session says Running", h.slice(-70));
h = one(ev({ direction: "WEEKEND_HAPPY_HOUR", joined: false }));
check(h === "", "an unbooked free hour gives no row at all (CliveS, 26-Sep-2026)", h);
h = row({ upcoming: [ev(Object.assign({ direction: "WEEKEND_HAPPY_HOUR", joined: false }, at(2))),
                     ev(Object.assign({ direction: "WEEKEND_HAPPY_HOUR", joined: true }, at(4)))] }, NOW);
check(/Free hour/.test(h) && /booked/.test(h) && !/not booked/.test(h) && /val ok/.test(h),
      "an earlier unbooked hour does not hide the booked one after it", h.slice(-70));
h = one(ev({ direction: "TURN_UP" }));
check(/Power Up/.test(h) && /battery not driven/.test(h),
      "a Power Up says the battery is not driven", h.slice(-70));
h = one(ev({ direction: "MYSTERY" }));
check(/MYSTERY/.test(h), "an unknown direction is quoted, not dropped", h.slice(-70));

// ── one line only, soonest first ───────────────────────────────
h = row({ upcoming: [ev(Object.assign({ id: 2 }, at(8))), ev(Object.assign({ id: 1 }, at(3)))] }, NOW);
check((h.match(/class="row"/g) || []).length === 1, "only one row, however many sessions");
check(h.includes(DashCalc.sessionRange(NOW + 3 * 3600e3, NOW + 4 * 3600e3, NOW)),
      "and it is the soonest one");

// ── it is actually wired into BOTH layouts ─────────────────────
check((code.match(/\$\{ssRow\}/g) || []).length === 2,
      "the row is placed in both the phone and desktop layouts",
      `found ${(code.match(/\$\{ssRow\}/g) || []).length}`);
check(/const ssRow = savingSessionRow\(/.test(code), "and is computed once");
check(/savingSessionRow\(\(_sigen\(\) && _sigen\(\)\.octopus_sessions\)/.test(code),
      "fed from octopus_sessions, not from windows directly");

// ── the shared module is actually LOADED by this page ──────────
// A guarded call to a library the page never loads is a silent no-op: 16 of 20
// pages once called DashUI without a script tag for it.
check(/<script src="energy-calc\.js"><\/script>/.test(raw),
      "index.html loads energy-calc.js");
check(/DashCalc\.savingSessions/.test(code), "and the row goes through DashCalc");

done();
