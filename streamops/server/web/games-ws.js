/* Read-only WS connection: commands needing credentials use games-control.js. */
(() => {
  const Client = window.StreamOpsWebSocketClient;
  const Model = window.StreamOpsGamesStore;
  const store = new Model.GameStore();
  const client = new Client({path:"/api/v1/games/ws", label:"Game Manager", connectionEvent:"streamops:games-connection"});
  let recovery = false;
  async function resync() {
    if (recovery || !client.connected) return;
    recovery = true;
    try {
      const data = await client.request("games.list");
      if (data?.games && data?.epoch) store.snapshot(data);
      store.needsResync = false;
      for (const id of store.operations.keys()) {
        try { store.operation(await client.request("games.operations.get", {operation_id:id})); }
        catch (_) { /* keep status unknown; never retry mutations */ }
      }
    } catch (error) {
      store.error = error.message; store.stale = true; store.emit();
    } finally { recovery = false; }
  }
  for (const event of ["games.snapshot","games.changed","games.operation","games.catalog.changed","games.heartbeat"]) {
    client.on(event, data => {
      store.event(event, data);
      if (store.needsResync) void resync();
    });
  }
  client.onState(({state}) => {
    store.connection(state);
    if (state === "connected") void resync();
  });
  client.start();
  window.StreamOpsGames = {client, store, resync};
})();