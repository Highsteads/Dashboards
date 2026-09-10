// Filename:    test_solar_card_split.mjs
// Description: Solar is its own hub card (v2.98.0). It used to be drawn inside
//              the weather card, so tapping the day's generation — the number
//              most looked at on the hub — opened the WEATHER page. The two are
//              now separate cards with separate destinations, and this locks
//              both the split and the thing that made the split fiddly: the
//              solar renderer no longer depends on the weather shell being
//              built first, so it must build its own and hide its own card.
// Author:      CliveS & Claude Opus 5
// Date:        02-09-2026
// Version:     1.0
//
// Run: node tests/test_solar_card_split.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                                      "Resources", "static", "pages", "index.html"), "utf8");
let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

console.log("\ntwo cards, two destinations");
check("a solar card exists and goes to the energy page",
      /<a id="solar-now"\s+class="dash-card" href="energy\.html"/.test(src));
check("and it starts hidden, so it is never an empty box",
      /<a id="solar-now"[^>]*style="display:none"/.test(src),
      "the renderer shows it once there is something to show, like #favourites");
check("the weather card still goes to the weather page",
      /<a id="weather-now"\s+class="dash-card" href="ecowitt\.html">/.test(src));
check("the solar block is no longer built by the weather shell",
      !/_ensureWeatherShell[\s\S]{0,400}wx-solar/.test(src),
      "that nesting is what sent a tap on Solar to the weather page");
check("the weather shell now builds only the weather rows",
      /el\.innerHTML = `<div id="weather-rows"><\/div>`;/.test(src));

console.log("\nthe solar renderer stands on its own");
const fn = src.slice(src.indexOf("function renderWeatherSolar()"));
check("it builds its own shell", /_ensureSolarShell\(card\)/.test(fn.slice(0, 1400)),
      "it used to rely on the weather card having been rendered first");
check("no inverter hides the whole card, not just its contents",
      /if \(!d \|\| !d\.solar\) \{ card\.style\.display = "none"; return; \}/.test(fn.slice(0, 1400)),
      "otherwise an empty box sits on the landing page");
check("no readings yet also hides the card",
      /if \(actual == null && fc == null\) \{ card\.style\.display = "none"; return; \}/.test(fn.slice(0, 1400)));
check("the solar card is in HEAVY_REGIONS", /HEAVY_REGIONS = \[[^\]]*"solar-now"/.test(src));
check("both cards are rendered on the same poll",
      /renderWeatherCard\(devices\)[\s\S]{0,400}renderWeatherSolar\(\)/.test(src));

process.exit(failed ? 1 : 0);
