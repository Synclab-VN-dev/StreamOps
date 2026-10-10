/* Ticket 86: pure state model; no DOM or backend imports. */
(() => {
  const UNKNOWN = "UNKNOWN";
  function gameState(game) { return game?.observation?.process?.state || UNKNOWN; }
  function isFresh(game) { return game?.observation?.process?.stale === false; }
  function counts(games, stale) {
    const values = Array.isArray(games) ? games : [];
    return {
      registered: stale ? null : values.length,
      running: stale || values.some(g => !isFresh(g) || gameState(g) === UNKNOWN)
        ? null : values.filter(g => gameState(g) === "RUNNING").length,
      verified: stale ? null : values.filter(g => g.observation?.obsCapture === "VERIFIED_ACTIVE").length
    };
  }
  class GameStore {
    constructor() { this.listeners = new Set(); this.reset(); }
    reset() { this.epoch = null; this.revision = -1; this.games = new Map(); this.operations = new Map();
      this.connected = false; this.stale = true; this.loading = true; this.error = ""; this.needsResync = false; }
    on(callback) { this.listeners.add(callback); callback(this); return () => this.listeners.delete(callback); }
    emit() { for (const callback of this.listeners) callback(this); }
    connection(state) {
      this.connected = state === "connected";
      this.stale = true; this.loading = this.connected; this.error = this.connected ? "" : "WebSocket offline";
      this.emit();
    }
    snapshot(data) {
      if (!data || !Array.isArray(data.games) || !Number.isInteger(data.revision) || typeof data.epoch !== "string") return false;
      if (data.epoch === this.epoch && data.revision < this.revision) return false;
      if (this.epoch && this.epoch !== data.epoch) {
        for (const [id, op] of this.operations)
          if (["PENDING","RUNNING"].includes(String(op.status).toUpperCase()))
            this.operations.set(id, {...op, status:"UNKNOWN", phase:"RECOVERY_REQUIRED", code:"server_restarted"});
      }
      this.epoch = data.epoch; this.revision = data.revision;
      this.games = new Map(data.games.filter(g => g && typeof g.id === "string").map(g => [g.id, g]));
      this.stale = !this.connected || data.stale === true; this.loading = false;
      this.error = ""; this.needsResync = !!data.resync_required;
      this.emit(); return true;
    }
    changed(data) {
      if (!data || typeof data.epoch !== "string" || data.epoch !== this.epoch) {
        this.needsResync = true; this.emit(); return false;
      }
      if (!Number.isInteger(data.revision) || data.revision <= this.revision) return false;
      if (data.revision > this.revision + 1) this.needsResync = true;
      this.revision = data.revision;
      if (typeof data.game_id === "string") {
        if (data.game === null) this.games.delete(data.game_id);
        else if (data.game && data.game.id === data.game_id) this.games.set(data.game_id, data.game);
        else this.needsResync = true;
      }
      this.emit(); return true;
    }
    operation(data) {
      if (!data || typeof (data.operation_id || data.id) !== "string") return;
      const key = data.operation_id || data.id;
      this.operations.set(key, Object.assign({}, data, {operation_id:key}));
      if (data.epoch && this.epoch && data.epoch !== this.epoch) this.needsResync = true;
      if (data.epoch === this.epoch && Number.isInteger(data.revision) && data.revision > this.revision)
        this.revision = data.revision;
      this.emit();
    }
    event(name, data) {
      if (name === "games.snapshot") return this.snapshot(data);
      if (name === "games.changed") return this.changed(data);
      if (name === "games.operation") return this.operation(data);
      if (name === "games.catalog.changed") { this.needsResync = true; this.emit(); }
      if (name === "games.heartbeat" && data?.epoch && this.epoch && data.epoch !== this.epoch) {
        this.needsResync = true; this.emit();
      }
    }
    items() { return Array.from(this.games.values()).sort((a,b) => a.name.localeCompare(b.name)); }
    summary() { return counts(this.items(), this.stale || this.loading); }
  }
  window.StreamOpsGamesStore = {GameStore, counts, gameState, isFresh};
})();