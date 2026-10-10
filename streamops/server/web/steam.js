/* Ticket #86: Steam and Game Manager are WS-only. No HTTP/REST polling. */
(() => {
  const $=s=>document.querySelector(s), format=window.StreamOpsUI;
  const log=format.createActivityLog("#activity-log"), ws=window.StreamOpsSteam;
  const games=window.StreamOpsGames, components=window.StreamOpsGamesComponents, control=window.StreamOpsGameControl;
  let current=null, connected=false, busy=false, previous="", lastGames="";
  function setError(message) {$("#error-message").textContent=message||"";$("#error-message").hidden=!message;}
  function render() {
    const fresh=connected && current && current.stale!==true;
    const state=fresh?(current.running===true?"Running":current.running===false?"Stopped":"UNKNOWN"):"UNKNOWN";
    $("#steam-state").textContent=busy?"Restarting":state;
    $("#steam-status-dot").className="status-dot "+(state==="Running"?"online":state==="Stopped"?"warning":"offline");
    $("#steam-pid").textContent=fresh?current.pid??"--":"--";
    $("#steam-started").textContent=fresh?format.formatDateTime(current.started_at):"--";
    $("#steam-uptime").textContent=fresh?format.formatDuration(current.uptime_seconds):"--";
    $("#steam-session").textContent=fresh?current.session_id??"--":"--";
    $("#steam-interactive").textContent=fresh && current.interactive!=null?(current.interactive?"Yes":"No"):"--";
    $("#steam-installation").textContent=fresh && current.installation_detected!=null?(current.installation_detected?"Detected":"Not detected"):"Unknown";
    $("#restart-button").disabled=busy||!fresh||current.installation_detected!==true||current.interactive!==true;
    $("#restart-button").textContent=busy?"Restarting…":"Restart in Big Picture";
    $("#steam-status-panel").setAttribute("aria-busy",String(busy));
    $("#status-text").textContent=connected?"Steam WS connected":"Steam WS offline";
    $("#status-dot").className="status-dot "+(connected?"online":"offline");
    if (fresh) {
      const signature=current.state+":"+current.pid+":"+current.interactive;
      if (signature!==previous) {previous=signature;log("Steam state: "+state);}
    }
  }
  ws.onState(({state})=>{
    connected=state==="connected";
    if (!connected) current=null;
    render();
    if (connected) ws.request("steam.status").then(s=>{current=s;render();}).catch(e=>setError(e.message));
  },{replay:true});
  ws.on("steam.snapshot",data=>{current=data;render();});
  games.store.on(store=>{
    const summary=store.summary();
    components.renderSummary($("#steam-games-summary"),store);
    $("#games-connection").textContent=store.stale?"UNKNOWN":"LIVE";
    const visible=store.stale?[]:store.items().filter(g=>g.observation?.process?.state==="RUNNING" && !g.observation?.process?.stale);
    components.renderRows($("#steam-running-games"),visible,null,()=>location.assign("/games"),store.stale?"Game status unavailable":"No running games");
    const sig=store.epoch+":"+store.revision+":"+store.stale;
    if(sig!==lastGames && !store.loading && !store.stale){lastGames=sig; log("Games: "+(summary.running??"Unknown")+" running");}
  });
  $("#steam-apply-token").addEventListener("click",()=>{
    control.setCredential($("#steam-control-token").value);
    $("#steam-control-token").value="";
    $("#steam-token-status").textContent=control.hasCredential()?"Credential ready":"Invalid token (min 24 characters)";
  });
  $("#restart-button").addEventListener("click",async()=>{
    if(busy || !connected || !current?.installation_detected || !current?.interactive) return;
    if(!window.confirm("Restart Steam in Big Picture Mode? Active games or downloads may be interrupted.")) {log("Restart cancelled");return;}
    busy=true;render();setError("");log("Steam restart requested");
    try {
      const value=await control.command("/api/v1/steam/ws","steam.lifecycle.restart",{});
      log("Steam restart completed (PID "+(value?.pid??"Unknown")+")","success");
      current=await ws.request("steam.status");render();
    }catch(e){setError(e.message);log("Steam restart failed: "+e.message,"error");}
    finally {busy=false;render();}
  });
  log("Steam Manager opened");
})();