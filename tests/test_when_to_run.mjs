// Filename:    test_when_to_run.mjs
// Description: The "When to run it" card on the Energy page (v3.34.0), which
//              replaced the Laundry and Carbon pages. Runs when-to-run.js's own
//              functions: freshness, clock wording, the half-hour list said
//              once when every slot is the same, deadline chips only where a
//              deadline means something, the carbon half, and the card hiding
//              each half (and itself) when there is nothing to say. Carries on
//              every behaviour test_laundry_page.mjs pinned.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(DIR, f), "utf8");
const src = read("when-to-run.js");

const ctx = { console, Math, Date, JSON, String, Number, Object, Promise, setTimeout, clearTimeout, setInterval, clearInterval };
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(read("dashboards-ui.js"), ctx);          // the real DashUI.esc and DashUI.ago
vm.runInContext(src, ctx);
const T = ctx.WhenToRun._t;

console.log("\nfreshness");
check("nothing has arrived yet is not stale", !T.freshness(undefined).stale && !T.freshness(NaN).stale && !T.freshness(-5).stale);
check("a fresh poll is not stale", !T.freshness(0).stale && !T.freshness(195000).stale);
{
    const f = T.freshness(240000);
    check("three missed polls is stale, and says how long", f.stale && /not updating for 4 minutes/.test(f.text), f.text);
}
check("the freshness readout runs on its own timer", /setInterval\(markFresh/.test(src));
check("lastGood is stamped only where data arrives, never in a catch",
      (src.match(/lastGood = Date\.now\(\)/g) || []).length === 3 && !/catch[\s\S]{0,120}lastGood = Date\.now\(\)/.test(src));

console.log("\ntimes read the way a person says them");
{
    const at = (h, m) => T.clock(new Date(2026, 5, 15, h, m).toISOString());
    check("4pm", at(16, 0) === "4pm");
    check("1:01pm", at(13, 1) === "1:01pm");
    check("9:30am", at(9, 30) === "9:30am");
    check("12pm and 12am", at(12, 0) === "12pm" && at(0, 0) === "12am");
}

console.log("\nthe half-hour list");
{
    const shape = (options) => T.shapeCard({ options, start: options.length ? options[0].start : null, appliance: { kwh: 0.74 } });
    const allFree = Array.from({ length: 45 }, (_, i) =>
        ({ start: new Date(2026, 5, 15, 10 + (i >> 1), (i % 2) * 30).toISOString(), grid_kwh: 0, cost_p: 0 }));
    const h = shape(allFree);
    check("every slot free is said once, not listed", /All 45 of them come out the same/.test(h) && !/class="slot/.test(h));
    const differ = shape([
        { start: new Date(2026, 5, 15, 10, 0).toISOString(), grid_kwh: 0.0, cost_p: 0 },
        { start: new Date(2026, 5, 15, 11, 0).toISOString(), grid_kwh: 0.4, cost_p: 10 },
        { start: new Date(2026, 5, 15, 12, 0).toISOString(), grid_kwh: 0.74, cost_p: 28 }]);
    check("a day that differs is listed row by row", (differ.match(/class="slot/g) || []).length === 3 && /28p/.test(differ));
    check("a zero-grid slot is marked free", /slot free/.test(differ) && />free</.test(differ));
    check("it is folded away, not a wall on the card", /^<details>/.test(differ));
    check("no options, or one, draws nothing", T.shapeCard({ options: [] }) === "" && T.shapeCard(null) === "" &&
          shape([{ start: new Date().toISOString(), grid_kwh: 0.2, cost_p: 5 }]) === "");
}

console.log("\none block per appliance");
{
    const planned = { key: "washing_machine", label: "the washing machine", state: "planned",
        message: "Put the washing machine on now. It should finish about 4:31pm", appliance: { kwh: 1, minutes: 61, measured_from: "47 cycles" },
        solar_kwh: 0.5, battery_kwh: 0.3, grid_kwh: 0.2, options: [] };
    const b = T.applianceBlock(planned);
    check("the verdict is the first sentence", /wr-verdict">Put the washing machine on now\./.test(b));
    check("chips name their appliance", /data-key="washing_machine"/.test(b));
    check("the split adds up", /Sun 50%/.test(b) && /Battery 30%/.test(b) && /Grid 20%/.test(b));
    check("the machine's own measurements are named", /61 minutes and 1 kWh, measured from 47 cycles of its own/.test(b));
    const running = T.applianceBlock({ ...planned, state: "running" });
    check("no chips where a deadline means nothing", !/class="chips"/.test(running));
    check("no_plan still offers chips", /class="chips"/.test(T.applianceBlock({ ...planned, state: "no_plan" })));
    check("the request carries the appliance key", /appliance: key/.test(src) && /setDeadline\(btn\.dataset\.key, btn\.dataset\.v/.test(src));
    const none = T.laundryHtml({ appliances: [] });
    check("nothing metered says what to add", /Nothing is metered yet/.test(none) && /Appliance Monitor device/.test(none));
    check("a hostile label is escaped", !/<script>/.test(T.applianceBlock({ ...planned, message: "<script>x</script>. y" })));
}

console.log("\nthe carbon half");
{
    const d = { carbon: { region: "North England", current: { intensity: 123.4, index: "low" },
                          best: { from: new Date(2026, 5, 15, 13, 30).toISOString() },
                          forecast: [{ from: "a", intensity: 1, index: "low" }],
                          mix: [{ fuel: "wind", perc: 40 }, { fuel: "gas", perc: 0 }] },
                advice: { level: "good", action: "run_now", headline: "Run it now", detail: "2 kW spare" } };
    const h = T.carbonHtml(d);
    check("the advice leads", /wr-tag good">Run now/.test(h) && /Run it now/.test(h));
    check("grid carbon is a whole number with its band", />123<span/.test(h) && />low</.test(h));
    check("the cleanest time reads like a person", /1:30pm/.test(h));
    check("a fuel at zero drops out of the mix", /wind/.test(h) && !/>gas</.test(h));
    check("a chart slot exists when there is a forecast", /wr-chart/.test(h));
    const down = T.carbonHtml({ carbon: { error: "x", current: {} }, advice: {} });
    const warm = T.carbonHtml({ carbon: { warming: true, current: {} }, advice: {} });
    check("while warming up there is a dash, never NaN", !/NaN/.test(warm) && /fetching grid data/.test(warm));
    check("a dead API says so rather than showing a number", /grid data unavailable/.test(down) && /v">—</.test(down));
}

console.log("\nthe card hides what it cannot say");
{
    const el = () => ({ hidden: false, innerHTML: "", querySelectorAll: () => [], querySelector: () => null, textContent: "", classList: { toggle() {} } });
    const calls = [];
    ctx.DashUI.poll = (fn) => { calls.push(fn.name); return { stop() {} }; };
    const mk = (cfg) => { calls.length = 0; const o = { card: el(), label: el(), laundryEl: el(), carbonEl: el(), freshEl: el(), cfg };
        const r = ctx.WhenToRun.mount(o); if (r) r.stop(); return o; };
    let o = mk({ carbon: false, scripts: { laundry: false } });
    check("both off: the card and its label go", o.card.hidden && o.label.hidden && calls.length === 0);
    o = mk({ carbon: false, scripts: { laundry: true } });
    check("carbon off: only the carbon half goes, and is not polled", o.carbonEl.hidden && !o.laundryEl.hidden && calls.join() === "loadLaundry");
    o = mk({ scripts: { laundry: false } });
    check("no scheduler script: only the laundry half goes", o.laundryEl.hidden && !o.carbonEl.hidden && calls.join() === "loadCarbon");
    o = mk({});
    check("an older config.js shows both", !o.laundryEl.hidden && !o.carbonEl.hidden && calls.length === 2);
}

console.log("\na refusal and a failed poll (lows batch [53] [54])");
{
    const cls = () => { const set = new Set(); return { set, add: c => set.add(c), remove: c => set.delete(c), toggle() {}, contains: c => set.has(c) }; };
    const head = { textContent: "" };
    const el = () => ({ hidden: false, innerHTML: "", querySelectorAll: () => [], querySelector: q => (q === ".wr-head" ? head : null),
                        textContent: "", classList: cls() });
    const fns = {};
    const oldPoll = ctx.DashUI.poll, oldMsg = ctx.DashUI.message;
    ctx.DashUI.poll = (fn) => { fns[fn.name] = fn; return { stop() {} }; };
    let reply = null;
    ctx.DashUI.message = async () => { if (reply instanceof Error) throw reply; return reply; };
    const o = { card: el(), label: el(), laundryEl: el(), carbonEl: el(), freshEl: el(), cfg: {} };
    const r = ctx.WhenToRun.mount(o);
    reply = { ok: false, error: "no plan yet — Appliance_Scheduler.py has not run" };
    await fns.loadLaundry();
    check("an ok:false plan shows its own reason", /Appliance_Scheduler\.py has not run/.test(o.laundryEl.innerHTML), o.laundryEl.innerHTML);
    check("and not the metering-plug advice", !/Nothing is metered yet/.test(o.laundryEl.innerHTML));
    const RealDate = ctx.Date;
    let NOW = RealDate.now();
    ctx.Date = class extends RealDate { static now() { return NOW; } };
    reply = { ok: true, appliances: [] , note: "N" };
    await fns.loadLaundry();
    const good = o.laundryEl.innerHTML;
    NOW += 10 * 60000;
    reply = { ok: false, error: "gone" };
    await fns.loadLaundry();
    check("a later refusal leaves the good plan on screen", o.laundryEl.innerHTML === good && !/gone/.test(o.laundryEl.innerHTML));
    check("and does not count as fresh data: the card reads out of date", /not updating/.test(o.freshEl.textContent), o.freshEl.textContent);
    ctx.Date = RealDate;

    reply = { carbon: { current: { intensity: 123, index: "low" }, region: "North East" }, advice: { headline: "Run it now", action: "run_now" } };
    await fns.loadCarbon();
    check("carbon draws", /Run it now/.test(o.carbonEl.innerHTML));
    reply = new Error("the Dashboards plugin is restarting");
    await fns.loadCarbon();
    check("one failed carbon poll keeps the good card", /Run it now/.test(o.carbonEl.innerHTML) && !/Could not reach/.test(o.carbonEl.innerHTML));
    check("and marks it out of date", o.carbonEl.classList.contains("stale") && /not updated/.test(head.textContent), head.textContent);
    const o2 = { card: el(), label: el(), laundryEl: el(), carbonEl: el(), freshEl: el(), cfg: {} };
    const r2 = ctx.WhenToRun.mount(o2);
    await fns.loadCarbon();
    check("with nothing to keep, the error is shown", /Could not reach the carbon data/.test(o2.carbonEl.innerHTML));
    r.stop(); r2.stop();
    ctx.DashUI.poll = oldPoll; ctx.DashUI.message = oldMsg;
}

console.log("\nthe old pages forward to the card");
for (const f of ["carbon.html", "laundry.html"]) {
    const s = read(f);
    check(f + " goes to Energy's card", /location\.replace\("energy\.html#when-card"\)/.test(s) && /http-equiv="refresh"/.test(s));
}
check("Energy loads the card and has somewhere to put it",
      read("energy.html").includes('<script src="when-to-run.js"></script>') && read("energy.html").includes('id="when-card"'));

done();
