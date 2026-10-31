'use strict';

const { clone } = require('./value');

class ResultCache {
  #entries = new Map();
  #hits = 0;
  #misses = 0;

  get(key) {
    const value = this.#entries.get(key);
    if (value === undefined) {
      this.#misses += 1;
      return null;
    }
    this.#hits += 1;
    return clone(value);
  }

  set(key, value) { this.#entries.set(key, clone(value)); }
  deleteSession(sessionId) {
    for (const [key, value] of this.#entries) if (value.sessionId === sessionId) this.#entries.delete(key);
  }
  diagnostics() { return { entries: this.#entries.size, hits: this.#hits, misses: this.#misses }; }
}

module.exports = { ResultCache };
