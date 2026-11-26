// Filename:    test_review_batch5.mjs
// Description: Fifth group from the 25/26-Nov-2026 review (3.73.8):
//                - the Flow page's HOME list counted a meter that was
//                  disabled or not answering at its last known watts, and its
//                  outdoor temperature came from a sensor in the same state;
//                - the Flow page never said it had stopped updating;
//                - the Savings page counted a day with no price as nothing
//                  and never said so, and wrote a loss as "saved".
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch5.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

console.log("Flow: only meters that can be believed");
{
    const ctx = { console, window: {}, Math, Date, JSON, String, Number, isFinite, isNaN, parseFloat, parseInt, encodeURIComponent, decodeURIComponent };
    vm.createContext(ctx);
    vm.runInContext(read("sigen-flow-bridge.js"), ctx);
    const B = ctx.window.SigenFlowBridge._t;
    const plug = (id, name, extra, st) => Object.assign({ id, name, enabled: true, errorState: "", pluginId: "x",
        states: Object.assign({ powerWatts: 100 }, st) }, extra);
    const loads = B.homeLoads([plug(1, "Kettle"), plug(2, "Washer", {}, { deviceOnline: false }),
                               plug(3, "Lamp", { errorState: "offline" }), plug(4, "Fan", { enabled: false }),
                               plug(5, "Heater", {}, { availability: "offline" }), plug(6, "Pump", {}, { connected: "false" }),
                               plug(7, "Dryer", {}, { deviceOnline: "True", availability: "online" })]);
    checkEq("a meter off the network, in error or disabled is left out", Array.from(loads, l => l.name), ["Dryer", "Kettle"]);
    const wx = (extra, st) => Object.assign({ id: 9, name: "Outdoor", enabled: true, errorState: "",
        states: Object.assign({ temperature: 3.6, humidity: 86, dewPoint: 1.5 }, st) }, extra);
    checkEq("a live weather sensor gives the outdoor temperature", B.outdoorC([wx({})], null), 3.6);
    checkEq("a disabled one gives none", B.outdoorC([wx({ enabled: false })], null), null);
    checkEq("nor does one in error", B.outdoorC([wx({ errorState: "timeout" })], null), null);
}

console.log("\nFlow: the page says when it has stopped updating");
{
    const flow = read("flow.html");
    check("the status bar is a live bar", /<span class="topbar-status" data-live>Updated <span id="ts">—<\/span><span class="live-cadence"><\/span><\/span>/.test(flow));
    check("it is marked only when a reading arrives", /const _liveness = DashUI\.liveness\(\{ staleAfterMs: 30000 \}\);/.test(flow)
          && (flow.split("_liveness.mark()").length - 1) === 1 && /say\(""\);\s*_liveness\.mark\(\);\s*feed\(\);/.test(flow));
    check("a reading that stops coming is said, not only the first failure", /No new reading from SigenEnergyManager/.test(flow));
}

console.log("\nSavings: a day with no price, and a loss");
{
    const ctx = { console, Math, Date, JSON, String, Number, isFinite, isNaN, parseFloat, parseInt };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(read("savings-view.js"), ctx);
    const T = ctx.SavingsView._t;
    const d = { first: "2026-03-27", last: "2026-11-24" };
    const some = T.notesCard(d, { unpricedDays: 3 });
    check("unpriced days are said", /Three days could not be priced/.test(some) && /counted as nothing/.test(some), some.replace(/<[^>]+>/g, " ").slice(0, 300));
    check("one day reads as one", /One day could not be priced/.test(T.notesCard(d, { unpricedDays: 1 })));
    check("none says nothing", !/could not be priced/.test(T.notesCard(d, { unpricedDays: 0 })));
    checkEq("a saving reads as before", T.savedWords(12.34), ["£12.34", "saved"]);
    checkEq("a loss is not called a saving", T.savedWords(-12.34), ["£12.34", "more spent than"]);
    checkEq("nothing known", T.savedWords(null)[0], "—");
    const view = read("savings-view.js");
    check("the hero uses those words", /savedWords\(p\.saved\)/.test(view));
    check("the poorest day says which way it went", /worst\.saved < 0 \? 'cost ' \+ gbp\(worst\.saved\) \+ ' more'/.test(view));
}

console.log("\nTimeline: today's view stops at now");
{
    const tl = read("timeline.html");
    const grab = name => { const i = tl.indexOf("function " + name + "("); let d = 0;
        for (let j = tl.indexOf("{", i); j < tl.length; j++) { if (tl[j] === "{") d++; else if (tl[j] === "}" && --d === 0) return tl.slice(i, j + 1); } };
    const ctx = vm.createContext({ console });
    vm.runInContext("var selDate = new Date(); var DAY = { energy: { points: [{ m: 0, soc: 40 }, { m: 60, soc: 50 }] } };" +
        "function ymd(d) { return d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); }\n" + grab("nowMinIfToday") + grab("energyAt"), ctx);
    const nowM = new Date().getHours() * 60 + new Date().getMinutes();
    checkEq("a minute that has happened has its reading", vm.runInContext("energyAt(0).soc", ctx), 40);
    if (nowM < 1430) checkEq("a minute that has not happened has none", vm.runInContext("energyAt(" + (nowM + 5) + ")", ctx), null);
    vm.runInContext("selDate = new Date(2026, 0, 5);", ctx);
    checkEq("a past day is read to its end", vm.runInContext("energyAt(1439).soc", ctx), 50);
    check("a span is drawn no further than now", /const end = Math\.min\(s\[1\], nowMin\);\s*if \(end <= s\[0\]\) continue;/.test(tl));
    check("the playhead cannot be put past now", /const cap = nowMinIfToday\(\);/.test(tl));
}

console.log("\nAir: a plug that is not answering has no 'now'");
check("the purifier plug's watts are shown only while the plug is live",
      /const w = plugLive && plug\.states \? parseFloat\(plug\.states\.powerWatts\) : NaN;/.test(read("levoit.html")));

done();
