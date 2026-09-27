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
vm.runInContext(extractFn(src, "collectCameras") + "\n" + extractFn(src, "cameraLoginWithheld")
                + "\nthis.collectCameras = collectCameras; this.cameraLoginWithheld = cameraLoginWithheld;", ctx);

const out = ctx.collectCameras(root([
    row({ host: "192.0.2.50", name: "Porch", vendor: "other",
          rtsp: "  rtsp://192.0.2.50:554/stream1 ", stream: "main" }),
    row({ host: "192.0.2.1", name: "Front", vendor: "dahua", rtsp: "left over", stream: "main" }),
]));
eq("an other camera saves its address and no stream", out.cams[0],
   { host: "192.0.2.50", name: "Porch", vendor: "other", rtsp: "rtsp://192.0.2.50:554/stream1" });
eq("a known make saves its stream and no address", out.cams[1],
   { host: "192.0.2.1", name: "Front", vendor: "dahua", stream: "main" });

win._camLoginHosts = ["192.0.2.1"];
win._camOwnLoginHosts = ["192.0.2.50"];
eq("its own login means it is not waiting for approval",
   ctx.cameraLoginWithheld([{ host: "192.0.2.1" }, { host: "192.0.2.50" }, { host: "192.0.2.51" }]),
   ["192.0.2.51"]);
delete win._camOwnLoginHosts;
eq("an older plugin that reports no own logins still works",
   ctx.cameraLoginWithheld([{ host: "192.0.2.50" }]), ["192.0.2.50"]);

check("the make list offers other", /<option value="other"/.test(src));
check("the address box shows only for other",
      /\.c-rtsp"\)\.hidden = !other/.test(src) && /\.c-stream"\)\.disabled = other/.test(src));

done();
