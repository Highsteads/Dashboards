// Filename:    test_page_shared_helpers.mjs
// Description: The shared page helpers added for the 24-09-2026 page batch,
//              run for real in a vm against the shipped files:
//                - DashUI.authStrikes: three consecutive refusals, reset by a
//                  good poll, and a reflector refusal never counted;
//                - IndigoAPI._fetch carries the refusal's reason to the handler;
//                - observeAll: a cached list is NOT a successful poll;
//                - DashUI.cameraStills: one ask, null on failure, never the
//                  old public name, and a failure is asked again;
//                - DashUI.cameraHealthTracker: a summary that has stopped
//                  being written, or says go2rtc is down, is not "health OK";
//                - DashUI.wx: the weather-station units the hub got wrong;
//                - DashUI.unifiStale: one stale rule for both WiFi pages;
//                - DashAction.selfPoll finds dashboard.js's top-level class;
//                - standalone-nav.js runs after the tap guard, not before it.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_page_shared_helpers.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");

function loadUi(extra = {}) {
    const win = Object.assign({ setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise,
                                AbortController, INDIGO_CONFIG: { apiKey: "k" } }, extra);
    win.window = win;
    vm.createContext(win);
    vm.runInContext(read("dashboards-ui.js"), win);
    return win;
}

console.log("\nauthStrikes — three in a row, and a reflector refusal is not a bad key");
{
    const trips = [], refused = [];
    const win = loadUi();
    const a = win.DashUI.authStrikes({ onTrip: () => trips.push(1), onRefused: e => refused.push(e) });
    const bad = { status: 401 };
    checkEq("first refusal is only counted", a.fail(bad), "counted");
    checkEq("second too", a.fail(bad), "counted");
    a.ok();
    checkEq("a good poll starts the count again", a.count(), 0);
    a.fail(bad); a.fail(bad);
    check("two after a success do not trip", trips.length === 0);
    checkEq("the third in a row trips", a.fail(bad), "tripped");
    check("and trips once", trips.length === 1);
    const refl = { status: 403, body: { ok: false, reason: "reflector_blocked", lanURL: "http://192.0.2.9:8176/x" } };
    for (let i = 0; i < 5; i++) a.fail(refl);
    check("five reflector refusals never trip", trips.length === 1 && a.count() === 0);
    check("each is shown as a refusal", refused.length === 5);
    check("the reason on the error itself counts too", win.DashUI.isReflectorRefusal({ reason: "reflector_blocked" }));
    check("a plain 403 is not a reflector refusal", !win.DashUI.isReflectorRefusal({ status: 403, body: { error: "x" } }));
    // The default trip forgets the key and goes to the hub.
    let cleared = 0;
    const win2 = loadUi({ IndigoAPI: { clearConfig: () => { cleared++; } }, location: { href: "room.html" } });
    const b = win2.DashUI.authStrikes();
    b.fail(bad); b.fail(bad);
    check("default: nothing forgotten after two", cleared === 0 && win2.location.href === "room.html");
    b.fail(bad);
    check("default: the third forgets the key and goes to the hub", cleared === 1 && win2.location.href === "index.html");
}

console.log("\nIndigoAPI hands the refusal's reason to the auth handler");
{
    const ctx = {
        window: { INDIGO_CONFIG: null }, location: { protocol: "http:", hostname: "192.0.2.1" },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        fetch: async () => ({ status: 403, ok: false, clone() { return this; },
                              json: async () => ({ ok: false, reason: "reflector_blocked" }),
                              headers: { get: () => "application/json" } }),
        AbortController, setTimeout, clearTimeout, console, Date, Promise,
    };
    vm.createContext(ctx);
    vm.runInContext(read("dashboard.js") + "\n;globalThis.__A = IndigoAPI;", ctx);
    const api = new ctx.__A({ apiKey: "k", baseURL: "x" });
    const seen = [];
    api.onAuthFailure(e => seen.push(e));
    try { await api._fetch("/message/com.clives.indigoplugin.dashboards/applyColour/", { method: "POST" }); } catch (_) { /* expected */ }
    check("the handler sees reason reflector_blocked", seen.length === 1 && seen[0].reason === "reflector_blocked",
          JSON.stringify(seen.map(e => e.reason)));
}

console.log("\nobserveAll: a cached list is not a successful poll");
{
    const ctx = {
        window: { INDIGO_CONFIG: null }, location: { protocol: "http:", hostname: "192.0.2.1" },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        document: { hidden: false, addEventListener() {}, removeEventListener() {} },
        setInterval: () => 0, clearInterval() {}, console, Date, Promise, JSON,
    };
    vm.createContext(ctx);
    vm.runInContext(read("dashboard.js") + "\n;globalThis.__A = IndigoAPI;", ctx);
    const api = new ctx.__A({ apiKey: "k", baseURL: "x" });
    let fromCache = true;
    api.getDevices = async () => { const d = [{ id: 1 }]; if (fromCache) d.fromCache = true; return d; };
    const oks = [], errs = [], cbs = [];
    api.observeAll(d => cbs.push(d), 3000, e => errs.push(e), d => oks.push(d));
    await new Promise(r => setImmediate(r));
    check("no onOk for the cached list", oks.length === 0);
    check("onErr says it is the last known states", errs.length === 1 && errs[0].fromCache === true
          && /last known/i.test(errs[0].message), JSON.stringify(errs.map(e => e.message)));
    check("the page still gets the list to draw", cbs.length === 1);
    fromCache = false;
    const api2 = new ctx.__A({ apiKey: "k", baseURL: "x" });
    api2.getDevices = api.getDevices;
    const oks2 = [];
    api2.observeAll(() => {}, 3000, () => {}, d => oks2.push(d));
    await new Promise(r => setImmediate(r));
    check("a real poll still reaches onOk", oks2.length === 1);
}

console.log("\ncameraStills — asked once, null on failure, never a guessed name");
{
    const calls = [];
    let reply = { status: 200, body: { ok: true, imagePattern: "stills-abc/cam-{host}.jpg",
                                       thumbPattern: "stills-abc/cam-{host}-thumb.jpg" } };
    const win = loadUi({ fetch: async (url) => { calls.push(url);
        return { ok: reply.status === 200, status: reply.status, json: async () => reply.body }; } });
    const U = win.DashUI;
    const [a, b] = await Promise.all([U.cameraStills(), U.cameraStills()]);
    check("two callers share one request", calls.length === 1 && a === b, String(calls.length));
    check("it asks the cameraStills action", /\/cameraStills\/$/.test(calls[0]));
    checkEq("and returns both patterns", a, { imagePattern: "stills-abc/cam-{host}.jpg",
                                               thumbPattern: "stills-abc/cam-{host}-thumb.jpg" });
    checkEq("a still's address comes from the pattern", U.stillUrl(a.thumbPattern, "192.0.2.5"),
            "stills-abc/cam-192.0.2.5-thumb.jpg");
    checkEq("no pattern, no address", U.stillUrl(null, "192.0.2.5"), "");
    checkEq("still poll by link: home 2 s, VPN 3 s, reflector 15 s",
            [U.stillPollMs("home"), U.stillPollMs("vpn"), U.stillPollMs("reflector")], [2000, 3000, 15000]);

    const calls2 = [];
    let status = 500;
    const win2 = loadUi({ fetch: async (url) => { calls2.push(url);
        return status === 200
            ? { ok: true, status: 200, json: async () => ({ ok: true, imagePattern: "stills-z/cam-{host}.jpg" }) }
            : { ok: false, status, json: async () => ({ ok: false, error: "no" }) }; } });
    const f = await win2.DashUI.cameraStills();
    check("a failure is null, not the old cam-{host}.jpg", f === null);
    status = 200;
    const g = await win2.DashUI.cameraStills();
    check("and is asked again next time", calls2.length === 2 && g && g.imagePattern === "stills-z/cam-{host}.jpg");
    checkEq("a missing thumbnail pattern falls back to the full one", g.thumbPattern, "stills-z/cam-{host}.jpg");
    const win3 = loadUi({ fetch: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, imagePattern: "cam.jpg" }) }) });
    check("a pattern with no {host} is refused", (await win3.DashUI.cameraStills()) === null);
    // Demo mode reads the canned answer.
    const demo = JSON.parse(read("demo-data/api/cameraStills.json"));
    check("the demo fixture answers with its placeholder", demo.ok === true && demo.imagePattern === "demo-cam.svg");
}

console.log("\ncamera health — a frozen summary is not health OK");
{
    const U = loadUi().DashUI;
    const T = U.cameraHealthTracker(60000);
    const now = 1_800_000_000_000;
    const h = { "192.0.2.1": { state: "ok" } };
    checkEq("fresh and up", T.feed({ _writeTs: now / 1000 - 2, _go2rtcUp: true, _cameraHealth: h }, now).state, "ok");
    checkEq("the same write 30 s later is still fine", T.feed({ _writeTs: now / 1000 - 2, _go2rtcUp: true, _cameraHealth: h }, now + 30000).state, "ok");
    checkEq("the same write 70 s later is stale", T.feed({ _writeTs: now / 1000 - 2, _go2rtcUp: true, _cameraHealth: h }, now + 70000).state, "stale");
    checkEq("a new write is fine again", T.feed({ _writeTs: now / 1000 + 70, _go2rtcUp: true, _cameraHealth: h }, now + 72000).state, "ok");
    checkEq("go2rtc down says so", T.feed({ _writeTs: now / 1000 + 74, _go2rtcUp: false, _cameraHealth: h }, now + 74000).state, "down");
    checkEq("no file is unknown", T.feed(null, now).state, "unknown");
    checkEq("no write time is unknown", T.feed({ _cameraHealth: h }, now).state, "unknown");
    const T2 = U.cameraHealthTracker();
    checkEq("a first read an hour old is stale", T2.feed({ _writeTs: now / 1000 - 3600, _cameraHealth: h }, now).state, "stale");
    const T3 = U.cameraHealthTracker();
    checkEq("a first read a minute off (clock skew) is trusted", T3.feed({ _writeTs: now / 1000 - 60, _cameraHealth: h }, now).state, "ok");
}

console.log("\nweather units — the hub printed km/h as mph");
{
    const W = loadUi().DashUI.wx;
    checkEq("20 km/h is 12 mph", Math.round(W.windMph(20, "km/h")), 12);
    checkEq("kmh too", Math.round(W.windMph(20, "kmh")), 12);
    checkEq("m/s", Math.round(W.windMph(10, "m/s")), 22);
    checkEq("mph unchanged", W.windMph(10, "mph"), 10);
    checkEq("an unknown unit says nothing", W.windMph(10, "furlongs"), null);
    checkEq("degF labelled as such", W.tempUnit({ temperatureUnit: "degF" }), "°F");
    checkEq("50 F is 10 C", W.tempC(50, { temperatureUnit: "F" }), 10);
    checkEq("C stays C", W.tempC(10, { temperatureUnit: "C" }), 10);
    checkEq("pressure unit as published", W.pressUnit({ pressureRelativeUnit: "inHg" }), "inHg");
    checkEq("inHg to hPa for the trend", Math.round(W.pressHpa(30, { pressureRelativeUnit: "inHg" })), 1016);
    checkEq("rain inches to mm", W.rainMm(1, "in"), 25.4);
    checkEq("rain mm unchanged", W.rainMm(3, "mm"), 3);
}

console.log("\nUniFi stale rule — one copy for both pages");
{
    const U = loadUi().DashUI;
    const ctl = st => ({ states: { status: st } });
    check("controller Connected, AP fine: live", !U.unifiStale({ enabled: true, states: {} }, ctl("Connected")));
    check("controller unreachable: stale", U.unifiStale({ enabled: true, states: {} }, ctl("Unreachable")));
    check("AP disabled: stale", U.unifiStale({ enabled: false }, ctl("Connected")));
    check("AP in error: stale", U.unifiStale({ errorState: "timeout" }, ctl("Connected")));
    check("no controller found: judged on the AP alone", !U.unifiStale({ enabled: true }, null));
}

console.log("\nDashAction.selfPoll finds dashboard.js's top-level class");
{
    // The Scenes page never feeds DashAction, so selfPoll is the only thing
    // that can advance a watch there. It looked for window.IndigoAPI, which a
    // top-level `class IndigoAPI` never creates.
    const timers = [];
    let NOW = 1_000_000;
    const polls = [];
    const doc = { head: { appendChild() {} }, body: { appendChild() {} }, createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
                  getElementById: () => null, querySelectorAll: () => [] };
    const box = { console, document: doc, Date: { now: () => NOW }, Promise, JSON, Math,
                  setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearInterval() {},
                  setTimeout: () => 0, clearTimeout() {}, polls };
    box.window = box;
    vm.createContext(box);
    vm.runInContext(`class IndigoAPI {
        getDevices() { polls.push(1); return Promise.resolve([]); }
        executeActionGroup() { return Promise.resolve(); }
    }`, box);
    vm.runInContext(read("dashboards-action.js"), box);
    check("the class is not on window (the trap itself)", typeof box.IndigoAPI === "undefined");
    const spec = { title: "Garage", timeoutSec: 60, rules: [{ when: [{ id: 1, state: "contact", is: true }], phase: "done", text: "Open" }] };
    await box.DashAction.run({ key: "scene:9", actionId: 9, spec });
    for (let i = 0; i < 20; i++) { NOW += 500; timers.forEach(t => t.fn()); await new Promise(r => setImmediate(r)); }
    check("selfPoll asks for the devices while the watch runs", polls.length > 0, `polls=${polls.length}`);
}

console.log("\nstandalone-nav runs after the tap guard, not before it");
{
    const listeners = [];
    let navigated = null;
    const loc = { href: "http://192.0.2.1:8176/public/dashboards/index.html", origin: "http://192.0.2.1:8176",
                  pathname: "/public/dashboards/index.html", search: "" };
    Object.defineProperty(loc, "href", { get: () => "http://192.0.2.1:8176/public/dashboards/index.html",
                                         set: v => { navigated = v; } });
    const box = { console, URL, location: loc, navigator: { standalone: true },
                  document: { addEventListener: (t, fn, cap) => listeners.push({ t, fn, cap }) } };
    box.window = box;
    vm.createContext(box);
    vm.runInContext(read("standalone-nav.js"), box);
    const l = listeners.find(x => x.t === "click");
    check("it listens in the bubble phase", l && !l.cap && !(l.cap && l.cap.capture));
    const a = { href: "http://192.0.2.1:8176/public/dashboards/room.html", target: "", hasAttribute: () => false };
    const ev = (prevented) => ({ defaultPrevented: prevented, target: { closest: () => a },
                                 preventDefault() { this.defaultPrevented = true; } });
    l.fn(ev(true));
    check("a click the tap guard cancelled does not navigate", navigated === null);
    l.fn(ev(false));
    check("a real tap still navigates in-app", navigated === a.href);
}

done();
