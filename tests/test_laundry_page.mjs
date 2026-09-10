// Filename:    test_laundry_page.mjs
// Description: Contract test for laundry.html's own logic — the freshness readout, the
//              clock wording, and the rule that collapses a day where every slot costs
//              the same.
//
//              WHY THIS EXISTS
//              Two of these are estate lessons rather than new ideas. A page that has
//              rendered once must still be able to say it has STOPPED (v3.9.2): the
//              freshness readout runs on its own timer, because a poll that has died
//              cannot be trusted to report that it has died. And a card that lists
//              forty-five identical rows saying "free" is a value dump — the first live
//              render of this page did exactly that, and it says it in one sentence now.
// Author:      CliveS & Claude Opus 5
// Date:        09-09-2026
// Version:     1.0
//
// Run: node tests/test_laundry_page.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "laundry.html");
const src = fs.readFileSync(SRC, "utf8");

// Pull the functions out rather than standing up a DOM: they are pure, and a test that
// needs a browser is a test nobody runs.
function grab(name) {
    const re = new RegExp("function " + name + "\\s*\\([\\s\\S]*?\\n\\}", "m");
    const m = src.match(re);
    assert.ok(m, `could not find function ${name}() in laundry.html`);
    return m[0];
}

const ctx = vm.createContext({ PLAN: null, STALE_AFTER_MS: 195000, esc: (s) => String(s) });
vm.runInContext(
    "const STALE = STALE_AFTER_MS;\n" +
    grab("agoWords") + "\n" + grab("freshness") + "\n" + grab("clock") + "\n" +
    grab("shapeCard") + "\n", ctx);

let failures = 0;
function check(name, fn) {
    try { fn(); console.log("  ok   " + name); }
    catch (e) { failures++; console.log("  FAIL " + name + "\n       " + e.message); }
}

console.log("laundry page");

/* ── the freshness readout ───────────────────────────────────────────────── */
check("nothing has arrived yet is NOT stale", () => {
    // Amber over a page that has never loaded is its own wrong answer; the loading
    // card is already saying so.
    assert.equal(ctx.freshness(undefined).stale, false);
    assert.equal(ctx.freshness(NaN).stale, false);
    assert.equal(ctx.freshness(-5).stale, false);
});

check("a fresh poll is not stale", () => {
    assert.equal(ctx.freshness(0).stale, false);
    assert.equal(ctx.freshness(60000).stale, false);
    assert.equal(ctx.freshness(195000).stale, false);
});

check("three missed polls IS stale, and says how long", () => {
    const f = ctx.freshness(240000);
    assert.equal(f.stale, true);
    assert.match(f.text, /not updating for 4 minutes/);
});

check("the age is worded the way a person says it", () => {
    assert.equal(ctx.agoWords(1000), "1 second");
    assert.equal(ctx.agoWords(45000), "45 seconds");
    assert.equal(ctx.agoWords(300000), "5 minutes");
    assert.equal(ctx.agoWords(60000 * 60), "1 hour");
    assert.equal(ctx.agoWords(60000 * 150), "3 hours");
});

check("_lastGood is written in exactly two places, both on data arriving", () => {
    // A third writer in a catch block would make the indicator unable to ever fire.
    const n = (src.match(/_lastGood = Date\.now\(\)/g) || []).length;
    assert.equal(n, 2, `_lastGood assigned ${n} times; expected the poll and the button only`);
    assert.ok(!/catch[\s\S]{0,200}_lastGood = Date\.now\(\)/.test(src),
              "_lastGood must never be stamped from a catch block");
});

check("the freshness readout runs on its OWN timer", () => {
    assert.ok(/setInterval\(markFreshness/.test(src),
              "a poll that has died cannot report that it has died");
});

/* ── clock wording ───────────────────────────────────────────────────────── */
check("times read the way a person says them", () => {
    const at = (h, m) => { const d = new Date(2026, 5, 15, h, m); return ctx.clock(d.toISOString()); };
    assert.equal(at(16, 0), "4pm");
    assert.equal(at(13, 1), "1:01pm");
    assert.equal(at(9, 30), "9:30am");
    assert.equal(at(12, 0), "12pm");
    assert.equal(at(0, 0), "12am");
});

check("no ISO time survives into the wording", () => {
    const d = new Date(2026, 5, 15, 14, 5);
    assert.ok(!/\d{2}:\d{2}:\d{2}/.test(ctx.clock(d.toISOString())));
});

/* ── the day-shape card ──────────────────────────────────────────────────── */
function shape(options) {
    // shapeCard now takes ONE appliance entry rather than reading a page-wide PLAN, so the
    // same card can be drawn for a washing machine and a dryer on the same page.
    return ctx.shapeCard({ options, start: options.length ? options[0].start : null,
                           appliance: { kwh: 0.74 } });
}

check("a day where every slot is free is said ONCE, not listed", () => {
    const opts = Array.from({ length: 45 }, (_, i) =>
        ({ start: new Date(2026, 5, 15, 10 + (i >> 1), (i % 2) * 30).toISOString(),
           grid_kwh: 0, cost_p: 0 }));
    const html = shape(opts);
    assert.ok(/All 45 of them come out the same/.test(html), "must say it in a sentence");
    assert.ok(!/class="slot/.test(html), "must not draw forty-five identical rows");
});

check("a day that actually differs IS listed, row by row", () => {
    const opts = [
        { start: new Date(2026, 5, 15, 10, 0).toISOString(), grid_kwh: 0.0, cost_p: 0 },
        { start: new Date(2026, 5, 15, 11, 0).toISOString(), grid_kwh: 0.4, cost_p: 10 },
        { start: new Date(2026, 5, 15, 12, 0).toISOString(), grid_kwh: 0.74, cost_p: 28 },
    ];
    const html = shape(opts);
    assert.equal((html.match(/class="slot/g) || []).length, 3);
    assert.ok(/free/.test(html), "a zero-grid slot is labelled free, not 0p");
    assert.ok(/28p/.test(html));
});

check("the free slot is marked so it reads at a glance", () => {
    const opts = [
        { start: new Date(2026, 5, 15, 10, 0).toISOString(), grid_kwh: 0.0, cost_p: 0 },
        { start: new Date(2026, 5, 15, 11, 0).toISOString(), grid_kwh: 0.4, cost_p: 10 },
    ];
    assert.ok(/slot free/.test(shape(opts)));
});

check("an appliance with no options at all draws no card", () => {
    assert.equal(ctx.shapeCard({ options: [] }), "");
    assert.equal(ctx.shapeCard({}), "");
    assert.equal(ctx.shapeCard(null), "");
});

check("the page renders one card per appliance, keyed for its own chips", () => {
    // Each chip carries the appliance it belongs to, or a second machine's buttons would
    // silently set the first one's deadline.
    assert.ok(/data-key="/.test(src), "chips must name their appliance");
    assert.ok(/setDeadline\(btn\.dataset\.key, btn\.dataset\.v/.test(src));
    assert.ok(/appliance: key/.test(src), "the request must carry the key");
});

check("nothing metered says what to do about it", () => {
    assert.ok(/Nothing is metered yet/.test(src));
    assert.ok(/Appliance Monitor device/.test(src), "must name the thing to add");
});

check("chips are only offered where a deadline means something", () => {
    // A machine mid-cycle, or one that has not run enough to be measured, has nothing to
    // schedule — offering it a deadline would be a button that does nothing useful.
    assert.ok(/state === "planned" \|\| a\.state === "no_plan"\) html \+= chipsFor/.test(src));
});

check("one option alone draws no card", () => {
    assert.equal(shape([{ start: new Date().toISOString(), grid_kwh: 0.2, cost_p: 5 }]), "");
});

/* ── house rules the page must keep ──────────────────────────────────────── */
check("the page loads the liveness gate and uses it before fetching", () => {
    assert.ok(/dashboards-gate\.js/.test(src));
    assert.ok(/DashGate.*check\(\)\s*===\s*"down"/.test(src),
              "must back off while the plugin restarts, or it wedges IWS for five minutes");
});

check("the page carries its own layout", () => {
    // dashboards-theme.css is VARIABLES ONLY — a page that links it and writes no layout
    // of its own renders essentially unstyled.
    assert.ok(/dashboards-theme\.css/.test(src));
    for (const cls of [".card", ".hero", ".main", ".note", ".loading", ".spinner"]) {
        assert.ok(src.includes(cls + "{") || src.includes(cls + " {"),
                  `missing house furniture ${cls}`);
    }
});

check("interpolated values are escaped", () => {
    assert.ok((src.match(/esc\(/g) || []).length > 8);
});

console.log(failures ? `\n${failures} FAILED` : "\nAll laundry page checks passed.");
process.exit(failures ? 1 : 0);
