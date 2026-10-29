/*
 * Filename:    sigen-flow-bridge.js
 * Description: A stand-in for Home Assistant's `hass` object, so Jean-Yves
 *              Avenard's Sigenergy Flow Card (sigenergy-flow-card.js, Apache-2.0,
 *              vendored unchanged) runs on the Flow page from Indigo data.
 *
 *              His card reads sensor values from hass.states under the entity
 *              names of the Sigenergy Local Modbus integration, asks
 *              hass.callApi for today's history and hass.callWS for recorder
 *              statistics and the solar forecast. Everything here answers
 *              those from what Dashboards already has:
 *                - SigenEnergyManager's status, half-hourly history and daily
 *                  records (the sigenApi proxy),
 *                - the solarStringHours history (per-string power),
 *                - the Zappi device (the AC charger on his picture),
 *                - the Ecowitt outdoor sensor and weather.json (OpenWeatherMap).
 *              The pure parts are on SigenFlowBridge._t for the node test.
 * Author:      CliveS & Claude Opus 5.5
 * Date:        29-10-2026
 * Version:     1.0
 */
(function (root) {
  'use strict';

  // The entity names his card looks for first (DEFAULT_ENTITIES and the
  // pvString pattern for the sigenergy_local_modbus backend).
  var E = {
    pv: 'sensor.sigen_plant_pv_power',
    home: 'sensor.sigen_plant_consumed_power',
    battery: 'sensor.sigen_plant_battery_power',
    soc: 'sensor.sigen_plant_battery_state_of_charge',
    capacity: 'sensor.sigen_plant_rated_energy_capacity',
    gridImport: 'sensor.sigen_plant_grid_import_power',
    gridExport: 'sensor.sigen_plant_grid_export_power',
    acPower: 'sensor.sigen_ac_charger_charging_power',
    acState: 'sensor.sigen_ac_charger_system_state',
    stringsPower: 'sensor.sigen_plant_sigen_pv_power',
    stringsLifetime: 'sensor.sigen_plant_total_generation_of_self_pv',
    dayPv: 'sensor.sigen_plant_daily_pv_energy',
    dayImport: 'sensor.sigen_plant_daily_grid_import_energy',
    dayExport: 'sensor.sigen_plant_daily_grid_export_energy',
    dayCharge: 'sensor.sigen_plant_daily_battery_charge_energy',
    dayDischarge: 'sensor.sigen_plant_daily_battery_discharge_energy',
    statPv: 'sensor.sigen_plant_total_pv_generation',
    statCharge: 'sensor.sigen_plant_total_charged_energy_of_the_ess',
    statDischarge: 'sensor.sigen_plant_total_discharged_energy_of_the_ess',
    statImport: 'sensor.sigen_plant_total_imported_energy',
    statExport: 'sensor.sigen_plant_total_exported_energy',
    weather: 'weather.forecast_home',
    sun: 'sun.sun',
  };
  var PV_STRING = function (n, key) { return 'sensor.sigen_inverter_pv' + n + '_' + key; };

  var SLOT_MS = 30 * 60 * 1000;           // SigenEnergyManager's history is half-hourly
  var CHARGER_PLUGIN = 'com.clives.indigoplugin.zappi';
  var CHARGER_STALE_MS = 10 * 60 * 1000;  // the energy page holds a Zappi back after ten minutes too

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function stateTrue(v) { return v === true || String(v).toLowerCase() === 'true'; }

  /* 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS', the server's local time -> ms. */
  function localStamp(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(String(text || '').trim());
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)).getTime();
  }
  function localDate(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || '').trim());
    return m ? new Date(+m[1], +m[2] - 1, +m[3]).getTime() : null;
  }
  function midnight(ms) { var d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); }

  function entity(id, value, unit, name, extra) {
    var known = value !== null && value !== undefined && value !== '';
    var attributes = { friendly_name: name || id };
    if (unit) attributes.unit_of_measurement = unit;
    if (extra) for (var k in extra) attributes[k] = extra[k];
    return { entity_id: id, state: known ? String(value) : 'unavailable', attributes: attributes };
  }

  /* ---- the Zappi, as the card's AC charger ---------------------------- */
  function chargerReading(devices, nowMs) {
    var dev = (devices || []).filter(function (d) {
      return d && d.pluginId === CHARGER_PLUGIN && d.deviceTypeId === 'zappi' && d.enabled !== false;
    })[0];
    if (!dev) return null;
    var st = dev.states || {};
    var reported = localStamp(st.lastReport);
    var live = !dev.errorState && stateTrue(st.online) && reported !== null && nowMs - reported <= CHARGER_STALE_MS;
    if (!live) return { name: dev.name, watts: null, words: 'Not reachable' };
    var plug = st.plugState;
    var plugged = plug !== undefined && plug !== 'unplugged' && plug !== 'unknown';
    var charging = plugged && (st.chargeState === 'charging' || st.chargeState === 'boosting');
    var watts = charging ? (num(st.chargePowerW) || 0) : 0;
    // The card shows the part before any '-', so no hyphens in these words.
    var words = !plugged ? 'No car' : charging ? (st.chargeState === 'boosting' ? 'Boosting' : 'Charging') : 'Plugged in';
    return { name: dev.name, watts: watts, words: words };
  }

  /* ---- outdoor temperature (Ecowitt), in degrees C --------------------- */
  function outdoorC(devices, wx) {
    var hits = (devices || []).filter(function (d) {
      var s = (d && d.states) || {};
      return s.temperature !== undefined && s.humidity !== undefined && s.dewPoint !== undefined;
    });
    var dev = hits.length > 1 ? (hits.filter(function (d) { return /outdoor/i.test(d.name || ''); })[0] || hits[0]) : hits[0];
    if (!dev) return null;
    var t = num(dev.states.temperature);
    if (t === null) return null;
    return wx ? wx.tempC(t, dev.states) : t;
  }

  /* ---- the HOME breakdown: every metered plug or switch ----------------
     The same power states the Active page reads. Left out: the Sigen and
     Zappi devices (drawn on the picture already), and meters whose name says
     they measure a whole circuit or the house, which would swamp the list. */
  var POWER_KEYS = ['powerWatts', 'power', 'curEnergyLevel', 'activePower'];
  var NOT_A_LOAD = /\b(mains|whole house|house total|grid|solar|inverter|battery|consumer unit)\b/i;
  function homeLoads(devices) {
    var out = [];
    (devices || []).forEach(function (d) {
      if (!d || d.enabled === false || d.pluginId === CHARGER_PLUGIN) return;
      if (/sigenergy/i.test(d.pluginId || '') || NOT_A_LOAD.test(d.name || '')) return;
      var s = d.states || {};
      for (var i = 0; i < POWER_KEYS.length; i++) {
        var w = num(s[POWER_KEYS[i]]);
        if (w !== null) { out.push({ entity: 'sensor.indigo_' + d.id + '_power', name: d.name, watts: Math.max(0, w) }); return; }
      }
    });
    return out.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
  }

  /* ---- OpenWeatherMap icon -> Home Assistant condition ----------------- */
  var OWM = { '01': 'sunny', '02': 'partlycloudy', '03': 'cloudy', '04': 'cloudy', '09': 'pouring',
              '10': 'rainy', '11': 'lightning-rainy', '13': 'snowy', '50': 'fog' };
  function condition(icon) {
    var m = /^(\d\d)([dn])?$/.exec(String(icon || ''));
    if (!m || !OWM[m[1]]) return null;
    if (m[1] === '01' && m[2] === 'n') return 'clear-night';
    return OWM[m[1]];
  }

  /* ---- a location from today's sunrise and sunset ----------------------
     The card works out sunrise and sunset from hass.config's latitude and
     longitude. Dashboards publishes only the times (weather.json), and a
     house's coordinates do not belong in a public file, so this finds a
     latitude and longitude that give the same two times (NOAA's equations).
     Any answer that reproduces today's times is as good as the real one for
     what the card does with it. */
  function solarDay(ms) {
    var d = new Date(ms);
    var start = Date.UTC(d.getUTCFullYear(), 0, 1);
    var doy = Math.floor((ms - start) / 86400000) + 1;
    var g = 2 * Math.PI / 365 * (doy - 1);
    var eq = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g)
                       - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
    var dec = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
              + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
    return { eq: eq, dec: dec };
  }
  function halfDayDeg(lat, dec) {
    var r = Math.PI / 180;
    var c = Math.cos(90.833 * r) / (Math.cos(lat * r) * Math.cos(dec)) - Math.tan(lat * r) * Math.tan(dec);
    return Math.acos(Math.max(-1, Math.min(1, c))) / r;
  }
  function locate(riseMs, setMs) {
    if (!(riseMs > 0) || !(setMs > riseMs) || setMs - riseMs > 86400000) return null;
    var noon = (riseMs + setMs) / 2;
    var s = solarDay(noon);
    var u = new Date(noon);
    var noonMin = u.getUTCHours() * 60 + u.getUTCMinutes() + u.getUTCSeconds() / 60;
    var lon = (720 - s.eq - noonMin) / 4;
    while (lon > 180) lon -= 360;
    while (lon < -180) lon += 360;
    var half = (setMs - riseMs) / 60000 / 8;    // degrees of hour angle
    // Day length changes one way from pole to pole on any one date, so
    // bisect between the polar circles. Near an equinox every latitude has
    // about the same day, and any of them then gives the same times.
    var lo = -66, hi = 66;
    var rising = halfDayDeg(hi, s.dec) > halfDayDeg(lo, s.dec);
    for (var i = 0; i < 40; i++) {
      var mid = (lo + hi) / 2;
      if ((halfDayDeg(mid, s.dec) < half) === rising) lo = mid; else hi = mid;
    }
    var lat = (lo + hi) / 2;
    return { latitude: Math.round(lat * 100) / 100, longitude: Math.round(lon * 100) / 100 };
  }

  /* ---- hass.states from one snapshot ---------------------------------- */
  function buildStates(input) {
    var status = input.status || {};
    var bat = status.battery || {}, sol = status.solar || {}, grid = status.grid || {};
    var home = status.home || {}, day = status.today_summary || {};
    var nowMs = input.nowMs || Date.now();
    var states = {};
    var put = function (id, v, unit, name, extra) { states[id] = entity(id, v, unit, name, extra); };

    var charger = input.charger;
    var gridW = num(grid.power_w);
    var homeW = num(home.load_w);
    // SigenEnergyManager's house load includes the Zappi. The card draws the
    // charger as a load of its own beside HOME, as Sigenergy's app does.
    if (homeW !== null && charger && charger.watts) homeW = Math.max(0, homeW - charger.watts);

    put(E.pv, num(sol.power_w), 'W', 'Solar');
    put(E.home, homeW, 'W', 'Home');
    put(E.battery, num(bat.power_w), 'W', 'Battery');      // positive while charging, as the card wants
    put(E.soc, num(bat.soc_pct), '%', 'Battery level');
    put(E.capacity, num(bat.capacity_kwh), 'kWh', 'Battery capacity');
    put(E.gridImport, gridW === null ? null : Math.max(0, gridW), 'W', 'Grid import');
    put(E.gridExport, gridW === null ? null : Math.max(0, -gridW), 'W', 'Grid export');
    put(E.dayPv, num(day.pv_kwh), 'kWh', 'Solar produced today');
    put(E.dayImport, num(day.import_kwh), 'kWh', 'Grid imported today');
    put(E.dayExport, num(day.export_kwh), 'kWh', 'Grid exported today');
    put(E.dayCharge, num(day.battery_charge_kwh), 'kWh', 'Battery charged today');
    put(E.dayDischarge, num(day.battery_discharge_kwh), 'kWh', 'Battery discharged today');
    // Lifetime counters: the card only needs them to exist; their energy per
    // period comes from statistics() below.
    put(E.statPv, num(sol.lifetime_kwh), 'kWh', 'Solar lifetime');
    put(E.statCharge, null, 'kWh', 'Battery charged');
    put(E.statDischarge, null, 'kWh', 'Battery discharged');
    put(E.statImport, null, 'kWh', 'Grid imported');
    put(E.statExport, null, 'kWh', 'Grid exported');
    put(E.stringsPower, num(sol.power_w), 'W', 'Sigenergy PV');
    put(E.stringsLifetime, num(sol.lifetime_kwh), 'kWh', 'Sigenergy PV lifetime');

    var strings = sol.strings || [];
    var dayKwh = input.stringDayKwh || [];
    strings.forEach(function (s, i) {
      var n = num(s.n) || (i + 1);
      put(PV_STRING(n, 'voltage'), num(s.v), 'V', s.label + ' voltage');
      put(PV_STRING(n, 'current'), num(s.a), 'A', s.label + ' current');
      put(PV_STRING(n, 'power'), num(s.w), 'W', s.label + ' power');
      put(PV_STRING(n, 'daily_energy'), dayKwh[i] === undefined ? null : dayKwh[i], 'kWh', s.label + ' today');
    });

    (input.loads || []).forEach(function (l) { put(l.entity, l.watts, 'W', l.name); });

    if (charger) {
      put(E.acPower, charger.watts, 'W', charger.name || 'Car charger');
      put(E.acState, charger.words, '', charger.name || 'Car charger');
    }

    var wx = input.weather;
    if (wx) {
      var rise = num(wx.sunrise), set = num(wx.sunset);
      if (rise && set) {
        put(E.sun, nowMs >= rise * 1000 && nowMs < set * 1000 ? 'above_horizon' : 'below_horizon', '', 'Sun');
      }
      var cond = condition(wx.now_icon);
      if (cond || input.outdoorC !== null && input.outdoorC !== undefined) {
        put(E.weather, cond || 'exceptional', '', 'Weather',
            { temperature: input.outdoorC === null || input.outdoorC === undefined ? null : Math.round(input.outdoorC * 10) / 10,
              temperature_unit: '°C' });
      }
    }
    var stamp = new Date(nowMs).toISOString();
    for (var id in states) states[id].last_changed = states[id].last_updated = stamp;
    return states;
  }

  /* ---- half-hourly slots -> per-slot figures ---------------------------
     t is the END of the slot (SigenEnergyManager's slot_end, local time).
     Battery energy is the balance: what came in (solar, import) less what
     went out (house, export). Positive = charging. */
  function slotFigures(slots) {
    return (slots || []).map(function (s) {
      var end = localStamp(s.t);
      if (end === null) return null;
      var pv = num(s.pv_kwh) || 0, imp = num(s.import_kwh) || 0, exp = num(s.export_kwh) || 0, home = num(s.home_kwh) || 0;
      var net = pv + imp - home - exp;
      return { start: end - SLOT_MS, end: end, pv: pv, imp: imp, exp: exp, home: home,
               charge: Math.max(0, net), discharge: Math.max(0, -net), soc: num(s.soc_end) };
    }).filter(Boolean).sort(function (a, b) { return a.start - b.start; });
  }

  // kWh in a half hour -> mean watts over it
  var W = function (kwh) { return kwh * 1000 * 3600000 / SLOT_MS; };

  /* hass.callApi('GET', 'history/period/<iso>?filter_entity_id=a,b...'):
     one list of {entity_id, state, last_changed} per entity asked for. */
  function historyPeriod(query, figs, stringHours, charger) {
    var m = /^history\/period\/([^?]+)\?(.*)$/.exec(query || '');
    if (!m) return [];
    var from = Date.parse(decodeURIComponent(m[1]));
    var ids = [];
    m[2].split('&').forEach(function (kv) {
      var p = kv.split('=');
      if (p[0] === 'filter_entity_id') ids = decodeURIComponent(p[1] || '').split(',');
    });
    var mid = function (f) { return f.start + SLOT_MS / 2; };
    var today = figs.filter(function (f) { return f.end > from; });
    var series = {};
    series[E.pv] = today.map(function (f) { return [mid(f), W(f.pv)]; });
    series[E.home] = today.map(function (f) { return [mid(f), W(f.home)]; });
    series[E.battery] = today.map(function (f) { return [mid(f), W(f.charge - f.discharge)]; });
    series[E.gridImport] = today.map(function (f) { return [mid(f), W(f.imp)]; });
    series[E.gridExport] = today.map(function (f) { return [mid(f), W(f.exp)]; });
    series[E.soc] = today.filter(function (f) { return f.soc !== null; }).map(function (f) { return [f.end, f.soc]; });
    if (charger) series[E.acPower] = [];
    // Per-string power: each hour's kWh is its mean kW, placed mid-hour.
    var hours = (stringHours && stringHours.hours) || [];
    var base = midnight(from + 1);
    for (var n = 1; n <= 4; n++) {
      series[PV_STRING(n, 'power')] = [];
      for (var h = 0; h < hours.length; h++) {
        var row = hours[h];
        if (!row || row[n - 1] === null || row[n - 1] === undefined) continue;
        series[PV_STRING(n, 'power')].push([base + h * 3600000 + 1800000, row[n - 1] * 1000]);
      }
    }
    return ids.filter(function (id) { return series[id]; }).map(function (id) {
      return series[id].map(function (p) {
        return { entity_id: id, state: String(Math.round(p[1] * 10) / 10), last_changed: new Date(p[0]).toISOString() };
      });
    });
  }

  /* hass.callWS({type:'recorder/statistics_during_period', ...}).
     'change' rows feed the Energy statistics panel; 'mean' rows feed the
     forecast's seven-day profile. Spans up to two days are answered from the
     half-hourly slots, longer ones from the daily records. */
  var CHANGE = {};
  CHANGE[E.statPv] = 'pv'; CHANGE[E.statImport] = 'imp'; CHANGE[E.statExport] = 'exp';
  CHANGE[E.statCharge] = 'charge'; CHANGE[E.statDischarge] = 'discharge';
  var DAILY = { pv: 'pv_kwh', imp: 'grid_import_kwh', exp: 'grid_export_kwh',
                charge: 'battery_charge_kwh', discharge: 'battery_discharge_kwh', home: 'home_kwh' };
  var MEAN = {};
  MEAN[E.pv] = 'pv'; MEAN[E.home] = 'home';

  function statistics(msg, figs, daily) {
    var from = Date.parse(msg.start_time), to = Date.parse(msg.end_time);
    var types = msg.types || [];
    var out = {};
    var ids = msg.statistic_ids || [];
    if (types.indexOf('mean') >= 0) {
      // Hourly means only: the card treats a 5-minute answer as 5-minute
      // slots, so it is told there are none and asks again by the hour.
      if (msg.period !== 'hour') return {};
      ids.forEach(function (id) {
        var key = MEAN[id];
        if (!key) return;
        var buckets = {};
        figs.forEach(function (f) {
          if (f.start < from || f.start >= to) return;
          var h = f.start - (f.start % 3600000);
          var b = buckets[h] || (buckets[h] = [0, 0]);
          b[0] += W(f[key]); b[1]++;
        });
        out[id] = Object.keys(buckets).map(Number).sort(function (a, b) { return a - b; })
          .map(function (h) { return { start: h, end: h + 3600000, mean: buckets[h][0] / buckets[h][1] }; });
      });
      return out;
    }
    var short = to - from <= 2 * 86400000;
    ids.forEach(function (id) {
      var key = CHANGE[id];
      if (!key) return;
      if (short) {
        out[id] = figs.filter(function (f) { return f.start >= from && f.start < to; })
          .map(function (f) { return { start: f.start, end: f.end, change: f[key] }; });
      } else {
        out[id] = (daily || []).map(function (r) {
          var d = localDate(r.date);
          if (d === null || d < from || d >= to) return null;
          var v = num(r[DAILY[key]]);
          return v === null ? null : { start: d, end: d + 86400000, change: v };
        }).filter(Boolean);
      }
    });
    return out;
  }

  /* hass.callWS({type:'energy/solar_forecast'}): SigenEnergyManager's
     hourly forecast for today, in kWh per 'HH:00', as Wh per ISO hour. */
  function solarForecast(hourly, nowMs) {
    var base = midnight(nowMs || Date.now());
    var wh = {};
    Object.keys(hourly || {}).forEach(function (k) {
      var m = /^(\d{1,2}):00$/.exec(k), v = num(hourly[k]);
      if (!m || v === null) return;
      wh[new Date(base + Number(m[1]) * 3600000).toISOString()] = v * 1000;
    });
    return Object.keys(wh).length ? { sigenergy_manager: { wh_hours: wh } } : {};
  }

  /* ---- the live object handed to the card ----------------------------- */
  function Bridge(opts) {
    this.message = opts.message;            // DashUI.message
    this.wx = opts.wx;                      // DashUI.wx
    this.status = null;
    this.devices = [];
    this.weather = null;
    this._cache = {};
    this.location = null;
  }
  Bridge.prototype._sigen = function (path, query, ttlMs) {
    var key = path + JSON.stringify(query || {});
    var hit = this._cache[key];
    if (hit && Date.now() - hit.at < ttlMs) return hit.p;
    var self = this;
    var p = this.message('sigenApi', { path: path, query: query || {} }, { pendingMs: 15000 })
      .catch(function (e) { delete self._cache[key]; throw e; });
    this._cache[key] = { at: Date.now(), p: p };
    return p;
  };
  Bridge.prototype._slots = function (hours) {
    var asked = Math.min(24 * 400, Math.max(24, Math.ceil(hours)));
    // Round up so a page left open reuses one fetch for five minutes.
    asked = Math.ceil(asked / 24) * 24;
    return this._sigen('history', { hours: asked }, 5 * 60 * 1000)
      .then(function (d) { return slotFigures(d && d.slots); });
  };
  Bridge.prototype._stringHours = function () {
    var key = 'strings', hit = this._cache[key];
    if (hit && Date.now() - hit.at < 5 * 60 * 1000) return hit.p;
    var self = this;
    var p = this.message('solarStringHours', {}, { pendingMs: 15000 })
      .catch(function () { delete self._cache[key]; return null; });
    this._cache[key] = { at: Date.now(), p: p };
    return p;
  };
  Bridge.prototype.hass = function (strings) {
    var self = this, nowMs = Date.now();
    var charger = chargerReading(this.devices, nowMs);
    var wx = this.weather;
    if (wx && !this.location) this.location = locate(num(wx.sunrise) * 1000, num(wx.sunset) * 1000);
    var config = { time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                   unit_system: { temperature: '°C' } };
    if (this.location) { config.latitude = this.location.latitude; config.longitude = this.location.longitude; }
    return {
      states: buildStates({ status: this.status, charger: charger, weather: wx, nowMs: nowMs,
                            outdoorC: outdoorC(this.devices, this.wx), stringDayKwh: strings,
                            loads: homeLoads(this.devices) }),
      config: config,
      language: 'en-GB',
      locale: { language: 'en-GB' },
      callApi: function (method, query) {
        if (method !== 'GET') return Promise.reject(new Error('read-only'));
        var from = Date.parse(decodeURIComponent((/^history\/period\/([^?]+)/.exec(query) || [])[1] || ''));
        var hours = isFinite(from) ? (Date.now() - from) / 3600000 + 1 : 24;
        return Promise.all([self._slots(hours), self._stringHours()]).then(function (r) {
          return historyPeriod(query, r[0], r[1], charger);
        });
      },
      callWS: function (msg) {
        if (msg && msg.type === 'energy/solar_forecast') {
          return Promise.resolve(solarForecast(self.status && self.status.hourly_forecast, Date.now()));
        }
        if (msg && msg.type === 'recorder/statistics_during_period') {
          var from = Date.parse(msg.start_time), to = Date.parse(msg.end_time);
          if (!isFinite(from) || !isFinite(to)) return Promise.resolve({});
          if (to - from <= 2 * 86400000 || (msg.types || []).indexOf('mean') >= 0) {
            return self._slots((Date.now() - from) / 3600000 + 1).then(function (figs) { return statistics(msg, figs, null); });
          }
          var days = Math.ceil((Date.now() - from) / 86400000) + 1;
          return self._sigen('daily', { days: Math.min(4000, days) }, 10 * 60 * 1000)
            .then(function (d) { return statistics(msg, [], d && d.records); });
        }
        return Promise.reject(new Error('Not available in Indigo: ' + (msg && msg.type)));
      },
      callService: function () { return Promise.reject(new Error('read-only')); },
    };
  };

  root.SigenFlowBridge = {
    Bridge: Bridge, E: E,
    _t: { buildStates: buildStates, slotFigures: slotFigures, historyPeriod: historyPeriod,
          statistics: statistics, solarForecast: solarForecast, chargerReading: chargerReading,
          homeLoads: homeLoads,
          outdoorC: outdoorC, condition: condition, locate: locate, localStamp: localStamp,
          halfDayDeg: halfDayDeg, solarDay: solarDay },
  };
})(typeof window !== 'undefined' ? window : globalThis);
