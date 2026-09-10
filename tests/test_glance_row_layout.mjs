// Filename:    test_glance_row_layout.mjs
// Description: The hub's glance row holds THREE cards in a TWO-column grid, so
//              the third wraps. Before v3.3.0 that put Weather under Energy and
//              left a hole the size of it beside Weather, while the grid
//              stretched Solar to Energy's full height around a third as much
//              content — measured 623px of card around 240px of it. Energy now
//              spans both rows, so Solar sits above Weather on the right.
//
//              This is a STRUCTURAL guard, not a rendering one: node has no CSS
//              engine, so it asserts the things that would silently reintroduce
//              the hole — a fourth card in the row, or the row span going away.
//              The visual result was checked in a real browser at 1200, 768 and
//              375 px, including with the Solar card hidden.
// Author:      CliveS & Claude Opus 5
// Date:        04-09-2026
// Version:     1.0
//
// Run: node tests/test_glance_row_layout.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HUB = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "index.html");
const html = fs.readFileSync(HUB, "utf8");

let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

console.log("\nthe hub's glance row");

// The row markup, so we can count what is actually in it.
const row = /<div class="dash-row glance">([\s\S]*?)<\/div>/.exec(html);
check("the row is still there", !!row);

if (row) {
    const ids = [...row[1].matchAll(/<a\s+id="([a-z-]+)"/g)].map(m => m[1]);
    check("holds exactly three cards", ids.length === 3, ids.join(", "));
    check("in the order Energy, Solar, Weather",
          ids.join(",") === "energy-detail,solar-now,weather-now", ids.join(","));
}

// Energy spans both rows, which is what puts Solar above Weather rather than
// leaving a hole. Scoped to the two-column layout: on a phone everything is a
// single column and the span must not apply.
const desktop = /@media \(min-width: 601px\) \{([\s\S]*?)\n        \}/.exec(html);
check("there is a two-column-only block", !!desktop);
check("energy spans both rows in it",
      !!desktop && /#energy-detail\s*\{\s*grid-row:\s*span 2/.test(desktop[1]));
check("cards sit at their own height, not stretched",
      !!desktop && /\.dash-row\.glance\s*\{\s*align-items:\s*start/.test(desktop[1]));

// The phone rule must survive: one column, so the row order IS the layout.
check("the phone layout still collapses to one column",
      /@media \(max-width: 600px\)[\s\S]*?\.dash-row\.glance\s*\{\s*grid-template-columns:\s*1fr/.test(html));

// Auto-placement, NOT pinned rows — Solar hides itself when there is no
// per-string payload, and a pinned grid-row would leave the hole back where it
// started instead of letting Weather move up.
check("solar and weather are not pinned to fixed rows",
      !/#solar-now\s*\{[^}]*grid-row:\s*[12]\b/.test(html) &&
      !/#weather-now\s*\{[^}]*grid-row:\s*[12]\b/.test(html));

console.log(failed ? `\n${failed} failed\n` : "\nall passed\n");
process.exit(failed ? 1 : 0);
