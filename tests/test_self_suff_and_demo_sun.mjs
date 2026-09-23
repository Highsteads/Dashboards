// Filename:    test_self_suff_and_demo_sun.mjs
// Description: v3.40.0. (1) A low self-sufficiency figure on a day the grid
//              charged the battery says why, instead of a bare 0% on a sunny
//              afternoon. (2) The demo's sunrise and sunset are worked out for
//              today, not frozen at the day the weather sample was taken, and
//              a real install's weather is never touched.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const load = (file, extra = {}) => {
    const w = Object.assign({ console }, extra);
    w.window = w; w.globalThis = w;
    vm.createContext(w);
    vm.runInContext(fs.readFileSync(path.join(PAGES, file), "utf8"), w);
    return w;
};

console.log("\nself-sufficiency says why it is low");
{
    const C = load("energy-calc.js").DashCalc;
    const why = C.selfSuffReason({ home_kwh: 13.64, import_kwh: 15.98, battery_charge_kwh: 19.75, self_suff: 0 });
    check("today's real case gets a reason", !!why);
    checkEq("short, for a tile", why.short, "grid charged the battery");
    checkEq("long, with the figures in words", why.long,
            "The grid supplied 16 kWh while the house used 13.6 kWh, because it also charged the battery. That energy runs the house later.");
    const part = C.selfSuffReason({ home_kwh: 12, import_kwh: 8, battery_charge_kwh: 5, self_suff: 33 });
    checkEq("part of the import", part && part.short, "partly from charging the battery");
    check("a good day needs no excuse", C.selfSuffReason({ home_kwh: 12, import_kwh: 1, battery_charge_kwh: 8, self_suff: 92 }) === null);
    check("low with no battery charging is just low", C.selfSuffReason({ home_kwh: 12, import_kwh: 10, battery_charge_kwh: 0.2, self_suff: 17 }) === null);
    check("missing figures give nothing, never a guess", C.selfSuffReason({ home_kwh: 12, self_suff: 0 }) === null);
    check("works out the percentage when the summary lacks it",
          !!C.selfSuffReason({ home_kwh: 10, import_kwh: 12, battery_charge_kwh: 6 }));
    for (const p of ["energy.html", "index.html"]) {
        check(`${p} uses the shared reason`, fs.readFileSync(path.join(PAGES, p), "utf8").includes("DashCalc.selfSuffReason("));
    }
}

console.log("\nthe demo's sun is today's");
{
    const demo = load("dashboards-ui.js", { INDIGO_CONFIG: { apiKey: "demo" } }).DashUI;
    const real = load("dashboards-ui.js", { INDIGO_CONFIG: { apiKey: "abc" } }).DashUI;
    const hm = (e, off) => new Date((e + off) * 1000).toISOString().slice(11, 16);
    const mins = s => +s.slice(0, 2) * 60 + +s.slice(3);
    const t = Date.UTC(2026, 8, 23, 12);
    const s = demo.sunTimes(t, 54.882, -1.818);
    // The live OpenWeatherMap forecast for this spot said 06:54 and 19:05.
    check("equinox sunrise within two minutes of the forecast", Math.abs(mins(hm(s.sunrise, 3600)) - mins("06:54")) <= 2, hm(s.sunrise, 3600));
    check("and sunset", Math.abs(mins(hm(s.sunset, 3600)) - mins("19:05")) <= 2, hm(s.sunset, 3600));
    const w = demo.sunTimes(Date.UTC(2026, 11, 21, 12), 54.882, -1.818);
    check("midwinter sets before 4pm", mins(hm(w.sunset, 0)) < 16 * 60, hm(w.sunset, 0));
    checkEq("BST starts at 01:00 UTC on the last Sunday of March",
            [demo.ukOffsetSec(Date.UTC(2026, 2, 29, 0, 59)), demo.ukOffsetSec(Date.UTC(2026, 2, 29, 1))], [0, 3600]);
    checkEq("and ends on the last Sunday of October",
            [demo.ukOffsetSec(Date.UTC(2026, 9, 25, 0, 59)), demo.ukOffsetSec(Date.UTC(2026, 9, 25, 1))], [3600, 0]);
    const sample = { sunrise: 1781148589, sunset: 1781210650, tz_offset: 3600, today_max: 15.6 };
    const out = demo.demoWeather(sample, t);
    check("demo mode replaces the frozen summer times", out.sunrise !== sample.sunrise && Math.abs(out.sunrise - s.sunrise) < 1800);
    check("and keeps the rest of the forecast", out.today_max === 15.6);
    check("without changing the sample itself", sample.sunrise === 1781148589);
    check("a real install's weather is returned untouched", real.demoWeather(sample, t) === sample);
    check("the hub feeds its weather through it",
          fs.readFileSync(path.join(PAGES, "index.html"), "utf8").includes("DashUI.demoWeather(await r.json())"));
}

done();
