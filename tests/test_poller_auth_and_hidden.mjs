// Filename:    test_poller_auth_and_hidden.mjs
// Description: Contract test for the hub's four side pollers — sigen, string
//              hours, insights and log watch.
//
//              WHY THIS EXISTS
//              They fetch directly rather than through IndigoAPI, so they sat
//              outside the auth-failure counter. A browser holding a stale key
//              asked again every 30 s for ever and every refusal wrote a
//              "Web Server Warning: access denied" line — 120 an hour, per open
//              tab, for a key that was never going to start working. Two of
//              them also had no hidden-tab gate, so a BACKGROUND tab kept
//              polling, which is how the log filled up while nobody was
//              looking at the page.
//
//              THE RULES
//              1. Every poller stands down when the tab is hidden.
//              2. Every poller reports a 401/403 so three of them trip the
//                 existing re-pair flow, rather than warning for ever.
//              3. A refusal is 401/403 only — a 500 or a 404 is a server
//                 problem, not a credential one, and must NOT clear the key.
// Author:      CliveS & Claude Opus 5
// Date:        28-08-2026
// Version:     1.0
//
// Run: node tests/test_poller_auth_and_hidden.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
const src = fs.readFileSync(PAGE, "utf8");

function extractFn(s, name) {
    const start = s.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unbalanced: " + name);
}

let fails = 0;
const check = (what, ok) => { console.log((ok ? "  ok   " : "  FAIL ") + what); if (!ok) fails++; };

console.log("hub side pollers — auth refusal and hidden-tab gates");

const POLLERS = ["_refreshSigen", "_refreshStringHours",
                 "_refreshInsights", "_refreshLogWatch"];

// ── rule 1: every poller stands down in a background tab ────────────────
for (const name of POLLERS) {
    const body = extractFn(src, name);
    // The gate must come before any fetch, or the request is already away.
    const gateAt  = body.indexOf("document.hidden");
    const fetchAt = body.indexOf("fetch(");
    check(`${name} stands down when the tab is hidden`,
          gateAt > -1 && (fetchAt === -1 || gateAt < fetchAt));
}

// ── rule 2: every poller reports a refusal ──────────────────────────────
for (const name of POLLERS) {
    check(`${name} reports a 401/403 to the auth counter`,
          extractFn(src, name).includes("_authRefused("));
}

// ── rule 3: what counts as a refusal ────────────────────────────────────
{
    const calls = [];
    const ctx = vm.createContext({ console, _onAuthFail: () => calls.push("authfail") });
    vm.runInContext(extractFn(src, "_authRefused"), ctx);
    const refused = st => { calls.length = 0;
        const out = vm.runInContext(`_authRefused(${JSON.stringify({ status: st })})`, ctx);
        return { out, fired: calls.length }; };

    check("401 is a refusal and is reported", refused(401).out === true && refused(401).fired === 1);
    check("403 is a refusal and is reported", refused(403).out === true && refused(403).fired === 1);
    check("500 is NOT a credential problem — must not clear the key",
          refused(500).out === false && refused(500).fired === 0);
    check("404 is NOT a credential problem",
          refused(404).out === false && refused(404).fired === 0);
    check("200 is not a refusal", refused(200).out === false && refused(200).fired === 0);
    calls.length = 0;
    check("a missing response is handled, not thrown on",
          vm.runInContext("_authRefused(null)", ctx) === false && calls.length === 0);

    // A poller must never be taken down by the reporting itself.
    const boom = vm.createContext({ console, _onAuthFail: () => { throw new Error("boom"); } });
    vm.runInContext(extractFn(src, "_authRefused"), boom);
    let threw = false;
    try { vm.runInContext('_authRefused({status:401})', boom); } catch (_) { threw = true; }
    check("a throwing auth handler cannot break the poller", !threw);
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
