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
 * Version:     1.2 (only the last setpoint press checks; honest message); 1.1 (pressDevice)
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

  /* Why a tile cannot show a device as live: 'disabled', 'error', or ''.
     The room page's motion tile had this rule; light, sensor and appliance
     tiles painted a disabled device's frozen state as current. */
  function unknownReason(d) {
    if (!d) return 'no reading';
    if (d.enabled === false) return 'disabled';
    if (String(d.errorState || '').trim()) return 'error';
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
  function confirmFromDevice(a, id, expected, undo) {
    root.setTimeout(function () {
      Promise.resolve(a.getDevice(id)).then(function (d) {
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

  function slideCommit(el) {
    var id = parseInt(el.dataset.id, 10);
    var value = parseInt(el.value, 10);
    root.clearTimeout(debounce[id]);
    debounce[id] = root.setTimeout(function () {
      if (api) Promise.resolve(api.setBrightness(id, value)).catch(function () {});
    }, 300);
  }

  /* ---- heating zone ---------------------------------------------------- */
  var SETPOINT_MIN = 8;      // RAMSES TRVs clamp at 8°C — 5 was silently raised
  var SETPOINT_MAX = 28;
  var PENDING_MS   = 4000;   // how long a sent setpoint shows before the device's own wins
  var READBACK_MS  = 2500;
  var TRV_STALE_MS = 3 * 3600 * 1000;   // flag a TRV unheard for more than 3 hours
  var pending = {};          // device id -> { v, t }
  var presses = {};          // device id -> how many presses so far (see bump)

  function currentTemp(d) {
    var s = d.states || {};
    var cand = [s.temperatureInput1, s.temperature, d.displayStateValRaw];
    for (var i = 0; i < cand.length; i++) {
      var n = parseFloat(cand[i]);
      if (!isNaN(n) && n > -50 && n < 100) return n;
    }
    return null;
  }
  function setpoint(d) {
    if (d.setpointHeat != null) return parseFloat(d.setpointHeat);
    var n = parseFloat((d.states || {}).setpointHeat);
    return isNaN(n) ? null : n;
  }
  /* Heating = the valve is open, or the zone says it is calling for heat
     and really is below its setpoint. The call-for-heat flag is read from
     the states first and the device second: the room page's old copy read
     only the second and missed it on every RAMSES zone. */
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
    var t = Date.parse(String(v).replace(' ', 'T'));
    return isNaN(t) ? null : t;
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
    var hot = heating(d);
    var s = d.states || {};
    var valve = parseFloat(s['valve-position'] || s.valvePosition || 0);
    var humidity = parseFloat(s.humidityInput1);
    // hvacMode is the system's heat/off setting, "Heat" on every RAMSES zone,
    // so it is only worth saying when it is Off.
    var status = /off/i.test(d.hvacMode || '') ? 'Off' : (hot ? 'Heating' : 'Valve closed');
    var meta = [esc(status)];
    if (isFinite(humidity)) meta.push(esc(humidity.toFixed(0) + '% RH'));
    if (!isNaN(valve) && valve > 0) meta.push(esc('valve ' + valve.toFixed(0) + '%'));
    var ls = lastSeen(d);
    if (ls != null) {
      var stale = (Date.now() - ls) > TRV_STALE_MS;
      var ago = root.DashUI && root.DashUI.ago ? root.DashUI.ago(Date.now() - ls) : '';
      meta.push('<span class="trv-age' + (stale ? ' stale' : '') + '">' + (stale ? icon('warn') + ' ' : '') +
                'heard ' + esc(ago) + '</span>');
    }
    var dis = sp == null ? ' disabled' : '';
    var name = esc(opts.name != null ? opts.name : d.name);
    var info = opts.info
      ? '<button class="info-btn" aria-label="Details for ' + name + '" onclick="event.stopPropagation(); openDeviceDetails(' + d.id + ')">&#9432;</button>'
      : '';
    return '' +
      '<div class="zone' + (hot ? ' heating' : '') + '" data-dsh-act-key="device:' + d.id + '">' +
        '<div class="zone-head">' +
          '<div class="name-row"><div class="zone-name">' + name + '</div>' + info + '</div>' +
          '<div class="zone-flame' + (hot ? ' on' : '') + '">' + icon('flame') + '</div>' +
        '</div>' +
        '<div class="temps"><div class="cur-temp ' + tempClass(cur) + '">' +
          (cur == null ? '—' : cur.toFixed(1)) + '<span class="cur-unit">°C</span></div></div>' +
        '<div class="setpoint">' +
          '<button class="setpoint-btn" onclick="DashTile.zone.bump(' + d.id + ', -1)" aria-label="Lower ' + name + ' setpoint"' + dis + '>−</button>' +
          '<div><div class="setpoint-label">Setpoint</div>' +
            '<div class="setpoint-val" id="sp-' + d.id + '" aria-live="polite" aria-atomic="true" data-sp="' + (actualSp == null ? '' : actualSp) + '">' +
            (sp == null ? '—' : sp.toFixed(1)) + '°</div></div>' +
          '<button class="setpoint-btn" onclick="DashTile.zone.bump(' + d.id + ', 1)" aria-label="Raise ' + name + ' setpoint"' + dis + '>+</button>' +
        '</div>' +
        '<div class="zone-meta">' + meta.map(function (m) { return '<span>' + m + '</span>'; }).join('') + '</div>' +
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
     — when the radiator had taken all four. Live-found on an iPhone. */
  function bump(id, dir) {
    var el = root.document && root.document.getElementById('sp-' + id);
    if (!el || !api) return Promise.resolve(false);
    var actual = parseFloat(el.dataset.sp);
    if (isNaN(actual)) return Promise.resolve(false);
    var base = pending[id] ? pending[id].v : actual;
    var next = base % 1 === 0 ? base + dir : (dir > 0 ? Math.ceil(base) : Math.floor(base));
    next = Math.max(SETPOINT_MIN, Math.min(SETPOINT_MAX, next));
    if (next === base) return Promise.resolve(false);          // at the clamp: nothing to send
    pending[id] = { v: next, t: Date.now() };
    var mine = presses[id] = (presses[id] || 0) + 1;
    el.textContent = next.toFixed(0) + '°';
    return Promise.resolve(api.setHeatSetpoint(id, next)).then(function () {
      root.setTimeout(function () {
        if (presses[id] !== mine) return;         // a later press will check instead
        Promise.resolve(api.getDevice(id)).then(function (d) {
          if (presses[id] !== mine) return;
          var got = d ? setpoint(d) : null;
          if (got != null && Math.abs(got - next) >= 0.5) {
            delete pending[id];
            // The tile may have been redrawn by the poll since the press.
            var live = root.document.getElementById('sp-' + id) || el;
            live.textContent = got.toFixed(1) + '°';
            // Say what is known — the radiator's own figure — not a guess at
            // the cause, which the old wording blamed on the plugin.
            var msg = 'The radiator still says ' + got.toFixed(1) + '° — the change did not take';
            try { if (root.DashAction) root.DashAction.note('device:' + id, 'error', msg); } catch (_) {}
            // The Heating page has its own message line and no DashAction.
            var t = root.document.getElementById('evo-toast');
            if (t) { t.textContent = msg; t.className = 'ctrl-toast err'; }
          }
        }).catch(function () {});
      }, READBACK_MS);
      return true;
    }).catch(function () {
      delete pending[id];
      el.textContent = actual.toFixed(1) + '°';
      return false;
    });
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
      currentTemp: currentTemp,
      setpoint: setpoint,
      heating: heating,
      tempClass: tempClass,
      lastSeen: lastSeen,
      TRV_STALE_MS: TRV_STALE_MS,
      SETPOINT_MIN: SETPOINT_MIN,
      SETPOINT_MAX: SETPOINT_MAX,
      _pending: pending,
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
