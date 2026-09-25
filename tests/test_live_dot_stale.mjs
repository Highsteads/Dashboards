// Filename:    test_live_dot_stale.mjs
// Description: The top bar's "· live" can say it is not (3.46.0). The hub,
//              Energy, Cost and System pages printed "· live" or "every 30s"
//              beside a pulsing green dot as fixed text, so a page whose data
//              had stopped still claimed to be live. DashUI.liveness turns the
//              bar amber and its words to "out of date" when nothing has been
//              marked for staleAfterMs, runs on its own timer, ignores time
//              spent hidden, and puts the page's own words back on the next
//              mark. The four pages must use it, and mark it only on data.
// Author:      CliveS & Claude Opus 5.5
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_live_dot_stale.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const UI = fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8");
const CSS = fs.readFileSync(path.join(PAGES, "dashboards-chrome.css"), "utf8");

function fakeBar(freshHtml) {
    const classes = new Set();
    const cad = { innerHTML: freshHtml };
    return {
        cad,
        classList: { toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
                     contains: (c) => classes.has(c) },
        querySelector: (sel) => (sel === ".live-cadence" ? cad : null),
    };
}

function world() {
    const listeners = {};
    const timers = [];
    let t = 1_000_000;
    const doc = {
        hidden: false, readyState: "complete",
        addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
        removeEventListener() {},
        querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
        createElement: () => ({ set textContent(_v) {}, style: {} }),
        head: { appendChild: () => {} },
        documentElement: { style: {} }, body: { classList: { add() {}, remove() {} } },
    };
    const win = { document: doc, location: { hostname: "192.168.1.10" }, INDIGO_CONFIG: {},
                  setInterval: (fn) => { timers.push(fn); return timers.length; }, clearInterval() {},
                  setTimeout, clearTimeout, Date, Math,
                  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
                  matchMedia: () => ({ matches: false, addEventListener() {} }),
                  getComputedStyle: () => ({ getPropertyValue: () => "" }),
                  requestAnimationFrame: (f) => setTimeout(f, 0), performance: { now: () => Date.now() } };
    win.window = win; win.self = win;
    vm.createContext(win);
    vm.runInContext(UI, win, { filename: "dashboards-ui.js" });
    return {
        win, doc,
        now: () => t,
        advance: (ms) => { t += ms; timers.forEach(fn => fn()); },
        fire: (ev) => (listeners[ev] || []).forEach(fn => fn()),
    };
}

// ── the pure rule ──
{
    const w = world();
    const st = (a, s) => w.win.DashUI.livenessState(a, s).stale;
    check("fresh at 0 ms", st(0, 30000) === false);
    check("the window itself is not stale", st(30000, 30000) === false);
    check("past the window is stale", st(30001, 30000) === true);
    check("no age yet is never stale", st(undefined, 30000) === false && st(NaN, 30000) === false);
    check("a clock that stepped back is not stale", st(-5, 30000) === false);
}

// ── the helper on a bar ──
{
    const w = world();
    const bar = fakeBar("&middot; live");
    const live = w.win.DashUI.liveness({ staleAfterMs: 30000, bars: [bar], now: w.now });
    w.advance(120000);
    check("before the first mark nothing turns amber", !bar.classList.contains("stale")
          && bar.cad.innerHTML === "&middot; live");
    live.mark();
    check("a mark is live", !bar.classList.contains("stale"));
    w.advance(29000);
    check("inside the window it stays live", !bar.classList.contains("stale"));
    w.advance(2000);
    check("its OWN timer turns it amber with no poll at all", bar.classList.contains("stale"));
    check("the words say so", bar.cad.innerHTML === "&middot; out of date", bar.cad.innerHTML);
    check("and no longer claim to be live", !/live/.test(bar.cad.innerHTML));
    live.mark();
    check("the next mark clears the amber at once", !bar.classList.contains("stale"));
    check("and puts the page's own words back", bar.cad.innerHTML === "&middot; live", bar.cad.innerHTML);

    // hidden time does not count
    w.doc.hidden = true;
    w.advance(600000);
    check("a hidden page is never painted amber", !bar.classList.contains("stale"));
    w.doc.hidden = false;
    w.fire("visibilitychange");
    check("coming back does not flash amber before the first poll", !bar.classList.contains("stale"));
    w.advance(31000);
    check("but a poll that stays dead after coming back is caught", bar.classList.contains("stale"));
}

// ── the stylesheet ──
check("the stale bar is amber", /\.topbar-status\.stale\s*\{[^}]*var\(--warn\)/.test(CSS));
check("the stale dot stops pulsing",
      /\.topbar-status\.stale \.ts::before\s*\{[^}]*animation:\s*none/.test(CSS));
check("reduced motion gets a still dot, not a 0.01 ms flicker",
      /prefers-reduced-motion: reduce\)\s*\{\s*:where\(header\.topbar\) \.topbar-status \.ts::before\s*\{\s*animation:\s*none/.test(CSS));

// ── the four pages ──
for (const [page, window] of [["index.html", 30000], ["energy.html", 30000],
                              ["cost.html", 90000], ["system-health.html", 90000]]) {
    const src = fs.readFileSync(path.join(PAGES, page), "utf8");
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    check(`${page}: its status bar is watched (data-live + .live-cadence)`,
          /class="topbar-status" data-live>[\s\S]{0,120}<span class="live-cadence">/.test(src));
    check(`${page}: no fixed "· live" left outside the cadence span`,
          !/<\/span><\/span>\s*(·|&middot;)\s*(live|every)/.test(src));
    check(`${page}: it uses the shared helper with a ${window / 1000} s window`,
          new RegExp(`DashUI\\.liveness\\(\\{\\s*staleAfterMs:\\s*${window}\\s*\\}\\)`).test(code));
    const marks = code.split("_liveness.mark()").length - 1;
    check(`${page}: marked in exactly one place`, marks === 1, `found ${marks}`);
}
// Marked on data only: next to the line that stamps the time from a good reply.
{
    const energy = fs.readFileSync(path.join(PAGES, "energy.html"), "utf8");
    check("energy: an error reply returns before the mark",
          /if \(d\.error\) \{ setText\('ts', 'Error: ' \+ d\.error\); return; \}[\s\S]{0,120}_liveness\.mark\(\)/.test(energy));
    const cost = fs.readFileSync(path.join(PAGES, "cost.html"), "utf8");
    check("cost: an error reply returns before the mark",
          /if \(d && d\.error\) \{ setText\('ts', 'Error: ' \+ d\.error\); return; \}[\s\S]{0,120}_liveness\.mark\(\)/.test(cost));
    const hub = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");
    check("hub: the footer line is watched too",
          /<span data-live>Updated <span id="ts-bot">/.test(hub));
}

done();
