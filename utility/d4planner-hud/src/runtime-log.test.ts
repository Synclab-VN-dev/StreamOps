import { beforeEach, expect, test, vi } from "vitest";
const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
beforeEach(() => { vi.resetModules(); invoke.mockReset(); });
test("logging is bounded and failures never reject UI work", async () => {
  const resolve: Array<() => void> = [];
  invoke.mockImplementation(() => new Promise<void>(r => resolve.push(r)));
  const { runtimeLog } = await import("./runtime-log");
  for (let n=0;n<80;n++) runtimeLog("DEBUG", "hud", "STATE_CHANGE", {revision:n});
  expect(invoke).toHaveBeenCalledTimes(32);
  resolve.forEach(r => r()); await new Promise(r => setTimeout(r,0));
  invoke.mockRejectedValue(new Error("unavailable"));
  expect(() => runtimeLog("INFO", "websocket", "CONNECT")).not.toThrow();
  expect(invoke.mock.calls.at(-1)?.[1].fields.dropped).toBe(48);
  await new Promise(r => setTimeout(r,0));
});
