// Filename:    test_review_small_pages.mjs
// Description: Small page faults from the 25/26-Nov-2026 review (3.73.5):
//                - on then off inside four seconds raised a false
//                  "No confirmation - check it" on a switch that had done both;
//                - the Rooms menu said "1 lights" and "1 windows", and a
//                  failed read of the room list read "No rooms found";
//                - the hub showed a days-old forecast file as today's.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_small_pages.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
function extractFn(s, name) {
    const start = s.search(new RegExp("function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unbalanced: " + name);
}

console.log("a quick on then off is judged once, on the last press");
{
    const timers = [], notes = [];
    const box = { console, Promise, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN,
        setTimeout: (fn, ms) => { timers.push(fn); return timers.length; }, clearTimeout: () => {},
        setInterval: () => 0, clearInterval: () => {},
        document: { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} }, querySelectorAll: () => [] },
        DashUI: { esc: s => String(s), ago: () => "" }, DashIcons: { svg: () => "" } };
    box.window = box; box.globalThis = box;
    vm.createContext(box);
    vm.runInContext(read("dashboards-action.js"), box);
    vm.runInContext(read("dashboards-controls.js"), box);
    box.DashAction.note = (key, phase, text) => notes.push(text);
    let real = false;                                   // what the lamp really is
    box.DashTile.bind({ turnOn: async () => { real = true; }, turnOff: async () => { real = false; },
                        getDevice: async id => ({ id, onState: real }) });
    const el = { dataset: { id: "5" }, checked: true, disabled: false };
    await box.DashTile.toggle(el);                      // on
    el.checked = false;
    await box.DashTile.toggle(el);                      // off, two seconds later
    while (timers.length) { await timers.shift()(); await new Promise(r => setImmediate(r)); }
    checkEq("no false alarm", notes.filter(n => /No confirmation/.test(n)), []);
    check("the switch is left as the lamp really is", el.checked === false);
    // A press that really is swallowed is still caught.
    notes.length = 0; el.checked = true;
    box.DashTile.bind({ turnOn: async () => {}, turnOff: async () => {}, getDevice: async id => ({ id, onState: false }) });
    await box.DashTile.toggle(el);
    while (timers.length) { await timers.shift()(); await new Promise(r => setImmediate(r)); }
    check("a swallowed press is still reported, and the switch put back", notes.some(n => /No confirmation/.test(n)) && el.checked === false);
}

console.log("\nthe Rooms menu");
{
    const menu = read("menu.html");
    const ctx = vm.createContext({});
    vm.runInContext(extractFn(menu, "countWords"), ctx);
    checkEq("one of a thing", [vm.runInContext('countWords(1, "light")', ctx), vm.runInContext('countWords(1, "window")', ctx)], ["1 light", "1 window"]);
    checkEq("several", vm.runInContext('countWords(3, "light")', ctx), "3 lights");
    check("the tiles use it", /countWords\(\(s\.lights\)\.length, "light"\)/.test(menu) && /countWords\(\(s\.windows\)\.length, "window"\)/.test(menu));
    check("a failed read of the room list says so", /Could not load the room list/.test(menu) && /failed = "the server answered " \+ r\.status/.test(menu));
}

console.log("\nthe hub's forecast");
{
    const hub = read("index.html");
    const ctx = vm.createContext({});
    vm.runInContext("const WEATHER_MAX_AGE_S = 3 * 3600;\n" + extractFn(hub, "freshWeather") + "\nglobalThis.f = freshWeather;", ctx);
    const now = 1795650000000;
    checkEq("an hour-old file is shown", ctx.f({ _writeTs: now / 1000 - 3600, today_max: 7 }, now).today_max, 7);
    checkEq("a day-old file is not", ctx.f({ _writeTs: now / 1000 - 86400, today_max: 7 }, now), null);
    checkEq("a file with no stamp (an older plugin) is shown as before", ctx.f({ today_max: 7 }, now).today_max, 7);
    checkEq("rubbish is nothing", ctx.f("x", now), null);
    check("the hub reads the file through it", /window\.__OWM_DATA = freshWeather\(await r\.json\(\), Date\.now\(\)\);/.test(hub));
}

done();
