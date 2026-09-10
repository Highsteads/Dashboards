/* Filename:    dashboards-ui.js
 * Description: Shared DOM helpers for the dashboard pages, plus the live
 *              power-flow diagram drawn on the Energy hero and the hub's
 *              Energy card.
 *
 *              energy.html kept its own cssVar / setText / tweenNumber and a
 *              hand-written SVG that no other page could reuse, so the hub
 *              showed the same four figures as plain text rows. Everything
 *              that touches the DOM lives here; the pure arithmetic stays in
 *              energy-calc.js, which is DOM-free so its tests can drive it.
 *
 *              The diagram builds its SVG ONCE and thereafter writes only
 *              attributes and styles, so it can sit inside a card that
 *              repaints on a 3-second poll without tearing down animations.
 * Author:      CliveS & Claude Opus 5 (v1.0); Claude Fable 5 (v1.1)
 * Date:        13-08-2026
 * Version:     1.1 (solarHoursChart — the stacked per-string hourly chart,
 *              shared by the Energy card and the hub's Solar · today block)
 */

(function (root) {
  'use strict';

  var doc = root.document;

  /* ── small DOM helpers (moved out of energy.html) ── */

  function cssVar(name, fallback) {
    if (!doc) return fallback;
    var v = getComputedStyle(doc.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function setText(id, v) {
    var e = typeof id === 'string' ? doc.getElementById(id) : id;
    if (e && e.textContent !== v) e.textContent = v;
  }

  function reducedMotion() {
    return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* Headline numbers update immediately. Custom graphical apply callbacks may tween.
     `format` exists because the power figures switch unit at 1 kW and again at
     10 kW (DashCalc.fmtKw), which the prefix/suffix/decimals form cannot say.
     `apply` lets a caller drive something that is not text — the battery ring
     tweens its stroke-dashoffset through the same easing.
     Each tween stamps a generation on the element so a second update arriving
     mid-flight cancels the first instead of two loops fighting over it. */
  function tweenNumber(el, target, opts) {
    if (!el) return;
    opts = opts || {};
    var dur = opts.duration || 600;
    var decimals = opts.decimals || 0;
    var prefix = opts.prefix || '';
    var suffix = opts.suffix || '';
    var apply = opts.apply || function (e, v) {
      if (opts.format) e.textContent = opts.format(v);
      else e.textContent = prefix + v.toFixed(decimals) + suffix;
    };

    var from = parseFloat(el.dataset._val);
    if (isNaN(from)) from = (target === null || target === undefined || isNaN(target)) ? 0 : Number(target);
    var to = (target === null || target === undefined || isNaN(target)) ? 0 : Number(target);
    el.dataset._val = String(to);

    var gen = String((parseInt(el.dataset._gen || '0', 10) + 1) % 100000);
    el.dataset._gen = gen;

    if (!opts.apply || reducedMotion() || Math.abs(to - from) < 0.005 || !root.requestAnimationFrame) {
      apply(el, to);
      return;
    }
    var t0 = root.performance ? performance.now() : 0;
    function step(t) {
      if (el.dataset._gen !== gen) return;          // superseded
      var p = Math.min(1, (t - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      apply(el, from + (to - from) * eased);
      if (p < 1) root.requestAnimationFrame(step);
    }
    root.requestAnimationFrame(step);
  }

  /* ── power flow diagram ──────────────────────────────────────────────
     Four nodes around an inverter hub, on the diagonals so each node's text
     sits on the OUTER side and never crosses the track running inward.

     What the motion means, which is the point of the redraw: the marching
     dashes run in the direction the power is travelling, their speed scales
     with the load and so does the stroke width. The old version ran three
     dots at a fixed 1.5 s whatever the figure, so 200 W and 8 kW looked
     identical.                                                           */

  /* Text always sits on the OUTER side of its disc, so a track running inward
     to the hub can never cross it. The two rows therefore mirror: the top row
     stacks label/value/sub upward away from the icon, the bottom row stacks
     them downward. Both still read label, value, sub top to bottom. */
  var GEO_FULL = {
    w: 600, h: 350,
    hub:  { x: 300, y: 179, r: 34, glyph: 30 },
    discR: 26, iconSize: 26, ringR: 32,
    startR: 40, endR: 42,
    nodes: {
      pv:   { x:  80, y: 116, out: -1 },
      grid: { x: 520, y: 116, out: -1 },
      home: { x:  80, y: 242, out:  1 },
      bat:  { x: 520, y: 242, out:  1 },
    },
    topOff: { lab: -76, val: -54, sub: -40 },
    botOff: { lab:  48, val:  68, sub:  84 },
    showLabel: true, showSub: true, showHub: true,
  };

  /* The hub's card carries the SAME readings as the energy page — same
     labels, same figures, same battery treatment. It was showing neither the
     node labels nor the battery's power and stored energy, which made it a
     summary of the diagram rather than the diagram. Only the size differs. */
  var GEO_COMPACT = {
    w:440,h:340,hub:{x:220,y:170,r:24,glyph:22},
    discR:14,iconSize:18,ringR:10,startR:28,endR:24,
    nodes:{pv:{x:108,y:68,out:-1},grid:{x:332,y:68,out:-1},home:{x:108,y:272,out:1},bat:{x:332,y:272,out:1}},
    topOff:{lab:-32,val:7,sub:31},botOff:{lab:-32,val:7,sub:31},
    showLabel:true,showSub:true,showHub:true
  };

  var LABELS = { pv: 'Solar', grid: 'Grid', home: 'Home', bat: 'Battery' };
  var ICONS  = { pv: 'sun', grid: 'pylon', home: 'house', bat: 'batt' };

  /* 24x24 stroke icons. `currentColor` so each one takes its node's colour
     from the group, which is also how the grid icon recolours on export. */
  var ICON_PATHS = {
    sun:
      '<circle cx="12" cy="12" r="4.2"/>' +
      '<path d="M12 1.8v2.8M12 19.4v2.8M22.2 12h-2.8M4.6 12H1.8' +
      'M19.2 4.8l-1.9 1.9M6.7 17.3l-1.9 1.9M19.2 19.2l-1.9-1.9M6.7 6.7L4.8 4.8"/>',
    house:
      '<path d="M2.9 10.6L12 3.2l9.1 7.4"/>' +
      '<path d="M5.3 9v10.6a1.3 1.3 0 0 0 1.3 1.3h10.8a1.3 1.3 0 0 0 1.3-1.3V9"/>' +
      '<path d="M9.7 20.9v-6.1h4.6v6.1"/>',
    pylon:
      '<path d="M12 2.6L6 21.4M12 2.6l6 18.8M4.4 6.6h15.2M7.6 13.4h8.8M9.3 9.8h5.4"/>',
    batt:
      '<rect x="2.2" y="7.4" width="16.6" height="9.2" rx="2.8"/>' +
      '<path d="M21.4 10.5v3"/>',
    /* The hub already has its ring, so the glyph only has to say "inverter".
       A boxed symbol at this size read as a broken-image placeholder; a plain
       alternating wave does not. */
    inv:
      '<path d="M2 12c2.2-6.2 4.4-6.2 6.6 0c2.2 6.2 4.4 6.2 6.6 0c2.2-6.2 4.4-6.2 6.6 0"/>',
  };

  function r1(n) { return Math.round(n * 10) / 10; }

  /* Straight run from the node's disc edge to the hub's edge. */
  function legPath(node, hub, startR, endR) {
    var dx = hub.x - node.x, dy = hub.y - node.y;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var ux = dx / len, uy = dy / len;
    return 'M' + r1(node.x + ux * startR) + ' ' + r1(node.y + uy * startR) +
           'L' + r1(hub.x - ux * endR) + ' ' + r1(hub.y - uy * endR);
  }

  /* Dashes per second. Flat below 100 W so a trickle still visibly creeps,
     square-rooted above it so the middle of the range spreads out instead of
     everything under 2 kW looking the same. */
  var FLOW_FULL_W = 8000;
  function flowDuration(watts) {
    var t = Math.sqrt(Math.min(FLOW_FULL_W, Math.abs(watts)) / FLOW_FULL_W);
    return (2.2 - 1.75 * t).toFixed(2) + 's';
  }
  function flowWidth(watts) {
    var t = Math.sqrt(Math.min(FLOW_FULL_W, Math.abs(watts)) / FLOW_FULL_W);
    return r1(2.4 + 4.6 * t);
  }

  var DEADBAND_W = 30;   /* unchanged from the original diagram */
  var _uid = 0;

  /* The diagram's stylesheet is injected rather than pasted into each page's
     inline <style>. There is no shared .css file in the bundle, and copying
     forty lines into two 90 KB HTML files is how the palette drifted apart in
     the first place. Injected once, guarded by its id. */
  var STYLE_ID = 'dashui-flow-css';
  var STYLE = [
    '.fdg{width:100%;height:auto;display:block;margin:0 auto;overflow:visible}',
    '.fdg use{fill:none;stroke:currentColor;stroke-width:1.7;',
    'stroke-linecap:round;stroke-linejoin:round}',
    '.fdg-compact use{stroke-width:2.1}',
    '.fdg text{text-anchor:middle;dominant-baseline:auto}',
    '.fdg-panel{fill:var(--card-bg-alt,#f5f5f8);stroke:var(--border-soft,#e8e8ed);stroke-width:.7}',
    '.fdg-disc{fill:var(--card-bg,#fff);stroke:var(--border-soft,#e8e8ed);stroke-width:1}',
    '.fdg-lab{font-size:10px;font-weight:600;letter-spacing:.6px;',
    'text-transform:uppercase;fill:var(--text-secondary,#86868b)}',
    '.fdg-val{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;',
    'letter-spacing:-.01em;fill:currentColor}',
    '.fdg-sub{font-size:10px;fill:var(--text-muted,#98989d)}',
    '.fdg-compact .fdg-val{font-size:15px}',
    '.fdg-compact .fdg-lab{font-size:9px;letter-spacing:.5px}',
    '.fdg-compact .fdg-sub{font-size:9px}',
    '.fdg-hub{color:var(--text-muted,#98989d)}',
    '.fdg-hub-ring{fill:none;stroke:var(--border-soft,#e8e8ed);stroke-width:1.5}',
    '.fdg-ring-bg{fill:none;stroke:var(--off-color,#d2d2d7);stroke-width:3}',
    '.fdg-ring{fill:none;stroke-width:3;stroke-linecap:round;transition:stroke .4s}',
    '.fdg-track{fill:none;stroke:var(--off-color,#d2d2d7);stroke-width:2;opacity:.5}',
    '.fdg-flow{fill:none;stroke-linecap:round;stroke-dasharray:9 20;opacity:0;',
    'animation:fdg-march 1s linear infinite;',
    'transition:stroke-width .45s ease,opacity .3s ease,stroke .45s ease}',
    '@keyframes fdg-march{to{stroke-dashoffset:-29}}',
    /* Bigger type on a phone: the SVG scales down with the viewport, so the
       17 px value would land around 10 px on a 380 px screen. */
    '@media(max-width:560px){.fdg-val{font-size:23px}.fdg-lab{font-size:13px}',
    '.fdg-sub{font-size:13px}.fdg use{stroke-width:1.4}}',
    '@media(prefers-reduced-motion:reduce){.fdg-flow{animation:none;stroke-dasharray:none}}',
    '.fcb-lab{fill:var(--text-muted,#98989d)}',
    '.fcb-empty{fill:var(--text-secondary,#86868b);font-size:13px}',
    '.fcb-axis{stroke:var(--border-soft,#e8e8ed);stroke-width:1}',
  ].join('');

  function injectStyle() {
    if (!doc || doc.getElementById(STYLE_ID)) return;
    var s = doc.createElement('style');
    s.id = STYLE_ID;
    s.textContent = STYLE;
    (doc.head || doc.documentElement).appendChild(s);
  }

  function flowDiagram(mount, opts) {
    if (!mount) return null;
    opts = opts || {};
    injectStyle();
    var G = opts.compact ? GEO_COMPACT : GEO_FULL;
    var p = opts.idPrefix || ('fd' + (++_uid));

    /* ── build the skeleton once ── */
    var defs = '<defs>';
    Object.keys(ICON_PATHS).forEach(function (k) {
      defs += '<symbol id="' + p + '-i-' + k + '" viewBox="0 0 24 24">' +
              ICON_PATHS[k] + '</symbol>';
    });
    defs += '</defs>';

    var tracks = '', flows = '', nodes = '';
    Object.keys(G.nodes).forEach(function (k) {
      var n = G.nodes[k];
      var d = opts.compact
        ? 'M'+n.x+' '+(n.y+(n.out<0?58:-58))+' V'+(n.out<0?158:182)+' H'+(n.x<220?190:250)
        : legPath(n, G.hub, G.startR, G.endR);
      tracks += '<path class="fdg-track" d="' + d + '"/>';
      flows  += '<path class="fdg-flow" id="' + p + '-flow-' + k + '" d="' + d + '"/>';

      if (opts.compact) {
        var tile = '<g class="fdg-node fdg-tile" id="'+p+'-node-'+k+'" transform="translate('+n.x+','+n.y+')">'+
          '<rect class="fdg-panel" x="-96" y="-58" width="192" height="116" rx="14"/>'+
          '<use href="#'+p+'-i-'+ICONS[k]+'" x="-78" y="-43" width="18" height="18"/>'+
          '<text class="fdg-lab" x="-50" y="-30">'+LABELS[k]+'</text>'+
          '<text class="fdg-val" id="'+p+'-val-'+k+'" x="-78" y="8">—</text>'+
          '<text class="fdg-sub" id="'+p+'-sub-'+k+'" x="-78" y="34"></text>';
        if(k==='bat') tile += '<circle class="fdg-ring-bg" cx="72" cy="-35" r="10"/>'+
          '<circle class="fdg-ring" id="'+p+'-ring" r="10" stroke-dasharray="62.8" stroke-dashoffset="62.8" transform="translate(72,-35) rotate(-90)"/>';
        nodes += tile+'</g>'; return;
      }
      var s = G.iconSize;
      var g = '<g class="fdg-node" id="' + p + '-node-' + k + '" transform="translate(' + n.x + ',' + n.y + ')">';
      if (opts.compact) g += '<rect class="fdg-panel" x="-58" y="' + (n.out < 0 ? -77 : -27) + '" width="116" height="110" rx="12"/>';
      g += '<rect class="fdg-disc" x="' + (-G.discR) + '" y="' + (-G.discR) + '" width="' + (G.discR * 2) + '" height="' + (G.discR * 2) + '" rx="9"/>';
      if (k === 'bat') {
        var c = 2 * Math.PI * G.ringR;
        g += '<circle class="fdg-ring-bg" r="' + G.ringR + '"/>' +
             '<circle class="fdg-ring" id="' + p + '-ring" r="' + G.ringR + '"' +
             ' stroke-dasharray="' + r1(c) + '" stroke-dashoffset="' + r1(c) + '"' +
             ' transform="rotate(-90)"/>';
      }
      g += '<use href="#' + p + '-i-' + ICONS[k] + '" xlink:href="#' + p + '-i-' + ICONS[k] + '"' +
           ' x="' + (-s / 2) + '" y="' + (-s / 2) + '" width="' + s + '" height="' + s + '"/>';
      var off = n.out < 0 ? G.topOff : G.botOff;
      if (G.showLabel) {
        g += '<text class="fdg-lab" y="' + off.lab + '">' + LABELS[k] + '</text>';
      }
      g += '<text class="fdg-val" id="' + p + '-val-' + k + '" y="' + off.val + '">—</text>';
      if (G.showSub) {
        g += '<text class="fdg-sub" id="' + p + '-sub-' + k + '" y="' + off.sub + '"></text>';
      }
      g += '</g>';
      nodes += g;
    });

    var hub = '';
    if(opts.compact) {
      hub='<g class="fdg-hub" transform="translate(220,170)"><rect class="fdg-core" x="-30" y="-24" width="60" height="48" rx="12"/>'+
        '<use href="#'+p+'-i-inv" x="-13" y="-13" width="26" height="26"/></g>'+
        '<text class="fdg-core-label" x="220" y="211">INVERTER</text>';
    } else if (G.showHub) {
      hub = '<g class="fdg-hub" transform="translate(' + G.hub.x + ',' + G.hub.y + ')">' +
            '<circle class="fdg-hub-ring" r="' + G.hub.r + '"/>' +
            '<use href="#' + p + '-i-inv" xlink:href="#' + p + '-i-inv"' +
            ' x="' + (-G.hub.glyph / 2) + '" y="' + (-G.hub.glyph / 2) + '"' +
            ' width="' + G.hub.glyph + '" height="' + G.hub.glyph + '"/></g>';
    }

    mount.innerHTML =
      '<svg class="fdg' + (opts.compact ? ' fdg-compact' : '') + '" viewBox="0 0 ' + G.w + ' ' + G.h + '"' +
      ' xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"' +
      ' role="img" aria-label="Live power flow: solar, home, grid and battery">' +
      defs + tracks + flows + hub + nodes + '</svg>';

    /* Scoped lookups, not getElementById — the card may build its diagram
       before the mount is attached to the document. */
    var svg = mount.querySelector('svg');
    function pick(suffix) { return svg.querySelector('[id="' + p + suffix + '"]'); }
    var el = { svg: svg, ring: pick('-ring') };
    ['pv', 'grid', 'home', 'bat'].forEach(function (k) {
      el['node_' + k] = pick('-node-' + k);
      el['flow_' + k] = pick('-flow-' + k);
      el['val_' + k]  = pick('-val-' + k);
      el['sub_' + k]  = pick('-sub-' + k);
    });

    /* Colours are re-read on every update rather than cached, so a light/dark
       switch takes effect on the next poll. The old code froze them as hex at
       load and the dots stayed on the light palette in dark mode. */
    function palette() {
      return {
        pv:      cssVar('--solar',     '#f5a623'),
        home:    cssVar('--home-load', '#af52de'),
        gridImp: cssVar('--grid-imp',  '#ff3b30'),
        gridExp: cssVar('--grid-exp',  '#0a84ff'),
        batChg:  cssVar('--bat-chg',   '#0a84ff'),
        batDis:  cssVar('--bat-dis',   '#ff3b30'),
        idle:    cssVar('--text-muted', '#98989d'),
      };
    }

    /* One leg: colour, direction, speed and thickness from the signed watts.
       `inward` is the direction the path itself was drawn (node -> hub), so a
       flow going the other way just plays the same animation in reverse. */
    function setLeg(key, watts, colour, inward) {
      var flow = el['flow_' + key];
      if (!flow) return;
      var live = Math.abs(watts) >= DEADBAND_W;
      flow.style.opacity = live ? '1' : '0';
      if (!live) return;
      flow.style.stroke = colour;
      flow.style.strokeWidth = flowWidth(watts);
      flow.style.animationDirection = inward ? 'normal' : 'reverse';
      var dur = flowDuration(watts);
      if (flow.style.animationDuration !== dur) flow.style.animationDuration = dur;
    }

    function fmt(w) {
      return (root.DashCalc && root.DashCalc.fmtKw) ? root.DashCalc.fmtKw(w) : Math.round(w) + ' W';
    }

    function update(st) {
      st = st || {};
      var pvW   = Number(st.pv   || 0);
      var homeW = Number(st.home || 0);
      var gridW = Number(st.grid || 0);      // + import, − export
      var batW  = Number(st.bat  || 0);      // + charging, − discharging
      var soc   = (st.soc == null || st.soc === '') ? null : Number(st.soc);   // '' is a never-written state, not 0 %
      var subs  = st.subs || {};
      var C = palette();

      var importing = gridW > DEADBAND_W;
      var charging  = batW  > DEADBAND_W;
      var gridCol = importing ? C.gridImp : C.gridExp;
      var batCol  = charging  ? C.batChg  : C.batDis;

      /* node colours (the icon inherits through `color`) */
      el.node_pv.style.color   = C.pv;
      el.node_home.style.color = C.home;
      el.node_grid.style.color = Math.abs(gridW) >= DEADBAND_W ? gridCol : C.gridExp;
      el.node_bat.style.color  = cssVar('--bat', '#34c759');

      /* legs — paths run node -> hub, so `inward` true means power arriving */
      setLeg('pv',   pvW,   C.pv,    true);
      setLeg('home', homeW, C.home,  false);
      setLeg('grid', gridW, gridCol, importing);
      setLeg('bat',  batW,  batCol,  !charging);

      /* values */
      tweenNumber(el.val_pv,   pvW,             { format: fmt });
      tweenNumber(el.val_home, homeW,           { format: fmt });
      tweenNumber(el.val_grid, Math.abs(gridW), { format: fmt });

      var idle = Math.abs(batW) < DEADBAND_W;
      tweenNumber(el.val_bat, Math.abs(batW),
                  { format: function (v) { return idle ? 'Idle' : fmt(v); } });

      /* subs */
      if (G.showSub) {
        setText(el.sub_pv,   subs.pv   || '');
        setText(el.sub_home, subs.home || '');
        setText(el.sub_grid, subs.grid ||
          (importing ? 'Importing' : (gridW < -DEADBAND_W ? 'Exporting' : 'Idle')));
        setText(el.sub_bat,  subs.bat ||
          (charging ? 'Charging' : (batW < -DEADBAND_W ? 'Discharging' : 'Idle')));
      }

      /* battery ring */
      if (el.ring && soc != null && !isNaN(soc)) {
        var circ = 2 * Math.PI * G.ringR;
        var pct = Math.max(0, Math.min(100, soc));
        el.ring.style.stroke = pct >= 60 ? cssVar('--on-color', '#34c759')
                             : pct >= 30 ? cssVar('--solar', '#f5a623')
                                         : cssVar('--bad', '#ff3b30');
        tweenNumber(el.ring, pct, {
          apply: function (e, v) {
            e.setAttribute('stroke-dashoffset', r1(circ * (1 - v / 100)));
          },
        });
      }
    }

    return { el: el.svg, update: update };
  }


  /* ── hourly solar forecast bars ──────────────────────────────────────
     Drawn from the same function on the Energy page and the hub, so the two
     cannot drift. Reads its geometry from the target's own viewBox, so a
     caller sizes the chart by choosing the viewBox rather than by passing
     numbers.

     Colours come from the palette. The Energy page's copy had them written in
     as hex, which meant the bars kept the light-mode colours in dark mode —
     and one of those hex values was the battery green from before v2.52.0, so
     it had already gone stale. */
  /* ── solar hours chart (v1.1) ──────────────────────────────────────────
     Draws the row model from DashCalc.buildSolarHours: elapsed hours as
     per-string stacked bars, each with a dashed tick at the forecast height,
     and future hours as pale forecast bars. Shared so the Energy card and
     the hub's Solar · today block are the SAME chart at two sizes — the
     lesson of forecastBars, whose duplicate copy in energy.html kept its
     light-mode hex colours in dark mode until v2.50.0 merged them.

     model  {rows, won, played} from DashCalc.buildSolarHours
     opts   stringLabels  4 names, PV-input order [W, E, S, G] (titles only)
            compact       true on the hub: no y-axis scale, fewer hour
                          labels, thinner ticks — the block is 380 px wide
            hitTargets    emit per-hour transparent rects for a tap handler

     Stack order is biggest string first (bottom) so the shape stays stable
     as the day turns. Beat/miss is GEOMETRY — the stack topping or missing
     its tick — never colour alone, so it survives colour-blindness. */
  var STRING_COLOURS = ['#369b91', '#5596c9', '#5266a8', '#b58a58'];  /* W E S G */
  var STRING_STACK_ORDER = [2, 1, 0, 3];                              /* S E W G */

  function solarHoursChart(el, model, opts) {
    if (!el || !model || !model.rows) return;
    opts = opts || {};
    var compact = !!opts.compact;
    var labels = opts.stringLabels || ['West', 'East', 'South', 'Garage'];
    var vb = (el.getAttribute('viewBox') || '0 0 756 190').split(/\s+/).map(Number);
    var W = vb[2] || 756, H = vb[3] || 190;
    var padL = compact ? 30 : 38, padR = 8;
    var padT = 29, padB = 25;

    var maxY = 0.5;
    model.rows.forEach(function (r) {
      maxY = Math.max(maxY, r.total || 0, r.forecast || 0);
    });
    var step = maxY <= 2 ? 0.5 : maxY <= 6 ? 2 : Math.ceil(maxY / 3);
    maxY = Math.ceil(maxY / step) * step;
    var colW = (W - padL - padR) / 24;
    var barW = colW * 0.7;
    var y = function (k) { return H - padB - (k / maxY) * (H - padT - padB); };

    var solar = cssVar('--solar', '#f5a623');
    var grid = cssVar('--border-soft', '#e5e5ea');
    var muted = cssVar('--text-secondary', '#86868b');
    var ink = cssVar('--text', '#1d1d1f');
    var out = '<text x="' + padL + '" y="12" font-size="10" fill="' + muted + '">kWh</text>';
    out += '<line x1="' + (W-116) + '" y1="9" x2="' + (W-98) + '" y2="9" stroke="' + muted + '" stroke-dasharray="3 3"/>' +
           '<text x="' + (W-91) + '" y="12" font-size="10" fill="' + muted + '">Forecast</text>';
    var current = model.rows.find(function(r){return r.mode === 'current';});
    if(current) {
      var nx = padL + (current.h + 1) * colW;
      out += '<rect x="' + r1(nx) + '" y="' + padT + '" width="' + r1(W-padR-nx) + '" height="' + (H-padT-padB) + '" fill="' + grid + '" opacity=".32"/>';
      out += '<line x1="' + r1(nx) + '" x2="' + r1(nx) + '" y1="' + padT + '" y2="' + (H-padB) + '" stroke="' + muted + '" stroke-dasharray="2 4" opacity=".55"/>';
    }

    /* Scale: the full chart earns gridlines with kWh labels; the compact one
       gets a single baseline, because 380 px cannot carry an axis and 24
       columns without becoming a smear. */
    var gridCount = Math.round(maxY / step);
    for (var g = 1; g <= gridCount; g++) {
      var gv = maxY * g / gridCount;
      out += '<line x1="' + padL + '" y1="' + r1(y(gv)) + '" x2="' + (W - padR) +
             '" y2="' + r1(y(gv)) + '" stroke="' + grid + '" stroke-width="1"/>';
      {
        out += '<text x="' + (padL - 4) + '" y="' + r1(y(gv) + 3) +
               '" text-anchor="end" font-size="9.5" fill="' + muted + '">' +
               (gv >= 10 ? Math.round(gv) : gv.toFixed(1)) + '</text>';
      }
    }

    model.rows.forEach(function (r) {
      var x0 = padL + r.h * colW + (colW - barW) / 2;
      var hh = (r.h < 10 ? '0' + r.h : r.h) + ':00';
      if (r.mode === 'future') {
        if (r.forecast > 0.01) {
          out += '<g><rect x="' + r1(x0) + '" y="' + r1(y(r.forecast)) + '" width="' + r1(barW) +
                 '" height="' + r1(y(0) - y(r.forecast)) + '" rx="2" fill="' + solar +
                 '" opacity="0.25"/><title>' + hh + ' — forecast ' + r.forecast.toFixed(2) +
                 ' kWh</title></g>';
        }
      } else if (r.parts) {
        var base = 0, tip = '';
        STRING_STACK_ORDER.forEach(function (idx) {
          var v = r.parts[idx] || 0;
          if (v <= 0.001) return;
          out += '<rect x="' + r1(x0) + '" y="' + r1(y(base + v)) + '" width="' + r1(barW) +
                 '" height="' + r1(Math.max(0.8, y(base) - y(base + v))) +
                 '" fill="' + STRING_COLOURS[idx] + '"/>';
          base += v;
          tip += (tip ? ' · ' : '') + labels[idx] + ' ' + v.toFixed(2);
        });
        out += '<rect x="' + r1(x0) + '" y="' + r1(y(r.total)) + '" width="' + r1(barW) +
               '" height="' + r1(y(0) - y(r.total)) + '" fill="transparent"><title>' +
               hh + ' — ' + tip + ' = ' + r.total.toFixed(2) + ' kWh (forecast ' +
               r.forecast.toFixed(2) + ')</title></rect>';
      } else if (r.total != null && r.total > 0.01) {
        out += '<g><rect x="' + r1(x0) + '" y="' + r1(y(r.total)) + '" width="' + r1(barW) +
               '" height="' + r1(y(0) - y(r.total)) + '" rx="2" fill="' + solar +
               '" opacity="0.85"/><title>' + hh + ' — ' + r.total.toFixed(2) +
               ' kWh (forecast ' + r.forecast.toFixed(2) + ')</title></g>';
      }
      /* Hour labels: every hour is legible at full width, every third on the
         hub — an unreadable axis is worse than a sparse one. */
      var every = compact ? 6 : 2;
      if (r.h % every === 0) {
        out += '<text x="' + r1(x0 + barW / 2) + '" y="' + (H - (compact ? 3 : 6)) +
               '" text-anchor="middle" font-size="' + (compact ? 10 : 10) + '" fill="' + muted +
               '"' + (r.mode === 'current' ? ' font-weight="700"' : '') + '>' + String(r.h).padStart(2, '0') + '</text>';
      }
      if (opts.hitTargets) {
        out += '<rect x="' + r1(padL + r.h * colW) + '" y="0" width="' + r1(colW) +
               '" height="' + H + '" fill="transparent" data-h="' + r.h + '" style="cursor:pointer"/>';
      }
    });
    var forecastPath = model.rows.map(function(r,i){return (i ? 'L' : 'M') + r1(padL+(r.h+.5)*colW) + ' ' + r1(y(r.forecast || 0));}).join(' ');
    out += '<path d="' + forecastPath + '" fill="none" stroke="' + muted + '" stroke-width="1.25" stroke-dasharray="3 3" stroke-linejoin="round" opacity=".85" pointer-events="none"/>';
    el.innerHTML = out;
  }

  function forecastBars(el, hourly, opts) {
    if (!el) return;
    opts = opts || {};
    injectStyle();
    var vb = (el.getAttribute('viewBox') || '0 0 756 80').split(/\s+/).map(Number);
    var W = vb[2] || 756, H = vb[3] || 80;
    var entries = Object.keys(hourly || {}).sort().map(function (k) { return [k, hourly[k]]; });
    if (!entries.length) {
      el.innerHTML = '<text x="' + (W / 2) + '" y="' + (H / 2) +
                     '" text-anchor="middle" class="fcb-empty">No forecast yet</text>';
      return;
    }
    var pastCol = cssVar('--solar', '#f5a623');
    var nowCol  = cssVar('--accent', '#5856d6');
    var maxK = Math.max.apply(null, entries.map(function (e) { return Number(e[1]) || 0; }).concat([0.1]));
    var curHr = opts.hour == null ? new Date().getHours() : opts.hour;
    var lblH = opts.labels === false ? 0 : (opts.labelSize || 9) + 5;
    var chartH = H - lblH - 2;
    var pad = 6, n = entries.length;
    var step = (W - pad * 2) / n;
    var bw = Math.max(2, step - Math.max(1, step * 0.18));
    /* Label every hour if they fit, otherwise every other one, so a narrow
       chart does not turn its axis into a smear. */
    var every = step < 16 ? 3 : (step < 26 ? 2 : 1);
    var out = '';
    entries.forEach(function (e, i) {
      var hr = parseInt(e[0].split(':')[0], 10);
      var kwh = Number(e[1]) || 0;     // a string-valued hourly entry threw at toFixed()
      var bh = Math.max(1, Math.round((kwh / maxK) * chartH));
      var x = pad + i * step + (step - bw) / 2;
      var isNow = hr === curHr;
      out += '<g><rect x="' + r1(x) + '" y="' + r1(chartH - bh) + '" width="' + r1(bw) +
             '" height="' + bh + '" rx="2" fill="' + (isNow ? nowCol : pastCol) +
             '" opacity="' + (hr < curHr ? '0.3' : '1') + '"/>' +
             '<title>' + (hr < 10 ? '0' + hr : hr) + ':00 — ' + kwh.toFixed(2) + ' kWh</title></g>';
      if (lblH && hr % every === 0) {
        out += '<text x="' + r1(x + bw / 2) + '" y="' + (H - 2) +
               '" text-anchor="middle" class="fcb-lab" font-size="' + (opts.labelSize || 9) + '">' + hr + '</text>';
      }
    });
    out += '<line x1="' + pad + '" y1="' + chartH + '" x2="' + (W - pad) + '" y2="' + chartH +
           '" class="fcb-axis"/>';
    el.innerHTML = out;
  }


  /* ── how are we reaching the server? ─────────────────────────────────
     The camera work needs this. The MJPEG proxy listens on its own port,
     which the Indigo reflector does NOT front — so over the reflector a live
     stream cannot work at all, and over Tailscale it works but costs about
     4 Mbit/s per camera on whatever mobile signal you happen to have.

     This is the honest trigger for cutting the cameras down: it is the link
     itself, known the moment the page loads. Presence would only be a proxy
     for it, and a wrong one when you are at home on a poor signal or away on
     someone else's wifi.

       'home'      RFC1918 or loopback — the LAN. Everything is cheap.
       'vpn'       Tailscale's CGNAT range. Streams reachable but expensive.
       'reflector' anything else. The MJPEG port is not reachable at all. */
  function linkClass() {
    /* The SERVER's verdict wins (v2.96.1): a changedSince reply that carried
       via:"reflector" was seen arriving through the reflector, whatever the
       address bar says. Only ever downgrades. */
    if (root.__DASH_VIA === 'reflector') return 'reflector';
    var h = (root.location && root.location.hostname) || '';
    // An IPv6 literal arrives from location.hostname wrapped in brackets, so a
    // bare '::1' comparison could never match what a browser actually reports.
    var v6 = h.replace(/^\[|\]$/g, '').toLowerCase();
    if (h === 'localhost' || v6 === '::1' || /\.local$/i.test(h)) return 'home';
    // Tailscale MagicDNS (<host>.<tailnet>.ts.net) is a NAME, not an address,
    // so the IPv4 test below fell through and classified it 'reflector' —
    // which switches live streaming off entirely. The tailnet routes arbitrary
    // ports perfectly well, so it belongs with the CGNAT range as 'vpn'.
    if (/\.ts\.net$/i.test(h)) return 'vpn';
    // IPv6 unique-local (fc00::/7) is the v6 equivalent of a private range.
    if (/^f[cd][0-9a-f]{2}:/.test(v6)) return 'home';
    var m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
    if (!m) return 'reflector';
    var a = +m[1], b = +m[2];
    if (a === 127) return 'home';
    if (a === 10) return 'home';
    if (a === 192 && b === 168) return 'home';
    if (a === 172 && b >= 16 && b <= 31) return 'home';
    if (a === 100 && b >= 64 && b <= 127) return 'vpn';   // Tailscale CGNAT
    return 'reflector';
  }
  /* ---- how fast is this link, really? ---------------------------------
     A HOSTNAME CANNOT ANSWER THIS, and assuming it could is what made
     "the cameras stop when I'm away" survive three attempts at fixing it.

     A LAN address reached over a VPN subnet route is byte-identical to
     being on the LAN. A tailnet with a subnet router advertising, say,
     192.168.1.0/24 lets a phone on mobile data open the bookmarked
     http://192.168.1.10:8176/ through the tunnel while location.hostname
     still reads 192.168.1.10 — the page concluded
     'home', opened six live MJPEG streams and pushed 5.5 MB/s (44 Mbit/s)
     down a mobile connection, which is what actually stalled the tiles.

     So measure the round trip instead. The result is cached for the session
     so pages do not re-probe on every navigation.

     THE THRESHOLD WAS ORIGINALLY 20 ms AND THAT WAS WRONG. It came from the
     assumption that "a LAN fetch is single-digit milliseconds", which is true
     of a wired Mac and NOT of a phone on wi-fi — the client that actually
     matters here. Measured on CliveS's iPhone, from the page footer:

         home wi-fi, no VPN     21 ms      <- the real "home" case
         home wi-fi over VPN   116 ms
         5G over VPN           245 ms

     So he missed being classified as home BY ONE MILLISECOND, on his own
     network, and never got live video anywhere — the symptom was silent
     because falling back to stills looks like a deliberate choice.

     50 ms sits at the geometric mean of the two nearest readings (21 and 116),
     giving a 2.4x margin below and 2.3x above. The remote readings cannot
     realistically come down to meet it: 116 ms was a tunnel between two
     devices in the SAME BUILDING, so any genuinely remote path is worse. It is
     also kinder to anyone whose wi-fi is slower than his, which a 20 ms bar
     would have shut out of live video entirely. */
  var RTT_HOME_MS   = 50;     /* above this, treat the link as remote */
  var RTT_PROBE_KEY = 'dash_link_rtt';

  /* The verdict used to be cached for the WHOLE browser session, which meant a
     device that changed network kept the old answer until the tab was closed.
     CliveS hit exactly that: he turned wi-fi off, moved to mobile data, and the
     page went on behaving as though it were at home. So the cache now expires,
     and a page can drop it deliberately when it has reason to think the network
     moved — see forgetRtt() and the visibility handler in cameras.html. Long
     enough that ordinary navigation between pages does not re-probe; short
     enough that picking the phone up somewhere else gets a fresh answer. */
  var RTT_CACHE_MS = 60000;

  function _cachedRtt() {
    try {
      var raw = sessionStorage.getItem(RTT_PROBE_KEY);
      if (raw === null) return null;
      var v = JSON.parse(raw);
      if (!v || typeof v.ms !== 'number') return null;
      if (Date.now() - v.at > RTT_CACHE_MS) return null;
      return v.ms;
    } catch (e) { return null; }
  }

  /* Throw the cached verdict away, so the next measuredClass() really measures. */
  function forgetRtt() {
    try { sessionStorage.removeItem(RTT_PROBE_KEY); } catch (e) {}
  }

  /* FASTEST of three small same-origin fetches.

     It was the median until v2.95.0, and the median measures the wrong thing.
     Latency noise is one-sided: a sleeping wi-fi radio, a busy CPU or a
     retried frame can only ever make a request arrive LATER, and nothing can
     make one arrive sooner than the path allows. So the quickest sample is the
     honest reading of the link, and the median mostly reports how noisy the
     DEVICE is.

     That distinction cost CliveS his camera mosaic. A phone and a laptop sat
     on the same LAN, feet apart, and the phone was classed remote: iOS parks
     the wi-fi radio between requests, so a phone pays a wake-up on samples a
     laptop never pays, and two slow samples out of three are enough to drag
     the median over a 50 ms bar. The floor of the three was always well under
     it. Taking the minimum keeps the bar strict rather than loosening it — a
     genuinely remote link cannot produce a sub-50 ms sample at all, however
     many times it is asked. */
  /* Guard on the FUNCTION, never on its return value: performance.now() is
     falsy at exactly 0, and the old `performance.now() ? ... : Date.now()`
     form then took the start from one clock and the end from the other. */
  var _now = function () {
    return (root.performance && performance.now) ? performance.now() : Date.now();
  };

  function probeRtt() {
    var cached = _cachedRtt();
    if (cached !== null) return Promise.resolve(cached);
    var url = 'config.js';
    var runs = [];
    var chain = Promise.resolve();
    for (var i = 0; i < 3; i++) {
      chain = chain.then(function () {
        var t0 = _now();
        return fetch(url + '?rtt=' + Date.now() + Math.random(), { cache: 'no-store' })
          .then(function () {
            var t1 = _now();
            runs.push(t1 - t0);
          })
          .catch(function () { runs.push(9999); });
      });
    }
    return chain.then(function () {
      // Math.min over the samples. A failed fetch pushed 9999, so a probe that
      // could not reach the server at all still reads as remote.
      var best = runs.length ? Math.min.apply(null, runs) : 9999;
      try {
        sessionStorage.setItem(RTT_PROBE_KEY,
          JSON.stringify({ ms: Math.round(best), at: Date.now() }));
      } catch (e) {}
      return best;
    });
  }

  /* The class to actually act on. Resolves to the address-based answer,
     except that a 'home' verdict must SURVIVE the measurement — a slow link
     wearing a LAN address is remote, whatever the address says. Never
     upgrades: a genuinely remote address is not made local by a fast probe. */
  function measuredClass() {
    var addr = linkClass();
    if (addr !== 'home') return Promise.resolve(addr);
    return probeRtt().then(function (ms) {
      return ms <= RTT_HOME_MS ? 'home' : 'vpn';
    });
  }

  /* ---- how much can this link actually CARRY? (v2.97.0) ---------------
     Latency was the wrong question. It was asked because a slow link cannot
     hold an MJPEG stream — but what a stream needs is THROUGHPUT, and the two
     come apart exactly where it matters. CliveS's iPhone on the house wi-fi
     with Tailscale running measures 116 ms, because every packet goes out to
     the tunnel and back in; its throughput is the whole of the home wi-fi.
     Judged on latency it was "remote" and got 3-second stills while sitting
     in the same room as the cameras. Judged on throughput it is what it is:
     a fast link that happens to take the long way round.

     So measure bytes per second, on a real file, and subtract the round trip
     so a small file over a high-latency link is not mistaken for a slow one. */
  var BW_PROBE_KEY  = 'dash_link_bw';
  var BW_CACHE_MS   = 60000;
  /* THE PAYLOAD HAS TO BE BIG ENOUGH TO TIME (v2.99.0). The probe used to
     fetch dashboards-ui.js, 44 KB — which a home link delivers in about 3 ms,
     so the measurement was one scheduler hiccup wide and any hiccup halved it.
     The largest asset the pages already ship is ~205 KB: 16 ms on a fast link,
     48 ms at the 34 Mbit/s the strip needs for four tiles, so the decision
     boundary is measured with room to spare. Falls back to the small file if
     the big one is not there. */
  var BW_FILES      = ['chart.umd.min.js', 'dashboards-ui.js'];
  /* Warm-up first, and take the BEST of the timed samples. Both corrections
     point the same way and for the same reason: interference is ONE-SIDED.
     A cold connection, TCP slow start, the page's own boot fetches and a
     sleeping phone radio can only ever make a reading WORSE — nothing makes
     bytes arrive faster than the link allows. MEASURED on this LAN, back to
     back: first fetch 6.9 Mbit/s, the four after it 92, 126, 117, 110. One
     cold sample therefore reported a fifteenth of the truth, which floors the
     budget at zero tiles and shows four 3-second stills to a phone in the same
     room as the cameras. Same lesson as the RTT floor above. */
  var BW_SAMPLES    = 2;
  /* One live MJPEG tile measured ~4.25 Mbit/s (17 Mbit/s for the hub's four).
     Ask for twice that before opening one: a link with no headroom queues,
     and a queued MJPEG stream never catches up — it just gets further behind
     (measured 30 s+ adrift), which is worse than a still on every count. */
  var LIVE_TILE_KBPS = 4250;
  var LIVE_HEADROOM  = 2;

  function _cachedBw() {
    try {
      var raw = sessionStorage.getItem(BW_PROBE_KEY);
      if (!raw) return null;
      var v = JSON.parse(raw);
      if (!v || typeof v.kbps !== 'number') return null;
      if (Date.now() - (v.at || 0) > BW_CACHE_MS) return null;
      return v.kbps;
    } catch (e) { return null; }
  }
  function forgetBw() { try { sessionStorage.removeItem(BW_PROBE_KEY); } catch (e) {} }

  /* One timed fetch, in kbit/s. 0 when it could not be fetched at all. */
  function _bwSample(url, rtt) {
    var t0 = _now();
    return fetch(url + '?bw=' + Date.now() + Math.random(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.arrayBuffer() : Promise.reject(new Error(r.status)); })
      .then(function (buf) {
        /* Take the transfer time, not the whole round trip: on a 200 ms link
           a 205 KB file "takes" 250 ms, and calling that 6 Mbit/s would
           understate a fast tunnel by an order of magnitude.
           BOUNDED, because the correction stops making sense once the round
           trip is most of the elapsed time: on this LAN the fetch takes 3 ms
           and the round trip is 2.3 ms, so subtracting it left 0.66 ms and
           claimed 2.8 Gbit/s. Never credit the link with more than 2.5x what
           was actually observed — enough to rescue a high-latency tunnel,
           not enough to invent a gigabit. */
        var elapsed = Math.max(0.5, _now() - t0);
        var ms = Math.max(elapsed * 0.4, elapsed - Math.min(rtt, elapsed) * 0.9);
        return (buf.byteLength * 8) / ms;          /* bytes*8 per ms == kbit/s */
      })
      .catch(function () { return 0; });
  }

  /* kbit/s, measured: a warm-up fetch to open the connection, then the best of
     BW_SAMPLES timed fetches of an asset the pages already ship. Best, not
     mean or median — see BW_SAMPLES above. */
  function probeBandwidth() {
    var cached = _cachedBw();
    if (cached !== null) return Promise.resolve(cached);
    return probeRtt().then(function (rtt) {
      /* Which asset is actually there. The warm-up doubles as the check, and
         its timing is DISCARDED — it is the cold one, and cold is the reading
         that was wrong before. */
      var chain = BW_FILES.reduce(function (prev, f) {
        return prev.then(function (found) {
          if (found) return found;
          return fetch(f + '?bwwarm=' + Date.now(), { cache: 'no-store' })
            .then(function (r) { return r.ok ? f : null; })
            .catch(function () { return null; });
        });
      }, Promise.resolve(null));

      return chain.then(function (url) {
        if (!url) return 0;
        var best = 0, i = 0;
        function next() {
          if (i++ >= BW_SAMPLES) return Promise.resolve(best);
          return _bwSample(url, rtt).then(function (kbps) {
            if (kbps > best) best = kbps;
            return next();
          });
        }
        return next();
      }).then(function (kbps) {
        try {
          sessionStorage.setItem(BW_PROBE_KEY,
            JSON.stringify({ kbps: Math.round(kbps), at: Date.now() }));
        } catch (e) {}
        return kbps;
      });
    }).catch(function () { return 0; });   /* could not measure == cannot afford a stream */
  }

  /* How many live MJPEG tiles this link can carry. 0 means stills only.
     The reflector is always 0 — the stream port is not fronted by it at all,
     so no measurement can make one work. */
  function streamBudget() {
    if (linkClass() === 'reflector') return Promise.resolve(0);
    return probeBandwidth().then(function (kbps) {
      return Math.max(0, Math.floor(kbps / (LIVE_TILE_KBPS * LIVE_HEADROOM)));
    });
  }

  /* ---- press feedback (v2.97.0) ---------------------------------------
     A tap on a phone left nothing behind: :active ends with the finger, and
     a tile that switches something takes a moment to come back with its new
     state, so the honest answer to "did that press land?" was "wait and see".
     One delegated listener marks whatever was pressed for a fifth of a
     second — long enough to see, short enough not to look stuck. The style
     is injected from here so every page has it without 20 copies. */
  var PRESS_SEL = '.fav-tile, .nav-btn, .card, .menu-tile, .menu-back, .door-btn, ' +
                  '.dash-card, .camera-card, .home-cam, button, .tile';
  function pressFeedback() {
    var d = root.document;
    // Presentation only, and it runs on load in every context this file is
    // pulled into — including a contract test's fake window. Anything missing
    // means "not a real page": say nothing and do nothing.
    if (!d || root.__dashPressWired
        || typeof d.addEventListener !== 'function'
        || typeof d.createElement !== 'function' || !d.head) return;
    root.__dashPressWired = true;
    var st = d.createElement('style');
    st.textContent =
      '.dash-pressed{transform:scale(.96)!important;' +
      'box-shadow:0 0 0 2px var(--accent,#4da3ff) inset,0 2px 10px rgba(0,0,0,.25)!important;' +
      'filter:brightness(1.12);transition:transform .06s ease-out,box-shadow .06s ease-out!important}' +
      '@media (prefers-reduced-motion: reduce){.dash-pressed{transform:none!important}}';
    d.head.appendChild(st);
    var clear;
    d.addEventListener('pointerdown', function (ev) {
      var el = ev && ev.target && ev.target.closest && ev.target.closest(PRESS_SEL);
      if (!el) return;
      el.classList.add('dash-pressed');
      clearTimeout(clear);
      clear = setTimeout(function () { el.classList.remove('dash-pressed'); }, 220);
    }, { passive: true, capture: true });
  }
  if (root.document && typeof root.document.addEventListener === 'function') {
    if (root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', pressFeedback);
    } else { pressFeedback(); }
  }

  /* True when a long-lived MJPEG stream is worth opening at all. */
  function canStream()  { return linkClass() !== 'reflector'; }
  /* True when we should be frugal: every byte is on someone's mobile data. */
  function isRemote()   { return linkClass() !== 'home'; }

  /* ---- idle guard (v2.96.1) ------------------------------------------
     A page left open on a table keeps polling for ever. On the LAN that is
     nobody's problem; through the Indigo reflector every still is carried by
     Indigo's own servers, and Indigo Domotics wrote to say so. So a page on
     that route stops its pictures after idleMs with nothing touched, and one
     tap starts them again. Returns {isIdle, stop}. */
  function idleGuard(idleMs, onIdle, onResume) {
    var doc = root.document, last = Date.now(), idle = false;
    function touch() {
      last = Date.now();
      if (idle) { idle = false; try { onResume && onResume(); } catch (e) { /* page's problem */ } }
    }
    if (doc) {
      ['pointerdown', 'touchstart', 'keydown', 'wheel'].forEach(function (ev) {
        doc.addEventListener(ev, touch, { passive: true });
      });
      doc.addEventListener('visibilitychange', function () { if (!doc.hidden) touch(); });
    }
    var every = Math.max(250, Math.min(15000, idleMs / 4));
    var timer = setInterval(function () {
      if (!idle && Date.now() - last >= idleMs) { idle = true; try { onIdle && onIdle(); } catch (e) { /* ditto */ } }
    }, every);
    return { isIdle: function () { return idle; }, stop: function () { clearInterval(timer); } };
  }

  /* The dashboards' LAN address for a page, from config.js — what a
     reflector-origin page offers the reader as the way home. '' if unknown. */
  function lanUrl(page) {
    var c = root.INDIGO_CONFIG || {};
    var b = String(c.lanURL || c.baseURL || '').replace(/\/$/, '');
    if (!b || /^https?:\/\/(127\.|localhost)/i.test(b)) return '';
    return b + '/public/dashboards/' + (page || 'index.html');
  }

  var API = {
    cssVar: cssVar,
    setText: setText,
    tweenNumber: tweenNumber,
    reducedMotion: reducedMotion,
    flowDiagram: flowDiagram,
    forecastBars: forecastBars,
    solarHoursChart: solarHoursChart,
    STRING_COLOURS: STRING_COLOURS,
    STRING_STACK_ORDER: STRING_STACK_ORDER,
    linkClass: linkClass,
    probeBandwidth: probeBandwidth,
    streamBudget: streamBudget,
    forgetBw: forgetBw,
    pressFeedback: pressFeedback,
    LIVE_TILE_KBPS: LIVE_TILE_KBPS,
    idleGuard: idleGuard,
    lanUrl: lanUrl,
    measuredClass: measuredClass,
    probeRtt: probeRtt,
    forgetRtt: forgetRtt,
    RTT_HOME_MS: RTT_HOME_MS,
    canStream: canStream,
    isRemote: isRemote,
    DEADBAND_W: DEADBAND_W,
  };

  root.DashUI = API;
  if (typeof globalThis !== 'undefined') globalThis.DashUI = API;
})(typeof window !== 'undefined' ? window : globalThis);
