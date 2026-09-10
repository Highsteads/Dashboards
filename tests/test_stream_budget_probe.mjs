// Filename:    test_stream_budget_probe.mjs
// Description: Contract test for DashUI.probeBandwidth / streamBudget — how
//              many hub camera tiles may stream (v2.99.0).
//
//              WHY THIS EXISTS
//              The probe fetched a 44 KB file ONCE. A home link delivers that
//              in about 3 ms, so the reading was one scheduler hiccup wide,
//              and the FIRST fetch on a page is the cold one: measured on this
//              LAN, back to back, 6.9 Mbit/s then 92, 126, 117, 110. A single
//              cold sample therefore reported a fifteenth of the truth, the
//              budget floored at zero tiles, and a phone in the same room as
//              the cameras showed four 3-second stills.
//
//              Interference here is ONE-SIDED — a cold connection, slow start,
//              the page's own boot fetches and a sleeping radio can only make
//              a reading worse — so the honest estimator is a warm-up followed
//              by the BEST of several samples, never the mean or the median.
// Author:      CliveS & Claude Opus 5
// Date:        02-09-2026
// Version:     1.0
//
// Run: node tests/test_stream_budget_probe.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");
const uiSrc  = fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8");
const hubSrc = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");

let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

// A window whose fetch answers with a fixed byte count, taking `msFor(n)` for
// the nth call. A real Promise throughout — a hand-rolled thenable gets
// ADOPTED by the engine and called a second time, which silently doubles the
// samples (the trap that hid an estimator bug in this very file before).
function makeWindow({ sizes = { "chart.umd.min.js": 205222, "dashboards-ui.js": 43981 },
                      msFor = () => 10, rttMs = 5, missing = [] } = {}) {
    // Starts at a real-looking timestamp, not 0: performance.now() is falsy at
    // 0, and a harness that starts there exercises a clock no page ever has.
    let clock = 1000, calls = [];
    const win = {
        location: { hostname: "192.168.1.10" },
        document: null,
        performance: { now: () => clock },
        Date, Math, JSON,
        setTimeout, clearTimeout, setInterval, clearInterval,
        sessionStorage: { _v: {}, getItem(k) { return this._v[k] ?? null; },
                          setItem(k, v) { this._v[k] = String(v); },
                          removeItem(k) { delete this._v[k]; } },
        fetch(url) {
            const file = String(url).split("?")[0];
            const warm = String(url).includes("bwwarm");
            calls.push({ file, warm });
            if (missing.includes(file)) return Promise.resolve({ ok: false, status: 404 });
            const ms = msFor(calls.length, warm);
            clock += ms;                      // the transfer takes this long
            const bytes = sizes[file] || 1000;
            return Promise.resolve({
                ok: true, status: 200,
                arrayBuffer: () => Promise.resolve({ byteLength: bytes }),
            });
        },
    };
    win.window = win; win.self = win;
    vm.createContext(win);
    vm.runInContext(uiSrc, win, { filename: "dashboards-ui.js" });
    // probeRtt does its own fetching; pin it so these cases test throughput only.
    win.DashUI.probeRtt = () => Promise.resolve(rttMs);
    return { win, calls: () => calls };
}

console.log("\nthe estimator takes the BEST sample, not the first or the average");
{
    // Cold first sample, fast afterwards — exactly what was measured live.
    const { win, calls } = makeWindow({ msFor: (n, warm) => (warm ? 60 : (n === 2 ? 250 : 16)) });
    const kbps = await win.DashUI.probeBandwidth();
    const mbit = kbps / 1000;
    check("a slow first sample does not decide it", mbit > 40,
          `got ${mbit.toFixed(1)} Mbit/s — the cold sample alone would say ~6`);
    // config.js is probeRtt's own probe — the bandwidth fetches are the rest.
    const c = calls().filter(x => x.file !== "config.js");
    check("a warm-up runs first and its timing is discarded",
          c[0].warm === true && c.length === 3,
          "the cold fetch is the one that was wrong before");
    check("then exactly two timed samples", c.filter(x => !x.warm).length === 2);
    check("the big asset is preferred", c.every(x => x.file === "chart.umd.min.js"));
}

console.log("\nand a genuinely slow link still reads slow");
{
    const { win } = makeWindow({ msFor: () => 1400 });   // 205 KB in 1.4 s
    const kbps = await win.DashUI.probeBandwidth();
    check("~1.2 Mbit/s link measures as such", kbps / 1000 < 3,
          `got ${(kbps / 1000).toFixed(2)} Mbit/s`);
    const budget = await win.DashUI.streamBudget();
    check("which buys no live tiles at all", budget === 0,
          "an MJPEG stream on a link that cannot drain it never catches up");
}

console.log("\nfast links buy the whole strip; the correction cannot invent capacity");
{
    const { win } = makeWindow({ msFor: (n, warm) => (warm ? 20 : 16) });   // ~100 Mbit/s
    check("four tiles are affordable at ~100 Mbit/s", await win.DashUI.streamBudget() >= 4);
}
{
    // Round trip ≈ the whole elapsed time: the subtraction must stay bounded.
    const { win } = makeWindow({ msFor: () => 3, rttMs: 2.9 });
    const mbit = (await win.DashUI.probeBandwidth()) / 1000;
    check("an RTT as long as the transfer cannot inflate it past 2.5x", mbit <= 205222 * 8 / 3 / 1000 * 2.5,
          `got ${mbit.toFixed(0)} Mbit/s against ${(205222 * 8 / 3 / 1000).toFixed(0)} observed`);
}

console.log("\ndegrading");
{
    const { win, calls } = makeWindow({ missing: ["chart.umd.min.js"] });
    await win.DashUI.probeBandwidth();
    check("falls back to the small file when the big one is absent",
          calls().some(c => c.file === "dashboards-ui.js"),
          "another install may not ship the chart library");
}
{
    const { win } = makeWindow({ missing: ["chart.umd.min.js", "dashboards-ui.js"] });
    check("nothing fetchable means no live tiles, not a crash",
          await win.DashUI.streamBudget() === 0);
}
{
    const { win } = makeWindow();
    win.location.hostname = "myhouse.indigodomo.net";
    check("the reflector is zero without measuring at all",
          await win.DashUI.streamBudget() === 0,
          "the stream port is not fronted by it, so no measurement can help");
}

console.log("\nthe hub spends the whole budget");
{
    check("every tile goes live once the budget covers them all",
          /const liveAll\s*=\s*budget >= hosts\.length;/.test(hubSrc));
    check("and the strip is re-rendered when the measurement lands",
          /_liveBudget = n;[\s\S]{0,120}renderCamerasOnce\(\)/.test(hubSrc),
          "without this the page keeps its conservative first answer for ever");
    check("a fresh measurement is taken on return to the tab",
          /DashUI\.forgetBw\(\)[\s\S]{0,120}_applyStreamBudget\(\)/.test(hubSrc));
}

process.exit(failed ? 1 : 0);
