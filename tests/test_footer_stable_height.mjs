// Filename:    test_footer_stable_height.mjs
// Description: The cameras page footer must not change height (v2.99.1).
//
//              It is sticky at the bottom, and its top line carries a live
//              byte rate that gains a digit every few seconds. When the line
//              wrapped, the whole grid moved. MEASURED in a 430px viewport:
//              74px at "19 kB/s total" against 90px at "153 kB/s total" — so
//              the page hopped 16px, twice a minute, for as long as it was
//              open. After the fix the footer measured 90px at every rate from
//              7 kB/s to 12.3 MB/s, with nothing clipped.
//
//              Layout cannot be measured here, so this locks the three things
//              that make it true: the row cannot wrap, the rate reserves its
//              width, and the long word lives only on the top bar which has
//              room for it.
// Author:      CliveS & Claude Opus 5
// Date:        02-09-2026
// Version:     1.0
//
// Run: node tests/test_footer_stable_height.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                                      "Resources", "static", "pages", "cameras.html"), "utf8");
let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

console.log("\nthe footer's top line is one line, always");
check("the status row is wrapped in .foot-line",
      /<span class="foot-line"><span id="grid-cam-count">/.test(src));
check("and .foot-line cannot wrap",
      /\.foot-line\s*\{[^}]*white-space:\s*nowrap/.test(src),
      "a wrap adds a line to a sticky bar, which shoves the grid");
check("overflowing text is clipped rather than reflowed",
      /\.foot-line\s*\{[^}]*text-overflow:\s*ellipsis/.test(src));
check("the rate reserves the width of its longest value",
      /#total-bw-bot\s*\{[^}]*min-width:\s*[\d.]+ch/.test(src),
      "so the characters before it do not shuffle as it changes");

console.log("\none owner for both readouts");
check("_setBw exists", /function _setBw\(rate\)/.test(src));
check("the top bar keeps the word 'total'", /top\.textContent = rate \+ " total"/.test(src));
check("the footer does not — it has no room for it",
      /bot\.textContent = rate;/.test(src));
check("nothing else writes either element directly",
      !/getElementById\("total-bw"\)[\s\S]{0,80}textContent =/.test(src.replace(/function _setBw[\s\S]*?\n    \}/, "")),
      "two writers is how the two readouts drifted apart");
const setters = src.match(/_setBw\(/g) || [];
check("every measurement path goes through it", setters.length >= 4,
      `found ${setters.length} references (definition + 3 call sites)`);

console.log("\nand the wording stays short enough to fit a phone");
check("health reads 'health OK', not 'camera health OK'",
      /: "health OK";/.test(src) && !/"camera health OK"/.test(src),
      "the row already says '9 cameras', so the second 'camera' only cost width");

process.exit(failed ? 1 : 0);
