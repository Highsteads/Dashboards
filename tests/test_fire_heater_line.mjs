// Filename:    test_fire_heater_line.mjs
// Description: Contract test for the living room fire's tile line (room.html
//              fireSubtitle, v3.21.0). Broadlink RF 1.4.0 reads the fire's plug
//              and publishes measuredState / measuredWatts / heavyLoad /
//              feedbackStatus; the tile turns those into one line a person can
//              read at a glance, with the heater called out when it runs.
// Author:      CliveS & Claude Opus 5
// Date:        21-09-2026
// Version:     1.0
//
// Run: node tests/test_fire_heater_line.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "room.html");
const src = fs.readFileSync(PAGE, "utf8");

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

const ctx = vm.createContext({ console });
vm.runInContext(extractFn(src, "fireSubtitle"), ctx);
const line = (states, onState = false) =>
    vm.runInContext(`fireSubtitle(${JSON.stringify({ onState, states })})`, ctx);

let fails = 0;
const check = (what, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? "  ok   " : "  FAIL ") + what + (ok ? "" : `  got ${JSON.stringify(got)}`));
    if (!ok) fails++;
};

console.log("Fire tile line");

check("an older plugin with no reading keeps the ordinary relay wording",
      line({ onOffState: true }, true), null);
check("heater running is called out, with the watts",
      line({ measuredState: "on", measuredWatts: 1512.4, heavyLoad: true, feedbackStatus: "On (measured)" }, true),
      { text: "Heater on · 1,512 W", heater: true });
check("the v2 API's string \"True\" counts as the heater running",
      line({ measuredState: "on", measuredWatts: 1512, heavyLoad: "True" }, true),
      { text: "Heater on · 1,512 W", heater: true });
check("the string \"False\" is NOT the heater running (it is truthy)",
      line({ measuredState: "on", measuredWatts: 38, heavyLoad: "False" }, true),
      { text: "Flame only · 38 W", heater: false });
check("flame without heater",
      line({ measuredState: "on", measuredWatts: 37.6, heavyLoad: false }, true),
      { text: "Flame only · 38 W", heater: false });
check("off is just off — no standby watts",
      line({ measuredState: "off", measuredWatts: 0.4, heavyLoad: false }),
      { text: "Off", heater: false });
check("waiting for the plug to confirm an ON",
      line({ measuredState: "off", feedbackStatus: "Waiting for on" }, true),
      { text: "Turning on…", heater: false });
check("waiting for the plug to confirm an OFF",
      line({ measuredState: "on", feedbackStatus: "Waiting for off", heavyLoad: true }),
      { text: "Turning off…", heater: false });
check("an ignored OFF says so, and still shows a running heater",
      line({ measuredState: "on", feedbackStatus: "Did not turn off", heavyLoad: true }, true),
      { text: "Did not respond · still on", heater: true });
check("no reading says the state is not confirmed",
      line({ measuredState: "unknown", feedbackStatus: "No reading" }, true),
      { text: "On · not confirmed", heater: false });
check("…in both directions",
      line({ measuredState: "unknown" }, false),
      { text: "Off · not confirmed", heater: false });

// The line is only used for the fire, and the heater class reaches the markup.
// The fire lives in LIGHTS in the real config, so the line must not depend on
// FIRE_IDS — the first version did, and the live page never showed it.
check("renderLight asks fireSubtitle for every tile, whatever its section",
      /const fireLine = fireSubtitle\(d\);/.test(extractFn(src, "renderLight")), true);
check("a lamp publishing no reading keeps its own wording",
      line({ onOffState: true, brightnessLevel: 40 }, true), null);
check("the heater-on class is applied to the state line",
      /class="light-state\$\{stateCls\}"/.test(extractFn(src, "renderLight")), true);

if (fails) { console.log(`${fails} failure(s)`); process.exit(1); }
console.log("all passed");
