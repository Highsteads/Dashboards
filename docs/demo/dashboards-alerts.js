/* Filename:    dashboards-alerts.js
 * Description: The browser alert rules, evaluated on every main page (3.46.0).
 *
 *              The rules have always lived in this browser's localStorage
 *              (dash_alerts), and alerts.html said they fired "while this
 *              page, or the dashboard on your home screen, is open". They
 *              only ever fired while alerts.html ITSELF was open: the
 *              watcher was inline in that page, so a hub on the wall with
 *              the rules saved raised nothing. The watcher now lives here,
 *              and the hub, the room pages, Energy and Alerts all load it.
 *
 *              Several tabs may be open at once, so two things stop the
 *              same change being announced twice:
 *                - one tab polls for the rules at a time: each writes a beat
 *                  (dash_alerts_beat) and a tab that sees another's fresh
 *                  beat stands by; Alerts always polls, as it paints the
 *                  "now" column;
 *                - a firing is CLAIMED in dash_alerts_fired (per rule, with
 *                  the 30 s per-rule cooldown the page always had), and only
 *                  the tab still holding the claim a moment later raises it,
 *                  so two tabs that both saw the change cannot both notify.
 *              Every localStorage touch is wrapped: a private window, or a
 *              browser with site data blocked, falls back to this tab alone,
 *              which is how the page behaved before.
 *
 *              The evaluators (judgeDevice, judgeVariable) and the claim are
 *              pure and take their storage as an argument, so
 *              tests/test_alerts_shared.mjs can drive them.
 * Author:      CliveS & Claude Opus 5.5
 * Date:        25-09-2026
 * Version:     1.0
 */

(function (root) {
  'use strict';

  var STORE_KEY = 'dash_alerts';          // {rules: [...], active: bool}
  var FIRED_KEY = 'dash_alerts_fired';    // {"device:12:on": {t, tab}}
  var LOG_KEY = 'dash_alerts_log';        // [{t, text}], newest first
  var BEAT_KEY = 'dash_alerts_beat';      // {tab, t}
  var COOLDOWN_MS = 30000;                // per rule, so a chattering sensor cannot send twenty
  var DEVICE_MS = 3000, VARIABLE_MS = 10000;
  var BEAT_STALE_MS = 25000;              // two missed variable polls (or eight device polls) and another tab takes over
  var CONFIRM_MS = 250;                   // how long a claim must survive before it is raised
  var LOG_MAX = 50;

  function storage() {
    try { return root.localStorage || null; } catch (e) { return null; }
  }
  function readJson(store, key, fallback) {
    try {
      var raw = store && store.getItem(key);
      if (!raw) return fallback;
      var v = JSON.parse(raw);
      return (v === null || v === undefined) ? fallback : v;
    } catch (e) { return fallback; }
  }
  function writeJson(store, key, value) {
    try { if (!store) return false; store.setItem(key, JSON.stringify(value)); return true; }
    catch (e) { return false; }
  }

  /* ── the rules ─────────────────────────────────────────────────────── */
  function load(store) {
    var d = readJson(store === undefined ? storage() : store, STORE_KEY, {});
    return {
      rules: (d && Array.isArray(d.rules)) ? d.rules.filter(function (r) { return r && typeof r === 'object'; }) : [],
      // The "alerts active" switch was a checkbox that forgot itself on every
      // reload and meant nothing to any other tab; it is kept with the rules now.
      active: !(d && d.active === false)
    };
  }
  function save(state, store) {
    return writeJson(store === undefined ? storage() : store, STORE_KEY,
                     { rules: (state && state.rules) || [], active: !(state && state.active === false) });
  }
  function ruleKey(r) { return r.kind + ':' + r.id + ':' + r.cond; }

  /* ── what a change means (pure) ────────────────────────────────────── */
  function deviceNow(d) {
    var ui = d.displayStateValUi;
    return { on: !!d.onState, ui: String(ui === null || ui === undefined ? '' : ui) };
  }
  function deviceText(now) { return now.ui || (now.on ? 'ON' : 'OFF'); }
  /* The alert text for a device rule, or null. `was` is the previous
     reading of the same device, `now` this one (both from deviceNow). */
  function judgeDevice(rule, was, now) {
    if (!was || !now) return null;
    if (rule.cond === 'on' && now.on && !was.on) return rule.name + ' turned on';
    if (rule.cond === 'off' && !now.on && was.on) return rule.name + ' turned off';
    if (rule.cond === 'change' && (now.on !== was.on || now.ui !== was.ui)) return rule.name + ': ' + deviceText(now);
    return null;
  }
  function judgeVariable(rule, was, value) {
    if (!was) return null;
    return String(value) !== was.val ? rule.name + ' is now ' + value : null;
  }

  /* ── one announcement across tabs ──────────────────────────────────── */
  var _memFired = {};   // this tab's own record, used when storage is not there
  function claim(key, tab, now, store) {
    var mine = _memFired[key];
    if (mine && now >= mine && now - mine < COOLDOWN_MS) return false;
    var fired = readJson(store, FIRED_KEY, {});
    if (!fired || typeof fired !== 'object' || Array.isArray(fired)) fired = {};
    var last = fired[key];
    if (last && typeof last.t === 'number' && now >= last.t && now - last.t < COOLDOWN_MS) return false;
    fired[key] = { t: now, tab: tab };
    // Keep the record small: nothing older than a day matters to a 30 s cooldown.
    Object.keys(fired).forEach(function (k) {
      if (!fired[k] || !(now - fired[k].t < 86400000)) delete fired[k];
    });
    writeJson(store, FIRED_KEY, fired);
    _memFired[key] = now;
    return true;
  }
  /* Still ours a moment later? Two tabs that read the record before either
     wrote it both claim; the last writer wins and the other stands down. No
     record at all (storage refused) means this tab is alone: it is ours. */
  function stillOurs(key, tab, store) {
    var fired = readJson(store, FIRED_KEY, null);
    if (!fired || !fired[key]) return true;
    return fired[key].tab === tab;
  }
  /* May this tab poll? Another tab's fresh beat means no. */
  function mayPoll(tab, now, store, always) {
    var b = readJson(store, BEAT_KEY, null);
    var other = b && b.tab !== tab && typeof b.t === 'number' && now >= b.t && now - b.t < BEAT_STALE_MS;
    if (other && !always) return false;
    // A tab that always polls (Alerts) still beats, so the others stand by.
    if (!other || always) writeJson(store, BEAT_KEY, { tab: tab, t: now });
    return true;
  }

  function readLog(store) {
    var l = readJson(store === undefined ? storage() : store, LOG_KEY, []);
    return Array.isArray(l) ? l.filter(function (x) { return x && typeof x.text === 'string'; }) : [];
  }
  function appendLog(text, t, store) {
    var s = store === undefined ? storage() : store;
    var l = readLog(s);
    l.unshift({ t: t, text: text });
    writeJson(s, LOG_KEY, l.slice(0, LOG_MAX));
  }

  /* ── the notification itself ───────────────────────────────────────── */
  var _swReg = null, _swAsked = false;
  function registerWorker() {
    if (_swAsked) return;
    _swAsked = true;
    try {
      var nav = root.navigator;
      if (nav && 'serviceWorker' in nav) {
        nav.serviceWorker.register('sw.js').then(function (r) { _swReg = r; }).catch(function () {});
      }
    } catch (e) { /* no worker: new Notification() below still works on desktop */ }
  }
  function notify(title, body) {
    var N = root.Notification;
    if (!N || N.permission !== 'granted') return;
    try {
      var opts = { body: body, icon: 'apple-touch-icon-192.png', tag: title + '|' + body };
      if (_swReg && _swReg.showNotification) _swReg.showNotification(title, opts);
      else new N(title, opts);
    } catch (e) { /* notification refused — nothing else to do */ }
  }

  /* ── the watcher ───────────────────────────────────────────────────── */
  var _started = null;
  /* watch(opts) starts polling for the saved rules. opts:
       api          an IndigoAPI (required)
       alwaysPoll   true on alerts.html: poll whatever the other tabs do
       onPaint(key, text)  the current value of "device:12" / "variable:9"
       onFire(text)        after this tab has raised an alert
     Returns {stop}. One watcher per page. */
  function watch(opts) {
    var o = opts || {};
    if (_started) return _started;
    var api = o.api;
    if (!api) return null;
    var tab = Math.random().toString(36).slice(2) + Date.now().toString(36);
    var prev = {};           // "device:123" -> {on, ui} / "variable:9" -> {val}
    var seeded = false, leading = false;
    function paint(key, text) { if (typeof o.onPaint === 'function') { try { o.onPaint(key, text); } catch (e) { /* page's problem */ } } }

    function lead(now) {
      var ok = mayPoll(tab, now, storage(), !!o.alwaysPoll);
      // A tab taking over starts from what is true NOW: its old readings
      // could be minutes out of date and would announce changes long past.
      if (ok && !leading) { prev = {}; seeded = false; }
      leading = ok;
      return ok;
    }
    function fire(rule, text) {
      var store = storage(), key = ruleKey(rule), t = Date.now();
      if (!claim(key, tab, t, store)) return;
      setTimeout(function () {
        if (!stillOurs(key, tab, storage())) return;
        var cfg = root.INDIGO_CONFIG || {};
        notify(cfg.siteName || 'Dashboards', text);
        appendLog(text, t);
        if (typeof o.onFire === 'function') { try { o.onFire(text, t); } catch (e) { /* page's problem */ } }
      }, CONFIRM_MS);
    }

    async function pollDevices() {
      var state = load();
      var rules = state.rules.filter(function (r) { return r.kind === 'device'; });
      if (!rules.length || !lead(Date.now())) return;
      var devs;
      try { devs = await api.getDevices(); } catch (e) { return; }
      var byId = new Map((devs || []).map(function (d) { return [d.id, d]; }));
      var seen = {};
      rules.forEach(function (r) {
        var key = 'device:' + r.id, d = byId.get(r.id);
        if (!d) { paint(key, 'missing'); return; }
        var now = seen[key] || (seen[key] = deviceNow(d));
        paint(key, deviceText(now));
        // Every rule on a device is judged against the SAME earlier reading.
        // The inline watcher stored the new reading after the first rule, so
        // a second rule on that device ("turns off" beside "turns on") never
        // saw a change at all.
        if (!seeded || !r.enabled || !state.active) return;
        var text = judgeDevice(r, prev[key], now);
        if (text) fire(r, text);
      });
      Object.keys(seen).forEach(function (k) { prev[k] = seen[k]; });
      seeded = true;
    }

    async function pollVariables() {
      var state = load();
      var rules = state.rules.filter(function (r) { return r.kind === 'variable'; });
      if (!rules.length || !lead(Date.now())) return;
      var vars;
      try { vars = await api.getVariables(); } catch (e) { return; }
      var byId = new Map((vars || []).map(function (v) { return [v.id, v]; }));
      var seen = {};
      rules.forEach(function (r) {
        var key = 'variable:' + r.id, v = byId.get(r.id);
        if (!v) { paint(key, 'missing'); return; }
        paint(key, String(v.value));
        seen[key] = { val: String(v.value) };
        if (!r.enabled || !state.active) return;
        var text = judgeVariable(r, prev[key], v.value);
        if (text) fire(r, text);
      });
      Object.keys(seen).forEach(function (k) { prev[k] = seen[k]; });
    }

    if (load().rules.length) registerWorker();
    // A plain setInterval, NOT DashUI.poll: an alert is most useful in a tab
    // you are not looking at, and poll() pauses in a hidden one.
    var t1 = setInterval(pollDevices, DEVICE_MS);
    var t2 = setInterval(pollVariables, VARIABLE_MS);
    pollDevices(); pollVariables();
    _started = {
      stop: function () { clearInterval(t1); clearInterval(t2); _started = null; },
      pollDevices: pollDevices, pollVariables: pollVariables
    };
    return _started;
  }

  /* The hub, room and Energy pages load this file and do nothing more: once
     the page has parsed, the watcher starts itself for a paired browser. A
     guest holds no key (and sees no alerts), and the demo's made-up devices
     must never fire this browser's real rules. alerts.html starts it itself,
     first, with its own painting. */
  function autoStart() {
    if (_started) return;
    try {
      var cfg = root.INDIGO_CONFIG || {};
      if (!cfg.apiKey || cfg.apiKey === 'demo') return;
      // dashboard.js declares `class IndigoAPI` at the top level of a classic
      // script: a global binding, but not a property of window.
      var Api = (typeof IndigoAPI === 'function') ? IndigoAPI : root.IndigoAPI;   // eslint-disable-line no-undef
      if (typeof Api !== 'function' || !Api.isConfigured()) return;
      if (!load().rules.length) {
        // Nothing to watch yet; look again if Alerts adds a rule in another tab.
        root.addEventListener && root.addEventListener('storage', function once(ev) {
          if (ev && ev.key === STORE_KEY && load().rules.length) {
            root.removeEventListener('storage', once);
            autoStart();
          }
        });
        return;
      }
      watch({ api: new Api() });
    } catch (e) { /* alerts are a nicety: never break the page that carries them */ }
  }

  var API = {
    load: load, save: save, ruleKey: ruleKey,
    deviceNow: deviceNow, judgeDevice: judgeDevice, judgeVariable: judgeVariable,
    claim: claim, stillOurs: stillOurs, mayPoll: mayPoll,
    readLog: readLog, appendLog: appendLog,
    registerWorker: registerWorker, notify: notify,
    watch: watch, autoStart: autoStart,
    STORE_KEY: STORE_KEY, LOG_KEY: LOG_KEY, COOLDOWN_MS: COOLDOWN_MS, BEAT_STALE_MS: BEAT_STALE_MS
  };
  root.DashAlerts = API;
  if (typeof globalThis !== 'undefined') globalThis.DashAlerts = API;

  var d = root.document;
  if (d && typeof d.addEventListener === 'function') {
    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', autoStart);
    else setTimeout(autoStart, 0);
  }
})(typeof window !== 'undefined' ? window : globalThis);
