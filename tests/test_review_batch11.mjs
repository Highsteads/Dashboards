// Filename:    test_review_batch11.mjs
// Description: Eleventh group from the 25/26-Nov-2026 review (3.73.13), the
//              Timeline page:
//                - "today" and "now" came from the reader's device, so a
//                  phone in another time zone saw a day the house had not
//                  reached, headed Today;
//                - the Chart view's time axis was one equal step per point,
//                  its on-percentage counted points, not time, and a state
//                  that had not changed read "Nothing recorded";
//                - a device that stopped being recorded while on was drawn
//                  on all day, every day, with nothing to say since when;
//                - the Nights view showed a file the watch stopped writing
//                  days ago as "Tonight".
// Author:      CliveS & Claude Fable 5.2
// Date:        26-11-2026
// Version:     1.0
//
// Run: node tests/test_review_batch11.mjs   (exit 0 = pass)

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, checkEq, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGES = path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents", "Resources", "static", "pages");
const read = f => fs.readFileSync(path.join(PAGES, f), "utf8");
const tl = read("timeline.html");
const grab = (src, name) => { const i = src.indexOf("function " + name + "("); if (i < 0) throw new Error("not found: " + name); let d = 0;
    for (let j = src.indexOf("{", i); j < src.length; j++) { if (src[j] === "{") d++; else if (src[j] === "}" && --d === 0) return src.slice(i, j + 1); } };

console.log("the house's clock");
{
    const mk = cfg => { const win = { setTimeout, clearTimeout, setInterval, clearInterval, Date, Math, JSON, Promise, AbortController, Intl, INDIGO_CONFIG: cfg };
        win.window = win; vm.createContext(win); vm.runInContext(read("dashboards-ui.js"), win); return win.DashUI.serverNow; };
    const at = Date.UTC(2026, 11, 3, 13, 30, 0);            // 1.30pm in the UK on 3 December
    checkEq("the house is in London", mk({ serverTz: "Europe/London" })(at), { ymd: "2026-12-03", min: 13 * 60 + 30, known: true });
    checkEq("in summer it is an hour on", mk({ serverTz: "Europe/London" })(Date.UTC(2026, 6, 1, 23, 30, 0)),
            { ymd: "2026-07-02", min: 30, known: true });
    checkEq("an offset alone will do", mk({ serverUtcOffsetMin: 60 })(Date.UTC(2026, 6, 1, 23, 30, 0)).ymd, "2026-07-02");
    checkEq("with nothing known, this device's clock is used and it says so", mk({})(at).known, false);
}

console.log("\nDay view: today is the house's today");
check("the page starts on the house's date", /let selDate = houseToday\(\);/.test(tl));
check("nothing on the page takes today from a bare new Date() any more",
      !/ymd\(new Date\(\)\)/.test(tl) && !/selDate = new Date\(\)/.test(tl));
check("now is the house's minute", /const hn = houseNow\(\);\s*const isToday = ymd\(selDate\) === hn\.ymd;\s*const nowMin = isToday \? hn\.min : 1440;/.test(tl));
{
    const c = vm.createContext({ console, window: { DashUI: { serverNow: () => ({ ymd: "2026-12-03", min: 810 }) } } });
    c.DashUI = c.window.DashUI;
    vm.runInContext("function pad(n){ return String(n).padStart(2,'0'); }" + grab(tl, "ymd") + grab(tl, "houseNow") + grab(tl, "houseToday")
        + "\nglobalThis.out = [houseNow().ymd, ymd(houseToday()), houseToday().getHours()];", c);
    checkEq("a phone in Sydney still opens on the house's 3 December", Array.from(c.out), ["2026-12-03", "2026-12-03", 12]);
}

console.log("\nDay view: a span the day opened with");
{
    const c = vm.createContext({ console, Number });
    vm.runInContext("const CARRY_OLD_DAYS = 7;" + grab(tl, "carriedSince") + grab(tl, "historyStaleWords")
        + "\nglobalThis.C = carriedSince; globalThis.H = historyStaleWords;", c);
    const day = new Date(2026, 10, 26).getTime() / 1000;
    const since = d => new Date(2026, 10, d, 21, 0).getTime() / 1000;
    checkEq("on since last night: said, not doubted", [c.C({ onSince: since(25) }, [0, 600], day).old, /on since 25 Nov$/.test(c.C({ onSince: since(25) }, [0, 600], day).words)], [false, true]);
    const old = c.C({ onSince: since(12) }, [0, 1440], day);
    checkEq("on since a fortnight ago: hatched, and it says nothing was recorded since", [old.old, /on since 12 Nov, nothing recorded since/.test(old.words)], [true, true]);
    checkEq("a span that began during the day says nothing", c.C({ onSince: since(12) }, [300, 600], day).words, "");
    checkEq("a device with no carried state says nothing", c.C({}, [0, 600], day).words, "");
    check("the span is drawn with it", /class="seg\$\{since\.old \? " old" : ""\}"/.test(tl) && /#view-day \.seg\.old\{/.test(tl));
    checkEq("a history file written today: no warning", c.H(3600), "");
    check("one last written three days ago is said", /last written to 3 days ago/.test(c.H(3 * 86400 + 5)));
    check("the Day view shows it", /const staleDb = historyStaleWords\(DAY\.historyAgeSeconds\);/.test(tl));
}

console.log("\nChart view: to scale, from the left edge to now");
{
    const ctx = { console, Date, Promise, Object, JSON, Math, String, Number, isFinite, parseFloat,
        document: { documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }),
        DashUI: { esc: s => String(s) } };
    ctx.window = ctx; vm.createContext(ctx);
    vm.runInContext(read("timeline-views.js"), ctx);
    const T = ctx.TimelineViews._t;
    const now = 1_800_000_000, H = 3600;
    const lamp = T.chartSeries({ now, hours: 24, points: [], before: { t: now - 5 * 86400, v: 1 } }, now);
    checkEq("a lamp left on for five days is a line across the whole day, not 'Nothing recorded'",
            Array.from(lamp.pts, p => [p.t - now, p.avg]), [[-24 * H, 1], [0, 1]]);
    checkEq("and it knows when that was recorded", lamp.lastAt, now - 5 * 86400);
    checkEq("it was on for all of it", T.onShare(lamp.pts), 1);
    checkEq("no rows and nothing before: nothing to draw", T.chartSeries({ now, hours: 24, points: [] }, now).pts.length, 0);
    // On from the start, off for one minute five times, then on: 6 changes in 24 h.
    const flick = [];
    for (let i = 0; i < 5; i++) { flick.push({ t: now - 12 * H + i * 120, avg: 0, min: 0, max: 0 }); flick.push({ t: now - 12 * H + i * 120 + 60, avg: 1, min: 1, max: 1 }); }
    const busy = T.chartSeries({ now, hours: 24, points: flick, before: { t: now - 30 * H, v: 1 } }, now);
    const share = T.onShare(busy.pts);
    check("five one-minute offs in a day is on for nearly all of it, weighed by time", share > 0.99 && share < 1, String(share));
    checkEq("the line starts at the left edge and runs to now", [busy.pts[0].t, busy.pts[busy.pts.length - 1].t], [now - 24 * H, now]);
    const temp = T.chartSeries({ now, hours: 6, bucketSeconds: 60, points: [{ t: now - 6 * H - 30, avg: 19, min: 19, max: 19 }, { t: now - H, avg: 21, min: 20, max: 22 }] }, now);
    checkEq("a bucket that starts just before the range is drawn at the edge", temp.pts[0].t, now - 6 * H);
    checkEq("the last reading is carried to now", [temp.pts[temp.pts.length - 1].t, temp.pts[temp.pts.length - 1].avg], [now, 21]);
    checkEq("and its age is known", temp.lastAt, now - H);
    const start = new Date(2026, 10, 26, 2, 40).getTime(), end = new Date(2026, 10, 26, 8, 40).getTime();
    checkEq("six hours: a tick on each hour", Array.from(T.timeTicks(start, end), v => new Date(v).getHours() + ":" + new Date(v).getMinutes()),
            ["3:0", "4:0", "5:0", "6:0", "7:0", "8:0"]);
    const d24 = T.timeTicks(end - 24 * 3600000, end).map(v => new Date(v).getHours());
    check("a day: every three hours, on the clock", d24.every(h => h % 3 === 0) && d24.length === 8, JSON.stringify(d24));
    const d7 = T.timeTicks(end - 168 * 3600000, end).map(v => new Date(v).getHours());
    check("a week: each midnight", d7.every(h => h === 0) && d7.length === 7, JSON.stringify(d7));
    const src = read("timeline-views.js");
    check("the axis is a real time axis", /x: \{ type: "linear", min: S\.start \* 1000, max: S\.end \* 1000/.test(src));
    check("the last figure says when it was recorded", /const sinceTxt = \(S\.lastAt && root\.DashUI\.ago\)/.test(src));
}

console.log("\nNights view: a file the watch has stopped writing");
{
    const ctx = { console, Date, Promise, Object, JSON, Math, String, Number, isFinite, parseFloat,
        document: { documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }), DashUI: { esc: s => String(s) } };
    ctx.window = ctx; vm.createContext(ctx);
    vm.runInContext(read("timeline-views.js"), ctx);
    const A = ctx.TimelineViews._t.presenceAge;
    checkEq("built half a minute ago: live", A({ ageSeconds: 27, generatedLocal: "2026-11-26 07:49:50" }).old, false);
    const old = A({ ageSeconds: 3 * 86400, generatedLocal: "2026-11-22 21:40:10" });
    check("built on Sunday evening: says so, with the day", old.old && /^Last built Sunday 22 November at 21:40; the presence watch has stopped$/.test(old.words), old.words);
    checkEq("a reply with no age (an older plugin) is taken as live", A({ generatedLocal: "2026-11-22 21:40:10" }).old, false);
    const src = read("timeline-views.js");
    check("no now-line is drawn over an old file", /if \(STALE\) return "";/.test(src));
    check("the night is named by its date, not 'Tonight'", /\$\("\.n-dlabel"\)\.textContent = STALE\s*\? new Date\(selDate \+ "T00:00:00"\)/.test(src));
    check("and the header says when it was built", /setStatus\(STALE \? age\.words : "Updated "/.test(src));
}

done();
