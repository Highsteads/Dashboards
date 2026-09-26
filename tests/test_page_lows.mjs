// Filename:    test_page_lows.mjs
// Description: The page half of the 24-09-2026 deep review's LOW findings.
//              Where a fix is a function it is lifted out of the shipped page
//              and run; where it is wiring the source is read with comments
//              stripped, so prose describing a rule can never satisfy it. Each
//              block names the finding it covers ([N] in
//              ~/Archive/Dashboards-review-2026-09-24.md).
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.1 (3.45.0: [70] runs the page's tile against the shared DashRTC module)
//
// Run: node tests/test_page_lows.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const code = f => strip(read(f));
const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function extractFn(s, name) {
    const start = s.search(new RegExp("(async\\s+)?function\\s+" + name + "\\s*\\("));
    if (start < 0) throw new Error("not found: " + name);
    let depth = 0;
    for (let j = s.indexOf("{", start); j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (!depth) return s.slice(start, j + 1); }
    }
    throw new Error("unbalanced: " + name);
}
const tick = (ms = 5) => new Promise(r => setTimeout(r, ms));
// Each finding's block runs on its own: one that cannot even find its function
// (the old code) records a failure and the rest still run.
async function section(fn) {
    try { await fn(); } catch (e) { check("block ran", false, e && e.message); }
}

// ── [59] [60] the hub's Doors & Windows card ────────────────────────────────
console.log("\n[59] [60] hub Doors & Windows: no false all-clear, and rooms.json is retried");
await section(async () => {
    const src = code("index.html");
    const host = { innerHTML: "" };
    let fetches = 0, fetchOk = false;
    const ctx = {
        console, Date, JSON, Math, Set, Object, String,
        document: { getElementById: id => (id === "alerts-strip" ? host : null) },
        DashIcons: { svg: n => `<svg data-n="${n}"></svg>` },
        DashAction: { truthy: v => v === true },
        escapeAttr: esc, relTime: () => "5m ago",
        fetch: async () => { fetches++; if (!fetchOk) throw new Error("offline");
                             return { ok: true, json: async () => ({ rooms: { Hall: { windows: [1, 2] } } }) }; },
    };
    vm.createContext(ctx);
    vm.runInContext("let ROOMS = null;\n" + (src.match(/let _roomsAt = 0, _roomsFails = 0;/) || [""])[0] + "\n"
        + extractFn(src, "loadRooms") + "\n" + extractFn(src, "maybeRetryRooms") + "\n"
        + extractFn(src, "renderAlertsCard")
        + "\nglobalThis.__h = { loadRooms, maybeRetryRooms, renderAlertsCard, rooms: () => ROOMS, setRooms: r => { ROOMS = r; } };", ctx);
    const H = ctx.__h;
    await H.loadRooms();
    H.renderAlertsCard([]);
    check("one failed read still says Loading", /Loading/.test(host.innerHTML));
    await H.loadRooms();
    H.renderAlertsCard([]);
    check("repeated failures say the room list could not be read", /Could not read the room list/.test(host.innerHTML), host.innerHTML);
    const before = fetches;
    H.maybeRetryRooms();
    check("the poll does not retry inside 30 s", fetches === before);
    fetchOk = true;
    const realNow = Date.now;
    ctx.Date = { now: () => realNow() + 31000 };
    H.maybeRetryRooms();
    await tick();
    ctx.Date = Date;
    check("the poll retries after 30 s and the list arrives", fetches === before + 1 && H.rooms() && H.rooms().rooms.Hall);

    H.renderAlertsCard([{ id: 1, name: "Door", enabled: true, onState: null, errorState: "offline" },
                        { id: 2, name: "Window", enabled: false, onState: false }]);
    check("no readable contact: no green tick and no 'All 0 closed'",
          !/data-n="check"/.test(host.innerHTML) && !/All 0 closed/.test(host.innerHTML) && /can report/.test(host.innerHTML), host.innerHTML);
    H.setRooms({ rooms: { Hall: { windows: [] } } });
    H.renderAlertsCard([]);
    check("no contacts set up says so, without a tick", /No door or window sensors set up/.test(host.innerHTML) && !/data-n="check"/.test(host.innerHTML));
    H.setRooms({ rooms: { Hall: { windows: [1, 2] } } });
    H.renderAlertsCard([{ id: 1, name: "Door", enabled: true, onState: false }, { id: 2, name: "W", enabled: true, onState: null, errorState: "x" }]);
    check("a real count keeps the green line", /data-n="check"/.test(host.innerHTML) && /All 1 closed · 1 unreadable/.test(host.innerHTML));
});

// ── [61] disabled devices on the hub ───────────────────────────────────────
console.log("\n[61] hub: a disabled device is not read as current");
await section(async () => {
    const src = code("index.html");
    const favHost = { innerHTML: "", style: {} }, pulse = { innerHTML: "" };
    const ctx = {
        console, Date, JSON, Math, Map, Set, Object, String, Number,
        document: { getElementById: id => (id === "favourites" ? favHost : id === "pulse-row" ? pulse : null),
                    querySelectorAll: () => [] },
        window: { INDIGO_CONFIG: { favourites: [] } },
        escapeAttr: esc, DashAction: { repaint() {}, truthy: v => v === true },
        DashIcons: { has: () => false, svg: n => `<svg data-n="${n}"></svg>` },
        fireHeaterChip: () => null, savingSessionChip: () => null, _sigen: () => null,
        renderAttention() {}, ROOMS: null,
    };
    vm.createContext(ctx);
    vm.runInContext((src.match(/const asBool = [^\n]+\n/) || [""])[0] + "let DEVCOUNTS = null;\n"
        + extractFn(src, "spokenWhen") + "\n" + extractFn(src, "renderFavouritesCard") + "\n" + extractFn(src, "renderHousePulse")
        + "\nglobalThis.__h = { renderFavouritesCard, renderHousePulse };", ctx);
    ctx.window.INDIGO_CONFIG.favourites = [{ type: "device", id: 5, state: "voltage", label: "Mains", warnBelow: 230 }];
    ctx.__h.renderFavouritesCard([{ id: 5, name: "Meter", enabled: false, states: { voltage: 241.3 } }]);
    check("a disabled reading favourite says Disabled, not its old value",
          /Disabled/.test(favHost.innerHTML) && !/241\.3/.test(favHost.innerHTML), favHost.innerHTML);
    ctx.__h.renderFavouritesCard([{ id: 5, name: "Meter", enabled: true, states: { voltage: 241.3 } }]);
    check("an enabled one still shows its value", /241\.3/.test(favHost.innerHTML));
    ctx.__h.renderHousePulse([
        { id: 1, name: "Presence - Alex", deviceTypeId: "unifiClient", enabled: false, states: { presence: "home" } },
        { id: 2, name: "Presence - Sam", deviceTypeId: "unifiClient", enabled: true, states: { presence: "away" } },
        { id: 3, name: "Zone", enabled: false, states: { hvacHeaterIsOn: true } },
        { id: 4, name: "Zone 2", enabled: true, states: { hvacHeaterIsOn: "true" } },
    ]);
    check("a disabled presence device is not a chip", !/Alex/.test(pulse.innerHTML) && /Sam · Away/.test(pulse.innerHTML), pulse.innerHTML);
    check("a disabled zone does not count as heating", /pc-num">1<\/span> zone heating/.test(pulse.innerHTML), pulse.innerHTML);
});

// ── [64] pressure tendency over three hours ────────────────────────────────
console.log("\n[64] hub pressure trend compares with the sample nearest 3 h old");
await section(async () => {
    const src = code("index.html");
    let NOW = 1_800_000_000_000;
    const store = {};
    const ctx = { Date: { now: () => NOW }, JSON, Math, Array, isFinite,
                  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } };
    vm.createContext(ctx);
    vm.runInContext(extractFn(src, "_trackPressure") + "\nglobalThis.__t = _trackPressure;", ctx);
    const H = 3600 * 1000;
    // Six hours ago it was 1000 hPa, three hours ago 1010.5, now 1010.8: the
    // 3 h tendency is steady; comparing with the 6 h sample says "rising".
    store["dashboards-pressure-history"] = JSON.stringify([
        { t: NOW - 5.9 * H, p: 1000 }, { t: NOW - 3 * H, p: 1010.5 }, { t: NOW - 2 * H, p: 1010.6 }]);
    const r = ctx.__t(1010.8);
    check("the 3 h sample decides the arrow, not a 6 h one", r && r.word === "steady", JSON.stringify(r));
    store["dashboards-pressure-history"] = JSON.stringify([{ t: NOW - 2.2 * H, p: 1000 }]);
    check("no sample in the 2.5-3.5 h window: no arrow yet", ctx.__t(1003) === null);
});

// ── [62] room All On / All Off report failures ─────────────────────────────
console.log("\n[62] room All On / All Off: a failed device is counted and said");
await section(async () => {
    const src = code("room.html");
    const notes = [];
    const btn = { classList: { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); } } };
    let seenBusy = false;
    const ctx = {
        console, Promise, Set, Array, window: {},
        document: { querySelector: sel => (/room:tv/.test(sel) ? btn : null) },
        DashAction: { note: (k, ph, t) => notes.push([k, ph, t]) },
        indigo: { turnOn: async id => { seenBusy = btn.classList.set.has("busy"); if (id === 2) throw new Error("timeout"); } },
        TV_IDS: new Set([1, 2, 3]),
    };
    vm.createContext(ctx);
    vm.runInContext("const SECTION_BUSY = new Set();\n" + extractFn(src, "sendToAll") + "\n" + extractFn(src, "toggleTv")
        + "\nglobalThis.__r = { toggleTv, SECTION_BUSY };", ctx);
    await ctx.__r.toggleTv();
    checkEq("one of three failing is noted on the section button", notes, [["room:tv", "error", "1 of 3 failed"]]);
    check("the button is busy while the commands are in flight, and not after", seenBusy && !btn.classList.set.has("busy"));
    ctx.indigo.turnOn = async () => { throw new Error("down"); };
    notes.length = 0;
    await ctx.__r.toggleTv();
    checkEq("all failing says no response", notes, [["room:tv", "error", "Failed — no response"]]);
    check("no inner .catch swallows a rejection any more", !/indigo\[fn\]\(id\)\.catch\(/.test(src));
    check("both section buttons carry an action key", /data-dsh-act-key="room:lights"/.test(src) && /data-dsh-act-key="room:tv"/.test(src));
});

// ── [66] room controls have names, and focus survives a re-render ───────────
console.log("\n[66] room: controls named by device, focus kept across the rebuild");
await section(async () => {
    const src = read("room.html");
    const box = {
        console, Math, JSON, String, Number, parseFloat, parseInt, isFinite, isNaN, Object,
        setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
        document: { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} }, querySelectorAll: () => [] },
        DashUI: { esc, ago: () => "5m" }, DashIcons: { svg: () => "" },
        escapeHtml: esc, prettyLightName: s => s, prettyMotionName: s => s,
        fireSubtitle: () => null, lightSupportsColour: () => false, colorSwatchCss: () => "",
        COLOUR_PRESETS: {}, I: () => "", formatWhen: () => "5m ago", _motionWording: () => ({ on: "Motion", off: "Clear" }),
    };
    box.window = box;
    vm.createContext(box);
    vm.runInContext(read("dashboards-action.js"), box);
    vm.runInContext(read("dashboards-controls.js"), box);
    vm.runInContext(["renderLight", "renderMotion", "focusSelector"].map(n => extractFn(src, n)).join("\n")
        + "\nglobalThis.__R = { renderLight, renderMotion, focusSelector };", box);
    const R = box.__R;
    const h = R.renderLight({ id: 3, name: "Hall <Lamp>", class: "Dimmer", enabled: true, onState: true, brightness: 40, states: {} });
    check("the switch is named after the device", /type="checkbox"[^>]*aria-label="Hall &lt;Lamp&gt;"/.test(h), h);
    check("the brightness slider says whose brightness", /type="range"[^>]*\s+aria-label="Hall &lt;Lamp&gt; brightness"/.test(h));
    check("the details button names its device", /aria-label="Details for Hall &lt;Lamp&gt;"/.test(h));
    const m = R.renderMotion({ id: 4, name: "Landing", onState: false, enabled: true, states: {} });
    check("so do the sensor tiles' details buttons", /aria-label="Details for Landing"/.test(m) && !/aria-label="Details"/.test(src));
    const fake = (tag, attrs, cls, type) => ({ tagName: tag, type, classList: cls ? [cls] : [], getAttribute: a => (a in attrs ? attrs[a] : null) });
    checkEq("a checkbox is found again by its device id", R.focusSelector(fake("INPUT", { "data-id": "3" }, null, "checkbox")), 'input[type="checkbox"][data-id="3"]');
    checkEq("and a slider apart from it", R.focusSelector(fake("INPUT", { "data-id": "3" }, "brightness", "range")), 'input.brightness[type="range"][data-id="3"]');
    checkEq("a details button by its device", R.focusSelector(fake("BUTTON", { "data-details-id": "4" }, "info-btn")), 'button.info-btn[data-details-id="4"]');
    const body = strip(extractFn(src, "render"));
    check("render saves the focused control before replacing the content and refocuses it after",
          /focusSelector\(was\)[\s\S]*content\.innerHTML = html;[\s\S]*querySelector\(fsel\)[\s\S]*\.focus\(/.test(body));

    // [86] the shared radiator tile
    const z = box.DashTile.zone.render({ id: 9, name: "Kitchen", states: { setpointHeat: 19, temperatureInput1: 18.5 } }, { info: true });
    check("[86] setpoint buttons name their zone", /aria-label="Lower Kitchen setpoint"/.test(z) && /aria-label="Raise Kitchen setpoint"/.test(z), z);
    check("[86] the setpoint is announced when it changes", /class="setpoint-val"[^>]*aria-live="polite"/.test(z));
    check("[86] the zone's details button names it", /aria-label="Details for Kitchen"/.test(z));
});

// ── [63] tomorrow's price, and [87] the dead summary writes ────────────────
console.log("\n[63] [87] Energy and Cost: tomorrow's price clears when unpublished");
await section(async () => {
    const ctx = { console, Math, Number, parseFloat, isNaN, String, Object, Array, Date, JSON };
    ctx.window = ctx; ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(read("energy-calc.js"), ctx);
    const T = ctx.DashCalc.tomorrowPrice;
    checkEq("a published higher price has its arrow", { ...T(24.1, 25.3) }, { text: "25.30p", delta: "▲ +1.2p", cls: "tmrw-up" });
    checkEq("after midnight, unpublished: no arrow and no 'TBDp'", { ...T(25.3, null) }, { text: "not published yet", delta: "", cls: "" });
    checkEq("the same price: no arrow", { ...T(25, 25.01) }, { text: "25.01p", delta: "", cls: "" });
    for (const f of ["energy.html", "cost.html"]) {
        const c = code(f);
        check(`${f} draws the row from DashCalc.tomorrowPrice and always writes the arrow`,
              /DashCalc\.tomorrowPrice\(/.test(c) && /if \(delta\) \{ delta\.textContent = tp\.delta; delta\.className = tp\.cls; \}/.test(c));
        check(`${f} carries no static 'p' after the price`, !/id="tar-tmrw">&#8212;<\/(span|b)>p/.test(c));
    }
    check("[87] energy.html writes no summary that no longer exists", !/sum-chg|sum-dis/.test(code("energy.html")));
});

// ── [65] Cost calendar year tabs ───────────────────────────────────────────
console.log("\n[65] Cost: a late reply for another year is not drawn");
await section(async () => {
    const src = code("cost.html");
    const drawn = [], waits = {};
    const ctx = {
        console, Promise,
        setActiveCalTab() {}, renderCalendarMonths: c => drawn.push(c.year),
        sigenFetch: (_, b) => new Promise(res => { waits[b.year] = res; }),
    };
    vm.createContext(ctx);
    vm.runInContext("let _calCurrentYear = null;\n" + extractFn(src, "switchCalYear") + "\nglobalThis.__s = switchCalYear;", ctx);
    const a = ctx.__s("2024"), b = ctx.__s("2025");
    waits["2025"]({ ok: true, json: async () => ({ year: 2025 }) });
    await b;
    waits["2024"]({ ok: true, json: async () => ({ year: 2024 }) });
    await a;
    checkEq("only the year now selected is drawn", drawn, [2025]);
});

// ── [70] a torn-down WebRTC tile sends no offer ────────────────────────────
console.log("\n[70] Cameras: stopping a tile during the ICE wait sends no offer");
await section(async () => {
    const src = code("cameras.html");
    const fetches = [];
    const pcs = [];
    class FakePC {
        constructor() { this.listeners = {}; this.signalingState = "stable"; this.iceGatheringState = "gathering";
                        this.connectionState = "new"; this.localDescription = null; pcs.push(this); }
        addTransceiver() {} addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
        async createOffer() { return { type: "offer", sdp: "v=0" }; }
        async setLocalDescription(o) { this.localDescription = o; }
        async setRemoteDescription() {}
        close() { this.signalingState = "closed"; }
        finishIce() { this.iceGatheringState = "complete"; (this.listeners.icegatheringstatechange || []).forEach(f => f()); }
    }
    const mkTile = () => ({ frameEl: { classList: { add() {}, remove() {} }, appendChild() {} }, imgEl: { style: {} },
                            dotEl: { classList: { add() {}, remove() {} } }, bwEl: { style: {} } });
    const fakeFetch = (url, opts) => { fetches.push(opts); return new Promise(() => {}); };
    // The peer connection moved into dashboards-webrtc.js (DashRTC, v3.45.0),
    // so the page's own startWebrtc/stopWebrtc run here against the REAL
    // shared module rather than a copy of it.
    const win = { RTCPeerConnection: FakePC, MediaStream: class {}, fetch: fakeFetch,
                  location: { protocol: "http:", hostname: "x" },
                  document: { createElement: () => ({ setAttribute() {}, addEventListener() {}, remove() {}, style: {} }) } };
    const ctx = {
        console, Promise, Date, Error, AbortController,
        setTimeout: (f, ms) => (ms >= 1000 ? 0 : setTimeout(f, ms)), clearTimeout() {},
        window: win, RTCPeerConnection: FakePC, MediaStream: class {},
        document: win.document,
        camState: { h: mkTile() }, cfg: {},
        clearTileTimers() {}, releaseFrameUrl() {}, setMode() {}, markRefreshed() {}, webrtcFallback() {},
        WEBRTC_ICE_MS: 8000, WEBRTC_FRAME_MS: 12000,
        startStill() {},
        fetch: fakeFetch,
    };
    vm.createContext(ctx);
    vm.runInContext(read("dashboards-webrtc.js"), ctx);
    ctx.DashRTC = win.DashRTC;
    vm.runInContext(extractFn(src, "webrtcUrl") + "\n" + extractFn(src, "stopWebrtc") + "\n" + extractFn(src, "startWebrtc")
        + "\nglobalThis.__w = { startWebrtc, stopWebrtc };", ctx);
    ctx.__w.startWebrtc("h");
    await tick();
    const first = ctx.camState.h.rtc;
    ctx.__w.stopWebrtc(ctx.camState.h);           // torn down while ICE gathers
    pcs[0].finishIce();
    await tick();
    check("no signalling POST goes out for a stopped tile", fetches.length === 0, `${fetches.length} sent`);
    check("and the stopped stream is closed", first.stopped && pcs[0].signalingState === "closed");
    ctx.__w.startWebrtc("h");                    // a fresh start works as before
    await tick();
    pcs[1].finishIce();
    await tick();
    check("a live tile still sends its offer, with its own abort signal",
          fetches.length === 1 && ctx.camState.h.rtc.ctrl && fetches[0].signal === ctx.camState.h.rtc.ctrl.signal);
});

// ── [71] [72] X1 the Cameras page's wiring ─────────────────────────────────
console.log("\n[71] [72] X1 Cameras: health polling, first focus, demo stills");
await section(async () => {
    const src = code("cameras.html");
    const bw = extractFn(src, "startBandwidthPoll");
    check("[71] camera health is not fetched while idle-paused or hidden",
          /if \(!_idlePaused && !document\.hidden && \(Date\.now\(\) - _healthLastFetch\) > 30000\)/.test(bw));
    check("[71] waking from the idle pause reads health again straight away",
          /_idlePaused = false; _healthLastFetch = 0;/.test(extractFn(src, "_armIdleGuard")));
    const vis = src.slice(src.indexOf('document.addEventListener("visibilitychange"'));
    check("[71] so does the tab showing again", /if \(document\.hidden\) \{ stopAll\(\); return; \}\s*_healthLastFetch = 0;/.test(vis));
    const boot = src.slice(src.indexOf("buildGrid();\n        loadStills();"));
    check("[72] the first tile is focused before the first layout",
          boot.indexOf("focusedHost = hosts[0];") > 0 && boot.indexOf("focusedHost = hosts[0];") < boot.indexOf("relayoutAll();"));

    // X1: the page resolves a still beside itself, so the online demo's
    // "demo-cam.svg" and the live "stills-<token>/..." both work.
    const ctx = { console, window: {}, location: { hostname: "highsteads.github.io" }, document: null,
                  sessionStorage: { getItem: () => null, setItem() {} }, Date, Math, JSON, setInterval, clearInterval, setTimeout, clearTimeout };
    ctx.window = ctx; ctx.self = ctx;
    vm.createContext(ctx);
    vm.runInContext(read("dashboards-ui.js"), ctx);
    vm.runInContext("let imgPattern = null, thumbPattern = null;\n" + extractFn(src, "snapshotUrl")
        + "\nglobalThis.__u = (i, t, h, f) => { imgPattern = i; thumbPattern = t; return snapshotUrl(h, f); };", ctx);
    checkEq("X1 the demo's picture stays beside the page", ctx.__u("demo-cam.svg", "demo-cam.svg", "10.0.0.1", false), "demo-cam.svg");
    checkEq("X1 the live still resolves beside the page too", ctx.__u("stills-ab12/cam-{host}.jpg", "stills-ab12/cam-{host}-thumb.jpg", "10.0.0.1", false),
            "stills-ab12/cam-10.0.0.1-thumb.jpg");
    checkEq("X1 and no pattern is no picture", ctx.__u(null, null, "10.0.0.1", true), "");
});

// ── [69] Timeline: a late day does not draw under another day's label ──────
console.log("\n[69] Timeline: only the day selected now is drawn");
await section(async () => {
    const src = code("timeline.html");
    const waits = {}, drawn = [];
    const body = { innerHTML: "" };
    const ctx = {
        console, Promise, Date, String, Object,
        document: { getElementById: () => body },
        window: { INDIGO_CONFIG: {} },      // 3.48.6: load() passes each day through dayForThisHouse
        setStatus() {}, esc, currentView: "day",
        fetchDay: d => new Promise((res, rej) => { waits[d] = { res, rej }; }),
    };
    vm.createContext(ctx);
    vm.runInContext("function pad(n){ return String(n).padStart(2, '0'); }\n" + extractFn(src, "ymd")
        + "\nlet selDate = new Date(2026, 8, 20); let DAY = null; let playMin = null; let dayLoaded = false;"
        + "\nfunction render(){ drawnDays.push(DAY.date + ' under ' + ymd(selDate)); }\n"
        + (src.match(/let _loadSeq = 0;/) || [""])[0] + "\n" + extractFn(src, "dayForThisHouse") + "\n" + extractFn(src, "load")
        + "\nglobalThis.__t = { load, back(){ selDate.setDate(selDate.getDate() - 1); return load(); } };", Object.assign(ctx, { drawnDays: drawn }));
    const a = ctx.__t.load();                 // the 20th, cold
    const b = ctx.__t.back();                 // then the 19th, cached
    waits["2026-09-19"].res({ date: "2026-09-19" });
    await b;
    waits["2026-09-20"].res({ date: "2026-09-20" });
    await a;
    checkEq("the late 20th is dropped; the 19th stays under its own label", drawn, ["2026-09-19 under 2026-09-19"]);
    const c = ctx.__t.back();                 // the 18th fails, but a newer ask has already gone
    const d = ctx.__t.back();
    waits["2026-09-17"].res({ date: "2026-09-17" });
    await d;
    waits["2026-09-18"].rej(new Error("timeout"));
    await c;
    check("a stale error does not replace the newer day", !/Couldn't load/.test(body.innerHTML));
});

// ── [73] Heating: the headline figures leave out stale and disabled zones ──
console.log("\n[73] Heating: house average, coldest and warmest come from live zones only");
await section(async () => {
    const src = read("heating.html");
    const ctx = { console, Date, Math, String, parseFloat, isFinite, isNaN, JSON, Object, window: {} };
    ctx.window = ctx;
    ctx.document = { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} } };
    vm.createContext(ctx);
    vm.runInContext(read("dashboards-action.js"), ctx);
    vm.runInContext(read("dashboards-controls.js"), ctx);
    vm.runInContext(`const getCurrentTemp = DashTile.zone.currentTemp; const getLastSeen = DashTile.zone.lastSeen;
        const TRV_STALE_MS = DashTile.zone.TRV_STALE_MS;
        function cleanZoneName(s) { return String(s || ""); }
        function escapeHtml(s) { return String(s); } function I() { return ""; }\n`
        + extractFn(strip(src), "houseSummaryCard") + "\nglobalThis.__h = houseSummaryCard;", ctx);
    const pad = n => String(n).padStart(2, "0");
    const seen = ms => { const d = new Date(Date.now() - ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
    const z = (name, t, extra = {}) => ({ id: name.length, name, enabled: true, states: { temperatureInput1: t, setpointHeat: 19, lastSeen: seen(60000) }, ...extra });
    const zones = [z("Hall", 19), z("Kitchen", 21),
                   { ...z("Loft", 8), states: { temperatureInput1: 8, setpointHeat: 19, lastSeen: seen(5 * 3600000) } },
                   z("Garage", 30, { enabled: false })];
    const out = { name: "Garden", enabled: false, states: { temperature: 12.3, humidity: 80, dewPoint: 9 } };
    const h = ctx.__h(zones, [...zones, out]);
    check("the average leaves out the stale and disabled zones", /20\.0°<\/div><div class="h-mlab">House avg<span class="h-msub">2 zones not counted/.test(h), h);
    check("coldest and warmest are live zones", /Hall/.test(h) && /Kitchen/.test(h) && !/8\.0°/.test(h) && !/30\.0°/.test(h));
    check("a disabled outdoor sensor is not shown as the outside temperature", !/Outside/.test(h));
    check("the stale TRV is still named in its warning", /Loft/.test(h));
});

// ── [74] [75] Settings: the camera hint and the swap-out list ──────────────
console.log("\n[74] [75] Settings: host hint, and the swap-out list follows the rows");
await section(async () => {
    const src = read("settings.html");
    check("[74] the hint no longer invites a port the server refuses",
          !/IP\[:port\]/.test(src) && /IP address or plain hostname \(no port\)/.test(src));
    const ctx = { console, esc };
    vm.createContext(ctx);
    vm.runInContext(extractFn(src, "swapOptionsHtml") + "\n" + extractFn(src, "collectCameras")
        + "\nglobalThis.__s = { swapOptionsHtml, collectCameras };", ctx);
    const h = ctx.__s.swapOptionsHtml([{ host: "10.0.0.7", name: "Drive" }], "10.0.0.5");
    check("[75] a swap host that is gone is not kept selected", !/selected/.test(h) && /Drive \(10\.0\.0\.7\)/.test(h), h);
    check("[75] one still present stays selected", /value="10\.0\.0\.7" selected/.test(ctx.__s.swapOptionsHtml([{ host: "10.0.0.7", name: "Drive" }], "10.0.0.7")));
    const row = (host, name, main = false) => ({ querySelector: q => ({ ".c-host": { value: host }, ".c-name": { value: name },
        ".c-vendor": { value: "dahua" }, ".c-stream": { value: "" }, ".c-rooms": { value: "" }, ".c-main": { checked: main } })[q] });
    const root = { querySelectorAll: () => [row("10.0.0.7", "Drive")], querySelector: () => ({ value: "10.0.0.5" }) };
    checkEq("[75] collecting drops a swap host no camera has", ctx.__s.collectCameras(root).swap, "");
    const body = strip(src);
    check("[75] editing a host or name, adding and deleting all rebuild the list",
          /\.c-del"\)\.addEventListener\("click", \(\) => \{ tr\.remove\(\); rebuildSwap\(\); \}\)/.test(body)
          && /camRow\(\{ vendor: "dahua" \}\)\);\s*rebuildSwap\(\);/.test(body)
          && /matches\("\.c-host, \.c-name"\)\) rebuildSwap\(\)/.test(body));
});

// ── [76] System Health: crashed and disabled apart, folds kept open ────────
console.log("\n[76] System Health: the census says stopped and disabled apart, and folds stay open");
await section(async () => {
    const src = code("system-health.html");
    const ctx = { WeakMap, Array };
    vm.createContext(ctx);
    vm.runInContext("const _painted = new WeakMap();\n" + extractFn(src, "paint") + "\nglobalThis.__p = paint;", ctx);
    let writes = 0;
    const folds = { a: { id: "sh-census", open: true } };
    const host = {
        _h: "", set innerHTML(v) { this._h = v; writes++; folds.a = { id: "sh-census", open: false }; }, get innerHTML() { return this._h; },
        querySelectorAll: () => Object.values(folds).filter(d => d.open),
        querySelector: sel => (sel === "#sh-census" ? folds.a : null),
    };
    ctx.__p(host, "<details id=\"sh-census\">x</details>");
    folds.a.open = true;                                   // the reader opens the fold
    ctx.__p(host, "<details id=\"sh-census\">x</details>");
    check("an unchanged section is not rewritten", writes === 1);
    ctx.__p(host, "<details id=\"sh-census\">y</details>");
    check("a changed one is, and the open fold stays open", writes === 2 && folds.a.open === true);
    const r = extractFn(src, "render");
    check("the census counts stopped and disabled apart",
          /\$\{crashed\} stopped/.test(r) && /\$\{disabled\} disabled/.test(r) && !/crashed \+ disabled/.test(r));
    check("every writer goes through paint", !/\.innerHTML\s*=/.test(src.replace(extractFn(src, "paint"), "")),
          (src.replace(extractFn(src, "paint"), "").match(/.{40}\.innerHTML\s*=.{20}/g) || []).join(" | "));
    check("every fold has an id to be found again by", !/<details(?![^>]*\bid=)/.test(src));
});

// ── [77] Weather: Solar now only from a live inverter ─────────────────────
console.log("\n[77] Weather: 'Solar now' and 'Roof vs sky' only from a live inverter reading");
await section(async () => {
    const src = code("ecowitt.html");
    const ctx = { Date, String, parseFloat, isFinite, isNaN, Math, escapeHtml: esc, ARRAY_KWP: 14,
                  num: (s, k) => (s[k] == null ? null : Number(s[k])), uvLabel: u => String(u),
                  weatherCard: (id, t, head, rows) => rows.map(r => r.join(": ")).join(" | ") };
    vm.createContext(ctx);
    vm.runInContext("const SIGEN_STALE_MS = 10 * 60 * 1000;\n" + extractFn(src, "sigenPv") + "\n" + extractFn(src, "renderSolar")
        + "\nglobalThis.__s = { sigenPv, renderSolar };", ctx);
    const now = Date.parse("2026-09-24T12:00:00");
    const solar = { id: 1, states: { solarRadiation: 700, uvIndex: 4 } };
    const inv = extra => ({ states: { pvPowerWatts: "2000" }, enabled: true, lastSuccessfulComm: "2026-09-24 11:59:50", ...extra });
    const live = ctx.__s.renderSolar(solar, ctx.__s.sigenPv(inv({}), now));
    check("a live inverter gives Solar now and the ratio", /Solar now: 2\.00 kW/.test(live) && /Roof vs sky/.test(live), live);
    const off = ctx.__s.renderSolar(solar, ctx.__s.sigenPv(inv({ enabled: false }), now));
    check("a disabled inverter shows no frozen figure and no ratio", !/2\.00 kW/.test(off) && !/Roof vs sky/.test(off) && /disabled/.test(off), off);
    const old = ctx.__s.renderSolar(solar, ctx.__s.sigenPv(inv({ lastSuccessfulComm: "2026-09-24 10:00:00" }), now));
    check("nor does one that has sent nothing for two hours", !/2\.00 kW/.test(old) && !/Roof vs sky/.test(old), old);
    const err = ctx.__s.renderSolar(solar, ctx.__s.sigenPv(inv({ errorState: "comm" }), now));
    check("nor one in error", !/Roof vs sky/.test(err) && /error/.test(err));
});

// ── [78] setup link: blocked storage says so, and the token is burned ─────
console.log("\n[78] setup link: a browser that blocks storage is told why");
await section(async () => {
    const src = read("setup.html");
    const script = src.slice(src.indexOf('const card = document.getElementById("card");'), src.lastIndexOf("</script>", src.indexOf('<script src="a11y.js">')));
    const card = { innerHTML: "", classList: { add() {} } };
    const posts = [];
    const ctx = {
        console, Promise, JSON, String, setTimeout: () => 0,
        document: { getElementById: () => card },
        location: { hash: "#" + "a".repeat(24), origin: "http://192.0.2.1:8176", href: "" },
        localStorage: { setItem() { throw new Error("QuotaExceededError"); } },
        window: {},
        fetch: async (url, opts) => {
            if (/setup-/.test(url)) return { ok: true, json: async () => ({ apiKey: "k" }) };
            posts.push(url); return { ok: true };
        },
    };
    vm.createContext(ctx);
    vm.runInContext(script, ctx);
    await tick(20);
    check("the reader is told storage is blocked, not left on the spinner", /Could not save the pairing/.test(card.innerHTML), card.innerHTML.slice(0, 120));
    check("and the one-time token is still burned", posts.some(u => /burnSetupToken/.test(u)));
    check("run() has a backstop catch", /run\(\)\.catch\(/.test(strip(src)));
});

// ── X2 Mains: a missing reference says why ─────────────────────────────────
console.log("\nX2 Mains: the whole-house reference says why it is missing");
await section(async () => {
    const src = code("mains.html");
    // Installed but not answering, so the plugin IS present (3.48.4 left the
    // absent case out of the page altogether; test_sigen_visibility covers it).
    const ctx = { Number, isNaN, Math, String, esc, I: () => "", window: { INDIGO_CONFIG: { sigenAvailable: true } } };
    vm.createContext(ctx);
    vm.runInContext(["has", "num", "plural", "sigenOn", "refMissingWhy", "renderStrip", "renderStripMetersOnly", "renderUnmetered"].map(n => extractFn(src, n)).join("\n")
        + "\nglobalThis.__m = { renderStrip, renderUnmetered, refMissingWhy };", ctx);
    const d = { reference: { id: 1, name: "Sigen Inverter", houseWatts: null, volts: null, stale: "SigenEnergyManager is not running" },
                meters: [], meteredWatts: 350, unmeteredWatts: null, unmeteredWhy: "no whole-house reading" };
    const strip = ctx.__m.renderStrip(d);
    check("House now shows a dash, not '— W' or 0", /House now<\/div>\s*<div class="gauge-big">&#8212;<\/div>/.test(strip) && !/>0 W</.test(strip), strip);
    check("and says why, naming the device and the reason",
          /No current reading from Sigen Inverter: SigenEnergyManager is not running\./.test(strip));
    const un = ctx.__m.renderUnmetered(d);
    check("the unmeasured card gives the same reason", /SigenEnergyManager is not running/.test(un), un);
    const liveRef = { reference: { name: "Sigen Inverter", houseWatts: 1200, volts: 241, stale: null }, meters: [], meteredWatts: 350, unmeteredWatts: 850 };
    check("a live reference still reads as before", /1200 W/.test(ctx.__m.renderStrip(liveRef)) && /measured by Sigen Inverter/.test(ctx.__m.renderStrip(liveRef)));
    checkEq("no inverter at all is said plainly", ctx.__m.refMissingWhy(null), "No inverter to measure the whole house.");
});

done();
