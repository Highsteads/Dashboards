// Filename:    test_settings_save_keeps.mjs
// Description: A Settings Save must not change what it was not asked to
//              change (3.73.4, review 26-11-2026). Relatives of the door
//              fault fixed in 3.73.3:
//                - a pulse door stored without pulseMs / openWhenContactOnState
//                  had both written from the FORM's defaults (2000 ms, "on
//                  means open"), which are the opposite of the room page's
//                  (1500 ms, off means open): any Save inverted the tile;
//                - a door favourite whose action group or lock had gone from
//                  Indigo was deleted by any Save;
//                - a scene favourite whose action group had gone was saved
//                  with the picker's "(not found ...)" text as its label;
//                - text typed in the Raw JSON box was thrown away by Save;
//                - "+ Add room override" for a room that already had a panel
//                  added a blank one, and Save then wiped that room's lists.
//              Runs the shipped settings.html functions.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_settings_save_keeps.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src = fs.readFileSync(path.join(PAGES, "settings.html"), "utf8");
const room = fs.readFileSync(path.join(PAGES, "room.html"), "utf8");

function extractFn(s, name) {
    const start = s.search(new RegExp("function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unbalanced: " + name);
}
const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const ctx = vm.createContext({ console, esc, window: {},
    strToIds: s => String(s || "").split(",").map(x => parseInt(x.trim(), 10)).filter(n => !isNaN(n)),
    GROUPS: [{ id: 1, name: "Open Garage" }, { id: 2, name: "Close Garage" }],
    DEVICES: [{ id: 50, name: "Front Door Lock" }], FAV_PAGES: [] });
for (const fn of ["doorFromRow", "doorActionOptions", "doorLockOptions", "favOptionsHtml", "collectFavourites",
                  "rawUnapplied", "findRoomPanel"]) vm.runInContext(extractFn(src, fn), ctx);
const run = (expr, vars) => { Object.assign(ctx, vars); return JSON.parse(JSON.stringify(vm.runInContext(expr, ctx))); };

console.log("a pulse door keeps what it was stored with");
const doorRow = (stored, f) => ({ dataset: { orig: JSON.stringify(stored) }, querySelector: sel => ({
    ".d-label": { value: f.label }, ".d-relays": { value: f.relays }, ".d-pulse": { value: f.pulse },
    ".d-contact": { value: f.contact }, ".d-openon": { checked: f.openOn } }[sel] || null) });
const BARE = { label: "Side Gate", relayIds: [11], statusContactId: 33 };
check("the form shows the room page's own pulse default",
      /door\.pulseMs \|\| 1500/.test(src) && /door\.pulseMs \|\| 1500/.test(room));
check("and ticks 'on means open' only where it was stored so, as the room page reads it",
      /door\.openWhenContactOnState === true \? "checked"/.test(src) && /!!door\.openWhenContactOnState/.test(room));
checkEq("an unchanged row saves the door as it was stored",
        run("doorFromRow(r)", { r: doorRow(BARE, { label: "Side Gate", relays: "11", pulse: "1500", contact: "33", openOn: false }) }), BARE);
checkEq("a key this page has never heard of survives",
        run("doorFromRow(r)", { r: doorRow({ ...BARE, zz: [1] }, { label: "Side Gate", relays: "11", pulse: "1500", contact: "33", openOn: false }) }).zz, [1]);
checkEq("ticking the box is saved",
        run("doorFromRow(r)", { r: doorRow(BARE, { label: "Side Gate", relays: "11", pulse: "1500", contact: "33", openOn: true }) }).openWhenContactOnState, true);
checkEq("a changed pulse is saved",
        run("doorFromRow(r)", { r: doorRow(BARE, { label: "Side Gate", relays: "11", pulse: "900", contact: "33", openOn: false }) }).pulseMs, 900);
const FULL = { ...BARE, pulseMs: 2000, openWhenContactOnState: true };
checkEq("a door stored with both keeps both",
        run("doorFromRow(r)", { r: doorRow(FULL, { label: "Side Gate", relays: "11", pulse: "2000", contact: "33", openOn: true }) }), FULL);
checkEq("unticking a stored true is saved as false",
        run("doorFromRow(r)", { r: doorRow(FULL, { label: "Side Gate", relays: "11", pulse: "2000", contact: "33", openOn: false }) }).openWhenContactOnState, false);
checkEq("clearing the contact removes it",
        "statusContactId" in run("doorFromRow(r)", { r: doorRow(BARE, { label: "Side Gate", relays: "11", pulse: "1500", contact: "", openOn: false }) }), false);

console.log("\na door favourite keeps an action group or lock Indigo no longer lists");
const act = vm.runInContext("doorActionOptions(999)", ctx);
check("the action picker keeps the id selected", /<option value="999" selected>/.test(act) && /not found/.test(act), act.slice(0, 160));
check("a known action adds no such option", !/not found/.test(vm.runInContext("doorActionOptions(1)", ctx)));
check("nor does an unset one", !/not found/.test(vm.runInContext('doorActionOptions(undefined)', ctx)));
const lock = vm.runInContext("doorLockOptions(888)", ctx);
check("the lock picker keeps the id selected", /<option value="888" selected>/.test(lock) && /not found/.test(lock));
check("a known lock adds no such option", !/not found/.test(vm.runInContext("doorLockOptions(50)", ctx)));

console.log("\na scene favourite whose action group has gone is not renamed to the warning");
const pick = vm.runInContext('favOptionsHtml("scene", 77)', ctx);
check("the not-found option is marked", /<option value="scene:77" selected data-missing="1">/.test(pick), pick.slice(0, 200));
const favRow = { dataset: { state: "" }, querySelector: sel => ({
    ".fav-pick": { value: "scene:77", selectedOptions: [{ text: "(not found: scene #77 — pick another, or it stays as is)", dataset: { missing: "1" } }] },
    ".fav-label": { value: "" } }[sel] || null) };
checkEq("it is saved as it was, with no label made up",
        run("collectFavourites(root)", { root: { querySelectorAll: () => [favRow] } }), [{ type: "scene", id: 77 }]);
const liveRow = { dataset: { state: "" }, querySelector: sel => ({
    ".fav-pick": { value: "scene:1", selectedOptions: [{ text: " Open Garage ", dataset: {} }] },
    ".fav-label": { value: "" } }[sel] || null) };
checkEq("a scene that exists still takes its own name",
        run("collectFavourites(root)", { root: { querySelectorAll: () => [liveRow] } }), [{ type: "scene", id: 1, label: "Open Garage" }]);

console.log("\nthe Raw JSON box");
ctx.window._rawWritten = '{"a":1}';
checkEq("untouched", vm.runInContext("rawUnapplied({ value: '{\"a\":1}' })", ctx), false);
checkEq("typed in and not applied", vm.runInContext("rawUnapplied({ value: '{\"a\":2}' })", ctx), true);
checkEq("no box at all", vm.runInContext("rawUnapplied(null)", ctx), false);
check("Save refuses while it holds unapplied changes", /if \(rawUnapplied\(document\.getElementById\("raw-json"\)\)\) \{\s*msg\("Not saved/.test(src));
check("the page records what it wrote into the box, both times",
      (src.match(/window\._rawWritten = ta\.value;/g) || []).length === 2);
check("the hint no longer promises the box is what gets saved", !/The full config as it will be saved\./.test(src));

console.log("\na room cannot be given two panels");
const panels = [{ dataset: { room: "Living Room" } }, { dataset: { room: "Hall" } }];
ctx.list = { querySelectorAll: () => panels };
checkEq("the same name finds its panel", vm.runInContext('findRoomPanel(list, "Hall")', ctx).dataset.room, "Hall");
checkEq("so does the name in another case, with spaces", vm.runInContext('findRoomPanel(list, " living room ")', ctx).dataset.room, "Living Room");
checkEq("a new room finds none", vm.runInContext('findRoomPanel(list, "Garage")', ctx), null);
check("+ Add room override opens the panel it finds instead of adding one",
      /const have = findRoomPanel\(list, want\);\s*if \(have\) \{/.test(src));

done();
