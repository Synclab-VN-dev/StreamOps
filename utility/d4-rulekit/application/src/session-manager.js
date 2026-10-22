'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');

class SessionManager {
  #sessions = new Map();
  #maxSessions;
  #ttlMs;
  #clock;

  constructor({ maxSessions, ttlMs, clock }) {
    this.#maxSessions = maxSessions;
    this.#ttlMs = ttlMs;
    this.#clock = clock;
  }

  assertCapacity() {
    if (this.#sessions.size >= this.#maxSessions) {
      throw new ApplicationError(ERROR_CODES.QUOTA_EXCEEDED, 'session quota exceeded');
    }
  }

  add(session) { this.#sessions.set(session.id, session); }
  delete(id) { this.#sessions.delete(id); }
  find(id) { return this.#sessions.get(id); }
  values() { return this.#sessions.values(); }

  get(id) {
    const session = this.find(id);
    if (!session) throw new ApplicationError(ERROR_CODES.SESSION_NOT_FOUND, `unknown session: ${id}`);
    return session;
  }

  touch(session) { session.touchedAt = this.#clock(); }
  isExpired(session) { return this.#clock() - session.touchedAt >= this.#ttlMs; }
}

module.exports = { SessionManager };
