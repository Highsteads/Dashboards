// Filename:    test_heating_truth.mjs
// Description: The heating tiles and summary say only what is measured
//              (3.73.5, review 26-11-2026):
//                - a valve's temperature is judged by when the TEMPERATURE
//                  was last reported (temperatureSeenEpoch), not lastSeen,
//                  which setpoint and mode reports keep moving, so a dead
//                  sensor's frozen reading looked fresh;
//                - a zone never measured (RAMSES seeds 0.0) shows a dash;
//                - a thermostat with no call-for-heat state is not told
//                  "Not calling for heat";
//                - a tile's note ("Confirmed at 21 degrees") goes after a
//                  couple of minutes instead of contradicting the tile;
//                - "Calling for heat" counts live zones by the tile's rule;
//                - a boost line with a reason and no figure does not stop
//                  the page drawing.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_heating_truth.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
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

let NOW = Date.UTC(2026, 10, 25, 23, 0, 0);
const els = {};
const box = { console, Promise, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN,
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {}, AbortController,
    document: { getElementById: id => els[id] || null, createElement: () => ({ style: {} }), head: { appendChild() {} },
                querySelectorAll: () => [], addEventListener() {}, documentElement: { style: {} } },
    INDIGO_CONFIG: { apiKey: "k", serverTz: "Europe/London", serverUtcOffsetMin: 0 },
    DashIcons: { svg: n => `<svg data-n="${n}"></svg>`, has: () => false }, __now: () => NOW };
box.window = box; box.globalThis = box;
vm.createContext(box);
vm.runInContext("Date.now = function () { return __now(); };", box);
for (const f of ["dashboards-ui.js", "dashboards-action.js", "dashboards-controls.js"]) vm.runInContext(read(f), box);
const T = box.DashTile, Z = T.zone;
const secs = ms => Math.floor(ms / 1000);
const ramses = (st = {}, extra = {}) => Object.assign({ id: 7, name: "En Suite Radiator", enabled: true, errorState: "", hvacMode: "Heat",
    setpointHeat: 18, states: Object.assign({ temperatureInput1: 17.8, setpointHeat: 18, hvacHeaterIsOn: false, online: "true",
        gatewayStatus: "online", trvStatus: "answering", lastSeen: "2026-11-25 22:59:00",
        temperatureSeenEpoch: secs(NOW) - 60 }, st) }, extra);

console.log("a valve's temperature is as old as its last temperature report");
const fresh = Z.render(ramses());
check("a live valve says when it was measured", /measured 1m ago/.test(fresh) && !/trv-age stale/.test(fresh), (/trv-age[^<]*<?[^<]*/.exec(fresh) || [])[0]);
const dead = ramses({ temperatureSeenEpoch: secs(NOW) - 4 * 3600 });       // lastSeen is still a minute old
check("one whose sensor stopped four hours ago is stale, though it was heard a minute ago", Z.stale(dead) === true);
const deadTile = Z.render(dead);
check("and its tile says so", /trv-age stale/.test(deadTile) && /measured 4h ago/.test(deadTile));
check("a valve the heating plugin calls silent is stale whatever its times", Z.stale(ramses({ trvStatus: "silent" })) === true);
check("a live one is not", Z.stale(ramses()) === false);
const old = { id: 8, name: "Old", states: { temperatureInput1: 19, lastSeen: "2026-11-25 19:00:00" } };
check("a zone with only lastSeen is judged by that", Z.stale(old) === true && /heard 4h ago/.test(Z.render(old)));
check("a zone that reports neither is never called stale", Z.stale({ id: 9, states: { temperatureInput1: 19 } }) === false);

console.log("\na zone never measured shows no reading");
const seed = ramses({ temperatureInput1: 0.0, setpointHeat: 0.0, temperatureSeenEpoch: 0 }, { setpointHeat: 0 });
checkEq("its temperature is unknown, not 0.0", Z.currentTemp(seed), null);
checkEq("its setpoint is unknown, not 0.0", Z.setpoint(seed), null);
const seedTile = Z.render(seed);
check("the tile draws dashes and no colour", />—<span class="cur-unit">/.test(seedTile) && !/cur-temp cold/.test(seedTile) && !/measured/.test(seedTile));
checkEq("a real 0.5 degrees on a zone that has been measured still shows", Z.currentTemp(ramses({ temperatureInput1: 0.5 })), 0.5);
checkEq("a Z-Wave thermostat at 8.0 is untouched", Z.currentTemp({ states: { temperatureInput1: 8.0 } }), 8);

console.log("\na thermostat that cannot say whether it is heating is not told that it is not");
const floor = { id: 20, name: "En Suite Floor Heating Thermostat", enabled: true, hvacMode: "Heat", setpointHeat: 14,
                states: { temperatureInput1: 12.0, setpointHeat: 14.0 } };
const floorTile = Z.render(floor);
check("no 'Not calling for heat'", !/calling for heat/i.test(floorTile), (/zone-meta">.*?<\/div>/.exec(floorTile) || [])[0]);
check("Off is still said", /<span>Off<\/span>/.test(Z.render(Object.assign({}, floor, { hvacMode: "Off" }))));
check("a valve that does report still says", /Not calling for heat/.test(fresh));

console.log("\na tile's note does not outstay what it describes");
T.bind({ setHeatSetpoint: async () => {}, getDevice: async () => null });
els["sp-7"] = { dataset: { sp: "18", gw: "offline" }, textContent: "" };
els["zone-note-7"] = { textContent: "" };
await Z.bump(7, 1);
check("a refused press is explained", /^Not sent\./.test(Z._notices[7] || ""));
check("the note is on the tile straight away", /zone-notice[^>]*>Not sent\./.test(Z.render(ramses({ gatewayStatus: "offline" }))));
NOW += 3 * 60 * 1000;
const later = Z.render(ramses({ temperatureSeenEpoch: secs(NOW) - 60 }));
check("three minutes on it has gone", /zone-notice[^>]*><\/div>/.test(later) && !Z._notices[7], (/zone-notice[^>]*>[^<]*/.exec(later) || [])[0]);

console.log("\nthe Heating page's summary");
const heat = read("heating.html");
{
    const ctx = vm.createContext({ console, Math, String, parseFloat, isFinite, isNaN, JSON, Object,
        DashTile: T, DashUI: box.DashUI, __now: () => NOW });
    vm.runInContext("Date.now = function () { return __now(); };", ctx);
    vm.runInContext(`const getCurrentTemp = DashTile.zone.currentTemp; const getLastSeen = DashTile.zone.lastSeen;
        const TRV_STALE_MS = DashTile.zone.TRV_STALE_MS;
        function cleanZoneName(s) { return String(s || ""); }
        function escapeHtml(s) { return String(s); } function I() { return ""; }\n`
        + extractFn(heat, "houseSummaryCard") + "\nglobalThis.__h = houseSummaryCard;"
        + extractFn(heat, "_deg") + extractFn(heat, "_clockWords").replace("_pad(m)", "String(m).padStart(2, '0')")
        + "\nvar _zoneById = new Map();\n" + extractFn(heat, "boostRoomLine") + "\nglobalThis.__b = boostRoomLine;", ctx);
    const z = (id, name, st, extra) => Object.assign(ramses(Object.assign({ temperatureSeenEpoch: secs(NOW) - 60 }, st), extra), { id, name });
    const zones = [z(1, "Hall", { temperatureInput1: 17.0, setpointHeat: 20, hvacHeaterIsOn: true }, { setpointHeat: 20 }),
                   z(2, "Kitchen", { temperatureInput1: 21.0 }),
                   z(3, "Garage", { temperatureInput1: 5.0, setpointHeat: 20, hvacHeaterIsOn: true }, { setpointHeat: 20, enabled: false }),
                   z(4, "Loft", { temperatureInput1: 9.0, temperatureSeenEpoch: secs(NOW) - 5 * 3600 }),
                   z(5, "Study", { temperatureInput1: 22.0, setpointHeat: 18, hvacHeaterIsOn: true })];   // flag kept, already warm
    const h = ctx.__h(zones, zones);
    check("only a live zone that is really heating is counted", /<div class="h-mval warn">1<\/div><div class="h-mlab">Calling for heat/.test(h), (/h-mval[^>]*>[^<]*<\/div><div class="h-mlab">Calling/.exec(h) || [])[0]);
    check("the average leaves out the disabled and the stale", /20\.0°<\/div><div class="h-mlab">House avg<span class="h-msub">2 zones not counted/.test(h));
    check("a zone stale by its temperature is named in the warning", /Loft/.test(h) && /h-stale/.test(h));
    let line;
    try { line = ctx.__b({ id: 9, room: "Hall", held: "a window is open", requested: null }, "3pm"); } catch (e) { line = ["threw", String(e)]; }
    checkEq("a blocked room with no figure still gets its line", line, ["held", "Hall: not boosted because a window is open."]);
    checkEq("with a figure it says the figure", ctx.__b({ id: 9, room: "Hall", held: "a window is open", requested: 12 }, "3pm"),
            ["held", "Hall: not boosted, set to 12 degrees because a window is open."]);
    checkEq("_deg never throws on a missing number", [vm.runInContext("_deg(null)", ctx), vm.runInContext("_deg('x')", ctx), vm.runInContext("_deg(21.5)", ctx)], ["—", "—", "21.5"]);
}

done();
