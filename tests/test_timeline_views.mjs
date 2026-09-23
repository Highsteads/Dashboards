// Filename:    test_timeline_views.mjs
// Description: Timeline as the one history page (v3.33.0): the four tabs, the
//              Nights tab hiding without its script, the old page names
//              forwarding to the right view, and the Nights view drawing EVERY
//              room the script watches (the old Presence page named two rooms
//              of one house and drew nothing else).
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(DIR, f), "utf8");
const tl = read("timeline.html");

console.log("\ntabs");
for (const v of ["day", "nights", "chart", "diary"]) {
    check(`a ${v} tab and panel`, tl.includes(`data-view="${v}"`) && tl.includes(`id="view-${v}"`));
}
check("the views file is loaded", tl.includes('<script src="timeline-views.js"></script>'));

console.log("\nthe Nights tab needs Presence_Watch.py");
{
    const src = tl.slice(tl.indexOf("function viewAvailable("));
    const fnSrc = src.slice(0, src.indexOf("\n}\n") + 2);
    const avail = cfg => { const ctx = { window: { INDIGO_CONFIG: cfg } }; vm.createContext(ctx);
        vm.runInContext(fnSrc + "\nglobalThis.__a = viewAvailable;", ctx); return ctx.__a; };
    check("shown when the script is installed", avail({ scripts: { presence: true } })("nights") === true);
    check("hidden when it is not", avail({ scripts: { presence: false } })("nights") === false);
    check("shown when config.js does not say (an older plugin)", avail({})("nights") === true);
    check("the other tabs never hide", avail({ scripts: { presence: false } })("chart") === true);
}

console.log("\nthe old page names forward to the right view");
{
    const target = f => (/location\.replace\("([^"]+)"/.exec(read(f)) || [])[1];
    check("presence.html -> Nights", target("presence.html") === "timeline.html?view=nights");
    check("activity.html -> Diary", target("activity.html") === "timeline.html?view=diary");
    check("history.html -> Chart", target("history.html") === "timeline.html?view=chart");
    check("history.html carries a ?device= across", /location\.search\.slice\(1\)/.test(read("history.html")));
    check("each also works without scripts", ["presence.html", "activity.html", "history.html"]
        .every(f => /http-equiv="refresh"/.test(read(f))));
}

console.log("\nNights draws every room the script watches");
{
    // Just enough DOM: each selector gets one stable stub element.
    const stubs = {};
    const stub = () => ({ innerHTML: "", textContent: "", hidden: false, disabled: false,
                          addEventListener() {}, dataset: {} });
    const el = { innerHTML: "", querySelector: sel => (stubs[sel] = stubs[sel] || stub()), querySelectorAll: () => [] };
    const room = (title) => ({
        title, window: { start: "20:00", end: "08:00", startMinOfDay: 1200, spanMin: 720 },
        sensorOrder: ["a"], sensorLabels: { a: "Wall" }, sensorStatus: {},
        byDate: { "2026-09-22": { live: false, stats: { a: { hasData: true, occMin: 60, occPct: 8, transitions: 3, longestHold: 40 } },
            tracks: { a: [[10, 70]] }, both: { green: [[10, 70]], amber: [] },
            summary: { firstSeenMin: 10, lastClearMin: 70, occMin: 60, occPct: 8, bothPresent: false, reportingCount: 1, sensorCount: 1 } } },
    });
    const DATA = { ok: true, dates: ["2026-09-22"], labels: { "2026-09-22": "Last night" }, generatedLocal: "2026-09-23 07:00:00",
                   rooms: { study: room("Study"), bedroom_2: room("Bedroom 2"), lounge: room("Lounge") } };
    const statuses = [];
    const ctx = {
        console, Date, Promise, Object, JSON, Math, String, Number,
        window: {}, document: { documentElement: {} },
        DashUI: { esc: s => String(s == null ? "" : s).replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`),
                  message: async (name) => (name === "presenceData" ? DATA : {}),
                  poll: (fn) => { fn(); return { stop() {} }; } },
    };
    ctx.window = ctx; ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(read("timeline-views.js"), ctx);
    const view = ctx.TimelineViews.nights(el, t => statuses.push(t));
    view.show();
    await new Promise(r => setTimeout(r, 20));
    const rooms = stubs[".n-rooms"].innerHTML;
    check("all three rooms are drawn", ["Study", "Bedroom 2", "Lounge"].every(t => rooms.includes(t)), rooms.slice(0, 120));
    check("the status line says when it was updated", statuses.includes("Updated 07:00"), JSON.stringify(statuses));
    check("no hard-coded room names are left", !/living_room|bedroom_1/.test(read("timeline-views.js")));
}

console.log("\nChart opens a device from a deep link");
{
    // dashboard.js declares IndigoAPI as a top-level CLASS: shared between
    // classic scripts, but never a property of window. The first build read
    // window.IndigoAPI and the view died silently. Declared the same way here.
    const stubs = {};
    const stub = () => ({ innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
                          addEventListener() {}, classList: { toggle() {} }, dataset: {} });
    const el = { innerHTML: "", querySelector: sel => (stubs[sel] = stubs[sel] || stub()), querySelectorAll: () => [] };
    const statuses = [], calls = [];
    const ctx = {
        console, Date, Promise, Object, JSON, Math, String, Number, isFinite, parseFloat,
        document: { documentElement: {} },
        getComputedStyle: () => ({ getPropertyValue: () => "#123456" }),
        DashUI: { esc: s => String(s == null ? "" : s), reducedMotion: () => true, message: async () => ({}), poll: () => ({ stop() {} }) },
        Chart: function () { this.destroy = () => {}; },
        calls,
    };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(`class IndigoAPI {
        async getDevices() { calls.push("devices"); return [{ id: 7, name: "Hall Temp", states: { temperature: 1 } }]; }
        async getHistoryStates(id) { calls.push("states:" + id); return { states: ["temperature"], types: {} }; }
        async getHistory(id, st, h) { calls.push("history:" + id + ":" + st + ":" + h);
            return { points: [{ t: 1, avg: 19.5, min: 19, max: 20 }, { t: 2, avg: 20.25, min: 20, max: 21 }] }; }
    }`, ctx);
    vm.runInContext(read("timeline-views.js"), ctx);
    const view = ctx.TimelineViews.chart(el, t => statuses.push(t));
    await view.open(7, "temperature");
    await new Promise(r => setTimeout(r, 20));
    check("it asks for the device's states and its history", calls.includes("states:7") && calls.includes("history:7:temperature:24"), JSON.stringify(calls));
    check("the stats line shows the latest value", /Latest <b>20\.3<\/b>/.test(stubs[".stats"].innerHTML), stubs[".stats"].innerHTML);
    check("the status names the device", statuses.includes("Hall Temp"), JSON.stringify(statuses));
}

done();
