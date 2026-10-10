(() => {
  const client = new window.StreamOpsWebSocketClient({
    path:"/api/v1/steam/ws", label:"Steam Manager", connectionEvent:"streamops:steam-connection"
  });
  client.start();
  window.StreamOpsSteam = client;
})();