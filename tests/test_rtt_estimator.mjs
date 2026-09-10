// Filename:    test_rtt_estimator.mjs
// Description: Contract test for the estimator inside DashUI.probeRtt — which
//              of several timing samples is taken as the reading for the link.
//
//              WHY THIS EXISTS
//              CliveS's iPhone and his laptop sat on the same LAN, feet apart,
//              on the same build of the same server. The laptop showed the four
//              camera tiles on the hub. The phone showed none, and said nothing
//              about it, because the hub had quietly classed it as remote and
//              stripped five regions off the page.
//
//              The cause was the estimator, not the threshold. probeRtt took
//              the MEDIAN of three fetches. iOS parks the wi-fi radio between
//              requests, so a phone pays a wake-up on samples a laptop never
//              pays — and two slow samples out of three drag the median over
//              the bar while the floor sits comfortably under it.
//
//              Latency noise is one-sided. A sleeping radio, a busy CPU or a
//              retried frame can only ever make a request arrive LATER; nothing
//              makes one arrive sooner than the path allows. So the FASTEST
//              sample is the honest reading of the link and the median mostly
//              reports how noisy the device is.
//
//              test_link_class.mjs cannot catch this: it gives all three
//              samples the same value, where min and median agree by
//              construction. Every case below needs samples that DIFFER.
// Author:      CliveS & Claude Opus 5
// Date:        30-08-2026
// Version:     1.0
//
// Run: node tests/test_rtt_estimator.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboards-ui.js");
const src = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in dashboards-ui.js`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

const RTT_HOME_MS = Number(/RTT_HOME_MS\s*=\s*(\d+)/.exec(src)[1]);

// Guard the guard: if probeRtt is ever renamed or reshaped, this file must
// fail loudly rather than pass over nothing. Same reasoning as the missing
// module-constant note in test_link_class.mjs.
const PROBE = grab("probeRtt");
if (!/Math\.min/.test(PROBE)) {
    console.error("FAIL  probeRtt no longer takes the minimum of its samples.");
    console.error("      The median is what hid CliveS's cameras on his phone.");
    process.exit(1);
}

// samples: one RTT per fetch, in the order the probe makes them.
function makeSandbox(samples) {
    const store = {};
    let i = 0;
    const box = {
        store,
        sessionStorage: {
            getItem: k => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = v; },
        },
        root: { location: { hostname: "192.168.1.10" }, performance: null },
        NOW: 0,
        console,
    };
    box.Date = { now: () => box.NOW };
    box.Math = Math;
    // A REAL promise, not a hand-rolled thenable. A thenable returned from a
    // .then callback is ADOPTED by the engine, which calls its .then a second
    // time with the resolve function — so a fake that advances the clock on
    // every .then burns two samples per fetch and reports the wrong one. That
    // is invisible while every sample is identical, which is exactly why the
    // harness in test_link_class.mjs never showed it.
    box.fetch = () => {
        box.NOW += samples[Math.min(i++, samples.length - 1)];
        return Promise.resolve({ ok: true });
    };
    box.RTT_HOME_MS = RTT_HOME_MS;
    box.RTT_PROBE_KEY = "dash_link_rtt";
    box.RTT_CACHE_MS = Number(/RTT_CACHE_MS\s*=\s*(\d+)/.exec(src)[1]);
    return box;
}

const CODE = ["var _now = function () { return Date.now(); };",   // the shared clock guard probeRtt uses (v2.99.0)
              grab("_cachedRtt"),
              PROBE.replace("root.performance && performance.now()", "false"),
              grab("measuredClass"), grab("linkClass")].join("\n");

async function probe(samples) {
    const box = makeSandbox(samples);
    vm.createContext(box);
    vm.runInContext(CODE + "\nvar __r = probeRtt();", box);
    return await box.__r;
}
async function classify(samples) {
    const box = makeSandbox(samples);
    vm.createContext(box);
    vm.runInContext(CODE + "\nvar __r = measuredClass();", box);
    return await box.__r;
}

const CASES = [
    // samples,              expect ms, expect class, why
    [[30, 60, 200],                 30, "home",
     "THE BUG — phone on the LAN whose radio woke slowly twice; median 60 said remote"],
    [[12, 15, 900],                 12, "home",
     "one stalled request must not decide the verdict"],
    [[900, 14, 800],                14, "home",
     "the fast sample counts wherever in the order it lands"],
    [[21, 21, 21],                  21, "home",
     "his real home wi-fi reading, steady — unchanged from the median"],
    [[116, 130, 140],              116, "vpn",
     "Tailscale in the same building: even the floor is over the bar"],
    [[245, 260, 900],              245, "vpn",
     "5G through Tailscale — no sample comes near local"],
    [[9999, 9999, 9999],          9999, "vpn",
     "every fetch failed; unreachable must never read as local"],
    [[9999, 9999, 40],              40, "home",
     "two failures and one clean local sample is still a local link"],
    [[RTT_HOME_MS, 500, 500],       RTT_HOME_MS, "home",
     "exactly at the threshold counts as local"],
    [[RTT_HOME_MS + 1, 500, 500],   RTT_HOME_MS + 1, "vpn",
     "one millisecond over is remote"],
];

let pass = 0, fail = 0;
console.log(`\nthreshold read from source: ${RTT_HOME_MS} ms\n`);
for (const [samples, wantMs, wantCls, why] of CASES) {
    const gotMs = await probe(samples);
    const gotCls = await classify(samples);
    const ok = gotMs === wantMs && gotCls === wantCls;
    ok ? pass++ : fail++;
    console.log(`${ok ? "ok  " : "FAIL"}  [${String(samples).padEnd(18)}] -> ${String(gotMs).padStart(4)} ms / ${gotCls.padEnd(4)}  ${why}`);
    if (!ok) console.log(`      expected ${wantMs} ms / ${wantCls}`);
}
console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
