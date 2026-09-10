// Filename:    test_room_door_device.mjs
// Description: Contract test for the ROOM page's state-driven door tile
//              (v2.86.0) — the variant used when a door config carries a
//              `deviceId` instead of relayIds + a status contact.
//
//              THE RULES THAT MATTER MOST
//              1. The tile picks the action group for the state SHOWING:
//                 closed -> openAction, open -> closeAction, stuck ->
//                 closeAction (securing the house is the useful recovery).
//                 Firing the wrong one opens a door somebody meant to close,
//                 and nothing else in the page would catch that.
//              2. Moving and unknown are display-only — the button is
//                 DISABLED. Pulsing an opener mid-travel stops or reverses it
//                 unpredictably, and a door that cannot be read must never
//                 render as a confident "Closed".
//              3. A state with no action group configured for it is also
//                 disabled rather than left looking live.
//
//              Extracts renderStateDoorTile from the SHIPPED room.html and
//              runs it in a vm, so this locks what ships rather than a copy.
// Author:      CliveS & Claude Opus 5
// Date:        28-08-2026
// Version:     1.0
//
// Run: node tests/test_room_door_device.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "room.html");
const ACTION = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                         "Resources", "static", "pages", "dashboards-action.js");

/** Pull one top-level `function NAME(...) { ... }` out by brace matching. */
function extractFn(src, name) {
    const start = src.indexOf("function " + name + "(");
    if (start < 0) throw new Error("function not found: " + name);
    let i = src.indexOf("{", start), depth = 0;
    for (let j = i; j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(start, j + 1); }
    }
    throw new Error("unbalanced braces in " + name);
}

const page = fs.readFileSync(PAGE, "utf8");
const ctx = vm.createContext({ console });
// The real DashAction — doorTile() is the decision this tile rests on, so the
// test must use the shipped one, not a stand-in that could drift from it.
vm.runInContext(fs.readFileSync(ACTION, "utf8"), ctx);
vm.runInContext("var window = this; var escapeHtml = s => String(s == null ? '' : s)" +
                ".replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')" +
                ".replace(/\"/g,'&quot;');", ctx);
vm.runInContext(extractFn(page, "renderStateDoorTile"), ctx);
vm.runInContext("var _doorLast = new Map();", ctx);

const DOOR = { label: "Garage Door", deviceId: 489580549,
               openAction: 1463818396, closeAction: 780532115 };

function render(doorState, door = DOOR) {
    vm.runInContext("_doorLast = new Map();", ctx);
    ctx.__door = door;
    ctx.__devs = doorState === undefined
        ? []
        : [{ id: door.deviceId, name: "Garage Door", states: { doorState } }];
    return vm.runInContext("renderStateDoorTile(__door, __devs, false)", ctx);
}

let failures = 0;
function check(what, cond) {
    if (cond) { console.log("  ok   " + what); }
    else { console.log("  FAIL " + what); failures++; }
}

console.log("state-driven room door tile");

const closed = render("closed");
check("closed shows Closed", /Closed/.test(closed));
check("closed offers to open", /Press to Open/.test(closed));
check("closed fires the OPEN action group",
      closed.includes('data-door-action="1463818396"'));
check("closed is not disabled", !/<button[^>]*\sdisabled/.test(closed));

const open = render("open");
check("open shows Open", />Open</.test(open));
check("open fires the CLOSE action group",
      open.includes('data-door-action="780532115"'));
check("open paints red", open.includes("door-state-open"));

const stuck = render("stuck");
check("stuck fires the CLOSE action group — securing the house is the recovery",
      stuck.includes('data-door-action="780532115"'));
check("stuck paints amber", stuck.includes("door-state-stuck"));

const moving = render("moving");
check("moving is DISABLED — pulsing mid-travel reverses it unpredictably",
      /<button[^>]*\sdisabled/.test(moving));
check("moving carries no action", moving.includes('data-door-action="0"'));

const unknown = render("banana");
check("an unrecognised state is disabled", /<button[^>]*\sdisabled/.test(unknown));
check("an unrecognised state shows a dash, never Closed",
      unknown.includes(">—<") && !/>Closed</.test(unknown));

const absent = render(undefined);
check("a device missing from the poll is disabled",
      /<button[^>]*\sdisabled/.test(absent));
check("a device missing from the poll never reads as Closed",
      !/>Closed</.test(absent));

const noAction = render("closed", { label: "D", deviceId: 489580549, closeAction: 780532115 });
check("closed with no openAction configured is disabled, not left looking live",
      /<button[^>]*\sdisabled/.test(noAction));

// Direction naming from the last settled state.
vm.runInContext("_doorLast = new Map();", ctx);
ctx.__door = DOOR;
ctx.__devs = [{ id: DOOR.deviceId, name: "Garage Door", states: { doorState: "closed" } }];
vm.runInContext("renderStateDoorTile(__door, __devs, false)", ctx);
ctx.__devs = [{ id: DOOR.deviceId, name: "Garage Door", states: { doorState: "moving" } }];
const opening = vm.runInContext("renderStateDoorTile(__door, __devs, false)", ctx);
check("moving after closed is named Opening…", /Opening/.test(opening));

console.log(failures ? `\n${failures} FAILED` : "\nall passed");
process.exit(failures ? 1 : 0);
