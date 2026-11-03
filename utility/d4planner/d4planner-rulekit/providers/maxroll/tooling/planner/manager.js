'use strict';
const http = require('node:http');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const {loadSnapshot, startServer} = require('../web/server');
const {readSelection, failure} = require('./selection');
const SCHEMA = 'd4planner-local-planner/v1';

class PlannerServerManager {
  constructor({stateRoot, port = 6085, timeoutMs = 12000, load = loadSnapshot, start = startServer} = {}) {
    this.stateRoot = stateRoot;
    this.port = port;
    this.timeoutMs = timeoutMs;
    this.load = load;
    this.start = start;
    this.state = 'STOPPED';
    this.running = null;
    this.flight = null;
    this.closed = false;
  }

  ensureReady({signal} = {}) {
    if (this.closed || signal?.aborted) return Promise.reject(failure('PLANNER_UNAVAILABLE'));
    if (!Number.isInteger(this.port) || this.port < 1024 || this.port > 65535) return Promise.reject(failure('PLANNER_UNAVAILABLE'));
    if (!this.flight) {
      const flight = {controller: new AbortController(), waiters: 0};
      this.flight = flight;
      const timer = setTimeout(() => flight.controller.abort(failure('PLANNER_HEALTH_FAILED')), this.timeoutMs);
      flight.promise = this.prepare(flight.controller.signal).finally(() => {
        clearTimeout(timer);
        if (this.flight === flight) this.flight = null;
      });
      flight.promise.catch(() => {});
    }
    const flight = this.flight;
    if (flight.controller.signal.aborted) return Promise.reject(failure('PLANNER_BUSY'));
    flight.waiters++;
    return new Promise((resolve, reject) => {
      let finished = false;
      const finish = (error, result) => {
        if (finished) return;
        finished = true;
        signal?.removeEventListener('abort', cancel);
        flight.controller.signal.removeEventListener('abort', timeout);
        if (--flight.waiters === 0 && this.flight === flight && error) flight.controller.abort(error);
        error ? reject(error) : resolve(result);
      };
      const cancel = () => finish(failure('PLANNER_UNAVAILABLE'));
      const timeout = () => finish(flight.controller.signal.reason || failure('PLANNER_HEALTH_FAILED'));
      signal?.addEventListener('abort', cancel, {once: true});
      flight.controller.signal.addEventListener('abort', timeout, {once: true});
      flight.promise.then(result => finish(null, result), error => finish(error));
    });
  }

  async prepare(signal) {
    let reused = Boolean(this.running?.server.listening);
    try {
      if (!reused) {
        await this.stopListener();
        this.state = 'STARTING';
        const config = await readSelection(this.stateRoot, this.port);
        let snapshot;
        try {
          snapshot = await this.load(config);
          if (snapshot.uiVerification.status !== 'AUTOMATED_VALIDATED') throw Error('receipt');
        } catch { throw failure('PLANNER_SNAPSHOT_UNTRUSTED'); }
        signal.throwIfAborted();
        const identity = {instanceId: randomUUID(), pid: process.pid, snapshotId: config.snapshotId, manifestSha256: config.manifestSha256};
        const token = randomUUID();
        try {
          this.running = await this.start(config, {snapshot, health: {token, identity}, onClientEvent: () => {}});
        } catch (error) { throw failure(error.code === 'EADDRINUSE' ? 'PLANNER_PORT_CONFLICT' : 'PLANNER_START_FAILED'); }
        this.identity = identity;
        this.token = token;
        this.running.server.on('error', () => { this.state = 'FAILED'; });
        this.running.server.on('close', () => { this.state = 'STOPPED'; });
      }
      signal.throwIfAborted();
      await this.health(signal);
      signal.throwIfAborted();
      this.state = 'READY';
      return {schemaVersion: SCHEMA, status: 'READY', url: `http://127.0.0.1:${this.port}/`,
        snapshotId: this.identity.snapshotId, manifestSha256: this.identity.manifestSha256, reused};
    } catch (error) {
      // Cancelling a new "open" request must not interrupt tabs using a
      // previously READY listener. Shutdown still closes it in close().
      if (reused && !this.closed && signal.aborted && signal.reason?.code === 'PLANNER_UNAVAILABLE') {
        throw failure('PLANNER_UNAVAILABLE');
      }
      await this.stopListener();
      this.state = 'FAILED';
      throw error.code?.startsWith('PLANNER_') ? error : failure('PLANNER_HEALTH_FAILED');
    }
  }

  async health(signal) {
    if (!this.running?.server.listening || this.running.server.address()?.address !== '127.0.0.1' ||
        this.running.server.address()?.port !== this.port) throw failure('PLANNER_HEALTH_FAILED');
    await new Promise((resolve, reject) => {
      const request = http.get({host: '127.0.0.1', port: this.port, path: '/__local/health',
        headers: {'x-local-planner-owner': this.token}, signal, timeout: 2000}, response => {
        let body = '';
        response.on('data', bytes => { body += bytes; if (body.length > 2048) request.destroy(); });
        response.on('end', () => {
          try {
            const value = JSON.parse(body);
            if (response.statusCode !== 200 || JSON.stringify(value) !== JSON.stringify(this.identity)) throw Error();
            resolve();
          } catch { reject(failure('PLANNER_HEALTH_FAILED')); }
        });
        response.on('error', () => reject(failure('PLANNER_HEALTH_FAILED')));
      });
      request.on('timeout', () => request.destroy());
      request.on('error', () => reject(failure('PLANNER_HEALTH_FAILED')));
    });
  }

  async stopListener() {
    const running = this.running;
    this.running = null;
    if (running) await running.close();
  }
  async close() {
    this.closed = true;
    this.flight?.controller.abort(failure('PLANNER_UNAVAILABLE'));
    await this.flight?.promise.catch(() => {});
    await this.stopListener();
    this.state = 'STOPPED';
  }
}
function fromEnvironment(env) {
  return new PlannerServerManager({stateRoot: env.D4_RULEKIT_PLANNER_STATE_ROOT ||
    (env.D4_RULEKIT_DATA_ROOT ? path.join(env.D4_RULEKIT_DATA_ROOT, 'planner', 'state') : undefined),
    port: Number(env.D4_RULEKIT_PLANNER_PORT || 6085)});
}
module.exports = {PlannerServerManager, fromEnvironment, SCHEMA};
