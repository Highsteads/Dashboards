/* Filename:    dashboards-icons.js
 * Description: The dashboard's icon set — line icons on a 24x24 grid, drawn
 *              with currentColor so each one takes the colour of whatever it
 *              sits in.
 *
 *              The pages used emoji for this: 106 of them across 51 distinct
 *              glyphs. Emoji are a font, not artwork — they render differently
 *              on every platform, they carry their own fixed colours which
 *              fight the palette beside them, and they ignore `color`
 *              entirely. index.html's .card-icon has always had a tinted
 *              rounded square with a `color` set on it, which the emoji inside
 *              simply disregarded; the design had been waiting for this.
 *
 *              Two ways in:
 *                <span data-icon="bed"></span>          markup, filled on load
 *                DashIcons.svg('bed', 20)               a string, for template
 *                                                       literals in page JS
 * Author:      CliveS & Claude Opus 5
 * Date:        28-07-2026
 * Version:     1.0
 */

(function (root) {
  'use strict';

  var doc = root.document;

  /* Every path is drawn inside 0 0 24 24, unfilled, and inherits stroke width
     and colour from the <svg> wrapper. Keep new icons to the same weight and
     the same optical size — an icon that is bolder or larger than its
     neighbours is the thing the eye catches, and it will not be the one that
     matters. */
  var P = {
    /* ── rooms ── */
    lounge:   'M3 11.5V8.6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2.9M2.2 11.5h19.6v5.2H2.2z' +
              'M4.4 16.7v2.2M19.6 16.7v2.2M6.6 11.5V9.4h10.8v2.1',
    bed:       'M3 19.6v-9.2M3 15.4h18M21 19.6v-5.4a3.8 3.8 0 0 0-3.8-3.8H9.4v5' +
              'M6.6 12.6a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z',
    dining:   'M6.4 3.2v7.4a2 2 0 0 0 2 2h.4v8.2M6.4 3.2v4.6M9.2 3.2v4.6' +
              'M17.6 3.2c-1.5 0-2.4 2-2.4 5.2s.9 4.4 2.4 4.4v8m0-17.6v9.6',
    kitchen:  'M4 9.6h16M4 9.6a8 8 0 0 1 16 0M6.6 9.6v9a2 2 0 0 0 2 2h6.8a2 2 0 0 0 2-2v-9' +
              'M9.6 5.4h.01M12 4.6h.01M14.4 5.4h.01',
    door:      'M6.4 20.8V4.4a1.4 1.4 0 0 1 1.4-1.4h8.4a1.4 1.4 0 0 1 1.4 1.4v16.4M3.8 20.8h16.4' +
              'M15 12.8a.8.8 0 1 0 0-1.6.8.8 0 0 0 0 1.6z',
    shower:    'M12 2.6v3.4M5.6 10.6a6.4 6.4 0 0 1 12.8 0z' +
              'M8.4 14.2v1.6M12 14.2v1.6M15.6 14.2v1.6M8.4 18.4v1.6M12 18.4v1.6M15.6 18.4v1.6',
    bath:      'M3 13.4h18v1.8a4.4 4.4 0 0 1-4.4 4.4H7.4A4.4 4.4 0 0 1 3 15.2z' +
              'M6.6 13.4V6.2a1.8 1.8 0 0 1 1.8-1.8h2.4M7.6 19.6l-1 1.8M16.4 19.6l1 1.8',
    plant:     'M8.8 21h6.4l.9-6.2H7.9zM12 14.8V9.4' +
              'M12 11.8c0-2.3 1.7-4 4.1-4.1.1 2.3-1.6 4.1-4.1 4.1z' +
              'M12 13.2c0-2-1.5-3.5-3.6-3.6-.1 2 1.4 3.6 3.6 3.6z',
    car:      'M4.6 16.6h14.8M5.4 16.6l1.5-5.4a2 2 0 0 1 1.9-1.4h6.4a2 2 0 0 1 1.9 1.4l1.5 5.4' +
              'M3.6 16.6v2.6a1 1 0 0 0 1 1h1.4a1 1 0 0 0 1-1v-2.6' +
              'M17 16.6v2.6a1 1 0 0 0 1 1h1.4a1 1 0 0 0 1-1v-2.6M3.6 16.6h16.8',
    garage:   'M3.4 20.6V9.8L12 4.2l8.6 5.6v10.8M3.4 20.6h17.2' +
              'M6.8 20.6v-7.4h10.4v7.4M6.8 16.4h10.4',
    laundry:   'M4.4 3.8h15.2a1.4 1.4 0 0 1 1.4 1.4v13.6a1.4 1.4 0 0 1-1.4 1.4H4.4A1.4 1.4 0 0 1 3 18.8V5.2a1.4 1.4 0 0 1 1.4-1.4z' +
              'M3 8h18M6 5.9h.01M9 5.9h.01' +
              'M12 10.4a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z',
    house:    'M2.9 10.6L12 3.2l9.1 7.4M5.3 9v10.6a1.3 1.3 0 0 0 1.3 1.3h10.8a1.3 1.3 0 0 0 1.3-1.3V9' +
              'M9.7 20.9v-6.1h4.6v6.1',

    /* ── status ── */
    check:    'M4.4 12.6l5 5L19.6 6.8',
    warn:     'M12 3.6l9.4 16.2H2.6L12 3.6zM12 9.6v4.8M12 17.4v.01',
    alert:     'M8.7 2.8h6.6l4.9 4.9v6.6l-4.9 4.9H8.7l-4.9-4.9V7.7z' +
              'M12 7.8v5M12 16.4v.01',
    cross:    'M6 6l12 12M18 6L6 18',
    bell:     'M12 3a5.6 5.6 0 0 0-5.6 5.6c0 4.6-1.8 6-1.8 6h14.8s-1.8-1.4-1.8-6A5.6 5.6 0 0 0 12 3z' +
              'M10.1 18.4a2.2 2.2 0 0 0 3.8 0',

    /* ── system ── */
    disk:     'M4.4 4.2h15.2a1.4 1.4 0 0 1 1.4 1.4v12.8a1.4 1.4 0 0 1-1.4 1.4H4.4A1.4 1.4 0 0 1 3 18.4V5.6a1.4 1.4 0 0 1 1.4-1.4z' +
              'M7.4 4.2v5.4h9.2V4.2M14 6.2v1.6M7.4 19.8v-5.2h9.2v5.2',
    memory:   'M6.6 6.6h10.8v10.8H6.6zM9.6 6.6V3.4M14.4 6.6V3.4M9.6 20.6v-3.2M14.4 20.6v-3.2' +
              'M17.4 9.6h3.2M17.4 14.4h3.2M3.4 9.6h3.2M3.4 14.4h3.2',
    gear:     'M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z' +
              'M19.1 14.6a1.6 1.6 0 0 0 .3 1.7l.1.1a1.9 1.9 0 1 1-2.7 2.7l-.1-.1a1.6 1.6 0 0 0-2.7 1.1v.3a1.9 1.9 0 1 1-3.8 0v-.2a1.6 1.6 0 0 0-2.8-1.1l-.1.1a1.9 1.9 0 1 1-2.7-2.7l.1-.1a1.6 1.6 0 0 0-1.1-2.7h-.3a1.9 1.9 0 1 1 0-3.8h.2A1.6 1.6 0 0 0 4.6 7l-.1-.1a1.9 1.9 0 1 1 2.7-2.7l.1.1a1.6 1.6 0 0 0 1.7.3H9a1.6 1.6 0 0 0 1-1.5v-.3a1.9 1.9 0 1 1 3.8 0v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1a1.9 1.9 0 1 1 2.7 2.7l-.1.1a1.6 1.6 0 0 0-.3 1.7V9a1.6 1.6 0 0 0 1.5 1h.3a1.9 1.9 0 1 1 0 3.8h-.2a1.6 1.6 0 0 0-1.4 1z',
    camera:   'M2.8 7.6h11.6a1.6 1.6 0 0 1 1.6 1.6v5.6a1.6 1.6 0 0 1-1.6 1.6H2.8a1.6 1.6 0 0 1-1.6-1.6V9.2a1.6 1.6 0 0 1 1.6-1.6z' +
              'M16 12.6l5.4 3.2a.6.6 0 0 0 .9-.5V8.7a.6.6 0 0 0-.9-.5L16 11.4z',
    plug:     'M8.4 2.6v6M15.6 2.6v6M6.4 8.6h11.2v3.2a5.6 5.6 0 0 1-11.2 0V8.6zM12 17.4V21.4',
    battery:   'M4.4 8.6h12a2 2 0 0 1 2 2v2.8a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2v-2.8a2 2 0 0 1 2-2z' +
              'M20.6 11v2M5.6 10.9h4.6v2.2H5.6z',
    link:     'M9.6 13.4a3.6 3.6 0 0 0 5.4.4l2.8-2.8a3.6 3.6 0 0 0-5.1-5.1l-1.6 1.6' +
              'M14.4 10.6a3.6 3.6 0 0 0-5.4-.4l-2.8 2.8a3.6 3.6 0 0 0 5.1 5.1l1.6-1.6',
    file:     'M13.4 2.8H6.8a1.8 1.8 0 0 0-1.8 1.8v14.8a1.8 1.8 0 0 0 1.8 1.8h10.4a1.8 1.8 0 0 0 1.8-1.8V8.2z' +
              'M13.4 2.8v5.4h5.6',
    folder:   'M3 7.4a1.8 1.8 0 0 1 1.8-1.8h4l2 2.6h7.4A1.8 1.8 0 0 1 21 10v7.6a1.8 1.8 0 0 1-1.8 1.8H4.8A1.8 1.8 0 0 1 3 17.6z',
    health:   'M3 12.4h4.2l2-5.2 3.6 10 2-4.8H21',

    /* ── domain ── */
    bolt:     'M13.4 2.4L4.6 13.4h6.2l-1 8.2 8.8-11h-6.2z',
    flame:     'M13.6 2.4c.4 3.4-2.2 4.6-3.4 6.6-1.1 1.9-.4 3.6.5 4.4-.9.2-2.3-.6-2.7-2.1' +
              '-1 1.4-1.4 2.8-1.4 4.2 0 3.4 2.8 5.9 6.2 5.9s6.2-2.5 6.2-5.9c0-4.6-3.7-8-5.4-13.1z' +
              'M12 21.4c1.9 0 3.4-1.4 3.4-3.2 0-2-1.7-3-1.7-4.9-1.4.8-2.3 2-2.3 3.4 ' +
              '0 .6-.4 1.1-1 1.1s-.9-.5-.9-1.2c-.6.8-1 1.7-1 2.6 0 1.8 1.6 2.2 3.5 2.2z',
    bulb:     'M9.2 18h5.6M10 21h4M8 13.6a5.4 5.4 0 1 1 8 0c-.8.9-1.2 1.6-1.2 2.6H9.2c0-1-.4-1.7-1.2-2.6z',
    person:   'M4.4 20.6v-1.8a4.4 4.4 0 0 1 4.4-4.4h6.4a4.4 4.4 0 0 1 4.4 4.4v1.8' +
              'M12 10.6a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6z',
    walk:     'M13.4 5.4a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8z' +
              'M9 22l2.2-6.2-2.4-2.2.9-5 3.7 1.6 2.8 2.8h3M9.8 10.2L6.6 12l-1.4 4M13 15l2 7',
    window:   'M4.4 3.6h15.2a1 1 0 0 1 1 1v14.8a1 1 0 0 1-1 1H4.4a1 1 0 0 1-1-1V4.6a1 1 0 0 1 1-1z' +
              'M12 3.6v16.8M3.4 12h17.2',
    lock:     'M6.6 10.6h10.8a1.6 1.6 0 0 1 1.6 1.6v7.2a1.6 1.6 0 0 1-1.6 1.6H6.6A1.6 1.6 0 0 1 5 19.4v-7.2a1.6 1.6 0 0 1 1.6-1.6z' +
              'M8.2 10.6V7.4a3.8 3.8 0 0 1 7.6 0v3.2',
    shield:   'M12 21.4s7.4-3.6 7.4-9.4V5.4L12 2.6 4.6 5.4V12c0 5.8 7.4 9.4 7.4 9.4z',
    drop:     'M12 2.8s6 6.4 6 10.4a6 6 0 0 1-12 0c0-4 6-10.4 6-10.4z',
    money:    'M12 21.4a9.4 9.4 0 1 0 0-18.8 9.4 9.4 0 0 0 0 18.8z' +
              'M14.8 8.4a3 3 0 0 0-5.2 2v3.2c0 1-.6 1.8-1.4 2.2h7.6M8.8 12.6h4.4',
    thermo:   'M14 14.2V5.4a2 2 0 1 0-4 0v8.8a4.4 4.4 0 1 0 4 0z',
    wifi:     'M4.2 9.6a11 11 0 0 1 15.6 0M7 12.8a7 7 0 0 1 10 0M9.8 16a3 3 0 0 1 4.4 0M12 19.4v.01',
    sun:      'M12 16.2a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4z' +
              'M12 1.8v2.8M12 19.4v2.8M22.2 12h-2.8M4.6 12H1.8' +
              'M19.2 4.8l-1.9 1.9M6.7 17.3l-1.9 1.9M19.2 19.2l-1.9-1.9M6.7 6.7L4.8 4.8',
    cloudsun:  'M7.4 11.4a3 3 0 1 0 0-6 3 3 0 0 0 0 6z' +
              'M7.4 2.6v1.4M3.6 4.2l1 1M2.2 8.4h1.4M11.2 4.2l-1 1' +
              'M9.6 20.8h7.8a3.6 3.6 0 0 0 .3-7.2 5 5 0 0 0-9.4-1 3.9 3.9 0 0 0 1.3 8.2z',
    storm:     'M7.8 16.4h8.6a3.6 3.6 0 0 0 .3-7.2 5 5 0 0 0-9.4-1 3.9 3.9 0 0 0 .5 8.2z' +
              'M13.2 13.2l-3.4 5h3.6l-2.6 4.4',
    clock:    'M12 21.4a9.4 9.4 0 1 0 0-18.8 9.4 9.4 0 0 0 0 18.8zM12 6.8V12l3.4 2',
    clipboard:'M9.6 3.4h4.8a1.2 1.2 0 0 1 1.2 1.2v1.2a1.2 1.2 0 0 1-1.2 1.2H9.6a1.2 1.2 0 0 1-1.2-1.2V4.6a1.2 1.2 0 0 1 1.2-1.2z' +
              'M15.6 5.2h1.8a1.8 1.8 0 0 1 1.8 1.8v12.4a1.8 1.8 0 0 1-1.8 1.8H6.6a1.8 1.8 0 0 1-1.8-1.8V7a1.8 1.8 0 0 1 1.8-1.8h1.8',
    film:     'M4 3.6h16a1.4 1.4 0 0 1 1.4 1.4v14a1.4 1.4 0 0 1-1.4 1.4H4a1.4 1.4 0 0 1-1.4-1.4V5A1.4 1.4 0 0 1 4 3.6z' +
              'M7.6 3.6v16.8M16.4 3.6v16.8M2.6 12h18.8M2.6 7.8h5M2.6 16.2h5M16.4 7.8h5M16.4 16.2h5',
    sparkle:  'M12 2.8l2.2 6 6 2.2-6 2.2-2.2 6-2.2-6-6-2.2 6-2.2z',
    pylon:    'M12 2.6L6 21.4M12 2.6l6 18.8M4.4 6.6h15.2M7.6 13.4h8.8M9.3 9.8h5.4',
    inverter: 'M2 12c2.2-6.2 4.4-6.2 6.6 0c2.2 6.2 4.4 6.2 6.6 0c2.2-6.2 4.4-6.2 6.6 0',
  };

  /* Aliases, so a page can name the thing rather than the drawing. */
  var ALIAS = {
    bedroom: 'bed', 'living-room': 'lounge', 'dining-room': 'dining',
    hall: 'door', 'en-suite': 'shower', bathroom: 'bath',
    conservatory: 'plant', drive: 'car', utility: 'laundry',
    ok: 'check', good: 'check', error: 'cross', danger: 'alert',
    cpu: 'gear', load: 'gear', ram: 'memory', storage: 'disk',
    presence: 'person', motion: 'walk', heating: 'flame', light: 'bulb',
    energy: 'bolt', cost: 'money', water: 'drop', temperature: 'thermo',
    system: 'health', scenes: 'film', weather: 'cloudsun', solar: 'sun',
  };

  function resolve(name) {
    name = String(name || '').trim();
    return P[name] ? name : (ALIAS[name] && P[ALIAS[name]] ? ALIAS[name] : null);
  }

  /* An <svg> string. `size` is optional — left off, it fills its box, which is
     what the tinted .card-icon square wants. */
  function svg(name, size, extraClass) {
    var key = resolve(name);
    if (!key) return '';
    var dim = size ? ' width="' + size + '" height="' + size + '"' : '';
    return '<svg class="dsh-icon' + (extraClass ? ' ' + extraClass : '') + '"' + dim +
           ' viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
           '<path d="' + P[key] + '"/></svg>';
  }

  var STYLE_ID = 'dashui-icons-css';
  function injectStyle() {
    if (!doc || doc.getElementById(STYLE_ID)) return;
    var s = doc.createElement('style');
    s.id = STYLE_ID;
    s.textContent =
      '.dsh-icon{width:1em;height:1em;display:inline-block;vertical-align:-.135em;' +
      'fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;' +
      'stroke-linejoin:round;overflow:visible}' +
      /* In the hub's tinted square the icon should fill the square, not the
         line-height — that container sets its own font-size for the old emoji. */
      '.card-icon .dsh-icon{width:60%;height:60%;stroke-width:1.6}' +
      '[data-icon]{display:inline-flex;align-items:center;justify-content:center}';
    (doc.head || doc.documentElement).appendChild(s);
  }

  /* Fill every <span data-icon="x"> on the page. Idempotent, so a page that
     rebuilds part of its DOM can just call it again. */
  function upgrade(rootEl) {
    if (!doc) return 0;
    injectStyle();
    var n = 0;
    (rootEl || doc).querySelectorAll('[data-icon]').forEach(function (el) {
      if (el.firstElementChild && el.firstElementChild.classList.contains('dsh-icon')) return;
      var html = svg(el.getAttribute('data-icon'));
      if (!html) return;
      el.innerHTML = html;
      n++;
    });
    return n;
  }

  /* Fill on load, then keep filling. Half these pages build their markup from
     template literals long after DOMContentLoaded — the Settings rows, the
     custom-link tiles — so a one-shot pass leaves those with empty squares
     where an icon should be. Watching the tree removes a whole class of
     "forgot to call upgrade after rendering" bug rather than asking every
     caller to remember. */
  function watch() {
    upgrade();
    if (!root.MutationObserver) return;
    var pending = false;
    // Called through `root`, not detached: requestAnimationFrame invoked
    // without its receiver throws "Illegal invocation" and the observer then
    // silently stops filling anything.
    var soon = root.requestAnimationFrame
      ? function (fn) { root.requestAnimationFrame(fn); }
      : function (fn) { root.setTimeout(fn, 0); };
    var obs = new root.MutationObserver(function (records) {
      if (pending) return;
      for (var i = 0; i < records.length; i++) {
        if (records[i].addedNodes.length) {
          pending = true;
          // Coalesce a burst of renders into one pass; upgrade() skips
          // anything already filled, so a spare call costs almost nothing.
          soon(function () { pending = false; upgrade(); });
          return;
        }
      }
    });
    obs.observe(doc.body || doc.documentElement, { childList: true, subtree: true });
  }

  if (doc) {
    if (doc.readyState === 'loading') {
      doc.addEventListener('DOMContentLoaded', watch);
    } else {
      watch();
    }
  }

  var API = { svg: svg, upgrade: upgrade, has: function (n) { return !!resolve(n); },
              names: function () { return Object.keys(P).sort(); } };
  root.DashIcons = API;
  if (typeof globalThis !== 'undefined') globalThis.DashIcons = API;
})(typeof window !== 'undefined' ? window : globalThis);
