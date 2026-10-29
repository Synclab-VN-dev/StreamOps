import { invoke } from '@tauri-apps/api/core';
import validateHudSchema from './hud-validator.generated';
import type { HudSnapshot, SelectionResult, TargetListEntry } from './hud-model';

export type SocketMessage = Record<string, unknown>;

const CONTRACT_REVISION = 'd4planner-r1-contract/1.0.0-candidate.5';

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
  assessmentRenderable: boolean;
  subscriptionId: string | null;
  targets: readonly Record<string, any>[];
  listRevision: number | null;
  error: string | null;
}

type PendingSnapshot = {
  requestId: string;
  mode: 'DISCOVER_ACTIVE_CONTEXT' | 'RESYNC_KNOWN_CONTEXT';
  minimumRevision: number;
  attempt: number;
  expectedContext?: Record<string, unknown>;
};

type PendingTargetSelection = {
  resolve: (result: SelectionResult) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

export class HudWebSocketDataSource {
  private socket: WebSocketLike | null = null;
  private sequence = 0;
  private pendingHello: string | null = null;
  private pendingTargetList: string | null = null;
  private pendingSnapshot: PendingSnapshot | null = null;
  private pendingTarget = new Map<string, PendingTargetSelection>();
  private readonly listeners = new Set<(state: HudDataState) => void>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private snapshotTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private state: HudDataState = {
    backend: null,
    hud: null,
    freshness: 'STARTUP',
    assessmentRenderable: false,
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
      snapshotOperationTimeoutMs?: number;
      maxDiscoveryAttempts?: number;
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
      this.clearSnapshotTimer();
      this.rejectPendingTargets('Backend connection closed before Target activation completed.');
      this.pendingTargetList = null;
      this.pendingHello = null;
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null, error: 'SOCKET_CLOSED' };
      this.pendingSnapshot = null;
      this.emit();
      this.scheduleReconnect();
    };
  }

  disconnect(): void {
    this.stopped = true;
    this.pendingTargetList = null;
    this.pendingHello = null;
    this.clearSnapshotTimer();
    this.rejectPendingTargets('Backend connection closed before Target activation completed.');
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

  selectTarget(targetId: string): Promise<SelectionResult> {
    this.requireBackend();
    const target = this.state.targets.find(item => item.targetId === targetId);
    if (!target || target.validation !== 'VALID' || typeof target.contentSha256 !== 'string') {
      throw new Error('Only a validated Target entry can be selected.');
    }
    if (this.state.listRevision === null) throw new Error('Target list is unavailable.');
    if (this.pendingTarget.size >= 32) throw new Error('TARGET_REQUEST_LIMIT');
    const messageId = this.id('select');
    const result = new Promise<SelectionResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingTarget.delete(messageId);
        reject(new Error('Target selection timed out.'));
      }, this.config.snapshotOperationTimeoutMs ?? 2_000);
      this.pendingTarget.set(messageId, { resolve, reject, timer });
    });
    try {
      this.send({
        ...this.envelope(messageId, 'target.select.request'),
        targetId,
        expectedSha256: target.contentSha256,
        expectedListRevision: this.state.listRevision,
      });
    } catch (error) {
      const pending = this.pendingTarget.get(messageId);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingTarget.delete(messageId);
      }
      throw error;
    }
    return result;
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
      const pending = this.pendingTarget.get(message.correlationId);
      if (!pending) return;
      this.pendingTarget.delete(message.correlationId);
      clearTimeout(pending.timer);
      // Activation acknowledgement never relabels the existing HUD. The next
      // committed HUD snapshot/update carries the new binding atomically.
      const status = String(message.status ?? 'REJECTED') as SelectionResult['status'];
      if (status === 'ACTIVATED') {
        pending.resolve({
          status,
          targetId: String(message.targetId),
          contentSha256: String(message.contentSha256),
          selectionRevision: Number(message.selectionRevision),
        });
      } else {
        pending.resolve({
          status: ['TARGET_CHANGED', 'TARGET_NOT_FOUND', 'TARGET_INVALID'].includes(status)
            ? status as 'TARGET_CHANGED' | 'TARGET_NOT_FOUND' | 'TARGET_INVALID'
            : 'REJECTED',
          targetId: String(message.targetId ?? ''),
          message: String(message.message ?? message.error?.message ?? status),
        });
      }
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
      const correlation = message.correlationId;
      if (correlation != null) {
        const selection = this.pendingTarget.get(correlation);
        if (selection) {
          this.pendingTarget.delete(correlation);
          clearTimeout(selection.timer);
          selection.reject(new Error(`${String(message.code ?? 'INTERNAL')}: ${String(message.message ?? 'Target selection rejected')}`));
        }
        const listing = correlation === this.pendingTargetList;
        if (listing) this.pendingTargetList = null;
        if (!selection && !listing && correlation !== this.pendingSnapshot?.requestId) return;
      }
      this.state = { ...this.state, error: String(message.code ?? 'INTERNAL') };
      this.emit();
    }
  }

  private acceptHello(message: Record<string, any>): void {
    this.clearSnapshotTimer();
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
        assessmentRenderable: false,
        subscriptionId: null,
        error: null,
      };
    }
    this.pendingSnapshot = null;
    this.pendingTargetList = null;
    this.rejectPendingTargets('Backend connection changed before Target activation completed.');
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

  private requestSnapshot(
    minimumOverride?: number,
    forceDiscovery = false,
    attempt = 1,
    discoveryReason?: 'KNOWN_CONTEXT_CHANGED' | 'TIMEOUT_RETRY',
  ): void {
    this.requireBackend();
    this.clearSnapshotTimer();
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
          reason: discoveryReason ?? (forceDiscovery ? 'KNOWN_CONTEXT_CHANGED' : 'INITIAL_CONNECTION'),
          attempt,
          runtimeInstanceId: this.state.backend!.runtimeInstanceId,
          minimumHudRevision: minimumRevision,
        };
    this.pendingSnapshot = {
      requestId: messageId,
      mode: requestContext.mode,
      minimumRevision,
      attempt: requestContext.mode === 'DISCOVER_ACTIVE_CONTEXT' ? requestContext.attempt : 0,
      ...('expectedContext' in requestContext ? { expectedContext: requestContext.expectedContext } : {}),
    };
    this.send({
      ...this.envelope(messageId, 'hud.snapshot.request'),
      requestContext,
    });
    const timeout = this.config.snapshotOperationTimeoutMs ?? 2_000;
    if (!(timeout > 0)) throw new Error('snapshotOperationTimeoutMs must be positive.');
    this.snapshotTimer = setTimeout(() => this.snapshotTimedOut(messageId), timeout);
  }

  private snapshotTimedOut(requestId: string): void {
    const pending = this.pendingSnapshot;
    if (!pending || pending.requestId !== requestId) return;
    this.snapshotTimer = null;
    this.pendingSnapshot = null;
    const nextAttempt = pending.attempt > 0 ? pending.attempt + 1 : 1;
    const maxAttempts = this.config.maxDiscoveryAttempts ?? 3;
    if (!(maxAttempts > 0) || nextAttempt > maxAttempts) {
      this.state = {
        ...this.state, freshness: 'STALE', subscriptionId: null,
        error: 'SNAPSHOT_RECOVERY_EXHAUSTED',
      };
      this.emit();
      return;
    }
    this.state = { ...this.state, freshness: 'STALE', subscriptionId: null };
    this.requestSnapshot(pending.minimumRevision, true, nextAttempt, 'TIMEOUT_RETRY');
    this.emit();
  }

  private clearSnapshotTimer(): void {
    if (this.snapshotTimer !== null) {
      clearTimeout(this.snapshotTimer);
      this.snapshotTimer = null;
    }
  }

  private rejectPendingTargets(message: string): void {
    for (const pending of this.pendingTarget.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error(message));
    }
    this.pendingTarget.clear();
  }

  private acceptSnapshot(message: Record<string, any>): void {
    const pending = this.pendingSnapshot;
    if (!pending || message.correlationId !== pending.requestId || message.authoritative !== true) return;
    const revision = message.hud?.hudRevision;
    const highWater = this.state.hud?.hudRevision ?? -1;
    if (!Number.isInteger(revision) || revision < highWater || revision < pending.minimumRevision) return;
    if (!this.validHud(message.hud)) {
      this.pendingSnapshot = null;
      this.clearSnapshotTimer();
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null, error: 'HUD_INVALID' };
      const nextAttempt = pending.attempt > 0 ? pending.attempt + 1 : 1;
      if (nextAttempt <= (this.config.maxDiscoveryAttempts ?? 3)) {
        this.requestSnapshot(pending.minimumRevision, true, nextAttempt, 'TIMEOUT_RETRY');
      }
      this.emit();
      return;
    }
    if (pending.mode === 'RESYNC_KNOWN_CONTEXT'
        && !sameContext(contextKey(message.hud?.context), pending.expectedContext)) {
      this.pendingSnapshot = null;
      this.clearSnapshotTimer();
      // Only the snapshot operation is superseded. Target commands on this
      // authenticated connection still require their correlated terminal reply.
      this.state = { ...this.state, freshness: 'STALE', assessmentRenderable: false, subscriptionId: null };
      // Do not apply the mismatched snapshot. Discover the authoritative active
      // context using its revision as the new anti-rollback floor.
      this.requestSnapshot(revision, true);
      this.emit();
      return;
    }
    this.pendingSnapshot = null;
    this.clearSnapshotTimer();
    this.reconnectAttempt = 0;
    this.state = {
      ...this.state,
      hud: structuredClone(message.hud),
      freshness: 'CURRENT',
      assessmentRenderable: true,
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
    if (!this.validHud(message.hud)) {
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null, error: 'HUD_INVALID' };
      this.requestSnapshot();
      this.emit();
      return;
    }
    if (message.previousHudRevision !== current) {
      this.state = { ...this.state, freshness: 'STALE', subscriptionId: null };
      this.requestSnapshot();
      this.emit();
      return;
    }
    this.state = { ...this.state, hud: structuredClone(message.hud), freshness: 'CURRENT' };
    this.emit();
  }

  private validHud(hud: unknown): hud is Record<string, any> {
    if (!validateHudSchema(hud) || !this.state.backend || !hud || typeof hud !== 'object') return false;
    const value = hud as Record<string, any>;
    if (value.backend.runtimeInstanceId !== this.state.backend.runtimeInstanceId
        || value.backend.generation !== this.state.backend.generation
        || value.provenance.assessmentVersion !== CONTRACT_REVISION) return false;
    const context = value.context;
    if (context.state === 'BOUND') {
      const { binding, character, target } = context;
      return binding.runtimeInstanceId === value.backend.runtimeInstanceId
        && binding.characterId === character.characterId
        && binding.currentRevision === character.currentRevision
        && binding.targetId === target.targetId
        && binding.targetSha256 === target.contentSha256
        && binding.selectionRevision === target.selectionRevision
        && binding.policyVersion === target.policyVersion;
    }
    return context.binding === null
      && value.score.status === 'NO_DATA'
      && value.equipment.length === 0;
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

export type HudDataEvent =
  | { type: "CONNECTION"; state: "CONNECTED" | "DISCONNECTED"; reason?: string }
  | { type: "ASSESSMENT_INVALIDATED" }
  | { type: "SNAPSHOT"; snapshot: HudSnapshot }
  | { type: "TARGETS"; targets: TargetListEntry[] };

export interface IHudDataSource {
  connect(listener: (event: HudDataEvent) => void): Promise<() => void>;
  refreshTargets(): Promise<void>;
  selectTarget(request: { targetId: string; expectedSha256: string }): Promise<SelectionResult>;
}

declare global {
  interface Window {
    __D4PLANNER_HUD_DATA_SOURCE__?: IHudDataSource;
  }
}

type NativeHudBootstrap = { endpoint: string; credential: string; origin: string };
type NativeBackendStatus = { state: 'STOPPED' | 'STARTING' | 'READY' | 'STOPPING' | 'EXITED' | 'FAILED' };

export class TauriHudDataSource implements IHudDataSource {
  private source: HudWebSocketDataSource | null = null;
  private unsubscribe: (() => void) | null = null;
  private listener: ((event: HudDataEvent) => void) | null = null;
  private recoveryEpoch = 0;
  private recovering: Promise<void> | null = null;

  constructor(
    private readonly nativeInvoke: typeof invoke = invoke,
    private readonly socketFactory: (endpoint: string) => WebSocketLike =
      endpoint => new WebSocket(endpoint) as unknown as WebSocketLike,
    private readonly recoveryDelaysMs: readonly number[] = [0, 100, 250, 500, 1_000],
  ) {}

  async connect(listener: (event: HudDataEvent) => void): Promise<() => void> {
    if (this.source) throw new Error('HUD data source is already connected.');
    this.listener = listener;
    this.recoveryEpoch += 1;
    await this.connectFromNativeBootstrap(this.recoveryEpoch);
    return () => {
      this.recoveryEpoch += 1;
      this.listener = null;
      this.unsubscribe?.();
      this.unsubscribe = null;
      this.source?.disconnect();
      this.source = null;
      this.recovering = null;
    };
  }

  private async connectFromNativeBootstrap(epoch: number): Promise<void> {
    const bootstrap = await this.nativeInvoke<NativeHudBootstrap>('get_hud_ws_bootstrap');
    if (epoch !== this.recoveryEpoch || this.listener === null) return;
    if (!bootstrap.endpoint.startsWith('ws://') || bootstrap.credential.length < 32) {
      throw new Error('Native Backend returned an invalid WebSocket bootstrap.');
    }
    const source = new HudWebSocketDataSource({
      ...bootstrap,
      socketFactory: this.socketFactory,
    });
    this.source = source;
    let lastRevision: number | null = null;
    let lastListRevision: number | null = null;
    let connected = false;
    this.unsubscribe = source.subscribe(state => {
      // Target operation errors do not invalidate the authenticated transport.
      const wasConnected = connected;
      if (!state.assessmentRenderable) this.listener?.({ type: 'ASSESSMENT_INVALIDATED' });
      const isConnected = state.backend !== null && state.freshness === 'CURRENT'
        && (state.error === null || state.error.startsWith('TARGET_'));
      if (isConnected !== connected) {
        connected = isConnected;
        this.listener?.(isConnected
          ? { type: 'CONNECTION', state: 'CONNECTED' }
          : { type: 'CONNECTION', state: 'DISCONNECTED', reason: state.error ?? 'Backend handshake pending' });
      }
      if (state.listRevision !== null && state.listRevision !== lastListRevision) {
        lastListRevision = state.listRevision;
        this.listener?.({ type: 'TARGETS', targets: structuredClone(state.targets) as TargetListEntry[] });
      }
      if (state.freshness === 'CURRENT' && state.hud && (state.hud.hudRevision !== lastRevision || !wasConnected)) {
        lastRevision = state.hud.hudRevision;
        this.listener?.({ type: 'SNAPSHOT', snapshot: structuredClone(state.hud) as HudSnapshot });
      }
      if (state.freshness === 'STALE' && connected) {
        connected = false;
        this.listener?.({ type: 'CONNECTION', state: 'DISCONNECTED', reason: state.error ?? 'Resynchronizing Backend state' });
      }
      if ((state.error === 'SOCKET_CLOSED' || state.error === 'RECONNECT_EXHAUSTED') && !this.recovering) {
        this.recovering = this.rediscoverBackend(epoch).finally(() => { this.recovering = null; });
      }
    });
    source.connect();
  }

  private async rediscoverBackend(epoch: number): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.source?.disconnect();
    this.source = null;
    for (const delay of this.recoveryDelaysMs) {
      if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
      if (epoch !== this.recoveryEpoch || this.listener === null) return;
      try {
        const status = await this.nativeInvoke<NativeBackendStatus>('get_backend_status');
        if (status.state === 'FAILED' || status.state === 'EXITED' || status.state === 'STOPPED') {
          await this.nativeInvoke<NativeBackendStatus>('restart_backend');
        }
        await this.connectFromNativeBootstrap(epoch);
        return;
      } catch {
        // Backend restart and READY are bounded by the native wrapper. Retry
        // bootstrap discovery, never the HUD data itself.
      }
    }
    this.listener?.({ type: 'CONNECTION', state: 'DISCONNECTED', reason: 'BACKEND_REDISCOVERY_EXHAUSTED' });
  }

  async refreshTargets(): Promise<void> {
    if (!this.source) throw new Error('Backend WebSocket data source is not connected.');
    this.source.requestTargets();
  }

  async selectTarget(request: { targetId: string; expectedSha256: string }): Promise<SelectionResult> {
    if (!this.source) throw new Error('Backend WebSocket data source is not connected.');
    const target = this.source.snapshot().targets.find(item => item.targetId === request.targetId);
    if (!target || target.contentSha256 !== request.expectedSha256) {
      return { status: 'TARGET_CHANGED', targetId: request.targetId, message: 'Target list/hash changed before activation.' };
    }
    return this.source.selectTarget(request.targetId);
  }
}

let productionSource: IHudDataSource | null = null;

/** Native bootstrap + strict S5 WebSocket validation; never substitutes demo data. */
export function productionHudDataSource(): IHudDataSource {
  if (window.__D4PLANNER_HUD_DATA_SOURCE__) return window.__D4PLANNER_HUD_DATA_SOURCE__;
  productionSource ??= new TauriHudDataSource();
  return productionSource;
}
