// Filename:    test_page_batch_fixes.mjs
// Description: The page half of the 24-09-2026 bug batch. Where a fix is a
//              function it is run for real, lifted out of the shipped page;
//              where it is wiring (which helper a page calls) the source is
//              read with its comments stripped, so prose describing a rule can
//              never satisfy it.
//                - the Timeline chart paints the NEWEST request, not the last
//                  to arrive;
//                - room tiles show a disabled or errored device as out of
//                  service, not as its frozen state;
//                - the hub's energy diagram goes still when Sigen is not live;
//                - the meter's 24-hour chart survives the next poll;
//                - a crashed plugin reaches the System Health headline;
//                - Active leaves unreachable plugs out of "drawn now";
//                - no page forgets the key on the first refusal, and no page
//                  builds a still's address from the old public name.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_page_batch_fixes.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const code = f => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

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

console.log("\nTimeline chart: the newest request paints, whatever order replies land in");
{
    const stubs = {}, handlers = {};
    const stub = sel => ({ innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
        addEventListener: (t, fn) => { handlers[sel + ":" + t] = fn; }, classList: { toggle() {} }, dataset: {} });
    const el = { innerHTML: "", querySelector: sel => (stubs[sel] = stubs[sel] || stub(sel)), querySelectorAll: () => [] };
    const pending = [];
    const ctx = {
        console, Date, Promise, Object, JSON, Math, String, Number, isFinite, parseFloat,
        document: { documentElement: {} },
        getComputedStyle: () => ({ getPropertyValue: () => "#123456" }),
        DashUI: { esc: s => String(s == null ? "" : s), reducedMotion: () => true, message: async () => ({}),
                  poll: () => ({ stop() {} }), chartRender: () => ({ destroy() {} }) },
        pending,
    };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(`class IndigoAPI {
        async getDevices() { return [{ id: 7, name: "Hall Temp", states: { temperature: 1 } }]; }
        async getHistoryStates(id) { return { states: ["temperature"], types: {} }; }
        getHistory(id, st, h) { return new Promise(res => pending.push({ h, res })); }
    }`, ctx);
    vm.runInContext(read("timeline-views.js"), ctx);
    const view = ctx.TimelineViews.chart(el, () => {});
    const opening = view.open(7, "temperature");
    await new Promise(r => setTimeout(r, 10));
    pending.shift().res({ points: [{ t: 1, avg: 1, min: 1, max: 1 }] });   // the first 24 h draw
    await opening;
    const chip = h => ({ closest: () => ({ dataset: { h: String(h) } }) });
    handlers[".ranges:click"]({ target: chip(720) });                      // slow 30-day ask
    handlers[".ranges:click"]({ target: chip(24) });                       // then back to 24 h
    const slow = pending.find(p => p.h === 720), quick = pending.find(p => p.h === 24);
    quick.res({ points: [{ t: 1, avg: 24, min: 24, max: 24 }] });
    await new Promise(r => setTimeout(r, 5));
    slow.res({ points: [{ t: 1, avg: 720, min: 720, max: 720 }] });
    await new Promise(r => setTimeout(r, 5));
    check("the 24 h reply stays on screen after the older 30-day one lands",
          /Latest <b>24\.0<\/b>/.test(stubs[".stats"].innerHTML), stubs[".stats"].innerHTML);
}

console.log("\nroom tiles: a disabled or errored device is not shown as live");
{
    const src = read("room.html");
    const box = {
        console, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN, Object,
        setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
        document: { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} }, querySelectorAll: () => [] },
        DashUI: { esc: s => String(s == null ? "" : s), ago: () => "5m" },
        DashIcons: { svg: () => "" },
        escapeHtml: s => String(s == null ? "" : s), prettyLightName: s => s, prettyMotionName: s => s,
        fireSubtitle: () => null, lightSupportsColour: () => false, colorSwatchCss: () => "",
        COLOUR_PRESETS: {}, I: () => "", formatWhen: () => "5m ago", _motionWording: () => ({ on: "Motion", off: "Clear" }),
    };
    box.window = box;
    vm.createContext(box);
    vm.runInContext(read("dashboards-action.js"), box);
    vm.runInContext(read("dashboards-controls.js"), box);
    vm.runInContext(["renderLight", "renderEnvSensor", "renderAppliance", "renderMotion"].map(n => extractFn(src, n)).join("\n")
        + "\nglobalThis.__R = { renderLight, renderEnvSensor, renderAppliance, renderMotion };", box);
    const R = box.__R;
    const light = R.renderLight({ id: 3, name: "Lamp", class: "Relay", enabled: false, onState: true, states: {} });
    check("a disabled light does not read On", !/light-card on/.test(light) && /— · disabled/.test(light));
    check("and its switch cannot be pressed", /type="checkbox"[^>]*disabled/.test(light));
    const live = R.renderLight({ id: 4, name: "Lamp", class: "Relay", enabled: true, onState: true, states: {} });
    check("a live light still reads On with a working switch", /light-card on/.test(live) && !/type="checkbox"[^>]*disabled/.test(live));
    const env = R.renderEnvSensor({ id: 5, name: "Hall", enabled: false, states: { temperature: "19.5", humidity: "50" } });
    check("a disabled sensor shows no old temperature", !/19\.5/.test(env) && /disabled/.test(env) && / unknown/.test(env));
    const envErr = R.renderEnvSensor({ id: 6, name: "Hall", errorState: "timeout", states: { temperature: "19.5" } });
    check("nor does one in error", !/19\.5/.test(envErr) && /error/.test(envErr));
    const app = R.renderAppliance({ label: "Washer", monitorId: 8 }, [{ id: 8, enabled: false, onState: true, states: { powerWatts: "450" } }]);
    check("a disabled plug does not read On or its watts", !/>On</.test(app) && !/450/.test(app) && /disabled/.test(app));
}

console.log("\nhub energy diagram: still when Sigen is not live");
{
    const ctx = { Date, String, isFinite };
    vm.createContext(ctx);
    const src = read("index.html");
    vm.runInContext("const SIGEN_API_STALE_MS = 120000; const SIGEN_DEVICE_STALE_MS = 15 * 60000;\n"
        + extractFn(src, "energyFreshness") + "\nglobalThis.F = energyFreshness;", ctx);
    const now = Date.parse("2026-09-24T12:00:00");
    const recent = "2026-09-24 11:59:50";
    checkEq("live", ctx.F({ enabled: true, errorState: "", lastChanged: recent }, now - 5000, now), "");
    check("disabled", /disabled/.test(ctx.F({ enabled: false, lastChanged: recent }, now, now)));
    check("in error", /error/.test(ctx.F({ enabled: true, errorState: "comm", lastChanged: recent }, now, now)));
    check("SEM not answering for over two minutes", /not answering/.test(ctx.F({ enabled: true, lastChanged: recent }, now - 180000, now)));
    check("readings unchanged for twenty minutes", /stopped/.test(ctx.F({ enabled: true, lastChanged: "2026-09-24 11:40:00" }, 0, now)));
    const card = extractFn(src, "renderEnergyCard");
    check("the diagram is fed zeros when not live", /const z = notLive \? 0 : 1/.test(card) && /pv: pv \* z/.test(card));
}

console.log("\nmeter: the 24-hour chart survives the next poll");
{
    const src = read("meter.html");
    const els = {};
    const box = {
        console, JSON, Promise, String,
        DEV_ID: 5,
        document: { getElementById: id => els[id] || null },
        esc: s => String(s),
        sparkline: pts => `<svg data-n="${pts.length}"></svg>`,
        post: async () => ({ points: [1, 2, 3] }),
    };
    vm.createContext(box);
    const histDecl = src.match(/const _hist = \{[^}]*\};/);
    check("the drawn chart is kept in one place", !!histDecl);
    vm.runInContext((histDecl ? histDecl[0] : "") + "\n" + extractFn(src, "renderHistory") + "\n" + extractFn(src, "drawHistory")
        + "\nglobalThis.__M = { renderHistory, drawHistory };", box);
    els["hist-watts"] = { innerHTML: "" }; els["hist-volts"] = { innerHTML: "" }; els["hist-note"] = { textContent: "" };
    await box.__M.drawHistory({ meter: { sources: { watts: "power", volts: "voltage" } } });
    const again = box.__M.renderHistory(5, {});
    check("a later paint still carries the chart", /<svg data-n="3"><\/svg>/.test(again));
    check("and the pill no longer says loading", !/loading/.test(again) && /from the logger/.test(again));
}

console.log("\nSystem Health: a crashed plugin reaches the headline");
{
    const c = code("system-health.html");
    check("crashed plugins are pushed to the issues as bad", /if \(crashed\)\s*issues\.push\(\["bad"/.test(c));
}

console.log("\nActive: an unreachable plug is not in 'drawn now'");
{
    const c = code("active.html");
    check("the total sums reachable devices only", /liveOn\s*=\s*onDevices\.filter\(d => DashTile\.isReachable\(d\)\)/.test(c)
          && /totalW\s*=\s*liveOn\.reduce/.test(c));
    check("and a row says its watts are the last it sent", /last sent/.test(c));
}

console.log("\nwiring: one auth counter, one stills location, one stale rule");
{
    for (const page of ["room.html", "heating.html", "ecowitt.html", "wifi.html", "wifi-ap.html", "active.html"]) {
        const c = code(page);
        check(`${page} no longer forgets the key on the first refusal`,
              !/onAuthFailure\(\(\)\s*=>/.test(c) && /DashUI\.authStrikes\(\)/.test(c) && /auth\.ok\(\)/.test(c));
    }
    const hub = code("index.html");
    check("the hub's counter is the shared one", /DashUI\.authStrikes\(/.test(hub) && !/_authFails/.test(hub));
    for (const page of ["index.html", "cameras.html", "room.html"]) {
        const c = code(page);
        check(`${page} asks cameraStills where the pictures are`, /DashUI\.cameraStills\(\)/.test(c));
        check(`${page} never builds the old public name`,
              !/cfg\.(image|thumb)Pattern/.test(c) && !/"cam-\{host\}/.test(c) && !/`cam-\$\{/.test(c));
    }
    const room = code("room.html");
    check("room stills follow the link, use thumbnails, and pause on the reflector",
          /DashUI\.stillPollMs\(link\)/.test(room) && /thumbPattern/.test(room) && /DashUI\.idleGuard\(/.test(room));
    check("the hub uses the same poll rule", /DashUI\.stillPollMs\(link\)/.test(hub));
    check("the hub reads camera health through the tracker", /_camTracker\.feed\(/.test(hub) && /camService/.test(hub));
    check("so does the Cameras page", /_camTracker\.feed\(/.test(code("cameras.html")) && /camera service down/.test(code("cameras.html")));
    check("the hub weather card uses the shared units", /DashUI\.wx/.test(hub) && !/windUnit === "m\/s"/.test(hub)
          && !/rainRateMm/.test(hub) && !/toFixed\(0\) \+ " hPa"|\} hPa\$\{/.test(hub));
    check("Ecowitt uses the same rules, not a copy", /DashUI\.wx\.windMph/.test(code("ecowitt.html")) && !/WIND_TO_MPH/.test(code("ecowitt.html")));
    check("both WiFi pages use the one stale rule",
          /DashUI\.unifiStale\(/.test(code("wifi.html")) && /DashUI\.unifiStale\(/.test(code("wifi-ap.html")));
}

done();
