export type SocketMessage = Record<string, unknown>;

export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export interface HudDataState {
  backend: { runtimeInstanceId: string; generation: number } | null;
  hud: Record<string, any> | null;
  freshness: 'STARTUP' | 'STALE' | 'CURRENT';
  subscriptionId: string | null;
  targets: readonly Record<string, any>[];
  listRevision: number | null;
  error: string | null;
}

type PendingSnapshot = {
  requestId: string;
  mode: 'DISCOVER_ACTIVE_CONTEXT' | 'RESYNC_KNOWN_CONTEXT';
  minimumRevision: number;
  expectedContext?: Record<string, unknown>;
};

export class HudWebSocketDataSource {
  private socket: WebSocketLike | null = null;
  private sequence = 0;
  private pendingHello: string | null = null;
  private pendingTargetList: string | null = null;
  private pendingSnapshot: PendingSnapshot | null = null;
  private pendingTarget = new Set<string>();
  private readonly listeners = new Set<(state: HudDataState) => void>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private state: HudDataState = {
    backend: null,
    hud: null,
    freshness: 'STARTUP',
    subscriptionId: null,
    targets: [],
    listRevision: null,
    error: null,
  };

  constructor(
    private readonly config: {
      endpoint: string;
      credential: string;
      origin: string;
      socketFactory: (endpoint: string) => WebSocketLike;
      reconnectDelaysMs?: readonly number[];
    },
  ) {}

  subscribe(listener: (state: HudDataState) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  snapshot(): HudDataState {
    return structuredClone(this.state);
  }

  connect(): void {
    if (this.socket && this.socket.readyState < 2) return;
    this.stopped = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.config.socketFactory(this.config.endpoint);
    this.socket = socket;
    socket.onopen = () => {
      const messageId = this.id('hello');
      this.pendingHello = messageId;
      this.send({
        protocolVersion: 'd4planner-ws/v1',
        messageId,
        type: 'hello',
        correlationId: null,
        backendGeneration: this.state.backend?.generation ?? 1,
        credential: this.config.credential,
        origin: this.config.origin,
        lastSeen: { hudRevision: this.state.hud?.hudRevision ?? null },
      });
    };
    socket.onmessage = event => {
      if (socket !== this.socket) return;
      try {
        const message: unknown = JSON.parse(event.data);
        if (message && typeof message === 'object') this.receive(message as Record<string, any>);
      } catch {
        this.state = { ...this.state, error: 'INVALID_MESSAGE' };
        this.emit();
      }
    };
    socket.onclose = () => {
      if (socket !== this.socket) return;
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null };
      this.pendingSnapshot = null;
      this.emit();
      this.scheduleReconnect();
    };
  }

  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  requestTargets(): void {
    this.requireBackend();
    const messageId = this.id('targets');
    this.pendingTargetList = messageId;
    this.send(this.envelope(messageId, 'target.list.request'));
  }

  selectTarget(targetId: string): void {
    this.requireBackend();
    const target = this.state.targets.find(item => item.targetId === targetId);
    if (!target || target.validation !== 'VALID' || typeof target.contentSha256 !== 'string') {
      throw new Error('Only a validated Target entry can be selected.');
    }
    if (this.state.listRevision === null) throw new Error('Target list is unavailable.');
    const messageId = this.id('select');
    this.pendingTarget.add(messageId);
    this.send({
      ...this.envelope(messageId, 'target.select.request'),
      targetId,
      expectedSha256: target.contentSha256,
      expectedListRevision: this.state.listRevision,
    });
  }

  private receive(message: Record<string, any>): void {
    if (message.protocolVersion !== 'd4planner-ws/v1') return;
    if (message.type === 'hello.accepted') {
      if (message.correlationId !== this.pendingHello) return;
      this.pendingHello = null;
      this.acceptHello(message);
      this.requestTargets();
      this.requestSnapshot();
      return;
    }
    if (!this.state.backend || message.backendGeneration !== this.state.backend.generation) return;
    if (message.type === 'target.list.result') {
      if (message.correlationId !== this.pendingTargetList) return;
      this.pendingTargetList = null;
      this.state = {
        ...this.state,
        targets: structuredClone(message.targets),
        listRevision: message.listRevision,
      };
      this.emit();
      return;
    }
    if (message.type === 'target.select.result') {
      if (!this.pendingTarget.delete(message.correlationId)) return;
      // Activation acknowledgement never relabels the existing HUD. The next
      // committed HUD snapshot/update carries the new binding atomically.
      return;
    }
    if (message.type === 'hud.snapshot') {
      this.acceptSnapshot(message);
      return;
    }
    if (message.type === 'hud.update') {
      this.acceptUpdate(message);
      return;
    }
    if (message.type === 'resync.required') {
      this.requestSnapshot();
      return;
    }
    if (message.type === 'error') {
      this.state = { ...this.state, error: String(message.code ?? 'INTERNAL') };
      this.emit();
    }
  }

  private acceptHello(message: Record<string, any>): void {
    const sameBackend = this.state.backend?.runtimeInstanceId === message.runtimeInstanceId
      && this.state.backend?.generation === message.backendGeneration;
    if (sameBackend) {
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null, error: null };
    } else {
      this.state = {
        ...this.state,
        backend: { runtimeInstanceId: message.runtimeInstanceId, generation: message.backendGeneration },
        hud: null,
        freshness: 'STARTUP',
        subscriptionId: null,
        error: null,
      };
    }
    this.pendingSnapshot = null;
    this.pendingTargetList = null;
    this.pendingTarget.clear();
    this.emit();
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return;
    const delays = this.config.reconnectDelaysMs ?? [100, 250, 500, 1_000, 2_000];
    if (this.reconnectAttempt >= delays.length) {
      this.state = { ...this.state, error: 'RECONNECT_EXHAUSTED', freshness: 'STALE' };
      this.emit();
      return;
    }
    const delay = delays[this.reconnectAttempt++];
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.socket = null;
      this.connect();
    }, delay);
  }

  private requestSnapshot(minimumOverride?: number, forceDiscovery = false): void {
    this.requireBackend();
    const minimumRevision = Math.max(this.state.hud?.hudRevision ?? 0, minimumOverride ?? 0);
    const context = this.state.hud?.context;
    const messageId = this.id('snapshot');
    const requestContext = context && !forceDiscovery
      ? {
          mode: 'RESYNC_KNOWN_CONTEXT' as const,
          runtimeInstanceId: this.state.backend!.runtimeInstanceId,
          minimumHudRevision: minimumRevision,
          expectedContext: contextKey(context),
        }
      : {
          mode: 'DISCOVER_ACTIVE_CONTEXT' as const,
          reason: forceDiscovery ? 'KNOWN_CONTEXT_CHANGED' : 'INITIAL_CONNECTION',
          attempt: 1,
          runtimeInstanceId: this.state.backend!.runtimeInstanceId,
          minimumHudRevision: minimumRevision,
        };
    this.pendingSnapshot = {
      requestId: messageId,
      mode: requestContext.mode,
      minimumRevision,
      ...('expectedContext' in requestContext ? { expectedContext: requestContext.expectedContext } : {}),
    };
    this.send({
      ...this.envelope(messageId, 'hud.snapshot.request'),
      requestContext,
    });
  }

  private acceptSnapshot(message: Record<string, any>): void {
    const pending = this.pendingSnapshot;
    if (!pending || message.correlationId !== pending.requestId || message.authoritative !== true) return;
    const revision = message.hud?.hudRevision;
    const highWater = this.state.hud?.hudRevision ?? -1;
    if (!Number.isInteger(revision) || revision < highWater || revision < pending.minimumRevision) return;
    if (pending.mode === 'RESYNC_KNOWN_CONTEXT'
        && !sameContext(contextKey(message.hud?.context), pending.expectedContext)) {
      this.pendingSnapshot = null;
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null };
      // Do not apply the mismatched snapshot. Discover the authoritative active
      // context using its revision as the new anti-rollback floor.
      this.requestSnapshot(revision, true);
      this.emit();
      return;
    }
    this.pendingSnapshot = null;
    this.reconnectAttempt = 0;
    this.state = {
      ...this.state,
      hud: structuredClone(message.hud),
      freshness: 'CURRENT',
      subscriptionId: message.subscriptionId,
      error: null,
    };
    this.emit();
  }

  private acceptUpdate(message: Record<string, any>): void {
    const current = this.state.hud?.hudRevision;
    const next = message.hud?.hudRevision;
    if (message.subscriptionId !== this.state.subscriptionId || !Number.isInteger(next)) return;
    if (current === undefined || next <= current) return;
    if (message.previousHudRevision !== current) {
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null };
      this.requestSnapshot();
      this.emit();
      return;
    }
    this.state = { ...this.state, hud: structuredClone(message.hud), freshness: 'CURRENT' };
    this.emit();
  }

  private envelope(messageId: string, type: string): SocketMessage {
    return {
      protocolVersion: 'd4planner-ws/v1',
      messageId,
      type,
      correlationId: null,
      backendGeneration: this.state.backend!.generation,
    };
  }

  private requireBackend(): void {
    if (!this.state.backend) throw new Error('Backend handshake is not complete.');
  }

  private send(message: SocketMessage): void {
    if (!this.socket || this.socket.readyState !== 1) throw new Error('WebSocket is not open.');
    this.socket.send(JSON.stringify(message));
  }

  private id(prefix: string): string {
    this.sequence += 1;
    return `${prefix}-${this.sequence}`;
  }

  private emit(): void {
    const snapshot = this.snapshot();
    this.listeners.forEach(listener => listener(snapshot));
  }
}

function contextKey(context: Record<string, any> | undefined): Record<string, unknown> {
  return {
    state: context?.state ?? 'STARTUP',
    characterId: context?.character?.characterId ?? null,
    targetId: context?.target?.targetId ?? null,
    selectionRevision: context?.target?.selectionRevision ?? null,
  };
}

function sameContext(actual: Record<string, unknown>, expected?: Record<string, unknown>): boolean {
  return expected !== undefined && JSON.stringify(actual) === JSON.stringify(expected);
}
