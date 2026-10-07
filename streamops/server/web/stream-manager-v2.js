(() => {
  const ui = window.StreamOpsUI;
  const $ = (s) => document.querySelector(s);
  const STATES = new Set(['IDLE','STARTING','LIVE','RECONNECTING','STOPPING','FAILED']);
  let destinations = [], obs = null, profiles = [], preflight = null, ws = null, reconnectTimer = null, expanded = null;
  const activity = [];

  const escapeHtml = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const publicError = e => e?.code ? `${e.code}: ${e.message}` : (e?.message || 'Operation failed.');
  const api = (path, options={}) => ui.fetchJson('/api/v1/multistream'+path, options);
  const state = d => STATES.has(d?.state) ? d.state : 'FAILED';
  const tone = s => s==='LIVE'?'ok':(['STARTING','STOPPING'].includes(s)?'blue':(s==='FAILED'?'bad':(s==='RECONNECTING'?'warn':'neutral')));
  const addActivity = (event, destination='', level='neutral') => {
    activity.unshift({time:new Date().toLocaleTimeString(),event,destination,level});
    activity.splice(30); renderActivity();
  };

  function sharedChecks() {
    return (preflight?.checks || []).map(item => [
      item.id,
      item.status === 'PASS',
      item.message || item.status,
    ]);
  }
  function sharedReady(){ return preflight?.status === 'PASS' && preflight?.profile_id === $('#preflight-profile').value; }
  function destinationReady(d){ return d.enabled !== false && !!d.server_url && ['IDLE','FAILED'].includes(state(d)); }

  function renderSession(){
    const live=destinations.filter(d=>state(d)==='LIVE').length;
    $('#obs-state').textContent=obs?.state || 'UNKNOWN';
    $('#obs-state').dataset.tone=obs?.state==='READY'?'ok':'bad';
    $('#obs-scene').textContent=obs?.scene?.name || obs?.active_scene || '--';
    $('#obs-profile').textContent=profiles.find(p=>p.id===$('#preflight-profile').value)?.name || '--';
    $('#obs-canvas').textContent=obs?.canvas ? `${obs.canvas.width}×${obs.canvas.height}` : '--';
    $('#obs-destinations').textContent=`${destinations.length} destinations · ${live} live`;
  }
  function renderPreflight(){
    const checks=sharedChecks(), passed=sharedReady(), ran=!!preflight;
    $('#preflight-pill').textContent=!ran ? 'NOT RUN' : (passed ? `${checks.length}/${checks.length} PASSED` : `${checks.filter(x=>x[1]).length}/${checks.length} FAILED`);
    $('#preflight-pill').dataset.tone=!ran?'neutral':(passed?'ok':'bad');
    $('#preflight-checks').innerHTML=checks.map(([name,ok,value])=>`<div class="v2-check"><span>${escapeHtml(name)}</span><strong data-tone="${ok?'ok':'bad'}">${escapeHtml(value)}</strong></div>`).join('');
    $('#preflight-error').hidden=!ran || passed;
  }
  function renderDestinations(){
    const root=$('#destination-list-v2');
    $('#destination-empty').hidden=destinations.length>0;
    root.innerHTML=destinations.map(d=>{
      const s=state(d), open=expanded===d.destination_id, ready=destinationReady(d), canStart=sharedReady()&&ready;
      const sub=s==='LIVE'?'Backend confirmed live':s==='RECONNECTING'?'Connection interrupted · recovering':s==='FAILED'?'Destination runtime failed':canStart?'Ready to stream':(!sharedReady()?'Blocked by shared preflight':'Destination configuration incomplete');
      return `<section class="v2-destination" data-id="${escapeHtml(d.destination_id)}">
        <button class="v2-destination-head" data-action="expand">
          <div><div class="v2-title-row"><h3>${escapeHtml(d.name)}</h3><span class="state-pill" data-tone="${tone(s)}">${s}</span>${['IDLE','FAILED'].includes(s)?`<span class="state-pill" data-tone="${canStart?'ok':'warn'}">${canStart?'READY':'BLOCKED'}</span>`:''}</div><p>${escapeHtml(sub)}</p></div><span>${open?'⌃':'⌄'}</span>
        </button>
        <div class="v2-destination-body" ${open?'':'hidden'}>
          <div class="v2-info-grid"><div><span>Endpoint</span><strong>${escapeHtml(d.server_url||'Missing')}</strong></div><div><span>Stream key</span><strong>Configured</strong></div><div><span>Readiness</span><strong>${canStart?'Ready':'Blocked'}</strong></div></div>
          <div class="action-row">
            ${['IDLE','FAILED'].includes(s)?`<button class="primary-button" data-action="start" ${canStart?'':'disabled'}>${s==='FAILED'?'Start again':'Start'}</button>`:`<button class="danger-button" data-action="stop" ${s==='STOPPING'?'disabled':''}>Stop</button>`}
            <button class="secondary-button" data-action="edit" ${['STARTING','LIVE','RECONNECTING','STOPPING'].includes(s)?'disabled':''}>Edit</button>
            <button class="secondary-button" data-action="stats" ${s==='LIVE'?'':'disabled'}>Refresh stats</button>
          </div><div class="v2-stats" data-role="stats"></div>
        </div>
      </section>`;
    }).join('');
  }
  function renderActivity(){
    $('#activity-count').textContent=`${activity.filter(x=>x.level==='bad').length} errors`;
    $('#activity-last').textContent=activity[0]?.event || 'No events';
    $('#activity-log-v2').innerHTML=activity.map(x=>`<li><time>${escapeHtml(x.time)}</time><span data-tone="${x.level}">${escapeHtml(x.destination?x.destination+' · '+x.event:x.event)}</span></li>`).join('');
  }
  function render(){ renderSession(); renderPreflight(); renderDestinations(); renderActivity(); }

  async function loadObs(){
    try { obs=await ui.fetchJson('/api/v1/obs/process/status'); }
    catch(e){ obs={state:'UNAVAILABLE'}; addActivity('OBS status unavailable','', 'bad'); }
  }
  async function loadProfiles(){
    const result=await ui.fetchJson('/api/v1/scene-profiles');
    profiles=result.profiles||[];
    const select=$('#preflight-profile');
    select.replaceChildren(...profiles.map(p=>new Option(p.name,p.id)));
    if(!profiles.length) select.add(new Option('No saved profiles',''));
  }
  async function runPreflight(){
    const profileId=$('#preflight-profile').value;
    if(!profileId){ preflight=null; render(); addActivity('Preflight blocked: no scene profile','', 'bad'); return; }
    try{
      preflight=await ui.fetchJson('/api/v1/live/preflight/shared',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:profileId})});
      render();
      addActivity(preflight.status==='PASS'?'Preflight passed':'Preflight failed','',preflight.status==='PASS'?'ok':'bad');
    }catch(e){ preflight=null; render(); addActivity(publicError(e),'Preflight','bad'); }
  }
  async function reconcile(){
    try {
      const result=await api('/destinations'); destinations=result.destinations||[];
      $('#page-error').hidden=true; render();
    } catch(e){ $('#page-error').textContent=publicError(e); $('#page-error').hidden=false; render(); }
  }
  async function command(id, action){
    const d=destinations.find(x=>x.destination_id===id); if(!d)return;
    try{
      const result=await api(`/destinations/${encodeURIComponent(id)}/${action}`,{method:'POST'});
      const i=destinations.findIndex(x=>x.destination_id===id); destinations[i]=result;
      addActivity(`${action} accepted → ${state(result)}`,d.name);
      render();
    }catch(e){ addActivity(publicError(e),d.name,'bad'); render(); }
  }
  async function stats(id, card){
    try{ const r=await api(`/destinations/${encodeURIComponent(id)}/stats`); const s=r.stats||{}; card.querySelector('[data-role=stats]').textContent=`Bitrate ${s.bitrate_bps||0} bps · FPS ${s.fps||0} · Bytes ${s.total_bytes||0} · Frames ${s.total_frames||0}`; }
    catch(e){ addActivity(publicError(e),'Stats','bad'); }
  }
  function openEditor(d=null){
    $('#editor-title').textContent=d?'Edit destination':'Add destination';
    $('#destination-id').value=d?.destination_id||'';
    $('#destination-name').value=d?.name||'';
    $('#destination-url').value=d?.server_url||'';
    $('#destination-enabled').checked=d?.enabled!==false;
    $('#destination-credential').value='';
    $('#credential-help').textContent=d?'Stored credential is never displayed. Enter a value only to replace it.':'Stream key is required for a new destination.';
    $('#destination-editor').hidden=false;
  }
  async function saveEditor(){
    const id=$('#destination-id').value.trim(), credential=$('#destination-credential').value;
    const body={name:$('#destination-name').value.trim(),server_url:$('#destination-url').value.trim(),enabled:$('#destination-enabled').checked};
    if(!id){ body.destination_id=body.name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''); body.credential=credential; }
    else if(credential) body.credential=credential;
    try{
      const result=await api(id?`/destinations/${encodeURIComponent(id)}`:'/destinations',{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      $('#destination-credential').value=''; $('#destination-editor').hidden=true; addActivity(id?'Destination updated':'Destination created',result.name,'ok'); await reconcile();
    }catch(e){ $('#editor-error').textContent=publicError(e); $('#editor-error').hidden=false; }
  }
  async function removeEditor(){
    const id=$('#destination-id').value; if(!id||!confirm('Delete this destination?'))return;
    try{ await api(`/destinations/${encodeURIComponent(id)}`,{method:'DELETE'}); $('#destination-editor').hidden=true; addActivity('Destination deleted',id); await reconcile(); }
    catch(e){ $('#editor-error').textContent=publicError(e); $('#editor-error').hidden=false; }
  }
  function connect(){
    if(ws) try{ws.close();}catch(_){}
    const scheme=location.protocol==='https:'?'wss':'ws'; ws=new WebSocket(`${scheme}://${location.host}/api/v1/multistream/ws`);
    ws.addEventListener('message',e=>{ try{const m=JSON.parse(e.data); if(m.type==='multistream.snapshot'){destinations=m.data?.destinations||[];render();return;} if(m.type?.startsWith('multistream.')||m.event){addActivity(m.event||m.type,m.destination_id||''); reconcile();}}catch(_){} });
    ws.addEventListener('close',()=>{ addActivity('Realtime disconnected; reconciling','', 'warn'); clearTimeout(reconnectTimer); reconnectTimer=setTimeout(()=>{reconcile();connect();},1000); });
  }

  $('#add-destination').addEventListener('click',()=>openEditor());
  $('#editor-cancel').addEventListener('click',()=>{$('#destination-editor').hidden=true;$('#destination-credential').value='';});
  $('#editor-save').addEventListener('click',saveEditor);
  $('#editor-delete').addEventListener('click',removeEditor);
  $('#run-preflight').addEventListener('click',runPreflight);
  $('#preflight-profile').addEventListener('change',()=>{preflight=null;render();});
  $('#destination-list-v2').addEventListener('click',e=>{const button=e.target.closest('button[data-action]');if(!button)return;const card=button.closest('.v2-destination'),id=card?.dataset.id,d=destinations.find(x=>x.destination_id===id);if(button.dataset.action==='expand'){expanded=expanded===id?null:id;renderDestinations();}else if(button.dataset.action==='start'||button.dataset.action==='stop')command(id,button.dataset.action);else if(button.dataset.action==='edit')openEditor(d);else if(button.dataset.action==='stats')stats(id,card);});
  Promise.all([loadObs(),loadProfiles(),reconcile()]).then(()=>{render();connect();}).catch(e=>{ $('#page-error').textContent=publicError(e); $('#page-error').hidden=false; });
})();