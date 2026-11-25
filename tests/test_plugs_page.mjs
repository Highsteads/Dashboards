// Filename:    test_plugs_page.mjs
// Description: The Plugs page must not say "used nothing" where nothing was
//              measured (3.73.4). A plug with no energy on record at all was
//              listed under "Used nothing in the last 30 days", and a plug that
//              is not answering read "0p, nothing used" for today.
//              Runs the shipped plugs.html helpers.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_plugs_page.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources",
                                      "static", "pages", "plugs.html"), "utf8");
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
const ctx = vm.createContext({ console, money: p => p + "p", kwh: k => (k === null || k === undefined) ? "not recorded" : k ? k + " kWh" : "nothing used" });
vm.runInContext(extractFn(src, "splitPlugs") + "\n" + extractFn(src, "cellWords"), ctx);

console.log("plugs page: nothing measured is not nothing used");
ctx.plugs = [{ name: "Kettle", month: { kwh: 2.5 } }, { name: "Printer", month: { kwh: 0 } },
             { name: "New Plug", month: { kwh: null } }, { name: "Bare" }];
const names = l => Array.from(l, p => p.name);
const s = vm.runInContext("splitPlugs(plugs)", ctx);
checkEq("a plug that used energy", names(s.used), ["Kettle"]);
checkEq("a plug that measured none", names(s.idle), ["Printer"]);
checkEq("a plug with nothing on record", names(s.blank), ["New Plug", "Bare"]);
check("the page says so in its own words", /No energy on record for/.test(src) && /blank\.length/.test(src));

ctx.p = { answering: false, today: { kwh: 0, pence: 0 }, week: { kwh: 3.1, pence: 48 } };
checkEq("a plug that is not answering has no today", vm.runInContext('cellWords(p, "today")', ctx), { val: "—", sub: "not answering" });
checkEq("its finished days still show", vm.runInContext('cellWords(p, "week")', ctx), { val: "48p", sub: "3.1 kWh" });
ctx.p = { answering: true, today: { kwh: 0, pence: 0 } };
checkEq("a plug that answers and used nothing says so", vm.runInContext('cellWords(p, "today")', ctx), { val: "0p", sub: "nothing used" });
ctx.p = { answering: true, today: { kwh: 1, pence: null } };
checkEq("energy with no price shows a dash for the money", vm.runInContext('cellWords(p, "today")', ctx), { val: "—", sub: "1 kWh" });

done();
