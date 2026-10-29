// Filename:    test_fav_page_links.mjs
// Description: Contract test for page-link favourites on the hub (3.68.0).
//
//              THE RULES
//              1. A page link sits among the live tiles in list order, so it
//                 can stand beside the tile it was pinned next to. It is not
//                 sent to the room-shortcut row.
//              2. It is an ANCHOR to the page, flagged readonly so the
//                 favourites click handler lets the browser navigate.
//              3. A typed label wins; without one a known page gets its name.
//              4. A pinned page's full-size nav card (Menu, Rooms) is hidden,
//                 the row goes once every card in it is hidden, and both come
//                 back when the page is unpinned or favourites are emptied.
// Author:      CliveS & Claude Opus 5.5
// Date:        29-10-2026
// Version:     1.0
//
// Run: node tests/test_fav_page_links.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");

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
function extractConst(s, name) {
    const start = s.indexOf("const " + name + " = {");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return "var " + s.slice(start + 6, j + 1) + ";"; }
    }
    throw new Error("unbalanced: " + name);
}

console.log("favourites — page links");

// The nav cards exactly as the shipped page writes them.
const navHrefs = [...src.matchAll(/<a class="card [^"]*" href="([^"]+)"/g)].map(m => m[1]);
check("the hub still has its Menu and Rooms cards",
      navHrefs.includes("menu.html") && navHrefs.includes("menu.html?g=rooms"));
const cards = navHrefs.map(h => ({ hidden: false, getAttribute: () => h }));
const grid = { hidden: false, querySelectorAll: () => cards };
const host = { id: "favourites", innerHTML: "", style: { display: "" } };
const ctx = vm.createContext({
    console,
    document: { getElementById: id => (id === "favourites" ? host : id === "grid" ? grid : null) },
    window: { INDIGO_CONFIG: { favourites: [
        { type: "device", id: 1, label: "Qashqai 12V", state: "voltage" },
        { type: "page", page: "flow.html", label: "Sigenergy" },
        { type: "page", page: "menu.html" },
        { type: "page", page: "menu.html?g=rooms" },
        { type: "room", room: "Living Room" },
    ] } },
    escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    DashAction: { repaint: () => {}, truthy: v => v === true },
});
vm.runInContext(extractConst(src, "FAV_PAGE_NOTES"), ctx);
for (const fn of ["spokenWhen", "hidePinnedNavCards", "renderFavouritesCard"]) vm.runInContext(extractFn(src, fn), ctx);
vm.runInContext("renderFavouritesCard([{ id: 1, name: 'Car', states: { voltage: 12.7 } }])", ctx);
const html = host.innerHTML;
const mainRow = html.slice(0, html.indexOf("fav-grid-rooms"));

check("page links sit in the main row", ["Sigenergy", ">Menu<", ">Rooms<"].every(t => mainRow.includes(t)));
check("in list order, after the reading they were pinned beside",
      mainRow.indexOf("Qashqai") < mainRow.indexOf("Sigenergy")
      && mainRow.indexOf("Sigenergy") < mainRow.indexOf(">Menu<")
      && mainRow.indexOf(">Menu<") < mainRow.indexOf(">Rooms<"));
check("they are anchors to the page", mainRow.includes('href="flow.html"')
      && mainRow.includes('href="menu.html"') && mainRow.includes('href="menu.html?g=rooms"'));
check("readonly, so a press navigates", (mainRow.match(/fav-pagelink" data-fav-type="page" data-fav-readonly="1"/g) || []).length === 3);
check("the typed label wins over the page's own name", mainRow.includes(">Sigenergy<") && !mainRow.includes(">Flow<"));
check("the Flow tile says what it opens", mainRow.includes("Power flow"));
check("the room shortcut keeps its own row", html.includes("fav-grid-rooms") && !mainRow.includes("Living Room"));
check("Menu and Rooms cards step aside once pinned", cards.every(c => c.hidden));
check("and the empty row goes with them", grid.hidden === true);

ctx.window.INDIGO_CONFIG.favourites = [{ type: "page", page: "menu.html" }];
vm.runInContext("renderFavouritesCard([])", ctx);
check("unpinning Rooms brings its card back", cards.find(c => c.getAttribute() === "menu.html?g=rooms").hidden === false
      && cards.find(c => c.getAttribute() === "menu.html").hidden === true && grid.hidden === false);

ctx.window.INDIGO_CONFIG.favourites = [];
vm.runInContext("renderFavouritesCard([])", ctx);
check("with no favourites both cards show", cards.every(c => !c.hidden) && grid.hidden === false);

ctx.window.INDIGO_CONFIG.favourites = [{ type: "page", page: 'x.html" onclick="evil' }];
vm.runInContext("renderFavouritesCard([])", ctx);
check("a hand-edited page cannot break out of the href", !host.innerHTML.includes('" onclick="'));

done();
