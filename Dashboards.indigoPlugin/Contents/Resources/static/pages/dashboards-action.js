/* Filename:    dashboards-action.js
 * Description: Shared "did that actually work?" feedback for the dashboard's
 *              control buttons. Runs an action group, then WATCHES the device
 *              states until the thing has really happened, taking the button
 *              over with a full-tile veil the whole time.
 *
 *              WHY THIS EXISTS
 *              The three door buttons (Open Front Door, Open/Close Garage) fed
 *              back a 12 px tick inside the tile you were pressing — under your
 *              own finger, for a nominal 1.2 s. It was usually far shorter than
 *              that: the hub rebuilds the favourites card every 3 s, which
 *              destroys the span holding the tick, and the restore timer then
 *              no-ops on isConnected. Errors were swallowed whole, so a 500 and
 *              a success looked identical.
 *
 *              It was also confirming the wrong thing. A 200 from Indigo means
 *              the action group was accepted, nothing more: Front_Door_Loop.py
 *              then blocks for up to 90 s retrying the unlock, and the garage
 *              controller may drop the press entirely on its 5 s debounce and
 *              still return 200. So the only honest confirmation comes from the
 *              contact sensors, which the page already receives on every poll.
 *
 *              TWO DESIGN POINTS WORTH KEEPING
 *              1. State lives in a module-level Map keyed off config, never in
 *                 the DOM. Every control surface here repaints on a 3 s poll, so
 *                 anything held on the node is gone within the beat. Pages tag
 *                 their buttons with data-dsh-act-key and call repaint(); the
 *                 phase paints itself back on to the freshly built node.
 *              2. The takeover is an absolutely-positioned veil appended to the
 *                 button, not a rewrite of its innards. That is what lets one
 *                 module drive .fav-tile, .scene-btn and .door-btn without
 *                 knowing anything about their markup.
 *
 *              evaluate() is pure and is the test seam — tests/test_action_watch.mjs
 *              drives it out of this file so it locks what actually ships.
 *
 *              v1.1 (13-08-2026): doorTile() — the pure state-to-tile map for
 *              the hub's state-driven door favourite (white closed, blue
 *              moving, red open, amber stuck). Watch specs may now carry
 *              theme:"door" (blue working veil) and holdDone (ms to hold a
 *              done veil; 0 clears at once so the tile's own colour is the
 *              confirmation). tests/test_door_tile.mjs drives all three.
 *
 *              v1.2 (13-08-2026): lockTile() — the lock-flavoured variant for
 *              a door with a LOCK and a CONTACT rather than a doorState
 *              device (the front door): white Locked, blue Unlocked, red
 *              Open. Same colour language, same test file.
 *
 *              v1.3 (30-08-2026): groupTile() and groupPlan() — one favourite
 *              tile driving several devices at once (the living room's three
 *              lamps and the fire behind a single press). Two pure functions:
 *              one decides what the tile SAYS and which way a press should go,
 *              the other turns that into the list of commands to send. They
 *              carry over the two rules the room page's All On / All Off
 *              button had to learn the hard way — an unreadable device gets no
 *              vote, and every member is commanded regardless of what it is
 *              believed to be doing. tests/test_fav_group_tile.mjs.
 * Author:      CliveS & Claude Fable 5; Claude Opus 5 (1.3)
 * Date:        30-08-2026
 * Version:     1.3
 */

(function (root) {
  'use strict';

  var doc = root.document;

  /* Phases:
       sending  the HTTP call is in flight
       working  Indigo accepted it; we are watching the sensors
       done     a rule matched with phase "done" — it really happened
       timeout  timeoutSec elapsed and nothing confirmed it
       error    the call itself failed                                      */
  var PHASES = ['sending', 'working', 'done', 'timeout', 'error'];

  /* How long a finished tile holds its result before reverting. A failure
     holds far longer than a success: you need time to read it, and you were
     probably walking away from the screen when it happened. */
  var HOLD_MS = { done: 4000, timeout: 10000, error: 10000 };

  var POLL_MS = 3000;              /* matches the pages' own device beat */
  var UI_TICK_MS = 500;            /* repaint cadence for the elapsed counter */
  var DEFAULT_TIMEOUT_SEC = 60;
  var FED_STALE_MS = 4500;         /* longer than POLL_MS, so one late poll
                                      from a page does not start a second one */

  var _watches = new Map();        /* key -> state object */
  var _timer = null;
  var _api = null;
  var _polling = false;
  var _lastFed = 0;                /* last time a page handed us devices */
  var _lastPoll = 0;

  function now() { return Date.now(); }

  /* ── config ─────────────────────────────────────────────────────────── */

  /* Watch specs are published top-level in config.js as actionWatch, keyed by
     action-group id. Top-level deliberately: a per-favourite key would be
     rebuilt field-by-field (and so destroyed) by both the plugin's save
     sanitiser and settings.html's collectFavourites, and it would only ever
     have worked on the hub. Keyed on the action group, one spec drives the
     hub tile, the scenes page and the room page alike. */
  function watchSpec(actionId) {
    if (actionId == null) return null;
    var cfg = root.INDIGO_CONFIG || {};
    var all = cfg.actionWatch || {};
    return all[String(actionId)] || null;
  }

  /* ── the rule evaluator (pure — the test seam) ──────────────────────── */

  /* Read a state off a device. Custom states live in .states; onState is a
     native attribute, so allow it by name too. Anything absent comes back
     undefined and is handled as UNKNOWN below — never as false. */
  function stateOf(dev, name) {
    if (!dev || !name) return undefined;
    var st = dev.states || {};
    if (Object.prototype.hasOwnProperty.call(st, name)) return st[name];
    if (name === 'onState') return dev.onState;
    return undefined;
  }

  /* The v2 API hands some custom states back as the STRINGS "True"/"False",
     so a === comparison silently never matches. Returns null for anything
     that is not recognisably a boolean, which the caller treats as unknown. */
  function truthy(v) {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'number') return v !== 0;
    if (typeof v === 'string') {
      var s = v.trim().toLowerCase();
      if (s === 'true' || s === 'on' || s === '1' || s === 'yes') return true;
      if (s === 'false' || s === 'off' || s === '0' || s === 'no') return false;
      return null;
    }
    return null;
  }

  /* A condition on one device state.

     THE TRAP THIS GUARDS: an absent state reads back undefined, and
     undefined == false compares EQUAL under loose comparison. A sensor that
     had never reported once would therefore satisfy {is:false} and the tile
     would announce a door movement that never happened. Absent is never a
     match, in either direction. */
  function condMet(cond, byId) {
    if (!cond || cond.id == null) return false;
    var raw = stateOf(byId.get(Number(cond.id)), cond.state);
    if (raw === undefined || raw === null) return false;
    if (typeof cond.is === 'boolean') {
      var got = truthy(raw);
      return got !== null && got === cond.is;
    }
    return String(raw) === String(cond.is);
  }

  /* Evaluate a watch spec against a device list. Rules run top-down, first
     match wins; `when: []` is the catch-all. Returns {phase, text}. */
  function evaluate(spec, devices, elapsedMs) {
    spec = spec || {};
    var rules = Array.isArray(spec.rules) ? spec.rules : [];
    var timeoutSec = Number(spec.timeoutSec) > 0
      ? Number(spec.timeoutSec) : DEFAULT_TIMEOUT_SEC;

    var byId = new Map();
    (devices || []).forEach(function (d) {
      if (d && d.id != null) byId.set(Number(d.id), d);
    });

    var matched = null;
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i] || {};
      var when = Array.isArray(r.when) ? r.when : [];
      var ok = true;
      for (var j = 0; j < when.length; j++) {
        if (!condMet(when[j], byId)) { ok = false; break; }
      }
      if (ok) { matched = r; break; }
    }

    /* A confirmation beats the clock. If the door reached its end state on the
       same tick the timer ran out, the honest answer is "it opened", not
       "no confirmation". */
    if (matched && matched.phase === 'done') {
      return { phase: 'done', text: matched.text || 'Done' };
    }
    if (elapsedMs >= timeoutSec * 1000) {
      return {
        phase: 'timeout',
        text: spec.timeoutText || 'No confirmation — check it'
      };
    }
    if (matched) {
      return { phase: matched.phase || 'working', text: matched.text || 'Working…' };
    }
    return { phase: 'working', text: spec.workingText || 'Working…' };
  }

  /* ── door favourite: state-to-tile map (pure — the other test seam) ──── */

  /* Map a door device's doorState (GarageDoor plugin: closed/open/moving/
     stuck/unknown) to what the hub tile shows and does. lastSettled is the
     last end state THIS page saw ("open"/"closed"), which is what names the
     direction while moving — a page opened mid-travel has none and honestly
     shows neutral "Moving…".

     key      CSS suffix (fav-door-<key>) — closed is the quiet default tile
     label    the state line under the name; text always carries the state,
              colour only reinforces it
     intent   which configured action a press fires ("open"/"close"), or null
              when a press must do nothing (moving, unknown, absent). Stuck
              fires close: the useful recovery is securing the house, and the
              watch reports honestly if it sticks again.

     An absent or unrecognised state is UNKNOWN, never a guess — a device
     missing from the poll must not render as a confident "Closed". */
  function doorTile(doorState, lastSettled) {
    var s = (doorState == null) ? '' : String(doorState).trim().toLowerCase();
    if (s === 'closed') return { key: 'closed', label: 'Closed', intent: 'open' };
    if (s === 'open')   return { key: 'open', label: 'Open', intent: 'close' };
    if (s === 'moving') {
      if (lastSettled === 'closed') return { key: 'opening', label: 'Opening…', intent: null };
      if (lastSettled === 'open')   return { key: 'closing', label: 'Closing…', intent: null };
      return { key: 'moving', label: 'Moving…', intent: null };
    }
    if (s === 'stuck') return { key: 'stuck', label: 'Stuck — check it', intent: 'close' };
    return { key: 'unknown', label: '—', intent: null };
  }

  /* Lock-flavoured door (v1.2): a door with a LOCK and a CONTACT rather than
     a doorState device — the front door. Same colour language: white is the
     secure resting state, blue a transitional one, red standing open.

     contactRaw  the contact device's state — true means the door is OPEN
     lockRaw     the lock device's state — true means LOCKED

     intent "open" fires the configured unlock/open sequence ONLY from the
     locked resting state. Open and unlocked are display-only: no action
     closes a front door, and re-firing the unlock outside its watched
     sequence invites overlapping runs of a script that blocks for 90 s.

     The contact is consulted FIRST, so a dead lock can never blind an open
     door; and an absent contact is UNKNOWN even with a healthy lock — a
     silent sensor must not render as a reassuring "Locked". */
  function lockTile(contactRaw, lockRaw) {
    var open = truthy(contactRaw);
    if (open === null) return { key: 'unknown', label: '—', intent: null };
    if (open === true) return { key: 'open', label: 'Open', intent: null };
    var locked = truthy(lockRaw);
    if (locked === null) return { key: 'unknown', label: '—', intent: null };
    if (locked === true) return { key: 'closed', label: 'Locked', intent: 'open' };
    return { key: 'unlocked', label: 'Unlocked', intent: null };
  }

  /* Group favourite (v1.3): ONE tile standing for several devices — the
     living room's three lamps and the fire behind a single press.

     members  [{id, onLevel?, openLoop?}] straight from the favourite's config
     byId     Map of device id -> the device as the poll returned it

     Two rules, both carried over from the room page's All On / All Off button,
     which had to learn them the hard way:

     1. AN UNREADABLE MEMBER GETS NO VOTE. The living room fire is a one-way
        radio relay: Indigo knows only what it last transmitted, so a fire lit
        from its own handset still reads off. Left in the vote, that one belief
        was enough to stop the room's button ever offering "All Off" — the single
        press that would have turned the fire off was never on offer. A member
        flagged openLoop, and any member whose state will not resolve to a plain
        true or false, is counted in the LABEL but never decides the direction.
     2. FALL BACK TO BELIEF ONLY WHEN THERE IS NOTHING BETTER. If no member is
        readable at all, the beliefs decide rather than the tile jamming on
        "turn everything on" for ever. With nothing resolved either, a press
        turns things ON: that is the visible, reversible direction, and a tile
        that does nothing is no use to somebody standing in a dark room.

     The label counts every member the poll returned, so three lamps on with the
     fire believed off reads "3 of 4 on" rather than a flat "On" that quietly
     writes the fire off. An absent member is left out of the count entirely —
     it is not evidence of anything, and must never pad the total.

     key     CSS suffix (fav-group-<key>): on / off / part / unknown
     label   the state line under the name
     intent  which way a press goes, "on" or "off" — never null: unlike a door
             mid-travel, there is no state here in which acting is unsafe
     on      how many members are believed on
     total   how many members the poll resolved */
  function groupTile(members, byId) {
    var list = Array.isArray(members) ? members : [];
    var resolved = 0, believedOn = 0, readable = [], beliefs = [];
    var unknown = 0;
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      if (!m) continue;
      var id = Number(m.id);
      var d = (byId && typeof byId.get === 'function' && isFinite(id)) ? byId.get(id) : null;
      if (!d) continue;
      var on = truthy(d.onState);
      // A member whose state does not resolve to a boolean is UNKNOWN, and
      // must not pad the total: "3 of 4 on" told the reader the fourth was
      // off when the honest answer was that nobody knew (v2.95.4).
      if (on === null) { unknown++; continue; }
      resolved++;
      if (on === true) believedOn++;
      beliefs.push(on);
      if (!m.openLoop) readable.push(on);
    }
    var voters = readable.length ? readable : beliefs;
    var allOn = voters.length > 0 && voters.every(function (v) { return v === true; });
    var intent = allOn ? 'off' : 'on';
    var unk = unknown ? ', ' + unknown + ' unknown' : '';
    var unkP = unknown ? ' (' + unknown + ' unknown)' : '';
    if (!resolved) return { key: 'unknown', label: '—', intent: 'on', on: 0, total: 0, unknown: unknown };
    if (believedOn === resolved) return { key: 'on', label: 'On' + unkP, intent: intent, on: believedOn, total: resolved, unknown: unknown };
    if (believedOn === 0) return { key: 'off', label: 'Off' + unkP, intent: intent, on: 0, total: resolved, unknown: unknown };
    return { key: 'part', label: believedOn + ' of ' + resolved + ' on' + unk,
             intent: intent, on: believedOn, total: resolved, unknown: unknown };
  }

  /* The commands one press of a group tile sends. Pure: it decides nothing
     about state, it only turns an already-decided direction into a plan.

     EVERY member is commanded, including the ones already believed to be in
     the state being asked for. Sending an off to something already off costs
     nothing, and it is the only way to be sure about a member that cannot be
     read — which is the whole reason the fire is in here.

     A member carrying onLevel is a dimmer that should land on a specific
     brightness rather than wherever it happened to be last: the living room's
     colour lamp is asked for 100. Off is a plain turnOff, which IS nought per
     cent and is unambiguous, where setBrightness(0) leaves some plugins
     reporting a light that is on at zero. */
  function groupPlan(members, intent) {
    var list = Array.isArray(members) ? members : [];
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      if (!m) continue;
      var id = Number(m.id);
      if (!isFinite(id) || !id) continue;
      if (intent === 'off') { out.push({ id: id, fn: 'turnOff' }); continue; }
      var lvl = Number(m.onLevel);
      if (isFinite(lvl) && lvl > 0 && lvl <= 100) out.push({ id: id, fn: 'setBrightness', level: Math.round(lvl) });
      else out.push({ id: id, fn: 'turnOn' });
    }
    return out;
  }

  /* ── stylesheet (injected once, guarded by id) ──────────────────────── */

  var STYLE_ID = 'dashaction-css';
  var STYLE = [
    '.dsh-act{position:relative}',
    /* The press animation on .fav-tile / .scene-btn would shrink the veil
       with it; and a covered button must not look pressable. */
    '.dsh-act-sending,.dsh-act-working{pointer-events:none}',
    '.dsh-act-sending:active,.dsh-act-working:active{transform:none}',
    '.dsh-act-veil{position:absolute;inset:0;border-radius:inherit;',
    'display:flex;align-items:center;justify-content:center;',
    'padding:8px 10px;text-align:center;overflow:hidden;z-index:2;',
    'font-family:inherit;font-size:13px;font-weight:700;line-height:1.25;',
    'letter-spacing:-.01em;color:#fff;background:var(--accent,#5856d6);',
    'animation:dsh-act-in .16s ease-out}',
    '@keyframes dsh-act-in{from{opacity:0}to{opacity:1}}',
    '.dsh-act-done .dsh-act-veil{background:var(--on-color,#34c759)}',
    '.dsh-act-timeout .dsh-act-veil{background:var(--warn,#ff9500)}',
    '.dsh-act-error .dsh-act-veil{background:var(--bad,#ff3b30)}',
    /* Door theme: the in-flight veil is BLUE to match the tile's own moving
       colour (and the hall lamp convention) — same value in both schemes,
       as the palette's other blues are. Result veils keep their colours. */
    '.dsh-act-t-door.dsh-act-sending .dsh-act-veil,',
    '.dsh-act-t-door.dsh-act-working .dsh-act-veil{background:#0a84ff}',
    '.dsh-act-txt{display:block;overflow-wrap:anywhere}',
    /* Indeterminate sweep: the door takes as long as it takes, so a
       percentage bar would be a fiction. */
    '.dsh-act-bar{position:absolute;left:0;right:0;bottom:0;height:3px;',
    'overflow:hidden;background:rgba(255,255,255,.28)}',
    '.dsh-act-bar::after{content:"";position:absolute;top:0;bottom:0;width:38%;',
    'background:rgba(255,255,255,.92);animation:dsh-act-sweep 1.1s ease-in-out infinite}',
    '@keyframes dsh-act-sweep{0%{left:-40%}100%{left:100%}}',
    '@media(prefers-reduced-motion:reduce){',
    '.dsh-act-veil{animation:none}',
    '.dsh-act-bar::after{animation:none;left:0;width:100%;opacity:.45}}',
  ].join('');

  function injectStyle() {
    if (!doc || doc.getElementById(STYLE_ID)) return;
    var s = doc.createElement('style');
    s.id = STYLE_ID;
    s.textContent = STYLE;
    (doc.head || doc.documentElement).appendChild(s);
  }

  /* ── painting ───────────────────────────────────────────────────────── */

  function label(st) {
    var txt = st.text || '';
    if (st.phase === 'working') {
      var secs = Math.floor((now() - st.startedAt) / 1000);
      /* Below two seconds the counter reads as flicker rather than progress. */
      if (secs >= 2) txt += ' ' + secs + 's';
    }
    return txt;
  }

  /* Apply (or clear) a key's phase on one button. Safe to call on a node that
     has just been rebuilt from scratch — that is the whole point. */
  function decorate(el, key) {
    if (!el) return false;
    var st = _watches.get(key);
    el.classList.remove('dsh-act', 'dsh-act-t-door');
    PHASES.forEach(function (p) { el.classList.remove('dsh-act-' + p); });

    var veil = el.querySelector(':scope > .dsh-act-veil');
    if (!st) {
      if (veil) veil.remove();
      if (el.dataset) delete el.dataset.dshActBusy;
      return false;
    }

    injectStyle();
    el.classList.add('dsh-act', 'dsh-act-' + st.phase);
    if (st.spec && st.spec.theme === 'door') el.classList.add('dsh-act-t-door');
    if (!veil) {
      veil = doc.createElement('span');
      veil.className = 'dsh-act-veil';
      veil.setAttribute('aria-live', 'polite');
      veil.innerHTML = '<span class="dsh-act-txt"></span>';
      el.appendChild(veil);
    }
    var txt = veil.querySelector('.dsh-act-txt');
    var next = label(st);
    if (txt && txt.textContent !== next) txt.textContent = next;

    var bar = veil.querySelector('.dsh-act-bar');
    var wantBar = (st.phase === 'sending' || st.phase === 'working');
    if (wantBar && !bar) {
      bar = doc.createElement('span');
      bar.className = 'dsh-act-bar';
      veil.appendChild(bar);
    } else if (!wantBar && bar) {
      bar.remove();
    }
    if (el.dataset) el.dataset.dshActBusy = wantBar ? '1' : '0';
    return true;
  }

  /* Repaint every tagged button on the page. Pages call this after a
     re-render; the internal timer calls it so the elapsed counter ticks. */
  function repaint() {
    if (!doc) return;
    var els = doc.querySelectorAll('[data-dsh-act-key]');
    for (var i = 0; i < els.length; i++) {
      decorate(els[i], els[i].getAttribute('data-dsh-act-key'));
    }
  }

  /* ── state machine ──────────────────────────────────────────────────── */

  function pending(key) {
    var st = _watches.get(key);
    return !!st && (st.phase === 'sending' || st.phase === 'working');
  }

  function settle(key, phase, text) {
    var st = _watches.get(key);
    if (!st) return;
    /* A spec may shorten how long a DONE veil holds (holdDone ms). At 0 the
       watch clears at once — for state-driven tiles the tile's own colour IS
       the confirmation, and a green interlude would say the same thing twice.
       Failure holds (timeout/error) are never shortened: they must be read. */
    var hold = HOLD_MS[phase] || 4000;
    if (phase === 'done' && st.spec && typeof st.spec.holdDone === 'number'
        && st.spec.holdDone >= 0) {
      hold = st.spec.holdDone;
    }
    if (hold === 0) {
      _watches.delete(key);
      repaint();
      return;
    }
    st.phase = phase;
    st.text = text;
    st.clearAt = now() + hold;
    repaint();
    ensureTimer();
  }

  function shortErr(e) {
    var m = (e && (e.message || e.toString())) || 'unknown error';
    m = String(m).replace(/\s+/g, ' ').trim();
    return m.length > 48 ? m.slice(0, 47) + '…' : m;
  }

  /* Advance every live watch against a device list. */
  function advance(devices) {
    var changed = false;
    _watches.forEach(function (st, key) {
      if (st.phase !== 'working') return;
      var res = evaluate(st.spec, devices, now() - st.startedAt);
      if (res.phase === 'done' || res.phase === 'timeout' || res.phase === 'error') {
        settle(key, res.phase, res.text);
        changed = true;
      } else if (res.text !== st.text) {
        st.text = res.text;
        changed = true;
      }
    });
    if (changed) repaint();
  }

  /* Fed by a page that already polls — costs nothing extra. */
  function tick(devices) {
    _lastFed = now();
    advance(devices);
  }

  function api() {
    if (_api) return _api;
    if (typeof root.IndigoAPI !== 'function') return null;
    try { _api = new root.IndigoAPI(); } catch (e) { _api = null; }
    return _api;
  }

  /* scenes.html renders once and never polls, so a watch there has nobody to
     feed it. Poll for ourselves, but only while something is actually being
     watched and only when no page has fed us recently. Idle cost is zero. */
  function selfPoll() {
    if (_polling) return;
    var needs = false;
    _watches.forEach(function (st) { if (st.phase === 'working') needs = true; });
    if (!needs) return;
    if (now() - _lastFed < FED_STALE_MS) return;
    if (now() - _lastPoll < POLL_MS) return;
    var a = api();
    if (!a) return;
    _lastPoll = now();
    _polling = true;
    a.getDevices()
      .then(function (devs) { advance(devs); })
      .catch(function () { /* the timeout is the backstop */ })
      .then(function () { _polling = false; });
  }

  function ensureTimer() {
    if (_timer || !_watches.size) return;
    _timer = setInterval(function () {
      var t = now();
      _watches.forEach(function (st, key) {
        if (st.clearAt && t >= st.clearAt) _watches.delete(key);
      });
      /* A working watch whose page has gone quiet still has to time out. */
      _watches.forEach(function (st, key) {
        if (st.phase !== 'working') return;
        if (t - st.startedAt >= timeoutMs(st)) {
          settle(key, 'timeout',
            (st.spec && st.spec.timeoutText) || 'No confirmation — check it');
        }
      });
      selfPoll();
      repaint();
      if (!_watches.size) { clearInterval(_timer); _timer = null; }
    }, UI_TICK_MS);
  }

  function timeoutMs(st) {
    var s = st.spec && Number(st.spec.timeoutSec);
    return (s > 0 ? s : DEFAULT_TIMEOUT_SEC) * 1000;
  }

  /* Fire a control action and take its button over until we know the outcome.

     opts: key       stable id for this control, e.g. "scene:1463818396"
           actionId  action group to run (used for the watch spec lookup too)
           watchId   override when the spec is keyed differently to the action
           exec      optional () => Promise, for controls that are not a plain
                     action group (room.html pulses relays directly)
           spec      optional watch spec supplied by the caller, for controls
                     that already know their own sensor (room.html doors carry
                     statusContactId in config) — skips the actionWatch lookup
           title     display name, used in fallback text
           sentText  what to say when there is no watch spec to follow    */
  function run(opts) {
    opts = opts || {};
    var key = opts.key;
    if (!key) return Promise.resolve(false);
    if (pending(key)) return Promise.resolve(false);   /* re-entry guard */

    injectStyle();
    var spec = opts.spec
      || watchSpec(opts.watchId != null ? opts.watchId : opts.actionId);
    /* Held by identity, not by key. A press that failed and was retried leaves
       its own settle/resolve still in flight; without this the older one lands
       afterwards and stamps a stale verdict over the newer press. */
    var mine = {
      key: key,
      title: opts.title || (spec && spec.title) || '',
      phase: 'sending',
      text: (spec && spec.sendingText) || 'Sending…',
      startedAt: now(),
      clearAt: 0,
      spec: spec
    };
    _watches.set(key, mine);
    repaint();
    ensureTimer();

    var p;
    try {
      if (typeof opts.exec === 'function') {
        p = Promise.resolve(opts.exec());
      } else {
        var a = opts.api || api();
        if (!a) throw new Error('no Indigo client');
        p = a.executeActionGroup(opts.actionId);
      }
    } catch (e) {
      p = Promise.reject(e);
    }

    return p.then(function () {
      var st = _watches.get(key);
      if (st !== mine || st.phase !== 'sending') return true;   /* superseded */
      if (!spec) {
        /* Nothing to watch — say it was sent and be honest that that is all
           we know. Still far more than the old 12 px tick. */
        settle(key, 'done', opts.sentText || 'Sent');
        return true;
      }
      st.phase = 'working';
      /* The clock starts when Indigo accepted it, not when the user pressed:
         a slow link must not eat the door's travel budget. */
      st.startedAt = now();
      st.text = (spec.workingText) || 'Working…';
      repaint();
      ensureTimer();
      return true;
    }).catch(function (e) {
      if (_watches.get(key) !== mine) return false;             /* superseded */
      settle(key, 'error', 'Failed — ' + shortErr(e));
      return false;
    });
  }

  /* Show a one-off result on a button without running anything through the
     state machine. This is for controls that stay optimistic — a light tile
     flips instantly and the poll corrects it — but whose FAILURES were
     previously swallowed in silence, which is the same complaint that started
     all this, one rung down. */
  function note(key, phase, text) {
    if (!key || PHASES.indexOf(phase) < 0) return;
    if (pending(key)) return;                 // never overwrite a run() still in flight (v2.95.4)
    injectStyle();
    _watches.set(key, {
      key: key,
      title: '',
      phase: phase,
      text: text || '',
      startedAt: now(),
      clearAt: now() + (HOLD_MS[phase] || 4000),
      spec: null
    });
    repaint();
    ensureTimer();
  }

  /* Test/teardown hook. */
  function reset() {
    _watches.clear();
    if (_timer) { clearInterval(_timer); _timer = null; }
    _lastFed = 0; _lastPoll = 0; _polling = false;
  }

  var API = {
    run: run,
    note: note,
    tick: tick,
    repaint: repaint,
    decorate: decorate,
    pending: pending,
    evaluate: evaluate,
    doorTile: doorTile,
    lockTile: lockTile,
    groupTile: groupTile,
    groupPlan: groupPlan,
    watchSpec: watchSpec,
    reset: reset,
    HOLD_MS: HOLD_MS,
  };

  root.DashAction = API;
  if (typeof globalThis !== 'undefined') globalThis.DashAction = API;
})(typeof window !== 'undefined' ? window : globalThis);
