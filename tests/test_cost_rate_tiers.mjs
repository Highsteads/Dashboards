/* Contract tests for the Cost page's Rates tiles.
 *
 * Drives the SHIPPED renderTariffSides() out of cost.html. The fixture is the
 * real /api/status shape SigenEnergyManager 5.110.0 sends on paired Octopus
 * Flux (region F prices, 17-Sep-2026), so it tests what the plugin produces.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import vm from "node:vm";

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");
const html = fs.readFileSync(path.join(PAGES, "cost.html"), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond) => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name); }
};

function extract(name) {
  const i = html.indexOf(name);
  if (i < 0) throw new Error("not found in cost.html: " + name);
  let d = 0, j = html.indexOf("{", i);
  do { if (html[j] === "{") d++; else if (html[j] === "}") d--; j++; } while (d > 0);
  return html.slice(i, j);
}

const tier = (label, p, windows, current = false) => ({ label, p, current,
  windows: windows.map(([start, end, cur]) => ({ start, end, current: !!cur })) });

const FLUX = {
  import_side: { name: "Octopus Flux Import", banded: true, now_p: 34.0999, tiers: [
    tier("Off-peak", 14.6184, [["02:00", "05:00"]]),
    tier("Day", 24.3543, [["05:00", "16:00"], ["19:00", "02:00"]]),
    tier("Peak", 34.0999, [["16:00", "19:00", true]], true),
  ]},
  export_side: { name: "Octopus Flux Export", banded: true, now_p: 27.6905, tiers: [
    tier("Off-peak", 4.2064, [["02:00", "05:00"]]),
    tier("Day", 9.7084, [["05:00", "16:00"], ["19:00", "02:00"]]),
    tier("Peak", 27.6905, [["16:00", "19:00", true]], true),
  ]},
};

function run(tariff) {
  const els = new Map();
  const document = {
    getElementById(id) {
      if (!els.has(id)) els.set(id, { id, innerHTML: "", textContent: "", hidden: false });
      return els.get(id);
    },
  };
  const ctx = { document, console,
    setText: (id, v) => { document.getElementById(id).textContent = String(v); } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(PAGES, "energy-calc.js"), "utf8")
    .replace(/^/, "var window = this;\n"), ctx);
  ctx.DashCalc = ctx.window.DashCalc;
  vm.runInContext(extract("function esc("), ctx);
  vm.runInContext(extract("function tierRows("), ctx);
  vm.runInContext(extract("function renderTariffSide("), ctx);
  vm.runInContext(extract("function renderTariffSides("), ctx);
  ctx.renderTariffSides({ tariff });
  return (id) => document.getElementById(id);
}

const text = (h) => h.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

{
  const el = run(FLUX);
  const imp = el("tar-tiers").innerHTML, exp = el("exp-tiers").innerHTML;
  ok("banded import shows its tier list, not the single figure",
     el("tar-banded").hidden === false && el("tar-flat").hidden === true);
  ok("banded export shows its tier list", el("exp-banded").hidden === false && el("exp-flat").hidden === true);
  ok("three import rows", (imp.match(/<li /g) || []).length === 3);
  ok("three export rows", (exp.match(/<li /g) || []).length === 3);
  ok("import prices, cheapest first", /Off-peak.*14\.62.*Day.*24\.35.*Peak.*34\.1/.test(text(imp)));
  ok("export prices, cheapest first", /Off-peak.*4\.21.*Day.*9\.71.*Peak.*27\.69/.test(text(exp)));
  ok("every window is shown with its hours",
     text(imp).includes("02:00 to 05:00") && text(imp).includes("05:00 to 16:00 and 19:00 to 02:00")
     && text(imp).includes("16:00 to 19:00"));
  ok("only the band in force is marked now", (imp.match(/class="tier now"/g) || []).length === 1
     && /class="tier now"><span class="tier-name">Peak/.test(imp));
  ok("tariff names shown", el("tar-banded-name").textContent === "Octopus Flux Import"
     && el("exp-banded-name").textContent === "Octopus Flux Export");
}
{
  const el = run({ import_side: { banded: false, tiers: [] },
                   export_side: { banded: false, tiers: [], name: "Outgoing Octopus", now_p: 12 } });
  ok("a flat tariff keeps the single-figure layout",
     el("tar-flat").hidden === false && el("tar-banded").hidden === true && el("exp-flat").hidden === false);
  ok("a flat export side names its tariff", el("exp-name").textContent === "Outgoing Octopus");
}
{
  const el = run({});
  ok("an older plugin with no sides falls back to flat, not blank",
     el("tar-flat").hidden === false && el("exp-flat").hidden === false);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
