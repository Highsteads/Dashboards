// Filename:    test_when_ready.mjs
// Description: Node contract test for DashUI.whenReady, extracted from the
//              shipped dashboards-ui.js.
//
//              WHY IT EXISTS (v3.19.0). The server stopped doing slow work
//              inside /message/ handlers, because those run on the path IWS
//              serves everything else from — timelineDay took 1707 ms and
//              systemHealth 262 ms, and every millisecond stalled every other
//              dashboard in the house. A handler now answers within 0.75 s
//              either way: with the data, or 503 + {"pending": true}.
//
//              That means the FIRST view of a slow page always lands on
//              pending. A page that treats it as an error shows one — so the
//              fix would have traded a stall for a broken page. Four things
//              are pinned:
//                1. a pending 503 is retried until the data arrives;
//                2. a 400 comes straight back — polling a bad date for ever is
//                   worse than the stall this replaced;
//                3. a 503 that is NOT ours is passed through, not retried;
//                4. it gives up rather than polling for ever.
// Author:      CliveS & Claude Opus 5
// Date:        18-09-2026
// Version:     1.0
//
// Run: node tests/test_when_ready.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "dashboards-ui.js");
const src  = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`async function ${name}(`);
    if (start < 0) throw new Error(`could not find ${name} in dashboards-ui.js`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}
const whenReady = new Function(grab("whenReady") + "; return whenReady;")();

const reply = (status, obj) => ({
    status,
    clone() { return this; },
    async json() { if (obj === undefined) throw new Error("no body"); return obj; },
});

let failures = 0;
const check = (label, cond) => {
    console.log(`  ${cond ? "ok  " : "FAIL"} ${label}`);
    if (!cond) failures++;
};

console.log("DashUI.whenReady");

// 1. pending is retried until the data lands
{
    let n = 0;
    const r = await whenReady(async () => {
        n++;
        return n < 3 ? reply(503, { pending: true, error: "building" })
                     : reply(200, { ok: true });
    }, { everyMs: 5 });
    check("polls a pending 503 until it is ready", r.status === 200 && n === 3);
}

// 2. onWait fires once, not on every poll
{
    let waits = 0, n = 0;
    await whenReady(async () => (++n < 4 ? reply(503, { pending: true }) : reply(200, {})),
                    { everyMs: 5, onWait: () => waits++ });
    check("tells the page it is waiting exactly once", waits === 1);
}

// 3. anything that is not pending comes straight back
for (const [status, obj, label] of [
    [400, { ok: false, error: "date format" }, "a 400 is returned at once"],
    [500, { ok: false, error: "boom" },        "a 500 is returned at once"],
    [503, { ok: false, error: "other" },       "a 503 that is not ours is not retried"],
    [503, undefined,                           "a 503 with no JSON body is not retried"],
]) {
    let n = 0;
    const r = await whenReady(async () => { n++; return reply(status, obj); }, { everyMs: 5 });
    check(label, r.status === status && n === 1);
}

// 4. it gives up rather than polling for ever
{
    let n = 0;
    let threw = false;
    try {
        await whenReady(async () => { n++; return reply(503, { pending: true, error: "slow" }); },
                        { everyMs: 5, timeoutMs: 40 });
    } catch (e) { threw = e.message === "slow"; }
    check("gives up with the server's own reason", threw);
    check("and stopped polling", n < 40);
}

console.log(failures ? `\n${failures} failure(s)` : "\nAll whenReady checks passed.");
process.exit(failures ? 1 : 0);
