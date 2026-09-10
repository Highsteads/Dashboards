// Filename:    test_reflector_block.mjs
// Description: Contract test for "refuse the reflector" (v3.1.0). Indigo
//              Domotics wrote twice about this server's reflector usage and
//              deactivated it; CliveS moved every away-from-home case onto
//              Tailscale and asked for the reflector to be refused outright.
//
//              THE TRAP THIS LOCKS
//              The page-side refusal lives in dashboards-auth.js, which loads
//              BEFORE dashboards-ui.js on 18 of the 20 pages. A check written
//              as `window.DashUI && DashUI.linkClass() === "reflector"` would
//              therefore be a silent no-op on exactly the pages that matter —
//              the same "guarded call to a library the page never loaded"
//              fault this project has hit before. So the refusal must decide
//              for itself, and its verdict must still agree with DashUI's.
// Author:      CliveS & Claude Opus 5
// Date:        03-09-2026
// Version:     1.0
//
// Run: node tests/test_reflector_block.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");
const authSrc = fs.readFileSync(path.join(PAGES, "dashboards-auth.js"), "utf8");
const uiSrc   = fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8");

let failed = 0;
const check = (n, ok, why) => {
    console.log((ok ? "  ok   " : "  FAIL ") + n + (why ? "   " + why : ""));
    if (!ok) failed++;
};

// Pull the refusal's own address test out of the shipped file.
const start = authSrc.indexOf("var _isReflectorAddress = function () {");
if (start < 0) { console.log("  FAIL the refusal has no self-contained address test"); process.exit(1); }
const end = authSrc.indexOf("};", authSrc.indexOf("return true;", start)) + 2;
const fnSrc = authSrc.slice(start, end);

function isReflector(hostname) {
    const box = { location: { hostname } };
    vm.createContext(box);
    vm.runInContext(fnSrc + "\nvar __r = _isReflectorAddress();", box);
    return box.__r;
}

console.log("\nthe refusal decides for itself");
check("it does not depend on DashUI",
      !/window\.DashUI[\s\S]{0,80}reflectorBlock|reflectorBlock[\s\S]{0,120}window\.DashUI/.test(authSrc),
      "auth.js runs before ui.js on 18 of 20 pages");
check("and dashboards-ui.js is indeed loaded after it on a real page",
      (() => {
          const p = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");
          return p.indexOf("dashboards-auth.js") < p.indexOf("dashboards-ui.js");
      })(),
      "if this ever flips, the reason for the duplication is gone");

console.log("\nand it agrees with DashUI.linkClass on every address");
const cases = [
    ["myhouse.indigodomo.net", true],
    ["some.example.com",          true],
    ["203.0.113.9",               true],
    ["192.168.1.10",           false],
    ["10.0.0.5",                  false],
    ["172.20.1.1",                false],
    ["127.0.0.1",                 false],
    ["localhost",                 false],
    ["indigo.tail-example.ts.net", false],
    ["indigo.local",              false],
    ["100.68.100.160",            false],
];
for (const [host, want] of cases) {
    const got = isReflector(host);
    check(`${host} -> ${got ? "reflector" : "allowed"}`, got === want);
    // and the same verdict from DashUI, which is the page's other opinion
    const box = { window: null, location: { hostname: host }, document: null,
                  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
                  Date, Math, JSON, setInterval, clearInterval, setTimeout, clearTimeout };
    box.window = box; box.self = box;
    vm.createContext(box);
    vm.runInContext(uiSrc, box, { filename: "dashboards-ui.js" });
    const ui = box.DashUI.linkClass() === "reflector";
    check(`   DashUI agrees for ${host}`, ui === want,
          ui === want ? "" : `DashUI says ${box.DashUI.linkClass()}`);
}

console.log("\nand the page says what to do instead");
check("the notice offers the LAN address", /cfg\.lanURL/.test(authSrc));
check("it names the setting that turns it off", /Refuse the reflector/.test(authSrc));
check("it stops before any page code runs", /_isReflectorAddress\(\)\)\s*\{[\s\S]{0,2000}return;\s*\n\s*\}/.test(authSrc),
      "returning is what stops the camera pictures being asked for");

process.exit(failed ? 1 : 0);
