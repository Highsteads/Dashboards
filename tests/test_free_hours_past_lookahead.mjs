// Filename:    test_free_hours_past_lookahead.mjs
// Description: A booked free hour that runs on from one inside the 24-hour
//              lookahead must stay in the merged row, even if it starts past it.
//
//              WHY THIS EXISTS
//              03-Oct-2026: two booked hours, 11:00-13:00, showed as 11:00-12:00
//              on the hub and the Energy page. At 11:40 the day before, the first
//              hour began 23h20m ahead and the second 24h20m, so the per-row
//              lookahead cut the second hour before the merge could join them.
// Author:      CliveS & Claude Sonnet 5.5
// Date:        03-10-2026
// Version:     1.0
//
// Run: node tests/test_free_hours_past_lookahead.mjs   (exit 0 = pass)

import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { checkOk as check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages");
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

// Booked free hours are shown 48 hours ahead; everything else 24.
// 11:40 BST two days before: hour 1 is 47h20m away, hour 2 is 48h20m away.
const TWO_DAYS = "2026-10-02T11:40:00+01:00";
let r = C.savingSessions(oct, Date.parse(TWO_DAYS));
check(r.length === 1, "the two booked hours are one row", JSON.stringify(r));
check(r[0] && r[0].hours === 2, "and it says two hours", r[0] && r[0].hours);
check(r[0] && r[0].endMs === Date.parse("2026-10-04T12:00:00Z"), "ending at 13:00 BST");

// Before the first hour is inside the lookahead, nothing shows at all.
r = C.savingSessions(oct, Date.parse("2026-10-02T09:00:00+01:00"));
check(r.length === 0, "nothing shows while the first hour is past the lookahead");

// A day later both are inside the window anyway.
r = C.savingSessions(oct, Date.parse("2026-10-03T11:40:00+01:00"));
check(r.length === 1 && r[0].hours === 2, "the day before, still one two-hour row");

// An unbooked hour never rides in on the exemption.
r = C.savingSessions({ upcoming: [hour(1, "10:00", true), hour(3, "12:00", false)] },
                     Date.parse(TWO_DAYS));
check(r.length === 1 && r[0].hours === 1, "an unbooked hour is still left out");

// A gap breaks the chain: a later booked hour past the lookahead stays hidden...
r = C.savingSessions({ upcoming: [hour(1, "10:00", true), hour(5, "13:00", true)] },
                     Date.parse(TWO_DAYS));
check(r.length === 1 && r[0].hours === 1, "a booked hour with a gap before it stays cut");
// ...and shows, as its own row, once it is inside the window.
r = C.savingSessions({ upcoming: [hour(1, "10:00", true), hour(5, "13:00", true)] },
                     Date.parse("2026-10-03T11:40:00+01:00"));
check(r.length === 2, "11:00-12:00 and 14:00-15:00 are two rows the day before", r.length);

// Anything that is not a free hour keeps the 24-hour window.
const td = { id: 9, direction: "TURN_DOWN", joined: true, points: 72,
             start: "2026-10-04T17:00:00+00:00", end: "2026-10-04T18:00:00+00:00" };
check(C.savingSessions({ upcoming: [td] }, Date.parse("2026-10-03T11:40:00+01:00")).length === 0,
      "a turn-down 30 hours out is still not shown");

done();
