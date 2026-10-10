/* Safe DOM renderers; game names are always textContent, never HTML. */
(() => {
  const Model = window.StreamOpsGamesStore;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function pill(value, fallback="UNKNOWN") {
    const label = value == null ? fallback : String(value);
    const node = element("span","gm-pill",label);
    node.dataset.tone = ["RUNNING","FOREGROUND","VERIFIED_ACTIVE","SELECTED"].includes(label) ? "ok"
      : ["ERROR","FAILED","UNKNOWN"].includes(label) ? "bad"
      : ["STARTING","STOPPING","CONFIGURED_ONLY"].includes(label) ? "warn" : "neutral";
    return node;
  }
  function safeNumber(value) { return value == null ? "Unknown" : String(value); }
  function renderSummary(root, store) {
    if (!root) return;
    root.replaceChildren();
    const summary = store.summary();
    const stats = element("div","gm-stats");
    for (const [name,key] of [["Running","running"],["Registered","registered"],["Capture verified","verified"]]) {
      const card=element("div","gm-stat");
      card.append(element("span","",name),element("strong","",summary[key] == null ? "Unknown" : summary[key]));
      stats.append(card);
    }
    root.append(stats);
  }
  function gameRow(game, selected, action) {
    const row = element("button","gm-game-row");
    row.type="button";row.dataset.gameId=game.id;
    row.setAttribute("aria-pressed",String(selected));
    const icon=element("span","gm-game-icon");
    icon.setAttribute("aria-hidden","true");
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("width","20");svg.setAttribute("height","20");
    svg.setAttribute("fill","none");svg.setAttribute("stroke","currentColor");
    svg.setAttribute("stroke-width","2");svg.setAttribute("stroke-linecap","round");
    svg.setAttribute("stroke-linejoin","round");
    for (const d of ["M6.6 12h4.8","M9 9.6v4.8","M15.5 11.9h.01","M18.5 10.9h.01",
      "M17 6H7a4 4 0 0 0-3.9 3.1l-1.6 8A2.4 2.4 0 0 0 3.9 20a2.4 2.4 0 0 0 1.7-.7L8 17h8l2.4 2.3a2.4 2.4 0 0 0 1.7.7 2.4 2.4 0 0 0 2.4-2.9l-1.6-8A4 4 0 0 0 17 6Z"]) {
      const p=document.createElementNS("http://www.w3.org/2000/svg","path");p.setAttribute("d",d);svg.append(p);
    }
    icon.append(svg);row.title=game.name;
    const text=element("span","gm-game-label");
    const seconds=game.observation?.process?.uptime_seconds;
    const uptime=Number.isFinite(seconds)&&seconds>=0?
      " · "+[Math.floor(seconds/3600),Math.floor(seconds%3600/60),Math.floor(seconds%60)]
        .map(x=>String(x).padStart(2,"0")).join(":"):"";
    const provider=String(game.provider||"Unknown");
    text.append(element("strong","",game.name),
      element("small","",provider.charAt(0).toUpperCase()+provider.slice(1)+uptime));
    row.append(icon,text,pill(game.observation?.process?.stale ? "UNKNOWN" : Model.gameState(game)));
    row.addEventListener("click",()=>action(game.id));
    return row;
  }
  function renderRows(root, games, selected, action, emptyMessage="No games") {
    if (!root) return;
    root.replaceChildren();
    if (!games.length) {root.append(element("p","gm-empty",emptyMessage));return;}
    for (const game of games) root.append(gameRow(game,selected===game.id,action));
  }
  function details(root, game, store, onAction, onBack) {
    root.replaceChildren();
    if (!game) {
      root.append(element("p","gm-empty","Select a game to see details."));
      return;
    }
    const obs=game.observation||{}, proc=obs.process||{};
    const running=proc.state==="RUNNING"&&!proc.stale&&!store.stale;
    const state=proc.stale||store.stale?"UNKNOWN":proc.state||"UNKNOWN";
    const pretty=value=>String(value??"UNKNOWN").replaceAll("_"," ").toLowerCase().replace(/^./,m=>m.toUpperCase());
    const valueText=value=>value==null?"—":String(value);
    const addHeading=(title,sub)=>{
      const box=element("div","gm-detail-section-heading");
      box.append(element("h3","",title));
      if(sub) box.append(element("p","gm-muted",sub));
      return box;
    };
    const row=(label,value,withPill=false)=>{
      const box=element("div","gm-detail-observation");
      box.append(element("span","gm-detail-observation-name",label));
      if(withPill) {
        const v=pill(pretty(value));v.dataset.code=String(value??"UNKNOWN");
        const raw=String(value??"UNKNOWN");
        v.dataset.tone=["FOREGROUND","VERIFIED_ACTIVE","SELECTED"].includes(raw)?"ok":
          ["CONFIGURED_ONLY","STARTING","STOPPING"].includes(raw)?"warn":
          ["ERROR","FAILED","UNKNOWN"].includes(raw)?"bad":"neutral";
        box.append(v);
      } else box.append(element("strong","",valueText(value)));
      return box;
    };
    const head=element("div","gm-detail-topbar");
    const back=element("button","gm-detail-back","← Back to games");
    back.type="button";back.addEventListener("click",onBack);
    const close=element("button","gm-detail-close","×");
    close.type="button";close.setAttribute("aria-label","Close game details");close.addEventListener("click",onBack);
    head.append(back,close);root.append(head);
    const intro=element("section","gm-detail-intro");
    const title=element("div","gm-detail-title");
    const icon=element("span","gm-game-icon","🎮");icon.setAttribute("aria-hidden","true");
    const titleText=element("div","gm-detail-title-text");
    titleText.append(element("h2","",game.name),
      element("p","gm-muted",[game.provider,game.genre].filter(Boolean).join(" · ")));
    const statePill=pill(pretty(state));statePill.dataset.code=state;
    statePill.dataset.tone=state==="RUNNING"?"ok":
      state==="FAILED"||state==="UNKNOWN"?"bad":"neutral";
    titleText.append(statePill);title.append(icon,titleText);intro.append(title);
    const stats=element("div","gm-detail-metrics");
    const metric=(label,value)=>{
      const item=element("div","gm-detail-metric");
      item.append(element("small","",label),element("strong","",valueText(value)));
      stats.append(item);
    };
    const formatSeconds=s=>{
      if(!Number.isFinite(s))return "—";
      const n=Math.max(0,Math.floor(s));
      return [Math.floor(n/3600),Math.floor(n%3600/60),n%60].map(x=>String(x).padStart(2,"0")).join(":");
    };
    metric("PID",running?proc.pid:null);
    metric("Uptime",running?formatSeconds(proc.uptime_seconds):"—");
    metric("Windows session",store.stale?null:proc.session_id);
    metric("Interactive",proc.interactive==null?"Unknown":proc.interactive?"Yes":"No");
    intro.append(stats);root.append(intro);
    const observed=element("section","gm-detail-section");
    observed.append(addHeading("Independent status","Process, window, OBS and streaming are verified separately."));
    const rows=element("div","gm-detail-observations");
    const win=store.stale?"UNKNOWN":obs.window;
    const capture=store.stale?"UNKNOWN":obs.obsCapture;
    const selected=store.stale?"UNKNOWN":obs.selectedForStream;
    rows.append(row("Window",win,true),row("OBS capture",capture,true),row("Selected for stream",selected,true));
    observed.append(rows);
    if(running&&capture==="CONFIGURED_ONLY") {
      const warning=element("p","gm-detail-warning","OBS capture is configured, but valid frames have not been verified.");
      warning.setAttribute("role","status");observed.append(warning);
    } else if(running&&capture==="ERROR") {
      const warning=element("p","gm-detail-warning gm-detail-danger","OBS cannot verify valid frames; the game process may still be healthy.");
      warning.setAttribute("role","alert");observed.append(warning);
    }
    root.append(observed);
    const controls=element("section","gm-detail-section");
    controls.append(addHeading("Game controls","Actions require verified capability and your confirmation."));
    const actions=element("div","gm-detail-action-row");
    for(const action of ["start","stop","restart"]) {
      const btn=element("button","gm-button gm-detail-action gm-detail-"+action,action[0].toUpperCase()+action.slice(1));
      btn.type="button";btn.dataset.action=action;
      const busy=Array.from(store.operations.values()).some(o=>
        o.game_id===game.id&&["PENDING","RUNNING"].includes(String(o.status).toUpperCase()));
      const allowed=game.capabilities?.[action]===true&&!store.stale&&!store.loading&&!busy;
      btn.disabled=!allowed;
      btn.title=allowed?"":game.capability_reason||"Unavailable or observation not verified";
      btn.addEventListener("click",()=>onAction(action,game));
      actions.append(btn);
    }
    controls.append(actions);
    const recent=Array.from(store.operations.values()).filter(o=>o.game_id===game.id).slice(-1)[0];
    if(recent) {
      const info=element("p","gm-operation","Operation "+(recent.action||"")+
        ": "+String(recent.status)+" / "+String(recent.phase||"UNKNOWN")+(recent.code?" ("+recent.code+")":""));
      info.setAttribute("role","status");controls.append(info);
    }
    if((recent&&String(recent.status)==="UNKNOWN")||state==="UNKNOWN"){
      const msg=element("p","gm-detail-warning",
        "Operation outcome unknown. A timeout does not prove the game stopped. Reconcile the observed state.");
      msg.setAttribute("role","alert");controls.append(msg);
    }
    const refresh=element("button","gm-button gm-secondary gm-detail-refresh","↻ Refresh / reconcile process");
    refresh.type="button";refresh.disabled=store.stale;
    refresh.addEventListener("click",()=>onAction("reconcile",game));controls.append(refresh);
    if(!game.capabilities?.start&&!game.capabilities?.stop&&!game.capabilities?.restart) {
      const warning=element("p","gm-action-reason","Actions unavailable: "+
        (store.stale?"WebSocket disconnected / stale":game.capability_reason||"Capability unverified"));
      warning.setAttribute("role","status");controls.append(warning);
    }
    root.append(controls);
    const related=element("section","gm-detail-section");
    related.append(addHeading("Related services"));
    const sub=element("div","gm-detail-observations");
    sub.append(row(game.provider==="steam"?"Steam client":game.provider+" launcher",
        obs.launcherState||"UNKNOWN",true),row("OBS capture",capture,true));
    related.append(sub);root.append(related);
    const advanced=element("details","gm-detail-advanced");
    advanced.append(element("summary","","Advanced & recovery"));
    const unsafe=element("button","gm-button gm-secondary","Force Stop (disabled)");
    unsafe.type="button";unsafe.disabled=true;unsafe.title="Disabled for safety in V1";
    advanced.append(unsafe,element("p","gm-muted","Force stop is disabled in V1; unsaved progress could be lost."));
    root.append(advanced);
  }
  window.StreamOpsGamesComponents={element,pill,renderSummary,renderRows,details};
})();