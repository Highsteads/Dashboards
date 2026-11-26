/* Filename:    savings-view.js
 * Description: The Savings page's words and drawings (3.71.0). Pure functions
 *              of the savingsReport reply, so tests/test_savings_view.mjs can
 *              run them under Node with no browser.
 * Author:      CliveS & Claude Opus 5.5
 * Date:        21-11-2026
 * Version:     1.0
 */
(function (root) {
  'use strict';

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];
  var SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var TARIFFS = { tracker: 'Octopus Tracker', agile: 'Agile Octopus', flux: 'Octopus Flux',
                  go: 'Octopus Go', flexible: 'Flexible Octopus', cosy: 'Cosy Octopus' };
  var PERIODS = [['1m', 'Month'], ['3m', '3 months'], ['ytd', 'This year'], ['all', 'Since records began']];
  var STEPS = ['nokit', 'solar', 'tariff', 'battery', 'extras', 'paid'];
  var STEP_LABEL = { nokit: 'No kit', solar: 'Solar', tariff: 'Tariff', battery: 'Battery',
                     extras: 'Extras', paid: 'Paid' };

  function esc(t) {
    return String(t === null || t === undefined ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function commas(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  // Pounds as a person writes them: £1,834 for big sums, £4.01 for small ones,
  // 42p under a pound. Always the size; callers say which way it went.
  function gbp(x) {
    if (x === null || x === undefined || !isFinite(x)) return '—';
    var a = Math.abs(x);
    if (a < 0.995) return Math.round(a * 100) + 'p';
    if (a >= 100) return '£' + commas(Math.round(a));
    return '£' + a.toFixed(2);
  }

  // [figure, word after it] for a saving, which can be a loss (3.73.8). gbp()
  // gives the size alone, so a loss used to read as "£12.34 saved".
  function savedWords(x) {
    if (x === null || x === undefined || !isFinite(x)) return ['—', 'saved'];
    return [gbp(x), x < 0 ? 'more spent than' : 'saved'];
  }

  function kwh(x) {
    if (x === null || x === undefined || !isFinite(x)) return '—';
    return commas(Math.round(x)) + ' kWh';
  }

  function pct(x) {
    return (x === null || x === undefined || !isFinite(x)) ? '—' : Math.round(x) + '%';
  }

  function pence(x) {
    if (x === null || x === undefined || !isFinite(x)) return '—';
    return Math.abs(x).toFixed(1) + 'p';
  }

  function dateWords(iso, withYear) {
    if (!iso) return '';
    var p = String(iso).split('-');
    var s = Number(p[2]) + ' ' + MONTHS[Number(p[1]) - 1];
    return withYear ? s + ' ' + p[0] : s;
  }

  function shortDate(iso) {
    var p = String(iso).split('-');
    return Number(p[2]) + ' ' + SHORT[Number(p[1]) - 1];
  }

  function monthYear(iso) {
    var p = String(iso).split('-');
    return MONTHS[Number(p[1]) - 1] + ' ' + p[0];
  }

  function tariffName(key) {
    var k = String(key || '').toLowerCase();
    return TARIFFS[k] || ('"' + String(key || 'unknown') + '"');
  }

  function listWords(items) {
    if (items.length < 2) return items.join('');
    return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }

  function plural(n, one, many) {
    var words = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
    var w = n <= 10 ? words[n] : commas(n);
    return w + ' ' + (n === 1 ? one : (many || one + 's'));
  }

  function periodWords(key, p) {
    if (key === '1m') return 'in the last 30 days';
    if (key === '3m') return 'in the last three months';
    if (key === 'ytd') return 'so far this year';
    return 'since ' + dateWords(p.first);
  }

  // What each step means, in a sentence or two, with its figure.
  function stepWords(step, p) {
    var s = p.steps;
    var names = (p.eras || []).map(function (e) { return esc(tariffName(e.name)); });
    var unique = names.filter(function (n, i) { return names.indexOf(n) === i; });
    switch (step) {
      case 'nokit':
        return { head: 'With no solar and no battery', fig: gbp(s.nokit),
          text: 'Start with the electricity the house really used, ' + kwh(p.energy.home) +
                ', every kWh bought at the standard capped price (Flexible Octopus) with its daily standing charge. ' +
                'That would have been the bill.' };
      case 'solar':
        return { head: 'Add the panels', fig: gbp(s.solar) + ' off',
          text: 'Now the panels, with no battery. Each half hour the house uses what the panels are making, ' +
                'buys any shortfall at the standard price and sells what is left at the standard export price ' +
                '(Outgoing Octopus). On its own that would have covered ' + pct(p.solarOnlySelfUsePct) +
                ' of what the house used.' };
      case 'tariff':
        return { head: 'Your tariff' + (unique.length > 1 ? 's' : ''),
          fig: s.tariff >= 0 ? gbp(s.tariff) + ' off' : gbp(s.tariff) + ' more',
          text: 'The same energy, priced at the tariff' + (unique.length > 1 ? 's' : '') + ' you were really on (' +
                listWords(unique) + ') instead of the standard ones, standing charges included. ' +
                (s.tariff >= 0 ? 'That on its own was cheaper by ' + gbp(s.tariff) + '.'
                               : 'That on its own cost ' + gbp(s.tariff) + ' more.') };
      case 'battery':
        return { head: 'Add the battery', fig: s.battery >= 0 ? gbp(s.battery) + ' off' : gbp(s.battery) + ' more',
          text: 'Now what the meters really recorded, with the battery keeping daytime solar for the evening and, ' +
                'on a time-of-use tariff, filling up cheap and selling at the dear times. ' +
                (p.billedDays ? 'Where Octopus has billed a day, its own bill is used. ' : '') +
                'The battery took ' + gbp(s.battery) + (s.battery >= 0 ? ' off.' : ' on.') };
      case 'extras':
        return { head: 'Paid on top', fig: gbp(s.extras) + ' off',
          text: 'Money paid for helping the grid: Axle\'s grid events and monthly top-ups' +
                (p.credits ? ', and Octopus\'s free-hour credits' : '') + '. ' +
                gbp(p.events) + ' from Axle' + (p.credits ? ' and ' + gbp(p.credits) + ' from Octopus.' : '.') };
      default:
        return { head: 'What it really cost', fig: s.paid < 0 ? gbp(s.paid) + ' in credit' : gbp(s.paid),
          text: s.paid < 0
            ? 'After all of that, the electricity paid you ' + gbp(s.paid) + ' ' + periodWords(p._key, p) + ', standing charges and all. ' +
              'Against the ' + gbp(s.nokit) + ' it would have cost, that is ' + gbp(p.saved) + ' better off.'
            : 'After all of that, the electricity cost ' + gbp(s.paid) + ', standing charges and all, against ' +
              gbp(s.nokit) + ' with no kit: ' + gbp(p.saved) + ' saved.' };
    }
  }

  // The five steps as floating bars: each starts where the last one ended.
  // `narrow`: a phone-width card, drawn on a narrower canvas so the labels
  // keep a readable size when the drawing is scaled down to fit.
  function waterfall(p, chosen, narrow) {
    var s = p.steps;
    var levels = [0, s.nokit];
    var bars = [{ k: 'nokit', a: 0, b: s.nokit, colour: 'var(--grid-imp)' }];
    var run = s.nokit;
    [['solar', s.solar, 'var(--solar)'], ['tariff', s.tariff, 'var(--accent)'],
     ['battery', s.battery, 'var(--bat)'], ['extras', s.extras, 'var(--good)']].forEach(function (x) {
      var next = run - x[1];
      bars.push({ k: x[0], a: run, b: next, colour: x[2] });
      levels.push(next);
      run = next;
    });
    bars.push({ k: 'paid', a: 0, b: s.paid, colour: s.paid <= 0 ? 'var(--good)' : 'var(--text-secondary)' });
    levels.push(s.paid);
    var top = Math.max.apply(null, levels), bot = Math.min.apply(null, levels);
    var W = narrow ? 380 : 600, H = 300, padT = 30, padB = 40, slot = W / bars.length, bw = Math.min(64, slot * 0.62);
    var span = (top - bot) || 1;
    var y = function (v) { return padT + (top - v) / span * (H - padT - padB); };
    // Whole pounds on a phone: six values share 300-odd pixels.
    var money = narrow ? function (v) { var a = Math.abs(v); return a >= 1 ? '£' + commas(Math.round(a)) : gbp(v); } : gbp;
    var out = ['<svg class="wf' + (narrow ? ' narrow' : '') + '" viewBox="0 0 ' + W + ' ' + H + '" role="group" aria-label="The saving, step by step">'];
    out.push('<line x1="0" x2="' + W + '" y1="' + y(0).toFixed(1) + '" y2="' + y(0).toFixed(1) +
             '" stroke="var(--border)" stroke-width="1"/>');
    bars.forEach(function (b, i) {
      var x = i * slot + (slot - bw) / 2;
      var y1 = y(Math.max(b.a, b.b)), y2 = y(Math.min(b.a, b.b));
      var h = Math.max(y2 - y1, 2);
      var val = (b.k === 'nokit' || b.k === 'paid') ? money(b.b) : (b.b <= b.a ? '−' : '+') + money(b.a - b.b);
      var label = STEP_LABEL[b.k];
      if (b.k === 'paid' && b.b < 0) { val = money(b.b); label = 'Credit'; }
      out.push('<g class="wf-bar' + (chosen && chosen !== b.k ? ' dim' : '') + '" data-step="' + b.k +
               '" tabindex="0" role="button" aria-pressed="' + (chosen === b.k) + '" aria-label="' +
               esc(label + ' ' + val) + '">');
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y1.toFixed(1) + '" width="' + bw.toFixed(1) +
               '" height="' + h.toFixed(1) + '" rx="3" fill="' + b.colour + '"/>');
      if (i < bars.length - 1) {
        out.push('<line x1="' + (x + bw).toFixed(1) + '" x2="' + ((i + 1) * slot + (slot - bw) / 2).toFixed(1) +
                 '" y1="' + y(b.b).toFixed(1) + '" y2="' + y(b.b).toFixed(1) +
                 '" stroke="var(--text-muted)" stroke-dasharray="3 3" stroke-width="1"/>');
      }
      out.push('<text class="wf-val" x="' + (x + bw / 2).toFixed(1) + '" y="' + (y1 - 8).toFixed(1) +
               '" text-anchor="middle">' + esc(val) + '</text>');
      out.push('<text class="wf-label" x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 14) +
               '" text-anchor="middle">' + label + '</text>');
      out.push('</g>');
    });
    out.push('</svg>');
    return out.join('');
  }

  function tile(k, v, s, barPct, barColour, basePct) {
    return '<div class="tile"><div class="tile-k">' + k + '</div><div class="tile-v">' + v + '</div>' +
      (barPct !== undefined ? '<div class="bar2"><i style="width:' + Math.max(0, Math.min(100, barPct)) +
        '%;background:' + barColour + '"></i></div>' : '') +
      (basePct !== undefined ? '<div class="bar2"><i style="width:' + Math.max(0, Math.min(100, basePct)) +
        '%;background:var(--text-muted)"></i></div>' : '') +
      '<div class="tile-s">' + s + '</div></div>';
  }

  function tiles(p) {
    var self = tile('Your own solar', pct(p.selfSufficiencyPct),
      'of what the house used came from its own panels, straight away or through the battery. ' +
      'With no battery it would have been about ' + pct(p.solarOnlySelfUsePct) + '.',
      p.selfSufficiencyPct, 'var(--solar)', p.solarOnlySelfUsePct);
    var priceWords = p.pricePaidP < 0
      ? 'On average each kWh the house used earned you ' + pence(p.pricePaidP) + ', against the ' +
        pence(p.priceNoKitP) + ' it would have cost on the standard tariff.'
      : 'On average each kWh the house used cost ' + pence(p.pricePaidP) + ', against ' +
        pence(p.priceNoKitP) + ' on the standard tariff.';
    var price = tile('Price per kWh', (p.pricePaidP < 0 ? '−' : '') + pence(p.pricePaidP), priceWords);
    var events = (p.extrasList || []).filter(function (x) { return x.kind === 'grid_event' && x.counted; }).length;
    var extra = tile('Paid on top', gbp(p.steps.extras),
      (events ? plural(events, 'grid event') + ' with Axle' : 'No grid events') +
      (p.credits ? ', plus Octopus free hours' : '') + ', ' + periodWords(p._key, p) + '.');
    return '<div class="tiles">' + self + price + extra + '</div>';
  }

  function payback(d) {
    var pb = d.payback, q = d.quote, pr = d.projection;
    if (!pb && !q) {
      return '<section class="card"><div class="card-title">Paying for itself</div>' +
        '<div class="note">Put what the system cost on the <a href="settings.html">Settings page</a> ' +
        '(Savings) to see how far it has paid for itself.</div></section>';
    }
    var html = '<section class="card" aria-label="Paying for itself"><div class="card-title">Paying for itself</div>';
    if (pb) {
      html += '<div class="pay-track" role="img" aria-label="' + pct(pb.pct) + ' paid back"><div class="pay-fill" style="width:' +
        Math.max(1, Math.min(100, pb.pct)) + '%"></div></div>';
      html += '<div class="pay-line">' + gbp(pb.savedSoFar) + ' of the ' + gbp(pb.cost) + ' it cost is back, ' +
        pct(pb.pct) + '. ';
      if (pb.paidOffDate) {
        html += 'At this pace it pays for itself in about ' + pb.yearsTotal + ' years, around ' +
          monthYear(pb.paidOffDate) + '.';
      }
      html += '</div>';
    }
    if (q && pr) {
      var rows = [];
      var cmp = function (label, promised, now, fmt, higherBetter) {
        if (promised === null || promised === undefined || now === null || now === undefined) return;
        var good = higherBetter ? now >= promised : now <= promised;
        rows.push('<tr><td>' + label + '</td><td>' + fmt(promised) + '</td><td class="' + (good ? 'better' : 'worse') +
          '">' + fmt(now) + '</td></tr>');
      };
      cmp('Saving a year', q.annualSaving, pr.saved, gbp, true);
      cmp('Solar a year', q.annualKwh, pr.pv, kwh, true);
      if (pb && pb.yearsTotal) cmp('Payback', q.paybackYears, pb.yearsTotal, function (v) { return v + ' years'; }, false);
      if (rows.length) {
        html += '<table class="vs"><thead><tr><th>The quote</th><th>Promised</th><th>On course for</th></tr></thead><tbody>' +
          rows.join('') + '</tbody></table>';
      }
    }
    if (pr) {
      var filled = (pr.filled || []).map(function (m) { return MONTHS[m - 1]; });
      html += '<div class="note">"On course for" takes each month at the pace recorded in it so far' +
        (filled.length ? ', and ' + listWords(filled) + ', not yet on record, at the pace of ' +
          MONTHS[Number(pr.basis.split('-')[1]) - 1] + ', the slowest month so far. December and January are darker still, so treat it as a best case.' : '.') +
        '</div>';
    }
    return html + '</section>';
  }

  function weeksCard(p) {
    var best = p.best, worst = p.worst;
    return '<section class="card" aria-label="Week by week"><div class="card-title">Week by week</div>' +
      '<div class="chart-box"><canvas id="weeks-chart" role="img" aria-label="Saved each week, with the solar made"></canvas></div>' +
      (best && worst ? '<div class="note">The best day was ' + dateWords(best.date) + ', ' + gbp(best.saved) +
        ' saved with ' + kwh(best.pv) + ' of solar. The poorest was ' + dateWords(worst.date) + ', ' +
        (worst.saved < 0 ? 'cost ' + gbp(worst.saved) + ' more' : gbp(worst.saved)) + ' with ' + kwh(worst.pv) + '. The line is the solar made each week, so a poor week shows whether the sky was to blame.</div>' : '') +
      '</section>';
  }

  function erasCard(p) {
    var eras = p.eras || [];
    if (!eras.length) return '';
    var rows = eras.map(function (e) {
      return '<tr><td>' + esc(tariffName(e.name)) + '<div class="note" style="margin-top:2px">' +
        shortDate(e.first) + ' to ' + shortDate(e.last) + '</div></td><td>' + commas(e.days) + '</td><td>' +
        gbp(e.saved) + '</td><td>' + gbp(e.saved / e.days) + '</td><td class="hide-narrow">' + kwh(e.pv / e.days) +
        '</td></tr>';
    }).join('');
    return '<section class="card" aria-label="Tariff by tariff"><div class="card-title">Tariff by tariff</div>' +
      '<table class="tbl"><thead><tr><th>Tariff</th><th>Days</th><th>Saved</th><th>A day</th><th class="hide-narrow">Solar a day</th></tr></thead><tbody>' +
      rows + '</tbody></table><div class="note">A summer tariff and a winter one cannot be compared by the pound alone: ' +
      'the solar a day says how much sun each one had to work with.</div></section>';
  }

  function stack(parts) {
    var total = parts.reduce(function (a, x) { return a + Math.max(0, x[1]); }, 0) || 1;
    return '<div class="stack">' + parts.map(function (x) {
      return '<i style="width:' + (100 * Math.max(0, x[1]) / total).toFixed(2) + '%;background:' + x[2] + '"></i>';
    }).join('') + '</div><div class="legend">' + parts.map(function (x) {
      return '<span><i style="background:' + x[2] + '"></i>' + x[0] + ' <b class="num">' + kwh(x[1]) + '</b></span>';
    }).join('') + '</div>';
  }

  function energyCard(p) {
    var e = p.energy;
    var viaBattery = Math.max(0, e.home_solar - e.direct);
    return '<section class="card" aria-label="Every kWh"><div class="card-title">Every kWh</div>' +
      '<div class="sub-head"><span>Where the house\'s electricity came from</span><span>' + kwh(e.home) + ' used</span></div>' +
      stack([['Solar, as it was made', e.direct, 'var(--solar)'], ['Solar, through the battery', viaBattery, 'var(--bat)'],
             ['Grid, through the battery', e.home_grid_battery, 'var(--accent)'], ['Grid, as it was used', e.home_grid_direct, 'var(--grid-imp)']]) +
      '<div class="sub-head"><span>Where the solar went</span><span>' + kwh(e.pv) + ' made</span></div>' +
      stack([['Used straight away', e.direct, 'var(--solar)'], ['Stored in the battery', e.solar_stored, 'var(--bat)'],
             ['Sold', e.solar_exported, 'var(--grid-exp)']]) +
      (e.batt_export > 1 ? '<div class="note">The battery also sold ' + kwh(e.batt_export) + ' it had stored.</div>' : '') +
      '</section>';
  }

  function extrasCard(p, showAll) {
    var list = (p.extrasList || []).slice().reverse();
    if (!list.length) return '';
    var KIND = { grid_event: 'Axle grid event', top_up: 'Axle monthly top-up', free_hour: 'Octopus free hour', other: 'Axle' };
    var shown = showAll ? list : list.slice(0, 8);
    var rows = shown.map(function (x) {
      var what = x.kind === 'top_up' ? 'Axle top-up for ' + MONTHS[Number(x.date.split('-')[1]) - 1]
               : (KIND[x.kind] || x.kind) + (x.label ? ' (' + esc(x.label) + ')' : '');
      return '<tr><td>' + shortDate(x.date) + '</td><td style="text-align:left">' + what + '</td><td class="hide-narrow">' +
        (x.kwh ? x.kwh.toFixed(1) + ' kWh' : '') + '</td><td' + (x.counted ? '' : ' class="muted"') + '>' +
        gbp(x.gbp) + (x.counted ? '' : '<div class="note" style="margin-top:0">not counted, ' + esc(x.why || '') + '</div>') + '</td></tr>';
    }).join('');
    return '<section class="card" aria-label="Paid on top"><div class="card-title">Paid on top, line by line</div>' +
      '<table class="tbl"><thead><tr><th>Date</th><th style="text-align:left">What</th><th class="hide-narrow">Energy</th><th>Paid</th></tr></thead><tbody>' +
      rows + '</tbody></table>' +
      (list.length > 8 ? '<div class="more"><button class="chip" data-all-extras="1">' +
        (showAll ? 'Show the latest eight' : 'Show all ' + commas(list.length)) + '</button></div>' : '') +
      '</section>';
  }

  function notesCard(d, p) {
    var lines = [];
    lines.push('Records run from ' + dateWords(d.first, true) + ' to ' + dateWords(d.last, true) +
      (d.daysBeforeRecords ? '. The system started ' + plural(d.daysBeforeRecords, 'day') +
        ' before that, which are not counted' : '') + '.');
    if (p.estimatedDays) {
      lines.push(plural(p.estimatedDays, 'day') + ' in this period ' + (p.estimatedDays === 1 ? 'was' : 'were') +
        ' recorded only as daily totals, so how much solar the house used as it was made is estimated for ' +
        (p.estimatedDays === 1 ? 'it' : 'them') + ' from the nearest month recorded half-hourly.');
    }
    if (p.missingDays) {
      lines.push(plural(p.missingDays, 'day') + ' had records that do not add up (the solar is missing), so ' +
        (p.missingDays === 1 ? 'it is' : 'they are') + ' left out.');
    }
    if (p.unpricedDays) {
      lines.push(plural(p.unpricedDays, 'day') + ' could not be priced, because no price was on record for ' +
        (p.unpricedDays === 1 ? 'it' : 'them') + ', and ' + (p.unpricedDays === 1 ? 'is' : 'are') +
        ' counted as nothing in the money above.');
    }
    if (p.billCheck) {
      var gap = Math.abs(p.billCheck.model - p.billCheck.octopus);
      lines.push('On the ' + plural(p.billedDays, 'day') + ' Octopus has billed, its own bill is used. Worked out ' +
        'from the meters instead, those days come to ' + gbp(p.billCheck.model) + (p.billCheck.model < 0 ? ' in credit' : '') +
        ' against Octopus\'s ' + gbp(p.billCheck.octopus) + (p.billCheck.octopus < 0 ? ' in credit' : '') +
        ', ' + gbp(gap) + ' apart, which is how far to trust the days Octopus has not billed yet.');
    }
    lines.push('Electricity only: gas is not counted. Battery wear is not counted either.');
    if (d.rates && d.rates.fetched) {
      var when = new Date(d.rates.fetched * 1000);
      lines.push('Standard prices are Octopus\'s own published Flexible Octopus and Outgoing Octopus prices' +
        ((d.rates.products || {}).region ? ' for region ' + esc(d.rates.products.region) : '') + ', read ' + when.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' }) +
        (d.rates.stale ? ', the last copy, because Octopus could not be reached since' : '') + '.');
    }
    return '<section class="card" aria-label="How this is worked out"><div class="card-title">How this is worked out</div>' +
      lines.map(function (l) { return '<div class="note">' + l.charAt(0).toUpperCase() + l.slice(1) + '</div>'; }).join('') + '</section>';
  }

  function page(d, key, step, showAll, narrow) {
    var p = d.periods[key];
    p._key = key;
    if (STEPS.indexOf(step) < 0) step = 'nokit';
    var w = stepWords(step, p);
    var chips = PERIODS.filter(function (x) { return d.periods[x[0]]; }).map(function (x) {
      return '<button class="chip' + (x[0] === key ? ' on' : '') + '" data-period="' + x[0] + '" aria-pressed="' +
        (x[0] === key) + '">' + x[1] + '</button>';
    }).join('');
    var hero = '<section class="card" aria-label="What was saved"><div class="chips">' + chips + '</div>' +
      '<div class="hero"><div><div class="hero-big num">' + savedWords(p.saved)[0] + '</div>' +
      '<div class="hero-sub">' + (p.saved < 0
        ? 'more spent ' + periodWords(key, p) + ' than the same house would have with no solar or battery on the standard tariff.'
        : 'saved ' + periodWords(key, p) + ', against the same house with no solar or battery on the standard tariff.') + '</div></div>' +
      '<div class="ring-wrap"><div class="ring-text"><b class="num">' + pct(p.selfSufficiencyPct) + '</b>of the electricity the house used came from its own panels.</div></div></div></section>';
    var steps = '<section class="card" aria-label="Step by step"><div class="card-title">Step by step</div>' +
      waterfall(p, step, narrow) +
      '<div class="wf-explain" aria-live="polite"><div class="head"><span>' + esc(w.head) + '</span><span class="num">' +
      esc(w.fig) + '</span></div>' + w.text + '</div><div class="note">Tap a bar to see what it means.</div></section>';
    return hero + steps + tiles(p) + payback(d) + weeksCard(p) + erasCard(p) + energyCard(p) +
      extrasCard(p, showAll) + notesCard(d, p);
  }

  function drawWeeks(canvas, p) {
    if (!canvas || !p || typeof DashUI === 'undefined' || !DashUI.chartRender) return;
    var weeks = p.weeks || [];
    var css = getComputedStyle(document.documentElement);
    var good = css.getPropertyValue('--good').trim() || '#2e9e5b';
    var solar = css.getPropertyValue('--solar').trim() || '#f5a623';
    var muted = css.getPropertyValue('--text-secondary').trim();
    var grid = css.getPropertyValue('--border').trim();
    DashUI.chartRender(canvas, {
      type: 'bar',
      data: {
        labels: weeks.map(function (w) { return w.week; }),
        datasets: [
          { type: 'bar', label: 'Saved', data: weeks.map(function (w) { return w.saved; }), yAxisID: 'y',
            backgroundColor: weeks.map(function (w) { return w.days < 7 ? good + '88' : good; }), borderRadius: 3, order: 2 },
          { type: 'line', label: 'Solar', data: weeks.map(function (w) { return w.pv; }), yAxisID: 'y2',
            borderColor: solar, backgroundColor: solar, pointRadius: 0, borderWidth: 2, tension: 0.3, order: 1 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: function (items) {
              if (!items.length) return '';
              var w = weeks[items[0].dataIndex];
              return 'Week of ' + dateWords(w.week) + (w.days < 7 ? ' (' + plural(w.days, 'day') + ')' : '');
            },
            label: function (item) {
              var w = weeks[item.dataIndex];
              return item.dataset.label === 'Saved' ? gbp(w.saved) + ' saved' : kwh(w.pv) + ' of solar';
            },
          } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: muted, maxTicksLimit: 8, autoSkip: true,
               callback: function (_v, i) { return shortDate(weeks[i].week); } } },
          y: { min: 0, grid: { color: grid }, ticks: { color: muted, maxTicksLimit: 5, callback: function (v) { return gbp(v); } } },
          y2: { min: 0, position: 'right', grid: { display: false },
                ticks: { color: muted, maxTicksLimit: 5, callback: function (v) { return v + ' kWh'; } } },
        },
      },
    });
  }

  root.SavingsView = { page: page, drawWeeks: drawWeeks,
                       _t: { gbp: gbp, kwh: kwh, pence: pence, stepWords: stepWords, waterfall: waterfall,
                             tariffName: tariffName, dateWords: dateWords, plural: plural, listWords: listWords,
                             payback: payback, notesCard: notesCard, savedWords: savedWords } };
})(typeof window !== 'undefined' ? window : globalThis);
