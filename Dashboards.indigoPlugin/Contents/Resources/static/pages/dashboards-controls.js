/* Filename:    dashboards-controls.js
 * Description: One tile system for the device controls (v3.37.0). The room,
 *              Active and Heating pages each carried their own copy of the
 *              on/off test, the toggle and brightness handlers and the heating
 *              zone tile, and the copies had already drifted: the room page's
 *              zone read one of the two places a TRV reports that it is
 *              calling for heat, and never read a setpoint back to check it
 *              had landed. Everything here is shared; the pages call it.
 *
 *              Needs dashboards-action.js loaded first.
 *              DashTile.bind(indigo) once the page has its IndigoAPI, then:
 *                state(v) / isOn(v)          the one on/off rule (true / false / null)
 *                toggle(el) / slide(el) / slideCommit(el)   room + Active switches
 *                pressDevice(el, id, opts)                  a device tile (hub)
 *                zone.render(d, opts) / zone.bump(id, dir) and the helpers
 * Author:      CliveS & Claude Opus 5.5
 * Date:        23-09-2026
 * Version:     1.6 (a zone's temperature is as old as its last temperature report; seed zeros are
 *              no reading; no demand state, no "Not calling"; notes expire); 1.5 (one "cannot be believed" rule, not answering included; the zone tile uses it;
 *              server times read in the server's zone); 1.4 (a room held by hand says until when); 1.3 (a run of setpoint taps
 *              sends one command; a gateway that is offline is said at once); 1.2 (only the last setpoint press checks); 1.1 (pressDevice)
 */
(function (root) {
  'use strict';

  var api = null;
  function bind(indigoApi) { api = indigoApi; }

  function esc(s) {
    if (root.DashUI && root.DashUI.esc) return root.DashUI.esc(s);
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function icon(n) { return root.DashIcons ? root.DashIcons.svg(n) : ''; }

  /* THE on/off rule, and there is one copy of it: DashAction's reader,
     which dashboards-action.js defines and this file requires. A native
     onState arrives as a real boolean, a plugin's custom state comes back
     from the v2 API as "True"/"False", and a few report 1/0 or "on".
     state() answers true, false, or null for "cannot say", which a tile
     must show as unknown rather than as off. */
  function state(v) {
    var r = root.DashAction && root.DashAction.truthy ? root.DashAction.truthy(v) : null;
    return r === true ? true : r === false ? false : null;
  }
  function isOn(v) { return state(v) === true; }

  /* Can this device's readings be believed right now? An Indigo
     state is a LAST KNOWN VALUE: a plug that drops off the network keeps its
     last watts and its last on-state, and each plugin says "I cannot reach
     it" in its own way — ShellyDirect deviceOnline (a bool, or the string
     "false" through the v2 API), Tasmota and z2m availability "offline",
     ESPHome connected false — plus Indigo's own errorState. Absent means
     reachable: a device that never reports reachability is not marked down. */
  function isReachable(d) {
    if (!d) return false;
    if (String(d.errorState || '').trim()) return false;
    var s = d.states || {};
    var flag = function (v) { return v === false || String(v).toLowerCase() === 'false'; };
    if ('deviceOnline' in s && flag(s.deviceOnline)) return false;
    if ('connected' in s && flag(s.connected)) return false;
    if ('availability' in s && String(s.availability).toLowerCase() === 'offline') return false;
    return true;
  }

  /* Why a tile cannot show a device as live: 'disabled', 'error',
     'not answering', or ''. The room page's motion tile had this rule; light,
     sensor and appliance tiles painted a disabled device's frozen state as
     current. 3.73.4 adds 'not answering': a Shelly that has dropped off the
     network keeps its last on/off and watts with an EMPTY errorState, so
     isReachable had to be part of the one rule every tile asks. */
  function unknownReason(d) {
    if (!d) return 'no reading';
    if (d.enabled === false) return 'disabled';
    if (String(d.errorState || '').trim()) return 'error';
    if (!isReachable(d)) return 'not answering';
    return '';
  }

  /* ---- toggle and brightness ------------------------------------------ */
  var CONFIRM_MS = 4000;
  var debounce = {};

  /* Send the state the reader ASKED FOR, never a toggle. A toggle flips
     whatever the device is now, so a light a motion rule had just switched
     on went OFF when somebody tapped it on, and the failure veil then blamed
     the device. The control knows the intent; this sends it. */
  function command(a, id, wantOn) {
    return wantOn ? a.turnOn(id) : a.turnOff(id);
  }

  function toggle(el) {
    if (!api) return Promise.resolve();
    el.disabled = true;
    var id = parseInt(el.dataset.id, 10);
    var expected = el.checked;
    var done = function () { root.setTimeout(function () { el.disabled = false; }, 500); };
    return Promise.resolve(command(api, id, expected))
      .then(function () { confirmToggle(el, id, expected); })
      .catch(function () { el.checked = !el.checked; })
      .then(done);
  }

  /* A toggle is CONFIRMED from the device, not assumed (v2.95.3). A device
     whose communication is disabled, or whose plugin has stopped, swallows
     the command without an error — the switch used to stay flipped for ever.
     `undo(actual)` puts the control back to what the device really says. */
  var toggleSeq = {};        // device id -> presses so far: only the LAST one is judged
  function confirmFromDevice(a, id, expected, undo) {
    // On then off inside four seconds: the first press's check found the
    // device off, where it expected on, and raised "No confirmation" over a
    // device that had done both (review 26-11-2026). The brightness slider
    // and the heating tile already judge only their last press.
    var seq = toggleSeq[id] = (toggleSeq[id] || 0) + 1;
    root.setTimeout(function () {
      if (toggleSeq[id] !== seq) return;
      Promise.resolve(a.getDevice(id)).then(function (d) {
        if (toggleSeq[id] !== seq) return;
        if (d && typeof d.onState === 'boolean' && d.onState !== expected) {
          undo(d.onState);
          try { if (root.DashAction) root.DashAction.note('device:' + id, 'timeout', 'No confirmation — check it'); } catch (_) {}
        }
      }).catch(function () { /* the next poll repaints from the server anyway */ });
    }, CONFIRM_MS);
  }
  function confirmToggle(el, id, expected) {
    confirmFromDevice(api, id, expected, function (actual) { el.checked = actual; });
  }

  /* A device TILE pressed (the hub's favourites, v3.41.0): the same rules as
     the switch on a room page — flip it at once so the press is felt, then
     check back with the device and put it right if the command went nowhere.
     The hub's copy flipped and never checked, so a swallowed command left a
     tile saying On over a lamp that was off until the next poll disagreed.
     opts.api overrides the bound API (the hub makes one per press);
     opts.key is the DashAction key for failure notes. */
  function paintTile(el, on) {
    el.classList.toggle('on', on);
    var st = el.querySelector && el.querySelector('.fav-state');
    if (st) st.textContent = on ? 'On' : 'Off';
  }
  function pressDevice(el, id, opts) {
    opts = opts || {};
    var a = opts.api || api;
    var key = opts.key || ('device:' + id);
    if (!a || !el) return Promise.resolve(false);
    var expected = !el.classList.contains('on');
    el.classList.add('busy');
    return Promise.resolve(command(a, id, expected)).then(function () {
      paintTile(el, expected);
      confirmFromDevice(a, id, expected, function (actual) {
        if (el.isConnected !== false) paintTile(el, actual);
      });
      return true;
    }).catch(function (e) {
      // An auth failure is the page's to handle; anything else used to vanish,
      // so a dead network looked exactly like success.
      if (!(e && (e.status === 401 || e.status === 403))) {
        try { if (root.DashAction) root.DashAction.note(key, 'error', 'Failed — ' + ((e && e.message) || 'no response')); } catch (_) {}
      }
      return false;
    }).then(function (ok) { el.classList.remove('busy'); return ok; });
  }

  function slide(el) {
    var pct = parseInt(el.value, 10);
    el.style.background = 'linear-gradient(to right, var(--accent) ' + pct + '%, var(--off-color) ' + pct + '%)';
    var lbl = root.document && root.document.getElementById('pct-' + el.dataset.id);
    if (lbl) lbl.textContent = pct + '%';
  }

  /* A brightness change is confirmed from the device too. It used to be
     sent and forgotten, so a lamp that never moved kept the slider's level
     until the next poll repainted it, and a failure vanished. Only the LAST
     commit per device reads back, so a drag that sends several levels is
     judged on the one it ended on. */
  var SLIDE_TOLERANCE = 2;   // percent: dimmers round, and some step in 2s
  var slideSeq = {};         // device id -> commits so far
  function slideCommit(el) {
    var id = parseInt(el.dataset.id, 10);
    var value = parseInt(el.value, 10);
    root.clearTimeout(debounce[id]);
    debounce[id] = root.setTimeout(function () {
      if (!api) return;
      var a = api;
      var seq = slideSeq[id] = (slideSeq[id] || 0) + 1;
      Promise.resolve(a.setBrightness(id, value)).then(function () {
        root.setTimeout(function () {
          if (slideSeq[id] !== seq) return;          // a later commit will judge
          Promise.resolve(a.getDevice(id)).then(function (d) {
            var actual = d && d.brightness != null ? parseInt(d.brightness, 10) : NaN;
            if (isNaN(actual) || Math.abs(actual - value) <= SLIDE_TOLERANCE) return;
            if (slideSeq[id] !== seq) return;
            el.value = String(actual);
            slide(el);
            try { if (root.DashAction) root.DashAction.note('device:' + id, 'timeout', 'No confirmation — it is at ' + actual + '%'); } catch (_) {}
          }).catch(function () { /* the next poll repaints from the server anyway */ });
        }, CONFIRM_MS);
      }).catch(function (e) {
        // An auth failure is the page's to handle; anything else is said.
        if (e && (e.status === 401 || e.status === 403)) return;
        try { if (root.DashAction) root.DashAction.note('device:' + id, 'error', 'Failed — ' + ((e && e.message) || 'no response')); } catch (_) {}
      });
    }, 300);
  }

  /* ---- heating zone ---------------------------------------------------- */
  var SETPOINT_MIN = 8;      // RAMSES TRVs clamp at 8°C — 5 was silently raised
  var SETPOINT_MAX = 28;
  var PENDING_MS   = 305000;   // bound confirmation waiting; RAMSES retries for five minutes
  var READBACK_MS  = 5000;
  var SEND_DELAY_MS = 1200;    // a run of taps settles before one command is sent
  var TRV_STALE_MS = 3 * 3600 * 1000;   // flag a TRV unheard for more than 3 hours
  var pending = {};          // device id -> { v, t }
  var notices = {};          // inline feedback, never an opaque tile overlay
  var noticeAt = {};         // device id -> when its note was written
  var NOTE_KEEP_MS = 120000; // a settled note goes after this (3.73.5): "Confirmed at 21
                             // degrees" used to stay for good, long after the setting changed
  var presses = {};          // device id -> how many presses so far (see bump)
  var holds = {};            // device id -> { until: ms, or null for a permanent one }

  /* Rooms the heating controller is leaving alone because somebody set them
     by hand (v3.72.0), from the evoHomeStatus reply's handHolds. The page
     hands the list over each time it has one; an empty or missing list
     clears it, so a hold that was cancelled does not linger on the tile. */
  function setHolds(list) {
    var next = {};
    (Array.isArray(list) ? list : []).forEach(function (h) {
      if (!h || !isFinite(Number(h.id))) return;
      var until = h.until == null ? null : Number(h.until) * 1000;
      if (until !== null && !isFinite(until)) return;
      next[Number(h.id)] = { until: until };
    });
    holds = next;
  }
  /* "2:05pm", "noon", "midnight": a time as a person says it. */
  function clockWords(ms) {
    var d = new Date(ms), h = d.getHours(), m = d.getMinutes();
    if (h === 0 && m === 0) return 'midnight';
    if (h === 12 && m === 0) return 'noon';
    return (h % 12 || 12) + (m ? ':' + (m < 10 ? '0' : '') + m : '') + (h < 12 ? 'am' : 'pm');
  }
  function holdText(id) {
    var h = holds[id];
    if (!h) return '';
    if (h.until === null) return 'set by hand, held until it is changed';
    if (h.until <= Date.now()) return '';
    return 'set by hand, held until ' + clockWords(h.until);
  }

  function currentTemp(d) {
    var s = d.states || {};
    // A RAMSES zone that has never reported a temperature holds the 0.0 it
    // was created with. That is not a reading (3.73.5).
    if (neverMeasured(s)) return null;
    var cand = [s.temperatureInput1, s.temperature, d.displayStateValRaw];
    for (var i = 0; i < cand.length; i++) {
      var n = parseFloat(cand[i]);
      if (!isNaN(n) && n > -50 && n < 100) return n;
    }
    return null;
  }
  function setpoint(d) {
    var seeded = neverMeasured(d.states || {});
    if (d.setpointHeat != null) {
      var own = parseFloat(d.setpointHeat);
      if (!isNaN(own) && !(seeded && own <= 0)) return own;   // "n/a" is no setpoint; nor is a seed 0
    }
    if (seeded && !(parseFloat((d.states || {}).setpointHeat) > 0)) return null;
    var n = parseFloat((d.states || {}).setpointHeat);
    return isNaN(n) ? null : n;
  }
  /* RAMSES ESP creates a zone with temperature 0.0, setpoint 0.0 and
     temperatureSeenEpoch 0, and fills them in as the valve reports. */
  function neverMeasured(s) {
    return ('temperatureSeenEpoch' in s) && !(Number(s.temperatureSeenEpoch) > 0);
  }
  /* Heating = the valve is open, or the zone says it is calling for heat
     and really is below its setpoint. The call-for-heat flag is read from
     the states first and the device second: the room page's old copy read
     only the second and missed it on every RAMSES zone. */
  /* Can this zone say whether it is calling for heat? A Z-Wave floor
     thermostat reports neither a valve nor a call-for-heat state, and was told
     "Not calling for heat" while it heated (3.73.5). */
  function knowsDemand(d) {
    var s = d.states || {};
    return s.hvacHeaterIsOn !== undefined || d.hvacHeaterIsOn !== undefined
        || ('valve-position' in s) || ('valvePosition' in s);
  }
  function heating(d) {
    var s = d.states || {};
    var valve = parseFloat(s['valve-position'] || s.valvePosition || 0);
    var hv = s.hvacHeaterIsOn !== undefined ? s.hvacHeaterIsOn : d.hvacHeaterIsOn;
    var cur = currentTemp(d), sp = setpoint(d);
    if (!isNaN(valve) && valve > 0) return true;
    return isOn(hv) && cur != null && sp != null && cur < sp - 0.2;
  }
  function tempClass(t) {
    if (t == null) return '';
    if (t < 16) return 'cold';
    if (t < 21) return '';
    if (t < 24) return 'warm';
    return 'hot';
  }
  /* RAMSES TRVs report lastSeen as a local "YYYY-MM-DD HH:MM:SS" string; a
     TRV that has dropped off the radio stops updating it. */
  function lastSeen(d) {
    var v = (d.states || {}).lastSeen;
    if (!v) return null;
    // Read in the SERVER's zone (DashUI.serverTime): read in the browser's,
    // every valve looked eleven hours silent from Australia.
    var t = (root.DashUI && root.DashUI.serverTime) ? root.DashUI.serverTime(v)
                                                    : Date.parse(String(v).replace(' ', 'T'));
    return isNaN(t) ? null : t;
  }
  /* When the zone's TEMPERATURE was last reported, in ms: 0 for never, null
     when the zone does not say. RAMSES ESP keeps temperatureSeenEpoch for
     exactly this. lastSeen also moves on setpoint and mode reports, so a
     valve whose sensor had died kept a frozen temperature looking fresh. */
  /* The radio gateway this zone is heard through has gone (RAMSES ESP's own
     states). One rule for the tile and for anything else that asks whether
     a zone's setpoint can be believed (3.73.13). */
  function gatewayOff(d) {
    var s = (d && d.states) || {};
    return String(s.gatewayStatus == null ? '' : s.gatewayStatus).toLowerCase() === 'offline'
        || String(s.online == null ? '' : s.online).toLowerCase() === 'false';
  }
  /* '' when the zone can be believed, else why not: unknownReason's words,
     or 'gateway offline'. */
  function notLiveReason(d) {
    return unknownReason(d) || (gatewayOff(d) ? 'gateway offline' : '');
  }

  function tempSeen(d) {
    var s = d.states || {};
    if ('temperatureSeenEpoch' in s) {
      var e = Number(s.temperatureSeenEpoch);
      return (isFinite(e) && e > 0) ? e * 1000 : 0;
    }
    return lastSeen(d);
  }
  /* Is the zone's temperature too old to count? Unheard for TRV_STALE_MS, or
     called silent by the heating plugin. A zone that gives no time is never
     stale: absence is not evidence. */
  function stale(d, now) {
    var s = d.states || {};
    if (String(s.trvStatus || '').toLowerCase() === 'silent') return true;
    var t = tempSeen(d);
    if (t == null || t === 0) return false;
    return ((now == null ? Date.now() : now) - t) > TRV_STALE_MS;
  }
  function shownSetpoint(d) {
    var p = pending[d.id];
    if (p) {
      if (Date.now() - p.t < PENDING_MS) return p.v;
      delete pending[d.id];
    }
    return setpoint(d);
  }

  /* The zone tile. opts.name overrides the device name; opts.info adds the
     details button (the page must define openDeviceDetails). */
  function renderZone(d, opts) {
    opts = opts || {};
    var cur = currentTemp(d), actualSp = setpoint(d), sp = shownSetpoint(d);
    var s = d.states || {};
    // A zone that cannot be believed says so (3.73.4). Its last temperature
    // stays, greyed, but it claims no call for heat: a disabled valve, one in
    // error or one whose gateway has gone was drawn as live, flame and all.
    var why = unknownReason(d);
    var gwOff = !why && gatewayOff(d);
    var notLive = !!why || gwOff;
    var hot = !notLive && heating(d);
    var valve = parseFloat(s['valve-position'] || s.valvePosition || 0);
    var humidity = parseFloat(s.humidityInput1);
    // hvacMode is the system's heat/off setting, "Heat" on every RAMSES zone,
    // so it is only worth saying when it is Off.
    var status = why === 'disabled' ? 'Disabled in Indigo'
               : why === 'error' ? 'The device reports an error'
               : why ? 'Not answering'
               : gwOff ? 'Heating gateway offline'
               : /off/i.test(d.hvacMode || '') ? 'Off'
               : !knowsDemand(d) ? ''
               : (hot ? 'Calling for heat' : 'Not calling for heat');
    var meta = status ? [esc(status)] : [];
    var held = holdText(d.id);
    if (held) meta.push('<span class="zone-hold">' + esc(held) + '</span>');
    if (isFinite(humidity)) meta.push(esc(humidity.toFixed(0) + '% RH'));
    if (!isNaN(valve) && valve > 0) meta.push(esc('valve ' + valve.toFixed(0) + '%'));
    var ls = tempSeen(d);
    if (ls != null && ls > 0) {
      var old = stale(d);
      var ago = root.DashUI && root.DashUI.ago ? root.DashUI.ago(Date.now() - ls) : '';
      // "measured" where the zone says when its temperature came in, "heard"
      // where it only says when anything did.
      meta.push('<span class="trv-age' + (old ? ' stale' : '') + '">' + (old ? icon('warn') + ' ' : '') +
                (('temperatureSeenEpoch' in s) ? 'measured ' : 'heard ') + esc(ago) + '</span>');
    } else if (stale(d)) {
      meta.push('<span class="trv-age stale">' + icon('warn') + ' valve silent</span>');
    }
    // A settled note goes once it is old: nothing else ever removed one.
    if (notices[d.id] && !pending[d.id] && (Date.now() - (noticeAt[d.id] || 0)) > NOTE_KEEP_MS) {
      delete notices[d.id];
      delete noticeAt[d.id];
    }
    // Buttons go for a zone Indigo will not command. Behind an offline
    // gateway they stay: the press explains itself in a sentence (bump).
    var dis = (sp == null || why) ? ' disabled' : '';
    var name = esc(opts.name != null ? opts.name : d.name);
    var info = opts.info
      ? '<button class="info-btn" aria-label="Details for ' + name + '" onclick="event.stopPropagation(); openDeviceDetails(' + d.id + ')">&#9432;</button>'
      : '';
    return '' +
      '<div class="zone' + (hot ? ' heating' : '') + (notLive ? ' unknown' : '') + '" data-dsh-act-key="device:' + d.id + '">' +
        '<div class="zone-head">' +
          '<div class="name-row"><div class="zone-name">' + (opts.history ?
            '<a class="zone-history-link" href="heating.html?zone=' + Number(d.id) + '">' + name + '</a>' : name) + '</div>' + info + '</div>' +
          '<div class="zone-flame' + (hot ? ' on' : '') + '">' + icon('flame') + '</div>' +
        '</div>' +
        '<div class="temps"><div class="cur-temp ' + tempClass(cur) + '">' +
          (cur == null ? '—' : cur.toFixed(1)) + '<span class="cur-unit">°C</span></div></div>' +
        '<div class="setpoint">' +
          '<button class="setpoint-btn" onclick="DashTile.zone.bump(' + d.id + ', -1)" aria-label="Lower ' + name + ' setpoint"' + dis + '>−</button>' +
          '<div><div class="setpoint-label">Setpoint</div>' +
            '<div class="setpoint-val" id="sp-' + d.id + '" aria-live="polite" aria-atomic="true" data-sp="' + (actualSp == null ? '' : actualSp) +
              '" data-gw="' + esc(String(s.gatewayStatus == null ? '' : s.gatewayStatus).toLowerCase()) + '">' +
            (sp == null ? '—' : sp.toFixed(1)) + '°</div></div>' +
          '<button class="setpoint-btn" onclick="DashTile.zone.bump(' + d.id + ', 1)" aria-label="Raise ' + name + ' setpoint"' + dis + '>+</button>' +
        '</div>' +
        '<div class="zone-meta">' + meta.map(function (m) { return '<span>' + m + '</span>'; }).join('') + '</div>' +
        '<div class="zone-notice" id="zone-note-' + d.id + '" role="status">' + esc(notices[d.id] || '') + '</div>' +
      '</div>';
  }

  /* One step up or down. Integer steps only (the REST API rejects fractional
     setpoints), rounded in the direction of the tap, chained from any value
     still pending, and READ BACK: a stopped heating plugin swallows the
     command without an error, and the tile used to show the new number as
     if it had landed.

     Only the LAST press on a radiator checks (v3.41.1). Every press used to
     check its own value 2.5 s later, so four quick taps from 8 to 12 had the
     first one find 12 where it expected 9 and report the change as refused
     — when the radiator had taken all four. Live-found on an iPhone.

     Only the last press SENDS, too (v3.71.4). Each tap used to go out as its
     own command, so a climb from 12 to 22 put 13, 17, 21 and 22 on the
     heating radio one after another, each resent while unconfirmed. The
     tile shows every tap at once, and one command leaves SEND_DELAY_MS
     after the last of them.

     A zone whose gateway is offline is not sent to at all: the heating
     plugin would refuse it, and the tile used to wait five minutes to say
     so. gatewayStatus is RAMSES ESP's state; a zone without it is sent as
     before. */
  function bump(id, dir) {
    var el = root.document && root.document.getElementById('sp-' + id);
    if (!el || !api) return Promise.resolve(false);
    var actual = parseFloat(el.dataset.sp);
    if (isNaN(actual)) return Promise.resolve(false);
    var base = pending[id] ? pending[id].v : actual;
    var next = base % 1 === 0 ? base + dir : (dir > 0 ? Math.ceil(base) : Math.floor(base));
    next = Math.max(SETPOINT_MIN, Math.min(SETPOINT_MAX, next));
    if (next === base) return Promise.resolve(false);          // at the clamp: nothing to send
    var mine = presses[id] = (presses[id] || 0) + 1;
    function note(text) {
      if (presses[id] !== mine) return;
      notices[id] = text;
      noticeAt[id] = Date.now();
      var node = root.document.getElementById('zone-note-' + id);
      if (node) node.textContent = text;
    }
    if (el.dataset.gw === 'offline') {
      delete pending[id];
      el.textContent = actual.toFixed(1) + '°';
      note('Not sent. The heating gateway is offline or cannot hear the heating controller, ' +
           'so the radiator would not get it.');
      return Promise.resolve(false);
    }
    pending[id] = { v: next, t: Date.now() };
    el.textContent = next.toFixed(0) + '°';
    note('Waiting for ' + next.toFixed(0) + ' degrees to be confirmed.');
    root.setTimeout(function () {
      if (presses[id] !== mine) return;      // a later tap took over: it sends, not this one
      // Plus then minus: back at what the radiator already has. Nothing to
      // send, and nothing to wait for (3.73.9).
      var settled = root.document.getElementById('sp-' + id) || el;
      if (parseFloat(settled.dataset.sp) === next) {
        delete pending[id];
        note('');
        return;
      }
      return send();
    }, SEND_DELAY_MS);
    return Promise.resolve(true);

    function send() {
    return Promise.resolve(api.setHeatSetpoint(id, next)).then(function () {
      var attempts = 0;
      function check() {
        if (presses[id] !== mine) return Promise.resolve();
        attempts++;
        return Promise.resolve(api.getDevice(id)).then(function (d) {
          if (presses[id] !== mine) return;
          var got = d ? setpoint(d) : null;
          var live = root.document.getElementById('sp-' + id) || el;
          if (got != null && isFinite(got) && Math.abs(got - next) < 0.5) {
            delete pending[id];
            live.dataset.sp = String(got);
            live.textContent = got.toFixed(1) + '°';
            note('Confirmed at ' + got.toFixed(0) + ' degrees.');
            return;
          }
          if (attempts < 60) {
            root.setTimeout(check, READBACK_MS);
            return;
          }
          delete pending[id];
          live.textContent = got == null || !isFinite(got) ? '—' : got.toFixed(1) + '°';
          note('Not confirmed after five minutes.' + (got == null || !isFinite(got) ?
            ' The current target is unavailable.' : ' The controller still reports ' + got.toFixed(1) + ' degrees.') +
            ' The controller may not have received it, or a heating rule changed it.');
        }).catch(function () {
          if (presses[id] !== mine) return;
          if (attempts < 60) { root.setTimeout(check, READBACK_MS); return; }
          delete pending[id];
          note('Cannot check the temperature change. The connection is unavailable.');
        });
      }
      root.setTimeout(check, READBACK_MS);
      return true;
    }).catch(function (error) {
      if (presses[id] !== mine) return false;
      delete pending[id];
      var live = root.document.getElementById('sp-' + id) || el;
      live.textContent = actual.toFixed(1) + '°';
      note('Not sent: ' + String(error && error.message || 'connection failed'));
      return false;
    });
    }
  }

  root.DashTile = {
    bind: bind,
    state: state,
    isOn: isOn,
    isReachable: isReachable,
    unknownReason: unknownReason,
    toggle: toggle,
    pressDevice: pressDevice,
    slide: slide,
    slideCommit: slideCommit,
    zone: {
      render: renderZone,
      bump: bump,
      setHolds: setHolds,
      holdText: holdText,
      clockWords: clockWords,
      currentTemp: currentTemp,
      setpoint: setpoint,
      heating: heating,
      tempClass: tempClass,
      lastSeen: lastSeen,
      tempSeen: tempSeen,
      notLive: notLiveReason,
      stale: stale,
      knowsDemand: knowsDemand,
      NOTE_KEEP_MS: NOTE_KEEP_MS,
      TRV_STALE_MS: TRV_STALE_MS,
      SETPOINT_MIN: SETPOINT_MIN,
      SETPOINT_MAX: SETPOINT_MAX,
      _pending: pending,
      _notices: notices,
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
