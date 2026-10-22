'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');

class SessionManager {
  #sessions = new Map();
  #maxSessions;
  #ttlMs;
  #clock;
  #scheduler;
  #pending = 0;
  #timers = new Map();

  constructor({ maxSessions, ttlMs, clock, scheduler }) {
    this.#maxSessions = maxSessions;
    this.#ttlMs = ttlMs;
    this.#clock = clock;
    this.#scheduler = scheduler ?? {
      setTimeout: (callback, delay) => setTimeout(callback, delay),
      clearTimeout: handle => clearTimeout(handle),
    };
  }

  assertCapacity() {
    if (this.#sessions.size + this.#pending >= this.#maxSessions) {
      throw new ApplicationError(ERROR_CODES.QUOTA_EXCEEDED, 'session quota exceeded');
    }
  }

  reserve() { this.assertCapacity(); this.#pending += 1; }
  releaseReservation() { if (this.#pending > 0) this.#pending -= 1; }

  addReserved(session, onExpire) {
    this.releaseReservation();
    session.onExpire = onExpire;
    this.#sessions.set(session.id, session);
    this.#schedule(session);
  }

  delete(id) {
    this.cancelExpiry(id);
    this.#sessions.delete(id);
  }
  find(id) { return this.#sessions.get(id); }
  values() { return this.#sessions.values(); }

  get(id) {
    const session = this.find(id);
    if (!session) throw new ApplicationError(ERROR_CODES.SESSION_NOT_FOUND, `unknown session: ${id}`);
    return session;
  }

  touch(session) {
    session.touchedAt = this.#clock();
    this.#schedule(session);
  }
  reschedule(session) { this.#schedule(session); }
  isExpired(session) { return this.#clock() - session.touchedAt >= this.#ttlMs; }

  cancelExpiry(id) {
    const handle = this.#timers.get(id);
    if (handle !== undefined) this.#scheduler.clearTimeout(handle);
    this.#timers.delete(id);
  }

  #schedule(session) {
    this.cancelExpiry(session.id);
    const remaining = Math.max(0, this.#ttlMs - (this.#clock() - session.touchedAt));
    const handle = this.#scheduler.setTimeout(() => {
      this.#timers.delete(session.id);
      void session.onExpire?.(session);
    }, remaining);
    handle?.unref?.();
    this.#timers.set(session.id, handle);
  }
}

module.exports = { SessionManager };
