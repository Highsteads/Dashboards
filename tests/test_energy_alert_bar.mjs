// Filename:    test_energy_alert_bar.mjs
// Description: Node contract test for energy.html's alert bar. Extracts the
//              real updateAlerts() out of the shipped page and drives it
//              against a stub DOM, so this locks what ships rather than a copy.
//
//              THE BUG THIS PINS (found live 30-Jul-2026, screenshot from
//              CliveS's phone): the bar was written with `textContent`, while
//              the icons it prefixes come from DashIcons.svg() as MARKUP.
//              textContent escapes markup, so the page printed
//              `<svg class="dsh-icon" viewBox="0 0 24 24" ...>` across the
//              top in red instead of drawing a bolt.
//
//              It survived the v2.51.0 icon sweep — which explicitly audited
//              insertion points for this exact mistake — because EVERY branch
//              in this function is an exception state that had not occurred
//              since: no storm has hit, Modbus has not dropped, and the VPP
//              branch could not fire at all while the Axle feed was dead.
//              A latent render bug in an alert path is invisible precisely
//              when things are going well, which is why it wants a test and
//              not another read-through.
//
//              Three things are pinned, and the third is the one a naive fix
//              would break:
//                1. the icon arrives as a real <svg> element, not as text;
//                2. an unstyled/absent icon still renders its message;
//                3. API-supplied text (the event window, the storm level) is
//                   ESCAPED — switching to innerHTML without splitting icon
//                   from text would trade a cosmetic bug for an injection.
// Author:      CliveS & Claude Fable 5
// Date:        30-07-2026
// Version:     1.0
//
// Run: node tests/test_energy_alert_bar.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC  = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "energy.html");
const src  = fs.readFileSync(SRC, "utf8");

function grab(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find function ${name} in energy.html`);
    let depth = 0, end = -1;
    for (let j = src.indexOf("{", start); j < src.length; j++) {
        if (src[j] === "{") depth++;
        else if (src[j] === "}") { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    return src.slice(start, end);
}

// ── stub DOM ───────────────────────────────────────────────────────────────
const bar = {
    id: "alert-bar", textContent: "", innerHTML: "", className: "",
    style: {},
};
globalThis.document = { getElementById: () => bar };
globalThis.window = globalThis;

// Stand-in for DashIcons: returns markup, exactly as the real one does.
const ICON = (n) => `<svg class="dsh-icon" data-n="${n}"><path d="M0 0"/></svg>`;
globalThis.DashIcons = { svg: ICON };

// ── load the real functions ────────────────────────────────────────────────
const code = [
    grab("esc"),
    grab("updateAlerts"),
    "const I = (n) => (window.DashIcons ? DashIcons.svg(n) : '');",
    "globalThis.updateAlerts = updateAlerts;",
].join("\n");
new Function(code)();

// ── assertions ─────────────────────────────────────────────────────────────
let failures = 0;
function check(label, cond, detail) {
    if (cond) { console.log(`  ok   ${label}`); }
    else { console.log(`  FAIL ${label}${detail ? "  — " + detail : ""}`); failures++; }
}

function reset() { bar.textContent = ""; bar.innerHTML = ""; bar.className = ""; bar.style = {}; }

const HEALTHY = { flags: { modbus_connected: true, import_active: false } };

// 1. VPP announced — the live case from the screenshot.
reset();
updateAlerts({ ...HEALTHY, vpp: { state: "announced", event_str: "19:00-20:00" } });
check("VPP announced renders an <svg> ELEMENT", bar.innerHTML.includes("<svg"), bar.innerHTML.slice(0, 80));
check("VPP announced does NOT escape the icon", !bar.innerHTML.includes("&lt;svg"), bar.innerHTML.slice(0, 80));
check("VPP announced keeps its wording", bar.innerHTML.includes("VPP event announced"));
check("VPP announced shows the window", bar.innerHTML.includes("19:00-20:00"));
check("bar is not written via textContent", bar.textContent === "", `textContent=${JSON.stringify(bar.textContent)}`);
check("VPP alone is not styled as a warning", bar.className === "");

// 2. VPP active.
reset();
updateAlerts({ ...HEALTHY, vpp: { active: true, state: "active", event_str: "19:00-20:00" } });
check("VPP active renders an <svg> ELEMENT", bar.innerHTML.includes("<svg"));
check("VPP active keeps its wording", bar.innerHTML.includes("VPP EVENT ACTIVE"));

// 3. Storm + Modbus still drive the warn class.
reset();
updateAlerts({ ...HEALTHY, storm: { level: "yellow" } });
check("storm sets the warn class", bar.className === "warn");
check("storm renders an <svg> ELEMENT", bar.innerHTML.includes("<svg"));
reset();
updateAlerts({ flags: { modbus_connected: false } });
check("modbus loss sets the warn class", bar.className === "warn");

// 4. An icon-less message still renders (the grid-charging branch passes '').
reset();
updateAlerts({ flags: { modbus_connected: true, import_active: true } });
check("icon-less message still renders", bar.innerHTML.includes("Charging from grid"));

// 5. INJECTION: API text must be escaped. event_str comes straight off the
//    Axle payload, so it is not ours to trust.
reset();
updateAlerts({ ...HEALTHY, vpp: { state: "announced", event_str: '<img src=x onerror="alert(1)">' } });
check("API text is escaped, not executed", !bar.innerHTML.includes("<img"), bar.innerHTML.slice(0, 120));
check("API text is still readable when escaped", bar.innerHTML.includes("&lt;img"));

// 6. Nothing wrong → bar hidden AND cleared (a stale alert must not linger).
reset();
bar.innerHTML = "stale";
updateAlerts(HEALTHY);
check("healthy system hides the bar", bar.style.display === "none");
check("healthy system clears the bar", bar.innerHTML === "", JSON.stringify(bar.innerHTML));

console.log(failures === 0
    ? "\ntest_energy_alert_bar.mjs: all checks passed"
    : `\ntest_energy_alert_bar.mjs: ${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
