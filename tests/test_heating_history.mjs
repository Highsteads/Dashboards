// Filename: test_heating_history.mjs
// Description: Real heating plot transformations: sparse changes, unknowns and clocks.
// Author: CliveS & Codex GPT-6
// Date: 26-10-2026
// Version: 1.0
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source = fs.readFileSync(new URL('../Dashboards.indigoPlugin/Contents/Resources/static/pages/heating-history.js',import.meta.url),'utf8');
const box = {Date,Number,Set}; vm.createContext(box); vm.runInContext(source,box);
const plot=box.HeatingHistory.plot;
const p=(t,v)=>({t,v});
const d={start:1000,end:2000,gapSeconds:300,series:{temperatureinput1:[p(900,18),p(1500,19)],temperatureseenepoch:[p(900,900),p(1100,1100),p(1500,1500),p(1800,1800)],setpointheat:[p(800,12),p(1100,22),p(1110,12)],hvacheaterison:[p(800,0),p(1100,1),p(1110,0)]}};
const v=plot(d);
assert.equal(v.temperature[0].y,18);
assert.equal(v.calling,10,'a ten second call must remain ten seconds');
assert.equal(v.known,900,'100 seconds without fresh measurements must be unknown');
assert(v.temperature.some(p=>p.x===1400 && p.y===null));
assert(v.target.some(p=>p.y===22));
assert.equal(v.events.length,2);
const missing=plot({start:1000,end:2000,series:{temperatureinput1:[p(1200,18)]}});
assert.equal(missing.temperature[0].y,null);
assert.equal(missing.calling,0);
assert.equal(missing.known,0);
assert(missing.target.every(p=>p.y===null));
const offline=structuredClone(d);offline.series.gatewaystatus=[p(800,'online'),p(1105,'offline')];
assert.equal(plot(offline).calling,5);
// Real UTC seconds remain a 24-hour span on either clock change day.
for(const date of ['2026-03-29T12:00:00Z','2026-10-25T12:00:00Z']){
 const end=Date.parse(date)/1000,start=end-86400;
 const result=plot({start,end,gapSeconds:90000,series:{temperatureinput1:[p(start,18)],setpointheat:[p(start,22)],hvacheaterison:[p(start,1)]}});
 assert.equal(result.calling,86400);
}
console.log('Heating history: sparse transitions, missing values, outages and both clock changes passed.');
