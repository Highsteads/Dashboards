/* Filename:    energy-calc.js
 * Description: Shared, DOM-free calculations for the Energy and Cost pages.
 *              Both pages had their own copies of the formatters and window
 *              helpers, and the arithmetic that mattered most sat inline in a
 *              2000-line <script> where nothing could test it. Everything here
 *              is a pure function of its arguments so tests/test_energy_cost.mjs
 *              can drive it directly.
 * Author:      CliveS & Claude Opus 5 (v1.0); Claude Fable 5 (v1.1-1.2)
 * Date:        13-08-2026
 * Version:     1.4 (packBalanceText + gridFrequencyState — wording the
 *              battery pack-balance inference and the grid-frequency band)
 *              prior 1.3 (buildSolarHours + site series), 1.2, 1.1
 */

(function (root) {
  'use strict';

  /* Fallback only — the real figure arrives as battery.capacity_kwh from
     SigenEnergyManager v5.52.0. energy.html used to hardcode 35.04, which is
     this house's pack and nobody else's. */
  var DEFAULT_CAPACITY_KWH = 35.04;

  /* The inverter stops discharging here, so it is the floor for any
     "how long would the battery last" figure. An estimate, and the chip that
     shows it says so. */
  var BACKUP_RESERVE_PCT = 5;

  /* ── numbers ── */

  function num(v) {
    var n = parseFloat(v);
    return isNaN(n) ? null : n;
  }

  /* Watts, shown in the unit that suits the size. The old version always
     divided by 1000 and printed two decimals, so 30 W read "0.03 kW". */
  function fmtKw(w) {
    if (w === null || w === undefined || isNaN(Number(w))) return '—';
    var n = Number(w);
    var a = Math.abs(n);
    if (a < 1000) return Math.round(n) + ' W';
    if (a < 10000) return (n / 1000).toFixed(2) + ' kW';
    return (n / 1000).toFixed(1) + ' kW';
  }

  function fmtKwh(v, dp) {
    if (v === null || v === undefined || isNaN(Number(v))) return '—';
    return Number(v).toFixed(dp === undefined ? 1 : dp) + ' kWh';
  }

  /* U+2212 minus, not a hyphen — it aligns with the digits. */
  function gbp(v, opts) {
    opts = opts || {};
    if (v === null || v === undefined || isNaN(Number(v))) return '—';
    var n = Number(v);
    var s = '£' + Math.abs(n).toFixed(2);
    return (opts.signed && n > 0 ? '+' : (n < 0 ? '−' : '')) + s;
  }

  function fmtPct(v, dp) {
    if (v === null || v === undefined || isNaN(Number(v))) return '—';
    return Number(v).toFixed(dp === undefined ? 1 : dp) + '%';
  }

  /* Pence per kWh. Whole pence hid a half-penny rate — a 12.5p rate printed
     as "13p" while the maths went on using 12.5. */
  function fmtPence(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return '—';
    var n = Number(v);
    return (Math.abs(n * 100 - Math.round(n * 100)) < 1e-9 && n * 10 % 10 === 0)
      ? n.toFixed(0) : n.toFixed(2).replace(/0$/, '');
  }

  /* ── today's energy allocation (the Sankey) ──
     Merit order for a self-consumption system: solar covers the house first,
     then charges the battery, then exports; the battery covers whatever the
     house still needs; the grid is last.

     Whatever a source cannot be matched to a sink is returned as `loss` rather
     than quietly dropped. The old version drew the SOLAR node at its full
     figure while its ribbons summed to less — about 1.9 kWh, 5.6%, invisible.
     It could also allocate more solar than was generated, because the battery
     charge was taken off `chg` without ever being capped at `pv`. */
  function computeFlows(s, chg, dis) {
    s = s || {};
    var pv   = Math.max(0, s.pv_kwh     || 0);
    var imp  = Math.max(0, s.import_kwh || 0);
    var exp  = Math.max(0, s.export_kwh || 0);
    var home = Math.max(0, s.home_kwh   || 0);
    chg = Math.max(0, chg || 0);
    dis = Math.max(0, dis || 0);

    var pvLeft = pv, impLeft = imp, disLeft = dis;
    var homeLeft = home, chgLeft = chg, expLeft = exp;

    var s2l = Math.min(pvLeft, homeLeft); pvLeft -= s2l; homeLeft -= s2l;
    var s2b = Math.min(pvLeft, chgLeft);  pvLeft -= s2b; chgLeft  -= s2b;
    var s2g = Math.min(pvLeft, expLeft);  pvLeft -= s2g; expLeft  -= s2g;

    var b2l = Math.min(disLeft, homeLeft); disLeft -= b2l; homeLeft -= b2l;
    var b2g = Math.min(disLeft, expLeft);  disLeft -= b2g; expLeft  -= b2g;

    var g2l = Math.min(impLeft, homeLeft); impLeft -= g2l; homeLeft -= g2l;
    var g2b = Math.min(impLeft, chgLeft);  impLeft -= g2b; chgLeft  -= g2b;

    /* Supplied but not matched to a sink — conversion and round-trip losses. */
    var loss = pvLeft + disLeft + impLeft;
    /* Consumed but not matched to a source. Should be ~0; a real figure here
       means the meters disagree, which is worth seeing rather than hiding. */
    var unmet = homeLeft + chgLeft + expLeft;

    return {
      pv: pv, imp: imp, exp: exp, home: home, chg: chg, dis: dis,
      s2l: s2l, s2b: s2b, s2g: s2g,
      b2l: b2l, b2g: b2g,
      g2l: g2l, g2b: g2b,
      loss: loss, unmet: unmet,
      /* Both sides of the diagram now add up to the same number. */
      totalIn:  pv + dis + imp,
      totalOut: home + chg + exp + loss,
    };
  }

  /* ── half-hourly supply/sink balance ──
     The old chart stacked Solar and Export on the positive side and Home and
     Import on the negative. Export is a SUBSET of solar (and of battery
     discharge), and import is a subset of what feeds home, so both stacks were
     inflated — on a live day, 34.4 kWh generated and 12.5 exported drew a
     positive stack reading nearly 47 kWh.

     Sources up, sinks down. Battery flow comes from the SOC delta, which the
     history slots already carry. */
  function buildBalanceSeries(slots, capacityKwh) {
    var cap = capacityKwh || DEFAULT_CAPACITY_KWH;
    var out = { solar: [], batteryOut: [], gridIn: [],
                home: [], batteryIn: [], gridOut: [] };
    (slots || []).forEach(function (s) {
      s = s || {};                                 // a missing slot contributes zeros
      var bat = 0;
      if (s.soc_start != null && s.soc_end != null) {
        bat = (s.soc_end - s.soc_start) / 100 * cap;   // + charging, − discharging
      }
      out.solar.push(s.pv_kwh || 0);
      out.batteryOut.push(bat < 0 ? -bat : 0);
      out.gridIn.push(s.import_kwh || 0);
      out.home.push(-(s.home_kwh || 0));
      out.batteryIn.push(bat > 0 ? -bat : 0);
      out.gridOut.push(-(s.export_kwh || 0));
    });
    return out;
  }

  /* ── SOC sparkline ──
     A null slot used to be read as 0, which dropped the trace to the floor and
     put a false "low 0%" in the caption. Nulls now break the line. */
  function socSeries(slots) {
    var pts = (slots || []).map(function (s) {
      return (s && s.soc_end != null && !isNaN(Number(s.soc_end)))
        ? Number(s.soc_end) : null;
    });
    var real = pts.filter(function (v) { return v !== null; });
    return {
      points: pts,
      min: real.length ? Math.min.apply(null, real) : null,
      max: real.length ? Math.max.apply(null, real) : null,
      count: real.length,
    };
  }

  /* ── backup runtime ──
     How long the battery would hold the house up at the current draw. An
     estimate: the draw is a snapshot and solar is ignored. */
  function backupRuntime(socPct, homeW, capacityKwh, reservePct) {
    var cap = capacityKwh || DEFAULT_CAPACITY_KWH;
    var floor = (reservePct === undefined || reservePct === null)
      ? BACKUP_RESERVE_PCT : reservePct;
    if (socPct === null || socPct === undefined || isNaN(Number(socPct))) return null;
    if (homeW === null || homeW === undefined || !(Number(homeW) > 0)) return null;
    var usableKwh = Math.max(0, (Number(socPct) - floor) / 100 * cap);
    if (usableKwh <= 0) return null;
    var hours = usableKwh / (Number(homeW) / 1000);
    var label;
    if (hours >= 240)     label = '10+ days';
    else if (hours >= 48) label = (hours / 24).toFixed(1) + ' days';
    else if (hours >= 10) label = Math.round(hours) + 'h';
    else if (hours >= 1)  label = hours.toFixed(1) + 'h';
    else                  label = Math.max(5, Math.round(hours * 60 / 5) * 5) + 'm';
    return { hours: hours, label: label,
             state: hours >= 8 ? 'ok' : (hours >= 2 ? '' : 'warn') };
  }

  /* ── rolling windows ── */

  /* Noon-anchored so a clock change cannot slide the date. */
  function isoOffset(anchorMs, daysBack) {
    return new Date(anchorMs - daysBack * 86400000).toISOString().slice(0, 10);
  }

  function winSum(byDate, anchorMs, startBack, field) {
    var sum = 0, found = 0;
    for (var i = 0; i < 7; i++) {
      var rec = byDate.get(isoOffset(anchorMs, startBack + i));
      if (rec && rec[field] != null) { sum += rec[field]; found++; }
    }
    return { sum: sum, found: found };
  }

  /* Money over a 7-day window, valued at each day's own saved rates.

     `fallbackStandingP` matters more than it looks: 87 of the first 121 live
     history rows carry no elec_standing_p_day at all, and without a fallback
     those days billed at zero standing charge. Recent days carried ~62p, so
     the week-on-week comparison reported a bill rise that was nothing but the
     age of the data. */
  function winMoney(byDate, anchorMs, startBack, fallbackStandingP, fallbackUnitP, fallbackExportP) {
    var bill = 0, exp = 0, found = 0, standingKnown = 0, rateKnown = 0, exportKnown = 0;
    for (var i = 0; i < 7; i++) {
      var rec = byDate.get(isoOffset(anchorMs, startBack + i));
      if (!rec) continue;
      found++;
      // A day missing its saved unit rate must not bill its import at £0 —
      // the same fault class the standing-charge fallback below already
      // fixed. Fall back to the latest known rate rather than pricing real
      // kWh as free.
      var rateP = rec.rate_today_p;
      if (rateP == null || isNaN(Number(rateP))) {
        rateP = (fallbackUnitP == null || isNaN(Number(fallbackUnitP)))
          ? 0 : Number(fallbackUnitP);
      } else {
        rateKnown++;
      }
      var unit = (rec.grid_import_kwh || 0) * Number(rateP) / 100;
      var stP  = rec.elec_standing_p_day;
      if (stP == null || isNaN(Number(stP))) {
        stP = (fallbackStandingP == null || isNaN(Number(fallbackStandingP)))
          ? 0 : Number(fallbackStandingP);
      } else {
        standingKnown++;
      }
      bill += unit + Number(stP) / 100;
      // Export gets the same fallback the import rate has: a day missing its
      // export rate used to be valued at zero, silently (v2.95.4).
      var exP = rec.export_rate_p;
      if (exP == null || isNaN(Number(exP))) {
        exP = (fallbackExportP == null || isNaN(Number(fallbackExportP))) ? 0 : Number(fallbackExportP);
      } else {
        exportKnown++;
      }
      exp  += (rec.grid_export_kwh || 0) * Number(exP) / 100;
    }
    return { bill: bill, exp: exp, net: exp - bill,
             found: found, standingKnown: standingKnown, rateKnown: rateKnown,
             exportKnown: exportKnown };
  }

  /* Most recent export rate anywhere in the history: the fallback for a row
     that lacks one. */
  function latestExportP(records) {
    for (var i = (records || []).length - 1; i >= 0; i--) {
      var v = records[i] && records[i].export_rate_p;
      if (v != null && !isNaN(Number(v))) return Number(v);
    }
    return null;
  }

  /* Most recent standing charge anywhere in the history — the fallback for
     rows written before the plugin started freezing it per day. */
  function latestStandingP(records) {
    for (var i = (records || []).length - 1; i >= 0; i--) {
      var v = records[i] && records[i].elec_standing_p_day;
      if (v != null && !isNaN(Number(v))) return Number(v);
    }
    return null;
  }

  /* Most recent unit rate anywhere in the history — winMoney's fallback for
     days whose saved rate is missing (87 of the first 121 rows here). */
  function latestUnitP(records) {
    for (var i = (records || []).length - 1; i >= 0; i--) {
      var v = records[i] && records[i].rate_today_p;
      if (v != null && !isNaN(Number(v))) return Number(v);
    }
    return null;
  }

  /* Percentage change, or null when there is no honest comparison to make. */
  function pctDelta(cur, prev) {
    if (prev == null || cur == null || prev === 0) return null;
    var pct = ((cur - prev) / Math.abs(prev)) * 100;
    return isFinite(pct) ? pct : null;
  }

  /* ── self-sufficiency ──
     Share of what the house used that did NOT come off the grid. */
  function selfSufficiency(homeKwh, importKwh) {
    if (homeKwh == null || !(homeKwh > 0)) return null;
    return Math.max(0, Math.min(100, (homeKwh - (importKwh || 0)) / homeKwh * 100));
  }

  /* ── solar progress (v1.1): today's cumulative actual vs expected ──

     slots         /api/history slots (manager half-hours, local ISO `t`,
                   pv_kwh per slot) — any window; only today's rows are used
     hourly        the status payload's hourly_forecast dict {"HH:00": kWh},
                   bias-corrected; each bucket is the kWh generated DURING
                   that hour, so its cumulative point lands at the hour's END
     actualNowKwh  the authoritative running total (solar.actual_today_kwh) —
                   pins the line's last point at "now", since the current
                   half-hour slot hasn't been written yet
     nowMin        minutes since local midnight
     todayStr      "YYYY-MM-DD" local

     Returns {actual, expected (both [{m, kwh}]), expectedNow, deltaKwh,
     expectedTotal}. Malformed rows are skipped, never guessed at; a pinned
     total BEHIND the summed slots is ignored rather than drawing the line
     backwards. */
  function _interpCum(points, m) {
    if (!isFinite(m) || !points.length) return null;
    if (m <= points[0].m) return points[0].kwh;
    for (var i = 1; i < points.length; i++) {
      if (m <= points[i].m) {
        var a = points[i - 1], b = points[i];
        var f = (m - a.m) / Math.max(1, b.m - a.m);
        return Math.round((a.kwh + (b.kwh - a.kwh) * f) * 100) / 100;
      }
    }
    return points[points.length - 1].kwh;
  }

  function buildSolarProgress(slots, hourly, actualNowKwh, nowMin, todayStr) {
    var r2 = function (v) { return Math.round(v * 100) / 100; };

    var actual = [{ m: 0, kwh: 0 }];
    var cum = 0;
    (Array.isArray(slots) ? slots : []).forEach(function (s) {
      if (!s || typeof s.t !== 'string' || s.t.slice(0, 10) !== todayStr) return;
      var hh = Number(s.t.slice(11, 13));
      var mm = Number(s.t.slice(14, 16));
      var kwh = num(s.pv_kwh);
      if (!isFinite(hh) || !isFinite(mm) || kwh === null) return;
      cum += kwh;
      actual.push({ m: hh * 60 + mm, kwh: r2(cum) });
    });
    var pinned = num(actualNowKwh);
    if (pinned !== null && isFinite(nowMin)) {
      var last = actual[actual.length - 1];
      if (nowMin >= last.m && pinned >= last.kwh) {
        actual.push({ m: nowMin, kwh: r2(pinned) });
      }
    }

    var expected = [{ m: 0, kwh: 0 }];
    var ecum = 0;
    Object.keys(hourly || {}).map(function (k) {
      return { h: Number(String(k).slice(0, 2)), kwh: num(hourly[k]) };
    }).filter(function (x) {
      return isFinite(x.h) && x.h >= 0 && x.h <= 23 && x.kwh !== null;
    }).sort(function (a, b) { return a.h - b.h; })
      .forEach(function (x) {
        ecum += x.kwh;
        expected.push({ m: (x.h + 1) * 60, kwh: r2(ecum) });
      });

    var expectedNow = _interpCum(expected, nowMin);
    var deltaKwh = (pinned !== null && expectedNow !== null)
      ? r2(pinned - expectedNow) : null;
    return { actual: actual, expected: expected, expectedNow: expectedNow,
             deltaKwh: deltaKwh, expectedTotal: r2(ecum) };
  }

  /* Forecast accuracy is historical mean absolute percentage error, not a
     statistical confidence interval.  The range is therefore deliberately
     labelled "typical" in the UI, and bounded so one thin data point cannot
     draw either a misleadingly precise or uselessly huge band. */
  function solarTypicalRange(expected, mapePct) {
    var e = num(expected), mape = num(mapePct);
    if (e === null || e < 0 || mape === null || mape < 0) return null;
    var fraction = Math.max(0.05, Math.min(0.50, mape / 100));
    return {
      fraction: fraction,
      low: Math.max(0, Math.round(e * (1 - fraction) * 100) / 100),
      high: Math.round(e * (1 + fraction) * 100) / 100,
    };
  }

  /* ── solar hours (v1.3): the stacked hourly chart's row model ──

     Marries the available sources into one 24-row model, shared by the
     Energy page's full chart and the hub's compact one:
       stringHours  solarStringHours `hours` — null for an hour with no
                    per-string samples, else [kWh x4]
       siteHours    solarStringHours `site` — the same hours' site total,
                    logged for years, so it covers the hours the strings
                    cannot. Exact hour buckets, no attribution guesswork
       slots        /api/history half-hour slots — LAST resort, for an
                    install with no SQL Logger (where the endpoint has
                    nothing to read). A slot's stamp is its END, so its
                    energy is attributed by MIDPOINT (stamp − 15 min): a
                    half-slot skew beats dropping the hour
       hourly       hourly_forecast {"HH:00": kWh}
     Returns {rows: [{h, mode: past|current|future, parts, total, forecast}],
     won, played} — won/played count COMPLETED daylight hours only (an hour
     still running can't have lost yet, and dark hours where both sides are
     ~0 prove nothing either way). A past hour with no data at all keeps
     total null: the chart shows the gap rather than a fabricated zero. */
  function buildSolarHours(stringHours, siteHours, slots, hourly, nowMin, todayStr) {
    var r2 = function (v) { return Math.round(v * 100) / 100; };
    var nowHour = Math.floor((isFinite(nowMin) ? nowMin : 0) / 60);

    var siteHour = {};
    (Array.isArray(slots) ? slots : []).forEach(function (s) {
      if (!s || typeof s.t !== 'string' || s.t.slice(0, 10) !== todayStr) return;
      var hh = Number(s.t.slice(11, 13));
      var mm = Number(s.t.slice(14, 16));
      var kwh = num(s.pv_kwh);
      if (!isFinite(hh) || !isFinite(mm) || kwh === null) return;
      var mid = Math.max(0, hh * 60 + mm - 15);
      var bucket = Math.floor(mid / 60);
      siteHour[bucket] = (siteHour[bucket] || 0) + kwh;
    });

    var rows = [], won = 0, played = 0;
    for (var h = 0; h < 24; h++) {
      var key = String(h).padStart(2, '0') + ':00';
      var forecast = num((hourly || {})[key]);
      forecast = forecast === null ? 0 : r2(forecast);
      var mode = h < nowHour ? 'past' : (h === nowHour ? 'current' : 'future');
      var parts = null, total = null;
      if (mode !== 'future') {
        var sh = (Array.isArray(stringHours) ? stringHours[h] : null);
        var site = (Array.isArray(siteHours) ? num(siteHours[h]) : null);
        if (Array.isArray(sh) && sh.length === 4) {
          parts = sh.map(function (v) { var n = num(v); return n === null ? 0 : n; });
          total = r2(parts.reduce(function (a, b) { return a + b; }, 0));
        } else if (site !== null) {
          total = r2(site);
        } else if (siteHour[h] != null) {
          total = r2(siteHour[h]);
        }
      }
      if (mode === 'past' && total !== null && (forecast > 0.05 || total > 0.05)) {
        played++;
        if (total >= forecast - 0.05) won++;
      }
      rows.push({ h: h, mode: mode, parts: parts, total: total, forecast: forecast });
    }
    return { rows: rows, won: won, played: played };
  }

  /* ── battery pack balance (v1.4) ──────────────────────────────────────
     Turns SigenEnergyManager's pack_balance block into the sentence the
     card shows. The inverter publishes no per-pack registers, so the plugin
     infers the shape from max/min/mean across N identical packs; this only
     words the verdict.

     Returns {text, tone} or null when there is nothing honest to say —
     never "packs healthy" off a reading that could not be taken. */
  function packBalanceText(bal) {
    if (!bal || !bal.verdict) return null;
    var spread = num(bal.spread_c);
    var s = spread === null ? '' : spread.toFixed(1) + '°C apart';
    if (bal.verdict === 'one_hot') {
      var hot = num(bal.hot_gap_c);
      if (hot === null) return null;              // a verdict without its figure says nothing
      return { text: 'One pack ' + hot.toFixed(1) + '°C above the others',
               tone: hot >= 6 ? 'warn' : '' };
    }
    if (bal.verdict === 'one_cold') {
      var cold = num(bal.cold_gap_c);
      if (cold === null) return null;
      return { text: 'One pack ' + cold.toFixed(1) + '°C below the others',
               tone: cold >= 6 ? 'warn' : '' };
    }
    if (bal.verdict !== 'even') return null;      // an unknown verdict is not "good"
    return { text: s ? 'Evenly matched · ' + s : 'Evenly matched', tone: 'good' };
  }

  /* Grid frequency against the 50 Hz nominal. The band is the UK statutory
     operating range (49.5–50.5) with the normal band at ±0.2; outside that
     the grid is under real stress, which is when a VPP event turns up. */
  function gridFrequencyState(hz) {
    var f = num(hz);
    if (f === null || f <= 0) return null;
    var off = f - 50;
    var tone = Math.abs(off) <= 0.2 ? 'good' : (Math.abs(off) <= 0.5 ? 'warn' : 'bad');
    return { hz: f, offset: Math.round(off * 100) / 100, tone: tone,
             text: f.toFixed(2) + ' Hz' };
  }

  /* ── grid voltage (v1.5) ──────────────────────────────────────────────
     The UK statutory range is 230 V +10%/-6% = 216.2 to 253.0. Above the
     ceiling an inverter must curtail or disconnect, so this is an export-
     revenue reading, not a curiosity — and the cause is the DNO's network.
     Limits come from the payload rather than being hardcoded here, since
     they are not the same everywhere. */
  function gridVoltageState(v, maxV, minV) {
    var volts = num(v);
    if (volts === null || volts <= 0) return null;
    var hi = num(maxV), lo = num(minV);
    if (hi === null) hi = 253.0;
    if (lo === null) lo = 216.2;
    var tone = 'good', note = 'normal';
    if (volts > hi) { tone = 'bad'; note = 'over the limit — export may cut'; }
    else if (volts > hi - 3) { tone = 'warn'; note = 'close to the ' + hi.toFixed(0) + ' V limit'; }
    else if (volts < lo) { tone = 'bad'; note = 'below the statutory minimum'; }
    return { volts: volts, tone: tone, note: note,
             headroom: Math.round((hi - volts) * 100) / 100 };
  }

  var API = {
    DEFAULT_CAPACITY_KWH: DEFAULT_CAPACITY_KWH,
    BACKUP_RESERVE_PCT: BACKUP_RESERVE_PCT,
    num: num, fmtKw: fmtKw, fmtKwh: fmtKwh, gbp: gbp,
    fmtPct: fmtPct, fmtPence: fmtPence,
    computeFlows: computeFlows,
    buildBalanceSeries: buildBalanceSeries,
    socSeries: socSeries,
    backupRuntime: backupRuntime,
    isoOffset: isoOffset, winSum: winSum, winMoney: winMoney,
    latestStandingP: latestStandingP, latestUnitP: latestUnitP, latestExportP: latestExportP, pctDelta: pctDelta,
    selfSufficiency: selfSufficiency,
    buildSolarProgress: buildSolarProgress,
    solarTypicalRange: solarTypicalRange,
    buildSolarHours: buildSolarHours,
    packBalanceText: packBalanceText,
    gridFrequencyState: gridFrequencyState,
    gridVoltageState: gridVoltageState,
  };

  root.DashCalc = API;
  if (typeof globalThis !== 'undefined') globalThis.DashCalc = API;
})(typeof window !== 'undefined' ? window : globalThis);
