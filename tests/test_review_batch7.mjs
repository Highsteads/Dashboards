// Filename:    test_review_batch7.mjs
// Description: Seventh group from the 25/26-Nov-2026 review (3.73.10):
//                - the hub said "SigenEnergyManager is not answering" and
//                  drew every flow at nought for up to half a minute each
//                  time the phone was unlocked;
//                - the Alerts page kept "could not be asked for the rules" up
//                  after the plugin answered, and left an unsaved tick showing.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch7.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

console.log("hub: coming back to the page asks for the Sigen reading at once");
const hub = read("index.html");
check("the visibility handler asks before it draws",
      /if \(document\.hidden\) \{ _hubStopAllLive\(\); return; \}[\s\S]{0,420}try \{ _refreshSigen\(\); \} catch \(_\) \{[^}]*\}\s*loadSummary\(\);/.test(hub));

console.log("\nAlerts page: messages follow what is true");
const alerts = read("alerts.html");
check("a load that works clears an earlier 'could not be asked'", /if \(_loadFailed\) \{ _loadFailed = false; say\("rules-msg", ""\); \}/.test(alerts));
check("a save that fails puts the controls back", /try \{ paint\(\); \} catch \(_\) \{[^}]*\}\s*say\("rules-msg", "Not saved: " \+ e\.message, true\);/.test(alerts));

done();
