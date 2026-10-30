import { invoke } from "@tauri-apps/api/core";
let pending = 0;
let dropped = 0;
export function runtimeLog(level: "DEBUG" | "INFO" | "WARN" | "ERROR", tag: "webview" | "websocket" | "hud", event: "START" | "READY" | "ERROR" | "CONNECT" | "DISCONNECT" | "RECONNECT" | "STATE_CHANGE" | "REQUEST" | "RESULT", fields: {revision?: number; ok?: boolean; correlationId?: string; errorCode?: string} = {}) {
  if (pending >= 32) { dropped++; return; }
  pending++;
  const lost = dropped; dropped = 0;
  void invoke("runtime_log_event", {level, tag, event, fields: {...fields, ...(lost ? {dropped: lost} : {})}}).catch(() => {}).finally(() => { pending--; });
}
