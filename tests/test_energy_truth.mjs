// Filename:    test_energy_truth.mjs
// Description: The Energy page says what was measured (3.73.5, review
//              26-11-2026):
//                - today's flow diagram invented a LOSSES figure and said
//                  "the counters disagree" on every day the battery sold at
//                  the peak and the grid fed the house (every Flux day);
//                - three of the manager's actions had no words, so the page
//                  printed their raw codes;
//                - a free hour still being measured read "Nothing owed,
//                  every free hour is settled";
//                - a failing Axle feed read "Standby";
//                - readings held over from before the inverter link dropped
//                  were stamped as live.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_energy_truth.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const ctx = { console, window: {}, Math, Date, JSON, String, Number, isFinite, isNaN, parseFloat, parseInt };
vm.createContext(ctx);
vm.runInContext(read("energy-calc.js"), ctx);
const C = ctx.window.DashCalc;
const near = (a, b, tol = 0.011) => Math.abs(a - b) <= tol;

console.log("today's flow: a day the battery sold at the peak");
// 25-Nov-2026, a Flux day: 28.0 kWh into the battery, 26.4 out, 31.8 imported, 11.1 exported.
const f = C.computeFlows({ pv_kwh: 4.7, import_kwh: 31.8, export_kwh: 11.1, home_kwh: 23.8 }, 28.0, 26.4);
check("no losses are invented", f.loss < 0.05, "loss " + f.loss.toFixed(2));
check("no use is left without a source", f.unmet < 0.05, "unmet " + f.unmet.toFixed(2));
check("every source is spent", near(f.s2l + f.s2b + f.s2g, 4.7) && near(f.b2l + f.b2g, 26.4) && near(f.g2l + f.g2b, 31.8),
      JSON.stringify({ s: f.s2l + f.s2b + f.s2g, b: f.b2l + f.b2g, g: f.g2l + f.g2b }));
check("every sink is filled", near(f.s2l + f.b2l + f.g2l, 23.8) && near(f.s2b + f.g2b, 28.0) && near(f.s2g + f.b2g, 11.1));
check("the battery's sale and the grid's share of the house are both shown", f.b2g > 10 && f.g2l > 3);
check("no ribbon is negative", [f.s2l, f.s2b, f.s2g, f.b2l, f.b2g, f.g2l, f.g2b].every(v => v >= 0));

console.log("\ntoday's flow: real disagreements are still said");
const lossy = C.computeFlows({ pv_kwh: 10, import_kwh: 0, export_kwh: 0, home_kwh: 8 }, 0, 0);
check("solar with nowhere to go is still a loss", near(lossy.loss, 2) && lossy.unmet < 0.01);
const short = C.computeFlows({ pv_kwh: 2, import_kwh: 0, export_kwh: 0, home_kwh: 8 }, 0, 0);
check("use with no source is still called out", near(short.unmet, 6) && short.loss < 0.01);
const plain = C.computeFlows({ pv_kwh: 20, import_kwh: 1, export_kwh: 6, home_kwh: 10 }, 8, 3);
check("a summer day keeps its order, and its one imported kWh goes to the house rather than nowhere",
      near(plain.s2l, 9) && near(plain.s2b, 8) && near(plain.s2g, 3) && near(plain.b2g, 3) && near(plain.g2l, 1)
      && plain.loss < 0.01 && plain.unmet < 0.01, JSON.stringify(plain));
const noImport = C.computeFlows({ pv_kwh: 20, import_kwh: 0, export_kwh: 5, home_kwh: 10 }, 8, 3);
check("with nothing imported nothing is moved", near(noImport.s2l, 10) && near(noImport.s2b, 8) && near(noImport.s2g, 2) && near(noImport.b2g, 3));

console.log("\nfree hours still being measured");
const s1 = C.octopusSummary({ free_hour_credits: [{ state: "measuring", owed_p: null }] });
checkEq("a measuring hour is open, with nothing yet known to be owed", [s1.openClaims, s1.owedP, s1.unknownClaims], [1, 0, 1]);
const s2 = C.octopusSummary({ free_hour_credits: [{ state: "awaiting", owed_p: 265 }, { state: "paid", owed_p: 0 }] });
checkEq("an awaited credit is counted as before", [s2.openClaims, s2.owedP, s2.unknownClaims], [1, 265, 0]);
checkEq("nothing open", C.octopusSummary({ free_hour_credits: [{ state: "paid" }, { state: "nothing_due" }] }).openClaims, 0);
checkEq("the words for it", [C.owedWords(s1), C.owedWords(s2), C.owedWords({ openClaims: 0, owedP: 0, unknownClaims: 0 })],
        [["Being worked out", "waiting for the meter reading"], ["£2.65", "waiting for Octopus to credit it"], ["Nothing", "every free hour is settled"]]);

console.log("\nthe page's words");
const page = read("energy.html");
for (const code of ["vpp_export", "saving_session", "happy_hour_import"]) {
    check(`${code} has a label and a class`, new RegExp(code + ":\\s+'[A-Z]").test(page) && new RegExp(code + ":\\s+'action-").test(page));
    check(`${code} has words in the Flow pop-up`, new RegExp(code + ":\\s+'[A-Z]").test(read("flow-popups.js")));
}
check("the VPP chip compares with the state the manager really sends", /=== 'active' \? 'warn'/.test(page) && !/'vpp_active'/.test(page));
check("a failing Axle feed is not 'Standby'", /api_status && d\.vpp\.api_status !== 'OK'/.test(page) && /Feed failing/.test(page));
check("readings from before the inverter link dropped are not stamped as live",
      /const linkDown = !!\(d\.flags && d\.flags\.modbus_connected === false\);/.test(page) && /if \(!linkDown\) _liveness\.mark\(\);/.test(page));
check("the Octopus card uses the shared words", /DashCalc\.owedWords\(sum\)/.test(page));

done();
