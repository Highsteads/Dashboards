// Filename:    test_idle_guard.mjs
// Description: Contract test for DashUI.idleGuard, DashUI.lanUrl and the
//              server-verdict override in DashUI.linkClass (v2.96.1). A page
//              on the reflector must stop its pictures after idleMs with no
//              touch and start again on the first one; a changedSince reply
//              that says via:"reflector" makes linkClass answer "reflector"
//              whatever the address says; lanUrl never offers a loopback.
// Author:      CliveS & Claude Fable 5.1
// Date:        02-09-2026
// Version:     1.0
//
// Run: node tests/test_idle_guard.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UI = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                     "Resources", "static", "pages", "dashboards-ui.js");
const src = fs.readFileSync(UI, "utf8");

function makeWindow(hostname) {
    const listeners = {};
    const doc = {
        hidden: false,
        addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
        querySelector: () => null, getElementById: () => null,
        // pressFeedback injects a stylesheet on load, so the fake document
        // needs a head it can append to.
        readyState: "complete",
        createElement: () => ({ set textContent(_v) {}, style: {} }),
        head: { appendChild: () => {} },
        documentElement: { style: {} }, body: { classList: { add() {}, remove() {} } },
    };
    const win = { document: doc, location: { hostname }, INDIGO_CONFIG: {},
                  setInterval, clearInterval, setTimeout, clearTimeout, Date, Math,
                  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
                  matchMedia: () => ({ matches: false, addEventListener() {} }),
                  getComputedStyle: () => ({ getPropertyValue: () => "" }),
                  requestAnimationFrame: (f) => setTimeout(f, 0), performance: { now: () => Date.now() },
                  fire: (ev) => (listeners[ev] || []).forEach(fn => fn({ target: { closest: () => null } })) };
    win.window = win; win.self = win;
    vm.createContext(win);
    vm.runInContext(src, win, { filename: "dashboards-ui.js" });
    return win;
}

let failed = 0;
function check(name, ok) { console.log((ok ? "PASS" : "FAIL") + "  " + name); if (!ok) failed++; }

const w = makeWindow("myhouse.indigodomo.net");
check("a name that is not an address classes as reflector", w.DashUI.linkClass() === "reflector");
const h = makeWindow("192.168.1.10");
check("a LAN address classes as home", h.DashUI.linkClass() === "home");
h.__DASH_VIA = "reflector";
check("the server's via:reflector verdict overrides a LAN address", h.DashUI.linkClass() === "reflector");

h.INDIGO_CONFIG = { lanURL: "http://192.168.1.10:8176/", baseURL: "http://127.0.0.1:8176" };
check("lanUrl builds the page address from lanURL", h.DashUI.lanUrl("cameras.html") === "http://192.168.1.10:8176/public/dashboards/cameras.html");
h.INDIGO_CONFIG = { baseURL: "http://127.0.0.1:8176" };
check("lanUrl never offers a loopback address", h.DashUI.lanUrl() === "");

let idled = 0, resumed = 0;
const g = w.DashUI.idleGuard(300, () => idled++, () => resumed++);
await new Promise(r => setTimeout(r, 120));
check("not idle before idleMs", g.isIdle() === false && idled === 0);
await new Promise(r => setTimeout(r, 400));
check("idle after idleMs with nothing touched", g.isIdle() === true && idled === 1);
w.fire("pointerdown");
check("one touch resumes", g.isIdle() === false && resumed === 1);
await new Promise(r => setTimeout(r, 800));   // idleMs plus two check ticks of slack
check("and it idles again, once", idled === 2 && resumed === 1);
w.document.hidden = false; w.fire("visibilitychange");
check("coming back to the tab counts as a touch", resumed === 2);
g.stop();

process.exit(failed ? 1 : 0);
