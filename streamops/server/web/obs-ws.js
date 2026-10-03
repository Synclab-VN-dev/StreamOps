(() => {
  const Client = window.StreamOpsWebSocketClient;
  if (!Client) throw new Error('StreamOpsWebSocketClient is not loaded.');

  window.StreamOpsObs = new Client({
    path: '/api/v1/obs/ws',
    label: 'OBS dashboard',
    connectionEvent: 'streamops:obs-connection',
  }).start();
})();
