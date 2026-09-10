// Filename:    test_door_tile.mjs
// Description: Contract test for the hub's state-driven door favourite —
//              DashAction.doorTile() (the pure state-to-tile map) plus the two
//              spec extensions that carry the design: theme:"door" (blue
//              in-flight veil class) and holdDone:0 (a confirmed press clears
//              its veil AT ONCE, because the tile's own colour turning red
//              "Open" or white "Closed" IS the confirmation).
//
//              THE RULES THAT MATTER MOST
//              1. An absent or unrecognised doorState is UNKNOWN — the tile
//                 shows a dash and refuses presses. A device missing from the
//                 poll must never render as a confident "Closed" (the
//                 absent-state-is-never-a-match rule, pointed at a tile).
//              2. Moving is display-only (intent null) — pulsing an opener
//                 mid-travel stops or reverses it unpredictably.
//              3. holdDone shortens ONLY the done hold. Timeout and error
//                 veils keep their long holds: failures must be readable.
//
//              Runs the shipped dashboards-action.js whole in a vm context,
//              so this locks what ships rather than a copy of it.
// Author:      CliveS & Claude Fable 5
// Date:        13-08-2026
// Version:     1.0
//
// Run: node tests/test_door_tile.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboards-action.js");
const src = fs.readFileSync(SRC, "utf8");

/* ── minimal DOM, same shape as test_action_watch.mjs's ─────────────────── */

function makeEl(tag) {
    const el = {
        tagName: tag, children: [], dataset: {}, parentNode: null,
        textContent: "", _attrs: {}, _classes: new Set(),
    };
    el.classList = {
        add: (...c) => c.forEach(x => el._classes.add(x)),
        remove: (...c) => c.forEach(x => el._classes.delete(x)),
        contains: c => el._classes.has(c),
    };
    Object.defineProperty(el, "className", {
        get: () => [...el._classes].join(" "),
        set: (v) => { el._classes = new Set(String(v).split(/\s+/).filter(Boolean)); },
    });
    el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
    el.remove = () => {
        const p = el.parentNode;
        if (p) p.children = p.children.filter(x => x !== el);
        el.parentNode = null;
    };
    el.setAttribute = (k, v) => { el._attrs[k] = String(v); };
    el.getAttribute = (k) => (k in el._attrs ? el._attrs[k] : null);
    el.querySelector = (sel) => descendants(el, sel)[0] || null;
    el.querySelectorAll = (sel) => descendants(el, sel);
    Object.defineProperty(el, "innerHTML", {
        get: () => el._html || "",
        set: (h) => {
            el._html = h;
            el.children = [];
            const re = /<span class="([^"]+)"><\/span>/g;
            let m;
            while ((m = re.exec(h))) {
                const c = makeEl("span");
                m[1].split(/\s+/).forEach(x => c._classes.add(x));
                el.appendChild(c);
            }
        },
    });
    return el;
}

function matches(el, sel) {
    if (sel.startsWith(".")) return el._classes.has(sel.slice(1));
    if (sel.startsWith("[") && sel.endsWith("]")) {
        return el.getAttribute(sel.slice(1, -1)) !== null;
    }
    return false;
}

function descendants(root, sel) {
    const scoped = sel.startsWith(":scope >");
    const s = scoped ? sel.replace(":scope >", "").trim() : sel;
    const out = [];
    const walk = (node, depth) => {
        node.children.forEach(c => {
            if ((!scoped || depth === 0) && matches(c, s)) out.push(c);
            if (!scoped) walk(c, depth + 1);
        });
    };
    walk(root, 0);
    return out;
}

function makeBox() {
    const body = makeEl("body");
    const head = makeEl("head");
    const doc = {
        _styles: {}, head, body,
        createElement: makeEl,
        getElementById: (id) => doc._styles[id] || null,
        querySelectorAll: (sel) => descendants(body, sel),
    };
    const realAppend = head.appendChild;
    head.appendChild = (c) => { if (c.id) doc._styles[c.id] = c; return realAppend(c); };

    const box = { console, document: doc, NOW: 1_000_000, _timers: [] };
    box.window = box;
    box.Date = { now: () => box.NOW };
    box.setInterval = (fn, ms) => {
        const t = { fn, ms, next: box.NOW + ms, id: box._timers.length + 1 };
        box._timers.push(t);
        return t.id;
    };
    box.clearInterval = (id) => {
        const i = box._timers.findIndex(t => t.id === id);
        if (i >= 0) box._timers.splice(i, 1);
    };
    box.advance = (ms) => {
        const target = box.NOW + ms;
        while (box.NOW < target) {
            const due = box._timers.filter(t => t.next <= target);
            if (!due.length) { box.NOW = target; break; }
            const soonest = Math.min(...due.map(t => t.next));
            box.NOW = soonest;
            box._timers.slice().forEach(t => {
                if (t.next <= box.NOW && box._timers.includes(t)) {
                    t.next = box.NOW + t.ms;
                    t.fn();
                }
            });
        }
    };
    vm.createContext(box);
    vm.runInContext(src, box, { filename: "dashboards-action.js" });
    if (!box.DashAction) throw new Error("dashboards-action.js did not export DashAction");
    return box;
}

/* ── harness ────────────────────────────────────────────────────────────── */

let pass = 0, fail = 0;
function check(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (ok) { pass++; console.log(`  ok   ${name}`); }
    else { fail++; console.log(`  FAIL ${name}\n         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
}
const flush = () => new Promise(r => setImmediate(r));

const box = makeBox();
const DA = box.DashAction;
const dt = (state, last) => DA.doorTile(state, last);

console.log("\n== doorTile: the settled states ==");
check("closed -> white tile, press opens",
    dt("closed"), { key: "closed", label: "Closed", intent: "open" });
check("open -> red tile, press closes",
    dt("open"), { key: "open", label: "Open", intent: "close" });

console.log("\n== doorTile: moving names its direction from the last settled state ==");
check("moving after closed -> Opening…, display-only",
    dt("moving", "closed"), { key: "opening", label: "Opening…", intent: null });
check("moving after open -> Closing…, display-only",
    dt("moving", "open"), { key: "closing", label: "Closing…", intent: null });
check("moving with no history (page opened mid-travel) -> neutral",
    dt("moving", undefined), { key: "moving", label: "Moving…", intent: null });

console.log("\n== doorTile: stuck offers the recovery, unknown offers nothing ==");
check("stuck -> amber, press fires close (secure the house)",
    dt("stuck"), { key: "stuck", label: "Stuck — check it", intent: "close" });
check("the plugin's own 'unknown' state -> dash, no press",
    dt("unknown"), { key: "unknown", label: "—", intent: null });

console.log("\n== doorTile: absent is never a confident tile ==");
check("undefined (device missing from the poll) -> unknown",
    dt(undefined), { key: "unknown", label: "—", intent: null });
check("null -> unknown",
    dt(null), { key: "unknown", label: "—", intent: null });
check("empty string -> unknown",
    dt(""), { key: "unknown", label: "—", intent: null });
check("an unrecognised value is never guessed at",
    dt("ajar"), { key: "unknown", label: "—", intent: null });

console.log("\n== doorTile: v2-API string variance ==");
check("case and whitespace tolerated",
    dt("  Closed "), { key: "closed", label: "Closed", intent: "open" });
check("OPEN uppercase",
    dt("OPEN"), { key: "open", label: "Open", intent: "close" });

/* ── lockTile: the lock-flavoured variant (front door) ──────────────────── */

const lt = (c, l) => DA.lockTile(c, l);

console.log("\n== lockTile: the front-door states ==");
check("closed + locked -> white Locked, press unlocks",
    lt(false, true), { key: "closed", label: "Locked", intent: "open" });
check("closed + unlocked -> blue Unlocked, display-only",
    lt(false, false), { key: "unlocked", label: "Unlocked", intent: null });
check("contact open -> red Open, display-only (nothing closes a front door)",
    lt(true, true), { key: "open", label: "Open", intent: null });
check("open wins even with the lock reporting unlocked",
    lt(true, false), { key: "open", label: "Open", intent: null });

console.log("\n== lockTile: a silent sensor never reassures ==");
check("absent contact -> unknown even with a healthy lock",
    lt(undefined, true), { key: "unknown", label: "—", intent: null });
check("closed but absent lock -> unknown (never a guessed Locked)",
    lt(false, undefined), { key: "unknown", label: "—", intent: null });
check("null contact -> unknown",
    lt(null, true), { key: "unknown", label: "—", intent: null });
check("a dead lock cannot blind an OPEN door (contact consulted first)",
    lt(true, undefined), { key: "open", label: "Open", intent: null });

console.log("\n== lockTile: v2-API string booleans ==");
check('"False" contact + "True" lock -> Locked',
    lt("False", "True"), { key: "closed", label: "Locked", intent: "open" });
check('"true" contact -> Open',
    lt("true", "false"), { key: "open", label: "Open", intent: null });
check("a non-boolean string is unknown, not false",
    lt("n/a", true), { key: "unknown", label: "—", intent: null });

/* ── the spec extensions, driven through the real run()/settle() path ───── */

const DOOR_ID = 489580549;
const SPEC = {
    title: "Garage", timeoutSec: 45,
    sendingText: "Sending…", workingText: "Opening…",
    timeoutText: "No confirmation — check the door",
    theme: "door", holdDone: 0,
    rules: [
        { when: [{ id: DOOR_ID, state: "doorState", is: "open" }],
          phase: "done", text: "Garage open" },
        { when: [], phase: "working", text: "Door moving…" },
    ],
};
const KEY = "door:" + DOOR_ID;
const doorDev = (s) => [{ id: DOOR_ID, states: { doorState: s } }];

function tile() {
    const b = makeEl("button");
    b.setAttribute("data-dsh-act-key", KEY);
    box.document.body.appendChild(b);
    return b;
}
const veilText = (el) => {
    const v = el.querySelector(".dsh-act-veil");
    const t = v && v.querySelector(".dsh-act-txt");
    return t ? t.textContent : null;
};

console.log("\n== theme:'door' — the in-flight veil carries the door class ==");
DA.reset();
box.document.body.children = [];
let btn = tile();
DA.run({ key: KEY, actionId: 1, spec: SPEC, exec: () => Promise.resolve() });
check("sending veil is door-themed", btn.classList.contains("dsh-act-t-door"), true);
await flush();
check("working veil keeps the theme", btn.classList.contains("dsh-act-t-door"), true);
check("and shows the working text", veilText(btn), "Opening…");

console.log("\n== holdDone:0 — the tile's colour IS the confirmation ==");
DA.tick(doorDev("open"));
check("confirmed -> veil GONE at once, no green interlude", veilText(btn), null);
check("watch fully cleared (not pending)", DA.pending(KEY), false);
check("door class removed with it", btn.classList.contains("dsh-act-t-door"), false);

console.log("\n== a themeless watch keeps the old behaviour ==");
DA.reset();
box.document.body.children = [];
btn = tile();
const PLAIN = Object.assign({}, SPEC);
delete PLAIN.theme;
delete PLAIN.holdDone;
DA.run({ key: KEY, actionId: 1, spec: PLAIN, exec: () => Promise.resolve() });
await flush();
check("no door class without the theme", btn.classList.contains("dsh-act-t-door"), false);
DA.tick(doorDev("open"));
check("done veil HOLDS without holdDone", veilText(btn), "Garage open");
box.advance(DA.HOLD_MS.done + 1000);
check("and clears after its normal hold", veilText(btn), null);

console.log("\n== holdDone never shortens a FAILURE hold ==");
DA.reset();
box.document.body.children = [];
btn = tile();
const QUICK = Object.assign({}, SPEC, { timeoutSec: 1 });
DA.run({ key: KEY, actionId: 1, spec: QUICK, exec: () => Promise.resolve() });
await flush();
box.advance(1500);          // past timeoutSec -> settle('timeout')
check("timeout veil is present and readable",
    veilText(btn), "No confirmation — check the door");
box.advance(5000);          // holdDone:0 must NOT have applied to it
check("still readable well past a zero hold", veilText(btn), "No confirmation — check the door");

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
