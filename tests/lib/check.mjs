// Filename:    tests/lib/check.mjs
// Description: The one pass/fail helper for the node tests (23-09-2026). Until
//              then 41 test files each carried their own copy, in eighteen
//              shapes, with their own counters and their own exit line. Lives
//              in tests/lib/ so the tests/*.mjs glob in run.sh and CI never
//              runs it as a test of its own.
//
//              Every shape a file used is here, named for its argument order,
//              so a file imports the one it was written against and its call
//              sites stay as they were. A file ends with done().
//
//              Belt and braces: if a file forgets done(), or throws before it,
//              the exit handler still turns a failure into exit code 1. A
//              check that fails must never leave the gate green.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import process from "node:process";

let passed = 0;
let failed = 0;

function record(ok, label, detail) {
    if (ok) {
        passed++;
        console.log(`  ok   ${label}`);
    } else {
        failed++;
        console.log(`  FAIL ${label}${detail ? "  — " + detail : ""}`);
    }
    return !!ok;
}

/** check(label, ok, detail?) */
export function check(label, ok, detail) {
    return record(ok, label, detail);
}

/** checkOk(ok, label, detail?) — the condition first. */
export function checkOk(ok, label, detail) {
    return record(ok, label, detail === undefined || detail === "" ? "" :
        typeof detail === "string" ? detail : JSON.stringify(detail));
}

/** checkEq(label, got, want) — equal as JSON. */
export function checkEq(label, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    return record(ok, label, ok ? "" : `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

/** checkIs(label, got, want) — strictly equal. */
export function checkIs(label, got, want) {
    const ok = got === want;
    return record(ok, label, ok ? "" : `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

/** checkFn(label, fn) — passes when fn returns without throwing. */
export function checkFn(label, fn) {
    try {
        fn();
        return record(true, label);
    } catch (e) {
        return record(false, label, e && e.message ? e.message : String(e));
    }
}

/** How many checks have passed and failed so far. */
export function counts() {
    return { passed, failed };
}

/** Print the summary and exit: 1 on any failure, else 0. */
export function done(title) {
    const head = title ? `${title}: ` : "";
    console.log(failed ? `\n${head}${failed} of ${passed + failed} FAILED`
                       : `\n${head}all ${passed} passed`);
    process.exit(failed ? 1 : 0);
}

process.on("exit", (code) => {
    if (failed && code === 0) process.exitCode = 1;
});
