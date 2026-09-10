// Filename:    test_settings_fav_passthrough.mjs
// Description: Contract test for the settings editor carrying favourites it
//              cannot draw (settings.html v1.1).
//
//              THE BUG THIS LOCKS SHUT
//              The favourites editor builds each row from a picker listing
//              devices, scenes and door tiles. A ROOM shortcut (v2.89.0) is in
//              none of those lists, so its row fell back to the picker's blank
//              first option and collectFavourites dropped it on `if (!v)
//              return`. Opening Settings and pressing Save would therefore have
//              DELETED all three room shortcuts, silently, with nothing in the
//              log and no way to tell what had gone. A group (v2.93.0) would
//              have gone the same way, and so would anything a newer hub
//              understands and this page does not.
//
//              A form must carry what it cannot draw. Never eat it.
// Author:      CliveS & Claude Opus 5
// Date:        30-08-2026
// Version:     1.0
//
// Run: node tests/test_settings_fav_passthrough.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "settings.html");
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
const eq = (w, got, want) => check(`${w} — got ${JSON.stringify(got)}`,
                                   JSON.stringify(got) === JSON.stringify(want));

// A row is only ever asked for its dataset and a couple of fields, so a plain
// object is enough to drive the real collectFavourites out of the shipped page.
function passRow(obj, label) {
    return { dataset: { raw: JSON.stringify(obj) },
             querySelector: sel => (sel === ".fav-label" ? { value: label == null ? "" : label } : null) };
}
function pickRow(value, label) {
    return { dataset: {},
             querySelector: sel => {
                 if (sel === ".fav-pick") return { value, selectedOptions: [{ text: "Some scene" }] };
                 if (sel === ".fav-label") return { value: label == null ? "" : label };
                 return null;
             } };
}
const rootOf = rows => ({ querySelectorAll: () => rows });

const ctx = vm.createContext({ console, parseInt, parseFloat, isNaN, JSON, Number, String });
vm.runInContext(extractFn(src, "collectFavourites"), ctx);
const collect = rows => { ctx.__r = rootOf(rows); return vm.runInContext("collectFavourites(__r)", ctx); };

console.log("settings — favourites the picker cannot draw");

const ROOM = { type: "room", room: "Living Room" };
const GROUP = { type: "group", label: "Living Room",
                devices: [{ id: 372666822, onLevel: 100 }, { id: 614164061, openLoop: true }] };

{
    const out = collect([passRow(ROOM)]);
    eq("a room shortcut survives a save instead of being deleted", out, [ROOM]);
}
{
    const out = collect([passRow(GROUP), passRow(GROUP)]);
    check("a group survives too, members and all",
          out.length === 2 && out[0].devices.length === 2 && out[0].devices[0].onLevel === 100
          && out[0].devices[1].openLoop === true);
}
{
    // The whole point: a type NEITHER this page nor this test knows about.
    const future = { type: "weather", station: 42, thing: { nested: true } };
    eq("an unrecognised type from a newer hub rides through untouched",
       collect([passRow(future)]), [future]);
}
{
    const out = collect([passRow(ROOM, "Lounge")]);
    eq("the label field still edits a pass-through row", out[0].label, "Lounge");
}
{
    const out = collect([passRow({ ...ROOM, label: "Old" }, "")]);
    check("and clearing the box removes the label rather than storing an empty one",
          !("label" in out[0]));
}
{
    const out = collect([passRow(ROOM), pickRow("device:7"), passRow(GROUP)]);
    eq("DOM order is preserved, so up/down still reorders across kinds",
       out.map(f => f.type), ["room", "device", "group"]);
}
{
    const rows = [{ dataset: { raw: "{not json" },
                    querySelector: () => ({ value: "" }) }];
    eq("a corrupt stashed row is dropped rather than throwing mid-save", collect(rows), []);
}
{
    // The ordinary path must be untouched by all this.
    const out = collect([pickRow("device:1234"), pickRow(""), pickRow("scene:99")]);
    eq("normal rows still collect, and a blank picker is still skipped",
       out, [{ type: "device", id: 1234 }, { type: "scene", id: 99, label: "Some scene" }]);
}

// The render side builds real DOM nodes, and this repo's tests carry no DOM
// library on purpose. So the checks below are SOURCE assertions, and are
// labelled as such rather than dressed up as behaviour: they pin the two
// properties collectFavourites above depends on, and nothing more. What they
// cannot see is the browser actually parsing that markup.
console.log("\nsettings — the row stashes what it cannot draw (SOURCE checks, not behaviour)");
{
    const fn = extractFn(src, "favRow");
    check("favRow stamps dataset.raw for a pass-through favourite",
          /favIsPassThrough\(f\)/.test(fn) && /r\.dataset\.raw = JSON\.stringify\(f\)/.test(fn));
    check("and rooms and groups are both classed as pass-through",
          /'room'|"room"/.test(extractFn(src, "favIsPassThrough")) &&
          /'group'|"group"/.test(extractFn(src, "favIsPassThrough")));
    // The pass-through branch is everything before the ordinary row's picker.
    const branch = fn.slice(0, fn.indexOf("const r = el(`<div class=\"field fav-row\"", fn.indexOf("return r;")));
    check("the pass-through row carries NO picker — a stray one would be read instead of the stash",
          !/class="fav-pick"/.test(branch));
    check("but it does carry the label input, or the label edit above would be dead",
          /class="fav-label"/.test(branch));
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
