// Filename:    test_free_hours_past_lookahead.mjs
// Description: A booked free hour shows from the moment it is booked, a free hour
//              nobody booked never shows, and any other session keeps the 24-hour
//              window.
//
//              WHY THIS EXISTS
//              03-Oct-2026: two booked hours, 11:00-13:00, showed as 11:00-12:00
//              because a per-row lookahead cut the second hour before the merge
//              could join them. 26-Nov-2026: CliveS asked for booked hours to show
//              as soon as they are booked (they had shown only 48 hours ahead), so
//              the lookahead for a booked free hour is now 8 days.
// Author:      CliveS & Claude Sonnet 5.5
// Date:        26-11-2026
// Version:     2.0
//
// Run: node tests/test_free_hours_past_lookahead.mjs   (exit 0 = pass)

import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { checkOk as check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources",
                       "static", "pages");
createRequire(import.meta.url)(path.join(PAGES, "energy-calc.js"));
const C = globalThis.DashCalc;

const HH = "WEEKEND_HAPPY_HOUR";
const hour = (id, startZ, joined) => ({
  id, direction: HH, joined, points: 0,
  start: `2026-10-04T${startZ}:00+00:00`,
  end:   `2026-10-04T${String(Number(startZ.slice(0, 2)) + 1).padStart(2, "0")}:00:00+00:00`,
});
const oct = { upcoming: [hour(1, "10:00", true), hour(2, "11:00", true),
                         hour(3, "12:00", false), hour(4, "13:00", false)] };

// Booked on the Thursday, three days out: it shows at once, as one two-hour row.
let r = C.savingSessions(oct, Date.parse("2026-10-01T17:20:00+01:00"));
check(r.length === 1, "booked hours show three days ahead as one row", JSON.stringify(r));
check(r[0] && r[0].hours === 2, "and it says two hours", r[0] && r[0].hours);
check(r[0] && r[0].endMs === Date.parse("2026-10-04T12:00:00Z"), "ending at 13:00 BST");

// The day before, still one two-hour row.
r = C.savingSessions(oct, Date.parse("2026-10-03T11:40:00+01:00"));
check(r.length === 1 && r[0].hours === 2, "the day before, still one two-hour row");

// An unbooked hour never shows.
r = C.savingSessions({ upcoming: [hour(1, "10:00", true), hour(3, "12:00", false)] },
                     Date.parse("2026-10-01T17:20:00+01:00"));
check(r.length === 1 && r[0].hours === 1, "an unbooked hour is left out");

// Two booked hours with a gap are two rows, both shown at once.
r = C.savingSessions({ upcoming: [hour(1, "10:00", true), hour(5, "13:00", true)] },
                     Date.parse("2026-10-01T17:20:00+01:00"));
check(r.length === 2, "11:00-12:00 and 14:00-15:00 are two rows", r.length);

// A booked hour more than 8 days out is not shown yet.
r = C.savingSessions({ upcoming: [hour(1, "10:00", true)] },
                     Date.parse("2026-09-24T09:00:00+01:00"));
check(r.length === 0, "a booked hour 10 days out is not shown yet", r.length);

// Anything that is not a free hour keeps the 24-hour window.
const td = { id: 9, direction: "TURN_DOWN", joined: true, points: 72,
             start: "2026-10-04T17:00:00+00:00", end: "2026-10-04T18:00:00+00:00" };
check(C.savingSessions({ upcoming: [td] }, Date.parse("2026-10-03T11:40:00+01:00")).length === 0,
      "a turn-down 30 hours out is still not shown");

done();
