// Filename:    dashboard.js
// Description: Shared IndigoAPI client for every Dashboards page. Replaces
//              the per-page inline copies (v1.22.0) and adds delta-aware
//              device fetching: a module-level cache plus the plugin's
//              changedSince endpoint mean each poll refetches only the
//              devices that actually changed, so pages can poll fast.
// Author:      CliveS & Claude Fable 5
// Date:        11-06-2026
// Version:     1.0
//
// Load order on every page: config.js → dashboards-auth.js →
// dashboards-gate.js → dashboard.js. The gate is optional (pages without it
// behave as before); when present, getDevices() consults DashGate.check()
// before touching /message/ — a request in flight there when the plugin
// host stops wedges the whole IWS event loop for ~5 min (v2.70.0).
//
// How the delta cycle works:
//   1. getDevices() first asks POST /message/.../changedSince/ {since: T}
//      (T = the server clock value returned by the previous call).
//   2. Plugin answers {now, changed: [ids], deleted: [ids]} from its
//      subscribeToChanges ledger — or {now, full: true} when T is 0/stale
//      or the change set is large.
//   3. Changed devices are refetched individually and merged into the
//      module-level cache; on "full" the whole list is refetched.
//   4. A safety full refresh happens every 5 minutes regardless.
// If the endpoint is unavailable (older plugin), getDevices() falls back to
// a plain full fetch — identical behaviour to pre-1.22.0.

class IndigoAPIError extends Error {
    constructor(msg, status) { super(msg); this.name = "IndigoAPIError"; this.status = status; }
}

// Module-level device cache shared by every IndigoAPI instance on the page.
const _INDIGO_STORE = {
    devices:  null,   // Map id -> device object
    sinceTs:  0,      // server clock from the last changedSince reply
    lastFull: 0       // Date.now() of the last full list fetch
};
const _FULL_REFRESH_MS = 300000;   // safety full resync every 5 min
const _FETCH_TIMEOUT_MS = 10000;   // per-request cap — a hung socket must not hold a slot for the OS's minutes-long default
const _DELTA_PATH = "/message/com.clives.indigoplugin.dashboards/changedSince/";

class IndigoAPI {
    constructor(config) {
        const c = config || window.INDIGO_CONFIG || IndigoAPI.getStoredConfig();
        if (!c) throw new IndigoAPIError("Not configured", 0);
        this._base = ""; // same-origin: Indigo /v2/api lacks CORS preflight, so always use page origin
        this._key = c.apiKey;
        // Demo mode (v2.3.0): canned fixtures + local simulator, no server.
        this._demo = (c.apiKey === "demo");
        // Guest mode (v2.1.0): no API key, reads go via the :8177 proxy with
        // the guest token, commands are politely refused client-side (and
        // would fail server-side anyway — a guest holds no IWS credential).
        this._guest = (!c.apiKey && c.guestToken) ? c.guestToken : "";
        this._guestBase = location.protocol + "//" + location.hostname + ":8177";
        this._errH = []; this._authH = [];
    }
    static isConfigured() {
        const c = window.INDIGO_CONFIG || IndigoAPI.getStoredConfig();
        return !!(c && c.baseURL && (c.apiKey || c.guestToken));
    }
    static getStoredConfig() {
        try { return JSON.parse(localStorage.getItem("indigo_config") || "null"); }
        catch { return null; }
    }
    static saveConfig(cfg) { localStorage.setItem("indigo_config", JSON.stringify(cfg)); }
    static clearConfig() { localStorage.removeItem("indigo_config"); }
    onError(fn) { this._errH.push(fn); }
    onAuthFailure(fn) { this._authH.push(fn); }
    async _fetch(path, opts = {}) {
        // The liveness gate, ONCE, for every /message/ call made through this
        // class (v2.95.3). Graphs (historyQuery) went ungated because only
        // getDevices consulted DashGate; a /message/ request landing on a
        // restarting plugin wedges the whole IWS loop for ~5 minutes.
        if (window.DashGate && path.startsWith("/message/")
                && await window.DashGate.check() === "down") {
            const err = new IndigoAPIError("Dashboards plugin is restarting", 0);
            this._errH.forEach(h => h(err)); throw err;
        }
        const headers = { Authorization: "Bearer " + this._key, Accept: "application/json", ...(opts.headers || {}) };
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs || _FETCH_TIMEOUT_MS);
        try {
            let r;
            try { r = await fetch(this._base + path, { ...opts, headers, signal: ctrl.signal }); }
            catch (e) {
                const err = new IndigoAPIError("Network error: " + e.message, 0);
                this._errH.forEach(h => h(err)); throw err;
            }
            if (r.status === 401 || r.status === 403) {
                const err = new IndigoAPIError("Auth failed", r.status);
                this._authH.forEach(h => h(err)); throw err;
            }
            if (!r.ok) {
                const err = new IndigoAPIError("HTTP " + r.status, r.status);
                this._errH.forEach(h => h(err)); throw err;
            }
            const ct = r.headers.get("Content-Type") || "";
            return ct.includes("json") ? await r.json() : null;
        } finally {
            clearTimeout(timer);
        }
    }
    async _guestFetch(path) {
        // Same timeout as _fetch (v2.95.3): one hung socket used to latch
        // observeAll's busy flag for ever, and the guest tablet froze silently.
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), _FETCH_TIMEOUT_MS);
        let r;
        try {
            r = await fetch(this._guestBase + path, {
                headers: { "X-Guest-Token": this._guest }, signal: ctrl.signal
            });
        } catch (e) {
            const err = new IndigoAPIError("Network error: " + e.message, 0);
            this._errH.forEach(h => h(err)); throw err;
        } finally {
            clearTimeout(timer);
        }
        if (r.status === 401 || r.status === 403) {
            const err = new IndigoAPIError("Guest auth failed", r.status);
            this._authH.forEach(h => h(err)); throw err;
        }
        if (!r.ok) throw new IndigoAPIError("HTTP " + r.status, r.status);
        return r.json();
    }

    // ── Demo mode internals (v2.3.0) ────────────────────────────────────
    async _demoLoad() {
        if (_INDIGO_STORE.devices) return;
        const res = await fetch("demo-data/devices.json", { cache: "no-store" });
        const list = await res.json();
        _INDIGO_STORE.devices  = new Map(list.map(d => [d.id, d]));
        _INDIGO_STORE.lastFull = Date.now();
    }
    _demoSimulate() {
        // Gentle drift so the demo feels alive: solar wobbles, the battery
        // creeps, and the odd motion sensor flickers.
        const devs = Array.from(_INDIGO_STORE.devices.values());
        for (const d of devs) {
            const st = d.states || {};
            if (st.pvPowerWatts !== undefined) {
                const pv = Math.max(0, parseFloat(st.pvPowerWatts) * (0.92 + Math.random() * 0.16));
                st.pvPowerWatts = String(Math.round(pv));
                st.batterySoc = String(Math.min(100,
                    (parseFloat(st.batterySoc) || 60) + (Math.random() - 0.45) * 0.2).toFixed(1));
            }
        }
        if (Math.random() < 0.25) {
            const motion = devs.filter(d => /motion|presence/i.test(d.name) && typeof d.onState === "boolean");
            if (motion.length) {
                const pick = motion[Math.floor(Math.random() * motion.length)];
                pick.onState = !pick.onState;
                pick.lastChanged = new Date().toISOString();
            }
        }
    }
    _demoCmd(message, objectId, parameters) {
        const d = _INDIGO_STORE.devices && _INDIGO_STORE.devices.get(objectId);
        if (d) {
            if (message.endsWith(".toggle")) d.onState = !d.onState;
            else if (message.endsWith(".turnOn"))  d.onState = true;
            else if (message.endsWith(".turnOff")) d.onState = false;
            else if (message.endsWith(".setBrightness") && parameters) {
                d.brightness = parameters.value;
                d.onState = parameters.value > 0;
            } else if (message.endsWith(".setHeatSetpoint") && parameters && d.states) {
                d.states.setpointHeat = parameters.value;
            }
            d.lastChanged = new Date().toISOString();
        }
        return Promise.resolve({ ok: true, demo: true });
    }

    // Guest block + per-tile PIN speed bump, shared by every path that
    // COMMANDS a device. Factored out in v2.94.0 so applyColour() below goes
    // through exactly the same gate as _cmd — a second command path that
    // quietly skipped the PIN would be a hole, and a silent one.
    async _gate(objectId) {
        if (this._guest) {
            alert("This device has read-only guest access — controls are disabled.");
            throw new IndigoAPIError("Guest access is read-only", 403);
        }
        // Per-tile PIN speed bump (v2.1.0): a paired device must enter the
        // control PIN once per session before commanding a protected device.
        const pinIds = (window.INDIGO_CONFIG || {}).pinRequired || [];
        if (pinIds.includes(objectId) && !sessionStorage.getItem("dash_pin_ok")) {
            const pin = prompt("This control is PIN-protected. Enter the control PIN:");
            if (pin == null) throw new IndigoAPIError("PIN entry cancelled", 0);
            const res = await this._fetch(
                "/message/com.clives.indigoplugin.dashboards/verifyPin/", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ pin })
                });
            if (!res || !res.valid) {
                alert("Incorrect PIN.");
                throw new IndigoAPIError("Incorrect PIN", 0);
            }
            sessionStorage.setItem("dash_pin_ok", "1");
        }
    }

    /* One request for a whole colour change (v2.94.0). The page used to fire
       turnOn, setBrightness and setColorLevels itself, in that order, each in
       an empty catch — so a phone locking or losing signal part-way left the
       lamp half-set with nothing said. The plugin now runs the sequence and
       reports each step, so a failure is a thrown error here rather than a
       silence. Pass either {preset:"warm"} or explicit level keys. */
    async applyColour(objectId, payload) {
        if (this._demo) {
            const p = ((window.INDIGO_CONFIG || {}).colourPresets || {})[payload && payload.preset];
            return this._demoCmd("indigo.device.turnOn", objectId)
                .then(() => (p && p.brightness != null)
                    ? this._demoCmd("indigo.dimmer.setBrightness", objectId, { value: p.brightness })
                    : null)
                .then(() => ({ ok: true, demo: true }));
        }
        await this._gate(objectId);
        const res = await this._fetch(
            "/message/com.clives.indigoplugin.dashboards/applyColour/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(Object.assign({ deviceId: objectId }, payload || {}))
            });
        if (!res || res.ok !== true) {
            const bad = (res && res.steps || []).filter(st => !st.ok).map(st => st.step);
            throw new IndigoAPIError(
                (res && res.error) || (bad.length ? bad.join(", ") + " failed" : "colour command failed"), 0);
        }
        return res;
    }

    async _cmd(message, objectId, parameters) {
        if (this._demo) return this._demoCmd(message, objectId, parameters);
        await this._gate(objectId);
        const body = { message, objectId };
        if (parameters) body.parameters = parameters;
        return this._fetch("/v2/api/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
    }

    // ── Delta-aware device list ─────────────────────────────────────────
    // `now` is the server clock the changedSince reply carried. It MUST be
    // recorded here as well as on the delta path: the cursor starts at 0, the
    // server answers `since <= 0` with {full:true}, and getDevices() returns
    // this function's result early — so without seeding the cursor here it
    // could never leave 0, every poll asked with since=0, every reply said
    // "full", and the delta system built in v1.22.0 never once engaged.
    // Measured before the fix: 685 kB of device list every 3 s per open page
    // where the delta reply is 498 bytes.
    async _fullDeviceFetch(now) {
        const list = this._guest
            ? await this._guestFetch("/guest/devices")
            : await this._fetch("/v2/api/indigo.devices");
        _INDIGO_STORE.devices  = new Map(list.map(d => [d.id, d]));
        _INDIGO_STORE.lastFull = Date.now();
        // Fall back to the local clock only when the server did not give us
        // one (endpoint unreachable). A local clock is a slightly wrong cursor
        // but a far better starting point than 0, which pins us to full
        // fetches for ever.
        if (now) _INDIGO_STORE.sinceTs = now;
        else if (!_INDIGO_STORE.sinceTs) _INDIGO_STORE.sinceTs = Date.now() / 1000;
        return list;
    }
    async getDevices() {
        // Coalesce (v2.95.3): observeAll and DashAction.selfPoll each own an
        // IndigoAPI but share _INDIGO_STORE, and two overlapping delta cycles
        // could store an older per-device read over a newer one and then
        // advance the cursor past it. One cycle in flight at a time.
        const s = _INDIGO_STORE;
        if (this._demo) return this._getDevicesInner();
        if (s.inflight) return s.inflight;
        s.inflight = this._getDevicesInner();
        try { return await s.inflight; } finally { s.inflight = null; }
    }
    async _getDevicesInner() {
        if (this._demo) {
            await this._demoLoad();
            this._demoSimulate();
            return Array.from(_INDIGO_STORE.devices.values());
        }
        const s = _INDIGO_STORE;
        // v2.70.0 liveness gate: while the plugin is stopping/stopped, a
        // /message/ call can wedge the whole IWS event loop for ~5 min — so
        // don't make one. Serve the cache and recover on a later tick. On a
        // boot-epoch change the server's change ledger has reset, so drop the
        // cursor: the next changedSince answers {full:true} and we resync.
        if (window.DashGate) {
            const verdict = await window.DashGate.check();
            if (verdict === "down") {
                if (s.devices) {
                    // Served from cache while the plugin is down. Flagged so a
                    // page does not advance its "Updated" clock on it (v2.95.3).
                    const cached = Array.from(s.devices.values());
                    cached.fromCache = true;
                    return cached;
                }
                throw new IndigoAPIError("Dashboards plugin is restarting", 0);
            }
            if (window.DashGate.bootChanged()) s.sinceTs = 0;
        }
        let resp = null;
        try {
            resp = this._guest
                ? await this._guestFetch("/guest/changedSince?since=" + encodeURIComponent(s.sinceTs))
                : await this._fetch(_DELTA_PATH, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ since: s.sinceTs })
                });
        } catch (e) {
            if (e instanceof IndigoAPIError && (e.status === 401 || e.status === 403)) throw e;
            // 404/405 = an older plugin without the endpoint: legacy full-fetch
            // fallback. Anything else (network error, timeout, 5xx) is an
            // OUTAGE — rethrow rather than firing a 685 kB full fetch into it
            // every 3 s from every open tab (the old amplifier behaviour).
            if (e instanceof IndigoAPIError && (e.status === 404 || e.status === 405)) {
                resp = null;
            } else {
                throw e;
            }
        }
        // The server saw this poll arrive through the reflector (v2.96.1):
        // tell DashUI.linkClass so every page slows its pictures down, even
        // where the address bar shows a name the classifier does not know.
        if (resp && resp.via === "reflector") window.__DASH_VIA = "reflector";
        const mustFull = !resp || !resp.ok || resp.full || !s.devices
            || (Date.now() - s.lastFull > _FULL_REFRESH_MS);
        if (mustFull) return this._fullDeviceFetch(resp && resp.ok ? resp.now : 0);

        (resp.deleted || []).forEach(id => s.devices.delete(id));
        // Advance the delta cursor only AFTER every changed device is refetched
        // successfully. If a getDevice drops (transient error), leave sinceTs at
        // the old value so the next poll re-requests the same window — otherwise
        // that device silently stays stale in the cache until the 5-min full
        // resync (v2.37.0 fix: the cursor advance used to run before the refetch).
        const ids = resp.changed || [];
        let allOk = true;
        if (ids.length) {
            const fetched = await Promise.all(
                ids.map(id => this.getDevice(id).catch(() => null)));
            fetched.forEach((d, i) => {
                if (d) s.devices.set(d.id, d);
                else allOk = false;   // this id will reappear next window
            });
        }
        if (allOk && resp.ok) s.sinceTs = resp.now || 0;
        return Array.from(s.devices.values());
    }

    async getDevice(id) {
        if (this._demo) {
            await this._demoLoad();
            return _INDIGO_STORE.devices.get(id) || null;
        }
        return this._guest
            ? this._guestFetch("/guest/device/" + id)
            : this._fetch("/v2/api/indigo.devices/" + id);
    }
    getActionGroups()     { return this._fetch("/v2/api/indigo.actionGroups"); }

    // ── History (v2.4.0) — time-series from SQL Logger via the plugin ───
    _demoSeries(deviceId, state, hours) {
        // Synthetic but plausible: daily sine + noise, seeded by ids so the
        // same device/state always draws the same shape in the demo.
        const now = Math.floor(Date.now() / 1000);
        const n = 200, step = (hours * 3600) / n, points = [];
        let seed = (deviceId % 97) + state.length * 13;
        for (let i = 0; i < n; i++) {
            const t = now - (n - i) * step;
            const day = Math.sin((t % 86400) / 86400 * 2 * Math.PI - 2 + seed % 5);
            const base = 20 + (seed % 40) + day * (5 + seed % 10);
            const noise = Math.sin(i * 1.7 + seed) * 1.5;
            const v = Math.round((base + noise) * 10) / 10;
            points.push({ t, avg: v, min: v - 0.8, max: v + 0.8, n: 5 });
        }
        return { ok: true, deviceId, state, hours, points };
    }
    async getHistoryStates(deviceId) {
        if (this._demo) {
            return { ok: true, deviceId,
                     states: ["temperature", "humidity", "batterysoc", "onoffstate"],
                     types: { temperature: "float", humidity: "float",
                              batterysoc: "float", onoffstate: "bool" },
                     rows: 12345, firstTs: "", lastTs: "" };
        }
        if (this._guest) {
            return this._guestFetch("/guest/history?action=states&deviceId=" + deviceId);
        }
        return this._fetch("/message/com.clives.indigoplugin.dashboards/historyQuery/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "states", deviceId })
        });
    }
    async getHistory(deviceId, state, hours, maxPoints) {
        if (this._demo) return this._demoSeries(deviceId, state, hours || 24);
        if (this._guest) {
            return this._guestFetch("/guest/history?action=series&deviceId=" + deviceId +
                "&state=" + encodeURIComponent(state) + "&hours=" + (hours || 24) +
                "&maxPoints=" + (maxPoints || 240));
        }
        return this._fetch("/message/com.clives.indigoplugin.dashboards/historyQuery/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "series", deviceId, state,
                                   hours: hours || 24, maxPoints: maxPoints || 240 })
        });
    }
    async getVariables() {
        if (this._demo) {
            const r = await fetch("demo-data/variables.json", { cache: "no-store" });
            return r.json();
        }
        return this._guest
            ? this._guestFetch("/guest/variables")
            : this._fetch("/v2/api/indigo.variables");
    }
    turnOn(id)            { return this._cmd("indigo.device.turnOn", id); }
    turnOff(id)           { return this._cmd("indigo.device.turnOff", id); }
    toggle(id)            { return this._cmd("indigo.device.toggle", id); }
    setBrightness(id, v)  { return this._cmd("indigo.dimmer.setBrightness", id, { value: v }); }
    // params: { redLevel, greenLevel, blueLevel, whiteLevel, whiteTemperature } — all optional, 0-100 levels, Kelvin temp.
    setColorLevels(id, params) { return this._cmd("indigo.dimmer.setColorLevels", id, params); }
    setHeatSetpoint(id, v){ return this._cmd("indigo.thermostat.setHeatSetpoint", id, { value: v }); }
    setCoolSetpoint(id, v){ return this._cmd("indigo.thermostat.setCoolSetpoint", id, { value: v }); }
    executeActionGroup(id){ return this._cmd("indigo.actionGroup.execute", id); }
    observe(id, cb, ms = 3000) {
        let last = "";
        let busy = false;   // in-flight guard, as observeAll has (v2.95.3)
        const tick = async () => {
            if (busy || document.hidden) return;
            busy = true;
            try { const d = await this.getDevice(id); const j = JSON.stringify(d);
                  if (j !== last) { last = j; cb(d); } } catch {}
            finally { busy = false; }
        };
        tick();
        const t = setInterval(tick, ms);
        return { stop: () => clearInterval(t) };
    }
    observeAll(cb, ms = 3000, onErr, onOk) {
        let last = "";
        let busy = false;   // in-flight guard: a slow tick must not be overlapped by the next
        const tick = async () => {
            if (busy || document.hidden) return;
            busy = true;
            try {
                const d = await this.getDevices();
                // onOk fires on EVERY successful poll (cb only on change) —
                // it exists so a page's "Updated" clock can tell the truth
                // instead of advancing on a blind timer through an outage.
                if (onOk) { try { onOk(d); } catch {} }
                const j = JSON.stringify(d);
                if (j !== last) { last = j; cb(d); }
            } catch (e) {
                if (onErr) { try { onErr(e); } catch {} }
            } finally {
                busy = false;
            }
        };
        tick();
        const t = setInterval(tick, ms);
        // Hidden tabs skip ticks (nothing is looking); an immediate tick on
        // return to visible so the page catches up without waiting a period.
        const onVis = () => { if (!document.hidden) tick(); };
        document.addEventListener("visibilitychange", onVis);
        return { stop: () => {
            clearInterval(t);
            document.removeEventListener("visibilitychange", onVis);
        } };
    }
}
