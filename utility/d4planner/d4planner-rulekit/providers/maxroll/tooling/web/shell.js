/* Parent-side visibility diagnostics still work when the child fails to execute. */
(() => {
  'use strict';
  const frame = document.querySelector('iframe');
  let imported=null,downloadUrl=null;
  const transfer=document.getElementById('transfer-status');
  const post=async(path,body)=>{
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Snapshot':LOCAL_SNAPSHOT_HASH},body:JSON.stringify(body)});
    if(!response.ok){const result=await response.json();throw Object.assign(Error(result.error||'Invalid native build or snapshot mismatch'),{status:response.status});}
    return response;
  };
  window.localNativeImport=()=>imported;
  window.localNativeExport=async payload=>{
    try{
      const response=await post('/__local/export',payload);
      const blob=await response.blob();
      if(downloadUrl)URL.revokeObjectURL(downloadUrl);
      downloadUrl=URL.createObjectURL(blob);
      const link=document.createElement('a');link.href=downloadUrl;link.download='maxroll-native-build.json';
      link.textContent='Download Native JSON';transfer.replaceChildren(link);
      link.click(); // Parent is not sandboxed. Child download permissions remain unchanged.
      transfer.append(' · Native only; canonical conversion unsupported. Not saved to cloud.');
    }catch(error){transfer.textContent='Export failed: '+error.message;throw error;}
  };
  document.getElementById('export-build').addEventListener('click',()=>{
    const button=[...frame.contentDocument.querySelectorAll('button')].find(b=>b.textContent.trim()==='My Profiles');
    if(!button){transfer.textContent='Wait for Planner to load.';return;}
    if(!frame.contentDocument.querySelector('input.d4t-save-name'))button.click();transfer.textContent='In My Profiles, enter a name and press Save to download Native JSON. Cloud save is disabled.';
  });
  document.getElementById('import-build').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;
    try{
      if(file.size>8*1024*1024)throw Error('File too large');
      const response=await post('/__local/import',JSON.parse(await file.text()));
      imported=await response.json();
      transfer.textContent='Importing native file…';
      await new Promise(resolve=>{frame.addEventListener('load',resolve,{once:true});frame.src=frame.getAttribute('src');});
      transfer.textContent='Native file loaded into this tab. Export again to retain edits; reload/closing the page discards tab state.';
    }catch(error){transfer.textContent=error.status===409?'Import rejected: '+error.message:'Import rejected: invalid native file, integrity or snapshot mismatch.';}
    event.target.value='';
  });
  window.addEventListener('pagehide',()=>{if(downloadUrl)URL.revokeObjectURL(downloadUrl);});
  let last = '', ticks = 0;
  const inspect = () => {
    const box = frame.getBoundingClientRect();
    let detail = { width: Math.round(box.width), height: Math.round(box.height),
      viewportWidth: innerWidth, viewportHeight: innerHeight, userAgent: navigator.userAgent.slice(0, 250) };
    try {
      const doc = frame.contentDocument;
      const button = doc && [...doc.querySelectorAll('button')].find(e => e.textContent.trim() === 'New Profile');
      detail = { ...detail, readyState: doc?.readyState || 'no-document',
        newProfile: !!button, buttonBox: button?.getBoundingClientRect().toJSON(),
        bodyChildren: doc?.body?.children.length || 0 };
    } catch { detail.frameAccess = 'denied'; }
    const state = JSON.stringify(detail);
    if (state !== last) {
      last = state;
      fetch('/__local/report', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({kind:'FRAME_STATE', session:frame.name, url:location.href, detail}) }).catch(() => {});
    }
  };
  frame.addEventListener('load', inspect);
  window.addEventListener('resize', inspect);
  const timer = setInterval(() => { inspect(); if (++ticks >= 30) clearInterval(timer); }, 1000);
  const update = () => fetch('/__local/diagnostics').then(r => r.json()).then(d => {
    document.getElementById('status').textContent = d.missing + ' missing / ' + d.blocked + ' blocked (server totals)';
  }).catch(() => {});
  update(); setInterval(update, 3000);
})();
