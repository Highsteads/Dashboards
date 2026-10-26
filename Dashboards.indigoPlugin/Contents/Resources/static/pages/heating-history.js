/* Filename: heating-history.js
 * Description: Read-only room heating detail, sparse history and recorded decisions.
 * Author: CliveS & Codex GPT-6
 * Date: 26-10-2026
 * Version: 1.0
 */
(function (root) {
  'use strict';
  const number = v => v == null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v);
  const clock = t => new Date(t * 1000).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
  const stamp = t => new Date(t * 1000).toLocaleString('en-GB', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit', timeZoneName:'short'});

  function plot(data) {
    const series = data.series || {}, start = data.start, end = data.end, gap = data.gapSeconds || 10800;
    const keys = Object.keys(series), cursors = {}, current = {};
    const moments = new Set([start, end]);
    keys.forEach(k => {
      cursors[k] = 0;
      (series[k] || []).forEach(p => {
        if (p.t >= start && p.t <= end) moments.add(p.t);
        if (k === 'temperatureseenepoch' || k === 'temperatureinput1' || k === 'temperature') {
          const expiry = (k === 'temperatureseenepoch' ? number(p.v) : p.t) + gap;
          if (expiry > start && expiry < end) moments.add(expiry);
        }
      });
    });
    const temperature = [], target = [], call = [], events = [];
    let lastTarget = null;
    Array.from(moments).sort((a,b) => a-b).forEach(t => {
      keys.forEach(k => {
        const points = series[k] || [];
        while (cursors[k] < points.length && points[cursors[k]].t <= t) current[k] = points[cursors[k]++];
      });
      const tp = current.temperatureinput1 || current.temperature;
      const heartbeat = current.temperatureseenepoch;
      const seen = heartbeat ? number(heartbeat.v) : tp ? tp.t : null;
      const gateway = current.gatewaystatus ? String(current.gatewaystatus.v).toLowerCase() : '';
      const fresh = seen != null && seen <= t + 60 && t - seen < gap && (!gateway || gateway === 'online');
      const temp = fresh && tp ? number(tp.v) : null;
      const sp = current.setpointheat ? number(current.setpointheat.v) : null;
      const hv = fresh && current.hvacheaterison ? number(current.hvacheaterison.v) : null;
      temperature.push({x:t, y:temp});
      target.push({x:t, y:fresh ? sp : null});
      call.push({x:t, y:hv === 0 || hv === 1 ? hv : null});
      if (sp != null && lastTarget != null && sp !== lastTarget && current.setpointheat.t === t) {
        const source = current.setpointsource;
        const why = source && source.t === t ? ({manual:'Changed by hand', indigo:'Changed through Indigo', timetable:'Evohome timetable'})[source.v] : '';
        events.push({t, target:sp, reason:why || 'Target reported by the thermostat', reported:true});
      }
      if (sp != null) lastTarget = sp;
    });
    function compact(points) {
      return points.filter((p,i) => i === 0 || i === points.length-1 || p.y !== points[i-1].y || p.y !== points[i+1].y);
    }
    let calling = 0, known = 0;
    for (let i=0;i<call.length-1;i++) {
      const seconds = call[i+1].x-call[i].x;
      if (call[i].y != null) known += seconds;
      if (call[i].y === 1) calling += seconds;
    }
    return {temperature:compact(temperature), target:compact(target), call:compact(call), events, calling, known};
  }

  let api, deviceId, chart, deviceList = [], hours = 24, busy = false, generation = 0, mounted = false, outsideId = null;
  let data = null, outside = null;
  const el = id => root.document.getElementById(id);
  const esc = text => root.DashUI.esc(text);
  function selectedZone() { return deviceList.find(d => Number(d.id) === deviceId); }
  function summary(d) {
    const temp = root.DashTile.zone.currentTemp(d), sp = root.DashTile.zone.setpoint(d);
    const bad = root.DashTile.unknownReason(d);
    const seen = root.DashTile.zone.lastSeen(d);
    const stale = seen != null && Date.now() - seen > root.DashTile.zone.TRV_STALE_MS;
    return bad || stale ? 'Current readings are unavailable or stale.' :
      (temp == null ? 'Temperature unavailable' : temp.toFixed(1) + '°C now') +
      (sp == null ? '' : ' · target ' + sp.toFixed(1) + '°C');
  }
  function mount(instance, id, devices) {
    api = instance; deviceId = Number(id); deviceList = devices;
    const d = selectedZone();
    if (!d) { el('content').innerHTML = '<p class="loading">This heating zone is unavailable. <a href="heating.html">Back to Heating</a></p>'; return; }
    if (mounted) { el('heat-now').textContent = summary(d); return; }
    mounted = true;
    root.document.querySelector('h1').textContent = d.name.replace(/\s+(Radiator|Thermostat)$/i, '');
    const back = root.document.querySelector('.hdr-left a'); back.href = 'heating.html'; back.textContent = '← Heating';
    el('evo-panel').hidden = true;
    el('content').innerHTML = '<section class="heat-detail"><h2>'+esc(d.name)+'</h2><p id="heat-now"></p>' +
      '<div class="heat-toolbar heat-nav"><button id="heat-prev" class="ctrl-btn" aria-label="Previous room">←</button>' +
      '<label>Room <select id="heat-room"></select></label><button id="heat-next" class="ctrl-btn" aria-label="Next room">→</button></div>' +
      '<div class="heat-toolbar" role="group" aria-label="History period">' +
      [6,24,168].map(h => '<button class="ctrl-btn heat-range" data-hours="'+h+'" aria-pressed="'+(h===24)+'">'+(h===168?'7 days':h+' hours')+'</button>').join('') +
      '<label><input type="checkbox" id="heat-outside"> Outside temperature</label></div>' +
      '<p id="heat-status" role="status">Loading recorded temperatures...</p>' +
      '<div class="heat-chart"><canvas id="heat-chart" role="img" aria-label="Room temperature, target and recorded heating changes"></canvas></div>' +
      '<p class="heat-strip-label">Calling for heat <span>(orange = calling, grey = not calling, stripes = unknown)</span></p>' +
      '<div id="heat-call" class="heat-call" role="img" aria-label="Recorded heat demand"></div>' +
      '<p id="heat-summary"></p><p class="heat-help">Calling for heat is the thermostat’s reported demand, not a measurement of heat from the radiator. Gaps mean readings were unavailable or over three hours old.</p>' +
      '<details open><summary>What changed</summary><p class="heat-help">Dots mark recorded controller requests. A request is not proof the thermostat received it. Reported target changes are listed separately.</p><p id="heat-reason-status"></p><ol id="heat-events"></ol></details></section>';
    el('heat-now').textContent = summary(d);
    el('heat-room').innerHTML = devices.map(x => '<option value="'+Number(x.id)+'"'+(Number(x.id)===deviceId?' selected':'')+'>'+esc(x.name)+'</option>').join('');
    el('heat-room').onchange = event => { root.location.href = 'heating.html?zone='+Number(event.target.value); };
    function move(step) {
      const i = devices.findIndex(x => Number(x.id)===deviceId);
      root.location.href = 'heating.html?zone='+Number(devices[(i+step+devices.length)%devices.length].id);
    }
    el('heat-prev').onclick = () => move(-1); el('heat-next').onclick = () => move(1);
    root.document.querySelectorAll('.heat-range').forEach(button => { button.onclick = () => {
      hours = Number(button.dataset.hours); generation++; busy = false;
      root.document.querySelectorAll('.heat-range').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.hours)===hours)));
      refresh();
    }; });
    el('heat-outside').onchange = () => refresh();
    root.DashUI.poll(refresh, 60000);
  }
  async function request(id, range) {
    if (api._guest) return api._guestFetch('/guest/history?action=heating&deviceId='+id+'&hours='+range);
    return root.DashUI.message('historyQuery', {action:'heating',deviceId:id,hours:range});
  }
  async function refresh() {
    if (busy || !mounted) return;
    busy = true; const mine = ++generation, range = hours;
    el('heat-status').textContent = 'Loading recorded temperatures...';
    try {
      const result = await request(deviceId, range);
      if (mine !== generation) return;
      data = result; outside = null;
      if (el('heat-outside').checked && outsideId) {
        try { outside = await request(outsideId, range); }
        catch (_) { outside = null; }
      }
      if (mine !== generation) return;
      draw();
    } catch (_) {
      if (mine === generation) el('heat-status').textContent = 'History is unavailable. Any graph below is the last successful view. Try again shortly.';
    } finally { if (mine === generation) busy = false; }
  }
  function draw() {
    const view = plot(data), wantsOutside = el('heat-outside').checked;
    const points = view.temperature.filter(p => p.y != null);
    const decisions = data.decisions || {items:[],available:false};
    const markers = (decisions.items || []).map(e => ({x:e.t,y:e.target,reason:e.reason}));
    const datasets = [
      {label:'Room temperature',data:view.temperature,borderColor:'#27a9ff',backgroundColor:'#27a9ff',borderWidth:3,pointRadius:0,spanGaps:false,tension:0},
      {label:'Target temperature',data:view.target,borderColor:'#e7a03b',borderWidth:2,borderDash:[6,4],pointRadius:0,stepped:'after',spanGaps:false},
      {label:'Controller request',data:markers,borderColor:'#bb80ed',backgroundColor:'#bb80ed',pointRadius:4,pointHoverRadius:7,showLine:false}
    ];
    if (wantsOutside && outside) datasets.push({label:'Outside',data:plot(outside).temperature,borderColor:'#81a492',borderWidth:2,pointRadius:0,spanGaps:false});
    if (chart) chart.destroy();
    const colour = root.getComputedStyle(root.document.body).getPropertyValue('--text-secondary').trim() || '#888';
    chart = new root.Chart(el('heat-chart'), {type:'line',data:{datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,parsing:false,onResize:() => { root.setTimeout(() => { if(chart && chart.chartArea && el('heat-call')) { el('heat-call').style.marginLeft=chart.chartArea.left+'px'; el('heat-call').style.marginRight=(chart.width-chart.chartArea.right)+'px'; } }, 100); },
      interaction:{mode:'nearest',intersect:false},plugins:{legend:{labels:{color:colour}},tooltip:{callbacks:{title:items => items.length?stamp(items[0].parsed.x):'',
        label:item => item.raw.reason ? 'Requested '+item.parsed.y+'°C: '+item.raw.reason : item.dataset.label+': '+item.parsed.y.toFixed(1)+'°C'}}},
      scales:{x:{type:'linear',min:data.start,max:data.end,ticks:{color:colour,maxTicksLimit:rangeTicks(),callback:t => hours>24?new Date(t*1000).toLocaleDateString('en-GB',{weekday:'short',hour:'2-digit'}):clock(t)}},
        y:{title:{display:true,text:'Temperature °C',color:colour},ticks:{color:colour}}}}});
    const span = data.end-data.start;
    el('heat-call').style.marginLeft = chart.chartArea.left + 'px';
    el('heat-call').style.marginRight = (chart.width - chart.chartArea.right) + 'px';
    el('heat-call').innerHTML = view.call.slice(0,-1).map((p,i) => '<span class="'+(p.y==null?'unknown':p.y===1?'calling':'resting')+'" style="left:'+((p.x-data.start)/span*100)+'%;width:'+((view.call[i+1].x-p.x)/span*100)+'%" title="'+esc(stamp(p.x)+' to '+stamp(view.call[i+1].x)+': '+(p.y==null?'Unknown':p.y===1?'Calling for heat':'Not calling for heat'))+'"></span>').join('');
    const minutes = Math.round(view.calling/60), knownHours = (view.known/3600).toFixed(1);
    el('heat-summary').textContent = (points.length ? 'Recorded temperature: '+Math.min(...points.map(p=>p.y)).toFixed(1)+' to '+Math.max(...points.map(p=>p.y)).toFixed(1)+'°C. ' : 'No usable temperature readings in this period. ') +
      'Calling for heat for '+Math.floor(minutes/60)+'h '+(minutes%60)+'m, from '+knownHours+' hours of known demand.';
    el('heat-status').textContent = stamp(data.start)+' to '+stamp(data.end) + (data.truncated?' · History limit reached; part of this period is missing.':'') +
      (wantsOutside && !outside?' · Outside history is unavailable.':'');
    el('heat-reason-status').textContent = !decisions.available ? 'Detailed reasons are not recorded here. Thermostat target changes are shown when available.' :
      (decisions.ambiguous?'Some reasons have ambiguous clock-change times and cannot be placed on the graph. ': '') +
      (decisions.truncated?'The decision log is incomplete.':'');
    const events = [...(decisions.items || []),...view.events].sort((a,b)=>b.t-a.t);
    el('heat-events').innerHTML = events.length ? events.map(e=>'<li><time>'+esc(stamp(e.t))+'</time> '+esc((e.reported?'Reported ':'Requested ')+e.target.toFixed(1)+'°C — '+e.reason)+'</li>').join('') : '<li>No target changes recorded in this period.</li>';
  }
  function rangeTicks() { return root.innerWidth < 500 ? 4 : 8; }
  root.HeatingHistory = {plot,mount,setOutside:id=>{outsideId=id;}};
})(typeof window !== 'undefined' ? window : globalThis);
