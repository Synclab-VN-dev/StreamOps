import { invoke } from '@tauri-apps/api/core';
import validateHudSchema from './hud-validator.generated';
import type { HudSnapshot, SelectionResult, TargetListEntry } from './hud-model';

export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  send(data: string): void;
  close(): void;
}
export type HudDataEvent =
  | { type: 'CONNECTION'; state: 'CONNECTED' | 'DISCONNECTED'; reason?: string }
  | { type: 'ASSESSMENT_INVALIDATED' }
  | { type: 'DATABASE_RESET' }
  | { type: 'SNAPSHOT'; snapshot: HudSnapshot; receivedAt?: string }
  | { type: 'TARGETS'; targets: TargetListEntry[] }
  | { type: 'TARGET_LIST_STATE'; status: 'IDLE' | 'LOADING' | 'READY' | 'ERROR'; error: string | null };
export interface IHudDataSource {
  connect(listener: (event: HudDataEvent) => void): Promise<() => void>;
  refreshTargets(): Promise<void>;
  refresh?(): Promise<void>;
  selectTarget(request: { targetId: string; expectedSha256: string }): Promise<SelectionResult>;
}
declare global { interface Window { __D4PLANNER_HUD_DATA_SOURCE__?: IHudDataSource; } }
type ReadModel = { schemaVersion: string; dbId: string; epoch: string; hudRevision: number; hud: HudSnapshot };
type Bootstrap = { endpoint: string; credential: string; origin: string };
type BackendStatus = { state: string; ready?: { childInstanceId: string; generation: number } };

/** D5: authoritative native DB reads; WS only requests a new read. */
export class TauriHudDataSource implements IHudDataSource {
  private listener: ((event: HudDataEvent) => void) | null = null;
  private socket: WebSocketLike | null = null;
  private epoch = 0;
  private checkpoint: { dbId: string; epoch: string; revision: number } | null = null;
  private readChain: Promise<void> = Promise.resolve();
  private online = false;
  private targets: TargetListEntry[] = [];
  private listRevision: number | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retry = 0;
  private recoveryInFlight = false;

  constructor(private readonly nativeInvoke: typeof invoke = invoke,
    private readonly socketFactory: (endpoint: string) => WebSocketLike = endpoint => new WebSocket(endpoint) as unknown as WebSocketLike,
    private readonly recoveryDelaysMs: readonly number[] = [100, 250, 500, 1000]) {}

  async connect(listener: (event: HudDataEvent) => void): Promise<() => void> {
    if (this.listener) throw new Error('Already connected');
    this.listener = listener;
    const epoch = ++this.epoch;
    this.offline('OFFLINE');
    await this.refresh(); // No bootstrap or Backend prerequisite.
    void this.connectSocket(epoch);
    const resume = () => { void this.refresh(); if (!this.socket) void this.connectSocket(epoch); };
    window.addEventListener('focus', resume);
    window.addEventListener('pageshow', resume);
    return () => {
      ++this.epoch; this.listener = null;
      if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
      const socket = this.socket; this.socket = null; socket?.close();
      window.removeEventListener('focus', resume); window.removeEventListener('pageshow', resume);
    };
  }

  refresh(): Promise<void> {
    const epoch = this.epoch;
    this.readChain = this.readChain.then(async () => {
      if (!this.listener || epoch !== this.epoch) return;
      try {
        const result = await this.nativeInvoke<ReadModel | null>('read_hud_database');
        if (!this.listener || epoch !== this.epoch) return;
        if (!result) { this.checkpoint = null; this.listener({type:'DATABASE_RESET'}); return; }
        if (result.schemaVersion !== 'd4planner-hud-db/v1' || !result.dbId || !result.epoch
          || !Number.isSafeInteger(result.hudRevision) || result.hudRevision < 0
          || !validateHudSchema(result.hud) || result.hud.hudRevision !== result.hudRevision) throw new Error('DB_INVALID_MODEL');
        const same = this.checkpoint?.dbId === result.dbId && this.checkpoint.epoch === result.epoch;
        if (same && result.hudRevision < this.checkpoint!.revision) throw new Error('REVISION_REGRESSION');
        if (!same) this.listener({type:'DATABASE_RESET'});
        this.checkpoint = {dbId:result.dbId, epoch:result.epoch, revision:result.hudRevision};
        const snapshot = structuredClone(result.hud);
        // Stored CURRENT is producer provenance, not proof the producer is live.
        let matchingProducer = false;
        if (this.online) {
          try {
            const status = await this.nativeInvoke<BackendStatus>('get_backend_status');
            matchingProducer = status.state === 'READY' && status.ready?.childInstanceId === snapshot.backend.runtimeInstanceId
              && status.ready?.generation === snapshot.backend.generation;
          } catch { /* Last-known remains readable. */ }
        }
        if (!this.listener || epoch !== this.epoch) return;
        if (!matchingProducer && snapshot.health.scoreFreshness === 'CURRENT') snapshot.health.scoreFreshness = 'STALE';
        this.listener({type:'SNAPSHOT',snapshot,receivedAt:new Date().toISOString()});
      } catch (error) {
        if (epoch === this.epoch) { this.offline(String(error)); this.listener?.({type:'ASSESSMENT_INVALIDATED'}); }
      }
    });
    return this.readChain;
  }

  private offline(reason: string) {
    this.online = false;
    this.listener?.({type:'CONNECTION',state:'DISCONNECTED',reason});
    this.listener?.({type:'TARGET_LIST_STATE',status:'IDLE',error:null});
    this.targets=[]; this.listRevision=null;
  }

  private async connectSocket(epoch: number): Promise<void> {
    if (epoch !== this.epoch || !this.listener || this.socket || this.recoveryInFlight) return;
    this.recoveryInFlight = true;
    try {
      const bootstrap = await this.nativeInvoke<Bootstrap>('get_hud_ws_bootstrap');
      if (epoch !== this.epoch || !this.listener) return;
      const url = new URL(bootstrap.endpoint);
      if (url.protocol !== 'ws:' || !['127.0.0.1','localhost','[::1]'].includes(url.hostname) || bootstrap.credential.length < 32) throw new Error('INVALID_BOOTSTRAP');
      const socket = this.socketFactory(bootstrap.endpoint);
      this.socket = socket;
      const helloId = `hello-${epoch}-${this.retry}`;
      socket.onopen = () => socket.send(JSON.stringify({protocolVersion:'d4planner-notify/v1',type:'hello',messageId:helloId,credential:bootstrap.credential,origin:bootstrap.origin}));
      socket.onmessage = event => {
        if (socket !== this.socket || epoch !== this.epoch) return;
        try {
          const message = JSON.parse(event.data);
          if (message.protocolVersion !== 'd4planner-notify/v1') throw new Error('INVALID_NOTIFICATION');
          if (message.type === 'hello.accepted' && message.correlationId === helloId) {
            this.online=true; this.retry=0;
            this.listener?.({type:'CONNECTION',state:'CONNECTED'}); void this.refresh();
          } else if (message.type === 'hud.committed' && this.online && typeof message.dbId === 'string' && typeof message.epoch === 'string'
            && Number.isSafeInteger(message.hudRevision) && message.hudRevision >= 0
            && Object.keys(message).sort().join(',') === 'dbId,epoch,hudRevision,messageId,protocolVersion,type') {
            void this.refresh(); // Never apply notification revision/data directly.
          } else throw new Error('INVALID_NOTIFICATION');
        } catch { this.offline('INVALID_NOTIFICATION'); socket.close(); }
      };
      socket.onclose = () => {
        if (socket !== this.socket || epoch !== this.epoch) return;
        this.socket=null; this.offline('OFFLINE'); void this.refresh(); this.scheduleReconnect(epoch);
      };
    } catch { this.offline('OFFLINE'); this.scheduleReconnect(epoch); }
    finally { this.recoveryInFlight=false; }
  }
  private scheduleReconnect(epoch: number) {
    if (this.retry >= this.recoveryDelaysMs.length || epoch !== this.epoch || !this.listener) return;
    this.reconnectTimer = setTimeout(() => { this.reconnectTimer=null; void this.connectSocket(epoch); },this.recoveryDelaysMs[this.retry++]);
  }
  async refreshTargets(): Promise<void> {
    this.listener?.({type:'TARGET_LIST_STATE',status:'LOADING',error:null});
    try {
      const listing = await this.nativeInvoke<{targets:TargetListEntry[];listRevision:number}>('backend_command',{method:'target.list',params:{}});
      this.targets=listing.targets; this.listRevision=listing.listRevision;
      this.listener?.({type:'TARGETS',targets:this.targets});
    } catch (error) {
      this.listener?.({type:'TARGET_LIST_STATE',status:'ERROR',error:String(error)}); throw error;
    }
  }
  async selectTarget(request: {targetId:string;expectedSha256:string}): Promise<SelectionResult> {
    if (this.listRevision === null || !this.targets.some(target => target.targetId === request.targetId && target.contentSha256 === request.expectedSha256)) {
      return {status:'TARGET_CHANGED',targetId:request.targetId,message:'Refresh Target list before activation.'};
    }
    try {
      return await this.nativeInvoke<SelectionResult>('backend_command',{method:'target.select',params:{...request,expectedListRevision:this.listRevision}});
    } finally { await this.refresh(); }
  }
}
let productionSource: IHudDataSource | null = null;
export function productionHudDataSource(): IHudDataSource {
  if (window.__D4PLANNER_HUD_DATA_SOURCE__) return window.__D4PLANNER_HUD_DATA_SOURCE__;
  return productionSource ??= new TauriHudDataSource();
}
