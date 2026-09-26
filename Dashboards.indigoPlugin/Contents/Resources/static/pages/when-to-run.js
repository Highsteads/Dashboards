/*
  Filename:    when-to-run.js
  Description: The "When to run it" card on the Energy page (v3.34.0). Until
               then two pages answered the same question: Laundry (the
               cheapest time to run each metered appliance before a deadline)
               and Carbon (how clean the grid is now and over the next day).
               They are one card now. Each half hides itself when it has
               nothing to say: laundry without Appliance_Scheduler.py, carbon
               when its region is switched off, and the card when both are.
  Author:      CliveS & Claude Opus 5.5
  Date:        23-09-2026
  Version:     1.0
*/
(function (root) {
    "use strict";

    const DashUI = () => root.DashUI;
    const esc = (s) => DashUI().esc(s);
    const pad = (n) => String(n).padStart(2, "0");

    const POLL_MS = 60000;
    const STALE_AFTER_MS = 195000;         // three missed sixty-second polls, plus slack
    const DEADLINES = [["12:00", "by noon"], ["14:00", "by 2pm"], ["16:00", "by 4pm"],
                       ["19:00", "by 7pm"], ["22:00", "by 10pm"], ["", "no deadline"]];

    // ── words ───────────────────────────────────────────────────────────
    /** "1:30pm", "9am" — the way a person says a time. */
    function clock(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        const h = d.getHours() % 12 || 12, m = d.getMinutes();
        return h + (m ? ":" + pad(m) : "") + (d.getHours() < 12 ? "am" : "pm");
    }
    /** How stale the data is. Its own clock: a poll that has died cannot
        report that it has died. */
    function freshness(ageMs) {
        if (!(ageMs >= 0) || ageMs <= STALE_AFTER_MS) return { stale: false, text: "" };
        return { stale: true, text: "not updating for " + DashUI().ago(ageMs, { words: true }) };
    }

    // ── laundry ─────────────────────────────────────────────────────────
    function currentDeadline(a) {
        if (!a || !a.deadline) return null;
        const d = new Date(a.deadline);
        return pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
    function chipsFor(a) {
        const cur = currentDeadline(a);
        return '<div class="wr-sub">Finish by</div><div class="chips">' + DEADLINES.map(([v, label]) =>
            '<button type="button" data-key="' + esc(a.key) + '" data-v="' + esc(v) + '" aria-pressed="' +
            (v === cur ? "true" : "false") + '">' + esc(label) + "</button>").join("") + "</div>";
    }
    function splitFor(a) {
        const total = (a.appliance && a.appliance.kwh) || 0;
        if (!total || a.state !== "planned") return "";
        const s = a.solar_kwh || 0, b = a.battery_kwh || 0, g = a.grid_kwh || 0;
        const pc = (v) => Math.max(0, Math.round(v / total * 1000) / 10);
        return '<div class="wr-sub">Where its ' + total.toFixed(2) + ' kWh would come from</div>' +
            '<div class="split"><span class="s" style="width:' + pc(s) + '%"></span><span class="b" style="width:' +
            pc(b) + '%"></span><span class="g" style="width:' + pc(g) + '%"></span></div>' +
            '<div class="legend"><span><i style="background:var(--on-color)"></i>Sun ' + pc(s) + '%</span>' +
            '<span><i style="background:var(--accent)"></i>Battery ' + pc(b) + '%</span>' +
            '<span><i style="background:var(--warn-color,#ff9f0a)"></i>Grid ' + pc(g) + "%</span></div>";
    }
    function shapeCard(a) {
        const opts = (a && a.options) || [];
        if (opts.length < 2) return "";
        const worst = Math.max.apply(null, opts.map(o => o.grid_kwh || 0));
        const head = '<summary>Every half hour between now and the deadline</summary>';
        // Forty-five identical "free" rows tell the reader nothing. Say it once.
        if (worst <= 0.01) {
            return '<details>' + head + '<p class="note">All ' + opts.length + ' of them come out the same: ' +
                'nothing off the grid whenever you run it. The battery can cover a run right through to the ' +
                'deadline, so there is nothing to choose between them.</p></details>';
        }
        const rows = opts.map(o => {
            const g = o.grid_kwh || 0;
            const w = worst > 0 ? Math.round(g / worst * 100) : 0;
            const cls = "slot" + (g <= 0.01 ? " free" : "") + (o.start === a.start ? " pick" : "");
            return '<div class="' + cls + '"><span class="t">' + esc(clock(o.start)) + '</span><span class="track">' +
                '<span class="fill" style="width:' + w + '%"></span></span><span class="p">' +
                (g <= 0.01 ? "free" : (o.cost_p || 0).toFixed(0) + "p") + "</span></div>";
        }).join("");
        return '<details>' + head + rows + '<p class="note">The bar is how much would come off the grid. ' +
            'Green means none of it would.</p></details>';
    }
    function applianceBlock(a) {
        const msg = a.message || "";
        const first = msg.split(". ")[0], rest = msg.split(". ").slice(1).join(". ");
        let html = '<div class="wr-appl"><div class="wr-verdict">' + esc(first) + (first ? "." : "") + "</div>" +
            (rest ? '<div class="wr-detail">' + esc(rest) + "</div>" : "");
        // Chips only where a deadline means anything: a machine mid-cycle, or
        // one not yet run enough times to be measured, has nothing to schedule.
        if (a.state === "planned" || a.state === "no_plan") html += chipsFor(a);
        if (a.state === "planned") html += splitFor(a) + shapeCard(a);
        const ap = a.appliance || {};
        if (ap.measured_from) {
            const title = String(a.label || "the appliance").replace(/^the /, "");
            html += '<p class="note">' + esc(title.charAt(0).toUpperCase() + title.slice(1)) + ": " +
                esc(String(ap.minutes)) + " minutes and " + esc(String(ap.kwh)) + " kWh, measured from " +
                esc(ap.measured_from) + " of its own, not the manual.</p>";
        }
        return html + "</div>";
    }
    function laundryHtml(plan) {
        // A refusal (ok:false, answered with HTTP 200) carries the real reason:
        // no plan yet, or SigenEnergyManager absent. It is not "nothing metered".
        if (plan && plan.ok === false) {
            return '<div class="wr-appl"><div class="wr-verdict">No laundry plan yet.</div><p class="note">' +
                esc(plan.error || "The plugin did not say why.") + "</p></div>";
        }
        const list = (plan && plan.appliances) || [];
        if (!list.length) {
            return '<div class="wr-appl"><div class="wr-verdict">Nothing is metered yet.</div><p class="note">' +
                esc((plan && plan.note) || "Put a metering plug on an appliance and add an Appliance Monitor device pointed at it.") +
                " Once it has run about five cycles this card can say when to run it, from that machine's own timings.</p></div>";
        }
        return list.map(applianceBlock).join("");
    }

    // ── carbon ──────────────────────────────────────────────────────────
    const IDX_COLOUR = { "very low": "#34c759", "low": "#8ccf3f", "moderate": "#ff9500", "high": "#ff6b35", "very high": "#ff453a" };
    const idxColour = (idx) => IDX_COLOUR[String(idx || "").toLowerCase()] || "#86868b";
    function localHM(iso) {
        const d = new Date(iso);
        if (isNaN(d)) return String(iso || "");
        return clock(iso) + (d.getDate() !== new Date().getDate() ? " tomorrow" : "");
    }
    function carbonHtml(d) {
        const carbon = (d && d.carbon) || {}, adv = (d && d.advice) || {};
        const cur = carbon.current || {};
        const warming = !!carbon.warming;
        const down = (!!carbon.error || cur.intensity == null) && !warming;
        const lvl = adv.level === "wait" ? "wait" : adv.level === "neutral" ? "neutral" : "good";
        const tag = adv.action === "run_now" ? "Run now" : adv.action === "wait_carbon" ? "Wait" :
                    adv.action === "anytime" ? "Any time" : "Advice";
        const c = idxColour(cur.index);
        let html = '<div class="wr-carbon-head"><span class="wr-tag ' + lvl + '">' + esc(tag) + "</span>" +
            '<div><div class="wr-verdict">' + esc(adv.headline || "—") + "</div>" +
            (adv.detail ? '<div class="wr-detail">' + esc(adv.detail) + "</div>" : "") + "</div></div>";
        html += '<div class="wr-gauges"><div class="wr-gauge"><div class="l">Grid carbon' +
            (carbon.region ? " · " + esc(carbon.region) : "") + '</div><div class="v">' +
            (down || cur.intensity == null ? "—" : esc(Math.round(cur.intensity))) + '<span class="u"> gCO₂/kWh</span></div>' +
            (warming ? '<div class="s">fetching grid data…</div>' : down ? '<div class="s">grid data unavailable</div>' :
             '<div class="s"><span class="idx" style="color:' + c + ";background:" + c + '22">' + esc(cur.index || "") + "</span></div>") +
            "</div>" + (carbon.best ? '<div class="wr-gauge"><div class="l">Cleanest in the next day</div><div class="v">' +
            esc(localHM(carbon.best.from)) + "</div></div>" : "") + "</div>";
        if ((carbon.forecast || []).length) html += '<div class="wr-chart"><canvas></canvas></div>';
        const mix = (carbon.mix || []).filter(m => Number(m.perc) > 0).sort((a, b) => b.perc - a.perc);
        if (mix.length) {
            const FUEL = { solar: "#ff9f0a", wind: "#34c759", hydro: "#5ac8fa", nuclear: "#5856d6", biomass: "#a3d900",
                           gas: "#ff6b35", coal: "#8e8e93", imports: "#64d2ff", other: "#86868b" };
            html += "<details><summary>Where the grid's power is coming from</summary>" + mix.map(m =>
                '<div class="mixrow"><span class="ml">' + esc(m.fuel) + '</span><span class="mt"><span class="mf" style="width:' +
                Math.min(100, Number(m.perc)) + "%;background:" + (FUEL[m.fuel] || "#86868b") + '"></span></span><span class="mv">' +
                Number(m.perc).toFixed(1) + "%</span></div>").join("") + "</details>";
        }
        html += '<details><summary>How this is worked out</summary><p class="note">Spare solar comes first (free, and ' +
            "running a load soaks up what would otherwise be exported), then a genuinely clean grid, then waiting " +
            "for the cleanest window in the next 16 hours. On a flat tariff the cost is much the same whenever you " +
            "run, so carbon and solar decide; on a time-of-use tariff the price changes through the day, which the " +
            "laundry plan above already weighs. Grid data: the free UK Carbon Intensity API.</p></details>";
        return html;
    }

    // ── the card ────────────────────────────────────────────────────────
    function mount(opts) {
        const cfg = opts.cfg || root.INDIGO_CONFIG || {};
        const card = opts.card, label = opts.label;
        const lEl = opts.laundryEl, cEl = opts.carbonEl, fEl = opts.freshEl;
        const wantLaundry = !((cfg.scripts || {}).laundry === false);
        // Carbon also needs SigenEnergyManager (3.48.5): the advice weighs its
        // solar and tariff, and the plugin will not fetch it without one.
        const wantCarbon = cfg.carbon !== false && cfg.sigenAvailable !== false;
        if (!wantLaundry && !wantCarbon) {
            if (card) card.hidden = true;
            if (label) label.hidden = true;
            return null;
        }
        if (!wantLaundry) lEl.hidden = true;
        if (!wantCarbon) cEl.hidden = true;
        let plan = null, busy = false, lastGood = 0, chart = null, chartSig = "", carbonGood = false;

        function markFresh() {
            if (!fEl) return;
            const f = freshness(lastGood ? Date.now() - lastGood : NaN);
            fEl.textContent = f.text;
            fEl.classList.toggle("stale", f.stale);
        }
        function drawLaundry() {
            lEl.innerHTML = '<div class="wr-head">Laundry</div>' + laundryHtml(plan);
            lEl.querySelectorAll(".chips button").forEach(btn =>
                btn.addEventListener("click", () => setDeadline(btn.dataset.key, btn.dataset.v, btn)));
        }
        async function loadLaundry() {
            try {
                const p = await DashUI().message("laundryPlan");
                if (p && p.ok === false) {
                    // Not fresh data: keep a good plan already on screen (it goes
                    // stale by its age), and show the reason only when there is none.
                    if (!plan || plan.ok === false) { plan = p; drawLaundry(); }
                } else {
                    plan = p;
                    lastGood = Date.now();
                    drawLaundry();
                }
            } catch (e) {
                if (!plan) lEl.innerHTML = '<div class="wr-head">Laundry</div><p class="note">Could not reach the plugin: ' + esc(e.message) + "</p>";
            }
            markFresh();
        }
        async function setDeadline(key, hhmm, btn) {
            if (busy) return;
            busy = true;
            lEl.querySelectorAll(".chips button").forEach(b => { b.disabled = true; });
            if (btn) btn.textContent = "Working…";
            try {
                const d = await DashUI().message("laundryDeadline", { appliance: key, deadline: hhmm });
                if (d && d.ok && d.pending) {
                    // Replanning on a worker: wait until the plan's "generated" stamp moves.
                    const was = d.plan && d.plan.generated;
                    for (let i = 0; i < 20; i++) {
                        await new Promise(r => setTimeout(r, 1000));
                        const p = await DashUI().message("laundryPlan");
                        if (p && p.generated && p.generated !== was) { plan = p; lastGood = Date.now(); break; }
                    }
                } else if (d && d.ok && d.plan) { plan = d.plan; lastGood = Date.now(); }
            } catch (e) {
                console.warn("when-to-run deadline: " + e.message);
            } finally {
                busy = false;
                drawLaundry();
            }
        }
        async function loadCarbon() {
            let d;
            try { d = await DashUI().message("carbonAdvisor"); }
            catch (e) {
                // Keep the last good card (a plugin restart fails every poll for a
                // moment) and say it is out of date; the error only when there is
                // nothing to keep.
                if (!carbonGood) {
                    cEl.innerHTML = '<div class="wr-head">Grid carbon</div><p class="note">Could not reach the carbon data: ' + esc(e.message) + "</p>";
                } else {
                    const head = cEl.querySelector(".wr-head");
                    if (head) head.textContent = "Grid carbon · not updated: " + e.message;
                    cEl.classList.add("stale");
                }
                return;
            }
            carbonGood = true;
            cEl.classList.remove("stale");
            cEl.innerHTML = '<div class="wr-head">Grid carbon</div>' + carbonHtml(d);
            drawChart(((d.carbon || {}).forecast || []).slice(0, 48), (d.carbon || {}).best);
        }
        function drawChart(fc, best) {
            const cv = cEl.querySelector(".wr-chart canvas");
            if (!cv || !fc.length || typeof root.Chart === "undefined") return;
            const sig = fc.map(e => e.from + e.intensity).join(",");
            if (chart && chartSig === sig && root.Chart.getChart(cv)) return;
            chartSig = sig;
            const bestFrom = best && best.from;
            const muted = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary").trim() || "#86868b";
            chart = DashUI().chartRender(cv, {
                type: "bar",
                data: { labels: fc.map(e => localHM(e.from)), datasets: [{ data: fc.map(e => e.intensity),
                    backgroundColor: fc.map(e => idxColour(e.index)), borderRadius: 3,
                    borderColor: fc.map(e => (e.from === bestFrom ? muted : "transparent")),
                    borderWidth: fc.map(e => (e.from === bestFrom ? 2 : 0)),
                    categoryPercentage: 1, barPercentage: 0.9 }] },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { callbacks: {
                        label: it => it.raw + " gCO₂/kWh (" + fc[it.dataIndex].index + ")" } } },
                    scales: {
                        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 7, color: muted, font: { size: 10 } } },
                        y: { beginAtZero: true, grid: { color: "rgba(128,128,128,.15)" }, ticks: { color: muted, font: { size: 10 }, maxTicksLimit: 4 } },
                    },
                },
            });
        }
        if (wantLaundry) DashUI().poll(loadLaundry, POLL_MS);
        if (wantCarbon) DashUI().poll(loadCarbon, POLL_MS);
        const t = setInterval(markFresh, 5000);
        return { stop() { clearInterval(t); } };
    }

    root.WhenToRun = { mount, _t: { clock, freshness, chipsFor, splitFor, shapeCard, applianceBlock, laundryHtml,
                                    carbonHtml, idxColour, localHM, DEADLINES } };
})(typeof window !== "undefined" ? window : globalThis);
