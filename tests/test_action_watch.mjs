// Filename:    test_action_watch.mjs
// Description: Contract test for DashAction — how the dashboard's control
//              buttons decide that the thing they asked for ACTUALLY HAPPENED.
//
//              WHY THIS EXISTS
//              The door tiles used to confirm with a 12 px tick that lived
//              somewhere between 0 and 1200 ms, under the pressing finger, and
//              said "Done" whether or not anything had moved. A 200 from Indigo
//              means only that the action group was accepted: the garage
//              controller can drop a press on its 5 s debounce and still
//              return 200, and Front_Door_Loop.py then blocks for up to 90 s
//              retrying the unlock. So the only honest confirmation comes from
//              the contact sensors, and that is what these rules read.
//
//              THE CASE THAT MATTERS MOST is "top reed made, bottom sensor has
//              never reported". An absent state reads back undefined, and
//              undefined == false compares EQUAL under loose comparison — so a
//              naive evaluator confirms "Garage open" off ONE working sensor
//              and a silent one. That is the FP300 lesson (a missing state is
//              not a passing check) pointed at a door.
//
//              Runs the shipped dashboards-action.js whole, in a vm context
//              with a fake DOM and a fake clock, so this locks what ships
//              rather than a copy of it.
// Author:      CliveS & Claude Opus 5
// Date:        02-08-2026
// Version:     1.0
//
// Run: node tests/test_action_watch.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                      "Resources", "static", "pages", "dashboards-action.js");
const src = fs.readFileSync(SRC, "utf8");

/* ── a DOM small enough to hand-roll, real enough to catch the re-render bug ── */

function makeEl(tag) {
    const el = {
        tagName: tag,
        children: [],
        dataset: {},
        parentNode: null,
        textContent: "",
        _attrs: {},
        _classes: new Set(),
    };
    el.classList = {
        add: (...c) => c.forEach(x => el._classes.add(x)),
        remove: (...c) => c.forEach(x => el._classes.delete(x)),
        contains: c => el._classes.has(c),
    };
    // A real className= feeds classList. Without this the veil is created with
    // no classes and every selector for it comes back empty — which looks
    // exactly like the module never building one.
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
            // Only ever used by decorate() for a single empty <span class="…">.
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
    // ":scope > .x" — direct children only. Everything else, whole subtree.
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

/* ── sandbox ────────────────────────────────────────────────────────────── */

function makeBox() {
    const body = makeEl("body");
    const head = makeEl("head");
    const doc = {
        _styles: {},
        head,
        body,
        createElement: makeEl,
        getElementById: (id) => doc._styles[id] || null,
        querySelectorAll: (sel) => descendants(body, sel),
    };
    // injectStyle appends its <style> to head; record it by id so the guard works.
    const realAppend = head.appendChild;
    head.appendChild = (c) => { if (c.id) doc._styles[c.id] = c; return realAppend(c); };

    const box = {
        console,
        document: doc,
        NOW: 1_000_000,
        _timers: [],
    };
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
        // Step the clock in timer-sized bites so intervals fire the right number
        // of times, the way a real 500 ms tick would.
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

/* ── fixtures: the real ids and the real semantics ──────────────────────── */

const BOTTOM = 315055299, TOP = 1689547546;
const FD_CONTACT = 651379270, FD_LOCK = 1835630858;

// Mirrors Garage_Door_Controller.py get_door_state(): states.contact is the
// reed. onState is its exact INVERSE on these two, which is why nothing here
// touches onState.
const GARAGE_OPEN = [{ id: TOP, state: "contact", is: true },
                     { id: BOTTOM, state: "contact", is: false }];
const GARAGE_CLOSED = [{ id: BOTTOM, state: "contact", is: true },
                       { id: TOP, state: "contact", is: false }];

const FORCE_OPEN = {
    title: "Garage", timeoutSec: 45,
    sendingText: "Sending…", workingText: "Opening…",
    timeoutText: "No confirmation — check the door",
    rules: [
        { when: GARAGE_OPEN, phase: "done", text: "Garage open" },
        { when: GARAGE_CLOSED, phase: "working", text: "Still closed — waiting" },
        { when: [], phase: "working", text: "Door moving…" },
    ],
};
const FORCE_CLOSE = {
    title: "Garage", timeoutSec: 45,
    sendingText: "Sending…", workingText: "Closing…",
    timeoutText: "No confirmation — check the door",
    rules: [
        { when: GARAGE_CLOSED, phase: "done", text: "Garage closed" },
        { when: GARAGE_OPEN, phase: "working", text: "Still open — waiting" },
        { when: [], phase: "working", text: "Door moving…" },
    ],
};
const FRONT_DOOR = {
    title: "Front door", timeoutSec: 95,
    timeoutText: "Not opened — check the door",
    rules: [
        { when: [{ id: FD_CONTACT, state: "onOffState", is: true }],
          phase: "done", text: "Front door open" },
        { when: [{ id: FD_LOCK, state: "onOffState", is: false }],
          phase: "working", text: "Unlocked — push the door" },
        { when: [], phase: "working", text: "Unlocking…" },
    ],
};

const dev = (id, states) => ({ id, states });
const garage = (bottom, top) => [dev(BOTTOM, { contact: bottom }), dev(TOP, { contact: top })];

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
const ev = (spec, devices, ms) => DA.evaluate(spec, devices, ms || 0);

console.log("\n== evaluate: garage travel ==");
check("closed, force-open pressed -> waiting",
    ev(FORCE_OPEN, garage(true, false)),
    { phase: "working", text: "Still closed — waiting" });
check("mid-travel (both reeds apart) -> moving",
    ev(FORCE_OPEN, garage(false, false)),
    { phase: "working", text: "Door moving…" });
check("top reed made -> confirmed open",
    ev(FORCE_OPEN, garage(false, true)),
    { phase: "done", text: "Garage open" });
check("force-close while already closed -> done at once (idempotent)",
    ev(FORCE_CLOSE, garage(true, false)),
    { phase: "done", text: "Garage closed" });

console.log("\n== evaluate: the absent-state trap ==");
// Top reed made, bottom sensor has never reported. GARAGE_OPEN's second
// condition is {bottom, contact, is:false} — and undefined == false is TRUE in
// JS. Anything comparing loosely announces a door that never moved.
check("one silent sensor must NOT confirm an opening",
    ev(FORCE_OPEN, [dev(BOTTOM, {}), dev(TOP, { contact: true })]),
    { phase: "working", text: "Door moving…" });
check("explicit null is not a match either",
    ev(FORCE_OPEN, [dev(BOTTOM, { contact: null }), dev(TOP, { contact: true })]),
    { phase: "working", text: "Door moving…" });
check("device missing from the payload entirely -> no throw, no match",
    ev(FORCE_OPEN, [dev(TOP, { contact: true })]),
    { phase: "working", text: "Door moving…" });
check("empty device list -> catch-all",
    ev(FORCE_OPEN, []),
    { phase: "working", text: "Door moving…" });

console.log("\n== evaluate: v2 API string booleans ==");
check('"False"/"True" strings coerce like real booleans',
    ev(FORCE_OPEN, garage("False", "True")),
    { phase: "done", text: "Garage open" });
check('"true"/"false" lowercase too',
    ev(FORCE_CLOSE, garage("true", "false")),
    { phase: "done", text: "Garage closed" });
check("a non-boolean string is unknown, not false",
    ev(FORCE_OPEN, [dev(BOTTOM, { contact: "n/a" }), dev(TOP, { contact: true })]),
    { phase: "working", text: "Door moving…" });

console.log("\n== evaluate: the clock ==");
check("before the timeout -> still working",
    ev(FORCE_OPEN, garage(true, false), 44_000),
    { phase: "working", text: "Still closed — waiting" });
check("past the timeout -> timeout",
    ev(FORCE_OPEN, garage(true, false), 45_000),
    { phase: "timeout", text: "No confirmation — check the door" });
check("a confirmation on the same tick beats the clock",
    ev(FORCE_OPEN, garage(false, true), 90_000),
    { phase: "done", text: "Garage open" });
check("no timeoutSec -> 60 s default",
    ev({ rules: [] }, [], 60_000).phase, "timeout");

console.log("\n== evaluate: front door ==");
check("locked and shut -> unlocking",
    ev(FRONT_DOOR, [dev(FD_LOCK, { onOffState: true }), dev(FD_CONTACT, { onOffState: false })]),
    { phase: "working", text: "Unlocking…" });
check("unlocked but still shut -> push the door",
    ev(FRONT_DOOR, [dev(FD_LOCK, { onOffState: false }), dev(FD_CONTACT, { onOffState: false })]),
    { phase: "working", text: "Unlocked — push the door" });
check("door opened -> confirmed",
    ev(FRONT_DOOR, [dev(FD_LOCK, { onOffState: false }), dev(FD_CONTACT, { onOffState: true })]),
    { phase: "done", text: "Front door open" });
check("95 s budget outlives Front_Door_Loop.py's 90 s",
    ev(FRONT_DOOR, [dev(FD_LOCK, { onOffState: true })], 90_000).phase, "working");

console.log("\n== the takeover survives a re-render ==");
const KEY = "scene:1463818396";
box.INDIGO_CONFIG = { actionWatch: { "1463818396": FORCE_OPEN } };

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

DA.reset();
box.document.body.children = [];
let btn = tile();
let settled = null;
DA.run({ key: KEY, actionId: 1463818396, exec: () => Promise.resolve() })
    .then(v => { settled = v; });

check("veil appears immediately on press", veilText(btn), "Sending…");
check("covered tile is not pressable again", DA.pending(KEY), true);

await flush();
check("accepted -> working", veilText(btn), "Opening…");

// The hub throws the whole favourites card away every 3 s. This is the exact
// failure that made the old tick unreadable.
box.document.body.children = [];
btn = tile();
check("a freshly rebuilt tile has no veil of its own", veilText(btn), null);
DA.repaint();
check("repaint restores the takeover onto the new node", veilText(btn), "Opening…");
check("and it is still not pressable", btn.classList.contains("dsh-act-working"), true);

DA.tick(garage(false, false));
check("mid-travel shows movement", veilText(btn), "Door moving…");

box.advance(6000);
check("elapsed seconds count up while working", veilText(btn), "Door moving… 6s");

DA.tick(garage(false, true));
check("confirmed open", veilText(btn), "Garage open");
check("done clears the busy class", btn.classList.contains("dsh-act-done"), true);
check("no longer pending", DA.pending(KEY), false);

box.advance(DA.HOLD_MS.done + 1000);
check("the result clears itself after its hold", veilText(btn), null);

console.log("\n== failures are visible ==");
DA.reset();
box.document.body.children = [];
btn = tile();
await DA.run({ key: KEY, actionId: 1463818396,
               exec: () => Promise.reject(new Error("Network unreachable")) });
check("a failed call says so instead of vanishing", veilText(btn), "Failed — Network unreachable");
check("and is coloured as an error", btn.classList.contains("dsh-act-error"), true);

console.log("\n== timeout with nobody feeding it ==");
DA.reset();
box.document.body.children = [];
btn = tile();
DA.run({ key: KEY, actionId: 1463818396, exec: () => Promise.resolve() });
await flush();
box.advance(46_000);
check("a watch nothing confirms times out on its own",
    veilText(btn), "No confirmation — check the door");
check("timeout is not dressed up as success",
    btn.classList.contains("dsh-act-done"), false);

console.log("\n== no watch configured -> honest 'Sent' ==");
DA.reset();
box.document.body.children = [];
btn = tile();
await DA.run({ key: KEY, actionId: 999999, exec: () => Promise.resolve(), sentText: "Sent" });
check("an unwatched action claims only that it was sent", veilText(btn), "Sent");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
