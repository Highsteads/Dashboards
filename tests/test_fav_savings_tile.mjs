// Filename:    test_fav_savings_tile.mjs
// Description: The hub's Savings tile shows the amount saved (3.71.1).
//
//              THE RULES
//              1. The line is the "since records began" saving, in whole
//                 pounds with commas: "£1,848 saved". A loss says "behind".
//                 With a system cost set, the share paid back follows,
//                 rounded as the Savings page rounds it, never 100% early (3.71.2).
//              2. No usable figure leaves the tile's ordinary line.
//              3. The hub asks only while a Savings tile is pinned, paints any
//                 tile already on screen, and a figure it has survives the
//                 next redraw of the favourites.
//              4. It is asked for only when SigenEnergyManager is present.
//              5. The tile turns green exactly when it says "paid for itself",
//                 on screen at once and after a redraw, and back if it stops (3.71.3).
// Author:      CliveS & Claude Opus 5.5
// Date:        23-11-2026
// Version:     1.0
//
// Run: node tests/test_fav_savings_tile.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");

function extract(s, name, kind) {
    const start = kind === "const" ? s.indexOf("const " + name + " = {")
                                   : s.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") {
            depth--;
            if (!depth) return kind === "const" ? "var " + s.slice(start + 6, j + 1) + ";" : s.slice(start, j + 1);
        }
    }
    throw new Error("unbalanced: " + name);
}

console.log("hub — the Savings tile");

const host = { id: "favourites", innerHTML: "", style: { display: "" } };
const tileClasses = new Set();
const tileEl = { classList: { toggle: (c, on) => { if (on) tileClasses.add(c); else tileClasses.delete(c); } } };
const painted = [{ textContent: "Open page", closest: () => tileEl }];
let asked = 0;
let reply = { periods: { all: { saved: 1848.4 } } };
const timers = [];
const ctx = vm.createContext({
    console,
    window: { INDIGO_CONFIG: { favourites: [{ type: "page", page: "savings.html", label: "Savings" }] } },
    document: {
        hidden: false,
        getElementById: id => (id === "favourites" ? host : null),
        querySelectorAll: sel => (sel.includes('href="savings.html"') ? painted : []),
    },
    escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    DashAction: { repaint: () => {}, truthy: v => v === true },
    hidePinnedNavCards: () => {},
    _msg: async (name) => { asked++; return name === "savingsReport" ? reply : null; },
    setTimeout: (fn, ms) => { timers.push(ms); },
});
vm.runInContext(extract(src, "FAV_PAGE_NOTES", "const"), ctx);
for (const fn of ["spokenWhen", "savingsTileNote", "savingsPaidOff", "_refreshSavingsTile", "renderFavouritesCard"]) {
    vm.runInContext(extract(src, fn), ctx);
}

// 1, 2: the words
const note = r => vm.runInContext("savingsTileNote", ctx)(r);
check("since records began, whole pounds with a comma", note({ periods: { all: { saved: 1848.4 } } }) === "£1,848 saved");
check("a loss says behind", note({ periods: { all: { saved: -12.6 } } }) === "£13 behind");
check("with a cost set, the share paid back follows",
      note({ periods: { all: { saved: 1848.4 } }, payback: { pct: 6.98 } }) === "\u00a31,848 saved, 7% paid back");
check("rounded as the Savings page rounds it, but never 100% before it is",
      note({ periods: { all: { saved: 1 } }, payback: { pct: 99.9 } }) === "\u00a31 saved, 99% paid back");
check("under one per cent says so", note({ periods: { all: { saved: 50 } }, payback: { pct: 0.4 } }) === "\u00a350 saved, under 1% paid back");
check("all of it back says so", note({ periods: { all: { saved: 30000 } }, payback: { pct: 113.3 } }) === "\u00a330,000 saved, paid for itself");
check("no cost set, no percentage", note({ periods: { all: { saved: 10 } }, payback: null }) === "\u00a310 saved");
check("no figure, no line", note(null) === null && note({ periods: {} }) === null
      && note({ periods: { all: { saved: "x" } } }) === null);

// 5: green exactly when it says paid for itself
const green = r => vm.runInContext("savingsPaidOff", ctx)(r);
check("paid for itself is green", green({ periods: { all: { saved: 30000 } }, payback: { pct: 100 } }) === true);
check("99.9% is not green", green({ periods: { all: { saved: 1 } }, payback: { pct: 99.9 } }) === false);
check("no cost set is not green", green({ periods: { all: { saved: 10 } }, payback: null }) === false);
check("no figure is not green", green(null) === false && green({ periods: {}, payback: { pct: 150 } }) === false);
for (const p of [0, 0.4, 6.98, 99.4, 99.9, 100, 113.3]) {
    const r = { periods: { all: { saved: 100 } }, payback: { pct: p } };
    check(`green and the words agree at ${p}%`, green(r) === note(r).endsWith("paid for itself"));
}

// 3: before any figure the tile reads as usual
vm.runInContext("renderFavouritesCard([])", ctx);
check("before a figure the tile says Open page", host.innerHTML.includes(">Open page<"));

await vm.runInContext("_refreshSavingsTile()", ctx);
check("asked once", asked === 1);
check("the tile on screen is painted at once", painted[0].textContent === "£1,848 saved");
vm.runInContext("renderFavouritesCard([])", ctx);
check("and the figure survives the next redraw", host.innerHTML.includes("£1,848 saved"));

check("not paid off, not green", !tileClasses.has("fav-paidoff") && !host.innerHTML.includes("fav-paidoff"));

// paid off: green on screen at once and after a redraw
reply = { periods: { all: { saved: 30000 } }, payback: { pct: 113.3 } };
await vm.runInContext("_refreshSavingsTile()", ctx);
check("paid off turns the tile on screen green", tileClasses.has("fav-paidoff"));
vm.runInContext("renderFavouritesCard([])", ctx);
check("and it stays green after a redraw", host.innerHTML.includes("fav-pagelink fav-paidoff"));
reply = { periods: { all: { saved: 1848.4 } }, payback: { pct: 6.98 } };
await vm.runInContext("_refreshSavingsTile()", ctx);
vm.runInContext("renderFavouritesCard([])", ctx);
check("and back to plain if it stops being true", !tileClasses.has("fav-paidoff") && !host.innerHTML.includes("fav-paidoff"));
check("the green is one fixed colour with white words",
      /\.fav-tile\.fav-paidoff\s*\{\s*background:\s*#267347;/.test(src) && /\.fav-tile\.fav-paidoff \.fav-state\s*\{\s*color:\s*#fff/.test(src));

// no figure yet: try again in a minute
reply = null;
ctx.window.__FAV_PAGE_LIVE = undefined;
await vm.runInContext("_refreshSavingsTile()", ctx);
check("with no figure yet it asks again after a minute", timers.includes(60000));

// not pinned: not asked
ctx.window.INDIGO_CONFIG.favourites = [{ type: "page", page: "flow.html" }];
asked = 0;
await vm.runInContext("_refreshSavingsTile()", ctx);
check("not pinned, not asked", asked === 0);

// 4: started only with SigenEnergyManager present
const boot = extract(src, "bootCommandCentre");
const call = boot.indexOf("_refreshSavingsTile();");
const opens = boot.lastIndexOf("if (", call);
const sigenBlock = call > 0 && boot.slice(opens, opens + 17) === "if (!_sigenOff) {"
    ? boot.slice(opens, boot.indexOf("}", call)) : "";
check("the poll starts inside the SigenEnergyManager-present block", sigenBlock.includes("_refreshSavingsTile();")
      && sigenBlock.includes("setInterval(_refreshSavingsTile, 15 * 60 * 1000)"));

done();
