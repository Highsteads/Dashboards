// Filename:    test_review_batch12.mjs
// Description: Twelfth group from the 25/26-Nov-2026 review (3.73.13):
//                - the Energy page judged "is this today's solar?" by
//                  comparing the payload's date with itself;
//                - SigenEnergyManager's "only part of today was counted"
//                  flag was never shown;
//                - a watch's own poll went on posting from a hidden tab.
//              (The watch's baseline is in test_action_watch.mjs, the restart
//              gate in test_stamp_gate.mjs, heating in test_heating_truth.mjs
//              and test_heating_history.mjs.)
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch12.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const grab = (src, name) => { const i = src.indexOf("function " + name + "("); if (i < 0) throw new Error("not found: " + name); let d = 0;
    for (let j = src.indexOf("{", i); j < src.length; j++) { if (src[j] === "{") d++; else if (src[j] === "}" && --d === 0) return src.slice(i, j + 1); } };
const energy = read("energy.html");

console.log("Energy: whose date decides what is today's");
{
    const c = vm.createContext({ console, Date, String, parseInt, Array,
        window: { DashUI: { serverNow: () => ({ ymd: "2026-11-26", min: 5, known: true }) } } });
    c.DashUI = c.window.DashUI;
    vm.runInContext("var _solStringHours = { date: '2026-11-25', hours: [] }, _solSlots = [], _solStatus = {};"
        + grab(energy, "_serverClock") + "\nglobalThis.clk = _serverClock;", c);
    checkEq("five past midnight, with yesterday's payload still held: today is the house's today",
            c.clk().todayStr, "2026-11-26");
    checkEq("so yesterday's payload no longer passes as today's",
            vm.runInContext("_solStringHours.date === _serverClock().todayStr", c), false);
    checkEq("the minute is the house's too", c.clk().nowMin, 5);
    c.window.DashUI.serverNow = () => ({ ymd: "1999-01-01", min: 0, known: false });
    vm.runInContext("_solSlots = [{ t: '2026-11-26T00:00:00' }];", c);
    checkEq("with no zone known it falls back to the slots, never to the payload being judged", c.clk().todayStr, "2026-11-26");
    check("the payload's own date is not read there any more",
          !/todayStr = _solStringHours\.date/.test(grab(energy, "_serverClock")));
    check("a stale payload is dropped and asked for again, at most once a minute",
          /if \(_solStringHours && !fresh\) \{\s*_solStringHours = null;\s*if \(Date\.now\(\) - _solStringAskedAt > 60000\)/.test(energy));
}

console.log("\nEnergy: a day only partly counted says so");
{
    const els = { "flow-sub": { textContent: "", style: {} }, "saved-sub": { textContent: "", style: {} } };
    const c = vm.createContext({ console, document: { getElementById: id => els[id] || null } });
    vm.runInContext(grab(energy, "partialDayWords") + grab(energy, "notePartialDay") + "\nglobalThis.W = partialDayWords; globalThis.N = notePartialDay;", c);
    checkEq("a whole day reads as before", [c.W(false).flow, c.W(false).saved], ["— since midnight", "solar & battery"]);
    c.N(true);
    check("a part day is said on the flow heading", /part of today only: the count started after midnight/.test(els["flow-sub"].textContent)
          && els["flow-sub"].style.color === "var(--warn)");
    checkEq("and on the saving", els["saved-sub"].textContent, "part of today only");
    c.N(false);
    checkEq("and taken off again the next day", [els["flow-sub"].textContent, els["flow-sub"].style.color], ["— since midnight", ""]);
    check("the page reads the flag", /notePartialDay\(!!s\.partial\);/.test(energy));
    check("the hero tiles carry it", /s\.partial \? 'part of today' : 'today'/.test(energy) && /s\.partial \? 'kWh, part day' : 'kWh'/.test(energy));
    check("both headings can be found", /id="flow-sub"/.test(energy) && /id="saved-sub"/.test(energy));
}

console.log("\na watch does not poll from a tab nobody can see");
{
    const act = read("dashboards-action.js");
    const self = grab(act, "selfPoll");
    check("the watch's own poll stops while hidden",
          /if \(typeof document !== 'undefined' && document\.hidden === true\) return;/.test(self));
    check("before it asks for anything", self.indexOf("document.hidden === true") < self.indexOf("a.getDevices()"));
}

done();
