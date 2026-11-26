// Filename:    test_review_batch13.mjs
// Description: Thirteenth group from the 25/26-Nov-2026 review (3.73.14):
//                - a camera tile left waiting for a tap opened live video on
//                  the next tap whatever the page's policy had become;
//                - Configure still described a card that was removed in
//                  3.69.2, and the go2rtc path sat under System Health.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch13.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents");
const cams = fs.readFileSync(path.join(ROOT, "Resources", "static", "pages", "cameras.html"), "utf8");
const grab = (src, name) => { const i = src.indexOf("function " + name + "("); if (i < 0) throw new Error("not found: " + name); let d = 0;
    for (let j = src.indexOf("{", i); j < src.length; j++) { if (src[j] === "{") d++; else if (src[j] === "}" && --d === 0) return src.slice(i, j + 1); } };

console.log("Cameras: a tap opens live video only where the page would");
{
    const c = vm.createContext({ console });
    vm.runInContext(`var WEBRTC_FOCUS = false, LIVE_POOL_SIZE = 0, LIVE_FOLLOWS_FOCUS = false, focusedHost = null;
        var hosts = ["a", "b", "c"], DEFAULT_LIVE = ["a", "b"], DEFAULT_LIVE_SET = new Set(DEFAULT_LIVE);
        ${grab(cams, "mayHoldLive")}
        ${grab(cams, "tapMayGoLive")}
        globalThis.T = tapMayGoLive;
        globalThis.set = (f, p, foc) => { WEBRTC_FOCUS = f; LIVE_POOL_SIZE = p; focusedHost = foc || null; };`, c);
    c.set(false, 0);
    checkEq("the link was measured as too slow for any: no tile goes live", ["a", "b", "c"].map(c.T), [false, false, false]);
    c.set(false, 2);
    checkEq("a pool of two: its two tiles, not the third", ["a", "b", "c"].map(c.T), [true, true, false]);
    c.set(true, 0, "c");
    checkEq("one stream allowed: the focused tile only", ["a", "b", "c"].map(c.T), [false, false, true]);
    c.set(true, 0);
    checkEq("with nothing focused that is the first tile", ["a", "b", "c"].map(c.T), [true, false, false]);
    check("the tap clears every claim, then starts only those still entitled",
          /flagged\.forEach\(h => \{ camState\[h\]\.needsTap = false; \}\);\s*const waiting = flagged\.filter\(tapMayGoLive\);/.test(cams)
          && /waiting\.forEach\(h => \{ startWebrtc\(h\); \}\);/.test(cams));
    check("a new layout drops a claim made under the old one", /st\.needsTap      = false;/.test(cams));
}

console.log("\nConfigure: what the dialog says is what the plugin does");
{
    const xml = fs.readFileSync(path.join(ROOT, "Server Plugin", "PluginConfig.xml"), "utf8");
    const carbon = (/<Field id="hlpCarbon"[\s\S]*?<Label>([\s\S]*?)<\/Label>/.exec(xml) || [])[1] || "";
    check("the carbon region no longer promises a card that was removed",
          /No page uses it at present/.test(carbon) && /removed in 3\.69\.2/.test(carbon) && !/Pick the DNO region closest to you, or Off to hide it/.test(carbon), carbon);
    check("the go2rtc path has a heading of its own, after a separator",
          /<Field id="sep_cameras" type="separator"\/>\s*<Field id="label_cameras" type="label">\s*<Label>Cameras<\/Label>\s*<\/Field>\s*<Field id="go2rtcPath"/.test(xml));
    const ids = Array.from(xml.matchAll(/<Field id="([^"]+)"/g), m => m[1]);
    checkEq("no field id is used twice", ids.length, new Set(ids).size);
    const hint = fs.readFileSync(path.join(ROOT, "Server Plugin", "scripts_mixin.py"), "utf8");
    check("the laundry script's hint does not name the removed card either", !/When to run it card/.test(hint) && /the laundry planner/.test(hint));
}

done();
