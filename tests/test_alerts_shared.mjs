// Filename:    test_alerts_shared.mjs
// Description: The Alerts rules as the pages see them (2.0, 3.47.0). The
//              plugin judges the rules now and the pages only raise browser
//              notifications for its firings. These checks drive the shipped
//              dashboards-alerts.js: every case in lib/alert_rule_cases.json
//              through the page's own judgeDevice / judgeVariable / deviceNow
//              / ruleKey / claim (the plugin's Python is held to the same
//              file), a firing raised only when its rule includes "browser",
//              a new page raising nothing already past, two tabs raising ONE
//              notification, a tab standing by while another polls, storage
//              that throws, the old localStorage rules read for the move to
//              the plugin, and no rule judged in the browser any more.
// Author:      CliveS & Claude Opus 5.5; CliveS & Claude (2.0)
// Date:        25-09-2026
// Version:     2.0
//
// Run: node tests/test_alerts_shared.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const SRC = fs.readFileSync(path.join(PAGES, "dashboards-alerts.js"), "utf8");
const CASES = JSON.parse(fs.readFileSync(path.join(HERE, "lib", "alert_rule_cases.json"), "utf8"));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function sharedStorage() {
    const m = new Map();
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), _m: m };
}
const throwingStorage = {
    getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("SecurityError"); },
    removeItem() { throw new Error("SecurityError"); },
};

// One browser tab: its own module instance, a storage it may share.
function tab(storage) {
    const shown = [];
    function Notification(title, opts) { shown.push({ title, body: opts.body }); }
    Notification.permission = "granted";
    const win = { localStorage: storage, Notification, INDIGO_CONFIG: { siteName: "Home" },
                  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
                  Map, JSON, Math, Date, Object, String, Array, Promise, isFinite,
                  navigator: {} };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(SRC, win, { filename: "dashboards-alerts.js" });
    return { win, A: win.DashAlerts, shown };
}

// A stand-in for the plugin's alertRules reply.
function server() {
    const s = { seq: 1000, firings: [], asked: 0, browserRules: 1 };
    s.fire = (text, channels = ["pushover", "browser"], ageS = 0) => {
        s.seq += 1;
        s.firings.unshift({ seq: s.seq, t: Date.now() / 1000 - ageS, text, channels,
                            delivered: [], failed: [], pending: false });
    };
    s.message = async (name, body) => {
        s.asked++;
        if (name !== "alertRules") throw new Error("unexpected " + name);
        return { ok: true, seq: s.seq, now: Date.now() / 1000, browserRules: s.browserRules,
                 browserWindow: 600, firings: s.firings.filter(f => f.seq > (body.firingsSince || 0)) };
    };
    return s;
}

// ── the shared rule cases (the plugin's Python runs the same file) ──
{
    const { A } = tab(sharedStorage());
    let n = 0;
    for (const c of CASES.deviceNow) {
        n++;
        check(`deviceNow ${JSON.stringify(c.dev)}`, JSON.stringify(A.deviceNow(c.dev)) === JSON.stringify(c.expect),
              JSON.stringify(A.deviceNow(c.dev)));
    }
    for (const c of CASES.device) {
        n++;
        const was = c.was === null ? null : A.deviceNow(c.was);
        const got = A.judgeDevice(c.rule, was, A.deviceNow(c.now));
        check(`device: ${c.why}`, got === c.expect, String(got));
    }
    for (const c of CASES.variable) {
        n++;
        const got = A.judgeVariable(c.rule, c.was, c.value);
        check(`variable: ${c.why}`, got === c.expect, String(got));
    }
    for (const c of CASES.ruleKey) {
        n++;
        check(`ruleKey ${c.expect}`, A.ruleKey(c.rule) === c.expect, A.ruleKey(c.rule));
    }
    for (const c of CASES.cooldown) {
        n++;
        const fresh = tab(throwingStorage).A;       // its own in-memory record
        const got = c.events.map(([k, t]) => fresh.claim(k, "me", t, throwingStorage));
        check(`cooldown: ${c.why}`, JSON.stringify(got) === JSON.stringify(c.expect), JSON.stringify(got));
    }
    check("the shared cases were all run", n >= 40, String(n));
}

// ── the plugin's firings become browser notifications ──
{
    const store = sharedStorage();
    const t = tab(store);
    const srv = server();
    srv.fire("Old news");                                   // before this page opened
    const w = t.A.watch({ message: srv.message, autoTick: false });
    await w.poll();
    await sleep(300);
    check("a new page raises nothing already past", t.shown.length === 0, JSON.stringify(t.shown));
    srv.fire("Hall turned on");
    srv.fire("Pump turned on", ["pushover"]);               // no browser channel
    await w.poll();
    await sleep(300);
    check("a firing with Browser ticked is raised", t.shown.some(s => s.body === "Hall turned on"));
    check("a firing without it is not", !t.shown.some(s => s.body === "Pump turned on"));
    check("the title is the site name", t.shown[0] && t.shown[0].title === "Home");
    await w.poll();
    await sleep(300);
    check("and it is raised once, not on every poll", t.shown.length === 1, JSON.stringify(t.shown));
    srv.fire("Stale", ["browser"], 3600);
    await w.poll();
    await sleep(300);
    check("a firing older than the window is not raised", !t.shown.some(s => s.body === "Stale"));
    w.stop();
}

// ── two tabs, one firing, one notification ──
{
    const store = sharedStorage();
    const a = tab(store), b = tab(store);
    const srv = server();
    const wa = a.A.watch({ message: srv.message, alwaysPoll: true, autoTick: false });
    const wb = b.A.watch({ message: srv.message, alwaysPoll: true, autoTick: false });
    await wa.poll(); await wb.poll();                         // both seeded
    srv.fire("Door turned on");
    // Both read the shared "seen" before either writes it.
    await Promise.all([wa.poll(), wb.poll()]);
    await sleep(300);
    const total = a.shown.length + b.shown.length;
    check("two tabs that both saw the firing raise ONE notification", total === 1, `a=${a.shown.length} b=${b.shown.length}`);
    await wa.poll(); await wb.poll(); await sleep(300);
    check("and neither raises it again later", a.shown.length + b.shown.length === 1);
    wa.stop(); wb.stop();
}

// ── a tab stands by while another polls ──
{
    const store = sharedStorage();
    const a = tab(store), b = tab(store);
    const srvA = server(), srvB = server();
    const wa = a.A.watch({ message: srvA.message, autoTick: false });
    await wa.poll();
    const wb = b.A.watch({ message: srvB.message, autoTick: false });
    await wb.poll();
    check("a second hub tab does not ask while the first one is", srvB.asked === 0, `asked ${srvB.asked}`);
    const beat = JSON.parse(store.getItem("dash_alerts_beat"));
    store.setItem("dash_alerts_beat", JSON.stringify({ tab: beat.tab, t: beat.t - a.A.BEAT_STALE_MS - 1 }));
    await wb.poll();
    check("and takes over once the first one has gone quiet", srvB.asked === 1, `asked ${srvB.asked}`);
    wa.stop(); wb.stop();
}

// ── storage that throws: this tab alone, still correct ──
{
    const lone = tab(throwingStorage);
    const srv = server();
    const w = lone.A.watch({ message: srv.message, autoTick: false });
    await w.poll();
    srv.fire("Gate turned on");
    await w.poll();
    await sleep(300);
    check("a tab whose storage throws still raises a new firing", lone.shown.length === 1, JSON.stringify(lone.shown));
    await w.poll(); await sleep(300);
    check("and only once", lone.shown.length === 1);
    check("the old rules read as none, not an exception", lone.A.loadLegacy().rules.length === 0);
    check("clearing them does not throw", lone.A.clearLegacy() === false);
    w.stop();
}

// ── pickFirings, pure ──
{
    const { A } = tab(sharedStorage());
    const reply = { seq: 20, now: 1000, firings: [
        { seq: 20, t: 990, text: "b", channels: ["browser"] },
        { seq: 19, t: 990, text: "a", channels: ["email", "browser"] },
        { seq: 18, t: 990, text: "old", channels: ["browser"] }] };
    const p = A.pickFirings(reply, { seq: 18 }, 600);
    check("pickFirings raises what is newer than seen, oldest first",
          JSON.stringify(p.raise.map(f => f.text)) === '["a","b"]' && p.seen === 20, JSON.stringify(p));
    const lost = A.pickFirings({ seq: 3, now: 1000, firings: [{ seq: 3, t: 999, text: "x", channels: ["browser"] }] }, { seq: 20 }, 600);
    check("a server whose numbers went back is followed down, raising nothing", lost.raise.length === 0 && lost.seen === 3);
    const first = A.pickFirings(reply, null, 600);
    check("no record yet: start from the newest, raise nothing", first.raise.length === 0 && first.seen === 20);
}

// ── the old rules, for the move to the plugin ──
{
    const store = sharedStorage();
    const { A } = tab(store);
    store.setItem("dash_alerts", JSON.stringify({ active: false, rules: [
        { kind: "device", id: 5, name: "Hall", cond: "on", enabled: true },
        { kind: "variable", id: 9, name: "Mode", cond: "on", enabled: false },
        { kind: "device", id: 5, name: "Hall again", cond: "on", enabled: true },
        { kind: "scene", id: 3, name: "Nope", cond: "on" },
        { kind: "device", id: "7", name: "Text id", cond: "on" },
        { kind: "device", id: 8, cond: "change" },
        "junk"] }));
    const legacy = A.loadLegacy();
    check("the old rules and switch are read", legacy.rules.length === 6 && legacy.active === false);
    const m = A.migrationRules(legacy);
    check("the plugin gets only what it will take", JSON.stringify(m.rules) === JSON.stringify([
        { kind: "device", id: 5, cond: "on", name: "Hall", enabled: true },
        { kind: "variable", id: 9, cond: "change", name: "Mode", enabled: false },
        { kind: "device", id: 8, cond: "change", name: "Device 8", enabled: true }]), JSON.stringify(m.rules));
    check("and the rest are counted, not hidden", m.skipped === 3, String(m.skipped));
    check("no channels are sent: the plugin gives each its default", m.rules.every(r => !("channels" in r)));
    check("clearing them after a move works", A.clearLegacy() === true && store.getItem("dash_alerts") === null);
}

// ── what the page says about the channels and a firing ──
{
    const { A } = tab(sharedStorage());
    check("Pushover ready", A.channelLine("pushover", { ready: true, status: "ready" }) === "Pushover: ready");
    check("Pushover plugin not running", A.channelLine("pushover", { ready: false, status: "plugin not running" }) === "Pushover: plugin not running");
    check("Pushover no user key", A.channelLine("pushover", { ready: false, status: "no user key" }) === "Pushover: no user key");
    check("email from IndigoSecrets", A.channelLine("email", { ready: true, source: "secrets" }) === "Email: ready (IndigoSecrets address)");
    check("a firing's outcome per channel",
          A.firingOutcome({ delivered: ["pushover"], failed: [{ channel: "email", reason: "no address" }], channels: ["pushover", "email", "browser"] })
          === "pushover sent · email failed (no address) · browser");
}

// ── nothing is judged in the browser any more ──
{
    check("the watcher no longer reads device or variable lists", !/getDevices|getVariables/.test(SRC));
    check("nor the old rules to evaluate them", !/function load\(/.test(SRC) && !/function save\(/.test(SRC));
    check("it asks the plugin for firings", /ask\('alertRules', \{ firingsSince:/.test(SRC));
    check("autoStart never runs for a guest or the demo",
          /if \(!cfg\.apiKey \|\| cfg\.apiKey === 'demo'\) return;/.test(SRC));
}

// ── the pages ──
{
    const alerts = fs.readFileSync(path.join(PAGES, "alerts.html"), "utf8");
    check("alerts.html loads the shared watcher", alerts.includes('<script src="dashboards-alerts.js"></script>'));
    check("alerts.html starts it with alwaysPoll", /DashAlerts\.watch\(\{[^}]*alwaysPoll:\s*true/.test(alerts));
    for (const page of ["index.html", "room.html", "energy.html"]) {
        const src = fs.readFileSync(path.join(PAGES, page), "utf8");
        const iDash = src.indexOf('src="dashboard.js"'), iAl = src.indexOf('src="dashboards-alerts.js"');
        check(`${page} loads dashboards-alerts.js after dashboard.js`, iDash >= 0 && iAl > iDash);
        check(`${page} loads dashboards-ui.js, whose message() the watcher asks with`, src.includes('src="dashboards-ui.js"'));
    }
    const guest = fs.readFileSync(path.join(PAGES, "guest.html"), "utf8");
    check("the guest page does not", !guest.includes("dashboards-alerts.js"));
}

done();
