#!/usr/bin/env node
'use strict';

const path = require('node:path');
const readline = require('node:readline');

const PROTOCOL_VERSION = 'd4-rulekit-ipc/v1';
const APPLICATION_CONTRACT_VERSION = 'd4-rulekit-application/v1';
const APIS = Object.freeze([
  'closeSession', 'commitChanges', 'createSession', 'evaluate',
  'getSession', 'listProviders', 'previewChanges', 'resetSession',
]);

function positiveEnv(name, fallback) {
  const value = process.env[name] === undefined ? fallback : Number(process.env[name]);
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`);
  return value;
}

function write(message) {
  process.stdout.write(`${JSON.stringify({ protocolVersion: PROTOCOL_VERSION, ...message })}\n`);
}

function publicError(error) {
  return {
    code: typeof error?.code === 'string' ? error.code : 'WORKER_FAILURE',
    message: typeof error?.message === 'string' ? error.message : 'Rule Kit worker failed',
  };
}

async function main() {
  const compositionPath = process.env.D4_RULEKIT_COMPOSITION_MODULE
    ? path.resolve(process.env.D4_RULEKIT_COMPOSITION_MODULE)
    : path.join(__dirname, 'production-composition.js');
  const factory = require(compositionPath);
  if (typeof factory.createComposition !== 'function') throw new Error('composition factory is invalid');
  const composition = await factory.createComposition(process.env);
  const app = composition?.application;
  if (!app || APIS.some(method => typeof app[method] !== 'function')) {
    throw new Error('composition does not implement the approved Application contract');
  }

  const instanceId = process.env.D4_RULEKIT_WORKER_INSTANCE_ID;
  const generation = Number(process.env.D4_RULEKIT_WORKER_GENERATION);
  if (!instanceId || !Number.isInteger(generation) || generation <= 0) {
    throw new Error('managed worker identity is required');
  }
  const maxConcurrent = positiveEnv('D4_RULEKIT_MAX_CONCURRENT', 4);
  const maxQueue = positiveEnv('D4_RULEKIT_MAX_QUEUE', 32);
  const active = new Map();
  const sessions = new Set();
  const queue = [];
  let running = 0;
  let shuttingDown = false;

  async function invoke(message, controller) {
    const params = message.params ?? {};
    switch (message.method) {
      case 'listProviders': return app.listProviders();
      case 'createSession': {
        const result = await app.createSession({ ...params, signal: controller.signal });
        sessions.add(result.sessionId);
        const ttlMs = positiveEnv('D4_RULEKIT_SESSION_TTL_MS', 30 * 60_000);
        return { ...result, leaseExpiresAt: new Date((result.touchedAt ?? Date.now()) + ttlMs).toISOString() };
      }
      case 'evaluate': return app.evaluate(params.sessionId, { ...params.options, signal: controller.signal });
      case 'previewChanges': return app.previewChanges(params.sessionId, { ...params.request, signal: controller.signal });
      case 'commitChanges': return app.commitChanges(params.sessionId, { ...params.request, signal: controller.signal });
      case 'resetSession': return app.resetSession(params.sessionId, { ...params.options, signal: controller.signal });
      case 'getSession': return app.getSession(params.sessionId);
      case 'closeSession': {
        const result = await app.closeSession(params.sessionId);
        sessions.delete(params.sessionId);
        return result ?? null;
      }
      default: throw Object.assign(new Error('method is not approved'), { code: 'INVALID_METHOD' });
    }
  }

  function drain() {
    while (!shuttingDown && running < maxConcurrent && queue.length) execute(queue.shift());
  }

  function execute(message) {
    running += 1;
    const controller = new AbortController();
    active.set(message.id, controller);
    Promise.resolve().then(() => invoke(message, controller)).then(
      result => write({ type: 'result', correlationId: message.id, result }),
      error => write({ type: 'error', correlationId: message.id, error: publicError(error) }),
    ).finally(() => {
      active.delete(message.id);
      running -= 1;
      drain();
    });
  }

  async function shutdown(exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    const forcedExit = setTimeout(
      () => process.exit(1), positiveEnv('D4_RULEKIT_WORKER_CLEANUP_TIMEOUT_MS', 10_000),
    );
    for (const request of queue.splice(0)) {
      write({ type: 'error', correlationId: request.id,
        error: { code: 'CANCELLED', message: 'worker is shutting down' } });
    }
    for (const controller of active.values()) controller.abort();
    await Promise.allSettled([...sessions].map(sessionId => app.closeSession(sessionId)));
    sessions.clear();
    await composition.close?.();
    clearTimeout(forcedExit);
    process.stdin.destroy();
    process.exit(exitCode);
  }

  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  input.on('line', line => {
    let message;
    try { message = JSON.parse(line); } catch {
      write({ type: 'error', correlationId: null,
        error: { code: 'INVALID_MESSAGE', message: 'message must be JSON' } });
      return;
    }
    if (message?.protocolVersion !== PROTOCOL_VERSION) return;
    if (message.type === 'cancel') {
      active.get(message.correlationId)?.abort();
      const index = queue.findIndex(request => request.id === message.correlationId);
      if (index >= 0) queue.splice(index, 1);
      return;
    }
    if (message.type === 'shutdown') {
      input.close();
      void shutdown();
      return;
    }
    if (message.type !== 'request' || typeof message.id !== 'string' || !APIS.includes(message.method)) {
      write({ type: 'error', correlationId: message?.id ?? null,
        error: { code: 'INVALID_MESSAGE', message: 'invalid request envelope' } });
      return;
    }
    if (shuttingDown || queue.length >= maxQueue) {
      write({ type: 'error', correlationId: message.id,
        error: { code: 'QUEUE_FULL', message: 'worker request queue is full' } });
      return;
    }
    if (running < maxConcurrent) execute(message); else queue.push(message);
  });
  input.on('close', () => void shutdown());
  process.on('SIGTERM', () => { input.close(); void shutdown(); });
  process.on('SIGINT', () => { input.close(); void shutdown(); });

  write({
    type: 'READY', applicationContractVersion: APPLICATION_CONTRACT_VERSION,
    workerInstanceId: instanceId, workerGeneration: generation,
    apis: APIS, health: { ready: true }, pid: process.pid,
  });
}

main().catch(error => {
  process.stderr.write(`Rule Kit worker startup failed: ${error?.message ?? 'unknown error'}\n`);
  process.exitCode = 1;
});
