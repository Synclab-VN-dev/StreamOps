(() => {
  const Client = window.StreamOpsWebSocketClient;
  if (!Client) throw new Error('StreamOpsWebSocketClient is not loaded.');

  window.StreamOpsLive = new Client({
    path: '/api/v1/live/ws',
    label: 'Streaming',
    connectionEvent: 'streamops:live-connection',
  }).start();
})();
