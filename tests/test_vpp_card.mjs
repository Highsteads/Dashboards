/* Contract tests for the Cost page's Grid events (Axle VPP) card.
 *
 * Drives the SHIPPED refreshVpp() out of cost.html rather than a copy, so the
 * test locks what actually renders. Fixtures are the REAL shapes the ledger
 * produces — a fixture invented from the schema only tests the schema.
 *
 * Most of what follows is about ABSENCE. An unsettled event and an event
 * settled at nothing look identical on a table row and mean opposite things,
 * and settlement runs days behind, so the newest event is normally unsettled.
 * Rendering it as £0.00 would report a loss that never happened.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "cost.html");
const html = fs.readFileSync(PAGE, "utf8");

let pass = 0, fail = 0;
const ok = (name, cond) => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name); }
};
const section = (s) => console.log("\n== " + s + " ==");

/* Pull a function out of the shipped page by brace-matching. */
function extract(name) {
  const i = html.indexOf(name);
  if (i < 0) throw new Error("not found in cost.html: " + name);
  let d = 0, j = html.indexOf("{", i);
  do { if (html[j] === "{") d++; else if (html[j] === "}") d--; j++; } while (d > 0);
  return html.slice(i, j);
}

function run(payload, { fetchOk = true } = {}) {
  const els = new Map();
  const document = {
    getElementById(id) {
      if (!els.has(id)) els.set(id, { id, innerHTML: "", textContent: "", style: {} });
      return els.get(id);
    },
  };
  const ctx = {
    document, console,
    sigenFetch: async () => ({ ok: fetchOk, json: async () => payload }),
    esc: (t) => String(t == null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
  };
  vm.createContext(ctx);
  vm.runInContext(extract("function _vppMoney"), ctx);
  vm.runInContext(extract("async function refreshVpp"), ctx);
  return ctx.refreshVpp().then(() => ({
    visible: document.getElementById("vpp-card").style.display === "",
    get: (id) => document.getElementById(id).innerHTML,
    /* One BODY row, cells split out, entities and markup stripped. The header
       row carries <th> and no <td>, so filtering on <td> drops it — indexing
       past it by hand is how an off-by-one gets written into a test. */
    row: (n) => {
      const rows = document.getElementById("vpp-table").innerHTML
        .split("<tr>").filter((r) => r.includes("<td"));
      if (!rows[n]) return null;
      return rows[n].split("<td").slice(1).map((c) =>
        ("<td" + c.split("</td>")[0])
          .replace(/&#8212;/g, "—").replace(/&pound;/g, "£").replace(/&ndash;/g, "–")
          .replace(/<[^>]+>/g, "").trim());
    },
  }));
}

/* Real ledger output, 18-Aug-2026: 16 Aug driven and unsettled, 14 Aug settled
   with the ordinary baseline gap, 11 Aug settled with the over-run, 20 Apr
   settled at a genuine zero. */
const REAL = {
  lifetime_gbp: 87.6, available_gbp: 87.6, withdraw_threshold_gbp: 10,
  can_withdraw: true,
  by_kind: { events_gbp: 35.68, top_ups_gbp: 26.92, other_gbp: 25, withdrawals_gbp: 0 },
  events_total: 13, events_settled: 12, events_pending: 1,
  month_to_date_gbp: 19.3, axle_age_days: 0.1, load_error: null, next_event: null,
  events: [
    { start_local: "16 Aug 2026 20:00", end_local: "21:00", settled: false,
      paid_gbp: null, paid_kwh: null, our_kwh: 4.32, diff_kwh: null },
    { start_local: "14 Aug 2026 20:00", end_local: "21:00", settled: true,
      paid_gbp: 3.84, paid_kwh: 3.838, our_kwh: 4.23, diff_kwh: 0.392 },
    { start_local: "11 Aug 2026 19:30", end_local: "20:30", settled: true,
      paid_gbp: 3.8, paid_kwh: 3.801, our_kwh: 7.05, diff_kwh: 3.249 },
    { start_local: "20 Apr 2026 08:00", end_local: "09:00", settled: true,
      paid_gbp: 0, paid_kwh: 0, our_kwh: null, diff_kwh: null },
  ],
};
const clone = (o) => JSON.parse(JSON.stringify(o));

console.log("Cost page — Grid events card");

section("headline figures");
{
  const r = await run(clone(REAL));
  ok("card is shown once the ledger holds something", r.visible);
  ok("available balance", r.get("v-avail").includes("87.60"));
  ok("says it can be withdrawn", r.get("v-avail-sub").includes("ready"));
  ok("lifetime", r.get("v-life").includes("87.60"));
  ok("settled count", r.get("v-life-sub").includes("12 settled"));
  ok("month to date", r.get("v-month").includes("19.30"));
  ok("names the pending event", r.get("v-month-sub").includes("1 awaiting"));
}

section("grid earnings are kept apart from the rest");
{
  const r = await run(clone(REAL));
  const head = r.get("v-events"), sub = r.get("v-events-sub");
  ok("grid events alone", head.includes("35.68"));
  ok("does NOT quote the lifetime total as grid earnings", !head.includes("87.60"));
  ok("monthly floor shown separately", sub.includes("26.92"));
  ok("referral/bonus shown separately", sub.includes("25.00"));
}

section("an unsettled event is PENDING, never zero");
{
  const r = await run(clone(REAL));
  const row = r.row(0);
  ok("the newest row is the unsettled one", row[0].startsWith("16 Aug"));
  ok("its money cell reads pending", row[1].toLowerCase() === "pending");
  ok("its money cell carries no amount at all", !row[1].includes("£"));
  ok("its paid kWh is a dash, not 0.000", row[2] === "—");
}

section("an event genuinely settled at zero is DIFFERENT");
{
  const r = await run(clone(REAL));
  const row = r.row(3);
  ok("20 Apr is the zero-settled row", row[0].startsWith("20 Apr"));
  ok("it shows a real £0.00", row[1] === "£0.00");
  ok("and is not labelled pending", !row[1].toLowerCase().includes("pending"));
  ok("its paid kWh is a real 0.000", row[2] === "0.000");
}

section("the table carries AXLE'S figures and nothing else");
{
  /* Our own per-event export is measured over a different span from Axle's —
     the driver runs either side of the paid window — so showing the two side
     by side invited the reading that a wide gap meant Axle had short-changed
     us. It reads 7.05 against 3.801 on 11-Aug, and the paid hour was in fact
     textbook. The figure stays in the ledger; it is off the table. */
  const r = await run(clone(REAL));
  const head = r.get("vpp-table").split("<tbody>")[0];
  ok("three columns", (head.match(/<th>/g) || []).length === 3);
  ok("no 'our kWh' column", !/our/i.test(head));
  ok("no 'diff' column", !/diff/i.test(head));
  ok("every body row has three cells", r.row(0).length === 3);
  const body = r.get("vpp-table");
  ok("the 11-Aug run total is nowhere in the table", !body.includes("7.05"));
  ok("but its settled figure is", body.includes("3.801"));
}

section("a month with nothing settled is not a month of no earnings");
{
  const p = clone(REAL);
  p.month_to_date_gbp = null;
  const r = await run(p);
  ok("no amount is invented", !r.get("v-month").includes("£"));
  ok("it says so instead", r.get("v-month-sub").includes("nothing settled"));
}

section("the next window, or its honest absence");
{
  const r = await run(clone(REAL));
  ok("says no window is announced", r.get("vpp-sub").includes("no window announced"));

  const p = clone(REAL);
  p.next_event = { start_local: "19 Aug 20:00", end_local: "21:00",
                   seconds_until_start: 7200, seconds_until_end: 10800 };
  const r2 = await run(p);
  ok("names the window", r2.get("vpp-sub").includes("19 Aug 20:00"));
  ok("and how long until it opens", r2.get("vpp-sub").includes("2.0 h"));

  p.next_event.seconds_until_start = 1500;
  const r3 = await run(p);
  ok("under an hour counts in minutes", r3.get("vpp-sub").includes("25 min"));

  p.next_event.seconds_until_start = -60;
  const r4 = await run(p);
  ok("a window already open says so", r4.get("vpp-sub").includes("running now"));
}

section("stale Axle figures are declared");
{
  const p = clone(REAL);
  p.axle_age_days = 23.4;
  const r = await run(p);
  ok("the note says how old they are", r.get("vpp-note").includes("23 days ago"));

  const r2 = await run(clone(REAL));
  ok("and stays quiet when they are fresh", !r2.get("vpp-note").includes("days ago"));
}

section("the card stays out of the way when it has nothing");
{
  const r = await run({ lifetime_gbp: null, events: [] });
  ok("an empty ledger renders no card", !r.visible);

  const r2 = await run(clone(REAL), { fetchOk: false });
  ok("an older plugin with no /api/vpp renders no card", !r2.visible);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
