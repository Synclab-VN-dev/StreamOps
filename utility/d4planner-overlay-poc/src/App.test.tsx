// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import partialFixture from "../../d4planner/contracts/release1/v1/fixtures/hud.partial.synthetic.json";
import noDataFixture from "../../d4planner/contracts/release1/v1/fixtures/hud.no-data.synthetic.json";
import App from "./App";
import type { HudDataEvent, IHudDataSource } from "./hud-data-source";
import type { HudSnapshot, SelectionResult, TargetListEntry } from "./hud-model";

const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));

const partial = partialFixture as unknown as HudSnapshot;
const noData = noDataFixture as unknown as HudSnapshot;
const targets: TargetListEntry[] = [
  { targetId: "synthetic-charge-bolt", displayName: "Charge Bolt", contentSha256: "a".repeat(64), byteLength: 100, validation: "VALID", errorCodes: [] },
  { targetId: "invalid-target", displayName: "Broken target", contentSha256: "b".repeat(64), byteLength: 10, validation: "INVALID", errorCodes: ["SCHEMA_INVALID"] },
  { targetId: "target-b", displayName: "Firewall", contentSha256: "c".repeat(64), byteLength: 120, validation: "VALID", errorCodes: [] },
];

class FakeDataSource implements IHudDataSource {
  listener?: (event: HudDataEvent) => void;
  selections: Array<{ targetId: string; expectedSha256: string }> = [];
  result: SelectionResult | null = null;
  holdSelection = false;
  finishSelection?: (result: SelectionResult) => void;
  constructor(private initial: HudSnapshot = partial) {}
  async connect(listener: (event: HudDataEvent) => void) {
    this.listener = listener;
    listener({ type: "CONNECTION", state: "CONNECTED" });
    listener({ type: "SNAPSHOT", snapshot: this.initial });
    return () => { this.listener = undefined; };
  }
  async refreshTargets() { this.listener?.({ type: "TARGETS", targets }); }
  async selectTarget(request: { targetId: string; expectedSha256: string }) {
    this.selections.push(request);
    if (this.holdSelection) return await new Promise<SelectionResult>(resolve => { this.finishSelection = resolve; });
    return this.result ?? { status: "ACTIVATED", targetId: request.targetId, contentSha256: request.expectedSha256, selectionRevision: 8 };
  }
  emit(event: HudDataEvent) { this.listener?.(event); }
}

function targetBSnapshot(revision = 13): HudSnapshot {
  return {
    ...partial, hudRevision: revision,
    context: {
      ...partial.context,
      target: { ...partial.context.target!, targetId: "target-b", displayName: "Firewall", buildDisplayName: "Synthetic Firewall", contentSha256: "c".repeat(64), selectionRevision: 8 },
      binding: { ...partial.context.binding!, targetId: "target-b", targetSha256: "c".repeat(64), selectionRevision: 8 },
    },
  };
}

beforeEach(() => { cleanup(); vi.clearAllMocks(); mocks.invoke.mockResolvedValue(undefined); });

describe("Release 1 Equipment HUD", () => {
  it("renders BE score, item counts and partial Equipment without client-side coverage UI", async () => {
    render(<App dataSource={new FakeDataSource()} />);
    await screen.findByText("SYNTHETIC CHARGE BOLT BUILD");
    expect(screen.getByText("50")).toBeTruthy();
    expect(screen.getByText("0/1")).toBeTruthy();
    expect(screen.getByText("Gloves")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Coverage");
    expect(document.body.textContent).not.toContain("Charms");
    expect(document.body.textContent).not.toContain("Torment");
  });

  it("lists targets but permits only valid ID/hash selection", async () => {
    const source = new FakeDataSource();
    render(<App dataSource={source} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open target menu" }));
    const invalid = await screen.findByRole("menuitem", { name: /Broken target/ });
    expect((invalid as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("menuitem", { name: /Firewall/ }));
    await waitFor(() => expect(source.selections).toEqual([{ targetId: "target-b", expectedSha256: "c".repeat(64) }]));
  });

  it("keeps the old target label and score when server rejects changed bytes", async () => {
    const source = new FakeDataSource();
    source.result = { status: "TARGET_CHANGED", targetId: "target-b", message: "Target changed after listing" };
    render(<App dataSource={source} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open target menu" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Firewall/ }));
    await screen.findByRole("alert");
    expect(screen.getByText("SYNTHETIC CHARGE BOLT BUILD")).toBeTruthy();
    expect(screen.getByText("50")).toBeTruthy();
  });

  it("bounds racing target choices to one pending server activation", async () => {
    const source = new FakeDataSource();
    source.holdSelection = true;
    render(<App dataSource={source} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open target menu" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Firewall/ }));
    await waitFor(() => expect(source.selections).toHaveLength(1));
    const first = screen.getByRole("menuitem", { name: /Charge Bolt/ });
    expect((first as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(first);
    expect(source.selections).toHaveLength(1);
    await act(async () => source.finishSelection?.({ status: "ACTIVATED", targetId: "target-b", contentSha256: "c".repeat(64), selectionRevision: 8 }));
  });

  it("does not show an activated target until an authoritative bound snapshot arrives", async () => {
    const source = new FakeDataSource();
    render(<App dataSource={source} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open target menu" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Firewall/ }));
    await waitFor(() => expect(source.selections).toHaveLength(1));
    expect(screen.getByText("SYNTHETIC CHARGE BOLT BUILD")).toBeTruthy();
    act(() => source.emit({ type: "SNAPSHOT", snapshot: targetBSnapshot() }));
    await screen.findByText("SYNTHETIC FIREWALL");
  });

  it("ignores stale same-generation snapshots and marks disconnect as not current", async () => {
    const source = new FakeDataSource(targetBSnapshot(20));
    render(<App dataSource={source} />);
    await screen.findByText("SYNTHETIC FIREWALL");
    act(() => source.emit({ type: "SNAPSHOT", snapshot: { ...partial, hudRevision: 18 } }));
    expect(screen.getByText("SYNTHETIC FIREWALL")).toBeTruthy();
    act(() => source.emit({ type: "CONNECTION", state: "DISCONNECTED", reason: "socket closed" }));
    expect(screen.getByText(/assessment is not current/)).toBeTruthy();
  });

  it("clears only stale connection errors after a validated authoritative reconnect snapshot", async () => {
    const source = new FakeDataSource(targetBSnapshot(20));
    render(<App dataSource={source} />);
    await screen.findByText("SYNTHETIC FIREWALL");
    act(() => source.emit({ type: "CONNECTION", state: "DISCONNECTED", reason: "socket closed" }));
    expect(screen.getByRole("alert").textContent).toContain("socket closed");
    act(() => source.emit({ type: "CONNECTION", state: "CONNECTED" }));
    expect(screen.getByRole("alert").textContent).toContain("socket closed");

    const restarted = {
      ...targetBSnapshot(1),
      backend: { runtimeInstanceId: "backend-new", generation: 4 },
    };
    act(() => source.emit({ type: "SNAPSHOT", snapshot: restarted }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

    // A late snapshot from the old generation cannot restore old UI state.
    act(() => source.emit({ type: "SNAPSHOT", snapshot: targetBSnapshot(99) }));
    expect(screen.getByText("SYNTHETIC FIREWALL")).toBeTruthy();
  });

  it("renders NO_DATA distinctly from a valid zero or fabricated 100", async () => {
    render(<App dataSource={new FakeDataSource(noData)} />);
    await screen.findByText("NO DATA");
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("100")).toBeNull();
  });

  it("Issues-only includes WARN but excludes UNKNOWN until All is selected", async () => {
    render(<App dataSource={new FakeDataSource()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Gloves/ }));
    fireEvent.click(screen.getByRole("button", { name: /Affixes/ }));
    expect(screen.queryByText(/Core Skill Ranks ·/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText(/Core Skill Ranks ·/)).toBeTruthy();
  });

  it("keeps Pin always-on-top and requests only the approved true state", async () => {
    render(<App dataSource={new FakeDataSource()} />);
    fireEvent.click(await screen.findByRole("button", { name: "⌖ Pinned" }));
    expect(mocks.invoke).toHaveBeenCalledWith("set_overlay_pin", { pinned: true });
  });
});
