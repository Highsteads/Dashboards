// Filename:    test_hub_attention.mjs
// Description: The hub's "needs a look" chip (v3.35.0). Devices in error, low
//              batteries, log errors, offline cameras and Home Insights used to
//              be two chips and two cards spread down the page; they are one
//              chip in the hero now, opening a list in place. This drives the
//              REAL attentionItems() and renderAttention() from index.html,
//              and the shared DashUI.swapImage() that cross-fades the camera
//              strip, which replaced its live streams.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");

function extractFn(s, name) {
    const start = s.indexOf("function " + name + "(");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}

const ctx = { console };
vm.createContext(ctx);
vm.runInContext(extractFn(src, "attentionItems") + "\nglobalThis.attentionItems = attentionItems;", ctx);
const items = ctx.attentionItems;

console.log("\nnothing wrong");
checkEq("no sources, nothing listed", items({}).length, 0);
checkEq("zero counts list nothing", items({ devices: { errors: 0, lowBatt: 0 }, log: { errors: 0 }, cams: { a: { state: "ok" } } }).length, 0);

console.log("\nthe camera service itself (24-09-2026)");
{
    // A health summary that has stopped being written, or was written while
    // go2rtc was down, used to leave the chip silent through a full outage.
    const down = items({ camService: "down" });
    checkEq("go2rtc down is one red item", [down.length, down[0] && down[0].level], [1, "bad"]);
    check("and says the camera service is not running", /camera service is not running/.test(down[0].title));
    const stale = items({ camService: "stale" });
    checkEq("a frozen summary is amber, not all well", [stale.length, stale[0] && stale[0].level], [1, "warn"]);
    checkEq("so is no summary at all", items({ camService: "unknown" }).length, 1);
    checkEq("a live service adds nothing", items({ camService: null, cams: { a: { state: "ok" } } }).length, 0);
}

console.log("\neach source speaks in words");
{
    const got = items({ devices: { errors: 1, lowBatt: 3 } });
    checkEq("one error and the batteries", got.length, 2);
    checkEq("an error is listed first and red", got[0].level, "bad");
    checkEq("singular", got[0].title, "1 device is reporting an error");
    checkEq("plural batteries", got[1].title, "3 batteries are running low");
    checkEq("low batteries are amber", got[1].level, "warn");
    checkEq("they open System health", got[0].href, "system-health.html");
    const named = items({ devices: { errors: 1, lowBatt: 2, errNames: ["Hall Lamp"], lowNames: ["Porch PIR", "Loft PIR"] } });
    checkEq("one device in error is named", named[0].title, "Hall Lamp is reporting an error");
    checkEq("two low batteries are listed by name", named[1].detail, "Porch PIR and Loft PIR. Under 20%, or the device says so itself.");
    const one = items({ devices: { lowBatt: 1, lowNames: ["Porch PIR"] } });
    checkEq("one low battery is named", one[0].title, "The battery in Porch PIR is running low");
    const many = items({ devices: { errors: 4, errNames: ["a", "b", "c", "d"] } });
    checkEq("four are counted, not listed", many[0].title, "4 devices are reporting an error");
    checkEq("names that do not match the count are not trusted",
            items({ devices: { errors: 2, errNames: ["a"] } })[0].title, "2 devices are reporting an error");
}
{
    const got = items({ log: { errors: 2, rows: [
        { level: "error", muted: true, source: "Muted", message: "ignore me" },
        { level: "error", muted: false, source: "Z-Wave", message: "timeout" }] } });
    checkEq("log errors counted", got[0].title, "2 errors in the Indigo log");
    checkEq("the worst UNMUTED row is quoted", got[0].detail, "Z-Wave: timeout");
    checkEq("they open Alerts", got[0].href, "alerts.html");
}
{
    const one = items({ cams: { "cam1": { state: "offline" }, "cam2": { state: "retrying" } }, camNames: { cam1: "Drive" } });
    checkEq("only offline counts, never retrying", one.length, 1);
    checkEq("one camera is named", one[0].title, "The Drive camera is not answering");
    const two = items({ cams: { a: { state: "offline" }, b: { state: "offline" }, c: { state: "offline" } },
                        camNames: { a: "Drive", b: "Garden", c: "Patio" } });
    checkEq("several are counted", two[0].title, "3 cameras are not answering");
    checkEq("and joined with and", two[0].detail, "Drive, Garden and Patio.");
    checkEq("an unnamed camera shows its host", items({ cams: { h9: { state: "offline" } } })[0].title,
            "The h9 camera is not answering");
}
{
    const ins = { ok: true, insights: [{ level: "warn", title: "Hall battery falling", detail: "fast" },
                                       { level: "info", title: "Lounge warm", detail: "2 degrees up" }] };
    const got = items({ insights: ins });
    checkEq("insights listed", got.length, 2);
    checkEq("a warning insight is amber", got[0].level, "warn");
    checkEq("an unusual-but-fine insight is info", got[1].level, "info");
    checkEq("still building lists nothing", items({ insights: { ok: true, building: true, insights: [{ title: "x" }] } }).length, 0);
}
{
    const got = items({ devices: { errors: 1, lowBatt: 1 }, log: { errors: 1, rows: [] }, cams: { a: { state: "offline" } },
                        insights: { ok: true, insights: [{ level: "info", title: "i", detail: "" }] } });
    checkEq("worst first: every red before any amber",
            got.map(i => i.level).join(","), "bad,bad,bad,warn,info");
}

console.log("\nthe chip and its list");
{
    const els = {};
    const mk = (id) => ({ id, innerHTML: "", hidden: true, firstChild: null, attrs: {},
        className: "", listeners: {},
        setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, f) { this.listeners[t] = f; },
        insertBefore(n) { this.firstChild = n; } });
    els["pulse-row"] = mk("pulse-row"); els["attention-panel"] = mk("attention-panel");
    const c = {
        console, window: { CAMERA_CONFIG: {} },
        document: { getElementById: id => els[id] || null, createElement: () => mk("btn") },
        DashIcons: { svg: n => `<svg data-n="${n}"></svg>` },
        escapeAttr: s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"),
    };
    vm.createContext(c);
    vm.runInContext(`let INSIGHTS = null, LOGFEED = null, CAMHEALTH = null, CAMSERVICE = null, DEVCOUNTS = null, _attOpen = false, _attBtn = null;
        ${extractFn(src, "attentionItems")}
        ${extractFn(src, "renderAttention")}
        globalThis.set = (k, v) => { if (k === "dev") DEVCOUNTS = v; if (k === "log") LOGFEED = v; };
        globalThis.renderAttention = renderAttention;`, c);
    c.set("dev", { errors: 0, lowBatt: 0 });
    c.renderAttention();
    const btn = els["pulse-row"].firstChild;
    check("the chip leads the row", !!btn);
    check("it says All well, green", /All well/.test(btn.innerHTML) && /\bgood\b/.test(btn.className));
    check("the list starts closed", els["attention-panel"].hidden === true && btn.attrs["aria-expanded"] === "false");
    btn.listeners.click();
    check("a tap opens it", els["attention-panel"].hidden === false && btn.attrs["aria-expanded"] === "true");
    check("an all-clear says what was checked", /Nothing out of the ordinary in devices and batteries\./.test(els["attention-panel"].innerHTML),
          els["attention-panel"].innerHTML);
    c.set("dev", { errors: 2, lowBatt: 0 });
    c.set("log", { errors: 0 });
    c.renderAttention();
    check("the same button is reused, so focus survives the redraw", els["pulse-row"].firstChild === btn);
    check("it turns red and counts", /\bbad\b/.test(btn.className) && /1 thing needs a look/.test(btn.innerHTML), btn.innerHTML);
    check("the list stays open across a redraw", els["attention-panel"].hidden === false);
    check("rows link to where the detail is", /<a class="att-row bad" href="system-health.html">/.test(els["attention-panel"].innerHTML));
}

console.log("\nthe old cards and chips are gone");
check("no insights card", !/id="insights-card"/.test(src));
check("no log card", !/id="logwatch-card"/.test(src));
check("no separate low-battery or in-error chips", !/low battery`\)|in error`\)/.test(src));
check("camera health is polled, once a minute", /setInterval\(_refreshCamHealth, 60 \* 1000\)/.test(src));

console.log("\nDashUI.swapImage cross-fades, and falls back cleanly");
{
    const ui = fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8");
    const mkEl = (tag) => ({ tag, style: {}, children: [], parentNode: null, attrs: {}, listeners: {},
        isConnected: true, className: "",
        setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] || (k === "src" ? this.src : null); },
        addEventListener(t, f) { this.listeners[t] = f; },
        appendChild(n) { n.parentNode = this; this.children.push(n); },
        removeChild(n) { this.children = this.children.filter(x => x !== n); n.parentNode = null; } });
    let reduced = false, loadOk = true;
    const raf = [];
    const w = {
        document: { createElement: mkEl, documentElement: {} },
        matchMedia: () => ({ matches: reduced }),
        getComputedStyle: el => ({ position: el.pos || "static", objectFit: "cover" }),
        requestAnimationFrame: f => raf.push(f),
        setTimeout: (f) => 0,
        Image: function () { const self = this; setTimeout(() => (loadOk ? self.onload : self.onerror)(), 0);
                             Object.defineProperty(self, "src", { set(v) { self._s = v; }, get() { return self._s; } }); },
    };
    w.window = w;
    const c = { window: w, self: w, globalThis: w, console, navigator: {}, location: { hostname: "x" } };
    Object.assign(c, w);
    vm.createContext(c);
    vm.runInContext(ui, c);
    const DashUI = c.DashUI || w.DashUI;
    check("exported", typeof DashUI.swapImage === "function");
    const flush = () => { while (raf.length) raf.shift()(); };

    const parent = mkEl("div"); parent.pos = "relative";
    const img = mkEl("img"); img.src = "old.jpg"; img.attrs.src = "old.jpg"; img.parentElement = parent;
    const badge = mkEl("span"); parent.appendChild(badge);            // drawn after the picture
    img.insertAdjacentElement = (where, n) => { n.parentNode = parent; parent.children.unshift(n); };
    const p = DashUI.swapImage(img, "new.jpg");
    await new Promise(r => setTimeout(r, 5));
    checkEq("the next frame is laid over the old one", parent.children.length, 2);
    check("straight after the picture, under the badge", parent.children[1] === badge);
    checkEq("it starts transparent", parent.children[0].style.cssText.includes("opacity:0"), true);
    checkEq("the old frame is still showing", img.src, "old.jpg");
    const second = await DashUI.swapImage(img, "newer.jpg");
    checkEq("a frame arriving mid-fade is skipped, not stacked", second, false);
    flush();                                  // double rAF -> fade in
    checkEq("then fades in", parent.children[0].style.opacity, "1");
    parent.children[0].listeners.transitionend();
    checkEq("the base takes the new frame", img.src, "new.jpg");
    flush();                                  // overlay leaves one frame later
    checkEq("and the overlay goes, one <img> at rest", parent.children.length, 1);
    checkEq("resolves true", await p, true);

    reduced = true;
    const img2 = mkEl("img"); img2.src = "a.jpg"; img2.attrs.src = "a.jpg"; img2.parentElement = parent;
    checkEq("reduced motion swaps straight away", await DashUI.swapImage(img2, "b.jpg"), true);
    checkEq("with no overlay", parent.children.length, 1);
    checkEq("and the new frame showing", img2.src, "b.jpg");

    loadOk = false; reduced = false;
    let rejected = false;
    await DashUI.swapImage(img2, "missing.jpg").catch(() => { rejected = true; });
    check("a frame that will not load rejects, so the caller can fall back", rejected);
    checkEq("and the old frame stays", img2.src, "b.jpg");
}

done();
