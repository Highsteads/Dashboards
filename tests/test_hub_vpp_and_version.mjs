// Filename:    test_hub_vpp_and_version.mjs
// Description: Node contract test for the v2.66.0 hub changes — the VPP chip
//              that replaced the grid-carbon one, and the running version
//              shown beside the date. Extracts the REAL renderHousePulse()
//              and renderHero() out of the shipped index.html, so this locks
//              what ships rather than a copy of it.
//
//              Why these want tests at all: three separate faults today were
//              render paths that had never executed. The alert bar printed raw
//              SVG, the chip row sat on the title, and the API published an
//              empty event window — all of them only reachable during a VPP
//              event, and there had not been one for six weeks. The VPP chip
//              and row below are exactly that shape again: code that is
//              invisible on ~364 days a year. Reasoning about them is not
//              enough; they need to be executed.
//
//              Pinned here:
//                • the chip appears ONLY while announced or running, and is
//                  absent when idle (the row must stay short the rest of the
//                  time — that is the whole reason it replaced a permanent
//                  chip);
//                • the carbon chip is really gone;
//                • the event window is escaped, not interpolated raw;
//                • the version renders beside the date, and its ABSENCE
//                  renders a clean date rather than a dangling separator —
//                  the same dangling-colon fault the API had.
// Author:      CliveS & Claude Fable 5
// Date:        30-07-2026
// Version:     1.0
//
// Run: node tests/test_hub_vpp_and_version.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
const src  = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in index.html`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// ── stub DOM ───────────────────────────────────────────────────────────────
const els = {};
function el(id) {
    if (!els[id]) els[id] = { id, innerHTML: "", textContent: "", style: {} };
    return els[id];
}
globalThis.document = { getElementById: (id) => el(id) };
globalThis.window = globalThis;
globalThis.DashIcons = { svg: (n) => `<svg data-n="${n}"></svg>` };

const helpers = `
    function escapeAttr(s) {
        return String(s == null ? "" : s)
            .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;");
    }
    // v2.73.0: renderHousePulse uses the page's module-level asBool — supply
    // it FROM SOURCE so a drift there fails here (the v2.62.0 harness trap:
    // a swallowed ReferenceError, not this loud one, is the dangerous form).
    ${(src.match(/const asBool = [^\n]+\n/) || [""])[0]}
`;
// v2.95.3: the pulse reads the Sigen payload through _sigen(), which ages it
// out at 120 s — supplied FROM SOURCE, same rule as asBool above.
new Function(helpers + grab("renderHousePulse") + grab("renderHero") + grab("_sigen") +
             "globalThis.renderHousePulse = renderHousePulse;" +
             "globalThis.renderHero = renderHero;" +
             "globalThis._sigen = _sigen;")();

let failures = 0;
function check(label, cond, detail) {
    if (cond) console.log(`  ok   ${label}`);
    else { console.log(`  FAIL ${label}${detail ? "  — " + detail : ""}`); failures++; }
}

const DEVICES = [
    { id: 1, name: "Presence - Clive", deviceTypeId: "unifiClient",
      states: { presence: "home" }, errorState: "" },
];
function pulse(vpp) {
    els["pulse-row"] = { id: "pulse-row", innerHTML: "", style: {} };
    window.__SIGEN_DATA = vpp ? { vpp } : null;
    window.__SIGEN_AT = Date.now();          // fresh — an aged payload renders nothing
    renderHousePulse(DEVICES);
    return els["pulse-row"].innerHTML;
}

// 1. Idle — no VPP chip at all. The row has to stay short when nothing is on.
let html = pulse({ state: "idle", active: false, event_str: "" });
check("idle shows no VPP chip", !/VPP/.test(html), html.slice(0, 120));
check("idle still shows presence", html.includes("Clive"));

// 2. Announced.
html = pulse({ state: "announced", active: false, event_str: "19:00-20:00" });
check("announced shows a VPP chip", html.includes("VPP announced"));
check("announced shows the window", html.includes("19:00-20:00"));
check("announced links to the energy page", html.includes('href="energy.html"'));

// 3. Running.
html = pulse({ state: "active", active: true, event_str: "19:00-20:00" });
check("running shows a VPP chip", html.includes("VPP running"));
check("running is styled as warn", /pulse-chip warn/.test(html));

// 4. No window text → no dangling separator (the API's own bug, in reverse).
html = pulse({ state: "announced", active: false, event_str: "" });
check("missing window leaves no trailing separator", !/announced\s*·\s*</.test(html), html.slice(0, 160));

// 5. The window is API-supplied, so it must be escaped — in BOTH branches.
//    Checking only one is how a mutation that unescaped the other survived the
//    first version of this test: the announced and running branches build their
//    chip separately, so each needs its own assertion.
const NASTY = '<img src=x onerror=1>';
html = pulse({ state: "announced", active: false, event_str: NASTY });
check("event window escaped (announced)", !html.includes("<img"), html.slice(0, 160));
html = pulse({ state: "active", active: true, event_str: NASTY });
check("event window escaped (running)", !html.includes("<img"), html.slice(0, 160));

// 6. Missing Sigen data entirely — must not throw, must not show a chip.
html = pulse(null);
check("absent Sigen data shows no VPP chip", !/VPP/.test(html));

// 7. The carbon chip really is gone.
check("carbon chip removed from the source", !src.includes("g CO₂"));
check("carbonAdvisor poll removed from the source", !src.includes("carbonAdvisor"));

// 8. Version beside the date.
function hero(build) {
    els["hero-date"] = { id: "hero-date", textContent: "", style: {} };
    els["hero-greet"] = { id: "hero-greet", textContent: "", style: {} };
    els["hero-sun"] = { id: "hero-sun", innerHTML: "", textContent: "", style: {} };
    globalThis.DASHBOARDS_BUILD = build;
    window.__OWM_DATA = null;
    renderHero();
    return els["hero-date"].textContent;
}
let d = hero("2.66.0");
check("version renders beside the date", d.includes("· v2.66.0"), d);
check("date itself survives", /\d/.test(d) && d.length > 10, d);

d = hero("");
check("absent version leaves a clean date", !d.includes("·") && !d.includes("v"), d);

console.log(failures === 0
    ? "\ntest_hub_vpp_and_version.mjs: all checks passed"
    : `\ntest_hub_vpp_and_version.mjs: ${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);

// 5. An aged payload (v2.95.3) — a VPP chip painted from a two-minute-old
// payload the page could no longer refresh is a false alarm.
{
    els["pulse-row"] = { id: "pulse-row", innerHTML: "", style: {} };
    window.__SIGEN_DATA = { vpp: { active: true, event_str: "16:00-17:00" } };
    window.__SIGEN_AT = Date.now() - 5 * 60 * 1000;
    renderHousePulse(DEVICES);
    check("a payload older than 120 s shows no VPP chip", !els["pulse-row"].innerHTML.includes("VPP"));
}
if (failures) { console.log(`\n${failures} check(s) failed`); process.exit(1); }
