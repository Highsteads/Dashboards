// Filename:    test_settings_door_passthrough.mjs
// Description: Contract test for the Settings page carrying a room door it
//              cannot edit (3.73.3).
//
//              THE BUG THIS LOCKS SHUT
//              A room door that follows a door device is stored as
//              {label, deviceId, openAction, closeAction}. The Settings form
//              only knew pulse doors (label, relays, pulse, status contact)
//              and rebuilt every door from those fields, so ANY Save - one
//              made to change a favourite, say - rewrote the door as a pulse
//              door with no relays, and the room page read "Not set up".
//              It happened twice on the live house before it was traced.
//
//              A form must carry what it cannot draw.
// Author:      CliveS & Claude Fable 5.2
// Date:        25-11-2026
// Version:     1.0
//
// Run: node tests/test_settings_door_passthrough.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { checkOk, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "settings.html");
const src = fs.readFileSync(PAGE, "utf8");

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

const ctx = vm.createContext({ console });
vm.runInContext("var strToIds = s => String(s || '').split(/[\\s,]+/).map(Number).filter(n => n > 0);", ctx);
vm.runInContext(extractFn(src, "doorFromRow"), ctx);

// A row is only asked for its dataset and its fields.
function row(fields, raw) {
    return { dataset: raw === undefined ? {} : { raw },
             querySelector: sel => (sel in fields ? fields[sel] : null) };
}
function collect(r) {
    ctx.__r = r;
    return JSON.parse(JSON.stringify(vm.runInContext("doorFromRow(__r)", ctx)));
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log("settings: a door that follows a door device survives a Save");

const STATE = { label: "Garage Door", deviceId: 1001, openAction: 2001, closeAction: 2002 };

let got = collect(row({ ".d-label": { value: "Garage Door" } }, JSON.stringify(STATE)));
checkOk(same(got, STATE), "the door is saved exactly as it was stored", JSON.stringify(got));

got = collect(row({ ".d-label": { value: "  Big Door " } }, JSON.stringify(STATE)));
checkOk(same(got, { ...STATE, label: "Big Door" }), "only its label follows the form", JSON.stringify(got));

got = collect(row({ ".d-label": { value: "" } }, JSON.stringify(STATE)));
checkOk(same(got, STATE), "a blanked label does not remove the door or its label", JSON.stringify(got));

got = collect(row({ ".d-label": { value: "X" } }, JSON.stringify({ ...STATE, somethingNewer: [1, 2] })));
checkOk(same(got.somethingNewer, [1, 2]) && got.deviceId === 1001, "a key this page has never heard of survives too");

console.log("a pulse door is still built from the form");

const pulse = fields => row({ ".d-label": { value: "Side Gate" }, ".d-relays": { value: "11, 12" },
                              ".d-pulse": { value: "1500" }, ".d-contact": { value: "33" },
                              ".d-openon": { checked: false }, ...fields });
got = collect(pulse({}));
checkOk(same(got, { label: "Side Gate", relayIds: [11, 12], pulseMs: 1500, statusContactId: 33,
                    openWhenContactOnState: false }), "every field is read", JSON.stringify(got));

got = collect(pulse({ ".d-pulse": { value: "" }, ".d-contact": { value: "" } }));
checkOk(got.pulseMs === 2000 && !("statusContactId" in got), "a blank pulse falls back to 2000 and a blank contact is left out");

ctx.__r = row({ ".d-label": { value: "" }, ".d-relays": { value: "" }, ".d-pulse": { value: "2000" },
                ".d-contact": { value: "" }, ".d-openon": { checked: true } });
checkOk(vm.runInContext("doorFromRow(__r)", ctx) === null, "an empty row is dropped");

got = collect(row({ ".d-label": { value: "Gate" }, ".d-relays": { value: "5" }, ".d-pulse": { value: "900" },
                    ".d-contact": { value: "" }, ".d-openon": { checked: true } }, "not json"));
checkOk(got.label === "Gate" && same(got.relayIds, [5]), "unreadable carried data falls back to the form");

console.log("the page uses it");

checkOk(/const door = doorFromRow\(r\);\s*if \(door\) doors\.push\(door\);/.test(src),
        "collectRooms asks doorFromRow for every door row");
checkOk(/if \(door && door\.deviceId\) \{[\s\S]{0,1400}?s\.dataset\.raw = JSON\.stringify\(door\);/.test(src),
        "a door with a device is drawn as a row that carries the whole door");

done();
