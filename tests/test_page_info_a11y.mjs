// Filename:    test_page_info_a11y.mjs
// Description: The page half of the 24-09-2026 deep review's INFO findings on
//              names and input. [88] Active's switch and brightness slider
//              were unnamed to a screen reader (the room page's were named in
//              [66]). [89] a camera tile could not be focused or chosen from
//              the keyboard and showed no camera name. [90] the control PIN
//              was typed into a plain text field that browsers keep in their
//              form history, and removing it meant typing a word into a
//              numeric field.
// Author:      CliveS & Claude Opus 5.5
// Date:        24-09-2026
// Version:     1.0
//
// Run: node tests/test_page_info_a11y.mjs

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const esc = s => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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

console.log("\n[88] Active: the switch and the slider say which device");
{
    const src = read("active.html");
    const box = {
        console, String, Number, parseInt, isFinite,
        DashTile: { isReachable: () => true, isOn: v => v === true },
        escapeHtml: esc, getWatts: () => null, fmtW: String, describeState: () => "On",
    };
    vm.createContext(box);
    vm.runInContext(extractFn(src, "renderRow") + "\nglobalThis.__r = renderRow;", box);
    const h = box.__r({ id: 5, name: "Hall <Lamp>", class: "indigo.Dimmer", onState: true, brightness: 40 });
    check("the switch is named after the device", /type="checkbox"[^>]*aria-label="Hall &lt;Lamp&gt;"/.test(h), h);
    check("the slider says whose brightness", /type="range"[\s\S]*?aria-label="Hall &lt;Lamp&gt; brightness"/.test(h));
}

console.log("\n[89] Cameras: a tile is a named button that works from the keyboard");
{
    const src = read("cameras.html");
    const grid = extractFn(src, "buildGrid");
    check("the frame is a focusable button", /class="cam-frame" role="button" tabindex="0"/.test(grid));
    check("named for its camera", /aria-label="Show \$\{escAttr\(name\)\} large"/.test(grid));
    check("the caption shows the camera's name", /<span class="name"><span class="dot"><\/span>\$\{escAttr\(name\)\}<\/span>/.test(grid));
    check("Enter and Space choose it", /addEventListener\("keydown"[\s\S]*?"Enter"[\s\S]*?" "[\s\S]*?focusTile\(host\)/.test(grid));
    check("a key pressed on the Snapshot button is left to that button", /e\.target !== frame\) return/.test(grid));
    check("and the focus is visible", /\.cam-frame:focus-visible\s*\{[^}]*outline/.test(src));
}

console.log("\n[90] Settings: the control PIN is a password field with its own remove box");
{
    const src = read("settings.html");
    const field = (src.match(/<input[^>]*id="sec-pin"[^>]*>/) || [""])[0];
    check("type=password", /type="password"/.test(field), field);
    check("still a number pad", /inputmode="numeric"/.test(field));
    check("not kept by the browser's form memory", /autocomplete="new-password"/.test(field));
    check("removal is a box, offered only when a PIN is set",
          /cfg\.controlPinSet \? `<label class="pin-clear"><input type="checkbox" id="sec-pin-clear">/.test(src));
    const box = { console };
    vm.createContext(box);
    vm.runInContext(extractFn(src, "pinToSave") + "\nglobalThis.__p = pinToSave;", box);
    const main = (pin, clear) => ({ querySelector: sel => sel === "#sec-pin" ? { value: pin }
                                                        : sel === "#sec-pin-clear" ? clear : null });
    checkEq("the ticked box removes the PIN", box.__p(main("1234", { checked: true })), "clear");
    checkEq("blank keeps it", box.__p(main("  ", { checked: false })), "");
    checkEq("a typed PIN replaces it", box.__p(main(" 4321 ", null)), "4321");
    check("the save sends what pinToSave says", /controlPin:\s+pinToSave\(main\)/.test(src));
}

done();
