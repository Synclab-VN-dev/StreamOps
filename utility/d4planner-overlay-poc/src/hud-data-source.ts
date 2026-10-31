/** S5 notification transport; S6 owns SQLite reads and rendered HUD state. */
export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  send(data: string): void;
  close(): void;
}
const protocolVersion = 'd4planner-notify/v1';
const identifier = (v: unknown) => typeof v === 'string' && v.length > 0 && v.length <= 160;
const keysAre = (v: Record<string, unknown>, keys: string[]) =>
  Object.keys(v).sort().join(',') === keys.sort().join(',');

/** Hints trigger a DB reread; they never carry or apply HUD data or commands. */
export class HudNotificationClient {
  private socket: WebSocketLike | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private handshakeTimer: ReturnType<typeof setTimeout> | null = null;
  private retry = 0;
  private sequence = 0;
  private stopped = true;
  constructor(private readonly config: {
    endpoint: string; credential: string; origin: string;
    socketFactory: (endpoint: string) => WebSocketLike;
    reread: () => void;
    connection: (online: boolean) => void;
    reconnectDelaysMs?: readonly number[];
    handshakeTimeoutMs?: number;
  }) {
    const url = new URL(config.endpoint);
    if (url.protocol !== 'ws:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
        || url.username || url.password) throw new Error('LOOPBACK_REQUIRED');
  }
  connect(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.retry = 0;
    this.config.reread(); // Offline startup never waits for BE/WS.
    this.open();
  }
  disconnect(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.clearHandshake();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.config.connection(false);
  }
  private clearHandshake(): void {
    if (this.handshakeTimer) clearTimeout(this.handshakeTimer);
    this.handshakeTimer = null;
  }
  private schedule(): void {
    const delays = this.config.reconnectDelaysMs ?? [250, 500, 1000, 2000, 5000];
    if (this.stopped || this.retry >= delays.length) return;
    this.retryTimer = setTimeout(() => { this.retryTimer = null; this.open(); }, delays[this.retry++]);
  }
  private open(): void {
    let socket: WebSocketLike;
    try { socket = this.config.socketFactory(this.config.endpoint); }
    catch { this.config.connection(false); this.schedule(); return; }
    this.socket = socket;
    const helloId = `hello-${++this.sequence}`;
    let authenticated = false;
    const active = () => !this.stopped && this.socket === socket;
    const failed = () => {
      if (!active()) return;
      this.socket = null;
      this.clearHandshake();
      socket.close();
      this.config.connection(false);
      this.config.reread();
      this.schedule();
    };
    this.handshakeTimer = setTimeout(failed, this.config.handshakeTimeoutMs ?? 3000);
    socket.onopen = () => {
      if (!active()) return;
      try { socket.send(JSON.stringify({protocolVersion, type:'hello', messageId:helloId,
        credential:this.config.credential, origin:this.config.origin})); }
      catch { failed(); }
    };
    socket.onmessage = event => {
      if (!active()) return;
      try {
        const m = JSON.parse(event.data);
        if (!m || typeof m !== 'object' || m.protocolVersion !== protocolVersion || !identifier(m.messageId))
          throw new Error('INVALID_NOTIFICATION');
        if (!authenticated && m.type === 'hello.accepted' && m.correlationId === helloId
            && keysAre(m, ['protocolVersion','type','messageId','correlationId'])) {
          authenticated = true;
          this.retry = 0;
          this.clearHandshake();
        } else if (authenticated && m.type === 'hud.committed' && identifier(m.dbId) && identifier(m.epoch)
            && Number.isSafeInteger(m.hudRevision) && m.hudRevision >= 0
            && keysAre(m, ['protocolVersion','type','messageId','dbId','epoch','hudRevision'])) {
          // Duplicate, reordered, gapped or replaced-DB hints all reread SQLite.
          // The reader alone validates revision/binding and prevents rollback.
        } else throw new Error('INVALID_NOTIFICATION');
      } catch { failed(); return; }
      this.config.connection(true);
      this.config.reread();
    };
    socket.onclose = failed;
  }
}
