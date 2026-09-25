/* Filename:    dashboards-alerts.js
 * Description: Browser notifications for the Alerts rules, on every main page.
 *
 *              2.0 (3.47.0): the PLUGIN keeps and judges the rules now, on
 *              Indigo's own change callbacks, and sends them by Pushover or
 *              email with no page open. Until then they lived in each
 *              browser's localStorage (dash_alerts) and were judged here, so
 *              a rule only fired while a dashboard tab was open. This file no
 *              longer judges anything, which is what stops a change being
 *              announced twice (once by the plugin, once by a page). It asks
 *              the plugin for its recent firings (alertRules with
 *              firingsSince) and raises a browser notification for each one
 *              whose rule includes "browser".
 *
 *              Several tabs may be open at once, so the 3.46.0 machinery that
 *              stops one firing being announced twice stays:
 *                - one tab polls at a time: each writes a beat
 *                  (dash_alerts_beat) and a tab that sees another's fresh
 *                  beat stands by; Alerts always polls;
 *                - a firing is CLAIMED in dash_alerts_fired (by its sequence
 *                  number), and only the tab still holding the claim a moment
 *                  later raises it;
 *                - the newest sequence seen is shared (dash_alerts_seen), so
 *                  a tab that takes over does not raise what another already
 *                  has, and a newly opened page does not raise old firings.
 *              Every localStorage touch is wrapped: a private window, or a
 *              browser with site data blocked, falls back to this tab alone.
 *
 *              judgeDevice, judgeVariable, deviceNow and ruleKey stay as the
 *              statement of what a rule means: the plugin's Python
 *              (alerts_mixin.py) is a port of them, and both are held to the
 *              same answers by tests/lib/alert_rule_cases.json. The legacy
 *              helpers read and clear a browser's old rules for the Alerts
 *              page's one-click move to the plugin.
 * Author:      CliveS & Claude
 * Date:        25-09-2026
 * Version:     2.0
 */

(function (root) {
  'use strict';

  var LEGACY_KEY = 'dash_alerts';          // {rules: [...], active: bool} — before 3.47.0
  var FIRED_KEY = 'dash_alerts_fired';    // {"firing:1758800000123": {t, tab}}
  var BEAT_KEY = 'dash_alerts_beat';      // {tab, t}
  var SEEN_KEY = 'dash_alerts_seen';      // {seq}: the newest firing any tab has handled
  var COOLDOWN_MS = 30000;                // the claim window
  var FAST_MS = 5000;                     // poll while any rule wants the browser
  var SLOW_MS = 30000;                    // poll while none does (a rule may be added)
  var BEAT_STALE_MS = 25000;              // a tab quiet this long is taken over
  var CONFIRM_MS = 250;                   // how long a claim must survive before it is raised
  var WINDOW_S = 600;                     // raise nothing older than this (the plugin says too)
  var RULES_MAX = 100;

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

  /* ── what a rule means (pure; the plugin's Python is held to these) ─── */
  function ruleKey(r) { return r.kind + ':' + r.id + ':' + r.cond; }
  function deviceNow(d) {
    var ui = d.displayStateValUi;
    return { on: !!d.onState, ui: String(ui === null || ui === undefined ? '' : ui) };
  }
  function deviceText(now) { return now.ui || (now.on ? 'ON' : 'OFF'); }
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

  /* ── this browser's rules from before 3.47.0 ───────────────────────── */
  function loadLegacy(store) {
    var d = readJson(store === undefined ? storage() : store, LEGACY_KEY, {});
    return {
      rules: (d && Array.isArray(d.rules)) ? d.rules.filter(function (r) { return r && typeof r === 'object'; }) : [],
      active: !(d && d.active === false)
    };
  }
  function clearLegacy(store) {
    var s = store === undefined ? storage() : store;
    try { if (s) { s.removeItem(LEGACY_KEY); s.removeItem('dash_alerts_log'); } return true; }
    catch (e) { return false; }
  }
  /* The old rules as the plugin will take them: {kind, id, cond, name,
     enabled}, no channels (the plugin gives each its default). A rule the
     plugin would refuse is left out and counted, so one bad entry cannot
     stop the rest moving. */
  function migrationRules(legacy) {
    var out = [], skipped = 0, seen = {};
    ((legacy && legacy.rules) || []).forEach(function (r) {
      var kind = r.kind, id = r.id, cond = r.kind === 'variable' ? 'change' : r.cond;
      var ok = (kind === 'device' || kind === 'variable') && typeof id === 'number'
        && isFinite(id) && Math.floor(id) === id && id > 0
        && (kind === 'variable' || cond === 'on' || cond === 'off' || cond === 'change');
      var key = kind + ':' + id + ':' + cond;
      if (!ok || seen[key] || out.length >= RULES_MAX) { skipped++; return; }
      seen[key] = true;
      var name = (typeof r.name === 'string' && r.name.trim()) ? r.name.trim().slice(0, 80)
        : (kind === 'device' ? 'Device ' : 'Variable ') + id;
      out.push({ kind: kind, id: id, cond: cond, name: name, enabled: r.enabled !== false });
    });
    return { rules: out, skipped: skipped };
  }

  /* ── what a channel's state reads as ────────────────────────────────── */
  function channelLine(name, st) {
    var label = name === 'pushover' ? 'Pushover' : name === 'email' ? 'Email' : name;
    if (!st) return label + ': unknown';
    if (st.ready) {
      return label + ': ready' + (name === 'email' && st.source === 'secrets' ? ' (IndigoSecrets address)' : '');
    }
    return label + ': ' + (st.status || 'not set up');
  }
  /* "pushover sent · email failed (no address) · browser". */
  function firingOutcome(f) {
    var bits = [];
    (f.delivered || []).forEach(function (c) { bits.push(c + ' sent'); });
    (f.failed || []).forEach(function (x) { bits.push(x.channel + ' failed (' + x.reason + ')'); });
    if (f.pending) bits.push('sending…');
    if ((f.channels || []).indexOf('browser') >= 0) bits.push('browser');
    return bits.join(' · ');
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
    // Keep the record small: nothing older than a day matters.
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

  /* Which of the plugin's firings this browser should raise (pure).
     `reply` is alertRules' {seq, firings, now}; `seen` the shared {seq} or
     null. Returns {raise: [...], seen: newSeq}. With no `seen` yet this
     browser has never polled: it starts from the newest firing and raises
     nothing already past. A server whose numbers went backwards (its list
     was lost) is followed down, again without raising the past. */
  function pickFirings(reply, seen, windowS) {
    var seq = (reply && typeof reply.seq === 'number') ? reply.seq : 0;
    var rows = (reply && Array.isArray(reply.firings)) ? reply.firings : [];
    if (!seen || typeof seen.seq !== 'number' || seq < seen.seq) return { raise: [], seen: seq };
    var nowS = (reply && typeof reply.now === 'number') ? reply.now : Date.now() / 1000;
    var win = windowS || WINDOW_S;
    var raise = rows.filter(function (f) {
      return f && typeof f.seq === 'number' && f.seq > seen.seq
        && (f.channels || []).indexOf('browser') >= 0
        && typeof f.t === 'number' && nowS - f.t <= win;
    }).sort(function (a, b) { return a.seq - b.seq; });
    return { raise: raise, seen: Math.max(seen.seq, seq) };
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
  /* True when a notification was handed to the browser. */
  function notify(title, body) {
    var N = root.Notification;
    if (!N || N.permission !== 'granted') return false;
    try {
      var opts = { body: body, icon: 'apple-touch-icon-192.png', tag: title + '|' + body };
      if (_swReg && _swReg.showNotification) _swReg.showNotification(title, opts);
      else new N(title, opts);
      return true;
    } catch (e) { return false; }
  }

  /* ── the watcher ───────────────────────────────────────────────────── */
  var _started = null;
  /* watch(opts) polls the plugin's firings. opts:
       message(name, body)  resolves to the plugin's reply (default DashUI.message)
       alwaysPoll   true on alerts.html: poll whatever the other tabs do
       autoTick     false to drive poll() by hand (the tests)
       onFirings(reply)     every reply this tab received
       onRaise(firing)      after this tab has raised a notification
     Returns {stop, poll}. One watcher per page. */
  function watch(opts) {
    var o = opts || {};
    if (_started) return _started;
    var ask = o.message || function (name, body) {
      var ui = root.DashUI;
      if (!ui || typeof ui.message !== 'function') return Promise.reject(new Error('no DashUI'));
      return ui.message(name, body);
    };
    var tab = Math.random().toString(36).slice(2) + Date.now().toString(36);
    var timer = null, stopped = false, wantsBrowser = false, ownSeen = null;

    function raise(f) {
      var key = 'firing:' + f.seq;
      if (!claim(key, tab, Date.now(), storage())) return;
      setTimeout(function () {
        if (!stillOurs(key, tab, storage())) return;
        var cfg = root.INDIGO_CONFIG || {};
        notify(cfg.siteName || 'Dashboards', f.text);
        if (typeof o.onRaise === 'function') { try { o.onRaise(f); } catch (e) { /* page's problem */ } }
      }, CONFIRM_MS);
    }
    function readSeen(store) { return readJson(store, SEEN_KEY, null) || ownSeen; }
    async function poll() {
      if (stopped || !mayPoll(tab, Date.now(), storage(), !!o.alwaysPoll)) return;
      var seen = readSeen(storage());
      var reply;
      try {
        reply = await ask('alertRules', { firingsSince: (seen && typeof seen.seq === 'number') ? seen.seq : 0 });
      } catch (e) { return; }
      if (!reply || reply.ok === false) return;
      wantsBrowser = (reply.browserRules || 0) > 0;
      if (wantsBrowser) registerWorker();
      // Read again: another tab may have moved it on while we were asking.
      var pick = pickFirings(reply, readSeen(storage()) || seen, reply.browserWindow);
      ownSeen = { seq: pick.seen };
      writeJson(storage(), SEEN_KEY, ownSeen);
      pick.raise.forEach(raise);
      if (typeof o.onFirings === 'function') { try { o.onFirings(reply); } catch (e) { /* page's problem */ } }
    }
    // A timer chain, NOT DashUI.poll: an alert is most useful in a tab you are
    // not looking at, and poll() pauses in a hidden one. Fast while any rule
    // wants the browser, slow otherwise (a rule may be added elsewhere).
    function tick() {
      if (stopped) return;
      Promise.resolve(poll()).catch(function () {}).then(function () {
        if (!stopped) timer = setTimeout(tick, wantsBrowser || o.alwaysPoll ? FAST_MS : SLOW_MS);
      });
    }
    if (o.autoTick !== false) tick();
    _started = {
      stop: function () { stopped = true; if (timer) clearTimeout(timer); _started = null; },
      poll: poll
    };
    return _started;
  }

  /* The hub, room and Energy pages load this file and do nothing more: once
     the page has parsed, the watcher starts itself for a paired browser. A
     guest holds no key, and the demo's made-up house must never raise this
     house's alerts. alerts.html starts it itself, with alwaysPoll. */
  function autoStart() {
    if (_started) return;
    try {
      var cfg = root.INDIGO_CONFIG || {};
      if (!cfg.apiKey || cfg.apiKey === 'demo') return;
      // dashboard.js declares `class IndigoAPI` at the top level of a classic
      // script: a global binding, but not a property of window.
      var Api = (typeof IndigoAPI === 'function') ? IndigoAPI : root.IndigoAPI;   // eslint-disable-line no-undef
      if (typeof Api !== 'function' || !Api.isConfigured()) return;
      watch({});
    } catch (e) { /* alerts are a nicety: never break the page that carries them */ }
  }

  var API = {
    ruleKey: ruleKey, deviceNow: deviceNow, deviceText: deviceText,
    judgeDevice: judgeDevice, judgeVariable: judgeVariable,
    loadLegacy: loadLegacy, clearLegacy: clearLegacy, migrationRules: migrationRules,
    channelLine: channelLine, firingOutcome: firingOutcome, pickFirings: pickFirings,
    claim: claim, stillOurs: stillOurs, mayPoll: mayPoll,
    registerWorker: registerWorker, notify: notify,
    watch: watch, autoStart: autoStart,
    LEGACY_KEY: LEGACY_KEY, SEEN_KEY: SEEN_KEY, COOLDOWN_MS: COOLDOWN_MS,
    BEAT_STALE_MS: BEAT_STALE_MS, RULES_MAX: RULES_MAX
  };
  root.DashAlerts = API;
  if (typeof globalThis !== 'undefined') globalThis.DashAlerts = API;

  var d = root.document;
  if (d && typeof d.addEventListener === 'function') {
    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', autoStart);
    else setTimeout(autoStart, 0);
  }
})(typeof window !== 'undefined' ? window : globalThis);
