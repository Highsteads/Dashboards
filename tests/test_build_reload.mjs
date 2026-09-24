// Filename:    test_build_reload.mjs
// Description: An open page reloads itself when the plugin is newer than the
//              code it is running (3.45.8). The stamp carries "build"; the
//              page knows window.DASHBOARDS_BUILD from config.js. A Safari
//              web app left open on the Mac mini ran 3.45.0 for hours after
//              3.45.7 was installed, and kept its old camera code with it.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_build_reload.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                            "Resources", "static", "pages", "dashboards-gate.js"), "utf8");

function page({ mine = "3.45.7", hidden = false, store = new Map() } = {}) {
    const calls = { reload: 0, replace: [] }, listeners = {};
    let now = 1_000_000;
    const win = { DASHBOARDS_BUILD: mine };
    const doc = { hidden,
                  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
                  removeEventListener: (t, f) => { listeners[t] = (listeners[t] || []).filter(x => x !== f); } };
    let stamp = { v: 1, boot: 1, ts: 1, hwm: 0, state: "run", build: "3.45.7" };
    const ctx = {
        window: win, document: doc, URL,
        location: { href: "http://h:8176/public/dashboards/index.html",
                    reload: () => { calls.reload++; }, replace: u => calls.replace.push(u) },
        sessionStorage: { getItem: k => (store.has(k) ? store.get(k) : null),
                          setItem: (k, v) => store.set(k, String(v)) },
        Date: { now: () => now },
        fetch: async () => ({ status: 200, ok: true, json: async () => stamp }),
        AbortController: class { constructor() { this.signal = {}; } abort() {} },
        setTimeout: () => 0, clearTimeout: () => {}, console,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    const G = win.DashGate;
    return {
        calls, doc, listeners, store,
        async tick(build) { stamp = Object.assign({}, stamp, { build, ts: stamp.ts + 1 }); now += 3000; await G.check(); },
    };
}

let p = page();
await p.tick("3.45.7");
check("the same build as the page: no reload", p.calls.reload === 0 && !p.calls.replace.length);

p = page();
await p.tick("3.45.8");
check("a newer build on the server reloads a visible page", p.calls.reload === 1);
await p.tick("3.45.8");
check("…once, not on every stamp", p.calls.reload === 1);

// The reload came back with the old page (a stale cache): the second go puts
// the build in the address, which no cache can answer with the old page.
const shared = new Map();
p = page({ store: shared });
await p.tick("3.45.8");
p = page({ store: shared });                      // same tab, reloaded, still old code
await p.tick("3.45.8");
check("a second attempt navigates to an address carrying the build",
      p.calls.reload === 0 && p.calls.replace.length === 1 && /[?&]build=3\.45\.8/.test(p.calls.replace[0]),
      JSON.stringify(p.calls));
p = page({ store: shared });
await p.tick("3.45.8");
check("…and after two goes it stops (no reload loop)", p.calls.reload === 0 && !p.calls.replace.length);

p = page({ hidden: true });
await p.tick("3.45.8");
check("a hidden page waits", p.calls.reload === 0);
p.doc.hidden = false;
(p.listeners.visibilitychange || []).forEach(f => f());
check("…and reloads when it is shown", p.calls.reload === 1);

p = page({ mine: null });
await p.tick("3.45.8");
check("a page that does not know its own build never reloads", p.calls.reload === 0);

done();
