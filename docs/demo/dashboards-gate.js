// Filename:    dashboards-gate.js
// Description: Liveness gate for every /message/ poller. A /message/ request
//              in flight when the Dashboards plugin host stops wedges the
//              ENTIRE IWS event loop for ~298 s (measured), 500ing every
//              static file and API route. The plugin heartbeats a tiny
//              changed.stamp file into /public (served by IWS itself — no
//              plugin IPC, cannot wedge); this gate reads it and tells
//              pollers whether it is safe to call /message/ right now.
// Author:      CliveS & Claude Fable 5
// Date:        31-07-2026
// Version:     1.0
//
// Load order: config.js → dashboards-auth.js → dashboards-gate.js → the rest.
//
// Usage:  const verdict = await DashGate.check();   // "ok" | "down" | "nogate"
//   "ok"     — heartbeat live, poll away.
//   "down"   — plugin stopping / stopped / stamp unreachable: do NOT call
//              /message/; render cached data and try again next tick.
//   "nogate" — no stamp exists (older plugin, or a host that never had it):
//              behave exactly as before this file existed. 404 must never
//              read as "down" or a mixed-version deploy bricks every page.
//
// Staleness is judged SKEW-IMMUNE: we never compare the server's ts with the
// client clock. We track when the ts VALUE last advanced, on the client
// clock — "no advance for STALE_MS" is a pure client-side duration.
(function () {
    "use strict";

    const STAMP_URL   = "changed.stamp";  // relative — same dir as the pages, works on LAN + reflector
    const FETCH_MS    = 2000;             // memoise window: ≤1 stamp fetch per 2 s shared by all pollers
    const NOGATE_RECHECK_MS = 60000;      // a 404'd stamp (older plugin) rechecks lazily — IWS logs a
                                          // warning per 404, and "nogate" behaviour is the pre-gate
                                          // status quo, so a slow discovery of a new stamp costs nothing
    const FETCH_TIMEOUT_MS = 5000;
    const STALE_MS    = 12000;            // 6 missed 2 s beats — far below the 298 s wedge
    const BACKOFF_BASE_MS = 3000;
    const BACKOFF_MAX_MS  = 60000;

    const st = {
        lastVerdict:  "nogate",
        lastFetchAt:  0,        // client clock of the last actual stamp fetch
        lastTs:       0,        // last server ts VALUE seen
        lastAdvance:  0,        // client clock when lastTs last advanced
        boot:         0,        // last server boot value seen
        bootFlag:     false,    // set on boot change, cleared by bootChanged()
        backoffMs:    0,        // 0 = not backing off
        backoffUntil: 0,
        inflight:     null      // shared promise so concurrent callers coalesce
    };

    function noteDown() {
        st.backoffMs = st.backoffMs ? Math.min(st.backoffMs * 2, BACKOFF_MAX_MS)
                                    : BACKOFF_BASE_MS;
        st.backoffUntil = Date.now() + st.backoffMs;
        st.lastVerdict = "down";
        return "down";
    }

    function noteOk() {
        st.backoffMs = 0;
        st.backoffUntil = 0;
        st.lastVerdict = "ok";
        return "ok";
    }

    async function fetchStamp() {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
        try {
            const r = await fetch(STAMP_URL + "?t=" + Date.now(),
                                  { cache: "no-store", signal: ctrl.signal });
            if (r.status === 404) { st.lastVerdict = "nogate"; return "nogate"; }
            if (!r.ok) return noteDown();          // 5xx = IWS/plugin unwell
            const j = await r.json();
            if (!j || typeof j.ts !== "number") return noteDown();
            if (j.boot && j.boot !== st.boot) {
                if (st.boot) st.bootFlag = true;   // a RE-boot, not first sight
                st.boot = j.boot;
            }
            const firstSight = st.lastTs === 0;
            // Any CHANGE is an advance (v2.95.3), not only an increase: a
            // server clock stepped back after an NTP correction made every
            // new stamp read below the last one, and the gate answered
            // "down" until the clock caught up. A frozen value is still caught.
            if (j.ts !== st.lastTs) {
                st.lastTs = j.ts;
                st.lastAdvance = Date.now();
            }
            if (j.state === "stopping") return noteDown();
            // First sight of a stamp already minutes old is a plugin that died
            // without writing the sentinel (kill -9, force-quit). It used to
            // read "ok" for a full STALE_MS window and let the page fire
            // /message/ calls into a dead host.
            // (Only a ts that IS an epoch can be aged — a synthetic counter is
            // not one, and a plugin cannot write a future stamp either.)
            if (firstSight && j.ts > 1e9 && (Date.now() / 1000 - j.ts) > 300) return noteDown();
            // A live writer advances ts every ~2 s. A frozen value means the
            // plugin died without writing the sentinel (kill -9, crash).
            if (Date.now() - st.lastAdvance > STALE_MS) return noteDown();
            return noteOk();
        } catch (e) {
            return noteDown();                     // network error / timeout
        } finally {
            clearTimeout(timer);
        }
    }

    async function check() {
        const now = Date.now();
        // While backing off, answer instantly from the last verdict — no fetch.
        if (st.lastVerdict === "down" && now < st.backoffUntil) return "down";
        // Memoise: many pollers on one page share one stamp fetch per window.
        const windowMs = st.lastVerdict === "nogate" ? NOGATE_RECHECK_MS : FETCH_MS;
        if (now - st.lastFetchAt < windowMs && !st.inflight) return st.lastVerdict;
        if (!st.inflight) {
            st.lastFetchAt = now;
            st.inflight = fetchStamp().finally(() => { st.inflight = null; });
        }
        return st.inflight;
    }

    window.DashGate = {
        check,
        // True exactly once after the plugin's boot epoch changes — the caller
        // should drop its delta cursor and do a full resync, because the
        // change ledger reset while it was not looking.
        bootChanged() {
            if (!st.bootFlag) return false;
            st.bootFlag = false;
            return true;
        },
        // Test hook: expose internals so the node suite can drive the clock.
        _state: st,
        _constants: { FETCH_MS, STALE_MS, BACKOFF_BASE_MS, BACKOFF_MAX_MS,
                      FETCH_TIMEOUT_MS, NOGATE_RECHECK_MS }
    };
})();
