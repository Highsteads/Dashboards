// Filename:    test_review_batch6.mjs
// Description: Sixth group from the 25/26-Nov-2026 review (3.73.9):
//                - the Active page called a device with no on/off reading
//                  "Off", and a dimmer with no brightness reading "0%";
//                - Settings said "Saved, live on the pages now" when the
//                  rebuild of the pages' files after the save had failed.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch6.mjs   (exit 0 = pass)

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

console.log("Active page: no reading is not Off, and no brightness is not 0%");
{
    const active = read("active.html");
    const truthy = v => (typeof v === "boolean" ? v : v === "True" || v === "true" ? true : v === "False" || v === "false" ? false : null);
    const ctx = vm.createContext({ DashTile: { state: truthy }, classify: () => "lights" });
    vm.runInContext(extractFn(active, "describeState") + "\nglobalThis.f = describeState;", ctx);
    checkEq("a lamp that is off", ctx.f({ onState: false, class: "indigo.DimmerDevice", brightness: 0 }), "Off");
    checkEq("a device that gives no on/off reading", ctx.f({ onState: null, class: "indigo.RelayDevice" }), "No reading");
    checkEq("and one with none at all", ctx.f({ class: "indigo.RelayDevice" }), "No reading");
    checkEq("a dimmer at 40%", ctx.f({ onState: true, class: "indigo.DimmerDevice", brightness: 40 }), "40% · lights");
    checkEq("a dimmer that is on with no brightness reading", ctx.f({ onState: true, class: "indigo.DimmerDevice" }), "On · lights");
    checkEq("a relay that is on", ctx.f({ onState: true, class: "indigo.RelayDevice" }), "Light on");
}

console.log("\nSettings: a save whose page rebuild failed says so");
{
    const s = read("settings.html");
    check("the message reads the reply", /res\.refreshed === false/.test(s) && /could not be updated/.test(s));
}

done();
