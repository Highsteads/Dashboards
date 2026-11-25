// Filename:    test_system_health_truth.mjs
// Description: The System page must not say "All systems healthy" over a
//              check that failed or could not measure (3.73.5, review
//              26-11-2026). A failed collector arrived as {error: ...} and
//              an unmeasured memory figure as pressure "unknown"; the page
//              read neither, and printed four green "OK" chips.
//              Also the Cost page's two halves of the saving, which were
//              clamped so they did not add up to the headline.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_system_health_truth.mjs   (exit 0 = pass)

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

const page = read("system-health.html");
const ctx = vm.createContext({ console, I: n => "", esc: s => String(s), num: (v, d) => (v == null ? "—" : Number(v).toFixed(d == null ? 1 : d)),
    band: (v, warn, bad) => (v >= bad ? "bad" : v >= warn ? "warn" : "") });
vm.runInContext(extractFn(page, "healthIssues"), ctx);
const run = d => { ctx.__d = d; return JSON.parse(JSON.stringify(vm.runInContext("healthIssues(__d)", ctx))); };
const GOOD = { mac: { cores: 15, load: [1.2, 1, 1], disk: { used_pct: 13 }, ram: { pressure: "normal", used_pct: 55 } },
               storage: {}, devices: { total: 215, in_error: [], low_battery: [], by_plugin: [] }, services: { cameras: 10, go2rtc: true, proxy: true } };
const labels = r => r.issues.map(i => i[1]);

console.log("system health: the verdict");
const good = run(GOOD);
checkEq("everything measured and fine", [good.worst, good.verdict, good.issues.length], ["good", "All systems healthy", 0]);
checkEq("every check that answered is listed as OK", good.okChecks, ["Disk", "Memory", "Load", "Devices"]);

const noRam = run({ ...GOOD, mac: { ...GOOD.mac, ram: { pressure: "unknown", total_gb: 64 } } });
check("memory that could not be measured is not 'healthy'", noRam.worst !== "good" && noRam.verdict !== "All systems healthy", noRam.verdict);
check("it is named", labels(noRam).some(l => /Memory could not be measured/.test(l)), labels(noRam).join(" | "));
check("and Memory is not among the OK chips", !noRam.okChecks.includes("Memory") && noRam.okChecks.includes("Disk"));
checkEq("with nothing actually wrong, the verdict says checks were missed", noRam.verdict, "Some checks could not be made");

const macErr = run({ ...GOOD, mac: { error: "timed out" } });
check("a failed Mac section is not healthy", macErr.worst !== "good" && labels(macErr).some(l => /Mac's own figures could not be read/.test(l)), labels(macErr).join(" | "));
const devErr = run({ ...GOOD, devices: { error: "boom" } });
check("a failed device check is not 'Devices OK'", devErr.worst !== "good" && !devErr.okChecks.includes("Devices")
      && labels(devErr).some(l => /Devices could not be checked/.test(l)));
const noDisk = run({ ...GOOD, mac: { ...GOOD.mac, disk: {} } });
check("a disk that gave no figure is not 0% full", noDisk.worst !== "good" && labels(noDisk).some(l => /Disk could not be measured/.test(l)));
const real = run({ ...GOOD, mac: { ...GOOD.mac, ram: { pressure: "high", used_pct: 95 } }, devices: { error: "boom" } });
checkEq("a real fault still outranks a missed check", [real.worst, real.verdict], ["bad", "Needs attention"]);
check("the page draws its chips from this", /healthIssues\(d\)/.test(page) && !/Memory OK<\/span><span class="chip good">\$\{I\("gear"\)\} Load OK/.test(page));
check("swap is no longer called the real pressure signal", !/the real pressure signal/.test(page));

console.log("\ncost page: the two halves of the saving add up");
const cost = read("cost.html");
const cctx = vm.createContext({ console });
vm.runInContext(extractFn(cost, "savingSplit"), cctx);
const split = t => { cctx.__t = t; return JSON.parse(JSON.stringify(vm.runInContext("savingSplit(__t)", cctx))); };
const flux = split({ no_solar_cost_gbp: 3.75, import_cost_gbp: 5.01, export_revenue_gbp: 3.11 });
check("on a day the battery was filled from the grid the first half is negative, not nought",
      Math.abs(flux.avoided - (-1.26)) < 0.001 && Math.abs(flux.avoided + flux.earned - 1.85) < 0.001, JSON.stringify(flux));
check("and it is named for what it is", /more/i.test(flux.label) && flux.label !== "Import avoided", flux.label);
checkEq("no bar is drawn for a negative half", flux.bars, [0, 0]);
const sunny = split({ no_solar_cost_gbp: 6, import_cost_gbp: 1, export_revenue_gbp: 5 });
checkEq("a sunny day reads as before", [sunny.avoided, sunny.label, sunny.bars], [5, "Import avoided", [50, 50]]);
checkEq("nothing known is nothing shown", split({}).avoided, null);
check("the hero uses it", /const s = savingSplit\(t\);/.test(cost) && !/Math\.max\(0, t\.no_solar_cost_gbp - t\.import_cost_gbp\)/.test(cost));
check("the table no longer promises a sum to the penny", !/a sum you can check by eye/.test(cost));

console.log("\nweather page");
check("the pressure unit is escaped before it reaches the page", /" " \+ escapeHtml\(pu\)/.test(read("ecowitt.html")));

done();
