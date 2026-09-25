// Filename:    test_room_camera_keyboard.mjs
// Description: A room page's camera card works from the keyboard (3.46.0).
//              It was a clickable <div> with no role, no tabindex and no key
//              handler, so Tab went straight past it and a screen reader
//              announced nothing. Now it is a named button that takes focus,
//              shows a focus ring, and opens the Cameras page on Enter or
//              Space, the same as a click. Drives the page's own functions.
// Author:      CliveS & Claude Opus 5.5
// Date:        25-09-2026
// Version:     1.0
//
// Run: node tests/test_room_camera_keyboard.mjs   (exit 0 = pass)

import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                            "Resources", "static", "pages", "room.html"), "utf8");

function fnSource(code, name) {
    const start = code.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`could not find ${name}`);
    let depth = 0;
    for (let j = code.indexOf("{", start); j < code.length; j++) {
        if (code[j] === "{") depth++;
        else if (code[j] === "}") { depth--; if (depth === 0) return code.slice(start, j + 1); }
    }
    throw new Error(`unbalanced braces in ${name}`);
}

const ctx = { location: { href: "room.html?room=Hall" },
              escapeHtml: (t) => String(t).replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`) };
vm.createContext(ctx);
vm.runInContext(["renderRoomCamera", "openRoomCamera", "roomCameraKey"].map(n => fnSource(SRC, n)).join("\n"), ctx);

const html = vm.runInContext(`renderRoomCamera({ host: "192.0.2.7", name: "Hall \\"Cam\\"" })`, ctx);
check("the card is a button to a screen reader", /class="camera-card"[^>]*role="button"/.test(html));
check("it takes Tab", /class="camera-card"[^>]*tabindex="0"/.test(html));
check("it has a name, escaped", /aria-label="Open Hall &#34;Cam&#34; on the Cameras page"/.test(html), html);
check("it has a key handler", /onkeydown="roomCameraKey\(event, this\)"/.test(html));

function press(key, onCard = true) {
    ctx.location.href = "room.html?room=Hall";
    const card = { dataset: { camHost: "192.0.2.7" } };
    let prevented = false;
    const e = { key, target: onCard ? card : {}, preventDefault: () => { prevented = true; } };
    ctx.roomCameraKey(e, card);
    return { href: ctx.location.href, prevented };
}
check("Enter opens the Cameras page on this camera", press("Enter").href === "cameras.html?focus=192.0.2.7");
const space = press(" ");
check("Space does too, without scrolling the page", space.href === "cameras.html?focus=192.0.2.7" && space.prevented);
check("any other key does nothing", press("a").href === "room.html?room=Hall" && !press("Tab").prevented);
check("a key meant for something inside the card is left alone", press("Enter", false).href === "room.html?room=Hall");

check("a visible focus ring", /\.camera-card:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--accent\)/.test(SRC));

done();
