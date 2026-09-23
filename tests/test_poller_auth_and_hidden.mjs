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
// Version:     1.1 (v3.28.0: refusals are reported inside _msg, over DashUI.message)
//
// Run: node tests/test_poller_auth_and_hidden.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

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

// ── rule 2: every poller goes through _msg, which reports a refusal ──────
// (v3.28.0: the refusal check moved INTO _msg, over DashUI.message.)
for (const name of POLLERS) {
    const body = extractFn(src, name);
    check(`${name} calls the plugin through _msg`, body.includes("_msg(") && !body.includes("fetch("));
}

// ── rule 3: what counts as a refusal, and the in-flight guard ───────────
{
    const run = async (err, opts = {}) => {
        const calls = [];
        let release;
        const ctx = vm.createContext({ console, Set,
            _onAuthFail: opts.boom ? () => { throw new Error("boom"); } : () => calls.push("authfail"),
            DashUI: { message: async () => {
                if (opts.hold) await new Promise(r => { release = r; });
                if (err) throw err;
                return { ok: true };
            } } });
        vm.runInContext("const _msgInflight = new Set();\n" + extractFn(src, "_msg"), ctx);
        let out, threw = false;
        try { out = await vm.runInContext('_msg("x")', ctx); } catch (_) { threw = true; }
        return { out, fired: calls.length, threw, ctx, release: () => release && release() };
    };
    const E = (status) => Object.assign(new Error("e"), { status, auth: status === 401 || status === 403 });

    let r = await run(E(401));
    check("401 is a refusal and is reported", r.out === null && r.fired === 1);
    r = await run(E(403));
    check("403 is a refusal and is reported", r.out === null && r.fired === 1);
    r = await run(E(500));
    check("500 is NOT a credential problem — must not clear the key", r.out === null && r.fired === 0);
    r = await run(E(404));
    check("404 is NOT a credential problem", r.out === null && r.fired === 0);
    r = await run(null);
    check("a good reply comes back", r.out && r.out.ok === true && r.fired === 0);
    r = await run(E(401), { boom: true });
    check("a throwing auth handler cannot break the poller", !r.threw && r.out === null);

    // One in flight per endpoint: a second ask while the first is out gets null.
    const calls = [];
    let release;
    const ctx = vm.createContext({ console, Set, _onAuthFail: () => {},
        DashUI: { message: async () => { calls.push(1); await new Promise(res => { release = res; }); return { ok: 1 }; } } });
    vm.runInContext("const _msgInflight = new Set();\n" + extractFn(src, "_msg"), ctx);
    const first = vm.runInContext('_msg("same")', ctx);
    const second = await vm.runInContext('_msg("same")', ctx);
    release();
    await first;
    check("a second ask while the first is in flight is skipped", second === null && calls.length === 1);
}

done();
