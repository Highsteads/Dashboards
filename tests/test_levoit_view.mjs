// Filename:    test_levoit_view.mjs
// Description: Node contract test for LevoitView (levoit-view.js), the Air
//              page's decisions (3.63.0), and the menu's Air tile. The device
//              fixture is shaped exactly as the Levoit Purifier plugin 1.0.0
//              writes its states (levoit_logic.decode), as the v2 API returns
//              a relay device.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-10-2026
// Version:     1.0
//
// Run: node tests/test_levoit_view.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const ctx = { window: {}, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(PAGES, "levoit-view.js"), "utf8"), ctx);
const V = ctx.window.LevoitView;

function purifier(states = {}, top = {}) {
    return Object.assign({
        id: 4100, name: "Bedroom Purifier", enabled: true, errorState: "", onState: true,
        pluginId: "com.clives.indigoplugin.levoit", deviceTypeId: "levoitPurifier",
        states: Object.assign({
            onOffState: true, mode: "auto", fanLevel: 2, pm25: 4, airQuality: 1,
            airQualityText: "excellent", filterLife: 87, childLock: false, displayOn: true,
            autoPreference: "efficient", deviceOnline: true, lastUpdate: "2026-10-24 13:30:05",
        }, states),
    }, top);
}
const lamp = { id: 7, name: "Lamp", states: { onOffState: true, brightnessLevel: 50 } };
const NOW = new Date(2026, 9, 24, 13, 32, 10).getTime();

// ── finding purifiers ──
checkEq("finds a purifier by its states, not its id", V.purifiers([lamp, purifier()]).map(d => d.id), [4100]);
checkEq("none on an install without one", V.purifiers([lamp]).length, 0);
checkEq("copes with nothing", V.purifiers(undefined).length, 0);
checkEq("several are sorted by name",
        V.purifiers([purifier({}, { id: 2, name: "Study" }), purifier({}, { id: 1, name: "Bedroom" })]).map(d => d.name),
        ["Bedroom", "Study"]);

// ── reading one ──
const v = V.view(purifier());
checkEq("PM2.5", v.pm25, 4);
checkEq("band from the purifier's own verdict", [v.band, v.bandWords], ["good", "Excellent"]);
checkEq("moderate", V.view(purifier({ airQuality: 3 })).band, "moderate");
checkEq("poor", [V.view(purifier({ airQuality: 4 })).band, V.view(purifier({ airQuality: 4 })).bandWords], ["poor", "Poor"]);
checkEq("unknown verdict", [V.view(purifier({ airQuality: 0 })).band, V.view(purifier({ airQuality: 0 })).bandWords],
        ["unknown", "Not known yet"]);
checkEq("offline is grey whatever the last verdict", V.view(purifier({ deviceOnline: false })).band, "unknown");
check("an error state is offline too", !V.view(purifier({}, { errorState: "offline" })).online);
checkEq("on comes from the relay's onState", V.view(purifier({}, { onState: false })).on, false);
checkEq("filter low under 10%", [V.view(purifier({ filterLife: 9 })).filterLow, V.view(purifier({ filterLife: 10 })).filterLow],
        [true, false]);
checkEq("filter clamped", V.view(purifier({ filterLife: 140 })).filter, 100);
checkEq("string booleans are read too", [V.view(purifier({ childLock: "True" })).childLock,
                                         V.view(purifier({ displayOn: "False" })).display], [true, false]);
checkEq("a missing PM2.5 is null, not 0", V.view(purifier({ pm25: "" })).pm25, null);

// ── presses ──
const sent = (command, value, ago = 0) => ({ command, value, sentAt: NOW - ago });
check("fan speed confirmed when the state reads it", V.confirmed(V.view(purifier({ fanLevel: 3 })), sent("fanSpeed", "3")));
check("fan speed not yet", !V.confirmed(v, sent("fanSpeed", "3")));
check("mode", V.confirmed(V.view(purifier({ mode: "sleep" })), sent("mode", "sleep")));
check("auto setting", V.confirmed(v, sent("autoPreference", "efficient")));
check("child lock on", V.confirmed(V.view(purifier({ childLock: true })), sent("childLock", "on")));
check("display off", V.confirmed(V.view(purifier({ displayOn: false })), sent("display", "off")));
check("power off", V.confirmed(V.view(purifier({}, { onState: false })), sent("power", false)));
checkEq("waiting inside 45 s", V.pressStatus(v, sent("mode", "sleep", 10000), NOW), "waiting");
checkEq("late after 45 s", V.pressStatus(v, sent("mode", "sleep", 46000), NOW), "late");
checkEq("nothing to say once it has taken", V.pressStatus(v, sent("mode", "auto", 46000), NOW), null);
checkEq("nothing to say with no press", V.pressStatus(v, undefined, NOW), null);

// ── "read 2 minutes ago" ──
checkEq("minutes, rounded down", V.updatedWords("2026-10-24 13:30:05", NOW), "2 minutes ago");
checkEq("singular", V.updatedWords("2026-10-24 13:31:05", NOW), "1 minute ago");
checkEq("just now", V.updatedWords("2026-10-24 13:31:50", NOW), "just now");
checkEq("hours", V.updatedWords("2026-10-24 10:30:05", NOW), "3 hours ago");
checkEq("no stamp", V.updatedWords("", NOW), "");

// ── the page sends only what the server allows ──
const html = fs.readFileSync(path.join(PAGES, "levoit.html"), "utf8");
check("page loads its view and the chart", html.includes('<script src="levoit-view.js">') && html.includes('<script src="chart.umd.min.js">'));
check("power goes through turnOn / turnOff", /indigo\.turnOn\(id\)/.test(html) && /indigo\.turnOff\(id\)/.test(html));
check("every other control goes through levoitControl", html.includes('DashUI.message("levoitControl"'));
check("controls pass the PIN / guest gate first", /indigo\.gateAny\(\[id\]\)/.test(html));
check("device names are escaped", html.includes("esc(v.name)") && html.includes("esc(d.name)"));
check("no device id is hard-coded", !/deviceId:\s*\d/.test(html));

// ── the menu tile ──
const menu = fs.readFileSync(path.join(PAGES, "menu.html"), "utf8");
check("the menu has an Air tile needing the Levoit plugin",
      /\["levoit\.html",\s*"Air",\s*"[^"]+",\s*"[^"]*",\s*"purifier",\s*"levoit"\]/.test(menu));
check("tileHidden honours levoitAvailable", /need === "levoit" && cfgM\.levoitAvailable === false/.test(menu));
const icons = fs.readFileSync(path.join(PAGES, "dashboards-icons.js"), "utf8");
check("the purifier icon exists", /\n\s*purifier:\s*'M/.test(icons));

// ── press feedback (CliveS, 24-10-2026: red and blue, no dotted outline) ──
check("the selected setting is solid blue", /\.seg button\.on \{ background: var\(--sel-blue\)/.test(html));
check("a pressed button is solid red", /\.seg button\.waiting \{ background: var\(--wait-red\)/.test(html));
check("a flicked switch is red while it waits", /\.toggle\.waiting \.slider/.test(html));
check("no dotted or dashed outline", !/dashed|dotted/.test(html));
check("a repeat of the press on its way is ignored", /const busy = \(_press\[id\] \|\| \{\}\)\[command\];/.test(html) && /busy && String\(busy\.value\) === String\(value\)/.test(html));
check("each control keeps its own press, so two quick presses both stay red", /\(_press\[id\] = _press\[id\] \|\| \{\}\)\[command\] =/.test(html));

done("levoit view");
