// Description: Camera selection, stream-budget handover, freshness, viewport pause and fullscreen fallback.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {checkFn, done} from './lib/check.mjs';
const base = new URL('../Dashboards.indigoPlugin/Contents/Resources/static/pages/', import.meta.url);
const camera=fs.readFileSync(new URL('cameras.html',base),'utf8'), hub=fs.readFileSync(new URL('index.html',base),'utf8');
function fn(source,name) {
 const start=source.indexOf('function '+name+'('); assert(start>=0,name);
 let depth=0; for(let i=source.indexOf('{',start);i<source.length;i++) {
  if(source[i]==='{') depth++;
  else if(source[i]==='}' && --depth===0) return source.slice(start,i+1);
 } throw Error(name);
}
function classes() { const c=new Set(); return {add:x=>c.add(x),remove:x=>c.delete(x),contains:x=>c.has(x),toggle:(x,v)=>{const n=v??!c.has(x);n?c.add(x):c.delete(x);return n;}}; }
function context(pool=6,special=false) {
 const hosts=['a','b','c','d','e','f','g','h'], calls=[];let maximum=0;
 const camState=Object.fromEntries(hosts.map(h=>[h,{mode:'still',paused:false,frameEl:{closest:()=>({classList:classes(),scrollIntoView(){}})}}]));
 const c={LINK:'home',hosts,camState,focusedHost:'a',LIVE_POOL_SIZE:pool,LIVE_FOLLOWS_FOCUS:pool===1,WEBRTC_FOCUS:special,DEFAULT_LIVE:hosts.slice(0,pool),DEFAULT_LIVE_SET:new Set(hosts.slice(0,pool)),allCamerasView:false,document:{getElementById:()=>({classList:classes()})},setCameraView(){},setMode(){}};
 const start=(h,mode)=>{calls.push([h,mode]);camState[h].mode=mode;maximum=Math.max(maximum,hosts.filter(x=>camState[x].mode==='webrtc').length);};
 c.startStill=h=>start(h,'still');c.startLive=c.startWebrtc=h=>start(h,'webrtc');
 vm.createContext(c);vm.runInContext(fn(camera,'mayHoldLive')+'\n'+fn(camera,'focusTile'),c);
 hosts.forEach(h=>{if(special?h==='a':c.mayHoldLive(h)) camState[h].mode='webrtc';});
 return {c,calls,max:()=>maximum};
}
checkFn('Focus receives a live slot within every budget, including repeated handovers',()=>{
 for(const pool of [0,1,2,4,6]) {
  const {c,max}=context(pool);
  for(const h of ['h','g','b','a','h']) {
   c.focusTile(h);const live=c.hosts.filter(x=>c.camState[x].mode==='webrtc');
   assert.equal(live.length,pool);assert(max()<=pool);if(pool) assert(live.includes(h));
   assert.equal(c.hosts.filter(x=>c.mayHoldLive(x)).length,pool);
  }
 }
});
checkFn('Away handover releases the old stream before starting the new one',()=>{
 const {c,calls,max}=context(0,true);c.focusTile('h');
 assert.deepEqual(calls.slice(0,2),[['a','still'],['h','webrtc']]);assert.equal(max(),1);
});
checkFn('Displaced tiles cannot steal a slot back; paused and unknown tiles stay safe',()=>{
 const {c}=context();c.focusTile('h');assert.equal(c.mayHoldLive('f'),false);
 c.camState.g.paused=true;c.focusTile('g');assert.equal(c.camState.g.mode,'still');
 c.focusTile('unknown');assert.equal(c.focusedHost,'g');
});
checkFn('Deep links accept only configured cameras and establish focus before streaming',()=>{
 const c={URLSearchParams};vm.createContext(c);vm.runInContext(fn(camera,'initialCamera'),c);
 assert.equal(c.initialCamera('?camera=cam%202',['cam 1','cam 2']),'cam 2');
 assert.equal(c.initialCamera('?camera=evil',['cam 1']),'cam 1');assert.equal(c.initialCamera('',['cam 1']),'cam 1');
 assert(hub.includes('href="cameras.html?camera=${encodeURIComponent(host)}"'));
 const boot=camera.slice(camera.indexOf('        buildGrid();'));
 assert(boot.indexOf('focusedHost = initialCamera(')<boot.indexOf('relayoutAll();'));
});
checkFn('Hub freshness follows the delivered picture, not unchanged HTTP responses',()=>{
 const c={Date};vm.createContext(c);vm.runInContext(fn(hub,'_hubPictureWords'),c);
 const img={parentNode:{classList:classes()},_stillObj:'blob',_stillMod:new Date(100000).toUTCString()};
 assert.equal(c._hubPictureWords(img,105000),'Picture 5s old');assert.equal(c._hubPictureWords(img,165000),'Picture 1m old');
 img._hubPictureError=true;assert.equal(c._hubPictureWords(img,165000),'Picture unavailable');
 img.parentNode.classList.add('is-live');assert.equal(c._hubPictureWords(img,165000),'Live');
 img.parentNode.classList.remove('is-live');img._hubPictureError=false;img._stillMod=null;
 assert.equal(c._hubPictureWords(img,165000),'Picture age unknown');
});
checkFn('Every tile exposes freshness and stale live video says it stopped',()=>{
 const words=()=>({textContent:'',classList:classes()});
 const c={Date:{now:()=>20000},hosts:['a','b','c'],debugAges:()=>false,STALE_MS:10000,_minAgeAtReceipt:null,frameAgeMs:(s,n)=>s.frameModMs==null?null:n-s.frameModMs,
 camState:{a:{mode:'still',frameModMs:15000,ageEl:words()},b:{mode:'webrtc',lastChangeAt:19000,ageEl:words()},c:{mode:'webrtc',lastChangeAt:1000,ageEl:words()}}};
 vm.createContext(c);vm.runInContext(fn(camera,'tickAges'),c);c.tickAges();
 assert.equal(c.camState.a.ageEl.textContent,'Picture 5s old');assert.equal(c.camState.b.ageEl.textContent,'Live');assert.equal(c.camState.c.ageEl.textContent,'Video stopped');
});
checkFn('A short off-screen visit cancels the stop; a longer one stops and then resumes',()=>{
 let callback,queued,stops=0,resumes=0;
 const c={window:{IntersectionObserver:true},IntersectionObserver:class{constructor(cb){callback=cb;}observe(){}disconnect(){}},_stripObserver:null,_stripLeaveTimer:null,_stripInView:true,HUB_OFFSCREEN_GRACE_MS:2000,document:{hidden:false},setTimeout:(cb,ms)=>{assert.equal(ms,2000);queued=cb;return 1;},clearTimeout:()=>{queued=null;},_hubStopAllLive:()=>stops++,_hubDecide:()=>resumes++};
 vm.createContext(c);vm.runInContext(fn(hub,'_hubObserve'),c);c._hubObserve({querySelectorAll:()=>[]});
 callback([{isIntersecting:false}]);assert.equal(stops,0);callback([{isIntersecting:true}]);assert.equal(queued,null);
 callback([{isIntersecting:false}]);queued();assert.equal(stops,1);assert.equal(c._stripInView,false);
 callback([{isIntersecting:true}]);assert.equal(resumes,1);assert.equal(c._stripInView,true);
});
checkFn('Fullscreen fallback works without the native API and restores focus on close',()=>{
 const button={textContent:'',setAttribute(){},focus(){}};let restored=0;
 const wrap={classList:classes(),querySelector:()=>button};
 const c={camState:{a:{frameEl:{closest:()=>wrap}}},expandedCamera:null,fullscreenReturnFocus:null,document:{activeElement:{focus:()=>restored++},body:{classList:classes()},fullscreenElement:null,querySelectorAll:()=>[button]}};
 vm.createContext(c);vm.runInContext(fn(camera,'closeCameraFullscreen')+'\n'+fn(camera,'openCameraFullscreen'),c);
 c.openCameraFullscreen('a');assert(wrap.classList.contains('camera-expanded'));assert.equal(button.textContent,'×');
 c.closeCameraFullscreen();assert(!wrap.classList.contains('camera-expanded'));assert.equal(restored,1);
});
for(const source of [camera,hub]) for(const script of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
done();
