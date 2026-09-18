// Filename:    test_alerts_settled_rows.mjs
// Description: Node contract test for alerts.html's log-watch row renderer.
//              Extracts the real render() out of the shipped page and drives it
//              against a stub DOM, so this locks what ships rather than a copy.
//
//              WHY IT EXISTS (18-09-2026): until today Log_Error_Watch MUTED
//              every "internal server error" IWS raised, because a plugin
//              restart 500s whatever a browser asks for while the loop is down.
//              That mute was path-blind, and measuring September showed only 26
//              of 112 such errors were anywhere near a restart — 84 of them
//              were one file the Dashboards plugin rewrites every few seconds.
//              So the mute went, replaced by a rule that has to find the
//              restart it blames, and the watch now marks those occurrences
//              `explained` rather than `muted`.
//
//              This card only ever knew about `muted`. Left alone it would
//              have painted every cascade row bright red with no marker — the
//              exact noise the rule exists to remove, arriving by a different
//              door. Three things are pinned:
//                1. a settled row (muted, answered or explained) is greyed and
//                   carries a pill saying WHICH of the three it is;
//                2. an ordinary error is still red and carries no pill;
//                3. the reason text is ESCAPED — it reaches the page from a
//                   rule label through innerHTML.
// Author:      CliveS & Claude Opus 5
// Date:        18-09-2026
// Version:     1.0
//
// Run: node tests/test_alerts_settled_rows.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "alerts.html");
const src  = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in alerts.html`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// ── stub DOM ───────────────────────────────────────────────────────────────
const meta = { textContent: "", innerHTML: "" };
const body = { textContent: "", innerHTML: "" };
const $ = (id) => (id === "logwatch-meta" ? meta : id === "logwatch-rows" ? body : null);
const esc = (s) => String(s).replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const shortTime = (s) => String(s || "");

const render = new Function("$", "esc", "shortTime",
    grab("render") + "; return render;")($, esc, shortTime);

// ── helpers ────────────────────────────────────────────────────────────────
let failures = 0;
function check(label, cond) {
    if (cond) { console.log(`  ok   ${label}`); }
    else { console.log(`  FAIL ${label}`); failures++; }
}
function paint(row) {
    body.innerHTML = "";
    render({ feed: { rows: [Object.assign(
        { source: "Web Server", message: "internal server error for request /x",
          level: "error", count: 3, last: "12:32" }, row)],
        errors: 0, warnings: 0, generatedLocal: "12:46" } });
    return body.innerHTML;
}

const GREY = "var(--text-secondary)";

console.log("alerts.html — settled rows carry a pill and are not red");

// 1. each settled kind is greyed and names itself
for (const [flag, pill] of [["muted", "muted"], ["recovered", "answered"],
                            ["explained", "explained"]]) {
    const html = paint({ [flag]: true });
    check(`${flag} row is greyed`,       html.includes(GREY));
    check(`${flag} row says "${pill}"`,  html.includes(`>${pill}</span>`));
    check(`${flag} row is not red`,      !html.includes("var(--red)"));
}

// 2. an ordinary error keeps its red dot and gains no pill
{
    const html = paint({});
    check("plain error is red",          html.includes("var(--red)"));
    check("plain error has no pill",     !/>(muted|answered|explained)</.test(html));
    check("plain error is not greyed",   !html.includes(GREY));
}

// 3. the explained reason is shown, and escaped
{
    const html = paint({ explained: true, reason: "IWS wedge after a plugin restart" });
    check("reason is shown",             html.includes("IWS wedge after a plugin restart"));
    const bad = paint({ explained: true, reason: '<img src=x onerror="alert(1)">' });
    check("reason is escaped",           !bad.includes("<img") && bad.includes("&lt;img"));
}

// 4. a row with no reason must not print a stray separator
{
    const html = paint({ explained: true, reason: "" });
    check("no reason, no dangling dot",  !/explained<\/span>\s*·\s*·/.test(html));
}

console.log(failures ? `\n${failures} failure(s)` : "\nAll alerts-card checks passed.");
process.exit(failures ? 1 : 0);
