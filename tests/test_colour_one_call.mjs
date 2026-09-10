// Filename:    test_colour_one_call.mjs
// Description: Contract test for the browser half of the v2.94.0 colour move —
//              IndigoAPI.applyColour in dashboard.js, and the two room.html
//              callers that used to fire the sequence themselves.
//
//              THE RULES
//              1. ONE request per colour change. It was three, in a fixed
//                 order, and a phone that locked between them left the lamp
//                 half-set. Counting the requests is the whole point.
//              2. The command GATE still runs. applyColour is a second path
//                 that commands a device, so a guest must still be refused and
//                 a PIN-protected device must still ask — a command path that
//                 quietly skips the gate is a hole, and a silent one.
//              3. A failure THROWS. The old code swallowed each step in an
//                 empty catch, which is how a half-set lamp said nothing.
//              4. The page sends the preset KEY, never the preset's values, so
//                 the server's table stays the authority.
// Author:      CliveS & Claude Opus 5
// Date:        30-08-2026
// Version:     1.0
//
// Run: node tests/test_colour_one_call.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const apiSrc = fs.readFileSync(path.join(PAGES, "dashboard.js"), "utf8");
const roomSrc = fs.readFileSync(path.join(PAGES, "room.html"), "utf8");

let fails = 0;
const check = (w, ok) => { console.log((ok ? "  ok   " : "  FAIL ") + w); if (!ok) fails++; };

// A context with just enough browser for IndigoAPI to run, and every fetch
// recorded so the request COUNT can be asserted.
function makeCtx(opts = {}) {
    const calls = [];
    const store = {};
    const ctx = {
        console, AbortController, setTimeout, clearTimeout, JSON, Object, Error, Math, Date, parseInt,
        location: { protocol: "http:", hostname: "indigo" },
        alert: msg => calls.push({ alert: msg }),
        prompt: () => opts.pinTyped,
        sessionStorage: {
            getItem: k => (k in store ? store[k] : null),
            setItem: (k, v) => { store[k] = String(v); },
        },
        fetch: async (url, init) => {
            calls.push({ url, body: init && init.body ? JSON.parse(init.body) : null });
            const reply = opts.reply ? opts.reply(url) : { ok: true, steps: [] };
            return { ok: true, status: 200,
                     headers: { get: () => "application/json" },
                     json: async () => reply };
        },
    };
    ctx.window = ctx;
    vm.createContext(ctx);
    ctx.window.INDIGO_CONFIG = Object.assign(
        { apiKey: "k", baseURL: "http://indigo", colourPresets: {
            warm: { label: "Warm white", icon: "cloudsun", mode: "white", whiteTemperature: 2700, brightness: 100 } } },
        opts.config || {});
    vm.runInContext(apiSrc, ctx);
    return { ctx, calls };
}
const api = ctx => vm.runInContext("new IndigoAPI()", ctx);

console.log("colour — one request, not three");
{
    const { ctx, calls } = makeCtx();
    await api(ctx).applyColour(372666822, { preset: "warm" });
    check("a preset is ONE request", calls.length === 1);
    check("to the plugin's applyColour endpoint",
          String(calls[0].url).endsWith("/message/com.clives.indigoplugin.dashboards/applyColour/"));
    check("carrying the device and the preset KEY, not the preset's values",
          calls[0].body.deviceId === 372666822 && calls[0].body.preset === "warm"
          && calls[0].body.whiteTemperature === undefined);
}
{
    const { ctx, calls } = makeCtx();
    await api(ctx).applyColour(5, { whiteTemperature: 3000 });
    check("explicit levels are one request too, with no brightness invented",
          calls.length === 1 && calls[0].body.whiteTemperature === 3000
          && calls[0].body.brightness === undefined);
}

console.log("\ncolour — failures are not swallowed");
{
    const { ctx } = makeCtx({ reply: () => ({ ok: false, steps: [{ step: "setColorLevels", ok: false }] }) });
    let threw = null;
    try { await api(ctx).applyColour(5, { preset: "warm" }); } catch (e) { threw = e; }
    check("a server-reported failure THROWS rather than reading as success", !!threw);
    check("and names the step that failed", threw && /setColorLevels/.test(threw.message));
}
{
    const { ctx } = makeCtx({ reply: () => ({ ok: false, error: "no device 9" }) });
    let threw = null;
    try { await api(ctx).applyColour(9, { preset: "warm" }); } catch (e) { threw = e; }
    check("and a plain error message is carried through", threw && /no device 9/.test(threw.message));
}

console.log("\ncolour — the command gate still applies");
{
    const { ctx, calls } = makeCtx({ config: { apiKey: "", guestToken: "g" } });
    let threw = null;
    try { await api(ctx).applyColour(5, { preset: "warm" }); } catch (e) { threw = e; }
    check("a guest is refused", !!threw && threw.status === 403);
    check("and no request is sent", calls.filter(c => c.url).length === 0);
}
{
    const { ctx, calls } = makeCtx({ config: { pinRequired: [5] }, pinTyped: null });
    let threw = null;
    try { await api(ctx).applyColour(5, { preset: "warm" }); } catch (e) { threw = e; }
    check("a PIN-protected device asks, and a cancelled prompt sends nothing",
          !!threw && calls.filter(c => c.url).length === 0);
}
{
    const { ctx, calls } = makeCtx({
        config: { pinRequired: [5] }, pinTyped: "1234",
        reply: url => (String(url).endsWith("verifyPin/") ? { valid: true } : { ok: true, steps: [] }) });
    await api(ctx).applyColour(5, { preset: "warm" });
    const urls = calls.filter(c => c.url).map(c => String(c.url));
    check("a correct PIN verifies first, THEN the colour goes",
          urls.length === 2 && urls[0].endsWith("verifyPin/") && urls[1].endsWith("applyColour/"));
}

console.log("\nroom page — the callers no longer sequence anything (source checks)");
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
for (const name of ["applyPreset", "applyColorSelection"]) {
    const fn = extractFn(roomSrc, name);
    check(`${name} makes exactly one call, through applyColour`,
          (fn.match(/indigo\.applyColour\(/g) || []).length === 1);
    check(`${name} no longer fires turnOn / setBrightness / setColorLevels itself`,
          !/indigo\.(turnOn|setBrightness|setColorLevels)\(/.test(fn));
    check(`${name} reports a failure instead of an empty catch`,
          /DashAction\.note\(/.test(fn) && !/catch\s*\{\s*\}/.test(fn));
}
check("the room page prefers the server's preset table",
      /colourPresets/.test(roomSrc));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
