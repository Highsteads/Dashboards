// Filename:    test_hub_saving_session_chip.mjs
// Description: Contract test for the Octopus Saving Session chip in the hub's
//              hero, beside the Axle (VPP) chip.
//
//              WHY THIS EXISTS
//              v3.15.0 put the session on the hub as a row in the Energy card.
//              What was asked for was the hero, where the Axle chip appears, and
//              a session that is on tonight did not show there at all. So this
//              pins both halves: the chip's wording for every kind of session,
//              and that renderHousePulse really puts it in the hero row, after
//              the VPP chip, from the shared DashCalc decision.
//
//              Times are built with the local-time Date constructor and the
//              expected ranges come from DashCalc.sessionRange itself, so the
//              test does not depend on the machine's time zone or locale.
// Author:      CliveS & Claude Opus 5
// Date:        16-09-2026
// Version:     1.0
//
// Run: node tests/test_hub_saving_session_chip.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                        "Resources", "static", "pages");
const raw = fs.readFileSync(path.join(PAGES, "index.html"), "utf8");
const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function fn(name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in index.html`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

// The REAL shared module, never a stub.
const require_ = createRequire(import.meta.url);
require_(path.join(PAGES, "energy-calc.js"));
const DashCalc = globalThis.DashCalc;
if (!DashCalc || typeof DashCalc.savingSessions !== "function") {
    throw new Error("energy-calc.js did not export DashCalc.savingSessions");
}

// ── stub DOM, the same shape test_hub_vpp_and_version.mjs uses ──────────────
const els = {};
globalThis.document = { getElementById: (id) => (els[id] = els[id] || { id, innerHTML: "", style: {} }) };
globalThis.window = globalThis;
globalThis.DashIcons = { svg: (n) => `<svg data-n="${n}"></svg>` };

new Function(`
    function escapeAttr(s) {
        return String(s == null ? "" : s)
            .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;");
    }
    ${(code.match(/const asBool = [^\n]+\n/) || [""])[0]}
    ${fn("savingSessionChip")}
    ${fn("renderHousePulse")}
    ${fn("_sigen")}
    globalThis.savingSessionChip = savingSessionChip;
    globalThis.renderHousePulse = renderHousePulse;
`)();

let pass = 0, fail = 0;
const check = (ok, label, detail = "") => {
    ok ? pass++ : fail++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${label}${detail ? "   " + JSON.stringify(detail) : ""}`);
};

// Wednesday 16 Sep 2026, local time.
const at = (d, h, m = 0) => new Date(2026, 8, d, h, m).getTime();
const iso = (ms) => new Date(ms).toISOString();
const sess = (startMs, endMs, extra = {}) => ({
    upcoming: [{ id: 6269, start: iso(startMs), end: iso(endMs), points: 82,
                 direction: "TURN_DOWN", joined: true, capacity: null, ...extra }],
});
const range = (s, e, now) => DashCalc.sessionRange(s, e, now);

// 1. Nothing to say -> no chip.
check(savingSessionChip(null, at(16, 14)) === null, "no payload gives no chip");
check(savingSessionChip({ upcoming: [] }, at(16, 14)) === null, "an empty list gives no chip");
check(savingSessionChip(sess(at(16, 11), at(16, 12)), at(16, 14)) === null,
      "a finished session gives no chip");

// 2. Tonight, opted in — tonight's real case.
let now = at(16, 14), s = at(16, 18), e = at(16, 19);
let c = savingSessionChip(sess(s, e), now);
check(c && c.cls === "good", "opted in tonight is green", c);
check(c && c.text === `Saving Session tonight · ${range(s, e, now)} · opted in`,
      "and says tonight, the times and opted in", c && c.text);

// 3. Not opted in -> amber, and says so in words.
c = savingSessionChip(sess(s, e, { joined: false }), now);
check(c && c.cls === "warn", "not opted in is amber", c);
check(c && c.text === `Saving Session tonight · ${range(s, e, now)} · NOT OPTED IN`,
      "and says NOT OPTED IN", c && c.text);

// 4. Running.
c = savingSessionChip(sess(s, e), at(16, 18, 20));
check(c && c.cls === "warn", "a running session is amber, like VPP running", c);
check(c && c.text === `Saving Session running · until ${DashCalc.sessionEndTime(e)}`,
      "and says when it ends", c && c.text);
c = savingSessionChip(sess(s, e, { joined: false }), at(16, 18, 20));
check(c && c.cls === "warn" && /running/.test(c.text) && /NOT OPTED IN/.test(c.text),
      "running but not opted in still says NOT OPTED IN", c);

// 5. Earlier in the day reads "today", not "tonight".
c = savingSessionChip(sess(at(16, 11), at(16, 12)), at(16, 9));
check(c && /^Saving Session today · /.test(c.text), "a late-morning session says today", c && c.text);

// 6. Tomorrow: no today/tonight; the range carries the weekday.
now = at(16, 20); s = at(17, 18); e = at(17, 19);
c = savingSessionChip(sess(s, e), now);
check(c && c.text === `Saving Session · ${range(s, e, now)} · opted in`,
      "tomorrow's session carries the weekday instead", c && c.text);
check(c && !/tonight|today/.test(c.text), "and never says tonight", c && c.text);

// 7. More than a day away is not news.
check(savingSessionChip(sess(at(19, 18), at(19, 19)), at(16, 14)) === null,
      "a session three days out gives no chip");

// 8. Free hour.
now = at(16, 9); s = at(16, 11); e = at(16, 12);
c = savingSessionChip(sess(s, e, { direction: "WEEKEND_HAPPY_HOUR" }), now);
check(c && c.cls === "good" && c.text === `Free hour today · ${range(s, e, now)} · booked`,
      "a booked free hour is green", c);
c = savingSessionChip(sess(s, e, { direction: "WEEKEND_HAPPY_HOUR", joined: false }), now);
check(c && c.cls === "" && /not booked/.test(c.text), "an unbooked free hour is plain, never amber", c);

// 9. An unknown direction surfaces, escaped.
c = savingSessionChip(sess(s, e, { direction: "<b>NEW</b>" }), now);
check(c && c.cls === "" && c.text.includes("&lt;b&gt;NEW&lt;/b&gt;") && !c.text.includes("<b>"),
      "an unknown session type is shown and escaped", c && c.text);

// 10. It really reaches the hero, after the VPP chip.
const DEVICES = [{ id: 1, name: "Presence - Clive", deviceTypeId: "unifiClient",
                   states: { presence: "home" }, errorState: "" }];
function pulse(payload) {
    els["pulse-row"] = { id: "pulse-row", innerHTML: "", style: {} };
    window.__SIGEN_DATA = payload;
    window.__SIGEN_AT = Date.now();
    renderHousePulse(DEVICES);
    return els["pulse-row"].innerHTML;
}
const liveNow = Date.now();
let html = pulse({ octopus_sessions: sess(liveNow + 3600e3, liveNow + 7200e3) });
check(/<a class="pulse-chip good" href="energy.html"><svg data-n="money"><\/svg> Saving Session/.test(html),
      "the hero row carries the chip, green, linked to the energy page", html.slice(-220));
html = pulse({ vpp: { state: "announced", active: false, event_str: "19:00-20:00" },
               octopus_sessions: sess(liveNow + 3600e3, liveNow + 7200e3) });
check(html.indexOf("VPP announced") >= 0 && html.indexOf("VPP announced") < html.indexOf("Saving Session"),
      "and sits after the VPP chip");
html = pulse({ octopus_sessions: { upcoming: [] } });
check(!/Saving Session/.test(html), "no session, no chip in the hero");
html = pulse(null);
check(!/Saving Session/.test(html), "no Sigen data, no chip in the hero");

// 11. The energy card row stays too.
check((code.match(/\$\{ssRow\}/g) || []).length === 2, "the Energy card row is still in both layouts");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
