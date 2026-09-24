/*
  Filename:    timeline-views.js
  Description: The three views Timeline gained in v3.33.0, when it became the
               one page for the house's recorded history:
                 Nights — per-night presence-sensor tracks (was presence.html)
                 Chart  — graph any recorded state (was history.html, "Graphs")
                 Diary  — locks, doors, leaks and restarts (was Activity's diary)
               Each view is mounted once, the first time its tab is opened,
               and polls only while it is on screen. timeline.html owns the
               tabs, the Day view and the status line.
  Author:      CliveS & Claude Opus 5.5
  Date:        23-09-2026
  Version:     1.0
*/
(function (root) {
    "use strict";

    const I = (n) => (root.DashIcons ? root.DashIcons.svg(n) : "");
    const esc = (s) => root.DashUI.esc(s);
    const pad = (n) => String(n).padStart(2, "0");

    function joinLabels(names) {
        if (names.length <= 1) return names[0] || "";
        if (names.length === 2) return `${names[0]} and ${names[1]}`;
        return names.slice(0, -1).join(", ") + ` and ${names[names.length - 1]}`;
    }

    // ── Nights ─────────────────────────────────────────────────────────
    // Presence_Watch.py builds these from the SQL Logger history: one card
    // per room it watches, with a track per sensor, a combined track that
    // turns amber wherever the sensors disagree, a movement strip and a
    // seven-night strip to jump between nights.
    function Nights(el, setStatus) {
        let DATA = null, selDate = null, poller = null;
        el.innerHTML = `
            <section class="card">
                <div class="datepick">
                    <button class="n-prev" aria-label="Older night">&lsaquo;</button>
                    <div><div class="lab n-dlabel">&mdash;</div><div class="sub n-dsub"></div></div>
                    <button class="n-next" aria-label="Newer night">&rsaquo;</button>
                </div>
                <div class="legend">
                    <span><span class="sw" style="background:var(--on-color)"></span>all detected</span>
                    <span><span class="sw" style="background:var(--amber)"></span>one dropped</span>
                    <span><span class="sw" style="background:var(--track)"></span>clear</span>
                    <span><span class="sw" style="background:var(--move);opacity:0.6"></span>movement</span>
                </div>
            </section>
            <div class="n-rooms"></div>
            <div class="empty n-empty" hidden></div>`;
        const $ = (sel) => el.querySelector(sel);

        const clock = (m) => { m = ((Math.round(m) % 1440) + 1440) % 1440; return pad(Math.floor(m / 60)) + ":" + pad(m % 60); };
        const minToClock = (room, m) => clock(room.window.startMinOfDay + m);
        const dur = (m) => { m = Math.round(m); const h = Math.floor(m / 60), mm = m % 60; return h ? (mm ? h + "h " + mm + "m" : h + "h") : mm + "m"; };
        const pct = (v, span) => 100 * v / span;
        const seg = (l, w, colour, z) => `<span class="seg" style="left:${l.toFixed(2)}%;width:${Math.max(w, 0.3).toFixed(2)}%;background:${colour}${z ? ";z-index:2" : ""}"></span>`;
        const segHtml = (segs, span, colour) => segs.map(s => seg(pct(s[0], span), pct(s[1] - s[0], span), colour)).join("");
        const bothHtml = (both, span) => segHtml(both.green || [], span, "var(--on-color)") +
            (both.amber || []).map(s => seg(pct(s[0], span), pct(s[1] - s[0], span), "var(--amber)", true)).join("");
        function activityHtml(act, span) {
            if (!act || !act.points || !act.points.length) return "";
            const bw = pct(act.bucketMin, span);
            return act.points.map(p => `<span class="abar" style="left:${pct(p.t, span).toFixed(2)}%;width:${Math.max(bw - 0.3, 0.6).toFixed(2)}%;height:${Math.max(12, Math.round(100 * p.c / act.max))}%"></span>`).join("");
        }
        function axisHtml(room) {
            const span = room.window.spanMin, step = span <= 320 ? 60 : 120, ticks = [];
            for (let o = 0; o <= span - 1; o += step) ticks.push(o);
            if (ticks[ticks.length - 1] !== span) ticks.push(span);
            return `<div class="axis">` + ticks.map(o => `<span>${minToClock(room, o)}</span>`).join("") + `</div>`;
        }
        function nowFutureHtml(night, span) {
            if (!night.live || night.nowMin == null) return "";
            const l = Math.min(100, pct(night.nowMin, span));
            return `<span class="future" style="left:${l.toFixed(2)}%"></span><span class="nowline" style="left:${l.toFixed(2)}%"></span>`;
        }
        const trackRow = (label, segs, night, span, bold, big) =>
            `<div class="trow"><span class="rlab ${bold ? "bold" : ""}">${label}</span><div class="trk ${big ? "big" : ""}">${segs}${nowFutureHtml(night, span)}</div></div>`;
        const mc = (label, val) => `<div class="mc"><div class="l">${label}</div><div class="v">${val}</div></div>`;
        function shortLabel(d) {
            const lab = DATA.labels[d] || d;
            if (lab === "Tonight") return "Tonight";
            if (lab === "Last night") return "Last";
            return lab.replace(/^(\w\w)\w*\s/, "$1 ");
        }
        function stripHtml(room) {
            const span = room.window.spanMin;
            const dates = DATA.dates.filter(d => room.byDate[d]).slice(0, 7);
            if (dates.length < 2) return "";
            return `<div class="striplab">Last ${dates.length} nights</div>` + dates.map(d =>
                `<div class="srow ${d === selDate ? "sel" : ""}" data-date="${esc(d)}"><span class="d">${esc(shortLabel(d))}</span>` +
                `<div class="mini">${bothHtml(room.byDate[d].both, span)}</div></div>`).join("");
        }
        function renderRoom(room) {
            const span = room.window.spanMin;
            const night = room.byDate[selDate];
            let html = `<section class="card"><div class="roomhead"><h2>${esc(room.title)}</h2>` +
                       `<span class="win">${esc(room.window.start)}&ndash;${esc(room.window.end)}</span></div>`;
            if (!night) {
                return html + `<div class="empty">No data for this night yet: the ${esc(room.window.start)}&ndash;${esc(room.window.end)} window has not run.</div>` +
                       stripHtml(room) + `</section>`;
            }
            const order = room.sensorOrder, labels = room.sensorLabels, status = room.sensorStatus || {};
            order.forEach(sid => {
                const st = night.stats[sid] || {};
                const why = status[sid] && status[sid] !== "ok" ? ` <span class="muted">(${esc(status[sid])})</span>` : "";
                html += trackRow(esc(labels[sid]) + why, st.hasData ? segHtml(night.tracks[sid] || [], span, "var(--on-color)") : "", night, span);
            });
            html += trackRow(order.length > 2 ? `All ${order.length}` : "Both", bothHtml(night.both, span), night, span, true, true);
            if (night.activity) html += `<div class="trow"><span class="rlab">moves</span><div class="actstrip">${activityHtml(night.activity, span)}</div></div>`;
            html += axisHtml(room);
            const s = night.summary;
            html += `<div class="mgrid">` +
                mc("First seen", s.firstSeenMin != null ? minToClock(room, s.firstSeenMin) : "&mdash;") +
                mc("Last clear", s.lastClearMin != null ? minToClock(room, s.lastClearMin) : "&mdash;") +
                mc("Occupied", s.occMin ? dur(s.occMin) + " &middot; " + s.occPct + "%" : "&mdash;") +
                mc(s.bothPresent ? "Disagreed" : "Sensors",
                   s.bothPresent ? (s.disagreeMin ? dur(s.disagreeMin) : "0m") : `${s.reportingCount ?? 1} of ${s.sensorCount ?? order.length}`) +
                `</div><div class="sens">`;
            order.forEach(sid => {
                const st = night.stats[sid] || {};
                html += st.hasData
                    ? `<div><b>${esc(labels[sid])}</b> &middot; ${dur(st.occMin)} (${st.occPct}%) &middot; ${st.transitions} changes &middot; longest ${dur(st.longestHold)}</div>`
                    : `<div><b>${esc(labels[sid])}</b> &middot; no data yet</div>`;
            });
            html += `</div>`;
            if (night.sleep) {
                const sl = night.sleep;
                html += `<div class="mgrid">` + mc("Settled", minToClock(room, sl.settledMin)) + mc("Up", minToClock(room, sl.upMin)) +
                        mc("In bed", dur(sl.inBedMin)) + mc("Wakeups", "" + sl.wakeups) + `</div>`;
            }
            (night.dropouts || []).forEach(d => {
                html += `<div class="callout warn"><span>${I("warn")}</span><span><b>${esc(d.dropped)}</b> dropped ` +
                        `${minToClock(room, d.startMin)}&ndash;${minToClock(room, d.endMin)} (${d.mins}m) while <b>${esc(d.held)}</b> held.</span></div>`;
            });
            const missing = order.filter(sid => !(night.stats[sid] || {}).hasData);
            if (s.bothPresent && !(night.dropouts || []).length) {
                html += `<div class="callout ok"><span>${I("check")}</span><span>${order.length > 2 ? `All ${order.length} sensors` : "Both sensors"} agreed all night, with no dropouts.</span></div>`;
            }
            if (missing.length) {
                html += `<div class="callout info"><span>&#9432;</span><span>${order.length - missing.length} of ${order.length} sensors reporting: ` +
                        `<b>${esc(joinLabels(missing.map(sid => labels[sid])))}</b> ${missing.length === 1 ? "has" : "have"} no data for this night yet.</span></div>`;
            }
            return html + stripHtml(room) + `</section>`;
        }
        function render() {
            const empty = $(".n-empty");
            if (!DATA || !DATA.dates || !DATA.dates.length) {
                empty.hidden = false; empty.textContent = "No presence data yet."; return;
            }
            empty.hidden = true;
            if (!selDate || DATA.dates.indexOf(selDate) < 0) selDate = DATA.dates[0];
            const idx = DATA.dates.indexOf(selDate);
            $(".n-dlabel").textContent = DATA.labels[selDate] || selDate;
            $(".n-dsub").textContent = new Date(selDate + "T00:00:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
            $(".n-next").disabled = idx <= 0;
            $(".n-prev").disabled = idx >= DATA.dates.length - 1;
            // Every room the script watches, in the order it wrote them. The
            // old page named two rooms of one house and drew nothing else.
            $(".n-rooms").innerHTML = Object.keys(DATA.rooms || {}).map(k => renderRoom(DATA.rooms[k])).join("");
            el.querySelectorAll(".srow").forEach(r => r.addEventListener("click", () => { selDate = r.dataset.date; render(); }));
            setStatus("Updated " + (DATA.generatedLocal ? DATA.generatedLocal.slice(11, 16) : ""));
        }
        $(".n-prev").addEventListener("click", () => { const i = DATA.dates.indexOf(selDate); if (i < DATA.dates.length - 1) { selDate = DATA.dates[i + 1]; render(); } });
        $(".n-next").addEventListener("click", () => { const i = DATA.dates.indexOf(selDate); if (i > 0) { selDate = DATA.dates[i - 1]; render(); } });
        async function load() {
            try {
                const d = await root.DashUI.message("presenceData");
                if (!d || d.ok === false) throw new Error(d && d.error ? d.error : "no data");
                DATA = d;
                render();
            } catch (e) {
                setStatus("No data");
                const empty = $(".n-empty");
                empty.hidden = false;
                empty.textContent = "Couldn't load the nights: the Presence_Watch.py script may not have run yet.";
            }
        }
        return {
            show() { if (!poller) poller = root.DashUI.poll(load, 120000); else if (DATA) render(); },
            hide() { if (poller) { poller.stop(); poller = null; } },
        };
    }

    // ── Chart ──────────────────────────────────────────────────────────
    // Anything the SQL Logger records, over 6 hours to 30 days. The Day view
    // and the Nights view link here with a device already chosen.
    function Chart_(el, setStatus) {
        el.innerHTML = `
            <section class="card">
                <div class="pickers">
                    <div><label for="c-dev">Device</label>
                        <input type="text" id="c-dev" list="c-devlist" placeholder="Start typing a device name&hellip;">
                        <datalist id="c-devlist"></datalist></div>
                    <div><label for="c-state">Recorded state</label>
                        <select id="c-state" disabled><option>&mdash;</option></select></div>
                </div>
                <div class="ranges">
                    <button class="range-chip" data-h="6">6 h</button>
                    <button class="range-chip on" data-h="24">24 h</button>
                    <button class="range-chip" data-h="168">7 days</button>
                    <button class="range-chip" data-h="720">30 days</button>
                </div>
            </section>
            <section class="card">
                <div class="chart-wrap"><canvas></canvas></div>
                <div class="stats"></div>
                <div class="empty c-empty">Choose a device above. Anything the SQL&nbsp;Logger records can be charted, going back months.</div>
            </section>`;
        const $ = (sel) => el.querySelector(sel);
        // dashboard.js declares IndigoAPI as a top-level class, which is shared
        // between classic scripts but never becomes a property of window.
        // eslint-disable-next-line no-undef
        const api = new (typeof IndigoAPI !== "undefined" ? IndigoAPI : root.IndigoAPI)();
        let DEVICES = [], byName = {}, chart = null, ready = null, wantState = null;
        const current = { id: 0, state: "", hours: 24, types: {} };
        // Request order. Replies render in the order they FINISH, and a
        // 30-day series takes 5-6 s against well under a second for 24 h, so an
        // older, slower reply used to land last and draw 30 days under a lit
        // 24 h chip, or one device's states under another device's name.
        // Every request takes a ticket; only the newest may paint.
        let drawSeq = 0;

        function prettyState(s) {
            const dev = DEVICES.find(d => d.id === current.id);
            const m = dev && dev.states && Object.keys(dev.states).find(k => k.toLowerCase().replace(/[^a-z0-9_]/g, "") === s);
            return m || s;
        }
        async function loadDevices() {
            DEVICES = (await api.getDevices()).slice().sort((a, b) => a.name.localeCompare(b.name));
            byName = {};
            $("#c-devlist").innerHTML = DEVICES.map(d => { byName[d.name] = d.id; return `<option value="${esc(d.name)}">`; }).join("");
        }
        function noChart(msg) {
            const e = $(".c-empty"); e.hidden = false; e.textContent = msg;
            if (chart) { chart.destroy(); chart = null; }
            $(".stats").innerHTML = "";
        }
        async function pickDevice(id) {
            const seq = ++drawSeq;
            current.id = id;
            const sel = $("#c-state");
            sel.disabled = true;
            sel.innerHTML = "<option>Loading&hellip;</option>";
            try {
                const res = await api.getHistoryStates(id);
                if (seq !== drawSeq) return;            // a later pick or draw owns the chart
                const states = res.states || [];
                current.types = res.types || {};
                if (!states.length) throw new Error("nothing recorded");
                sel.innerHTML = states.map(s => `<option value="${esc(s)}">${esc(prettyState(s))}</option>`).join("");
                sel.disabled = false;
                const fav = (wantState && states.includes(wantState)) ? wantState
                          : states.find(s => /onoffstate|temperature|batterysoc|power|humidity|lux/.test(s));
                wantState = null;
                sel.value = fav || states[0];
                current.state = sel.value;
                draw();
            } catch (e) {
                if (seq !== drawSeq) return;
                sel.innerHTML = "<option>&mdash;</option>";
                const noDb = String((e && e.message) || "").indexOf("SQL Logger") !== -1;
                setStatus(noDb ? "SQL Logger not running" : "Nothing recorded for that device");
                noChart(noDb ? "Charts need Indigo's SQL Logger plugin (it ships with Indigo; enable it from the Plugins menu). Everything else works without it."
                             : "Nothing recorded for that device: the SQL Logger may exclude it.");
            }
        }
        async function draw() {
            if (!current.id || !current.state) return;
            const seq = ++drawSeq;
            // What THIS request asked for, so the axis labels describe what is
            // drawn, not whatever the chips say by the time it paints.
            const hours = current.hours;
            setStatus("Loading\u2026");
            let res;
            try { res = await api.getHistory(current.id, current.state, hours); }
            catch (e) { if (seq === drawSeq) setStatus("Query failed: " + e.message); return; }
            if (seq !== drawSeq) return;
            const pts = res.points || [];
            if (!pts.length) {
                setStatus((DEVICES.find(d => d.id === current.id) || {}).name || "");
                noChart("Nothing recorded in this range. Try a longer one.");
                return;
            }
            $(".c-empty").hidden = true;
            const labels = pts.map(p => new Date(p.t * 1000));
            const avg = pts.map(p => p.avg), mins = pts.map(p => p.min), maxs = pts.map(p => p.max);
            const css = getComputedStyle(document.documentElement);
            const accent = css.getPropertyValue("--accent").trim();
            const muted = css.getPropertyValue("--text-secondary");
            const grid = css.getPropertyValue("--border");
            // An on/off state has nothing between its two levels, so it is a
            // step with no min/max band.
            const isBool = (res.type || current.types[current.state]) === "bool";
            const series = isBool
                ? [{ label: prettyState(current.state), data: avg, borderColor: accent, borderWidth: 2, pointRadius: 0,
                     stepped: "before", fill: true, backgroundColor: accent + "22" }]
                : [{ label: "max", data: maxs, borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: accent + "22" },
                   { label: "min", data: mins, borderWidth: 0, pointRadius: 0, fill: false },
                   { label: prettyState(current.state), data: avg, borderColor: accent, borderWidth: 2, pointRadius: 0,
                     tension: 0.25, fill: false }];
            chart = root.DashUI.chartRender($("canvas"), {
                type: "line",
                data: { labels, datasets: series },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false }, ticks: { maxTicksLimit: 8, color: muted,
                             callback: (v, i) => { const d = labels[i]; if (!d) return "";
                                 return hours <= 48 ? pad(d.getHours()) + ":" + pad(d.getMinutes()) : d.getDate() + "/" + (d.getMonth() + 1); } } },
                        y: isBool ? { min: 0, max: 1, ticks: { stepSize: 1, color: muted, callback: v => (v ? "on" : "off") }, grid: { color: grid } }
                                  : { ticks: { color: muted }, grid: { color: grid } },
                    },
                },
            });
            const known = (a) => a.filter(v => v != null && isFinite(v));
            const lo = known(mins).length ? Math.min(...known(mins)) : null;
            const hi = known(maxs).length ? Math.max(...known(maxs)) : null;
            const last = avg[avg.length - 1];
            if (isBool) {
                const on = avg.filter(v => v != null && v > 0.5).length, n = known(avg).length;
                $(".stats").innerHTML = `<span>Now <b>${last == null ? "&mdash;" : (last > 0.5 ? "on" : "off")}</b></span>` +
                    `<span>On for <b>${n ? Math.round(on / n * 100) : 0}%</b> of the range</span>`;
            } else {
                const f = v => (v == null ? "&mdash;" : v.toFixed(1));
                $(".stats").innerHTML = `<span>Latest <b>${f(last)}</b></span><span>Lowest <b>${f(lo)}</b></span><span>Highest <b>${f(hi)}</b></span>`;
            }
            setStatus((DEVICES.find(d => d.id === current.id) || {}).name || "");
        }
        $("#c-dev").addEventListener("change", () => { const id = byName[$("#c-dev").value]; if (id) pickDevice(id); });
        $("#c-state").addEventListener("change", () => { current.state = $("#c-state").value; draw(); });
        el.querySelector(".ranges").addEventListener("click", e => {
            const chip = e.target.closest(".range-chip");
            if (!chip) return;
            el.querySelectorAll(".range-chip").forEach(c => c.classList.toggle("on", c === chip));
            current.hours = parseFloat(chip.dataset.h);
            draw();
        });
        return {
            show() {
                if (!ready) ready = loadDevices().catch(e => setStatus("Couldn't load the device list: " + ((e && e.message) || e)));
                else if (current.id) setStatus((DEVICES.find(d => d.id === current.id) || {}).name || "");
                else setStatus("Pick a device");
            },
            hide() {},
            /** Open with a device (and optionally a state) already chosen. */
            async open(deviceId, state) {
                this.show();
                await ready;
                const d = DEVICES.find(x => x.id === deviceId);
                if (!d) { setStatus("That device is not in the list"); return; }
                wantState = String(state || "").toLowerCase().replace(/[^a-z0-9_]/g, "") || null;
                $("#c-dev").value = d.name;
                pickDevice(deviceId);
            },
        };
    }

    // ── Diary ──────────────────────────────────────────────────────────
    // The notable lines from the event log: locks and door codes, doors,
    // leaks, plugin restarts. Errors live on the System page, not here.
    function Diary(el, setStatus) {
        let poller = null;
        const catIcon = (cat) => ({ lock: I("lock"), safety: I("drop"), system: I("gear") }[cat] || "&bull;");
        el.innerHTML = `<section class="card"><div class="card-title"><span>House diary</span>
            <span class="pill">doors &middot; locks &middot; leaks &middot; restarts</span></div>
            <div class="d-body"><div class="loading"><div class="spinner"></div><p>Reading the log&hellip;</p></div></div></section>`;
        const body = el.querySelector(".d-body");
        async function load() {
            try {
                const d = await root.DashUI.message("activityFeed");
                const diary = (d && d.diary) || [];
                body.innerHTML = diary.length ? diary.map(e => `<div class="row">
                        <div class="ic">${catIcon(e.cat)}</div>
                        <div class="bd"><div class="m">${esc(e.msg)}${e.count > 1 ? `<span class="cnt">&times;${e.count}</span>` : ""}</div><div class="s">${esc(e.src)}</div></div>
                        <div class="rt">${esc(e.time)}</div></div>`).join("")
                    : `<div class="empty">Nothing notable in the recent log. Locks, doors, leaks and plugin restarts show here; a script talking to itself does not.</div>`;
                const t = new Date();
                setStatus("Updated " + pad(t.getHours()) + ":" + pad(t.getMinutes()));
            } catch (e) {
                body.innerHTML = `<div class="empty">Couldn't read the diary: ${esc(e.message)}</div>`;
                setStatus("No data");
            }
        }
        return {
            show() { if (!poller) poller = root.DashUI.poll(load, 30000); },
            hide() { if (poller) { poller.stop(); poller = null; } },
        };
    }

    root.TimelineViews = { nights: Nights, chart: Chart_, diary: Diary };
})(typeof window !== "undefined" ? window : globalThis);
