// Numeric readings update synchronously, while graphical callbacks may animate.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const code = fs.readFileSync(new URL('../Dashboards.indigoPlugin/Contents/Resources/static/pages/dashboards-ui.js', import.meta.url), 'utf8');
let frames = [];
const ctx = { requestAnimationFrame: fn => frames.push(fn), matchMedia: () => ({ matches: false }) };
vm.createContext(ctx);
vm.runInContext(code, ctx);
const el = { dataset: { _val: '12' }, textContent: '12' };
ctx.DashUI.tweenNumber(el, 37.5, { decimals: 1, suffix: ' W' });
assert.equal(el.textContent, '37.5 W');
assert.equal(frames.length, 0);
ctx.DashUI.tweenNumber(el, 1500, { format: n => (n / 1000).toFixed(2) + ' kW' });
assert.equal(el.textContent, '1.50 kW');
ctx.DashUI.tweenNumber(el, 25, { apply: (e, n) => { e.ring = n; } });
assert.equal(frames.length, 1, 'custom graphical updates retain animation');
console.log('Immediate numbers: formatting and graphical animation checks passed');
