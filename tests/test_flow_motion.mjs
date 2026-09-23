// Filename:    test_flow_motion.mjs
// Description: The power-flow diagram's motion (v3.38.0). The dots used to be
//              a CSS animation whose duration was rewritten on every poll,
//              which jumped every dot to a new place each time the power
//              changed. A frame loop now eases the speed, slows a reversing
//              flow through a stop, and stops itself when nothing moves.
//              Drives the REAL flowDiagram from dashboards-ui.js frame by
//              frame against a small stub DOM. Also checks chartRender, which
//              lets a refreshed chart ease to its new figures instead of
//              being destroyed and regrown.
// Author:      CliveS & Claude Opus 5.5
// Date:        23-09-2026
// Version:     1.0

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { check, done } from "./lib/check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "Dashboards.indigoPlugin", "Contents",
                                      "Resources", "static", "pages", "dashboards-ui.js"), "utf8");

function world(reduced) {
    const els = {};
    const mkEl = () => ({ style: {}, dataset: {}, textContent: "", isConnected: true, setAttribute() {}, getAttribute() { return null; } });
    const svg = { isConnected: true, querySelector: sel => { const m = /id="([^"]+)"/.exec(sel); return m ? (els[m[1]] = els[m[1]] || mkEl()) : null; } };
    const mount = { set innerHTML(v) { this._h = v; }, get innerHTML() { return this._h; }, querySelector: () => svg };
    const frames = [];
    const w = {
        document: { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} }, documentElement: {} },
        getComputedStyle: () => ({ getPropertyValue: () => "" }),
        matchMedia: () => ({ matches: reduced }),
        requestAnimationFrame: fn => { frames.push(fn); return frames.length; },
        setTimeout: () => 0, clearTimeout() {}, console,
    };
    w.window = w; w.globalThis = w;
    vm.createContext(w);
    vm.runInContext(SRC, w);
    const d = w.DashUI.flowDiagram(mount, { idPrefix: "t" });
    let t = 0;
    const run = (n, ms = 16) => { for (let i = 0; i < n && frames.length; i++) { t += ms; frames.shift()(t); } };
    return { d, els, frames, run, svg };
}

console.log("\na live leg moves, and speeds up smoothly");
{
    const W = world(false);
    W.d.update({ pv: 3000, home: 800, grid: 0, bat: 2000, soc: 50 });
    const pv = W.d._legs.pv;
    check("a frame is asked for", W.frames.length === 1);
    check("the solar leg runs towards the house (negative offset)", pv.target < 0);
    W.run(1); W.run(1);
    const early = Math.abs(pv.v);
    check("it does not start at full speed", early > 0 && early < Math.abs(pv.target) * 0.5, `v=${early}`);
    W.run(120);
    check("and reaches it", Math.abs(pv.v - pv.target) < 0.5, `v=${pv.v} target=${pv.target}`);
    check("the offset is written to the path", W.els["t-flow-pv"].style.strokeDashoffset !== undefined);
    check("the offset stays within one dot gap", Math.abs(parseFloat(W.els["t-flow-pv"].style.strokeDashoffset)) < 16);

    console.log("\nmore power, faster dots, no jump");
    const before = parseFloat(W.els["t-flow-pv"].style.strokeDashoffset);
    const v0 = pv.v;
    W.d.update({ pv: 7000, home: 800, grid: 0, bat: 2000, soc: 50 });
    W.run(1);
    const after = parseFloat(W.els["t-flow-pv"].style.strokeDashoffset);
    const step = Math.abs(((after - before) + 24) % 16 - 8);
    check("the next frame moves the dots by about one frame's worth", step <= Math.abs(pv.v) * 0.017 + 0.01, `step=${step}`);
    check("the speed is climbing, not snapped", Math.abs(pv.v) > Math.abs(v0) && Math.abs(pv.v) < Math.abs(pv.target));

    console.log("\na reversing flow slows through a stop");
    const bat = W.d._legs.bat;
    check("charging runs away from the hub", bat.v > 0);
    W.d.update({ pv: 7000, home: 800, grid: 0, bat: -2500, soc: 50 });
    const seen = [];
    for (let i = 0; i < 80; i++) { W.run(1); seen.push(bat.v); }
    check("it passes through the slow values on the way", seen.some(v => Math.abs(v) < 3));
    check("and ends up running the other way", bat.v < -5);

    console.log("\nnothing moving, no frames");
    W.d.update({ pv: 0, home: 0, grid: 0, bat: 0, soc: 50 });
    W.run(400);
    check("every leg comes to rest", Object.values(W.d._legs).every(L => L.v === 0));
    check("and the loop stops asking for frames", W.frames.length === 0);
    check("a dead leg fades out", W.els["t-flow-pv"].style.opacity === "0");

    console.log("\ntaken off the page, it stops for good");
    W.d.update({ pv: 3000, home: 0, grid: 0, bat: 0 });
    W.svg.isConnected = false;
    W.run(5);
    check("a detached diagram asks for no more frames", W.frames.length === 0);
}

console.log("\nreduced motion");
{
    const W = world(true);
    W.d.update({ pv: 3000, home: 800, grid: 500, bat: 0 });
    check("no frame loop at all", W.frames.length === 0);
    check("the leg still shows, as a solid line", W.els["t-flow-pv"].style.opacity === "1");
}

check("the CSS march is gone", !/fdg-march|animationDuration/.test(SRC));

console.log("\ncharts change rather than rebuild");
{
    const made = [], destroyed = [];
    function FakeChart(cv, cfg) { this.canvas = cv; this.config = { type: cfg.type }; this.data = cfg.data;
        this.options = cfg.options; this.updates = 0; cv._chart = this; made.push(this); }
    FakeChart.prototype.update = function () { this.updates++; };
    FakeChart.prototype.destroy = function () { destroyed.push(this); this.canvas._chart = null; };
    FakeChart.getChart = cv => cv._chart || null;
    const w = { document: { getElementById: () => null, createElement: () => ({ style: {} }), head: { appendChild() {} }, documentElement: {} },
                getComputedStyle: () => ({ getPropertyValue: () => "" }), matchMedia: () => ({ matches: false }),
                Chart: FakeChart, console };
    w.window = w; w.globalThis = w;
    vm.createContext(w); vm.runInContext(SRC, w);
    const cv = {};
    const cfg = (vals, n = 1) => ({ type: "bar", data: { labels: vals.map((_, i) => "t" + i),
        datasets: Array.from({ length: n }, () => ({ data: vals, backgroundColor: "red" })) }, options: {} });
    const a = w.DashUI.chartRender(cv, cfg([1, 2, 3]));
    check("the first draw makes a chart", made.length === 1 && a === made[0]);
    check("with the one shared motion", a.options.animation && a.options.animation.duration === 650);
    const b = w.DashUI.chartRender(cv, cfg([4, 5, 6]));
    check("new figures update the SAME chart", b === a && made.length === 1 && a.updates === 1);
    check("and it now holds them", JSON.stringify(a.data.datasets[0].data) === "[4,5,6]");
    check("nothing was destroyed", destroyed.length === 0);
    const c = w.DashUI.chartRender(cv, cfg([1, 2], 2));
    check("a different number of series rebuilds", c !== a && destroyed.includes(a) && made.length === 2);
    const w2 = Object.assign({}, w, { matchMedia: () => ({ matches: true }) });
    w2.window = w2; w2.globalThis = w2; vm.createContext(w2); vm.runInContext(SRC, w2);
    check("reduced motion: no animation", w2.DashUI.chartAnimation() === false);
}

done();
