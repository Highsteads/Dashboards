// Filename:    test_room_env_battery.mjs
// Description: Contract test for the ROOM page's battery figure on a
//              temperature and humidity sensor tile (3.73.1).
//
//              THE RULE: a battery state of 0 is not a reading. Zigbee2MQTT
//              Bridge seeds the state to 0 until the sensor first reports, so
//              a newly paired sensor read "0%" on its tile and "Battery 0%"
//              in its details. A figure shows only once one has been sent.
//
//              Extracts batteryPercent and renderEnvSensor from the SHIPPED
//              room.html and runs them in a vm.
// Author:      CliveS & Claude Fable 5.2
// Date:        25-11-2026
// Version:     1.0
//
// Run: node tests/test_room_env_battery.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { checkOk as check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "room.html");

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
vm.runInContext("var escapeHtml = s => String(s == null ? '' : s);" +
                "var prettyMotionName = s => s;" +
                "var I = n => '[' + n + ']';" +
                "var DashTile = { unknownReason: () => null };", ctx);
vm.runInContext(extractFn(page, "batteryPercent"), ctx);
vm.runInContext(extractFn(page, "renderEnvSensor"), ctx);

function pct(states) {
    ctx.__s = states;
    return vm.runInContext("batteryPercent(__s)", ctx);
}
function tile(states) {
    ctx.__d = { id: 1, name: "Temperature And Humidity", states };
    return vm.runInContext("renderEnvSensor(__d)", ctx);
}

console.log("room page: battery figure on a sensor tile");

check(pct({ battery: 0 }) === null, "0 is not a reading");
check(pct({ battery: "0" }) === null, "the string 0 is not a reading either");
check(pct({}) === null, "no battery state gives no figure");
check(pct(undefined) === null, "no states at all gives no figure");
check(pct({ battery: "abc" }) === null, "text gives no figure");
check(pct({ battery: 1 }) === 1, "1% is a reading");
check(pct({ battery: "87" }) === 87, "a string percentage is read");
check(pct({ battery: 100 }) === 100, "100% is a reading");

const fresh = tile({ temperature: 20.0, humidity: 52.0, battery: 0, "battery.ui": "Mains" });
check(fresh.includes("20.0°C"), "the tile still shows the temperature");
check(fresh.includes("52% humidity"), "the tile still shows the humidity");
check(!fresh.includes("[battery]") && !fresh.includes("0%"),
      "a sensor that has never reported its battery shows no battery figure");

const low = tile({ temperature: 19.5, humidity: 60, battery: 14 });
check(low.includes("[battery] 14%"), "a real reading is shown");

const full = tile({ temperature: 19.5, humidity: 60, battery: 100 });
check(!full.includes("[battery]"), "a full battery is left off the tile, as before");

check(/if \(batteryPercent\(s\) != null\) out \+= _detailRow\("Battery"/.test(page),
      "the details panel uses the same rule");

done();
