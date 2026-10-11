/* V1 trusted-LAN game-control WebSocket. No application tokens (BE #85 contract). */
(() => {
  function command(path, operation, payload) {
    return new Promise((resolve,reject) => {
      const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
      const socket = new WebSocket(url, "streamops-games-v1");
      const id = "req-" + Date.now() + "-" + Math.random().toString(36).slice(2);
      let settled = false;
      const timer = setTimeout(() => finish(new Error("Operation acknowledgement timed out.")), 20000);
      function finish(error, value) {
        if (settled) return;
        settled = true; clearTimeout(timer);
        try { socket.close(); } catch (_) {}
        if (error) reject(error); else resolve(value);
      }
      socket.addEventListener("open", () => socket.send(JSON.stringify({
        type:"request",request_id:id,operation,payload
      })));
      socket.addEventListener("message", ({data}) => {
        let message;
        try { message = JSON.parse(data); } catch (_) { return; }
        if (message.type !== "response" || message.request_id !== id) return;
        if (message.ok) finish(null,message.data);
        else finish(Object.assign(new Error(message.error?.message || "Operation rejected"),
          {code:message.error?.code}));
      });
      socket.addEventListener("close", () => finish(new Error("Control WebSocket disconnected before acknowledgement.")));
      socket.addEventListener("error", () => finish(new Error("Control WebSocket error.")));
    });
  }
  window.StreamOpsGameControl = {command};
})();
