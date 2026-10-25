import { afterEach, describe, expect, it, vi } from 'vitest';
import { HudWebSocketDataSource, type WebSocketLike } from './hud-data-source';

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
  return {
    hudRevision: revision,
    context: {
      state: 'BOUND',
      character: { characterId },
      target: { targetId, selectionRevision: targetId === 'target-a' ? 7 : 8 },
    },
    score: { status: 'SCORED', value: targetId === 'target-a' ? 50 : 75 },
  };
}

function setup(reconnectDelaysMs?: readonly number[]) {
  const sockets: FakeSocket[] = [];
  const source = new HudWebSocketDataSource({
    endpoint: 'ws://127.0.0.1:12345',
    credential,
    origin: 'tauri://localhost',
    reconnectDelaysMs,
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
});
