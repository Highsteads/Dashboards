// Filename:    test_energy_dawn_viable.mjs
// Description: Node contract test for how the Energy page and the Flow page's
//              battery pop-up read SigenEnergyManager's decision.dawn_viable
//              (3.70.2). From SigenEnergyManager 5.145.2 that field is null
//              while the plugin has no dawn forecast to judge. Null is "not
//              known": it must not be drawn as a red "No" (a bare truth test
//              does that) nor as "Yes".
// Author:      CliveS & Claude Fable 5.2
// Date:        10-11-2026
// Version:     1.0
//
// Run: node tests/test_energy_dawn_viable.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkOk as check, checkEq as eqLabelFirst, done } from "./lib/check.mjs";

const checkEq = (got, want, label) => eqLabelFirst(label, got, want);
const HERE  = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src   = fs.readFileSync(path.join(PAGES, "energy.html"), "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) return null;
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// ── the Energy page's "Dawn viable" row ────────────────────────────────────
const fn = grab("dawnVerdict");
check(fn !== null, "energy.html has a dawnVerdict function");
if (fn !== null) {
    const dawnVerdict = vm.runInNewContext(`(${fn})`);
    const same = (got, text, cls, label) => {
        checkEq(got.text, text, label + ": text");
        checkEq(got.cls, cls, label + ": class");
    };
    same(dawnVerdict(true),  "Yes", "dv dawn-ok",   "true");
    same(dawnVerdict(false), "No",  "dv dawn-warn", "false");
    for (const [v, label] of [[null, "null"], [undefined, "missing"], ["", "blank"],
                               ["True", "the text True"], ["False", "the text False"], [0, "nought"], [1, "one"]]) {
        same(dawnVerdict(v), "—", "dv", label + " is a dash with no colour");
    }
}
check(!src.includes("d.decision.dawn_viable ?"), "update() has no bare truth test on dawn_viable");
check(src.includes("dawnVerdict(d.decision.dawn_viable)"), "update() reads the verdict through dawnVerdict");

// ── the Flow page's battery pop-up ─────────────────────────────────────────
const ctx = { window: {}, console, Date, Math, JSON };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "flow-popups.js"), "utf8"), ctx);
const P = ctx.window.FlowPopups;
const NOW = new Date(2026, 10, 10, 12, 0).getTime();
const base = { battery: { soc_pct: 61, power_w: 0, capacity_kwh: 35.04 }, home: { load_w: 500 }, grid: { power_w: 0 } };
const dawnLine = dec => (P.batteryView({ ...base, decision: dec }, NOW).lines.find(l => l.key === "dawn") || null);

checkEq(dawnLine({ action: "vpp_export", dawn_viable: null, soc_at_dawn_kwh: null }), null,
        "no forecast and no verdict: no dawn line at all");
checkEq(dawnLine({ action: "self_consumption", dawn_viable: true, soc_at_dawn_kwh: 15.9 }).text,
        "It should last until the sun comes up, with about 16 kWh (45%) left at dawn.", "yes is still said");
checkEq(dawnLine({ action: "start_import", dawn_viable: false, soc_at_dawn_kwh: 2 }).tone, "warn", "no is still a warning");
// A figure with no verdict beside it: give the figure, promise nothing.
const bare = dawnLine({ action: "self_consumption", dawn_viable: null, soc_at_dawn_kwh: 15.9 });
checkEq(bare.text, "About 16 kWh (45%) is expected to be left at dawn.", "a figure without a verdict makes no promise");
checkEq(bare.tone, "", "and is not a warning");

done();
