// Filename:    test_fav_device_label.mjs
// Description: Contract test for the label on a plain on/off device favourite
//              (v2.92.1). Settings offers a "label (optional)" box for every
//              favourite type, and the hub was ignoring it on this one type —
//              the live device name won, so a label typed in Settings was
//              stored and then silently never shown.
//
//              THE RULES
//              1. A typed label WINS over the live device name, as it already
//                 does on the door and reading tiles.
//              2. With NO label the live device name still shows, so an
//                 untouched favourite keeps following Indigo renames.
//              3. A favourite whose device is missing from the poll falls back
//                 to its label, and to "#<id>" when it has neither — it must
//                 never render blank.
//              4. The tile still carries the live on/off state either way:
//                 renaming a tile must not cost it its state.
// Author:      CliveS & Claude Opus 5
// Date:        30-08-2026
// Version:     1.0
//
// Run: node tests/test_fav_device_label.mjs   (exit 0 = pass)

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

console.log("favourites — device tile label");

const host = { id: "favourites", innerHTML: "", style: { display: "" } };
const ctx = vm.createContext({
    console,
    document: { getElementById: id => (id === "favourites" ? host : null) },
    window: { INDIGO_CONFIG: { favourites: [] } },
    escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    DashAction: { repaint: () => {} },
    DashIcons: { has: () => false, svg: () => "" },
});
vm.runInContext(extractFn(src, "renderFavouritesCard"), ctx);

function render(favs, devices) {
    ctx.window.INDIGO_CONFIG.favourites = favs;
    ctx.__devices = devices;
    vm.runInContext("renderFavouritesCard(__devices)", ctx);
    return host.innerHTML;
}

// The real case this was written for: "Fire On/Off" is the device's name, and
// a tile reading "Fire On/Off — On" is nonsense. Settings lets you call it
// "Fire"; the hub has to honour that.
{
    const html = render([{ type: "device", id: 614164061, label: "Fire" }],
                        [{ id: 614164061, name: "Fire On/Off", onState: true }]);
    check("a typed label is used instead of the device name",
          html.includes(">Fire<") && !html.includes("Fire On/Off"));
    check("the tile still shows live state and paints itself on",
          html.includes(">On<") && /class="fav-tile on"/.test(html));
}

// No label: the live name must still win, so renaming in Indigo follows through.
{
    const html = render([{ type: "device", id: 7 }],
                        [{ id: 7, name: "Twigs Light Plug", onState: false }]);
    check("with no label the live device name is used",
          html.includes(">Twigs Light Plug<"));
    check("state is Off and the tile is not painted on",
          html.includes(">Off<") && !/class="fav-tile on"/.test(html));
}

// An empty-string label must not blank the tile — it is "no label", not "".
{
    const html = render([{ type: "device", id: 7, label: "" }],
                        [{ id: 7, name: "Twigs Light Plug", onState: false }]);
    check("an empty label falls through to the device name, not a blank tile",
          html.includes(">Twigs Light Plug<"));
}

// Device missing from the poll (deleted, or a device the API did not return).
{
    const html = render([{ type: "device", id: 99, label: "Colour Lamp" }], []);
    check("a missing device falls back to its label", html.includes(">Colour Lamp<"));
    check("and shows an unknown state rather than a confident Off",
          html.includes(">—<"));
}
{
    const html = render([{ type: "device", id: 99 }], []);
    check("with neither label nor device it names the id, never blank",
          html.includes(">#99<"));
}

// A reading favourite keeps its own precedence — this change must not reach it.
{
    const html = render([{ type: "device", id: 5, state: "voltage", label: "Qashqai 12V" }],
                        [{ id: 5, name: "Qashqai Battery", states: { voltage: 12.7 } }]);
    check("reading tiles are untouched and still prefer their label",
          html.includes(">Qashqai 12V<") && html.includes("fav-reading"));
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
