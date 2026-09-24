// Filename:    test_tap_guard.mjs
// Description: Contract test for the tap guard and press feedback in
//              dashboards-ui.js (v3.24.0). A finger that brushes a tile while
//              scrolling must not switch anything; a clean tap must get
//              through and flash; a tile that does nothing (a reading, a
//              moving door, a plain card) must never flash; mouse and
//              keyboard clicks are never judged.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0
//
// Run: node tests/test_tap_guard.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UI = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                     "Resources", "static", "pages", "dashboards-ui.js");
const src = fs.readFileSync(UI, "utf8");

// ── a fake element: just enough of matches/closest/classList ──────────
function el({ tag = "BUTTON", cls = [], attrs = {}, disabled = false, field = false } = {}) {
    const set = new Set(cls);
    const e = {
        tagName: tag, disabled,
        classList: { add: c => set.add(c), remove: c => set.delete(c), contains: c => set.has(c) },
        hasAttribute: k => k in attrs,
        getAttribute: k => (k in attrs ? attrs[k] : null),
        matches(sel) {
            return sel.split(",").map(x => x.trim()).some(x =>
                x === ":disabled" ? disabled
                : x.startsWith("[aria-disabled") ? attrs["aria-disabled"] === "true"
                : x.startsWith(".") ? set.has(x.slice(1)) : false);
        },
        // The field selector is the only one naming textarea; everything else
        // (the press selector) resolves to the element itself.
        closest: sel => (sel.includes("textarea") ? (field ? e : null) : e),
    };
    return e;
}

// ── a fake page: capture listeners in order, stopImmediatePropagation honoured
function makeWindow() {
    const listeners = {};
    let now = 1_000_000;
    const doc = {
        readyState: "complete",
        addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
        createElement: () => ({ set textContent(v) { doc._css = v; } }),
        head: { appendChild() {} },
        querySelector: () => null, getElementById: () => null,
        documentElement: { style: {} },
    };
    const FakeDate = { now: () => now };
    const win = { document: doc, location: { hostname: "192.168.1.10" }, INDIGO_CONFIG: {},
                  setInterval, clearInterval, setTimeout, clearTimeout, Date: FakeDate, Math,
                  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
                  matchMedia: () => ({ matches: false, addEventListener() {} }),
                  getComputedStyle: () => ({ getPropertyValue: () => "", cursor: "pointer" }) };
    win.window = win; win.self = win;
    vm.createContext(win);
    vm.runInContext(src, win, { filename: "dashboards-ui.js" });
    function fire(type, ev = {}) {
        let stopped = false;
        const e = Object.assign({ defaultPrevented: false,
            preventDefault() { this.defaultPrevented = true; },
            stopImmediatePropagation() { stopped = true; } }, ev);
        for (const fn of listeners[type] || []) { if (stopped) break; fn(e); }
        return { prevented: e.defaultPrevented, stopped };
    }
    return { win, doc, fire, tick: ms => { now += ms; } };
}

// ── the pure decision ────────────────────────────────────────────────
{
    const { win } = makeWindow();
    const U = win.DashUI;
    const base = { travel: 0, scrolledWhileDown: false, downAt: 10_000, glideAt: -Infinity };
    check("a still finger is a tap", U.isScrollTouch(base) === false);
    check("travel past the slop is a scroll", U.isScrollTouch({ ...base, travel: U.TAP_SLOP_PX + 1 }) === true);
    check("travel within the slop is still a tap", U.isScrollTouch({ ...base, travel: U.TAP_SLOP_PX - 1 }) === false);
    check("any scroll while down is a scroll", U.isScrollTouch({ ...base, scrolledWhileDown: true }) === true);
    check("landing on a gliding page is a scroll", U.isScrollTouch({ ...base, glideAt: 9_900 }) === true);
    check("landing well after the glide is a tap", U.isScrollTouch({ ...base, glideAt: 9_000 }) === false);

    check("a switch tile is actionable", U.isActionable(el({ cls: ["fav-tile"] })) === true);
    check("a reading tile is not", U.isActionable(el({ cls: ["fav-tile", "fav-reading"] })) === false);
    check("a moving door tile is not", U.isActionable(el({ cls: ["fav-tile", "fav-door", "fav-door-moving"] })) === false);
    check("a disabled button is not", U.isActionable(el({ disabled: true })) === false);
    check("a link is", U.isActionable(el({ tag: "A", cls: ["fav-tile", "fav-roomlink"], attrs: { href: "room.html" } })) === true);
    check("a plain card with a pointer cursor is not", U.isActionable(el({ tag: "DIV", cls: ["dash-card"] })) === false);
    check("a div with an onclick is", U.isActionable(el({ tag: "DIV", cls: ["camera-card"], attrs: { onclick: "x()" } })) === true);
}

// ── the wired listeners ──────────────────────────────────────────────
function tap(page, target, { travel = 0, type = "touch" } = {}) {
    page.fire("pointerdown", { pointerType: type, clientX: 100, clientY: 200, target });
    if (travel) page.fire("pointermove", { clientX: 100, clientY: 200 + travel, target });
    page.tick(80);
    page.fire("pointerup", { target });
    return page.fire("click", { target });
}

{
    const page = makeWindow();
    const t = el({ cls: ["fav-tile"] });
    const r = tap(page, t);
    check("a clean tap reaches the page", r.prevented === false && r.stopped === false);
    check("and flashes", t.classList.contains("dash-pressed"));
}
{
    const page = makeWindow();
    const t = el({ cls: ["fav-tile"] });
    const r = tap(page, t, { travel: 40 });
    check("a brushing drag is stopped before the page sees it", r.prevented && r.stopped);
    check("and does not flash", !t.classList.contains("dash-pressed"));
}
{
    const page = makeWindow();
    const t = el({ cls: ["fav-tile", "fav-reading"] });
    tap(page, t);
    check("a reading tile never flashes", !t.classList.contains("dash-pressed"));
}
{
    const page = makeWindow();
    const t = el({ cls: ["fav-tile"] });
    // A swipe: the browser takes it for a scroll and the page glides on.
    page.fire("pointerdown", { pointerType: "touch", clientX: 100, clientY: 400, target: t });
    page.fire("pointercancel", {});
    for (let i = 0; i < 5; i++) { page.tick(40); page.fire("scroll", {}); }
    page.tick(60);                                    // finger lands mid-glide
    const r = tap(page, t);
    check("the touch that stops a glide does not switch anything", r.prevented && r.stopped);
    page.tick(1000);
    const r2 = tap(page, t);
    check("a tap once the page has settled goes through", !r2.prevented && !r2.stopped);
}
{
    const page = makeWindow();
    const t = el({ cls: ["fav-tile"] });
    page.fire("pointerdown", { pointerType: "mouse", clientX: 0, clientY: 0, target: t });
    page.fire("pointermove", { clientX: 0, clientY: 90, target: t });
    const r = page.fire("click", { target: t });
    check("a mouse click is never judged", !r.prevented && !r.stopped);
    const k = page.fire("click", { target: t });
    check("a keyboard click (no press) is never judged", !k.prevented && !k.stopped);
}
{
    // lows batch [55]: a swipe left its cancelled press behind, and a keyboard
    // click (detail 0, no pointerdown) inside five seconds was judged against
    // it and silently cancelled.
    const page = makeWindow();
    const t = el({ cls: ["fav-tile"] });
    page.fire("pointerdown", { pointerType: "touch", clientX: 100, clientY: 400, target: t });
    page.fire("pointercancel", {});
    page.tick(1500);
    const k = page.fire("click", { target: t, detail: 0 });
    check("a keyboard click after a swipe is not cancelled", !k.prevented && !k.stopped);
    page.fire("pointerdown", { pointerType: "touch", clientX: 100, clientY: 400, target: t });
    page.fire("scroll", {});
    const k2 = page.fire("click", { target: t, detail: 0 });
    check("a click with detail 0 is never judged, even mid-press", !k2.prevented && !k2.stopped);
}
{
    const page = makeWindow();
    const f = el({ tag: "INPUT", field: true });
    const r = tap(page, f, { travel: 40 });
    check("a slider drag is left alone", !r.prevented && !r.stopped);
}
{
    // Two tiles tapped in quick succession: each must clear on its own. A
    // single shared timer cancelled the first tile's clear and left it stuck.
    const page = makeWindow();
    const a = el({ cls: ["fav-tile"] }), b = el({ cls: ["fav-tile"] });
    tap(page, a); tap(page, b);
    await new Promise(r => setTimeout(r, 300));
    check("a quick second tap does not leave the first tile stuck",
          !a.classList.contains("dash-pressed") && !b.classList.contains("dash-pressed"));
}
{
    const page = makeWindow();
    check("small buttons' shrink is off on touch screens too",
          /@media \(hover: none\)\{[^}]*\.setpoint-btn:active|@media \(hover: none\)\{[^}]*\.ctrl-btn:active/.test(page.doc._css || ""));
    check("tile shrink is switched off on touch screens",
          /@media \(hover: none\)\{[^}]*\.fav-tile:active[^}]*\{transform:none!important;/.test(page.doc._css || ""));
}

done();
