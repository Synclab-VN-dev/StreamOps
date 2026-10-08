// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { OverlayStatus } from "./overlay-mode";
import App from "./App";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
  unlisten: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: mocks.listen }));

let onMode: ((event: { payload: OverlayStatus }) => void) | undefined;

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  onMode = undefined;
  mocks.listen.mockImplementation(async (_event: string, callback: typeof onMode) => {
    onMode = callback;
    return mocks.unlisten;
  });
  mocks.invoke.mockImplementation(async (command: string, args?: { interactive: boolean }) => {
    if (command === "get_overlay_status") return { interactive: true };
    if (command === "set_overlay_mode") return { interactive: args!.interactive };
    if (command === "drag_overlay") return undefined;
    throw new Error("unexpected IPC " + command);
  });
});

describe("HUD / Tauri IPC interaction", () => {
  it("renders mock score and starts interactive, then enters passive click-through", async () => {
    render(<App />);
    expect(screen.getByText("CHARGE BOLT")).toBeTruthy();
    expect(screen.getByText("8 / 10")).toBeTruthy();
    expect(screen.getByText("6 / 8")).toBeTruthy();
    await screen.findByText("INTERACTIVE");
    fireEvent.click(screen.getByRole("button", { name: "Enable pass-through" }));
    await screen.findByText("PASSIVE");
    expect(mocks.invoke).toHaveBeenCalledWith("set_overlay_mode", { interactive: false });
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => onMode?.({ payload: { interactive: true } }));
    expect(screen.getByText("INTERACTIVE")).toBeTruthy();
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("refuses repeated clicks while IPC is pending", async () => {
    let finish!: (value: OverlayStatus) => void;
    const pending = new Promise<OverlayStatus>((resolve) => { finish = resolve; });
    mocks.invoke.mockImplementation(async (command: string) =>
      command === "get_overlay_status" ? { interactive: true } : pending);
    render(<App />);
    await screen.findByText("INTERACTIVE");
    const button = screen.getByRole("button");
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mocks.invoke.mock.calls.filter((args) => args[0] === "set_overlay_mode")).toHaveLength(1);
    await act(async () => finish({ interactive: false }));
    expect(screen.getByText("PASSIVE")).toBeTruthy();
  });

  it("preserves interactive controls when Windows rejects the cursor mode switch", async () => {
    mocks.invoke.mockImplementation(async (command: string) => {
      if (command === "get_overlay_status") return { interactive: true };
      throw new Error("native hit-testing rejected");
    });
    render(<App />);
    await screen.findByText("INTERACTIVE");
    fireEvent.click(screen.getByRole("button"));
    await screen.findByRole("alert");
    expect(screen.getByText("INTERACTIVE")).toBeTruthy();
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("global hotkey event beats stale initial get-status response", async () => {
    let finish!: (value: OverlayStatus) => void;
    mocks.invoke.mockImplementation(async (command: string) =>
      command === "get_overlay_status"
        ? new Promise<OverlayStatus>((resolve) => { finish = resolve; })
        : undefined);
    render(<App />);
    await waitFor(() => expect(onMode).toBeDefined());
    await act(async () => onMode?.({ payload: { interactive: false } }));
    await act(async () => finish({ interactive: true }));
    expect(screen.getByText("PASSIVE")).toBeTruthy();
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("only allows dragging in interactive mode with left mouse button", async () => {
    render(<App />);
    await screen.findByText("INTERACTIVE");
    const header = screen.getByText("CHARGE BOLT").closest("header")!;
    fireEvent.mouseDown(header, { button: 2 });
    expect(mocks.invoke).not.toHaveBeenCalledWith("drag_overlay");
    fireEvent.mouseDown(header, { button: 0 });
    await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith("drag_overlay"));
    await act(async () => onMode?.({ payload: { interactive: false } }));
    mocks.invoke.mockClear();
    fireEvent.mouseDown(header, { button: 0 });
    expect(mocks.invoke).not.toHaveBeenCalledWith("drag_overlay");
  });

  it("fails safe if event subscription fails, and unsubscribes on unmount", async () => {
    mocks.listen.mockRejectedValueOnce(new Error("global event unavailable"));
    const { unmount } = render(<App />);
    await screen.findByRole("alert");
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    unmount();

    const next = render(<App />);
    await screen.findByText("INTERACTIVE");
    next.unmount();
    expect(mocks.unlisten).toHaveBeenCalledTimes(1);
  });
});
