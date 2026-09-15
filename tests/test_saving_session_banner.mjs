// Filename:    test_saving_session_banner.mjs
// Description: Contract test for the Octopus Saving Session banner on the
//              Energy page.
//
//              WHY THIS EXISTS
//              The obvious source for this banner is octopus_sessions.windows,
//              and it is the wrong one: that list is what the battery is DRIVEN
//              from, so the plugin filters it to JOINED turn-downs and happy
//              hours. A session you are not opted into is absent from it
//              altogether, so a banner built on it is silent in exactly the
//              case worth shouting about — an announced session earning
//              nothing. These tests pin the source, the joined/not-joined
//              split, the direction handling, and the fact that the warn
//              colour is carried as a flag rather than sniffed out of the
//              rendered text.
// Author:      CliveS & Claude Opus 5
// Date:        15-09-2026
// Version:     1.0
//
// Run: node tests/test_saving_session_banner.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "energy.html");
const raw = fs.readFileSync(SRC, "utf8");

// Strip comments so a rule can never be satisfied by prose that describes it.
const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function fn(name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in energy.html`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

// The DECISION lives in DashCalc (energy-calc.js), shared with the hub. Load the
// REAL module rather than stubbing it: a stub would let the page and the shared
// rule drift apart, which is the whole thing this split exists to prevent.
const require_ = createRequire(import.meta.url);
require_(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                   "Resources", "static", "pages", "energy-calc.js"));
const DashCalc = globalThis.DashCalc;
if (!DashCalc || typeof DashCalc.savingSessions !== "function") {
    throw new Error("energy-calc.js did not export DashCalc.savingSessions");
}

let pass = 0, fail = 0;
const check = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + detail : ""}`);
};

const ctx = { Date, Math, isFinite, Object, DashCalc,
              I: (n) => `<svg data-icon="${n}">` };
vm.createContext(ctx);
vm.runInContext([fn("savingSessionAlerts"),
                 "globalThis.savingSessionAlerts = savingSessionAlerts;"].join("\n"), ctx);
const alerts = ctx.savingSessionAlerts;

const NOW = Date.parse("2026-09-15T12:00:00Z");
const at = (hoursFromNow, lenH = 1) => ({
    start: new Date(NOW + hoursFromNow * 3600e3).toISOString(),
    end:   new Date(NOW + (hoursFromNow + lenH) * 3600e3).toISOString(),
});
const row = (o = {}) => Object.assign({ id: 1, points: 72, direction: "TURN_DOWN",
                                        joined: true, capacity: null }, at(6), o);
const one = (r) => alerts({ upcoming: [r] }, NOW);

console.log("Saving Session banner");

// ── the reason this exists ─────────────────────────────────────
let m = one(row({ joined: false }));
check(m.length === 1 && /NOT OPTED IN/.test(m[0].text),
      "an un-joined session says NOT OPTED IN", JSON.stringify(m[0] && m[0].text));
check(m.length === 1 && m[0].warn === true,
      "and it carries the warn flag");

m = one(row({ joined: true }));
check(m.length === 1 && /opted in/.test(m[0].text) && !/NOT OPTED IN/.test(m[0].text),
      "a joined session says opted in", JSON.stringify(m[0] && m[0].text));
check(m.length === 1 && m[0].warn === false,
      "and does not warn");

// ── live vs announced ──────────────────────────────────────────
m = one(row(at(-0.5)));
check(m.length === 1 && /ACTIVE/.test(m[0].text), "a live session says ACTIVE",
      JSON.stringify(m[0] && m[0].text));
check(alerts({ upcoming: [row(at(-3))] }, NOW).length === 0,
      "a finished session is dropped");
check(alerts({ upcoming: [row(at(48))] }, NOW).length === 0,
      "a session two days out is not news");
check(alerts({ upcoming: [row(at(-0.5, 96))] }, NOW).length === 1,
      "but a LIVE session always shows, however long it runs");

// ── direction ──────────────────────────────────────────────────
m = one(row({ direction: "WEEKEND_HAPPY_HOUR", joined: false }));
check(m.length === 1 && /not booked/.test(m[0].text) && m[0].warn === false,
      "an unbooked free hour says booked, not opted-in, and never warns",
      JSON.stringify(m[0] && m[0].text));
m = one(row({ direction: "TURN_UP" }));
check(m.length === 1 && /Power Up/.test(m[0].text) && /not driven/.test(m[0].text),
      "a Power Up says the battery is not driven", JSON.stringify(m[0] && m[0].text));
m = one(row({ direction: "SOMETHING_NEW" }));
check(m.length === 1 && /SOMETHING_NEW/.test(m[0].text),
      "an unknown direction is quoted, not dropped", JSON.stringify(m[0] && m[0].text));

// ── the money ──────────────────────────────────────────────────
m = one(row({ joined: false, points: 72 }));
check(/9p\/kWh/.test(m[0].text), "72 points renders as 9p/kWh", JSON.stringify(m[0].text));
m = one(row({ joined: false, points: 0 }));
check(!/p\/kWh/.test(m[0].text), "zero points quotes no rate at all");

// ── the degraded path ──────────────────────────────────────────
m = alerts({ windows: [row()] }, NOW);           // no `upcoming` key at all
check(m.length === 1 && !/NOT OPTED IN/.test(m[0].text),
      "an older plugin's windows-only payload never claims NOT OPTED IN");
check(alerts(null, NOW).length === 0, "a missing payload is silent, not a crash");
check(alerts({ upcoming: [Object.assign(row(), { start: "nonsense" })] }, NOW).length === 0,
      "an unparseable time is skipped rather than rendered as Invalid Date");

// ── structural: the bar colour is a flag, not a substring ──────
const ua = fn("updateAlerts");
check(/msgs\.some\(m => m\.warn\)/.test(ua),
      "the bar's warn class reads the flag");
check(!/m\.text\.includes\('Storm'\)/.test(ua),
      "and no longer sniffs the rendered text for 'Storm'");
check(/savingSessionAlerts\(d\.octopus_sessions/.test(ua),
      "updateAlerts feeds it octopus_sessions");
check(!/savingSessionAlerts\(d\.octopus_sessions\.windows/.test(ua),
      "and passes the whole block, not just windows");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
