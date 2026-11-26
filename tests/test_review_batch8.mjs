// Filename:    test_review_batch8.mjs
// Description: Eighth group from the 25/26-Nov-2026 review (3.73.11):
//                - the Plugs and Savings pages kept old figures under
//                  "Updated HH:MM" when their updates stopped, with no day;
//                - three lines of wording that were no longer true.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch8.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

console.log("Plugs and Savings say when they have stopped updating");
for (const f of ["plugs.html", "savings.html"]) {
    const s = read(f);
    check(`${f}: the status bar is a live bar`, /<span class="topbar-status" data-live>Updated <span id="ts">—<\/span><span class="live-cadence"><\/span><\/span>/.test(s));
    check(`${f}: marked once, on a good reply, after the time is written`,
          (s.split("_liveness.mark()").length - 1) === 1 && /const _liveness = DashUI\.liveness\(\{ staleAfterMs: 3 \* POLL_MS \+ 30000 \}\);/.test(s)
          && s.indexOf("_liveness.mark()") > s.indexOf("return;                           // keep the last figures"));
    check(`${f}: the day is shown when the figures are not today's`, /d\.toDateString\(\) === new Date\(\)\.toDateString\(\) \? ""/.test(s));
}

console.log("\nwording that had gone out of date");
check("the Energy menu tile no longer promises the removed card", !/when to run it/i.test(read("menu.html")));
check("the Scenes page points at Settings for hidden scenes", /Hidden scenes are chosen on the Settings page\./.test(read("scenes.html")) && !/DASHBOARDS_HIDDEN_SCENES/.test(read("scenes.html")));
check("the Meter chart does not call its last logged figure 'now'", /<span>last logged <b>/.test(read("meter.html")));

done();
