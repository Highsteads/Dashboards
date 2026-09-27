// Filename:    test_self_suff_reason.mjs
// Description: v3.40.0. A low self-sufficiency figure on a day the grid
//              charged the battery says why, instead of a bare 0% on a sunny
//              afternoon. (Its demo-sun half went with demo mode in 3.53.0.)
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026 (1.1: 27-09-2026)
// Version:     1.1

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const load = (file, extra = {}) => {
    const w = Object.assign({ console }, extra);
    w.window = w; w.globalThis = w;
    vm.createContext(w);
    vm.runInContext(fs.readFileSync(path.join(PAGES, file), "utf8"), w);
    return w;
};

console.log("\nself-sufficiency says why it is low");
{
    const C = load("energy-calc.js").DashCalc;
    const why = C.selfSuffReason({ home_kwh: 13.64, import_kwh: 15.98, battery_charge_kwh: 19.75, self_suff: 0 });
    check("today's real case gets a reason", !!why);
    checkEq("short, for a tile", why.short, "grid charged the battery");
    checkEq("long, with the figures in words", why.long,
            "The grid supplied 16 kWh while the house used 13.6 kWh, because it also charged the battery. That energy runs the house later.");
    const part = C.selfSuffReason({ home_kwh: 12, import_kwh: 8, battery_charge_kwh: 5, self_suff: 33 });
    checkEq("part of the import", part && part.short, "partly from charging the battery");
    check("a good day needs no excuse", C.selfSuffReason({ home_kwh: 12, import_kwh: 1, battery_charge_kwh: 8, self_suff: 92 }) === null);
    check("low with no battery charging is just low", C.selfSuffReason({ home_kwh: 12, import_kwh: 10, battery_charge_kwh: 0.2, self_suff: 17 }) === null);
    check("missing figures give nothing, never a guess", C.selfSuffReason({ home_kwh: 12, self_suff: 0 }) === null);
    check("works out the percentage when the summary lacks it",
          !!C.selfSuffReason({ home_kwh: 10, import_kwh: 12, battery_charge_kwh: 6 }));
    for (const p of ["energy.html", "index.html"]) {
        check(`${p} uses the shared reason`, fs.readFileSync(path.join(PAGES, p), "utf8").includes("DashCalc.selfSuffReason("));
    }
}

done();
