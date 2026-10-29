import { afterEach, describe, expect, it, vi } from 'vitest';
import { HudWebSocketDataSource, TauriHudDataSource, type WebSocketLike } from './hud-data-source';
import type { invoke } from '@tauri-apps/api/core';
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
    void source.selectTarget('target-a').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
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
  for (let i = 0; i < 32; i++) void source.selectTarget('target-a').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
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
  void source.selectTarget('target-a').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
  socket.close(); vi.advanceTimersByTime(1);
  const next = sockets[1]; next.onopen?.(); accept(next); targets(next);
  void source.selectTarget('target-a').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
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

it.each(['TARGET_CHANGED', 'TARGET_INVALID', 'success', 'list'])(
  'preserves Target correlations during same-connection context rediscovery: %s', outcome => {
    const successful = outcome === 'success' || outcome === 'list';
    vi.useFakeTimers();
    const { source, socket, sockets } = setup([1]);
    accept(socket);
    socket.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: pendingSnapshot(socket).messageId, backendGeneration: 3,
      subscriptionId: 'initial', hud: hud(20),
    });
    socket.close(); vi.advanceTimersByTime(1);
    const reconnected = sockets[1];
    reconnected.onopen?.(); accept(reconnected);
    const resync = pendingSnapshot(reconnected);
    expect(resync.requestContext).toMatchObject({mode: 'RESYNC_KNOWN_CONTEXT', minimumHudRevision: 20});
    const listReply = {
      protocolVersion: 'd4planner-ws/v1', type: 'target.list.result', backendGeneration: 3,
      correlationId: reconnected.sent.find(m => m.type === 'target.list.request')!.messageId,
      listRevision: 1,
      targets: [{targetId: 'target-b', validation: 'VALID', contentSha256: 'b'.repeat(64)}],
    };
    reconnected.receive(listReply);
    void source.selectTarget('target-b').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
    const selectionId = reconnected.sent.at(-1)!.messageId;
    source.requestTargets();
    const listId = reconnected.sent.at(-1)!.messageId;
    reconnected.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: resync.messageId, backendGeneration: 3,
      subscriptionId: 'mismatched', hud: hud(21, 'target-b', 'character-b'),
    });
    const discovery = pendingSnapshot(reconnected);
    expect(discovery.requestContext).toMatchObject({mode: 'DISCOVER_ACTIVE_CONTEXT', minimumHudRevision: 21});
    expect(source.snapshot()).toMatchObject({freshness: 'STALE', assessmentRenderable: false, subscriptionId: null,
      hud: {hudRevision: 20, context: {target: {targetId: 'target-a'}}}});
    const response = {
      protocolVersion: 'd4planner-ws/v1', backendGeneration: 3, correlationId: selectionId,
      ...(successful ? {type: 'target.select.result', status: 'ACTIVATED', targetId: 'target-b'}
        : {type: 'error', code: outcome}),
    };
    socket.receive(response);
    reconnected.receive({...response, backendGeneration: 2});
    socket.receive({...listReply, correlationId: listId, listRevision: 99});
    reconnected.receive({...listReply, correlationId: listId, backendGeneration: 2, listRevision: 99});
    expect(source.snapshot().listRevision).toBe(1);
    expect(source.snapshot().error).toBeNull();
    if (outcome === 'list') {
      reconnected.receive({...listReply, correlationId: listId, listRevision: 2});
      expect(source.snapshot().listRevision).toBe(2);
    }
    if (successful) expect((source as any).pendingTarget.has(selectionId)).toBe(true);
    reconnected.receive(response);
    // Correlated command errors are settled on their Promise, never transport health.
    expect(source.snapshot().error).toBeNull();
    expect((source as any).pendingTarget.size).toBe(0);
    reconnected.receive({...listReply, correlationId: listId, listRevision: 2});
    expect(source.snapshot().listRevision).toBe(2);
    // Command response cannot relabel the old assessment as B.
    expect(source.snapshot().hud?.context.target.targetId).toBe('target-a');
    reconnected.receive({...response, type: 'error', code: 'INTERNAL'});
    reconnected.receive({...listReply, correlationId: listId, listRevision: 99});
    // Correlated command errors are settled on their Promise, never transport health.
    expect(source.snapshot().error).toBeNull();
    expect(source.snapshot().listRevision).toBe(2);
    const discovered = {protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: discovery.messageId, backendGeneration: 3, subscriptionId: 'discovered'};
    reconnected.receive({...discovered, hud: hud(20)});
    expect(source.snapshot().freshness).toBe('STALE');
    reconnected.receive({...discovered, hud: hud(21, 'target-b', 'character-b')});
    expect(source.snapshot()).toMatchObject({freshness: 'CURRENT', subscriptionId: 'discovered',
      hud: {hudRevision: 21, context: {target: {targetId: 'target-b'}}}});
    for (let i = 0; i < 32; i++) void source.selectTarget('target-b').catch(error => { expect(error.message).toMatch(/TARGET_CHANGED|TARGET_INVALID|Backend connection/); });
    expect(() => source.selectTarget('target-b')).toThrow('TARGET_REQUEST_LIMIT');
    source.disconnect();
    expect((source as any).pendingTarget.size).toBe(0);
    expect((source as any).pendingTargetList).toBeNull();
  },
);
describe('TauriHudDataSource backend rediscovery', () => {
  it('drops the old transport and authenticates against a restarted Backend bootstrap', async () => {
    const sockets: { endpoint: string; socket: FakeSocket }[] = [];
    const calls: string[] = [];
    let bootstrapReads = 0;
    const nativeInvoke = (async (command: string) => {
      calls.push(command);
      if (command === 'get_hud_ws_bootstrap') {
        bootstrapReads += 1;
        return bootstrapReads === 1
          ? { endpoint: 'ws://127.0.0.1:31001', credential: 'a'.repeat(64), origin: 'tauri://localhost' }
          : { endpoint: 'ws://127.0.0.1:31002', credential: 'b'.repeat(64), origin: 'tauri://localhost' };
      }
      if (command === 'get_backend_status') return { state: 'FAILED' };
      if (command === 'restart_backend') return { state: 'READY' };
      throw new Error(`unexpected native command ${command}`);
    }) as typeof invoke;
    const events: Record<string, any>[] = [];
    const source = new TauriHudDataSource(
      nativeInvoke,
      endpoint => {
        const socket = new FakeSocket();
        sockets.push({ endpoint, socket });
        return socket;
      },
      [0],
    );
    const dispose = await source.connect(event => events.push(event));
    const first = sockets[0].socket;
    first.onopen?.();
    accept(first);
    let request = pendingSnapshot(first);
    first.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 3, subscriptionId: 'old-sub', hud: hud(20),
    });
    targets(first);
    const selection = source.selectTarget({targetId: 'target-a', expectedSha256: 'a'.repeat(64)});
    const rejected = expect(selection).rejects.toThrow('TARGET_INVALID');
    const eventCount = events.length;
    first.receive({protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
      correlationId: first.sent.at(-1)!.messageId, code: 'TARGET_INVALID', message: 'Invalid target'});
    await rejected;
    expect(events.slice(eventCount).some(event => event.type === 'CONNECTION' && event.state === 'DISCONNECTED')).toBe(false);
    first.close();
    await vi.waitFor(() => expect(sockets).toHaveLength(2));
    expect(sockets.map(item => item.endpoint)).toEqual([
      'ws://127.0.0.1:31001', 'ws://127.0.0.1:31002',
    ]);
    expect(calls).toContain('restart_backend');
    const second = sockets[1].socket;
    second.onopen?.();
    expect(second.sent[0].credential).toBe('b'.repeat(64));
    const restarted = { runtimeInstanceId: 'backend-b', generation: 4 };
    accept(second, restarted);
    request = pendingSnapshot(second);
    const nextHud = hud(1);
    nextHud.backend = restarted;
    nextHud.context.binding.runtimeInstanceId = restarted.runtimeInstanceId;
    second.receive({
      protocolVersion: 'd4planner-ws/v1', type: 'hud.snapshot', authoritative: true,
      correlationId: request.messageId, backendGeneration: 4, subscriptionId: 'new-sub', hud: nextHud,
    });
    expect(events.at(-1)).toMatchObject({
      type: 'SNAPSHOT', snapshot: { backend: restarted, hudRevision: 1 },
    });
    expect(events.some(event => event.type === 'CONNECTION' && event.state === 'DISCONNECTED')).toBe(true);
    dispose();
  });
});

it('settles a correlated terminal Target error immediately and cancels its timeout', async () => {
  vi.useFakeTimers();
  const {source, socket} = setup(); accept(socket); targets(socket);
  const result = source.selectTarget('target-a');
  const settled = vi.fn();
  void result.then(settled, settled);
  const id = socket.sent.at(-1)!.messageId;
  socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
    correlationId: id, code: 'TARGET_CHANGED', message: 'Target changed after listing'});
  await Promise.resolve();
  expect(settled).toHaveBeenCalledTimes(1);
  expect(settled.mock.calls[0][0].message).toContain('TARGET_CHANGED');
  socket.receive({protocolVersion: 'd4planner-ws/v1', type: 'error', backendGeneration: 3,
    correlationId: id, code: 'INTERNAL'});
  vi.advanceTimersByTime(2001);
  expect(settled).toHaveBeenCalledTimes(1);
  source.disconnect();
});

it('keeps list failures and timeouts separate from transport and bounds superseded list requests', () => {
  vi.useFakeTimers();
  const {source, socket} = setup(); accept(socket); targets(socket);
  const request = pendingSnapshot(socket);
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'hud.snapshot',authoritative:true,
    correlationId:request.messageId,backendGeneration:3,subscriptionId:'sub-a',hud:hud(12)});
  source.requestTargets();
  const oldId = socket.sent.at(-1)!.messageId;
  source.requestTargets();
  const id = socket.sent.at(-1)!.messageId;
  const error = {protocolVersion:'d4planner-ws/v1',type:'error',backendGeneration:3,
    correlationId:id,code:'TARGET_INVALID',message:'Listing unavailable'};
  socket.receive({...error,correlationId:oldId});
  socket.receive({...error,backendGeneration:2});
  expect(source.snapshot().targetListStatus).toBe('LOADING');
  socket.receive(error);
  expect(source.snapshot()).toMatchObject({error:null,freshness:'CURRENT',targetListStatus:'ERROR',
    targetListError:'TARGET_INVALID: Listing unavailable',targets:[],listRevision:null});
  expect((source as any).pendingTargetList).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  source.requestTargets();
  const retry = socket.sent.at(-1)!.messageId;
  socket.receive({...error,code:'INTERNAL'}); // Late prior operation cannot end the retry.
  expect(source.snapshot().targetListStatus).toBe('LOADING');
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'target.list.result',backendGeneration:3,
    correlationId:retry,listRevision:1,targets:[]});
  expect(source.snapshot()).toMatchObject({targetListStatus:'READY',targetListError:null,targets:[],error:null});
  source.requestTargets();
  vi.advanceTimersByTime(2001);
  expect(source.snapshot()).toMatchObject({error:null,freshness:'CURRENT',targetListStatus:'ERROR',targetListError:'Target listing timed out.'});
  source.requestTargets();
  source.disconnect();
  expect((source as any).pendingTargetList).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  expect(source.snapshot().error).toBe('SOCKET_CLOSED');
});

it('binds local receipt telemetry to the accepted revision, never a stale or wrong-generation message', () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-29T01:00:00Z'));
  const { source, socket } = setup();
  accept(socket);
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'hud.snapshot',authoritative:true,
    correlationId:pendingSnapshot(socket).messageId,backendGeneration:3,subscriptionId:'telemetry',hud:hud(12)});
  expect(source.snapshot().hudReceivedAt).toBe('2026-10-29T01:00:00.000Z');
  vi.setSystemTime(new Date('2026-10-29T01:00:01Z'));
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'hud.update',backendGeneration:4,
    subscriptionId:'telemetry',previousHudRevision:12,hud:hud(13)});
  expect(source.snapshot().hudReceivedAt).toBe('2026-10-29T01:00:00.000Z');
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'hud.update',backendGeneration:3,
    subscriptionId:'telemetry',previousHudRevision:11,hud:hud(12)});
  expect(source.snapshot().hudReceivedAt).toBe('2026-10-29T01:00:00.000Z');
  socket.receive({protocolVersion:'d4planner-ws/v1',type:'hud.update',backendGeneration:3,
    subscriptionId:'telemetry',previousHudRevision:12,hud:hud(13)});
  expect(source.snapshot().hudReceivedAt).toBe('2026-10-29T01:00:01.000Z');
  expect(source.snapshot().hud).not.toHaveProperty('hudReceivedAt');
  source.disconnect();
});
