/* Ticket #86: Steam and Game Manager are WS-only. No HTTP/REST polling. */
(() => {
  const $=s=>document.querySelector(s), format=window.StreamOpsUI;
  const log=format.createActivityLog("#activity-log"), ws=window.StreamOpsSteam;
  const games=window.StreamOpsGames, components=window.StreamOpsGamesComponents, control=window.StreamOpsGameControl;
  let current=null, connected=false, busy=false, previous="", lastGames="", showAll=false;
  function setError(message) {$("#error-message").textContent=message||"";$("#error-message").hidden=!message;}
  function render() {
    const fresh=connected && current && current.stale!==true;
    const state=fresh?(current.running===true?"Running":current.running===false?"Stopped":"UNKNOWN"):"UNKNOWN";
    $("#steam-notice").hidden = state !== "UNKNOWN";
    $("#steam-state").textContent=busy?"Restarting":state;
    $("#steam-state-badge").dataset.tone=state==="Running"?"ok":state==="Stopped"?"warn":"bad";
    $("#steam-heading-status").textContent=state==="Running"?"Steam running":state==="Stopped"?"Steam stopped":"Steam unavailable";
    $("#steam-heading-status").dataset.tone=state==="Running"?"ok":state==="Stopped"?"warn":"bad";
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
    const stats=$("#steam-games-summary");stats.replaceChildren();
    for (const [label,key] of [["Running","running"],["Registered","registered"]]) {
      const cell=components.element("span","gm-steam-stat");
      cell.append(components.element("small","",label),
        components.element("strong","",summary[key]===null?"—":summary[key]));
      stats.append(cell);
    }
    $("#games-connection").textContent=store.stale?"UNKNOWN":summary.running==null?"UNKNOWN":summary.running+" running";
    $("#games-connection").dataset.tone=store.stale?"bad":summary.running?"ok":"neutral";
    const visible=store.stale?[]:store.items().filter(g=>g.observation?.process?.state==="RUNNING" && !g.observation?.process?.stale);
    const list=$("#steam-running-games");
    if (visible.length) {
      components.renderRows(list,showAll?visible:visible.slice(0,3),null,()=>location.assign("/games"));
      if(visible.length>3) {
        const more=components.element("button","gm-show-more",
          showAll?"Show fewer games":"+"+(visible.length-3)+" more games");
        more.type="button";
        more.setAttribute("aria-expanded",String(showAll));
        more.addEventListener("click",()=>{showAll=!showAll;games.store.emit();});
        list.append(more);
      }
    } else {
      list.replaceChildren();
      const empty=components.element("div","gm-steam-empty");
      const ico=components.element("span","gm-steam-empty-icon",store.stale?"!":"♧");
      ico.setAttribute("aria-hidden","true");
      const heading=components.element("strong","",store.stale?"Status unavailable":"No games running");
      const explanation=components.element("p","",store.stale?
        "Cannot confirm running sessions.":"Manage registered games in your library.");
      empty.append(ico,heading,explanation);
      list.append(empty);
    }
    const sig=store.epoch+":"+store.revision+":"+store.stale;
    if(sig!==lastGames && !store.loading && !store.stale){lastGames=sig; log("Games: "+(summary.running??"Unknown")+" running");}
  });
  const gameToggle=$("#steam-games-toggle"),gameBody=$("#steam-games-body");
  gameToggle.addEventListener("click",()=>{
    const expanded=gameToggle.getAttribute("aria-expanded")==="true";
    gameToggle.setAttribute("aria-expanded",String(!expanded));
    gameBody.hidden=expanded;
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
  // Report only real session events; no fabricated timestamps or counts.
  const activityList=$("#activity-log");
  function updateActivitySummary() {
    const count=activityList.children.length;
    const latest=activityList.lastElementChild?.querySelector("time")?.textContent?.slice(0,5)||"—";
    const summary=$("#steam-activity-details .gm-activity-summary");
    summary.textContent=count+" session event"+(count===1?"":"s")+" · latest "+latest;
  }
  new MutationObserver(updateActivitySummary).observe(activityList,{childList:true});
  log("Steam Manager opened");
  updateActivitySummary();
})();