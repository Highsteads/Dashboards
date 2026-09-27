// Filename:    test_settings_other_camera.mjs
// Description: The Settings page's camera table and the "other" make (3.52.0).
//              An "other" camera saves the RTSP address typed beside it and no
//              stream choice, a Dahua or Hikvision camera saves its stream and
//              no address, and a camera with a login of its own in Configure is
//              not listed as waiting for approval of the shared one. Drives the
//              real collectCameras and cameraLoginWithheld out of the shipped
//              page.
// Author:      CliveS & Claude Opus 5.5
// Date:        27-09-2026
// Version:     1.0
//
// Run: node tests/test_settings_other_camera.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                       "Resources", "static", "pages", "settings.html");
const src = fs.readFileSync(PAGE, "utf8");

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

const eq = (w, got, want) => check(`${w} — got ${JSON.stringify(got)}`,
                                   JSON.stringify(got) === JSON.stringify(want));

function row(f) {
    const fields = {
        ".c-host": { value: f.host }, ".c-name": { value: f.name },
        ".c-vendor": { value: f.vendor }, ".c-rtsp": { value: f.rtsp || "" },
        ".c-stream": { value: f.stream || "" }, ".c-rooms": { value: f.rooms || "" },
        ".c-main": { checked: !!f.main },
    };
    return { querySelector: sel => fields[sel] || null };
}
function root(rows) {
    return {
        querySelectorAll: sel => (sel === "#cam-rows tr" ? rows : []),
        querySelector: sel => (sel === "#swap-out" ? { value: "" } : null),
    };
}

const win = {};
const ctx = vm.createContext({ window: win });
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
ctx.esc = esc;
vm.runInContext(["collectCameras", "cameraLoginWithheld", "cameraMakes", "makeOptionsHtml", "makeAddress"]
                .map(n => extractFn(src, n)).join("\n")
                + "\nthis.collectCameras = collectCameras; this.cameraLoginWithheld = cameraLoginWithheld;"
                + " this.cameraMakes = cameraMakes; this.makeOptionsHtml = makeOptionsHtml; this.makeAddress = makeAddress;", ctx);

const out = ctx.collectCameras(root([
    row({ host: "192.0.2.50", name: "Porch", vendor: "other",
          rtsp: "  rtsp://192.0.2.50:554/stream1 ", stream: "main" }),
    row({ host: "192.0.2.1", name: "Front", vendor: "dahua", stream: "main" }),
    row({ host: "192.0.2.2", name: "Drive", vendor: "reolink", stream: "main",
          rtsp: "rtsp://192.0.2.2:554/h265Preview_01_main" }),
]));
eq("an other camera saves its address and no stream", out.cams[0],
   { host: "192.0.2.50", name: "Porch", vendor: "other", rtsp: "rtsp://192.0.2.50:554/stream1" });
eq("a known make with a blank box saves its stream and no address", out.cams[1],
   { host: "192.0.2.1", name: "Front", vendor: "dahua", stream: "main" });
eq("a known make with a typed address saves the address, which names its stream", out.cams[2],
   { host: "192.0.2.2", name: "Drive", vendor: "reolink", rtsp: "rtsp://192.0.2.2:554/h265Preview_01_main" });

// The make list comes from the plugin; without it (an older plugin), the two it knew.
win._camMakes = [{ id: "reolink", label: "Reolink", main: "rtsp://{host}:554/m", sub: "rtsp://{host}:554/s" }];
eq("the grey hint is the make's address for this host and stream",
   [ctx.makeAddress("reolink", "10.0.0.9", "main"), ctx.makeAddress("reolink", "10.0.0.9", ""),
    ctx.makeAddress("reolink", "", "main"), ctx.makeAddress("other", "10.0.0.9", "main")],
   ["rtsp://10.0.0.9:554/m", "rtsp://10.0.0.9:554/s", "", ""]);
const opts = ctx.makeOptionsHtml("somefuturemake");
check("a saved make the page does not know is kept, not swapped for the first",
      /<option value="somefuturemake" selected>/.test(opts));
check("other is always offered, last", /<option value="other">Other \(type the address\)<\/option>$/.test(opts));
delete win._camMakes;
eq("an older plugin falls back to the two makes it knew",
   ctx.cameraMakes().map(m => m.id), ["dahua", "hikvision"]);

win._camLoginHosts = ["192.0.2.1"];
win._camOwnLoginHosts = ["192.0.2.50"];
eq("its own login means it is not waiting for approval",
   ctx.cameraLoginWithheld([{ host: "192.0.2.1" }, { host: "192.0.2.50" }, { host: "192.0.2.51" }]),
   ["192.0.2.51"]);
delete win._camOwnLoginHosts;
eq("an older plugin that reports no own logins still works",
   ctx.cameraLoginWithheld([{ host: "192.0.2.50" }]), ["192.0.2.50"]);

check("Stream is greyed out for other or a typed address",
      /\.c-stream"\)\.disabled = vendor === "other" \|\| !!box\.value\.trim\(\)/.test(src));

done();
