// Filename:    test_review_batch9.mjs
// Description: Ninth group from the 25/26-Nov-2026 review (3.73.12):
//                - a device that could not be read again still counted as a
//                  good poll, so "Updated" moved over a reading it did not have;
//                - the hub's "All well" was green before anything had been
//                  asked, and for as long as the page stayed open after a
//                  source stopped answering;
//                - the hub printed a weather station that had stopped as now,
//                  "dry" included;
//                - the hub's energy card drew a missing reading as 0.0 and
//                  called a frozen device's totals today's;
//                - the Wi-Fi pages kept an offline access point's clients and
//                  uptime, and "Internet Online" in green with the controller
//                  not answering.
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch9.mjs   (exit 0 = pass)

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

console.log("device poll: a device that could not be read again");
{
    const timers = [];
    const ctx = {
        window: { INDIGO_CONFIG: null },
        document: { hidden: false, addEventListener() {} },
        location: { protocol: "http:", hostname: "192.168.1.10" },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        sessionStorage: { getItem: () => null, setItem() {} },
        fetch: async () => { throw new Error("no network in test"); },
        setInterval: fn => { timers.push(fn); return timers.length; }, clearInterval() {},
        console,
    };
    vm.createContext(ctx);
    vm.runInContext(read("dashboard.js") + "\n;globalThis.__t = { IndigoAPI, _INDIGO_STORE };", ctx);
    const { IndigoAPI, _INDIGO_STORE: STORE } = ctx.__t;
    const api = new IndigoAPI({ apiKey: "k", baseURL: "x" });
    STORE.devices = new Map([[1, { id: 1, name: "old" }], [2, { id: 2, name: "old" }]]);
    STORE.lastFull = Date.now(); STORE.sinceTs = 10;
    api._fetch = async () => ({ ok: true, now: 20, changed: [1, 2], deleted: [] });
    api.getDevice = async id => { if (id === 1) throw new Error("dropped"); return { id: 2, name: "new" }; };
    const out = await api.getDevices();
    check("the list says one of its devices is not fresh", out.incomplete === true);
    checkEq("and still carries both, the unread one as it was", Array.from(out, d => d.name).sort(), ["new", "old"]);

    let oks = 0, errs = 0, draws = 0;
    api.observeAll(() => { draws++; }, 3000, () => { errs++; }, () => { oks++; });
    await new Promise(r => setTimeout(r, 20));
    checkEq("the page's clock is not moved, and no error is raised", [oks, errs], [0, 0]);
    check("the page is still drawn from what it has", draws === 1);
    api.getDevice = async id => ({ id, name: "new" });
    await timers[0]();
    await new Promise(r => setTimeout(r, 20));
    checkEq("the next poll reads it and the clock moves again", oks, 1);
    const hub = read("index.html");
    check("the hub's own poll keeps its clock still too", /if \(!devices\.fromCache && !devices\.incomplete\) markRefreshed\(\);/.test(hub));
}

const hub = read("index.html");

console.log("\nhub: All well only when the sources have answered");
{
    const c = { console };
    vm.createContext(c);
    vm.runInContext(`const ATT_MAX_AGE_MS = { devices: 30000, log: 660000, insights: 660000, cams: 180000 };
        const ATT_NAMES = { devices: "devices and batteries", log: "the Indigo log", cams: "the cameras", insights: "usual behaviour" };
        ${extractFn(hub, "attentionUnchecked")}
        ${extractFn(hub, "attentionChip")}
        globalThis.U = attentionUnchecked; globalThis.C = attentionChip;`, c);
    const now = 10_000_000;
    const all = ["devices", "log", "insights", "cams"];
    const fresh = { devices: now - 2000, log: now - 60000, insights: now - 60000, cams: now - 30000 };
    checkEq("everything answered lately: nothing unchecked", c.U(fresh, now, all).length, 0);
    checkEq("green", c.C([], []), { cls: "good", icon: "check", text: "All well" });
    const start = c.U({ devices: now - 1000, log: 0, insights: 0, cams: 0 }, now, all);
    checkEq("just opened: three sources have not answered yet", Array.from(start, u => u.key), ["log", "insights", "cams"]);
    checkEq("so the chip is not green", c.C([], start), { cls: "", icon: "", text: "Checking" });
    const stopped = c.U(Object.assign({}, fresh, { log: now - 20 * 60000 }), now, all);
    checkEq("the log watch last answered 20 minutes ago", Array.from(stopped, u => [u.key, u.never]), [["log", false]]);
    checkEq("the chip says so", c.C([], stopped).text, "Not all checked");
    checkEq("just back from a hidden tab, an old answer counts for a few seconds",
            c.U(Object.assign({}, fresh, { log: now - 20 * 60000 }), now, all, true).length, 0);
    checkEq("but one that never answered does not", c.U({ devices: now }, now, ["devices", "log"], true).length, 1);
    checkEq("something that needs a look still wins", c.C([{ level: "bad" }], stopped).cls, "bad");
    checkEq("the device poll stopping is noticed after half a minute",
            Array.from(c.U(Object.assign({}, fresh, { devices: now - 45000 }), now, all), u => u.key), ["devices"]);
    check("a reply that the log could not be read is not a clean log",
          /if \(d\.ok === false\) \{ LOGFEED = null; renderAttention\(\); return; \}/.test(hub));
    check("an install with no SQL Logger is not kept waiting for insights",
          /if \(!\(INSIGHTS && INSIGHTS\.ok === false\)\) expect\.push\("insights"\);/.test(hub));
    check("the chip is looked at on a timer, for when every source stops",
          /setInterval\(\(\) => \{ if \(!document\.hidden\) \{ try \{ renderAttention\(\); \}/.test(hub));
    check("no chip before the devices have been read",
          /if \(!items\.length && !\(_lastUpdate > 0\)\) \{/.test(hub));
}

console.log("\nhub: the energy card's words");
{
    const c = { console, parseFloat, isFinite };
    vm.createContext(c);
    vm.runInContext(extractFn(hub, "energyWords") + "\nglobalThis.W = energyWords;", c);
    const s = { batterySoc: "62.4", pvDailyKwh: "3.25", homeDailyKwh: "11", gridDailyExportKwh: "0", gridDailyImportKwh: "7.126" };
    const live = c.W(s, 35.04, false);
    checkEq("live: today's totals", [live.subs.pv, live.subs.home, live.heading, live.solarKey],
            ["today 3.3 kWh", "today 11.0 kWh", "Today", "Solar today"]);
    checkEq("live: the battery line", live.subs.bat, "62.4% · 21.9 kWh");
    const frozen = c.W(s, 35.04, true);
    checkEq("not live: the totals are the last known, not today's",
            [frozen.subs.pv, frozen.heading, frozen.solarKey, frozen.subs.bat],
            ["last known 3.3 kWh", "Last known totals", "Solar, last known", "last known 62.4% · 21.9 kWh"]);
    const empty = c.W({}, 35.04, false);
    checkEq("a state never filled is not 0.0", [empty.subs.pv, empty.subs.bat, empty.pv, empty.imp],
            ["no reading", "no reading", "—", "—"]);
    checkEq("a real nought is still a nought", c.W({ gridDailyExportKwh: 0 }, 0, false).exp, "0.0 kWh");
    const card = extractFn(hub, "renderEnergyCard");
    check("the card uses them", /subs: W\.subs/.test(card) && /\$\{W\.heading\}/.test(card) && /\$\{W\.solarKey\}/.test(card)
          && !/pvToday\.toFixed/.test(card));
}

console.log("\nweather station: one rule for the hub and the Ecowitt page");
{
    const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController,
                  INDIGO_CONFIG: { serverUtcOffsetMin: 0 } };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    const F = win.DashUI.wx.freshness;
    const now = Date.UTC(2026, 10, 26, 12, 0, 0);
    const dev = (st, extra) => Object.assign({ enabled: true, errorState: "", states: Object.assign({ temperature: 3.1 }, st) }, extra);
    checkEq("reported five minutes ago: live", F(dev({ deviceOnline: true, lastUpdate: "2026-11-26 11:55:00" }), now).stale, false);
    const old = F(dev({ deviceOnline: true, lastUpdate: "2026-11-26 07:00:00" }), now);
    checkEq("reported five hours ago: not live, and says when", [old.stale, old.why, old.words], [true, "old", "last report 5h ago"]);
    const off = F(dev({ deviceOnline: "false", lastUpdate: "2026-11-26 11:00:00" }), now);
    check("offline", off.stale && off.why === "offline" && /^the station is offline, last report /.test(off.words), off.words);
    checkEq("disabled in Indigo", F(dev({ lastUpdate: "2026-11-26 11:59:00" }, { enabled: false }), now).why, "disabled");
    checkEq("in error", F(dev({ lastUpdate: "2026-11-26 11:59:00" }, { errorState: "timeout" }), now).why, "error");
    checkEq("a station with no time of its own is not called stale", F(dev({}), now).stale, false);
    const card = extractFn(hub, "renderWeatherCard");
    check("the hub asks before it prints", /const wxLive = WX\.freshness\(outdoor, Date\.now\(\)\);\s*if \(wxLive\.stale\) \{[\s\S]{0,600}Not live[\s\S]{0,300}Last reading[\s\S]{0,200}return;/.test(card));
    check("the Ecowitt page uses the same rule", /const fr = DashUI\.wx\.freshness\(dev, Date\.now\(\)\);\s*const stale = fr\.stale;/.test(read("ecowitt.html")));
}

console.log("\nWi-Fi: an access point that has dropped, a controller that is not answering");
{
    const src = read("wifi.html");
    const c = { console, String, formatWhen: v => v ? "5m ago" : "", escapeHtml: s => String(s),
                fmtNum: v => (v == null || v === "" ? "—" : String(v)), num: v => (v == null || v === "" ? null : Number(v)),
                latClass: () => "", loadClass: () => "" };
    vm.createContext(c);
    vm.runInContext(extractFn(src, "speedTestWords") + extractFn(src, "controllerStaleNote") + extractFn(src, "staleSub") + extractFn(src, "renderInternet")
        + "\nglobalThis.N = controllerStaleNote; globalThis.I = renderInternet;", c);
    const ctl = (st, extra) => Object.assign({ enabled: true, errorState: "", lastChanged: "x",
        states: Object.assign({ status: "Connected", wanStatus: "ok", speedtestDown: 900 }, st) }, extra);
    checkEq("a connected controller: no note", c.N(ctl({})), "");
    checkEq("a controller that is not answering", c.N(ctl({ status: "Sign-in refused" })), "Not live: the controller is not answering, last read 5m ago");
    check("a disabled one", /disabled in Indigo/.test(c.N(ctl({}, { enabled: false }))));
    check("live: Internet reads Online in green", /m-val good">Online</.test(c.I(ctl({}))));
    const stale = c.I(ctl({ status: "Not connected" }));
    check("not answering: no green Online", !/Online/.test(stale) && !/\bgood\b/.test(stale) && /Not known/.test(stale), stale);
    check("and it says the speeds are from the last test", /last test/.test(stale) && /Not live: the controller is not answering/.test(stale));
    const ap = extractFn(src, "renderAP");
    check("an offline AP's bands are left out", /const off = !stale && !online;\s*if \(off\) bands = "";/.test(ap));
    check("and its clients and uptime", /\$\{off \? `<span class="warn">not answering/.test(ap));
    check("no wireless or wired count is invented", /\$\{wireless \?\? "—"\} wireless · \$\{wired \?\? "—"\} wired/.test(src));
    const one = read("wifi-ap.html");
    check("the AP's own page: dashes for an AP that has dropped", /\$\{off \? '—' : \(s\.numClients \?\? '—'\)\}/.test(one)
          && /\$\{off \? '—' : uptimeUi\(s\.uptimeSeconds\)\}/.test(one));
    check("and no client list", /if \(!off\) html \+= renderClients\(s\);/.test(one));
    check("an uptime never reported is a dash, not 0d 0h 0m", /function uptimeUi\(s\) \{ const n = num\(s\); if \(n === null\) return "—";/.test(one));
}

done();
