// Filename:    test_alerts_page_server.mjs
// Description: alerts.html edits the rules in the PLUGIN (3.47.0), not in
//              this browser. Runs the shipped page script against a small
//              fake DOM and a stand-in for the plugin: the rules, channel
//              states and recent firings come from alertRules; adding,
//              pausing and the alerts-active switch go to saveAlertRules with
//              the rev it was handed; a page that is out of date reloads; a
//              browser still holding pre-3.47.0 rules is OFFERED the move
//              (never done silently), and its localStorage is cleared only
//              after the plugin took them; the Send test button reports each
//              channel. Also that the page keeps its https explanation and
//              no longer keeps any rule in localStorage itself.
// Author:      CliveS & Claude
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_alerts_page_server.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const HTML = fs.readFileSync(path.join(PAGES, "alerts.html"), "utf8");
const ALERTS_JS = fs.readFileSync(path.join(PAGES, "dashboards-alerts.js"), "utf8");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// The page's own script: the block that declares I() and edits the rules.
const blocks = [...HTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const PAGE = blocks.find(b => b.includes("const I = (n) =>") && b.includes("saveAlertRules"));

class El {
    constructor(id) {
        Object.assign(this, { id, textContent: "", hidden: false, disabled: false,
                              checked: false, value: "", className: "", style: {}, dataset: {},
                              children: [], attrs: {} });
        this._html = "";
    }
    // Setting innerHTML replaces the children, as it does in a browser.
    get innerHTML() { return this._html; }
    set innerHTML(v) { this._html = String(v); this.children = []; }
    appendChild(c) { this.children.push(c); return c; }
    querySelectorAll() { return []; }
    setAttribute(k, v) { this.attrs[k] = v; }
}

function storage(init) {
    const m = new Map(Object.entries(init || {}));
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), _m: m };
}

function view(over) {
    return Object.assign({
        ok: true, rev: 2, max: 100, active: true, defaultEmail: "", emailSource: "none",
        channels: { pushover: { ready: false, status: "plugin not running" },
                    email: { ready: true, status: "ready", source: "settings" } },
        defaultChannels: ["email", "browser"], rules: [], firings: [], seq: 5, now: Date.now() / 1000,
    }, over || {});
}

async function page({ server, store, secure = true }) {
    const els = {};
    const calls = [];
    const document = {
        readyState: "loading", activeElement: null,
        getElementById: id => (els[id] || (els[id] = new El(id))),
        createElement: t => new El(t), createTextNode: t => ({ textContent: String(t) }),
        querySelectorAll: () => [], addEventListener() {},
    };
    const shown = [];
    function Notification(title, opts) { shown.push(opts.body); }
    Notification.permission = "granted";
    Notification.requestPermission = async () => "granted";
    const ctx = {
        document, localStorage: store, Notification, isSecureContext: secure,
        location: { href: "alerts.html" }, navigator: {}, INDIGO_CONFIG: { apiKey: "k", siteName: "Home" },
        setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
        Map, JSON, Math, Date, Object, String, Array, Promise, isFinite, parseInt, Error,
        console,
    };
    ctx.window = ctx;
    ctx.IndigoAPI = class { static isConfigured() { return true; }
                            async getDevices() { return [{ id: 5, name: "Hall" }, { id: 6, name: "Shed" }]; }
                            async getVariables() { return [{ id: 9, name: "Mode" }]; } };
    ctx.DashUI = {
        esc: s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
        poll: (fn) => { fn(); return { stop() {}, run: fn }; },
        message: async (name, body, opts) => { calls.push({ name, body }); return server(name, body, opts); },
    };
    vm.createContext(ctx);
    vm.runInContext(ALERTS_JS, ctx, { filename: "dashboards-alerts.js" });
    vm.runInContext(PAGE, ctx, { filename: "alerts.html" });
    await sleep(20);
    const byId = new Proxy(els, { get: (o, k) => document.getElementById(k) });
    return { els: byId, calls, shown, ctx, stop: () => ctx.DashAlerts.watch({}).stop() };
}

function err(message, status, body) {
    const e = new Error(message); e.status = status; e.body = body; return e;
}

check("the page script was found", !!PAGE);

// ── the plugin's view is painted ──
{
    const store = storage();
    const v = view({ rules: [
        { kind: "device", id: 5, cond: "on", name: "Hall", enabled: true, channels: ["email", "browser"],
          target: "ok", now: "on" },
        { kind: "device", id: 77, cond: "off", name: "Gone", enabled: true, channels: ["email"],
          target: "missing", now: "deleted in Indigo" }],
        firings: [{ seq: 5, t: Date.now() / 1000, text: "Hall turned on", channels: ["email", "browser"],
                    delivered: ["email"], failed: [], pending: false }] });
    const p = await page({ store, server: async (name) => (name === "alertRules" ? v : null) });
    check("it asks the plugin for everything", p.calls.some(c => c.name === "alertRules" && !("firingsSince" in c.body)));
    check("Pushover's state is shown", p.els["pushover-state"].textContent === "Pushover: plugin not running");
    check("email's too", p.els["email-state"].textContent === "Email: ready");
    check("a rule row per rule", p.els.rules.children.length === 2);
    check("a deleted target says so", p.els.rules.children[1].innerHTML.includes("deleted in Indigo")
          && p.els.rules.children[1].children.some(c => c.textContent === "target gone"));
    check("each rule has a tick per channel", /data-ch="pushover"[^>]*>[\s\S]*data-ch="email" checked[\s\S]*data-ch="browser" checked/.test(p.els.rules.children[0].innerHTML),
          p.els.rules.children[0].innerHTML);
    check("the recent firings are the plugin's", p.els.log.children.length === 1
          && p.els.log.children[0].children.some(c => c.textContent === "email sent · browser"));
    check("the Add row starts with the plugin's default channels",
          !p.els["add-pushover"].checked && p.els["add-email"].checked && p.els["add-browser"].checked);
    check("nothing to move: the offer is hidden", p.els["migrate-card"].hidden === true);
    check("nothing is written to this browser's storage for the rules", store._m.get("dash_alerts") === undefined);
    p.stop();
}

// ── edits go to the plugin with the rev ──
{
    const store = storage();
    let current = view({ rules: [{ kind: "device", id: 5, cond: "on", name: "Hall", enabled: true,
                                   channels: ["email"], target: "ok", now: "off" }] });
    const saves = [];
    const p = await page({ store, server: async (name, body) => {
        if (name === "alertRules") return current;
        if (name === "saveAlertRules") {
            saves.push(body);
            if (body.rev !== current.rev) throw err("the rules were changed somewhere else", 409, { reason: "stale" });
            current = view(Object.assign({}, current, { rev: current.rev + 1,
                rules: (body.rules || current.rules).map(r => Object.assign({ target: "ok", now: "off" }, r)),
                active: body.active === undefined ? current.active : body.active }));
            return current;
        }
    } });
    await sleep(10);               // the pickers load
    p.els.kind.value = "device"; p.els.entity.value = "6"; p.els.cond.value = "off";
    p.els["add-to"].value = "shed@example.com";
    p.els["add-btn"].onclick();
    await sleep(10);
    const add = saves[0];
    check("Add sends the whole list with the rev it was given", add && add.rev === 2 && add.rules.length === 2);
    check("the new rule carries its channels and address",
          add && JSON.stringify(add.rules[1]) === JSON.stringify({ kind: "device", id: 6, cond: "off", name: "Shed",
                                                                  enabled: true, channels: ["email", "browser"],
                                                                  email: "shed@example.com" }), JSON.stringify(add && add.rules[1]));
    check("the page shows the saved list", p.els.rules.children.length === 2);
    p.els.master.checked = false;
    p.els.master.onchange();
    await sleep(10);
    check("the alerts-active switch is saved in the plugin", saves[1] && saves[1].active === false && saves[1].rev === 3);
    // Another tab saved meanwhile: this page's rev is old.
    current = view(Object.assign({}, current, { rev: 9 }));
    p.els.master.checked = true;
    p.els.master.onchange();
    await sleep(10);
    check("a save from an out-of-date page is refused and the page reloads",
          p.els["rules-msg"].textContent.includes("changed somewhere else") && p.calls.filter(c => c.name === "alertRules" && !("firingsSince" in c.body)).length >= 2);
    p.stop();
}

// ── moving a browser's old rules: offered, then cleared only on success ──
{
    const legacy = JSON.stringify({ active: true, rules: [
        { kind: "device", id: 5, name: "Hall", cond: "on", enabled: true },
        { kind: "variable", id: 9, name: "Mode", cond: "change", enabled: true }] });
    const store = storage({ dash_alerts: legacy });
    let fail = true;
    const posted = [];
    const p = await page({ store, server: async (name, body) => {
        if (name === "alertRules") return view();
        if (name === "saveAlertRules") {
            posted.push(body);
            if (fail) throw err("the plugin already has 1 rule, so nothing was moved", 409, { reason: "not_empty" });
            return view({ rev: 3, rules: body.rules.map(r => Object.assign({ channels: ["email", "browser"], target: "ok", now: "" }, r)) });
        }
    } });
    check("the move is offered, not done", p.els["migrate-card"].hidden === false && posted.length === 0);
    check("the offer counts the rules", p.els["migrate-btn"].textContent === "Move these 2 rules to the plugin",
          p.els["migrate-btn"].textContent);
    await p.els["migrate-btn"].onclick();
    check("the move is sent as a migration with no channels (the plugin picks)",
          posted[0] && posted[0].migrate === true && posted[0].rules.length === 2 && posted[0].rules.every(r => !r.channels));
    check("a refused move leaves this browser's rules alone", store._m.has("dash_alerts"));
    check("and says why", p.els["migrate-msg"].textContent.includes("Nothing was moved"));
    fail = false;
    await p.els["migrate-btn"].onclick();
    check("a successful move clears them from this browser", !store._m.has("dash_alerts"));
    check("and the page now shows the plugin's copy", p.els.rules.children.length === 2);
    p.stop();
}

// ── Send test reports each channel ──
{
    const store = storage();
    const p = await page({ store, secure: false, server: async (name, body) => {
        if (name === "alertRules") return view();
        if (name === "sendTestAlert") {
            return { ok: true, text: "Test from Dashboards", results: {
                pushover: { ok: false, reason: "Pushover plugin not running" },
                email: { ok: true, reason: "sent" }, browser: { ok: true, reason: "raised by the open pages" } } };
        }
    } });
    check("the test ticks start on the ready channels and the browser",
          !p.els["test-pushover"].checked && p.els["test-email"].checked && p.els["test-browser"].checked);
    p.els["test-pushover"].checked = true;
    await p.els["test-btn"].onclick();
    const sent = p.calls.find(c => c.name === "sendTestAlert");
    check("the test names its channels and a nonce", sent && JSON.stringify(sent.body.channels) === '["pushover","email","browser"]'
          && /^[a-z0-9]{8,}$/.test(sent.body.nonce));
    const out = p.els["test-result"].innerHTML;
    check("each channel's result is shown", out.includes("Pushover: failed (Pushover plugin not running)")
          && out.includes("Email: sent"), out);
    check("on plain http the browser line says why it was not shown",
          out.includes("Browser: not shown here (needs an https address)"), out);
    check("the https explanation is still on the page", p.els["perm-why"].hidden === false
          && p.els["perm-state"].textContent === "needs an https address");
    p.stop();
}

// ── the page's source ──
{
    check("the page keeps no rule in localStorage itself",
          !/localStorage/.test(PAGE) && !/DashAlerts\.(save|load)\(/.test(PAGE));
    check("the old browser rules are only cleared after the plugin took them",
          PAGE.indexOf("DashAlerts.clearLegacy()") > PAGE.indexOf('DashUI.message("saveAlertRules",\n                { rules: mig.rules'));
    check("the log-watch card's render() is still the first in the page (test_alerts_settled_rows)",
          HTML.indexOf("function render(") > HTML.indexOf("Server-side log-error watch"));
    check("no copy says the rules live in this browser only", !/live in this browser only/.test(HTML));
}

done();
