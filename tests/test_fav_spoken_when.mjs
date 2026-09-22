// Filename:    test_fav_spoken_when.mjs
// Description: Contract test for spokenWhen() (v3.23.0) — a reading favourite
//              whose value is a bare timestamp is said the way a person says it,
//              per the house notification rule ("1pm today", not "2026-09-22
//              13:00:30"). First user: the Doorbell last rang tile.
//
//              THE RULES
//              1. Today / yesterday / weekday within a week / "12 September",
//                 with the year only when it differs.
//              2. On the hour drops ":00"; midnight and noon are words.
//              3. It is relative to the VIEWER's now, so it rolls over itself.
//              4. Anything that is not exactly a timestamp returns null, so every
//                 other reading (a voltage, "12.6 V", a word) is left untouched.
//              5. Pure ASCII.
// Author:      CliveS & Claude Opus 5
// Date:        22-09-2026
// Version:     1.0
//
// Run: node tests/test_fav_spoken_when.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
const src = fs.readFileSync(PAGE, "utf8");

function extractFn(s, name) {
    const start = s.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unbalanced: " + name);
}

let fails = 0;
const check = (w, got, want) => {
    const ok = got === want;
    console.log((ok ? "  ok   " : "  FAIL ") + w + (ok ? "" : `  got ${JSON.stringify(got)} want ${JSON.stringify(want)}`));
    if (!ok) fails++;
};

console.log("favourites — spoken timestamps");
const ctx = vm.createContext({ console, Date, Math, String, isNaN });
vm.runInContext(extractFn(src, "spokenWhen"), ctx);
const sw = (raw, now) => ctx.spokenWhen(raw, now);

const NOW = new Date(2026, 8, 22, 13, 30, 0);          // Tue 22 Sep 2026, 1:30pm
check("on the hour, today",       sw("2026-09-22 13:00:30", NOW), "1pm today");
check("minutes kept",             sw("2026-09-22 09:05:00", NOW), "9:05am today");
check("yesterday",                sw("2026-09-21 16:15:00", NOW), "4:15pm yesterday");
check("weekday within a week",    sw("2026-09-17 09:30:00", NOW), "Thursday at 9:30am");
check("older: date, no year",     sw("2026-09-12 10:00:00", NOW), "12 September");
check("older, other year",        sw("2025-12-25 10:00:00", NOW), "25 December 2025");
check("midnight is a word",       sw("2026-09-22 00:00:00", NOW), "midnight today");
check("noon is a word",           sw("2026-09-21 12:00:00", NOW), "noon yesterday");
check("12:30pm not 0:30pm",       sw("2026-09-22 12:30:00", NOW), "12:30pm today");
check("12:10am not 0:10am",       sw("2026-09-22 00:10:00", NOW), "12:10am today");
check("rolls over overnight",     sw("2026-09-22 13:00:30", new Date(2026, 8, 23, 7, 0)), "1pm yesterday");
check("slightly future = today",  sw("2026-09-22 13:31:00", NOW), "1:31pm today");
check("T separator accepted",     sw("2026-09-22T13:00:30", NOW), "1pm today");
check("no seconds accepted",      sw("2026-09-22 13:00", NOW), "1pm today");
check("a voltage is left alone",  sw("12.6 V", NOW), null);
check("a plain number left alone",sw("12.60", NOW), null);
check("empty is null",            sw("", NOW), null);
check("null is null",             sw(null, NOW), null);
check("impossible date refused",  sw("2026-02-30 10:00:00", NOW), null);
const all = ["2026-09-22 13:00:30", "2026-09-17 09:30:00", "2025-12-25 10:00:00"].map(r => sw(r, NOW)).join(" ");
check("pure ASCII", /^[\x20-\x7e]*$/.test(all), true);

// Wiring: the reading tile must actually call it, not merely define it.
const fav = extractFn(src, "renderFavouritesCard");
check("reading tile uses spokenWhen", /spokenWhen\(raw\)/.test(fav), true);

if (fails) { console.log(`${fails} failure(s)`); process.exit(1); }
console.log("all passed");
