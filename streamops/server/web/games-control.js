/* Credentials are per-tab memory only, never URLs, cookies, logs, or localStorage. */
(() => {
  let credential = "";
  function setCredential(value) {
    credential = typeof value === "string" ? value.trim() : "";
  }
  function hasCredential() { return credential.length >= 24; }
  function command(path, operation, payload) {
    if (!hasCredential()) return Promise.reject(Object.assign(new Error("Enter the game-control token first."),{code:"control_token_required"}));
    if (location.protocol !== "https:" && !["localhost","127.0.0.1"].includes(location.hostname)
        && !window.confirm("Unencrypted LAN connection: game-control credential can be exposed on this network. Continue?"))
      return Promise.reject(new Error("Use HTTPS or a trusted LAN."));
    return new Promise((resolve,reject) => {
      const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
      const socket = new WebSocket(url, ["streamops-games-v1","streamops-game-control." + credential]);
      const id = "req-" + Date.now() + "-" + Math.random().toString(36).slice(2);
      let settled = false;
      const timer = setTimeout(() => finish(new Error("Operation acknowledgement timed out.")), 20000);
      function finish(error, value) {
        if (settled) return;
        settled = true; clearTimeout(timer);
        try { socket.close(); } catch (_) {}
        if (error) reject(error); else resolve(value);
      }
      socket.addEventListener("open", () => socket.send(JSON.stringify({type:"request",request_id:id,operation,payload})));
      socket.addEventListener("message", ({data}) => {
        let message;
        try {message = JSON.parse(data);} catch (_) {return;}
        if (message.type !== "response" || message.request_id !== id) return;
        if (message.ok) finish(null,message.data);
        else finish(Object.assign(new Error(message.error?.message || "Operation rejected"),{code:message.error?.code}));
      });
      socket.addEventListener("close", () => finish(new Error("Control WebSocket disconnected before acknowledgement.")));
      socket.addEventListener("error", () => finish(new Error("Control WebSocket error.")));
    });
  }
  window.StreamOpsGameControl = {setCredential,hasCredential,command,clear:()=>setCredential("")};
  window.addEventListener("pagehide", () => setCredential(""));
})();