// Filename:    dashboards-auth.js
// Description: Browser-side credential merge + LAN auto-seed for the
//              Dashboards pages. Loaded immediately AFTER config.js on every
//              page that talks to the Indigo REST API.
// Author:      CliveS & Claude Fable 5
// Date:        11-06-2026
// Version:     1.2
//
// As of plugin v1.20.0 the server no longer publishes the Indigo API key in
// config.js — the /public/ namespace is served by IWS with NO authentication
// and is reachable over the Indigo reflector (i.e. from the public internet).
// config.js now carries only the server baseURL.
//
// The key lives in this browser's localStorage under "indigo_config" — the
// same store the pages' existing Connect form (index.html) has always
// written. This shim merges the two sources into window.INDIGO_CONFIG so the
// per-page IndigoAPI classes keep working unchanged.
//
// v1.1 (plugin v1.20.1) adds two things:
//
// 1. ORIGIN-PREFERRING baseURL. The pages are always served by the same IWS
//    instance as the API, so the page's own origin IS the right API base on
//    every route — LAN, Tailscale IP, or reflector. The configured/stored
//    baseURL is only a fallback for non-http contexts (e.g. an app webview).
//    This is what makes the dashboards actually work over the reflector.
//
// 2. LAN/TAILSCALE AUTO-SEED. With no stored key, the shim asks the plugin's
//    proxy on :8177 for /bootstrap (that port is never fronted by the
//    reflector and the plugin additionally refuses non-private source IPs).
//    On success the key is stored and the page reloads — so devices at home
//    or on the Tailnet never see the Connect form at all. Over the reflector
//    the fetch fails fast (mixed content / unreachable) and the existing
//    Connect form takes over.
(function () {
    "use strict";

    // --- Optional plugins (v1.2, plugin v3.13.0) ------------------------------
    // config.js says which optional plugins are present. A page that has
    // nothing to draw without one hides itself and SAYS why — a gap with no
    // word beside it reads as a fault. Hoisted, so window.DashFeatures below
    // exists on every page whichever early return this file takes.
    function _dashSigenOn() {
        return !(window.INDIGO_CONFIG && window.INDIGO_CONFIG.sigenAvailable === false);
    }
    function _dashSigenAbsent(pageLabel) {
        // Draw one card in place of the page and return true when the
        // SigenEnergyManager plugin is absent; return false and touch nothing
        // when it is present. A page wraps its boot in this, so a bookmark to
        // it on a server without the plugin explains itself instead of showing
        // empty charts and fetch errors.
        if (_dashSigenOn()) return false;
        var esc = function (s) {
            return String(s).replace(/[&<>"]/g, function (c) {
                return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
            });
        };
        var draw = function () {
            var main = document.querySelector("main") || document.body;
            if (!main) return;
            main.innerHTML =
                '<section style="max-width:36em;margin:2em auto;padding:1.2em 1.4em;border-radius:14px;' +
                'background:var(--card-bg,#fff);color:var(--text,#1d1d1f);line-height:1.55">' +
                '<h2 style="margin:0 0 .5em;font-size:1.15em">The ' + esc(pageLabel) +
                ' page needs the SigenEnergyManager plugin</h2>' +
                '<p style="margin:0 0 .6em;color:var(--text-secondary,#86868b)">It is not installed on ' +
                'this Indigo server, so there is nothing for this page to show. Everything else on ' +
                'the dashboards works without it.</p>' +
                '<p style="margin:0"><a href="index.html">Back to the hub</a></p></section>';
        };
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", draw);
        else draw();
        return true;
    }

    var cfg = window.INDIGO_CONFIG || {};
    var stored = null;
    try {
        stored = JSON.parse(localStorage.getItem("indigo_config") || "null");
    } catch (e) {
        stored = null;
    }
    stored = stored || {};

    var origin = (location.protocol === "http:" || location.protocol === "https:")
        ? location.origin : "";
    // A MERGE, not a whitelist (v2.95.1). This used to rebuild the object
    // field by field, so anything config.js published that the list omitted
    // was silently dropped before any page saw it — favourites (v2.10.0),
    // customLinks (v2.13.1) and then colourPresets (the plugin published the
    // preset table from v2.94.0 and room.html never received it, so editing a
    // preset changed nothing on the page). Everything config.js carries now
    // passes through; only the three fields this file OWNS are set here.
    window.INDIGO_CONFIG = Object.assign({}, cfg, {
        baseURL:    origin || cfg.baseURL || stored.baseURL || "",
        apiKey:     cfg.apiKey || stored.apiKey || "",
        guestToken: ""
    });
    // The fields the pages have always been able to assume exist:
    window.INDIGO_CONFIG.sigenDeviceId = cfg.sigenDeviceId || 0;
    window.INDIGO_CONFIG.pinRequired   = cfg.pinRequired || [];
    window.INDIGO_CONFIG.favourites    = cfg.favourites || [];   // v2.10.0: hub Favourites
    window.INDIGO_CONFIG.customLinks   = cfg.customLinks || [];  // v2.13.0: hub Custom links
    window.INDIGO_CONFIG.arrayKwp      = cfg.arrayKwp || 0;      // v2.72.0: solar array rating
    window.INDIGO_CONFIG.actionWatch   = cfg.actionWatch || {};  // v2.75.0: DashAction watches
    // Optional-plugin flags (v3.13.0). Absent from an older config.js the
    // key reads as true — an upgrade must never hide pages that were there
    // yesterday. heatingControls has always been read raw by the heating page.
    window.INDIGO_CONFIG.sigenAvailable = (cfg.sigenAvailable !== false);
    window.DashFeatures = { sigen: _dashSigenOn, sigenAbsent: _dashSigenAbsent };
    // REFUSE THE REFLECTOR (v3.1.0). The server refuses the data; this stops
    // the page ASKING, which matters because a page's camera pictures come
    // from /public — anonymous static files the plugin never sees a request
    // for. A tab left open on the reflector address was pulling those
    // regardless of what any handler decided.
    // NOT via DashUI.linkClass: dashboards-ui.js loads AFTER this file on 18
    // of the 20 pages, so `window.DashUI && ...` would be a silent no-op on
    // exactly the pages that matter. The address half of that verdict is four
    // lines, so this owns it rather than depending on load order.
    var _isReflectorAddress = function () {
        var h = (location.hostname || "").toLowerCase();
        var v6 = h.replace(/^\[|\]$/g, "");
        if (h === "localhost" || v6 === "::1" || /\.local$/.test(h) || /\.ts\.net$/.test(h)) return false;
        if (/^f[cd][0-9a-f]{2}:/.test(v6)) return false;
        var m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
        if (!m) return true;                      // a NAME that is not ours: the reflector
        var a = +m[1], b = +m[2];
        if (a === 127 || a === 10) return false;
        if (a === 192 && b === 168) return false;
        if (a === 172 && b >= 16 && b <= 31) return false;
        if (a === 100 && b >= 64 && b <= 127) return false;   // Tailscale CGNAT
        return true;
    };
    if (cfg.reflectorBlock === true && _isReflectorAddress()) {
        var lan = String(cfg.lanURL || "").replace(/\/$/, "");
        var here = (location.pathname.split("/").pop() || "index.html");
        var url = lan ? lan + "/public/dashboards/" + here : "";
        var say = function () {
            document.title = "Not over the reflector";
            document.body.innerHTML =
                '<div style="max-width:34em;margin:12vh auto;padding:0 1.2em;font:16px/1.6 -apple-system,' +
                'BlinkMacSystemFont,\'Segoe UI\',sans-serif;color:#333">' +
                '<h1 style="font-size:1.3em">This dashboard is not served over the reflector</h1>' +
                '<p>The Indigo reflector relays through Indigo Domotics\' own servers, and the camera ' +
                'pictures on these pages are far heavier than it is meant to carry. This server is set ' +
                'to serve the dashboards on the local network and VPN only.</p>' +
                (url ? '<p>At home, or with the VPN connected: <a href="' + url + '">' + url + '</a></p>' : '') +
                '<p style="color:#777;font-size:.9em">Plugins &rarr; Dashboards &rarr; Configure &rarr; ' +
                '"Refuse the reflector" turns this off again.</p></div>';
        };
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", say);
        else say();
        return;
    }

    // Site name (v2.96.0): the pages ship saying "Dashboards"; a siteName in
    // the settings store renames the tab title, the home-screen label and the
    // hub heading, so another install is not called after the author's house.
    var site = String(cfg.siteName || "").trim();
    if (site && site !== "Dashboards") {
        try {
            document.title = document.title.replace(/^Dashboards\b/, site);
            var mt = document.querySelector('meta[name="apple-mobile-web-app-title"]');
            if (mt) mt.setAttribute("content", site);
            var apply = function () { var h = document.getElementById("site-name"); if (h) h.textContent = site; };
            if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply); else apply();
        } catch (e) { /* presentation only */ }
    }
    // (History of the whitelist, kept because the shape of the fault matters:
    // it bit twice before the merge — favourites (v2.10.0) and customLinks (v2.13.1)
    // both shipped, looked correct in config.js, and rendered nothing. ANY new
    // config.js field must be added above as well.

    // --- Demo mode (v2.3.0) ---------------------------------------------------
    // demo.html sets sessionStorage "dash_demo"; every page then runs from the
    // canned fixtures in demo-data/ with a tiny state simulator — no Indigo
    // server, no credentials. This is what powers the hosted GitHub Pages
    // showcase. Demo wins over everything else and never touches real creds.
    if (sessionStorage.getItem("dash_demo")) {
        window.INDIGO_CONFIG.apiKey = "demo";
        window.INDIGO_CONFIG.sigenAvailable = true;   // the fixtures carry energy data whatever this server has
        // Demo is UNMARKED data that looks real — on a live install anyone
        // stumbling into demo.html saw plausible-but-fake readings with no
        // sign and no way out. Every page now wears a banner with the exit.
        var _addDemoBanner = function () {
            if (document.getElementById("dash-demo-banner")) return;
            var b = document.createElement("div");
            b.id = "dash-demo-banner";
            b.style.cssText = "position:fixed;bottom:0;left:0;right:0;z-index:9999;" +
                "background:#b45309;color:#fff;text-align:center;padding:6px 10px;" +
                "font:600 13px -apple-system,sans-serif;cursor:pointer;";
            b.textContent = "DEMO DATA — none of this is your house. Tap to exit.";
            b.addEventListener("click", function () {
                sessionStorage.removeItem("dash_demo");
                location.href = "index.html";
            });
            document.body.appendChild(b);
        };
        if (document.body) _addDemoBanner();
        else document.addEventListener("DOMContentLoaded", _addDemoBanner);
        return;
    }

    // --- Guest mode (v2.1.0) ------------------------------------------------
    // A device paired via guest.html holds ONLY the guest token (localStorage
    // "dash_guest") — read-only data via the :8177 proxy, no API key, no
    // control surface. Guest mode takes priority and skips the full-key
    // auto-seed so a guest device never acquires the master key.
    var guest = localStorage.getItem("dash_guest") || "";
    if (guest && !window.INDIGO_CONFIG.apiKey) {
        window.INDIGO_CONFIG.guestToken = guest;
        return;
    }

    // --- LAN/Tailscale auto-seed -------------------------------------------
    if (window.INDIGO_CONFIG.apiKey) return;                 // already paired
    if (!origin) return;                                     // non-http context
    if (sessionStorage.getItem("dash_bootstrap_tried")) return;  // once per tab
    sessionStorage.setItem("dash_bootstrap_tried", "1");

    var bootstrapURL = location.protocol + "//" + location.hostname + ":8177/bootstrap";
    var ctrl = ("AbortController" in window) ? new AbortController() : null;
    if (ctrl) setTimeout(function () { ctrl.abort(); }, 2500);

    fetch(bootstrapURL, ctrl ? { signal: ctrl.signal } : {})
        .then(function (res) {
            if (!res.ok) throw new Error("bootstrap " + res.status);
            return res.json();
        })
        .then(function (data) {
            if (!data || !data.apiKey) throw new Error("no key in bootstrap");
            localStorage.setItem("indigo_config", JSON.stringify({
                baseURL: origin,
                apiKey:  data.apiKey
            }));
            location.reload();
        })
        .catch(function () {
            // Not on the LAN/Tailnet (or proxy down) — the normal Connect
            // form / redirect-to-index flow handles it from here.
        });
})();
