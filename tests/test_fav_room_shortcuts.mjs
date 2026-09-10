// Filename:    test_fav_room_shortcuts.mjs
// Description: Contract test for room shortcuts in the Favourites card
//              (v2.89.0) — a second row of links to room.html, under the live
//              device tiles.
//
//              THE RULES
//              1. Room favourites go on their OWN row and never mix into the
//                 device row: one is navigation, the other is live state.
//              2. They are ANCHORS with a real href, not buttons. A link
//                 should behave like a link, and it must still work if the
//                 delegated click handler is ever not wired.
//              3. The room name is URL-ENCODED. "Living Room" and "Bedroom 1"
//                 both contain a space, so an unencoded href is a broken link
//                 on the two rooms most likely to be pinned.
//              4. They carry the readonly flag, so the favourites click
//                 handler steps aside and the browser navigates natively
//                 instead of trying to toggle a device that isn't there.
// Author:      CliveS & Claude Opus 5
// Date:        28-08-2026
// Version:     1.0
//
// Run: node tests/test_fav_room_shortcuts.mjs   (exit 0 = pass)

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
const check = (w, ok) => { console.log((ok ? "  ok   " : "  FAIL ") + w); if (!ok) fails++; };

console.log("favourites — room shortcuts");

const host = { id: "favourites", innerHTML: "", style: { display: "" } };
const ctx = vm.createContext({
    console,
    document: { getElementById: id => (id === "favourites" ? host : null) },
    window: { INDIGO_CONFIG: { favourites: [
        { type: "device", id: 1, label: "A lamp" },
        { type: "room", room: "Living Room" },
        { type: "room", room: "Bedroom 1" },
        { type: "room", room: "Dining Room", label: "Dining" },
    ] } },
    escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    DashAction: { repaint: () => {} },
    DashIcons: { has: () => false, svg: () => "" },
});
vm.runInContext(extractFn(src, "renderFavouritesCard"), ctx);
vm.runInContext("renderFavouritesCard([{ id: 1, name: 'A lamp', onState: false }])", ctx);
const html = host.innerHTML;

check("a second row is rendered for the rooms", html.includes("fav-grid-rooms"));
check("all three rooms appear", ["Living Room", "Bedroom 1", "Dining"].every(n => html.includes(n)));
{
    // Assert the DEVICE row itself is clean, not merely that the rooms row
    // comes after it: dropping the filter renders each room in BOTH rows, and
    // an ordering check happily passes on that.
    const deviceRow = html.slice(0, html.indexOf("fav-grid-rooms"));
    check("rooms are NOT mixed into the device row",
          !/Living Room|Bedroom 1|Dining/.test(deviceRow));
    check("the device row holds only the device tile",
          (deviceRow.match(/class="fav-tile/g) || []).length === 1);
}
check("room shortcuts are anchors, not buttons",
      /<a class="fav-tile fav-roomlink"/.test(html));
check("each has a real href to room.html", (html.match(/href="room\.html\?room=/g) || []).length === 3);
check("the room name is URL-encoded — a space would break the two most likely picks",
      html.includes("room=Living%20Room") && html.includes("room=Bedroom%201"));
check("no raw space survives in an href", !/href="room\.html\?room=[^"]* /.test(html));
check("a custom label is used over the room name",
      html.includes(">Dining<") && !html.includes(">Dining Room<"));
check("readonly so the click handler steps aside and the link navigates",
      (html.match(/data-fav-readonly="1"/g) || []).length >= 3);
check("the device tile is still rendered", html.includes("A lamp"));

// A room entry with no name must be dropped, not rendered as a dead link.
ctx.window.INDIGO_CONFIG.favourites = [{ type: "room", room: "" }, { type: "room" }];
vm.runInContext("renderFavouritesCard([])", ctx);
check("a nameless room favourite is dropped, not drawn as a dead link",
      !host.innerHTML.includes("fav-roomlink"));

// Rooms alone must still show the card.
ctx.window.INDIGO_CONFIG.favourites = [{ type: "room", room: "Hall" }];
vm.runInContext("renderFavouritesCard([])", ctx);
check("room shortcuts alone still show the card",
      host.style.display === "block" && host.innerHTML.includes("room=Hall"));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
