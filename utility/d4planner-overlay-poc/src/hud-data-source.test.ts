import { afterEach, describe, expect, it, vi } from 'vitest';
import { HudWebSocketDataSource, type WebSocketLike } from './hud-data-source';
import hudFixture from '../../d4planner/contracts/release1/v1/fixtures/hud.partial.synthetic.json';

class FakeSocket implements WebSocketLike {
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: Record<string, any>[] = [];
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  receive(message: Record<string, any>) { this.onmessage?.({ data: JSON.stringify(message) }); }
}

const credential = 'test-only-private-credential-000000000000';
const backend = { runtimeInstanceId: 'backend-a', generation: 3 };

function hud(revision: number, targetId = 'target-a', characterId = 'character-a') {
  const value = structuredClone(hudFixture) as Record<string, any>;
  const selectionRevision = targetId === 'target-a' ? 7 : 8;
  const contentSha256 = (targetId === 'target-a' ? 'a' : 'b').repeat(64);
  value.hudRevision = revision;
  value.backend = { runtimeInstanceId: backend.runtimeInstanceId, generation: backend.generation };
  value.context.character.characterId = characterId;
  value.context.target.targetId = targetId;
  value.context.target.contentSha256 = contentSha256;
  value.context.target.selectionRevision = selectionRevision;
  value.context.binding = {
    runtimeInstanceId: backend.runtimeInstanceId,
    characterId,
    currentRevision: value.context.character.currentRevision,
    targetId,
    targetSha256: contentSha256,
    selectionRevision,
    policyVersion: value.context.target.policyVersion,
  };
  value.score.value = targetId === 'target-a' ? 50 : 75;
  return value;
}

function setup(
  reconnectDelaysMs?: readonly number[],
  recovery?: { snapshotOperationTimeoutMs: number; maxDiscoveryAttempts: number },
) {
  const sockets: FakeSocket[] = [];
  const source = new HudWebSocketDataSource({
    endpoint: 'ws://127.0.0.1:12345',
    credential,
    origin: 'tauri://localhost',
    reconnectDelaysMs,
    ...recovery,
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  source.connect();
  const socket = sockets[0];
  socket.onopen?.();
  return { source, socket, sockets };
}

afterEach(() => vi.useRealTimers());

function accept(socket: FakeSocket, runtime = backend) {
  socket.receive({
    protocolVersion: 'd4planner-ws/v1',
    type: 'hello.accepted',
    correlationId: socket.sent[0].messageId,
    backendGeneration: runtime.generation,
    runtimeInstanceId: runtime.runtimeInstanceId,
  });
}

function pendingSnapshot(socket: FakeSocket) {
  return [...socket.sent].reverse().find(message => message.type === 'hud.snapshot.request')!;
}

describe('HudWebSocketDataSource', () => {
  it('discovers initial state and applies only contiguous updates', () => {
    const { source, socket } = setup();
    accept(socket);
    const request = pendingSnapshot(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3,
      subscriptionId: 'sub-a', hud: hud(12),
    });
    expect(source.snapshot()).toMatchObject({ freshness: 'CURRENT', subscriptionId: 'sub-a' });
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.update', backendGeneration: 3,
      subscriptionId: 'sub-a', previousHudRevision: 12, hud: hud(13),
    });
    expect(source.snapshot().hud?.hudRevision).toBe(13);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.update', backendGeneration: 3,
      subscriptionId: 'sub-a', previousHudRevision: 11, hud: hud(12),
    });
    expect(source.snapshot().hud?.hudRevision).toBe(13);
  });

  it('preserves high-water on same-backend reconnect and rejects stale snapshot', () => {
    const { source, socket, sockets } = setup();
    accept(socket);
    let request = pendingSnapshot(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-a', hud: hud(20),
    });
    socket.close();
    source.connect();
    const reconnect = sockets[1];
    reconnect.onopen?.();
    expect(reconnect.sent[0].lastSeen.hudRevision).toBe(20);
    accept(reconnect);
    expect(source.snapshot()).toMatchObject({ freshness: 'STALE', hud: { hudRevision: 20 } });
    request = pendingSnapshot(reconnect);
    reconnect.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-stale', hud: hud(18),
    });
    expect(source.snapshot()).toMatchObject({ freshness: 'STALE', hud: { hudRevision: 20 } });
    reconnect.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-new', hud: hud(20),
    });
    expect(source.snapshot()).toMatchObject({ freshness: 'CURRENT', subscriptionId: 'sub-new' });
  });

  it('uses discovery when reconnect snapshot reveals a new active context', () => {
    const { source, socket, sockets } = setup();
    accept(socket);
    let request = pendingSnapshot(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-a', hud: hud(20),
    });
    socket.close();
    source.connect();
    const reconnect = sockets[1];
    reconnect.onopen?.();
    accept(reconnect);
    request = pendingSnapshot(reconnect);
    reconnect.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'unaccepted',
      hud: hud(21, 'target-b', 'character-b'),
    });
    const discovery = pendingSnapshot(reconnect);
    expect(discovery.requestContext).toMatchObject({
      mode: 'DISCOVER_ACTIVE_CONTEXT', minimumHudRevision: 21,
    });
    expect(source.snapshot()).toMatchObject({ freshness: 'STALE', hud: { hudRevision: 20 } });
    reconnect.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: discovery.messageId, backendGeneration: 3, subscriptionId: 'sub-b',
      hud: hud(21, 'target-b', 'character-b'),
    });
    expect(source.snapshot()).toMatchObject({
      freshness: 'CURRENT', subscriptionId: 'sub-b', hud: { hudRevision: 21 },
    });
  });

  it('resets for a new backend identity and requests discovery from its revision space', () => {
    const { source, socket, sockets } = setup();
    accept(socket);
    let request = pendingSnapshot(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-a', hud: hud(20),
    });
    socket.close();
    source.connect();
    const reconnect = sockets[1];
    reconnect.onopen?.();
    accept(reconnect, { runtimeInstanceId: 'backend-b', generation: 4 });
    request = pendingSnapshot(reconnect);
    expect(source.snapshot()).toMatchObject({
      backend: { runtimeInstanceId: 'backend-b', generation: 4 }, hud: null, freshness: 'STARTUP',
    });
    expect(request.requestContext).toMatchObject({
      mode: 'DISCOVER_ACTIVE_CONTEXT', minimumHudRevision: 0,
    });
    reconnect.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.update', backendGeneration: 3,
      subscriptionId: 'sub-a', previousHudRevision: 20, hud: hud(21),
    });
    expect(source.snapshot().hud).toBeNull();
  });

  it('requests authoritative resync on a forward revision gap', () => {
    const { source, socket } = setup();
    accept(socket);
    const request = pendingSnapshot(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'sub-a', hud: hud(12),
    });
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.update', backendGeneration: 3,
      subscriptionId: 'sub-a', previousHudRevision: 13, hud: hud(14),
    });
    const resync = pendingSnapshot(socket);
    expect(source.snapshot()).toMatchObject({ freshness: 'STALE', hud: { hudRevision: 12 } });
    expect(resync.requestContext).toMatchObject({
      mode: 'RESYNC_KNOWN_CONTEXT', minimumHudRevision: 12,
    });
  });

  it('allows only server-listed valid target IDs and waits for committed HUD binding', () => {
    const { source, socket } = setup();
    accept(socket);
    const listRequest = socket.sent.find(message => message.type === 'target.list.request')!;
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'target.list.result', backendGeneration: 3,
      correlationId: listRequest.messageId,
      listRevision: 4,
      targets: [
        { targetId: 'target-a', validation: 'VALID', contentSha256: 'a'.repeat(64) },
        { targetId: 'target-b', validation: 'INVALID', contentSha256: 'b'.repeat(64) },
      ],
    });
    expect(() => source.selectTarget('target-b')).toThrow(/validated/);
    source.selectTarget('target-a');
    const select = socket.sent.find(message => message.type === 'target.select.request')!;
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'target.select.result', backendGeneration: 3,
      correlationId: select.messageId, status: 'ACTIVATED', targetId: 'target-a',
    });
    expect(source.snapshot().hud).toBeNull();
  });

  it('automatically reconnects with a bounded budget and never loops forever', () => {
    vi.useFakeTimers();
    const { source, socket, sockets } = setup([10, 20]);
    socket.close();
    vi.advanceTimersByTime(10);
    expect(sockets).toHaveLength(2);
    sockets[1].onopen?.();
    sockets[1].close();
    vi.advanceTimersByTime(20);
    expect(sockets).toHaveLength(3);
    sockets[2].onopen?.();
    sockets[2].close();
    vi.runAllTimers();
    expect(sockets).toHaveLength(3);
    expect(source.snapshot()).toMatchObject({
      freshness: 'STALE', error: 'RECONNECT_EXHAUSTED',
    });
  });

  it('rejects wrong handshake correlation and late messages from an old connection', () => {
    const { source, socket, sockets } = setup();
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hello.accepted', correlationId: 'wrong',
      backendGeneration: 3, runtimeInstanceId: 'backend-a',
    });
    expect(source.snapshot().backend).toBeNull();
    accept(socket);
    socket.close();
    source.connect();
    const reconnect = sockets[1];
    reconnect.onopen?.();
    accept(reconnect);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: pendingSnapshot(reconnect).messageId, backendGeneration: 3,
      subscriptionId: 'late-old-connection', hud: hud(99),
    });
    expect(source.snapshot().hud).toBeNull();
  });

  it('bounds snapshot timeout recovery and consumes late correlations', () => {
    vi.useFakeTimers();
    const { source, socket } = setup(undefined, {
      snapshotOperationTimeoutMs: 10, maxDiscoveryAttempts: 2,
    });
    accept(socket);
    const first = pendingSnapshot(socket);
    expect(first.requestContext).toMatchObject({
      mode: 'DISCOVER_ACTIVE_CONTEXT', attempt: 1, reason: 'INITIAL_CONNECTION',
    });
    vi.advanceTimersByTime(10);
    const retry = pendingSnapshot(socket);
    expect(retry.messageId).not.toBe(first.messageId);
    expect(retry.requestContext).toMatchObject({
      mode: 'DISCOVER_ACTIVE_CONTEXT', attempt: 2, reason: 'TIMEOUT_RETRY',
      minimumHudRevision: 0,
    });
    vi.advanceTimersByTime(10);
    expect(source.snapshot()).toMatchObject({
      freshness: 'STALE', error: 'SNAPSHOT_RECOVERY_EXHAUSTED', subscriptionId: null,
    });
    const requestCount = socket.sent.filter(message => message.type === 'hud.snapshot.request').length;
    vi.runAllTimers();
    expect(socket.sent.filter(message => message.type === 'hud.snapshot.request')).toHaveLength(requestCount);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: first.messageId, backendGeneration: 3,
      subscriptionId: 'late', hud: hud(99),
    });
    expect(source.snapshot().hud).toBeNull();
  });

  it('rejects a HUD payload that does not satisfy the versioned schema', () => {
    const { source, socket } = setup();
    accept(socket);
    const request = pendingSnapshot(socket);
    const invalid = hud(12);
    delete invalid.provenance;
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3,
      subscriptionId: 'sub-invalid', hud: invalid,
    });
    expect(source.snapshot()).toMatchObject({ hud: null, freshness: 'STALE', error: 'HUD_INVALID' });
    expect(pendingSnapshot(socket).messageId).not.toBe(request.messageId);
  });

  it.each([
    ['runtime instance', (value: Record<string, any>) => { value.context.binding.runtimeInstanceId = 'other'; }],
    ['character revision', (value: Record<string, any>) => { value.context.binding.currentRevision += 1; }],
    ['target hash', (value: Record<string, any>) => { value.context.binding.targetSha256 = 'c'.repeat(64); }],
    ['policy version', (value: Record<string, any>) => { value.context.binding.policyVersion = 'other-policy'; }],
  ])('rejects inconsistent %s binding without applying the assessment', (_label, mutate) => {
    const { source, socket } = setup();
    accept(socket);
    const request = pendingSnapshot(socket);
    const invalid = hud(12);
    mutate(invalid);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3,
      subscriptionId: 'sub-invalid', hud: invalid,
    });
    expect(source.snapshot()).toMatchObject({ hud: null, freshness: 'STALE', error: 'HUD_INVALID' });
  });

  it('rejects a HUD identity that disagrees with the accepted backend generation', () => {
    const { source, socket } = setup();
    accept(socket);
    const request = pendingSnapshot(socket);
    const invalid = hud(12);
    invalid.backend.generation = 2;
    invalid.context.binding.runtimeInstanceId = invalid.backend.runtimeInstanceId;
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3,
      subscriptionId: 'sub-invalid', hud: invalid,
    });
    expect(source.snapshot()).toMatchObject({ hud: null, freshness: 'STALE', error: 'HUD_INVALID' });
  });
});

function targets(socket: FakeSocket) {
  const request = socket.sent.find(m => m.type === 'target.list.request')!;
  socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'target.list.result',
    backendGeneration: 3, correlationId: request.messageId, listRevision: 1,
    targets: [{targetId: 'target-a', validation: 'VALID', contentSha256: 'a'.repeat(64)}]});
}

it('consumes correlated errors without accumulating pending selection or accepting late errors', () => {
  const {source, socket} = setup(); accept(socket); targets(socket);
  for (let i = 0; i < 100; i++) {
    source.selectTarget('target-a');
    const id = socket.sent.at(-1)!.messageId;
    socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
      correlationId: id, code: i % 2 ? 'TARGET_CHANGED' : 'TARGET_INVALID'});
    expect((source as any).pendingTarget.size).toBe(0);
  }
  const previous = source.snapshot().error;
  socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
    correlationId: 'unknown-or-duplicate', code: 'INTERNAL'});
  expect(source.snapshot().error).toBe(previous);
  source.disconnect();
});

it('bounds outstanding selections and clears connection-owned requests', () => {
  const {source, socket} = setup(); accept(socket); targets(socket);
  for (let i = 0; i < 32; i++) source.selectTarget('target-a');
  expect(() => source.selectTarget('target-a')).toThrow('TARGET_REQUEST_LIMIT');
  const first = socket.sent.find(m => m.type === 'target.select.request')!;
  socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'target.select.result',
    backendGeneration: 3, correlationId: first.messageId});
  expect((source as any).pendingTarget.size).toBe(31);
  source.disconnect();
  expect((source as any).pendingTarget.size).toBe(0);
});

it('old connection/generation errors do not complete a new selection', () => {
  vi.useFakeTimers();
  const {source, socket, sockets} = setup([1]); accept(socket); targets(socket);
  source.selectTarget('target-a');
  socket.close(); vi.advanceTimersByTime(1);
  const next = sockets[1]; next.onopen?.(); accept(next); targets(next);
  source.selectTarget('target-a');
  const id = next.sent.at(-1)!.messageId;
  const error = {protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
    correlationId: id, code: 'TARGET_INVALID'};
  socket.receive(error);
  next.receive({...error, backendGeneration: 2});
  expect((source as any).pendingTarget.size).toBe(1);
  next.receive(error);
  expect((source as any).pendingTarget.size).toBe(0);
  source.disconnect();
});
