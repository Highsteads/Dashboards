// Filename:    test_review_batch10.mjs
// Description: Tenth group from the 25/26-Nov-2026 review (3.73.12), the
//              Cameras page and the hub's camera strip:
//                - a hub tile the browser paused stayed captioned "Live" over
//                  a frozen frame;
//                - a tile that was only connecting read "Live" or "Video stopped";
//                - a health file abandoned up to ten minutes ago read as
//                  health OK on a freshly opened page;
//                - cameras never checked counted as healthy;
//                - a still was dated, and marked as held, before it was shown;
//                - the data rates showed 0 kB/s before anything was measured,
//                  and a tile's rate was a byte count called "per second".
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch10.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

function extractFn(s, name) {
    const start = s.indexOf("function " + name + "(");
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unterminated: " + name);
}

const hub = read("index.html");
const cams = read("cameras.html");
const rtc = read("dashboards-webrtc.js");

console.log("hub strip: a video the browser has paused");
check("the tile stops saying Live and takes a fresh still",
      /onBlocked: \(\) => \{\s*if \(s\.rtc !== rtc\) return;\s*_hubNote\(HUB_TAP_NOTE\);\s*frame\.classList\.remove\("is-live"\);[\s\S]{0,160}window\._hubSwapIn\(img, true\);/.test(hub));
check("the tap that starts it again puts Live back, only if it had been live",
      /onUnblocked: \(\) => \{ if \(s\.rtc === rtc && s\.wasLive\) frame\.classList\.add\("is-live"\); \}/.test(hub)
      && /s\.wasLive = true;\s*frame\.classList\.add\("is-live"\);/.test(hub));
check("the video helper tells the page when the tap worked",
      /h\._onUnblocked = opts\.onUnblocked \|\| null;/.test(rtc) && /if \(h\._onUnblocked\) \{ try \{ h\._onUnblocked\(\); \}/.test(rtc));

console.log("\nCameras page: a tile that is only connecting");
{
    const tick = extractFn(cams, "tickAges");
    check("says Connecting until the first frame",
          /if \(!st\.webrtcGotFrame\) \{\s*txt = "Connecting";\s*\} else if \(st\.lastChangeAt\) \{/.test(tick));
}

console.log("\ncamera health: the first read of the file");
{
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, INDIGO_CONFIG: {} };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    const mk = () => win.DashUI.cameraHealthTracker(60000);
    const now = 2_000_000_000_000;
    const file = ageS => ({ _writeTs: (now / 1000) - ageS, _go2rtcUp: true, _cameraHealth: { a: { state: "ok" } } });
    checkEq("written two seconds ago: believed at once", mk().feed(file(2), now).state, "ok");
    const T = mk();
    const old = file(300);                                    // the writer stopped five minutes ago
    checkEq("written five minutes ago: not yet believed", T.feed(old, now).state, "checking");
    checkEq("the same file four seconds later: still not", T.feed(old, now + 4000).state, "checking");
    checkEq("and after a minute with no new write: stale", T.feed(old, now + 61000).state, "stale");
    const S = mk();                                           // a phone whose clock is five minutes out
    checkEq("a healthy file seen by a wrong clock waits one read", S.feed(file(300), now).state, "checking");
    checkEq("then is believed when the file has been written again", S.feed(file(296), now + 4000).state, "ok");
    check("the hub reads again in four seconds", /if \(v\.state === "checking" && !_camRecheck\) \{\s*_camRecheck = setTimeout\(/.test(hub));
    check("so does the Cameras page", /if \(v\.state === "checking"\) \{[\s\S]{0,260}el\.textContent = "health checking";[\s\S]{0,80}_healthLastFetch = Date\.now\(\) - 30000 \+ 4000;/.test(cams));
}

console.log("\ncamera health: never checked is not healthy");
{
    const c = { console };
    vm.createContext(c);
    vm.runInContext(extractFn(cams, "cameraHealthWords") + "\nglobalThis.W = cameraHealthWords;", c);
    checkEq("all checked and well", c.W(0, 0, 0), "health OK");
    checkEq("three never checked", c.W(0, 0, 3), "3 not checked");
    checkEq("offline still comes first", c.W(1, 2, 3), "1 camera offline");
    checkEq("then retrying", c.W(0, 2, 3), "2 cameras retrying");
    check("the page counts them", /const unchecked = rows\.filter\(x => !x \|\| x\.state === "unknown"\)\.length;/.test(cams));
    check("the hub lists the cameras as checked only when every one has an answer",
          /!Object\.values\(CAMHEALTH\)\.some\(x => !x \|\| x\.state === "unknown"\)\) checked\.push\(ATT_NAMES\.cams\);/.test(hub));
}

console.log("\nCameras page: a still is dated when it is shown");
check("the header is held until then", /st\._lastMod200 = r\.headers\.get\("Last-Modified"\) \|\| null;/.test(cams)
      && !/st\.lastMod = r\.headers\.get\("Last-Modified"\) \|\| st\.lastMod;/.test(cams));
check("and adopted with the frame",
      /st\.objUrl = url;[\s\S]{0,120}if \(modHdr\) st\.lastMod = modHdr;\s*if \(modMs != null && !isNaN\(modMs\)\) st\.frameModMs = modMs;/.test(cams));

console.log("\nCameras page: data rates");
{
    const c = { console, isFinite };
    vm.createContext(c);
    vm.runInContext(extractFn(cams, "tileRateKb") + extractFn(cams, "rateWords") + "\nglobalThis.R = tileRateKb; globalThis.W = rateWords;", c);
    checkEq("the first reading has nothing to compare with", c.R(0, 0, 5_000_000, 1000), null);
    checkEq("no figure is shown for it", c.W(null), "—");
    checkEq("a second on time: 200 kB in one second", c.W(c.R(1_000_000, 1000, 1_204_800, 2000)), "200 kB/s");
    checkEq("a late tick: 400 kB over two seconds is still 200 kB/s", c.W(c.R(1_000_000, 1000, 1_409_600, 3000)), "200 kB/s");
    checkEq("megabytes", c.W(2048), "2.0 MB/s");
    checkEq("a counter that went backwards (a new connection) gives no figure", c.R(9_000_000, 1000, 100, 2000), null);
    check("both totals start at a dash", /<span id="total-bw">—<\/span>/.test(cams) && /<span id="total-bw-bot">—<\/span>/.test(cams));
    check("the total waits for two samples", /_setBw\(rateWords\(hadSample \? ownKBs : null\)\);/.test(cams));
    check("a new stream starts with no earlier reading", /st\.lastRtcAt      = 0;/.test(cams));
}

done();
