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
    fireEvent.click(screen.getByRole("button", { name: /Equipment/ }));
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
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open target menu" }));
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
    fireEvent.click(await screen.findByRole("button", { name: /Equipment/ }));
    fireEvent.click(screen.getByRole("button", { name: /Gloves/ }));
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

it('Equipment owns its section independently of Compare and Summary resets children', async () => {
  render(<App dataSource={new FakeDataSource()} />);
  const equipment = await screen.findByRole('button', {name: /Equipment/});
  expect(screen.queryByRole('complementary', {name: 'Equipment list'})).toBeNull();
  fireEvent.click(equipment);
  expect(screen.getByRole('complementary', {name: 'Equipment list'})).toBeTruthy();
  expect(screen.queryByRole('complementary', {name: 'Item comparison'})).toBeNull();
  fireEvent.click(screen.getByRole('button', {name: /Gloves/}));
  fireEvent.click(screen.getByRole('button', {name: 'Close item comparison'}));
  expect(screen.getByRole('complementary', {name: 'Equipment list'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name: /Gloves/}));
  fireEvent.click(screen.getByRole('button', {name: 'Close equipment'}));
  expect(screen.queryByRole('complementary')).toBeNull();
  fireEvent.click(equipment);
  const summary = screen.getByRole('button', {name: /SYNTHETIC CHARGE BOLT BUILD/});
  fireEvent.click(summary); fireEvent.click(summary);
  expect(screen.queryByRole('complementary')).toBeNull();
});

it('never marks last-known data current on a reconnect before authoritative recovery', async () => {
  const source = new FakeDataSource();
  render(<App dataSource={source} />);
  await screen.findByText('50');
  act(() => source.emit({type: 'CONNECTION', state: 'DISCONNECTED', reason: 'Resynchronizing Backend state'}));
  act(() => source.emit({type: 'CONNECTION', state: 'CONNECTED'}));
  expect(screen.getByRole('status').textContent).toMatch(/last-known/i);
  expect(document.querySelector('main')?.getAttribute('data-freshness')).toBe('STALE');
  act(() => source.emit({type: 'SNAPSHOT', snapshot: targetBSnapshot()}));
  expect(document.querySelector('main')?.getAttribute('data-freshness')).toBe('CURRENT');
  expect(screen.queryByRole('status')).toBeNull();
});

it('hides known-mismatched score and Equipment until authoritative discovery', async () => {
  const source = new FakeDataSource(); render(<App dataSource={source} />);
  fireEvent.click(await screen.findByRole('button', {name: /Equipment/}));
  expect(screen.getByText('50')).toBeTruthy();
  expect(screen.getByText('Gloves')).toBeTruthy();
  act(() => source.emit({type: 'ASSESSMENT_INVALIDATED'}));
  expect(screen.queryByText('50')).toBeNull();
  expect(screen.queryByText('Gloves')).toBeNull();
  expect(screen.getByText('—')).toBeTruthy();
  act(() => source.emit({type: 'SNAPSHOT', snapshot: targetBSnapshot()}));
  expect(screen.getByText('50')).toBeTruthy();
  expect(screen.getByText('SYNTHETIC FIREWALL')).toBeTruthy();
});

it.each(['TARGET_CHANGED', 'INTERNAL'])('typed %s socket rejection reaches the controller without disconnecting the HUD', async code => {
  const {TauriHudDataSource} = await import('./hud-data-source');
  const socket = {
    readyState: 1, onopen: null as (() => void) | null,
    onclose: null as (() => void) | null,
    onmessage: null as ((event: {data: string}) => void) | null,
    sent: [] as Record<string, any>[],
    send(data: string) { this.sent.push(JSON.parse(data)); },
    close() { this.onclose?.(); },
    receive(message: Record<string, any>) { this.onmessage?.({data: JSON.stringify(message)}); },
  };
  mocks.invoke.mockImplementation(async (command: string) => command === 'get_hud_ws_bootstrap'
    ? {endpoint: 'ws://127.0.0.1:30001', credential: 'x'.repeat(64), origin: 'tauri://localhost'} : undefined);
  const source = new TauriHudDataSource(mocks.invoke, () => socket);
  const view = render(<App dataSource={source} />);
  await waitFor(() => expect(socket.onopen).not.toBeNull());
  act(() => socket.onopen?.());
  const envelope = {protocolVersion: 'd4planner-ws/v1', backendGeneration: partial.backend.generation};
  act(() => socket.receive({...envelope, type: 'hello.accepted', correlationId: socket.sent[0].messageId,
    runtimeInstanceId: partial.backend.runtimeInstanceId}));
  const snapshotRequest = socket.sent.find(message => message.type === 'hud.snapshot.request')!;
  act(() => socket.receive({...envelope, type: 'hud.snapshot', authoritative: true,
    correlationId: snapshotRequest.messageId, subscriptionId: 'ui-sub', hud: partial}));
  await screen.findByText('50');
  fireEvent.click(screen.getByRole('button', {name: 'Open target menu'}));
  act(() => socket.receive({...envelope, type: 'target.list.result',
    correlationId: socket.sent.at(-1)!.messageId, listRevision: 1, targets}));
  fireEvent.click(screen.getByRole('menuitem', {name: /Firewall/}));
  await act(async () => socket.receive({...envelope, type: 'error',
    correlationId: socket.sent.at(-1)!.messageId, code, message: 'Target operation failed'}));
  expect(screen.getByRole('alert').textContent).toContain(code);
  expect(document.querySelector('main')?.getAttribute('data-connection')).toBe('CONNECTED');
  expect(screen.getByText('50')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name: 'Open target menu'}));
  expect(screen.getByText('Loading Targets…')).toBeTruthy();
  act(() => socket.receive({...envelope, type:'target.list.result', correlationId:socket.sent.at(-1)!.messageId, listRevision:1, targets}));
  expect((screen.getByRole('menuitem', {name: /Firewall/}) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole('menuitem', {name:/Firewall/}));
  await act(async () => socket.receive({...envelope, type:'target.select.result',
    correlationId:socket.sent.at(-1)!.messageId,status:'ACTIVATED',targetId:'target-b',contentSha256:'c'.repeat(64),selectionRevision:8}));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(document.querySelector('main')?.getAttribute('data-connection')).toBe('CONNECTED');
  // A gap forces known-context resync. A different authoritative context
  // must hide A until the separate discovery reply has passed all guards.
  const changed = targetBSnapshot(partial.hudRevision + 10);
  act(() => socket.receive({...envelope, type: 'hud.update', subscriptionId: 'ui-sub',
    previousHudRevision: partial.hudRevision + 8, hud: changed}));
  const known = socket.sent.at(-1)!;
  expect(known.requestContext.mode).toBe('RESYNC_KNOWN_CONTEXT');
  act(() => socket.receive({...envelope, type: 'hud.snapshot', authoritative: true,
    correlationId: known.messageId, subscriptionId: 'mismatch', hud: changed}));
  const discovery = socket.sent.at(-1)!;
  expect(discovery.requestContext.mode).toBe('DISCOVER_ACTIVE_CONTEXT');
  expect(screen.queryByText('50')).toBeNull();
  expect(screen.queryByRole('complementary', {name: 'Equipment list'})).toBeNull();
  act(() => socket.receive({...envelope, type: 'hud.snapshot', authoritative: true,
    correlationId: known.messageId, subscriptionId: 'late', hud: partial}));
  expect(screen.queryByText('50')).toBeNull();
  act(() => socket.receive({...envelope, type: 'hud.snapshot', authoritative: true,
    correlationId: discovery.messageId, subscriptionId: 'discovered', hud: changed}));
  expect(screen.getByText('SYNTHETIC FIREWALL')).toBeTruthy();
  expect(screen.getByText('50')).toBeTruthy();
  expect(document.querySelector('main')?.getAttribute('data-freshness')).toBe('CURRENT');
  view.unmount();
});

it('shows a listing failure instead of empty or stale targets and permits retry', async () => {
  const {TauriHudDataSource} = await import('./hud-data-source');
  const socket = {
    readyState: 1, onopen: null as (() => void) | null,
    onclose: null as (() => void) | null,
    onmessage: null as ((event: {data: string}) => void) | null,
    sent: [] as Record<string, any>[],
    send(data: string) { this.sent.push(JSON.parse(data)); },
    close() { this.onclose?.(); },
    receive(message: Record<string, any>) { this.onmessage?.({data: JSON.stringify(message)}); },
  };
  mocks.invoke.mockImplementation(async (command: string) => command === 'get_hud_ws_bootstrap'
    ? {endpoint: 'ws://127.0.0.1:30001', credential: 'x'.repeat(64), origin: 'tauri://localhost'} : undefined);
  const source = new TauriHudDataSource(mocks.invoke, () => socket);
  const view = render(<App dataSource={source} />);
  await waitFor(() => expect(socket.onopen).not.toBeNull());
  act(() => socket.onopen?.());
  const envelope = {protocolVersion: 'd4planner-ws/v1', backendGeneration: partial.backend.generation};
  act(() => socket.receive({...envelope, type: 'hello.accepted', correlationId: socket.sent[0].messageId,
    runtimeInstanceId: partial.backend.runtimeInstanceId}));
  const snapshotRequest = socket.sent.find(message => message.type === 'hud.snapshot.request')!;
  act(() => socket.receive({...envelope, type: 'hud.snapshot', authoritative: true,
    correlationId: snapshotRequest.messageId, subscriptionId: 'ui-sub', hud: partial}));
  await screen.findByText('50');

  fireEvent.click(screen.getByRole('button', {name: 'Open target menu'}));
  const failedId = socket.sent.at(-1)!.messageId;
  await act(async () => socket.receive({...envelope, type:'error', correlationId:failedId,
    code:'TARGET_INVALID', message:'Target listing is unavailable.', retryable:false}));
  expect(screen.getByRole('alert').textContent).toContain('TARGET_INVALID');
  expect(screen.queryByText('No Target JSON files')).toBeNull();
  // Target failure must not remove the independent Report Issue action.
  expect(screen.queryAllByRole('menuitem').filter(item => item.textContent !== 'Report Issue')).toHaveLength(0);
  expect(screen.getByRole('menuitem', {name:'Report Issue'})).toBeTruthy();
  expect(document.querySelector('main')?.getAttribute('data-connection')).toBe('CONNECTED');
  expect(document.querySelector('main')?.getAttribute('data-freshness')).toBe('CURRENT');
  fireEvent.click(screen.getByRole('button', {name:'Retry Target list'}));
  expect(screen.getByText('Loading Targets…')).toBeTruthy();
  const retry = socket.sent.at(-1)!.messageId;
  act(() => socket.receive({...envelope, type:'target.list.result',correlationId:failedId,listRevision:99,targets}));
  // Target failure must not remove the independent Report Issue action.
  expect(screen.queryAllByRole('menuitem').filter(item => item.textContent !== 'Report Issue')).toHaveLength(0);
  expect(screen.getByRole('menuitem', {name:'Report Issue'})).toBeTruthy();
  act(() => socket.receive({...envelope, type:'target.list.result',correlationId:retry,listRevision:1,targets}));
  expect(screen.queryByRole('alert')).toBeNull();
  fireEvent.click(screen.getByRole('menuitem', {name:/Firewall/}));
  const select = socket.sent.at(-1)!.messageId;
  await act(async () => socket.receive({...envelope,type:'target.select.result',correlationId:select,
    status:'ACTIVATED',targetId:'target-b',contentSha256:'c'.repeat(64),selectionRevision:8}));
  act(() => socket.receive({...envelope,type:'hud.update',subscriptionId:'ui-sub',previousHudRevision:partial.hudRevision,
    hud:targetBSnapshot(partial.hudRevision+1)}));
  expect(screen.getByText('SYNTHETIC FIREWALL')).toBeTruthy();
  view.unmount();
});

it('Report Issue pointer interaction does not start native window dragging', async () => {
  render(<App dataSource={new FakeDataSource()} />);
  await screen.findByText('SYNTHETIC CHARGE BOLT BUILD');
  const menu=screen.getByRole('button',{name:'Open target menu'});
  fireEvent.mouseDown(menu,{button:0});
  expect(mocks.invoke.mock.calls.filter(call=>call[0]==='drag_overlay')).toHaveLength(0);
  fireEvent.click(menu);
  fireEvent.mouseDown(screen.getByRole('menuitem',{name:'Report Issue'}),{button:0});
  fireEvent.click(screen.getByRole('menuitem',{name:'Report Issue'}));
  expect(screen.getByLabelText('Report Issue')).toBeTruthy();
  expect(mocks.invoke.mock.calls.filter(call=>call[0]==='drag_overlay')).toHaveLength(0);
});
