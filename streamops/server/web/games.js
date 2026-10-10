(() => {
  const service=window.StreamOpsGames, store=service.store, ui=window.StreamOpsGamesComponents;
  const control=window.StreamOpsGameControl, log=window.StreamOpsUI.createActivityLog("#activity-log");
  const $=s=>document.querySelector(s);
  let selected=null, activeOperation=null, lastSignature="";
  function error(message) { const e=$("#games-error");e.textContent=message||"";e.hidden=!message; }
  function render() {
    const games=store.items(), summary=store.summary();
    $("#status-text").textContent=store.stale ? "Game WS: offline / stale" : "Game WS: connected";
    ui.renderSummary($("#game-summary"),store);
    $("#running-caption").textContent=summary.running==null?"Unverified":summary.running+" running";
    const running=store.stale?[]:games.filter(g=>g.observation?.process?.state==="RUNNING" && g.observation?.process?.stale===false);
    ui.renderRows($("#running-games"),running,selected,select,store.loading?"Loading…":store.stale?"Status unavailable":"No running games");
    const search=$("#game-search").value.trim().toLocaleLowerCase(), filter=$("#game-filter").value;
    const library=games.filter(g=>(g.name+" "+g.provider).toLocaleLowerCase().includes(search)).filter(g=>filter==="all"||
      (filter==="running" && g.observation?.process?.state==="RUNNING" && !g.observation?.process?.stale && !store.stale)||
      (filter==="stopped" && g.observation?.process?.state==="STOPPED" && !g.observation?.process?.stale && !store.stale));
    ui.renderRows($("#game-library"),library,selected,select,store.loading?"Loading library…":store.stale?"Library data stale":"No matching games");
    const game=selected?store.games.get(selected):null;
    ui.details($("#game-detail"),game,store,action,closeDetail);
    $("#games-workspace").classList.toggle("gm-has-detail",!!game);
    const signature=store.epoch+":"+store.revision+":"+store.stale;
    if (signature!==lastSignature) { lastSignature=signature; if (!store.loading && !store.stale) log("Games updated (revision "+store.revision+")"); }
  }
  function select(id) { selected=id;render();$("#game-detail").focus(); }
  function closeDetail() { selected=null;render();$("#library-title").scrollIntoView({block:"nearest"});$("#game-search").focus(); }
  async function action(name,game) {
    error("");
    if (name==="reconcile") {
      try {await service.client.request("games.reconcile",{game_id:game.id});await service.resync();log("Refreshed observation for "+game.name);}
      catch(e){error(e.message);}return;
    }
    if (activeOperation) return;
    if (!game.capabilities?.[name] || store.stale) return error(game.capability_reason||"Action unavailable");
    const warning=name==="start"?"Start "+game.name+"?":name==="stop"?"Gracefully stop "+game.name+"? Unsaved progress may be lost.":
      "Restart "+game.name+"? Unsaved progress may be lost.";
    if (!window.confirm(warning)) {log(name+" cancelled");return;}
    activeOperation=true;render();log(name+" requested for "+game.name);
    try {
      const key="game-"+Date.now()+"-"+Math.random().toString(36).slice(2);
      const result=await control.command("/api/v1/games/ws","games.lifecycle."+name,{game_id:game.id,idempotency_key:key});
      if (!result?.operation_id) throw new Error("Missing operation ID");
      store.operation(result);log(name+" accepted; verifying actual process state");
      error("");await service.resync();
    } catch(e){error(e.message);log(name+" failed: "+e.message,"error");}
    finally {activeOperation=false;render();}
  }
  document.addEventListener("keydown",event=>{if(event.key==="Escape" && selected){event.preventDefault();closeDetail();}});
  $("#game-search").addEventListener("input",render);
  $("#game-filter").addEventListener("change",render);
  $("#refresh-catalog").addEventListener("click",async()=>{
    try { await service.client.request("games.catalog.refresh");await service.resync();log("Catalog refreshed"); }
    catch(e){error(e.message);}
  });
  $("#apply-token").addEventListener("click",()=>{
    control.setCredential($("#game-control-token").value);
    $("#game-control-token").value="";
    $("#token-status").textContent=control.hasCredential()?"Credential ready for this tab":"Token invalid (minimum 24 characters)";
  });
  service.store.on(render);
  log("Game Manager opened");
})();