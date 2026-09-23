// Filename:    test_dash_poll.mjs
// Description: Contract test for DashUI.poll (v3.28.0): one polling loop for
//              every page. It must skip a tick while the tab is hidden, never
//              start a run while the last is still in flight, run at once when
//              the tab comes back, and stop when told.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0
//
// Run: node tests/test_dash_poll.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const src = fs.readFileSync(path.join(PAGES, "dashboards-ui.js"), "utf8");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const listeners = {};
const doc = { hidden: false, addEventListener: (e, f) => { (listeners[e] = listeners[e] || []).push(f); },
              removeEventListener: (e, f) => { listeners[e] = (listeners[e] || []).filter(x => x !== f); } };
const win = { document: doc, setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, Promise };
win.window = win;
vm.createContext(win);
vm.runInContext(src, win);
const poll = win.DashUI.poll;

{
    let n = 0;
    const p = poll(() => { n++; }, 20);
    check("runs at once", n === 1);
    await sleep(70);
    check("and on every tick", n >= 3);
    p.stop();
    const was = n; await sleep(60);
    check("stop means stop", n === was);
}
{
    let n = 0;
    doc.hidden = true;
    const p = poll(() => { n++; }, 15);
    await sleep(60);
    check("a hidden tab does not poll", n === 0);
    doc.hidden = false;
    (listeners.visibilitychange || []).forEach(f => f());
    check("coming back runs at once", n === 1);
    p.stop();
}
{
    let started = 0, release;
    const p = poll(() => { started++; return new Promise(r => { release = r; }); }, 10);
    await sleep(60);
    check("a slow run is never overtaken by the next tick", started === 1);
    release(); await sleep(25);
    check("the next tick runs once it has settled", started === 2);
    p.stop(); release();
}
{
    let n = 0;
    const p = poll(() => { n++; throw new Error("boom"); }, 15);
    await sleep(50);
    check("a run that throws does not stop the loop", n >= 2);
    p.stop();
}
{
    // Pages that poll the plugin go through DashUI.poll, not a bare timer.
    const bare = [];
    for (const f of ["carbon.html", "cost.html", "meter.html", "mains.html", "laundry.html",
                     "presence.html", "scenes.html", "system-health.html", "activity.html"]) {
        const s = fs.readFileSync(path.join(PAGES, f), "utf8");
        if (/setInterval\((load|tick|refreshVpp|refreshWeekCompare)\b/.test(s)) bare.push(f);
    }
    check("no page polls the plugin with a bare setInterval" + (bare.length ? ": " + bare.join(", ") : ""), bare.length === 0);
}
done();
