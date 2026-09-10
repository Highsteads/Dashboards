// Filename:    test_sigen_visibility.mjs
// Description: The browser half of "the Sigenergy pages hide themselves when
//              the plugin is absent" (v3.13.0). The auth shim's flag default
//              and its DashFeatures notice, the menu dropping exactly the
//              three tiles, the hub hiding its Energy/Solar cards and the
//              banner while SAYING why, the hub never polling the proxy, and
//              each of the three pages guarding its boot. Demo mode forces the
//              flag on, and an old config.js without the key reads as present.
// Author:      CliveS & Claude Fable 5.1
// Date:        10-09-2026
// Version:     1.0
//
// Run: node tests/test_sigen_visibility.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE  = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read  = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const auth  = read("dashboards-auth.js");
const menu  = read("menu.html");
const hub   = read("index.html");
const energy = read("energy.html"), cost = read("cost.html"), laundry = read("laundry.html");

function extractFn(s, name) {
    const start = s.indexOf("function " + name + "(");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}
function extractLiteral(s, head) {
    const start = s.indexOf(head);
    if (start < 0) throw new Error("not found: " + head);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(s.indexOf("{", start), j + 1); }
    }
    throw new Error("unterminated: " + head);
}

let failed = 0;
function check(name, ok, why) {
    console.log((ok ? "  ok   " : "  FAIL ") + name + (why ? "   " + why : ""));
    if (!ok) failed++;
}

/* A tiny document: elements by id, a <main>, readyState, one listener bag. */
function fakeDocument(ids, readyState = "complete") {
    const els = {};
    for (const id of ids) els[id] = { id, style: {}, hidden: false, textContent: "", innerHTML: "" };
    const main = { innerHTML: "" };
    const listeners = {};
    return {
        els, main, listeners, readyState,
        getElementById: id => els[id] || null,
        querySelector: sel => (sel === "main" ? main : null),
        addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
        body: main,
    };
}

console.log("\ndashboards-auth.js — the flag and the notice");
check("sigenAvailable defaults to TRUE when config.js lacks the key",
      /window\.INDIGO_CONFIG\.sigenAvailable = \(cfg\.sigenAvailable !== false\);/.test(auth),
      "an upgrade must never hide pages that were there yesterday");
check("DashFeatures is published before the reflector early-return",
      auth.indexOf("window.DashFeatures = {") > 0 &&
      auth.indexOf("window.DashFeatures = {") < auth.indexOf("cfg.reflectorBlock === true"));
{
    const demo = auth.slice(auth.indexOf('window.INDIGO_CONFIG.apiKey = "demo";'));
    // Anchored to the START of a statement: a commented-out line still
    // contains the words, and a bare substring match let exactly that survive.
    check("demo mode forces the flag on",
          /^\s*window\.INDIGO_CONFIG\.sigenAvailable = true;/m.test(demo.slice(0, 300)),
          "the fixtures carry energy data whatever this server has");
}
{
    const src = extractFn(auth, "_dashSigenOn") + "\n" + extractFn(auth, "_dashSigenAbsent") +
                "\nglobalThis.__on = _dashSigenOn; globalThis.__absent = _dashSigenAbsent;";
    const run = (cfg, readyState) => {
        const document = fakeDocument([], readyState);
        const ctx = { window: { INDIGO_CONFIG: cfg }, document, console };
        vm.runInNewContext(src, ctx);
        return { r: ctx.__absent("Energy <b>"), document, on: ctx.__on() };
    };
    let t = run({ sigenAvailable: false });
    check("absent: returns true and draws the notice into <main>",
          t.r === true && /needs the SigenEnergyManager plugin/.test(t.document.main.innerHTML));
    check("absent: the page label is escaped", /Energy &lt;b&gt;/.test(t.document.main.innerHTML));
    check("absent: offers the way back", /href="index\.html"/.test(t.document.main.innerHTML));
    check("absent: sigen() reads false", t.on === false);
    t = run({ sigenAvailable: true });
    check("present: returns false and touches nothing", t.r === false && t.document.main.innerHTML === "");
    t = run({});
    check("no key at all: treated as present", t.r === false && t.on === true);
    t = run({ sigenAvailable: false }, "loading");
    check("absent while still loading: draws on DOMContentLoaded",
          t.document.main.innerHTML === "" && (t.document.listeners.DOMContentLoaded || []).length === 1);
    t.document.listeners.DOMContentLoaded[0]();
    check("...and then the notice is there", /needs the SigenEnergyManager plugin/.test(t.document.main.innerHTML));
}

console.log("\nmenu.html — exactly the three tiles go");
{
    const groups = vm.runInNewContext("(" + extractLiteral(menu, "const GROUPS = {") + ")", {});
    const ctx = {};
    vm.runInNewContext(extractFn(menu, "tileHidden") + "\nglobalThis.__h = tileHidden;", ctx);
    const tiles = [...groups.house.tiles, ...groups.tools.tiles];
    const hidden = cfg => tiles.filter(t => ctx.__h(t, cfg)).map(t => t[0]).sort();
    check("absent: energy, cost and laundry are dropped",
          JSON.stringify(hidden({ sigenAvailable: false })) === JSON.stringify(["cost.html", "energy.html", "laundry.html"]));
    check("present: nothing dropped", hidden({ sigenAvailable: true }).length === 0);
    check("no key: nothing dropped", hidden({}).length === 0 && hidden(undefined).length === 0);
    check("carbon still follows its own region flag",
          JSON.stringify(hidden({ carbon: false })) === JSON.stringify(["carbon.html"]));
    const tagged = tiles.filter(t => t.length > 5).map(t => t[0] + ":" + t[5]).sort();
    check("only those three tiles carry a needs-key, and it is sigen",
          JSON.stringify(tagged) === JSON.stringify(["cost.html:sigen", "energy.html:sigen", "laundry.html:sigen"]));
    check("the filter is the one the grid uses",
          /\.filter\(t => !tileHidden\(t, cfgM\)\)/.test(menu) && /tile\(\.\.\.t\.slice\(0, 5\)\)/.test(menu),
          "a sixth element must not leak into tile()'s arguments");
}

console.log("\nindex.html — the hub hides its cards and says why");
{
    const ctx = { console };
    vm.runInNewContext(extractFn(hub, "applySigenAvailability") + "\nglobalThis.__a = applySigenAvailability;", ctx);
    const run = cfg => {
        const document = fakeDocument(["energy-detail", "solar-now", "house-banner", "hub-feature-note", "weather-now"]);
        ctx.window = { INDIGO_CONFIG: cfg }; ctx.document = document;
        return { off: ctx.__a(), d: document.els };
    };
    let t = run({ sigenAvailable: false });
    check("absent: returns true", t.off === true);
    check("absent: energy, solar and banner hidden",
          ["energy-detail", "solar-now", "house-banner"].every(id => t.d[id].style.display === "none"));
    check("absent: the weather card is untouched", t.d["weather-now"].style.display !== "none");
    check("absent: the note is shown and names the plugin",
          t.d["hub-feature-note"].hidden === false && /SigenEnergyManager/.test(t.d["hub-feature-note"].textContent));
    t = run({ sigenAvailable: true });
    check("present: nothing hidden, note hidden and empty",
          t.off === false && t.d["energy-detail"].style.display !== "none" &&
          t.d["hub-feature-note"].hidden === true && t.d["hub-feature-note"].textContent === "");
    check("the note element exists in the markup", /<p id="hub-feature-note" class="muted" hidden><\/p>/.test(hub));
    const boot = extractFn(hub, "bootCommandCentre");
    check("boot applies the availability before polling",
          boot.indexOf("applySigenAvailability()") > 0 && boot.indexOf("applySigenAvailability()") < boot.indexOf("_refreshSigen();"));
    check("boot never starts the Sigen poll when absent",
          /if \(!_sigenOff\) \{\s*_refreshSigen\(\);\s*setInterval\(_refreshSigen, 30 \* 1000\);\s*\}/.test(boot));
    const rs = hub.slice(hub.indexOf("async function _refreshSigen()"), hub.indexOf("function _sigenMoney()"));
    check("_refreshSigen itself returns before asking the proxy",
          rs.indexOf("sigenAvailable === false) return;") > 0 && rs.indexOf("sigenAvailable === false) return;") < rs.indexOf("_msg(SIGEN_PROXY"));
    const rec = extractFn(hub, "renderEnergyCard");
    check("renderEnergyCard hides the card rather than saying 'device not found'",
          rec.indexOf('sigenAvailable === false) {') > 0 && rec.indexOf('sigenAvailable === false) {') < rec.indexOf("Sigen device not found"));
}

console.log("\nthe three pages guard their boot");
{
    const iE = energy.indexOf("DashFeatures.sigenAbsent('Energy')");
    check("energy: the guard sits before the first poll starts",
          iE > 0 && iE < energy.indexOf("fetchStatus();\n", iE) && iE < energy.indexOf("setInterval(fetchStatus"));
    const iC = cost.indexOf("DashFeatures.sigenAbsent('Cost')");
    check("cost: after the api-key redirect, before the poll",
          cost.indexOf("location.href = 'index.html'") < iC && iC < cost.indexOf("load(); setInterval(load, POLL_INTERVAL_MS)"));
    check("laundry: the guarded boot is the only boot",
          /if \(window\.DashFeatures && DashFeatures\.sigenAbsent\('Laundry'\)\) \{[\s\S]*?\} else \{\s*load\(\);\s*setInterval\(load, POLL_MS\);\s*\}/.test(laundry) &&
          (laundry.match(/^load\(\);$/mg) || []).length === 0);
    check("each page loads the auth shim (where DashFeatures lives)",
          [energy, cost, laundry].every(p => /<script src="dashboards-auth\.js">/.test(p)));
}

console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
