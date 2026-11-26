// Filename:    test_review_batch3.mjs
// Description: Third group from the 25/26-Nov-2026 review (3.73.6):
//                - the Air page showed a disabled purifier as online, with
//                  working controls, and a filter life that had never been
//                  read as "0%, time to order a new filter";
//                - its connection error was painted over by a 5-second timer,
//                  a slower Day reply drew under the Week chip, and any
//                  failure read "Nothing recorded yet";
//                - one poll with three refused device reads counted as three
//                  strikes and wiped the browser's stored key;
//                - a disabled or errored UniFi controller left every access
//                  point reading as live;
//                - the room and Active pages never said they had stopped
//                  updating ("Next refresh 0s" over old states).
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch3.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

console.log("Air page: what the purifier's tile believes");
{
    const ctx = { console, window: {}, Math, Date, JSON, String, Number, isFinite, isNaN, parseFloat, parseInt };
    vm.createContext(ctx);
    vm.runInContext(read("levoit-view.js"), ctx);
    const V = ctx.window.LevoitView;
    const dev = (st, extra) => Object.assign({ id: 1, name: "Purifier", enabled: true, errorState: "", onState: true,
        states: Object.assign({ deviceOnline: true, mode: "auto", airQuality: 1, pm25: 3, filterLife: 81, fanLevel: 2,
                                lastUpdate: "2026-11-26 00:10:00" }, st) }, extra);
    const live = V.view(dev({}));
    checkEq("a live purifier reads as before", [live.online, live.pm25, live.filter, live.filterLow, live.why], [true, 3, 81, false, ""]);
    const off = V.view(dev({}, { enabled: false }));
    checkEq("a disabled purifier is not online, and says why", [off.online, off.band, off.why], [false, "unknown", "Disabled in Indigo"]);
    const never = V.view(dev({ filterLife: 0, pm25: 0, lastUpdate: "" }));
    checkEq("a purifier never read has no filter figure and no PM2.5", [never.filter, never.filterLow, never.pm25], [null, false, null]);
    checkEq("a blank filter life is no figure", V.view(dev({ filterLife: "" })).filter, null);
    const worn = V.view(dev({ filterLife: 4 }));
    checkEq("a filter that really is low still says so", [worn.filter, worn.filterLow], [4, true]);
    const zero = V.view(dev({ filterLife: 0 }));
    checkEq("a filter read as 0 after a real reading is 0", [zero.filter, zero.filterLow], [0, true]);
    const page = read("levoit.html");
    check("the page draws a dash for no figure, and no warning", /v\.filter === null \? "—" : v\.filter \+ "%"/.test(page));
    check("the 5-second timer leaves a connection error alone", /if \(!_errShown && window\.__lastDevices\) render\(window\.__lastDevices\);/.test(page));
    check("a slower reply for another range is dropped", /if \(mine !== _histReq\[id\] \|\| hours !== \(_hours\[id\] \|\| 24\)\) return;/.test(page));
    check("a chart that could not be loaded says so", /Could not load the chart/.test(page));
    check("a disabled purifier's line says so", /v\.why/.test(page));
}

console.log("\none refused poll is one strike");
{
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, INDIGO_CONFIG: { apiKey: "k" } };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    let t = 1000000;
    const trips = [];
    const a = win.DashUI.authStrikes({ onTrip: () => trips.push(1), now: () => t });
    const bad = { status: 401 };
    a.fail(bad); a.fail(bad); a.fail(bad);                 // one poll, three device reads refused together
    checkEq("three refusals in the same moment count once", [a.count(), trips.length], [1, 0]);
    t += 3000; a.fail(bad);
    t += 3000;
    checkEq("the third refused POLL trips", [a.fail(bad), trips.length], ["tripped", 1]);
    t += 3000; a.fail(bad); a.ok(); t += 3000; a.fail(bad);
    checkEq("a good poll still starts the count again", a.count(), 1);
}

console.log("\nWi-Fi: a controller that cannot be believed makes its access points stale");
{
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, INDIGO_CONFIG: {} };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    const U = win.DashUI.unifiStale;
    const ap = { enabled: true, errorState: "", states: {} };
    const ctl = extra => Object.assign({ enabled: true, errorState: "", states: { status: "Connected" } }, extra);
    checkEq("a connected controller, a live AP", U(ap, ctl({})), false);
    checkEq("a disabled controller", U(ap, ctl({ enabled: false })), true);
    checkEq("a controller in error", U(ap, ctl({ errorState: "timeout" })), true);
    checkEq("a controller that is not Connected", U(ap, ctl({ states: { status: "Sign-in refused" } })), true);
    checkEq("a disabled AP", U({ enabled: false, states: {} }, ctl({})), true);
}

console.log("\nroom and Active pages say when they have stopped updating");
for (const f of ["room.html", "active.html"]) {
    const s = read(f);
    check(`${f}: the top status bar is a live bar`, /<span class="topbar-status" data-live>Updated <span id="ts">—<\/span> <span class="live-cadence">· Next refresh <span id="cdwn">—<\/span>s<\/span><\/span>/.test(s));
    check(`${f}: it is marked on each good poll, and only there`, /const _liveness = DashUI\.liveness\(\{ staleAfterMs: 15000 \}\);/.test(s)
          && (s.split("_liveness.mark()").length - 1) === 1 && /function markRefreshed\(\) \{\s*_lastUpdate = Date\.now\(\);\s*_liveness\.mark\(\);/.test(s));
}

done();
