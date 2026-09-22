// Filename:    test_fire_heater_chip.mjs
// Description: Contract test for the hub's fire-heater chip (index.html
//              fireHeaterChip, v3.22.0). Shown only while a heater runs, it
//              names the fire and its watts and links to the fire's room.
// Author:      CliveS & Claude Opus 5
// Date:        22-09-2026
// Version:     1.0
//
// Run: node tests/test_fire_heater_chip.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
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

const asBoolSrc = (src.match(/const asBool = [^\n]+/) || [])[0];
if (!asBoolSrc) throw new Error("asBool not found");
const ctx = vm.createContext({ console });
vm.runInContext(asBoolSrc + "\n" + extractFn(src, "fireHeaterChip"), ctx);
const chip = (devices, rooms = null) =>
    vm.runInContext(`fireHeaterChip(${JSON.stringify(devices)}, ${JSON.stringify(rooms)})`, ctx);

const FIRE = 614164061;
const ROOMS = { rooms: { "Living Room": { lights: [1, FIRE], openLoop: [FIRE] }, "Kitchen": { lights: [2] } } };
const fire = states => ({ id: FIRE, name: "Fire On/Off", enabled: true, states });

let fails = 0;
const check = (what, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? "  ok   " : "  FAIL ") + what + (ok ? "" : `  got ${JSON.stringify(got)}`));
    if (!ok) fails++;
};

console.log("Hub fire-heater chip");

check("heater running: named, with watts, linked to its room",
      chip([fire({ measuredState: "on", heavyLoad: true, measuredWatts: 1512.3 })], ROOMS),
      { href: "room.html?room=Living%20Room", text: "Fire heater on · 1,512 W" });
check("the v2 API's string \"True\" counts",
      chip([fire({ measuredState: "on", heavyLoad: "True", measuredWatts: 1500 })], ROOMS).text,
      "Fire heater on · 1,500 W");
check("the string \"False\" does not (it is truthy)",
      chip([fire({ measuredState: "on", heavyLoad: "False", measuredWatts: 38 })], ROOMS), null);
check("flame only: no chip",
      chip([fire({ measuredState: "on", heavyLoad: false, measuredWatts: 38 })], ROOMS), null);
check("off: no chip",
      chip([fire({ measuredState: "off", heavyLoad: false })], ROOMS), null);
check("a stale heavyLoad with the reading lost: no chip",
      chip([fire({ measuredState: "unknown", heavyLoad: true })], ROOMS), null);
check("a disabled device: no chip",
      chip([{ ...fire({ measuredState: "on", heavyLoad: true }), enabled: false }], ROOMS), null);
check("no plug reading at all (older Broadlink RF): no chip",
      chip([fire({ onOffState: true })], ROOMS), null);
check("no rooms.json: links to the heating page",
      chip([fire({ measuredState: "on", heavyLoad: true, measuredWatts: 1500 })], null).href,
      "heating.html");
check("no watts: the words alone",
      chip([fire({ measuredState: "on", heavyLoad: true })], ROOMS).text, "Fire heater on");
check("two heaters: counted",
      chip([fire({ measuredState: "on", heavyLoad: true }),
            { id: 9, name: "Garage Heater", enabled: true, states: { measuredState: "on", heavyLoad: true } }],
           ROOMS).text, "2 heaters on");
check("renderHousePulse pushes the chip after the heating zones",
      /fireHeaterChip\(devices, ROOMS\)/.test(extractFn(src, "renderHousePulse")), true);

if (fails) { console.log(`${fails} failure(s)`); process.exit(1); }
console.log("all passed");
