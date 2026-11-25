// Filename:    test_room_windows_row.mjs
// Description: Contract test for the ROOM page's windows row (3.73.2): a
//              room's temperature and humidity sensors sit on the same row
//              as its window and door contacts, after them. A room with no
//              contacts keeps a Sensors row of its own, and a room with no
//              sensors keeps the plain "Windows & Doors" heading.
//
//              Extracts renderWindowsRow from the SHIPPED room.html.
// Author:      CliveS & Claude Fable 5.2
// Date:        25-11-2026
// Version:     1.0
//
// Run: node tests/test_room_windows_row.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { checkOk, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "room.html");

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
vm.runInContext("var renderSectionHeader = t => '<h>' + t + '</h>';" +
                "var renderMotion = (d, w) => '<win ' + d.id + ' ' + w.on + '/' + w.off + '>';" +
                "var renderEnvSensor = d => '<env ' + d.id + '>';", ctx);
vm.runInContext(extractFn(page, "renderWindowsRow"), ctx);

function row(windows, sensors) {
    ctx.__w = windows; ctx.__s = sensors;
    return vm.runInContext("renderWindowsRow(__w, __s)", ctx);
}

console.log("room page: sensors share the windows row");

const both = row([{ id: 1 }], [{ id: 9 }]);
checkOk(both === '<h>Windows, Doors & Sensors</h><div class="grid"><win 1 Open/Closed><env 9></div>',
        "one grid holds the window then the sensor", both);
checkOk((both.match(/class="grid"/g) || []).length === 1, "there is one row, not two");

const many = row([{ id: 1 }, { id: 2 }], [{ id: 8 }, { id: 9 }]);
checkOk(many.indexOf("<win 2") < many.indexOf("<env 8") && many.indexOf("<env 8") < many.indexOf("<env 9"),
        "contacts come first, then the sensors in their order");

const winOnly = row([{ id: 1 }], []);
checkOk(winOnly === '<h>Windows & Doors</h><div class="grid"><win 1 Open/Closed></div>',
        "a room with no sensors keeps the plain heading", winOnly);

checkOk(row([], [{ id: 9 }]) === "", "a room with no contacts draws no windows row");
checkOk(row([], []) === "", "an empty room draws nothing");

checkOk(/if \(sensors\.length && !windows\.length\) \{\s*html \+= renderSectionHeader\("Sensors"\)/.test(page),
        "the Sensors row is drawn only where there are no contacts");
checkOk(/html \+= renderWindowsRow\(windows, sensors\);/.test(page), "the page draws the shared row");

done();
