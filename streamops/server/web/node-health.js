/* Ticket #86 E2E-06: Node capture readiness is observed from the existing
 * OBS WebSocket status hub, never inferred from Steam/game state or REST.
 */
(() => {
  const status = document.querySelector("#node-health-status");
  if (!status) return;
  const client = new window.StreamOpsWebSocketClient({
    path:"/api/v1/obs/ws", label:"Node health"
  });
  let connected=false, observation=null;
  function render() {
    if (!connected || !observation || observation.status !== "ok") {
      status.textContent = "Node health: UNKNOWN (WS unavailable)";
      status.dataset.tone = "bad";
      return;
    }
    const ready=observation.capture_ready;
    const backend=typeof observation.capture_backend==="string"
      ? observation.capture_backend : "unknown";
    const text=ready===true?"Capture READY":ready===false?"Capture NOT READY":"Capture UNKNOWN";
    status.textContent = "Node health: online · "+text+" · "+backend;
    status.dataset.tone = ready===true?"ok":"warn";
  }
  client.onState(({state}) => {
    connected=state==="connected";
    if(!connected) observation=null;
    render();
  },{replay:true});
  client.on("obs.snapshot",data=>{
    observation=data?.node && typeof data.node==="object"?data.node:null;
    render();
  });
  client.start();
  window.StreamOpsNodeHealth = {client};
})();
