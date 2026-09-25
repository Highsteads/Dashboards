// Filename:    test_heating_boost_pin.mjs
// Description: The Heating page's boost and force buttons go through the PIN
//              guard (3.46.0). Every radiator's own + and − asked for the
//              control PIN when it was on the PIN list, but the boost panel
//              called the plugin directly, so a tablet that could not change
//              one radiator could heat the whole house for 24 hours. Drives
//              the shipped IndigoAPI.gateAny and the page's own callEvoAction.
// Author:      CliveS & Claude Opus 5.5
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_heating_boost_pin.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const DASH = fs.readFileSync(path.join(PAGES, "dashboard.js"), "utf8");
const HEATING = fs.readFileSync(path.join(PAGES, "heating.html"), "utf8");

function fnSource(code, name) {
    const start = code.indexOf(`async function ${name}(`);
    if (start < 0) throw new Error(`could not find ${name}`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

function world({ pinIds = [], answer = "1234", guest = false } = {}) {
    const session = new Map();
    const asked = [], sent = [], alerts = [];
    const toast = { textContent: "", className: "" };
    const ctx = {
        window: { INDIGO_CONFIG: { pinRequired: pinIds } },
        location: { protocol: "http:", hostname: "192.168.1.10" },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        sessionStorage: { getItem: k => session.get(k) || null, setItem: (k, v) => session.set(k, v) },
        prompt: (q) => { asked.push(q); return answer; },
        alert: (m) => alerts.push(m),
        fetch: async () => { throw new Error("no network"); },
        setTimeout: () => 0, clearTimeout() {},
        document: {
            getElementById: (id) => (id === "evo-toast" ? toast : null),
            querySelectorAll: () => [],
        },
        DashUI: { message: async (name, body) => { sent.push({ name, body }); return { ok: true }; } },
        console, Date, Promise, JSON, Map,
    };
    vm.createContext(ctx);
    vm.runInContext(DASH + "\n;globalThis.IndigoAPI = IndigoAPI;", ctx);
    const api = new ctx.IndigoAPI(guest ? { guestToken: "g", baseURL: "x" } : { apiKey: "k", baseURL: "x" });
    // verifyPin: 1234 is the PIN.
    api._fetch = async (p, opts) => ({ valid: JSON.parse(opts.body).pin === "1234" });
    ctx.indigo = api;
    ctx._shownZoneIds = [11, 12, 13];
    ctx.EVO_LABELS = {};
    ctx._evoToastTimer = null;
    vm.runInContext("var _evoToastTimer = null;\n" + fnSource(HEATING, "callEvoAction")
                    + "\n;globalThis.callEvoAction = callEvoAction;", ctx);
    return { ctx, asked, sent, alerts, toast, session };
}

// ── the shared guard ──
{
    const w = world({ pinIds: [12] });
    await w.ctx.indigo.gateAny([11, 12]);
    check("gateAny asks when ANY id is on the PIN list", w.asked.length === 1);
    await w.ctx.indigo.gateAny([12]);
    check("and only once per session", w.asked.length === 1);
    const q = world({ pinIds: [99] });
    await q.ctx.indigo.gateAny([11, 12]);
    check("no protected id, no question", q.asked.length === 0);
    const one = world({ pinIds: [5] });
    await one.ctx.indigo._gate(5);
    check("_gate(id) is the same guard for one device", one.asked.length === 1);
}

// ── the boost buttons ──
{
    const w = world({ pinIds: [12] });
    await w.ctx.callEvoAction("forceHeatingOn24h", null);
    check("a boost with a protected zone asks for the PIN", w.asked.length === 1);
    check("and then sends it", w.sent.length === 1 && w.sent[0].name === "evoHomeAction");

    const wrong = world({ pinIds: [12], answer: "0000" });
    await wrong.ctx.callEvoAction("startTimedBoost2h", null);
    check("a wrong PIN sends NOTHING", wrong.sent.length === 0);
    check("and says so", /Incorrect PIN/.test(wrong.toast.textContent), wrong.toast.textContent);

    const cancel = world({ pinIds: [13], answer: null });
    await cancel.ctx.callEvoAction("startTimedBoost1h", null);
    check("a cancelled PIN sends nothing", cancel.sent.length === 0);
    check("and says the PIN is needed", /PIN is needed/.test(cancel.toast.textContent), cancel.toast.textContent);

    const open = world({ pinIds: [] });
    await open.ctx.callEvoAction("startTimedBoost1h", null);
    check("with no protected zone the boost goes straight through", open.asked.length === 0 && open.sent.length === 1);

    const guest = world({ pinIds: [], guest: true });
    await guest.ctx.callEvoAction("startTimedBoost1h", null);
    check("a guest device sends nothing", guest.sent.length === 0);
}

// ── the page keeps its list of zones for it ──
check("render() records the zones on screen", /_shownZoneIds = zones\.map\(d => d\.id\)/.test(HEATING));

done();
