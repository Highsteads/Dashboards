/* Filename:    levoit-view.js
 * Description: The Air page's decisions, kept out of the HTML so a node test
 *              can check them: which devices are purifiers, what each reading
 *              means, and whether a control the page pressed has taken.
 *              levoit.html only draws what this returns.
 *
 *              The devices are the Levoit Purifier plugin's, found by STATE
 *              SIGNATURE (pm25 + filterLife + fanLevel), never by id, so the
 *              page works for any number of purifiers on any install.
 * Author:      CliveS & Claude Opus 5.5
 * Date:        24-10-2026
 * Version:     1.0
 */

(function (root) {
  'use strict';

  var SIGNATURE = ['pm25', 'filterLife', 'fanLevel'];
  var MODES = [['auto', 'Auto'], ['manual', 'Manual'], ['sleep', 'Sleep']];
  var AUTO_PREFS = [['default', 'Default'], ['efficient', 'Efficient'], ['quiet', 'Quiet']];
  var FAN_LEVELS = [1, 2, 3, 4];
  var FILTER_LOW = 10;          // the plugin warns below this too
  var CONFIRM_MS = 45000;       // a press not seen in the states by then is "not confirmed"

  // The purifier's own 1-4 verdict. The band picks the colour; the words are
  // what a person reads beside the number.
  var BANDS = {
    1: { band: 'good', words: 'Excellent' },
    2: { band: 'good', words: 'Good' },
    3: { band: 'moderate', words: 'Moderate' },
    4: { band: 'poor', words: 'Poor' },
  };

  function truthy(v) {
    // The v2 API hands custom Boolean states back as true/false, but a
    // string "True"/"False" has been seen from other plugins; take both.
    if (typeof v === 'string') return /^(true|on|yes|1)$/i.test(v.trim());
    return !!v;
  }

  function int(v, dflt) {
    var n = parseInt(v, 10);
    return isNaN(n) ? dflt : n;
  }

  function purifiers(devices) {
    return (devices || []).filter(function (d) {
      var s = (d && d.states) || {};
      return SIGNATURE.every(function (k) { return s[k] !== undefined; });
    }).sort(function (a, b) { return String(a.name || '').localeCompare(String(b.name || '')); });
  }

  function airBand(airQuality) {
    return BANDS[int(airQuality, 0)] || { band: 'unknown', words: 'Not known yet' };
  }

  function view(d) {
    var s = (d && d.states) || {};
    var online = truthy(s.deviceOnline) && !(d && d.errorState);
    var mode = String(s.mode || 'unknown').toLowerCase();
    var air = airBand(s.airQuality);
    var filter = Math.max(0, Math.min(100, int(s.filterLife, 0)));
    var on = d && d.onState !== undefined ? truthy(d.onState) : truthy(s.onOffState);
    return {
      id: d.id,
      name: d.name || 'Air purifier',
      on: on,
      online: online,
      error: (d && d.errorState) || '',
      pm25: s.pm25 === undefined || s.pm25 === null || s.pm25 === '' ? null : int(s.pm25, null),
      band: online ? air.band : 'unknown',
      bandWords: air.words,
      mode: mode,
      fan: int(s.fanLevel, 0),
      filter: filter,
      filterLow: filter < FILTER_LOW,
      childLock: truthy(s.childLock),
      display: truthy(s.displayOn),
      autoPref: String(s.autoPreference || '').toLowerCase(),
      lastUpdate: s.lastUpdate || '',
    };
  }

  /* What the states must read for a press to count as done. The Levoit
     plugin reads the purifier back after VeSync accepts a command, so the
     states move once the purifier has really changed. */
  function confirmed(v, press) {
    if (!press) return true;
    switch (press.command) {
      case 'power':          return v.on === press.value;
      case 'fanSpeed':       return v.fan === Number(press.value) && v.on;
      case 'mode':           return v.mode === press.value;
      case 'autoPreference': return v.autoPref === press.value;
      case 'childLock':      return v.childLock === (press.value === 'on');
      case 'display':        return v.display === (press.value === 'on');
      default:               return true;
    }
  }

  /* 'waiting' while a press is in flight, 'late' once CONFIRM_MS has passed
     without the states agreeing, null when there is nothing to say. */
  function pressStatus(v, press, nowMs) {
    if (!press) return null;
    if (confirmed(v, press)) return null;
    return (nowMs - press.sentAt) > CONFIRM_MS ? 'late' : 'waiting';
  }

  /* "Updated 2 minutes ago" from the plugin's lastUpdate ("2026-10-24 13:30:05",
     local time). Plain words, rounded down; '' when there is no stamp. */
  function updatedWords(lastUpdate, nowMs) {
    var m = /^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)$/.exec(String(lastUpdate || ''));
    if (!m) return '';
    var t = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
    var secs = Math.max(0, Math.floor((nowMs - t) / 1000));
    if (secs < 60) return 'just now';
    var mins = Math.floor(secs / 60);
    if (mins < 60) return mins + (mins === 1 ? ' minute ago' : ' minutes ago');
    var hours = Math.floor(mins / 60);
    if (hours < 48) return hours + (hours === 1 ? ' hour ago' : ' hours ago');
    var days = Math.floor(hours / 24);
    return days + ' days ago';
  }

  root.LevoitView = {
    purifiers: purifiers, view: view, airBand: airBand, confirmed: confirmed,
    pressStatus: pressStatus, updatedWords: updatedWords,
    MODES: MODES, AUTO_PREFS: AUTO_PREFS, FAN_LEVELS: FAN_LEVELS,
    FILTER_LOW: FILTER_LOW, CONFIRM_MS: CONFIRM_MS, SIGNATURE: SIGNATURE,
  };
})(typeof window !== 'undefined' ? window : globalThis);
