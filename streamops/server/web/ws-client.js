(() => {
  class StreamOpsWebSocketClient {
    constructor({path, label, connectionEvent}) {
      this.path = path;
      this.label = label;
      this.connectionEvent = connectionEvent;
      this.socket = null;
      this.pending = new Map();
      this.listeners = new Map();
      this.stateListeners = new Set();
      this.cachedEvents = new Map();
      this.connected = false;
      this.destroyed = false;
      this.generation = 0;
      this.requestCounter = 0;
      this.reconnectAttempt = 0;
      this.reconnectTimer = null;
      this.watchdogTimer = null;
      this.lastMessageAt = 0;
      this.lifecycleBound = false;
    }

    url() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${protocol}//${location.host}${this.path}`;
    }

    start() {
      if (!this.lifecycleBound) {
        this.lifecycleBound = true;
        window.addEventListener('pagehide', () => this.destroy());
        window.addEventListener('pageshow', () => this.resume());
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible' && !this.connected && !this.destroyed) this.connect();
        });
      }
      this._startWatchdog();
      this.connect();
      return this;
    }

    connect() {
      if (
        this.destroyed
        || this.socket?.readyState === WebSocket.OPEN
        || this.socket?.readyState === WebSocket.CONNECTING
      ) return;
      clearTimeout(this.reconnectTimer);
      const generation = ++this.generation;
      this._state('connecting');
      let socket;
      try {
        socket = new WebSocket(this.url());
      } catch {
        this._scheduleReconnect();
        return;
      }
      this.socket = socket;
      socket.addEventListener('open', () => {
        if (generation !== this.generation || this.destroyed) return socket.close();
        this.connected = true;
        this.reconnectAttempt = 0;
        this.lastMessageAt = Date.now();
        this._state('connected');
      });
      socket.addEventListener('message', (event) => {
        if (generation !== this.generation) return;
        this.lastMessageAt = Date.now();
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type === 'response') this._response(message);
        else if (message.type === 'event' && typeof message.event === 'string') {
          this._event(message.event, message.data);
        }
      });
      socket.addEventListener('close', () => {
        if (generation !== this.generation) return;
        this.socket = null;
        const wasConnected = this.connected;
        this.connected = false;
        this._rejectPending(
          new Error(`${this.label} connection closed before the operation completed.`)
        );
        this._state(this.destroyed ? 'destroyed' : 'disconnected', {wasConnected});
        if (!this.destroyed) this._scheduleReconnect();
      });
      socket.addEventListener('error', () => socket.close());
    }

    request(operation, payload = {}, timeoutMs = 60000) {
      if (!this.connected || this.socket?.readyState !== WebSocket.OPEN) {
        return Promise.reject(
          new Error(`${this.label} is reconnecting. Try again when the connection is restored.`)
        );
      }
      const requestId = `req-${Date.now()}-${++this.requestCounter}`;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.pending.delete(requestId);
          reject(new Error(`Operation timed out: ${operation}`));
        }, timeoutMs);
        this.pending.set(requestId, {resolve, reject, timer});
        try {
          this.socket.send(JSON.stringify({
            type: 'request',
            request_id: requestId,
            operation,
            payload,
          }));
        } catch (error) {
          clearTimeout(timer);
          this.pending.delete(requestId);
          reject(error);
        }
      });
    }

    on(eventName, listener, {replay = false} = {}) {
      if (!this.listeners.has(eventName)) this.listeners.set(eventName, new Set());
      this.listeners.get(eventName).add(listener);
      if (replay && this.cachedEvents.has(eventName)) {
        queueMicrotask(() => listener(this.cachedEvents.get(eventName)));
      }
      return () => this.listeners.get(eventName)?.delete(listener);
    }

    onState(listener, {replay = false} = {}) {
      this.stateListeners.add(listener);
      if (replay) {
        queueMicrotask(() => listener({
          state: this.connected ? 'connected' : this.socket ? 'connecting' : 'disconnected',
        }));
      }
      return () => this.stateListeners.delete(listener);
    }

    waitFor(eventName) {
      if (this.cachedEvents.has(eventName)) {
        return Promise.resolve(this.cachedEvents.get(eventName));
      }
      return new Promise((resolve) => {
        const off = this.on(eventName, (data) => {
          off();
          resolve(data);
        });
      });
    }

    destroy() {
      this.destroyed = true;
      clearTimeout(this.reconnectTimer);
      clearInterval(this.watchdogTimer);
      this.reconnectTimer = null;
      this.watchdogTimer = null;
      this._rejectPending(new Error('Page closed before the operation completed.'));
      this.connected = false;
      this.generation++;
      const socket = this.socket;
      this.socket = null;
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'pagehide');
      this._state('destroyed');
    }

    resume() {
      if (!this.destroyed && (this.connected || this.socket)) return;
      this.destroyed = false;
      this._startWatchdog();
      this.connect();
    }

    _response(message) {
      const pending = this.pending.get(message.request_id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.request_id);
      if (message.ok) {
        pending.resolve(message.data);
        return;
      }
      const error = new Error(message.error?.message || 'Operation failed.');
      error.code = message.error?.code || 'operation_failed';
      pending.reject(error);
    }

    _event(eventName, data) {
      this.cachedEvents.set(eventName, data);
      for (const listener of this.listeners.get(eventName) || []) listener(data);
    }

    _state(state, detail = {}) {
      const payload = {state, ...detail};
      for (const listener of this.stateListeners) listener(payload);
      if (this.connectionEvent) {
        window.dispatchEvent(new CustomEvent(this.connectionEvent, {detail: payload}));
      }
    }

    _rejectPending(error) {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(error);
      }
      this.pending.clear();
    }

    _scheduleReconnect() {
      if (this.destroyed || this.reconnectTimer !== null) return;
      const delays = [1000, 2000, 4000, 8000, 15000];
      const delay = delays[Math.min(this.reconnectAttempt++, delays.length - 1)];
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, delay);
    }

    _startWatchdog() {
      if (this.watchdogTimer !== null) return;
      this.watchdogTimer = setInterval(() => {
        if (this.connected && Date.now() - this.lastMessageAt > 30000) this.socket?.close();
      }, 5000);
    }
  }

  window.StreamOpsWebSocketClient = StreamOpsWebSocketClient;
})();
