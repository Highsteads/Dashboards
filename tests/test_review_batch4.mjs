// Filename:    test_review_batch4.mjs
// Description: Fourth group from the 25/26-Nov-2026 review (3.73.7):
//                - camera health read from an old streams.json was "stale" on
//                  the first read and "ok" on the second, though the file had
//                  not been written again;
//                - one camera with no still on disk made the speed test fail,
//                  which switched live video off for every camera on the page;
//                - the Cameras page could start live streams in a hidden tab;
//                - the hub printed a negative "Solar saved" in green.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch4.mjs   (exit 0 = pass)

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

console.log("camera health from a file that is not being written");
{
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, INDIGO_CONFIG: {} };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    const T = win.DashUI.cameraHealthTracker(60000);
    const now = 1795650000000, old = now / 1000 - 1200;            // written twenty minutes ago
    const file = { _writeTs: old, _go2rtcUp: true, _cameraHealth: { a: "ok" } };
    checkEq("the first read of an old file is stale", T.feed(file, now).state, "stale");
    checkEq("and so is the second read of the same file", T.feed(file, now + 3000).state, "stale");
    checkEq("and the tenth", T.feed(file, now + 30000).state, "stale");
    checkEq("once it is written again it is believed", T.feed({ ...file, _writeTs: (now + 31000) / 1000 }, now + 32000).state, "ok");
    const F = win.DashUI.cameraHealthTracker(60000);
    checkEq("a file written just now is ok at once", F.feed({ ...file, _writeTs: now / 1000 - 2 }, now).state, "ok");
}

console.log("\nthe speed test with one camera that has no still");
{
    const ctx = { window: { location: { hostname: "x" } }, console, setTimeout, clearTimeout, setInterval, clearInterval, AbortController, Promise };
    vm.createContext(ctx);
    vm.runInContext(read("dashboards-webrtc.js"), ctx);
    const R = ctx.window.DashRTC;
    let t = 0;
    const fetcher = bad => async u => (bad.some(b => u.indexOf(b) >= 0)
        ? { ok: false, status: 404 } : { ok: true, blob: async () => ({ size: 100000 }) });
    const urls = ["cam-a.jpg", "cam-b.jpg", "cam-c.jpg", "cam-d.jpg"];
    const one = await R._round(urls, { fetch: fetcher(["cam-b"]), clock: () => (t += 50) });
    checkEq("the three that answered are measured", one.bytes, 300000);
    let threw = false;
    try { await R._round(urls, { fetch: fetcher(["cam-a", "cam-b", "cam-c"]), clock: () => (t += 50) }); } catch (e) { threw = true; }
    check("with only one answering there is nothing to measure", threw);
    const all = await R._round(urls, { fetch: fetcher([]), clock: () => (t += 50) });
    checkEq("all four as before", all.bytes, 400000);
    const single = await R._round(["cam-a.jpg"], { fetch: fetcher([]), clock: () => (t += 50) });
    checkEq("a house with one camera is still measured", single.bytes, 100000);
}

console.log("\nthe Cameras page does not lay out live video in a hidden tab");
check("the measured policy is applied, and laid out only when the page is showing",
      /if \(typeof document === "undefined" \|\| !document\.hidden\) relayoutAll\(\);\s*\}\s*renderPolicy\(ms\);/.test(read("cameras.html")));

console.log("\nthe hub's saving row keeps its sign");
{
    const hub = read("index.html");
    const ctx = vm.createContext({});
    vm.runInContext(extractFn(hub, "benefitRow") + "\nglobalThis.b = benefitRow;", ctx);
    const pos = ctx.b({ benefit: 1.85 }), neg = ctx.b({ benefit: -1.37 });
    check("a saving is green", /<span class="key">Solar saved<\/span><span class="val ok">£1\.85<\/span>/.test(pos), pos);
    check("a day behind is not called a saving, and is not green",
          /Behind a grid-only day/.test(neg) && /£1\.37/.test(neg) && !/val ok/.test(neg) && !/Solar saved/.test(neg), neg);
    checkEq("no figure, no row", [ctx.b(null), ctx.b({})], ["", ""]);
    check("both layouts use it", (hub.match(/\$\{benefitRow\(m\)\}/g) || []).length === 2 && !/<span class="val ok">\$\{benefitStr\}/.test(hub));
}

done();
