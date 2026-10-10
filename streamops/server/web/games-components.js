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
    const icon=element("span","gm-game-icon","▣");
    icon.setAttribute("aria-hidden","true");
    const text=element("span","gm-game-label");
    text.append(element("strong","",game.name),element("small","",game.provider));
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
    if (!game) {root.append(element("p","gm-empty","Select a game to see details.")); return;}
    const head=element("div","gm-detail-heading");
    const back=element("button","gm-button gm-secondary gm-back","← Back");
    back.type="button";back.addEventListener("click",onBack);
    const name=element("div","");name.append(element("h2","",game.name),element("p","gm-muted",game.provider+" · "+game.id));
    head.append(back,name);root.append(head);
    const obs=game.observation||{}, proc=obs.process||{};
    const status=element("div","gm-detail-grid");
    for (const [label,value] of [
      ["Process",proc.stale || store.stale ? "UNKNOWN" : proc.state],
      ["PID",proc.pid],["Windows session",proc.session_id],["Window",obs.window],
      ["OBS capture",obs.obsCapture],["Stream selection",obs.selectedForStream],
      ["Installed",obs.installed == null ? "UNKNOWN" : obs.installed ? "Yes" : "No"],
      ["Owned",obs.owned == null ? "UNKNOWN" : obs.owned ? "Yes" : "No"]
    ]) {
      const cell=element("div","gm-detail-cell");
      cell.append(element("small","",label));
      if (["Process","Window","OBS capture","Stream selection"].includes(label)) cell.append(pill(value));
      else cell.append(element("strong","",safeNumber(value)));
      status.append(cell);
    }
    root.append(status);
    const actions=element("div","gm-action-grid");
    for (const action of ["start","stop","restart"]) {
      const btn=element("button","gm-button "+(action==="stop"?"gm-danger":""),action[0].toUpperCase()+action.slice(1));
      btn.type="button";
      const allowed=game.capabilities?.[action]===true && !store.stale && !store.loading
        && !Array.from(store.operations.values()).some(o=>o.game_id===game.id&&["PENDING","RUNNING"].includes(String(o.status).toUpperCase()));
      btn.disabled=!allowed;btn.title=allowed?"":game.capability_reason||"Unavailable or observation not verified";
      btn.addEventListener("click",()=>onAction(action,game));
      actions.append(btn);
    }
    const force=element("button","gm-button gm-secondary","Force Stop (disabled)");
    force.type="button";force.disabled=true;force.title="Disabled for safety in V1";actions.append(force);
    const refresh=element("button","gm-button gm-secondary","Refresh observation");
    refresh.type="button";refresh.disabled=store.stale;refresh.addEventListener("click",()=>onAction("reconcile",game));actions.append(refresh);
    root.append(actions);
    const related=element("details","gm-related");
    related.append(element("summary","","Related services and advanced"));
    related.append(element("p","gm-muted","Steam, OBS and optional D4Planner are independent; unavailable services do not mean this game failed."));
    root.append(related);
    const recent=Array.from(store.operations.values()).filter(o=>o.game_id===game.id).slice(-1)[0];
    if (recent) {
      const info=element("p","gm-operation","Operation "+recent.action+": "+recent.status+" / "+recent.phase+(recent.code?" ("+recent.code+")":""));
      info.setAttribute("role","status");root.append(info);
    }
  }
  window.StreamOpsGamesComponents={element,pill,renderSummary,renderRows,details};
})();