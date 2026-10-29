/*
 * Filename:    flow-popups.js
 * Description: What the Flow page's SigenStor and GRID pop-ups say (3.67.0).
 *              Pure: SigenEnergyManager's status in, a list of plain-English
 *              lines out, so the node test can drive every sentence. The page
 *              (flow.html) only draws them.
 *
 *              Written to the estate's notification rules: sentences, not
 *              key: value; every number with what it means; internal names
 *              translated, an unknown one shown in quotes rather than dropped;
 *              times as a person says them ("4pm", "6:58pm").
 * Author:      CliveS & Claude Opus 5.5
 * Date:        29-10-2026
 * Version:     1.0
 */
(function (root) {
  'use strict';

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function round(v, dp) { var f = Math.pow(10, dp || 0); return Math.round(v * f) / f; }

  /* 1.4 kW, 380 W */
  function power(w) {
    var a = Math.abs(w);
    if (a >= 1000) return round(a / 1000, a >= 10000 ? 0 : 1) + ' kW';
    return Math.round(a) + ' W';
  }
  /* 6 kWh, 14.9 kWh: whole numbers lose the .0 */
  function kwh(v) {
    var r = round(v, v >= 10 ? 0 : 1);
    return r + ' kWh';
  }
  function pence(p) { return round(p, 1) + 'p'; }
  function pounds(v) { return '£' + Math.abs(v).toFixed(2); }

  /* minutes after midnight -> "4pm", "6:58pm", "midnight", "noon" */
  function clock(mins) {
    mins = ((Math.round(mins) % 1440) + 1440) % 1440;
    if (mins === 0) return 'midnight';
    if (mins === 720) return 'noon';
    var h = Math.floor(mins / 60), m = mins % 60;
    var suffix = h < 12 ? 'am' : 'pm';
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return h12 + (m ? ':' + (m < 10 ? '0' : '') + m : '') + suffix;
  }
  function hhmm(text) {
    var m = /^(\d{1,2}):(\d{2})$/.exec(String(text || ''));
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];
  function dayWords(ms, nowMs) {
    var d = new Date(ms), n = new Date(nowMs);
    var a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    var b = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    var diff = Math.round((a - b) / 86400000);
    if (diff === 0) return 'today';
    if (diff === -1) return 'yesterday';
    if (diff === 1) return 'tomorrow';
    return d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  function timeOf(ms) { var d = new Date(ms); return clock(d.getHours() * 60 + d.getMinutes()); }
  function hoursWords(h) {
    if (h >= 48) return 'about ' + Math.round(h / 24) + ' days';
    if (h >= 2) return 'about ' + Math.round(h) + ' hours';
    if (h >= 1) return 'about an hour';
    var m = Math.max(5, Math.round(h * 60 / 5) * 5);
    return 'about ' + m + ' minutes';
  }
  function quoted(s) { return '"' + String(s) + '"'; }

  /* The plugin's decision codes, said as what the battery is doing. */
  var DOING = {
    self_consumption: 'Running the house on its own',
    solar_overflow:   'Sending the spare solar out to the grid',
    start_import:     'Charging from the grid',
    stop_import:      'Just finishing a grid charge',
    schedule_import:  'Waiting to charge from the grid',
    start_export:     'Selling to the grid overnight',
    stop_export:      'Just finishing an export',
  };

  /* Minimum energy kept back in a power cut (DashCalc.BACKUP_RESERVE_PCT). */
  var RESERVE_PCT = 5;

  /* ---- SigenStor ------------------------------------------------------ */
  function batteryView(status, nowMs) {
    var s = status || {};
    var bat = s.battery || {}, dec = s.decision || {}, home = s.home || {}, day = s.today_summary || {};
    var soc = num(bat.soc_pct), cap = num(bat.capacity_kwh), w = num(bat.power_w);
    var lines = [];
    var headline = soc === null ? 'Battery' : 'Battery ' + Math.round(soc) + '%';
    var sub = (soc !== null && cap) ? round(soc / 100 * cap, 0) + ' of ' + kwh(cap) + ' stored' : '';

    // What it is doing, and how hard. Charging while it runs the house on
    // its own can only be the solar.
    var doing = DOING[dec.action] || (dec.action ? 'The manager says ' + quoted(dec.action) : 'No word from the manager');
    var flow = w === null ? ''
      : w > 25 ? (dec.action === 'self_consumption' ? ', and the solar is charging it at ' : ', charging at ') + power(w)
      : w < -25 ? ', supplying ' + power(w) : ', resting';
    lines.push({ key: 'doing', text: doing + flow + '.' });

    // Will it last the night
    var dawn = num(dec.soc_at_dawn_kwh);
    if (dawn !== null) {
      var pct = cap ? ' (' + Math.round(dawn / cap * 100) + '%)' : '';
      lines.push({ key: 'dawn', tone: dec.dawn_viable === false ? 'warn' : '',
                   text: dec.dawn_viable === false
                     ? 'It is expected to run low before the sun comes up, with about ' + kwh(dawn) + pct + ' left at dawn.'
                     : 'It should last until the sun comes up, with about ' + kwh(dawn) + pct + ' left at dawn.' });
    }

    // Backup time at the house's draw now
    var load = num(home.load_w);
    if (soc !== null && cap && load && load > 0) {
      var usable = Math.max(0, (soc - RESERVE_PCT) / 100 * cap);
      if (usable > 0) {
        var hrs = usable / (load / 1000);
        lines.push({ key: 'backup', tone: hrs < 2 ? 'warn' : '',
                     text: 'In a power cut it would run the house for ' + hoursWords(hrs) +
                           ' at the ' + power(load) + ' it is using now.' });
      }
    }

    // Health
    var soh = num(bat.soh_pct), tmin = num(bat.temp_min_c), tmax = num(bat.temp_max_c);
    var bal = (bat.pack_balance || {}).verdict, packs = num(bat.pack_count);
    var health = [];
    if (soh !== null) health.push('Health ' + Math.round(soh) + '%' + (soh >= 90 ? ', as good as new' : soh >= 80 ? ', normal wear' : ', worn'));
    if (tmin !== null && tmax !== null) {
      var t = 'cells between ' + Math.round(tmin) + ' and ' + Math.round(tmax) + ' degrees';
      if (bal === 'even') t += (packs ? ', all ' + (packs === 4 ? 'four' : packs) + ' packs evenly matched' : ', packs evenly matched');
      else if (bal) t += ', packs ' + quoted(bal);
      health.push(t);
    }
    if (health.length) lines.push({ key: 'health', tone: bal && bal !== 'even' ? 'warn' : '', text: health.join('; ') + '.' });

    // Today
    var ch = num(day.battery_charge_kwh), dis = num(day.battery_discharge_kwh);
    if (ch !== null && dis !== null) lines.push({ key: 'today', text: 'Today it has taken in ' + kwh(ch) + ' and given out ' + kwh(dis) + '.' });

    // Only when something unusual is going on
    var vpp = s.vpp || {}, storm = s.storm || {}, cut = s.power_cut || {};
    if (cut.ongoing) lines.push({ key: 'cut', tone: 'bad', text: 'Power cut: the battery is running the house.' });
    else if (cut.lockout_active) {
      var floor = num(cut.lockout_soc_floor);
      // SigenEnergyManager: export resumes early at the SOC floor, or once
      // today's solar can refill that reserve on its own.
      lines.push({ key: 'lockout', tone: 'warn',
                   text: 'After the recent power cut, export is held off for a while as a precaution' +
                         (floor !== null ? ', until the battery reaches ' + Math.round(floor) + '% or the day\'s solar can refill it' : '') + '.' });
    }
    if (vpp.active) lines.push({ key: 'vpp', text: 'Exporting for the VPP' + (vpp.event_str ? ': ' + vpp.event_str : '') + '.' });
    if (storm.level && storm.level !== 'none' && storm.level !== 'clear') {
      var release = num(storm.export_release_pct);
      lines.push({ key: 'storm', tone: 'warn',
                   text: 'Storm warning (' + quoted(storm.level) + '): charge is being kept back in case the power goes' +
                         (storm.export_suppressed ? (release !== null ? ', with no export below ' + Math.round(release) + '%' : ', with export held off') : '') + '.' });
    }
    return { title: headline, sub: sub, lines: lines,
             links: [{ href: 'energy.html', text: 'Battery and plan on the Energy page' }] };
  }

  /* ---- tariff bands --------------------------------------------------- */
  /* The band now, when it ends and what follows, from SigenEnergyManager's
     tiers ({label, p, current, windows:[{start, end, current}]}). */
  function bands(side) {
    var tiers = (side && side.tiers) || [];
    var now = null, end = null;
    tiers.forEach(function (t) {
      (t.windows || []).forEach(function (w) { if (w.current) { now = t; end = hhmm(w.end); } });
    });
    if (!now) return null;
    var next = null;
    tiers.forEach(function (t) {
      (t.windows || []).forEach(function (w) { if (hhmm(w.start) === end && t !== now) next = t; });
    });
    return { now: now, end: end, next: next };
  }
  function tierPrice(side, label) {
    var t = ((side && side.tiers) || []).filter(function (x) { return x.label === label; })[0];
    return t ? num(t.p) : null;
  }

  /* "2026-10-25 18:58 UTC — grid LOST (...)" -> ms */
  function eventTime(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC/.exec(String(text || ''));
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
  }
  function lastCut(events) {
    var list = events || [];
    for (var i = list.length - 1; i >= 0; i--) {
      if (/grid LOST/.test(list[i])) {
        var at = eventTime(list[i]);
        var back = null;
        for (var j = i + 1; j < list.length; j++) {
          var m = /grid RESTORED \(duration ([^)]+)\)/.exec(list[j]);
          if (m) { back = m[1]; break; }
        }
        return at === null ? null : { at: at, lasted: back };
      }
    }
    return null;
  }
  function durationWords(text) {
    var m = /^([\d.]+)\s*(s|m|min|h)$/.exec(String(text || '').trim());
    if (!m) return text ? quoted(text) : null;
    var v = Number(m[1]), u = m[2];
    var secs = u === 's' ? v : (u === 'h' ? v * 3600 : v * 60);
    if (secs < 90) return 'about a minute';
    if (secs < 3600) return 'about ' + Math.round(secs / 60) + ' minutes';
    var h = secs / 3600;
    return h < 1.5 ? 'about an hour' : 'about ' + round(h, h < 10 ? 1 : 0) + ' hours';
  }

  /* ---- GRID ----------------------------------------------------------- */
  function gridView(status, nowMs) {
    var s = status || {};
    var grid = s.grid || {}, tariff = s.tariff || {}, econ = (s.economics || {}).today || {};
    var day = s.today_summary || {}, q = s.grid_quality || {}, cut = s.power_cut || {};
    var w = num(grid.power_w);
    var lines = [];
    var title = cut.ongoing ? 'Power cut' : w === null ? 'Grid' : w > 25 ? 'Buying ' + power(w) : w < -25 ? 'Selling ' + power(w) : 'Barely using the grid';

    // Price now and next
    var imp = tariff.import_side, exp = tariff.export_side;
    var b = bands(imp);
    if (b) {
      var sell = tierPrice(exp, b.now.label);
      var t = b.now.label + ' rate now: ' + pence(num(b.now.p)) + ' a unit to buy' +
              (sell !== null ? ' and ' + pence(sell) + ' to sell' : '') + ', until ' + clock(b.end) + '.';
      lines.push({ key: 'price', tone: /peak/i.test(b.now.label) && !/off/i.test(b.now.label) ? 'warn' : '', text: t });
      if (b.next) {
        var sellNext = tierPrice(exp, b.next.label);
        lines.push({ key: 'next', text: 'Then ' + b.next.label.toLowerCase() + ': ' + pence(num(b.next.p)) + ' to buy' +
                                        (sellNext !== null ? ' and ' + pence(sellNext) + ' to sell' : '') + '.' });
      }
    } else if (num(imp && imp.now_p) !== null) {
      lines.push({ key: 'price', text: 'A unit costs ' + pence(num(imp.now_p)) + ' to buy now.' });
    }

    // Today, money and energy together
    var ic = num(econ.import_cost_gbp), er = num(econ.export_revenue_gbp);
    var ik = num(day.import_kwh), ek = num(day.export_kwh);
    if (ic !== null || ik !== null) {
      var bought = 'Today the house has bought ' + (ik !== null ? kwh(ik) : 'some electricity') + (ic !== null ? ' for ' + pounds(ic) : '');
      var sold = ek !== null && ek >= 0.05 ? ' and sold ' + kwh(ek) + (er !== null ? ' for ' + pounds(er) : '') : ' and sold nothing';
      lines.push({ key: 'today', text: bought + sold + '.' });
    }

    // Supply quality
    var v = num(q.voltage_v), hz = num(q.frequency_hz), vmin = num(q.statutory_min_v), vmax = num(q.statutory_max_v);
    if (v !== null) {
      var inside = vmin === null || vmax === null || (v >= vmin && v <= vmax);
      var vt = 'The supply is at ' + Math.round(v) + ' volts';
      if (vmin !== null && vmax !== null) vt += inside ? ', inside the legal ' + Math.round(vmin) + ' to ' + Math.round(vmax) : ', outside the legal ' + Math.round(vmin) + ' to ' + Math.round(vmax);
      if (hz !== null) vt += ', at ' + round(hz, 2) + ' hertz' + (Math.abs(hz - 50) > 0.5 ? ', which is outside the normal 49.5 to 50.5' : '');
      lines.push({ key: 'supply', tone: inside && (hz === null || Math.abs(hz - 50) <= 0.5) ? '' : 'bad', text: vt + '.' });
    }

    // Octopus events booked
    var up = ((s.octopus_sessions || {}).upcoming) || [];
    up.slice(0, 3).forEach(function (e) {
      var a = Date.parse(e.start), z = Date.parse(e.end);
      if (!isFinite(a) || !isFinite(z)) return;
      var kind = e.direction === 'TURN_DOWN' ? 'Saving Session (use less)' : e.direction === 'TURN_UP' ? 'Power-up (use more)' : quoted(e.direction || 'Octopus event');
      lines.push({ key: 'session', text: kind + ' booked ' + dayWords(a, nowMs) + ', ' + timeOf(a) + ' to ' + timeOf(z) + '.' });
    });

    // Power cuts
    if (cut.ongoing) lines.push({ key: 'cut', tone: 'bad', text: 'The grid is down. The battery is running the house.' });
    else {
      var last = lastCut(cut.events);
      if (last) {
        var lasted = durationWords(last.lasted);
        lines.push({ key: 'lastcut', text: 'The last power cut was ' + dayWords(last.at, nowMs) + ' at ' + timeOf(last.at) +
                                            (lasted ? ' and lasted ' + lasted : '') + '.' });
      }
    }
    return { title: title, sub: tariff.name || '', lines: lines,
             links: [{ href: 'cost.html', text: 'What it costs, on the Cost page' }, { href: 'mains.html', text: 'Mains meters' }] };
  }

  root.FlowPopups = { batteryView: batteryView, gridView: gridView,
                      _t: { clock: clock, power: power, kwh: kwh, bands: bands, lastCut: lastCut,
                            durationWords: durationWords, dayWords: dayWords, hoursWords: hoursWords } };
})(typeof window !== 'undefined' ? window : globalThis);
