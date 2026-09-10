// Filename:    test_bulk_lights_open_loop.mjs
// Description: Contract test for the Lights section's "All On / All Off" when
//              the room contains a device whose state cannot be READ back —
//              the living room fire, a one-way RF relay whose onOffState is
//              only what was last transmitted.
//
//              THE RULE: a vote in the COMMAND, never in the DECISION.
//              1. An unreadable device does not decide the button's mode. Left
//                 in, the fire's permanently-"off" belief meant the button
//                 never once offered "All Off" while the fire was lit from its
//                 handset — so the single press that would have turned it off
//                 was never available.
//              2. It IS still commanded. "All Off" sends off to EVERY id,
//                 including ones already believed off and including the
//                 unreadable one. Belt and braces: an off to something already
//                 off costs nothing, and it is the only way to be sure about a
//                 device that cannot be read.
//              3. The label and the action use the SAME rule. If they diverge
//                 the button says one thing and does another, which is worse
//                 than either behaviour on its own.
// Author:      CliveS & Claude Opus 5
// Date:        28-08-2026
// Version:     1.0
//
// Run: node tests/test_bulk_lights_open_loop.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "room.html");
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

const LAMP_A = 11, LAMP_B = 12, FIRE = 614164061;

/** Run toggleLights with the given believed on/off states. */
function press(states, openLoop = [FIRE], mainLight = []) {
    const sent = [];
    const ctx = vm.createContext({
        console,
        LIGHT_IDS: new Set(Object.keys(states).map(Number)),
        MAIN_LIGHT_IDS: new Set(mainLight),
        OPEN_LOOP_IDS: new Set(openLoop),
        document: { querySelector: sel => {
            const id = Number((sel.match(/data-id="(\d+)"/) || [])[1]);
            return id in states ? { checked: states[id] } : null;
        } },
        indigo: {
            turnOn:  id => { sent.push(["on", id]);  return Promise.resolve(); },
            turnOff: id => { sent.push(["off", id]); return Promise.resolve(); },
        },
        Promise,
    });
    vm.runInContext(extractFn(src, "toggleLights"), ctx);
    return vm.runInContext("toggleLights()", ctx).then(() => sent);
}

let fails = 0;
const check = (w, ok) => { console.log((ok ? "  ok   " : "  FAIL ") + w); if (!ok) fails++; };

console.log("Lights bulk button with an unreadable device");

const ids = s => s.map(x => x[1]).sort((a, b) => a - b);
const dir = s => [...new Set(s.map(x => x[0]))];

// THE CASE THAT PROMPTED THIS: lamps on, fire believed off but actually lit.
let sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: false });
check("lamps on + fire believed off still offers OFF (the fire does not veto it)",
      dir(sent).join() === "off");
check("...and the OFF reaches the fire too",
      ids(sent).includes(FIRE));
check("...and every light, not only those believed on",
      ids(sent).join() === [LAMP_A, LAMP_B, FIRE].sort((a, b) => a - b).join());

// Everything off — the button is an ON, and it asserts on to all of them.
sent = await press({ [LAMP_A]: false, [LAMP_B]: false, [FIRE]: false });
check("everything off sends ON", dir(sent).join() === "on");
check("...to every device including the fire", ids(sent).includes(FIRE));

// Belt and braces the other way: one lamp already on, pressing ON re-sends it.
sent = await press({ [LAMP_A]: true, [LAMP_B]: false, [FIRE]: false });
check("a mixed room sends ON to all, re-asserting the lamp already on",
      dir(sent).join() === "on" && ids(sent).length === 3);

// The fire's own belief must never flip the decision on its own.
const bothWays = await Promise.all([
    press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: false }),
    press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: true }),
]);
check("the fire's belief does not change the direction either way",
      dir(bothWays[0]).join() === dir(bothWays[1]).join());

// Without the exclusion the old behaviour returns — proves the mechanism.
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: false }, []);
check("with nothing marked unreadable the fire DOES veto — the old behaviour",
      dir(sent).join() === "on");


// ---------------------------------------------------------------------------
// mainLight — a light the bulk button must LEAVE ALONE (v3.4.0)
//
// The room's main light. You want the lamps off in one press without also
// killing the ceiling light. It still renders and is still switchable on its
// own; it is only out of the GROUP.
//
// This existed as a MAIN_LIGHT_ID pinned to -1 in both the label and the
// command, so it read as implemented in two places and had never excluded
// anything — -1 matches no device. These cases would all have passed against
// that, which is why the last one asserts the opposite direction too.
// ---------------------------------------------------------------------------
console.log("\nLights bulk button with a main light held out");

const MAIN = 99;

// Lamps on, main light on: the button is still an OFF, and the main light
// keeps its state.
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [MAIN]: true }, [], [MAIN]);
check("the main light is never commanded", !ids(sent).includes(MAIN));
check("...while the rest of the room still gets its OFF",
      dir(sent).join() === "off" && ids(sent).join() === [LAMP_A, LAMP_B].join());

// It must not get a VOTE either: lamps on + main light OFF must still read as
// "all on" and offer OFF. If it voted, one dark ceiling light would flip the
// button to ON and turning the lamps off in one press would be impossible.
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [MAIN]: false }, [], [MAIN]);
check("a main light that is OFF does not veto the room's OFF",
      dir(sent).join() === "off");

// ...and the mirror: lamps off + main light ON must still be an ON for the
// lamps, not an OFF.
sent = await press({ [LAMP_A]: false, [LAMP_B]: false, [MAIN]: true }, [], [MAIN]);
check("a main light that is ON does not make the room read as lit",
      dir(sent).join() === "on" && !ids(sent).includes(MAIN));

// The distinction from openLoop, which is the easy thing to get wrong: an
// unreadable device is excluded from the DECISION but still COMMANDED. A main
// light is excluded from BOTH.
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: false }, [FIRE], []);
check("an openLoop device is still commanded (it is only out of the vote)",
      ids(sent).includes(FIRE));
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [FIRE]: false }, [FIRE], [FIRE]);
check("...but marked mainLight as well, it is left alone entirely",
      !ids(sent).includes(FIRE));

// Proves the mechanism rather than the default: with nothing held out, the
// main light IS commanded — which is exactly what it did before this release.
sent = await press({ [LAMP_A]: true, [LAMP_B]: true, [MAIN]: true }, [], []);
check("with nothing held out the main light IS commanded — the old behaviour",
      ids(sent).includes(MAIN));

// A room of nothing but unreadable devices must not claim "all on".
sent = await press({ [FIRE]: true }, [FIRE]);
check("a room with only unreadable devices sends ON, never a false 'all on' OFF",
      dir(sent).join() === "on");

// The set must actually be WIRED to rooms.json. This test supplies
// OPEN_LOOP_IDS directly, so without checking the source a page that never
// populated it would sail through — a mutation run proved exactly that.
check("OPEN_LOOP_IDS is populated from the room's openLoop list",
      /OPEN_LOOP_IDS\s*=\s*new Set\(sec\("openLoop"\)\)/.test(src));

// Same for mainLight, and this one is not hypothetical: it shipped as a
// MAIN_LIGHT_ID pinned to -1 with the filters already in place, so the feature
// read as done in two places and excluded nothing for months. A mutation run
// that blanked the assignment stayed green until this check existed.
check("MAIN_LIGHT_IDS is populated from the room's mainLight list",
      /MAIN_LIGHT_IDS\s*=\s*new Set\(sec\("mainLight"\)\)/.test(src));
check("...and is never left as a set that can match nothing",
      !/MAIN_LIGHT_IDS?\s*=\s*-1/.test(src));

// The page reads sec("mainLight"); the PLUGIN has to write that same key into
// rooms.json or the whole chain is dead again, silently. Both ends, one name.
const PLUGIN = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                         "Server Plugin", "plugin.py");
const py = fs.readFileSync(PLUGIN, "utf8");
check("the plugin emits mainLight into rooms.json",
      /room_data\["mainLight"\]\s*=/.test(py) && /cfg\.get\("mainLight"\)/.test(py));
check("...and does NOT pin it out of lights (it must still render)",
      !/mainLight[\s\S]{0,400}?room_data\[k\] = \[i for i in room_data\[k\]/.test(py));

// The label must use the same rule as the action.
const label = src.slice(src.indexOf("const others      = lights.filter"),
                        src.indexOf("const lbl = allOthersOn"));
check("the label excludes unreadable devices too, so it cannot disagree",
      label.includes("OPEN_LOOP_IDS.has(d.id)"));
check("the label holds the main light out too", label.includes("MAIN_LIGHT_IDS.has(d.id)"));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
