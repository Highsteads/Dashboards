/* Contract tests for the hub's VPP status and earnings rows.
 *
 * Drives the SHIPPED vppStatusRow / vppEarningsRow out of index.html.
 *
 * The interesting states here appear a handful of times a month, so they are
 * exactly the ones nobody notices being wrong. Two rules carry the weight:
 * a feed that cannot answer must never be drawn as "nothing scheduled", and
 * a figure that is not known must never be drawn as a number.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "index.html");
const html = fs.readFileSync(PAGE, "utf8");

let pass = 0, fail = 0;
const ok = (name, cond) => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name); }
};
const section = (s) => console.log("\n== " + s + " ==");

function extract(name) {
  const i = html.indexOf(name);
  if (i < 0) throw new Error("not found in index.html: " + name);
  let d = 0, j = html.indexOf("{", i);
  do { if (html[j] === "{") d++; else if (html[j] === "}") d--; j++; } while (d > 0);
  return html.slice(i, j);
}

const ctx = {
  console,
  escapeAttr: (t) => String(t == null ? "" : t)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;"),
};
vm.createContext(ctx);
vm.runInContext(extract("function vppStatusRow"), ctx);
vm.runInContext(extract("function vppEarningsRow"), ctx);

const text = (h) => h.replace(/&middot;/g, "·").replace(/&pound;/g, "£")
                     .replace(/<[^>]+>/g, "").trim();
const cls = (h) => (h.match(/class="val ([^"]*)"/) || [, ""])[1].trim();

console.log("Hub — VPP rows");

section("the row is permanent, and says so when there is nothing on");
{
  const h = ctx.vppStatusRow({ state: "idle", active: false, event_str: "", api_status: "OK" });
  ok("a row is drawn on a quiet day", h.includes("VPP"));
  ok("and it says none announced", text(h).includes("None announced"));
  ok("with no alarm colour", cls(h) === "");
}

section("a running or announced window");
{
  const run = ctx.vppStatusRow({ state: "active", active: true, event_str: "20:00-21:00", api_status: "OK" });
  ok("running is named", text(run).includes("Running"));
  ok("with the window", text(run).includes("20:00-21:00"));
  ok("and marked as happening now", cls(run) === "warn");

  const ann = ctx.vppStatusRow({ state: "announced", active: false, event_str: "20:00-21:00",
                                 api_status: "OK", next_event: { seconds_until_start: 7200 } });
  ok("announced is named", text(ann).includes("Announced"));
  ok("with hours to go", text(ann).includes("in 2.0 h"));
  ok("marked as good news", cls(ann) === "ok");

  const soon = ctx.vppStatusRow({ state: "announced", active: false, event_str: "20:00-21:00",
                                  api_status: "OK", next_event: { seconds_until_start: 900 } });
  ok("under an hour counts in minutes", text(soon).includes("in 15 min"));

  const open = ctx.vppStatusRow({ state: "announced", active: false, event_str: "20:00-21:00",
                                  api_status: "OK", next_event: { seconds_until_start: -30 } });
  ok("a window already open claims no countdown", !text(open).includes("in "));
}

section("A DEAD FEED IS NOT A QUIET FORTNIGHT");
{
  const h = ctx.vppStatusRow({ state: "idle", active: false, event_str: "",
                               api_status: "Authentication failed (401) - token rejected by Axle" });
  ok("the failure is reported", text(h).includes("Feed failing"));
  ok("and names it", text(h).includes("401"));
  ok("it is NOT reported as nothing scheduled", !text(h).includes("None announced"));
  ok("and it is coloured as a problem", cls(h) === "warn");
}

section("nothing from the plugin at all");
{
  ok("no VPP block means no row", ctx.vppStatusRow(null) === "");
  ok("and no money row", ctx.vppEarningsRow(null) === "");
}

section("an older SigenEnergyManager degrades quietly");
{
  /* Before v5.72.0 the block carried state/active/event_str and nothing else. */
  const old = { state: "idle", active: false, event_str: "" };
  const h = ctx.vppStatusRow(old);
  ok("the status row still renders", text(h).includes("None announced"));
  ok("an absent api_status is not read as a failure", !text(h).includes("Feed failing"));
  ok("and no earnings are invented", ctx.vppEarningsRow(old) === "");
}

section("earnings are shown only when known");
{
  const h = ctx.vppEarningsRow({ earnings: { month_to_date_gbp: 19.3, lifetime_gbp: 87.6,
                                             events_pending: 1 } });
  ok("this month leads", text(h).includes("£19.30"));
  ok("lifetime rides alongside", text(h).includes("£87.60 lifetime"));
  ok("and pending events are flagged", text(h).includes("1 pending"));

  const noMonth = ctx.vppEarningsRow({ earnings: { month_to_date_gbp: null, lifetime_gbp: 87.6,
                                                   events_pending: 0 } });
  ok("a month with nothing settled falls back to lifetime", text(noMonth).includes("£87.60 lifetime"));
  ok("and does NOT invent a zero for the month", !text(noMonth).includes("£0.00"));

  const nothing = ctx.vppEarningsRow({ earnings: { month_to_date_gbp: null, lifetime_gbp: null } });
  ok("nothing known at all draws no row", nothing === "");

  const zeroMonth = ctx.vppEarningsRow({ earnings: { month_to_date_gbp: 0, lifetime_gbp: 87.6 } });
  ok("a genuine zero month IS shown as zero", text(zeroMonth).includes("£0.00"));
}

section("text from the API is escaped — in EVERY branch that interpolates it");
{
  /* `event_str` is built into two separate branches and `api_status` into a
     third. A mutation that dropped the escaping from the running branch
     survived a suite that only exercised the announced one — testing one
     branch is not testing its sibling. */
  const EVIL = '<img src=x onerror=alert(1)>';

  const ann = ctx.vppStatusRow({ state: "announced", active: false,
                                 event_str: EVIL, api_status: "OK" });
  ok("announced branch escapes the window text", !ann.includes("<img"));

  const run = ctx.vppStatusRow({ state: "active", active: true,
                                 event_str: EVIL, api_status: "OK" });
  ok("running branch escapes it too", !run.includes("<img"));

  const bad = ctx.vppStatusRow({ state: "idle", active: false, event_str: "",
                                 api_status: EVIL });
  ok("the feed-failure branch escapes its message", !bad.includes("<img"));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
