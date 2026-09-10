// Filename:    test_freshness_indicator.mjs
// Description: Contract test for the "not updating" status line on mains.html
//              and meter.html.
//
//              WHY THIS EXISTS
//              Both pages could render once and then stop for ever without
//              saying so. The error handler only speaks when #content is
//              EMPTY, so a dead poll left plausible readings on screen with
//              nothing but a quietly frozen clock to show for it — on
//              08-Sep-2026 neither CliveS nor I could tell from the page
//              whether it was still updating, and the answer took five polls
//              of instrumented measurement to settle. The indicator turns
//              that into something you can see.
//
//              These tests pin the threshold, the wording, the singulars, and
//              the two rules that make it trustworthy: it must be driven by
//              its OWN timer (a poll that has died cannot report that it has
//              died), and only a poll that actually returned data may clear it.
// Author:      CliveS & Claude Opus 5
// Date:        09-09-2026
// Version:     1.0
//
// Run: node tests/test_freshness_indicator.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");

let pass = 0, fail = 0;
const check = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + detail : ""}`);
};

function fnSource(code, name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name}`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

for (const page of ["mains.html", "meter.html"]) {
    console.log(`\n${page}`);
    const src = fs.readFileSync(path.join(PAGES, page), "utf8");
    // Strip comments so a rule can never be satisfied by prose describing it.
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

    const ctx = { Math };
    vm.createContext(ctx);
    vm.runInContext("const STALE_AFTER_MS = 90000;\n"
        + fnSource(code, "agoWords") + "\n" + fnSource(code, "freshness"), ctx);
    const freshness = (ms) => vm.runInContext(`freshness(${ms})`, ctx);
    const words = (ms) => vm.runInContext(`agoWords(${ms})`, ctx);

    // ── the threshold ──
    check(freshness(0).stale === false, "a reading that just arrived is not stale");
    check(freshness(89000).stale === false, "89 s is not yet stale");
    check(freshness(90000).stale === false, "90 s exactly is not stale (the bar is ABOVE it)");
    check(freshness(90001).stale === true, "past 90 s it says so");
    check(freshness(600000).stale === true, "ten minutes is stale");

    // Nothing has arrived yet: the loading card is already saying that, and an
    // amber "not updating" over a page that never loaded is its own wrong answer.
    check(freshness(undefined).stale === false, "no reading yet is never reported as stale");
    check(freshness(NaN).stale === false, "an unusable age is never reported as stale");
    check(freshness(-5).stale === false, "a clock that stepped backwards is not stale");

    // ── the wording ──
    check(freshness(0).text.includes("every 30s"), "fresh shows the cadence");
    check(freshness(240000).text === "&middot; not updating for 4 minutes",
          "stale says how long", JSON.stringify(freshness(240000).text));
    check(!freshness(240000).text.includes("every 30s"),
          "stale does NOT still claim to be updating every 30s");

    // ── singulars, on every branch ──
    check(words(1000) === "1 second", "1 second", words(1000));
    check(words(45000) === "45 seconds", "45 seconds", words(45000));
    check(words(60000) === "60 seconds", "under 90 s stays in seconds", words(60000));
    check(words(120000) === "2 minutes", "2 minutes", words(120000));
    check(words(3540000) === "59 minutes", "59 minutes", words(3540000));
    check(words(3600000) === "1 hour", "1 hour, not 1 hours", words(3600000));
    check(words(7200000) === "2 hours", "2 hours", words(7200000));

    // ── the two rules that make it trustworthy ──
    // 1. Its own timer. A poll that has died cannot report that it has died.
    check(/setInterval\(markFreshness,\s*\d+\)/.test(code),
          "it is driven by its own timer, not by the poll");
    // 2. Only a poll that returned data may clear it.
    const setTs = fnSource(code, "setTs");
    check(/_lastGood\s*=\s*Date\.now\(\)/.test(setTs),
          "only setTs — called on a successful poll — resets the clock");
    const others = code.split("_lastGood = Date.now()").length - 1;
    check(others === 1, "nothing else anywhere resets it", `found ${others}`);

    // 3. The markup it needs must exist, or the whole thing is a silent no-op.
    check(/id="freshness"/.test(src), "the status line carries id=freshness");
    check(/id="cadence"/.test(src), "the cadence text carries id=cadence");
    check(/\.topbar-status\.stale\{/.test(src), "the stale style is defined");
    check(/\.topbar-status\.stale \.ts::before\{[^}]*animation:none/.test(src),
          "the live dot stops pulsing when stale");

    // 4. A failed poll leaves evidence, or the next report is as undiagnosable
    //    as the one that prompted this file.
    check(/console\.error\(/.test(code), "a failed poll is logged");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
