// Filename:    test_fav_group_tile.mjs
// Description: Contract test for the group favourite (v2.93.0) — ONE hub tile
//              standing for several devices. Drives the two pure helpers out
//              of the shipped dashboards-action.js, then the rendered tile out
//              of the shipped index.html, so it locks what actually ships.
//
//              THE RULES
//              1. An UNREADABLE member gets no vote. The living room fire is a
//                 one-way RF relay whose state is a belief; left in the vote it
//                 stops the tile ever offering an "off", which is exactly what
//                 it did to the room page's All On / All Off button.
//              2. Belief decides only when nothing readable exists, and with
//                 nothing resolved at all a press turns things ON — visible and
//                 reversible beats a tile that does nothing.
//              3. An ABSENT member is not evidence. It is left out of the count
//                 entirely rather than padding the total or reading as off.
//              4. EVERY member is commanded, including ones already believed to
//                 be in the state asked for — the only way to be sure about one
//                 that cannot be read.
//              5. A member with onLevel lands on that brightness going up; off
//                 is always a plain turnOff, which is nought per cent.
// Author:      CliveS & Claude Opus 5
// Date:        30-08-2026
// Version:     1.0
//
// Run: node tests/test_fav_group_tile.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const actionSrc = fs.readFileSync(path.join(PAGES, "dashboards-action.js"), "utf8");
const pageSrc = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");

let fails = 0;
const check = (w, ok) => { console.log((ok ? "  ok   " : "  FAIL ") + w); if (!ok) fails++; };
const eq = (w, got, want) => check(`${w} — got ${JSON.stringify(got)}`, JSON.stringify(got) === JSON.stringify(want));

// ── load the shipped module ──────────────────────────────────────────────
const root = {};
vm.runInNewContext(actionSrc, { window: root, globalThis: root, document: undefined, console });
const { groupTile, groupPlan } = root.DashAction;

// The living room as configured: three lamps plus the open-loop fire.
const LAMP = 372666822, TWIGS = 1293995000, DISPLAY = 515728864, FIRE = 614164061;
const MEMBERS = [
    { id: LAMP, onLevel: 100 },
    { id: TWIGS },
    { id: DISPLAY },
    { id: FIRE, openLoop: true },
];
const map = pairs => new Map(pairs.map(([id, on]) => [id, { id, onState: on }]));

console.log("group favourite — state and direction");

{
    const t = groupTile(MEMBERS, map([[LAMP, true], [TWIGS, true], [DISPLAY, true], [FIRE, true]]));
    eq("everything on reads On and a press turns it off", [t.key, t.label, t.intent], ["on", "On", "off"]);
}
{
    const t = groupTile(MEMBERS, map([[LAMP, false], [TWIGS, false], [DISPLAY, false], [FIRE, false]]));
    eq("everything off reads Off and a press turns it on", [t.key, t.label, t.intent], ["off", "Off", "on"]);
}
{
    const t = groupTile(MEMBERS, map([[LAMP, true], [TWIGS, false], [DISPLAY, true], [FIRE, false]]));
    eq("a mix counts itself out loud", [t.key, t.label], ["part", "2 of 4 on"]);
    check("and a press turns everything ON while any readable one is off", t.intent === "on");
}
{
    // THE BUG THIS RULE EXISTS FOR: three lamps on, fire lit from its handset
    // so Indigo still believes it off. The fire must not veto the "off".
    const t = groupTile(MEMBERS, map([[LAMP, true], [TWIGS, true], [DISPLAY, true], [FIRE, false]]));
    check("the open-loop fire does not veto an off when every readable member is on",
          t.intent === "off");
    check("but it is still counted honestly in the label", t.label === "3 of 4 on");
}
{
    // Mirror: the fire believed ON must not carry the group to "all on" either.
    const t = groupTile(MEMBERS, map([[LAMP, false], [TWIGS, false], [DISPLAY, false], [FIRE, true]]));
    check("nor does it carry the group when the readable members are off", t.intent === "on");
    eq("label still counts it", [t.key, t.label], ["part", "1 of 4 on"]);
}

console.log("\ngroup favourite — absent and unreadable members");
{
    const t = groupTile(MEMBERS, map([[LAMP, true], [TWIGS, true]]));
    eq("members missing from the poll are left out of the count, not read as off",
       [t.key, t.label, t.intent], ["on", "On", "off"]);
    eq("and out of the total", [t.on, t.total], [2, 2]);
}
{
    const t = groupTile(MEMBERS, new Map());
    eq("nothing resolved is unknown, never a confident Off", [t.key, t.label], ["unknown", "—"]);
    check("and a press still turns things on rather than doing nothing", t.intent === "on");
}
{
    // A state that will not resolve to a boolean is not a reading.
    const t = groupTile(MEMBERS, new Map([[LAMP, { id: LAMP, onState: null }],
                                          [TWIGS, { id: TWIGS, onState: undefined }]]));
    // Contract flipped in v2.95.4: an unreadable member is UNKNOWN. It used
    // to be counted in the total and so read as OFF in the label — "3 of 4
    // on" told the reader the fourth was off when nobody knew.
    eq("unresolvable states are unknown, not off, and cast no vote",
       [t.key, t.label, t.intent, t.unknown], ["unknown", "—", "on", 2]);
}
{
    const t = groupTile(MEMBERS, new Map([[LAMP, { id: LAMP, onState: true }],
                                          [TWIGS, { id: TWIGS, onState: null }]]));
    eq("a readable member decides the label and the unknown one is named",
       [t.key, t.label, t.intent, t.on, t.total, t.unknown], ["on", "On (1 unknown)", "off", 1, 1, 1]);
}
{
    // Only the fire present: belief has to decide, or it could never go off.
    const t = groupTile([{ id: FIRE, openLoop: true }], map([[FIRE, true]]));
    check("with nothing readable, belief decides rather than jamming on 'on'", t.intent === "off");
}
{
    // v2 API custom states arrive as the STRINGS "True"/"False".
    const t = groupTile(MEMBERS, new Map([[LAMP, { id: LAMP, onState: "true" }],
                                          [TWIGS, { id: TWIGS, onState: "True" }],
                                          [DISPLAY, { id: DISPLAY, onState: "on" }]]));
    eq("string booleans from the v2 API are understood", [t.key, t.intent], ["on", "off"]);
}
{
    const t = groupTile([], new Map());
    eq("an empty group is unknown, not on", [t.key, t.total], ["unknown", 0]);
}

console.log("\ngroup favourite — what a press actually sends");
{
    const plan = groupPlan(MEMBERS, "on");
    eq("every member is commanded, none skipped", plan.length, 4);
    eq("the dimmer is asked for its level, the rest are plain turnOn",
       plan, [{ id: LAMP, fn: "setBrightness", level: 100 },
              { id: TWIGS, fn: "turnOn" },
              { id: DISPLAY, fn: "turnOn" },
              { id: FIRE, fn: "turnOn" }]);
}
{
    const plan = groupPlan(MEMBERS, "off");
    check("off is a plain turnOff for every member, dimmer included — that IS 0%",
          plan.length === 4 && plan.every(c => c.fn === "turnOff") && !("level" in plan[0]));
}
{
    const plan = groupPlan([{ id: 1, onLevel: 0 }, { id: 2, onLevel: 101 },
                            { id: 3, onLevel: "x" }, { id: 4, onLevel: 55.6 }], "on");
    eq("a junk or out-of-range level falls back to turnOn rather than a guess",
       plan.map(c => c.fn), ["turnOn", "turnOn", "turnOn", "setBrightness"]);
    eq("a fractional level is rounded, not truncated", plan[3].level, 56);
}
{
    const plan = groupPlan([{ id: "nope" }, null, { id: 0 }, { id: 9 }], "on");
    eq("members with no usable id are dropped, the rest still go", plan, [{ id: 9, fn: "turnOn" }]);
}

// ── the rendered tile, out of the shipped page ───────────────────────────
console.log("\ngroup favourite — the rendered tile");
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
const host = { id: "favourites", innerHTML: "", style: { display: "" } };
const ctx = vm.createContext({
    console,
    document: { getElementById: id => (id === "favourites" ? host : null) },
    // The page guards every DashAction call with `window.DashAction &&`,
    // so the harness has to hang it off window as the real page does —
    // a bare global here renders the fallback tile and proves nothing.
    window: { INDIGO_CONFIG: { favourites: [] }, DashAction: root.DashAction },
    escapeAttr: s => String(s == null ? "" : s).replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    DashAction: root.DashAction,
    DashIcons: { has: () => false, svg: () => "" },
});
ctx.DashAction.repaint = () => {};
vm.runInContext("const _doorLast = new Map();", ctx);
vm.runInContext(extractFn(pageSrc, "renderFavouritesCard"), ctx);

function render(favs, devices) {
    ctx.window.INDIGO_CONFIG.favourites = favs;
    ctx.__devices = devices;
    vm.runInContext("renderFavouritesCard(__devices)", ctx);
    return host.innerHTML;
}
const GROUP = { type: "group", label: "Living Room", devices: MEMBERS };
const devs = on => [{ id: LAMP, name: "Colour Lamp", onState: on },
                    { id: TWIGS, name: "Twigs", onState: on },
                    { id: DISPLAY, name: "Display", onState: on },
                    { id: FIRE, name: "Fire", onState: on }];
{
    const html = render([GROUP], devs(true));
    check("the group renders as one tile, not four", (html.match(/class="fav-tile/g) || []).length === 1);
    check("it carries its label", html.includes(">Living Room<"));
    check("it says On and is painted on", html.includes(">On<") && / on"/.test(html));
    check("the direction decided at render time rides on the tile",
          html.includes('data-group-intent="off"'));
}
{
    const html = render([GROUP], devs(false));
    check("all off says so and asks for on", html.includes(">Off<") && html.includes('data-group-intent="on"'));
    check("and is not painted on", !/fav-group-on/.test(html));
}
{
    // The index the click handler reads must point into the UNFILTERED config
    // array, or a room favourite above the group silently misaddresses it.
    const html = render([{ type: "room", room: "Hall" }, GROUP], devs(true));
    check("the tile's index addresses the full config, rooms included",
          html.includes('data-fav-idx="1"'));
}
{
    const html = render([GROUP], []);
    check("a group whose devices are all absent shows a dash, not Off",
          html.includes(">—<") && html.includes("fav-group-unknown"));
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
