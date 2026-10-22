'use strict';

const { SNAPSHOT_ERROR_CODES, snapshotError } = require('./errors');
const { sanitizeUrlForDiagnostics } = require('./policy');

function resourceKey(method, url) {
  return `${method.toUpperCase()} ${url}`;
}

class SnapshotMount {
  #context;
  #handler;
  #onUnmount;
  #mounted = true;
  #diagnostics;
  #unmountPromise = null;

  constructor({ context, handler, onUnmount, diagnostics }) {
    this.#context = context;
    this.#handler = handler;
    this.#onUnmount = onUnmount;
    this.#diagnostics = diagnostics;
    context.once?.('close', () => {
      this.#mounted = false;
      this.#onUnmount();
    });
  }

  get mounted() {
    return this.#mounted;
  }

  getDiagnostics() {
    return Object.freeze({
      fulfilled: this.#diagnostics.fulfilled,
      aborted: this.#diagnostics.aborted,
      redirected: this.#diagnostics.redirected,
      misses: Object.freeze([...this.#diagnostics.misses]),
    });
  }

  async unmount() {
    if (!this.#mounted) return;
    if (this.#unmountPromise) return this.#unmountPromise;
    this.#unmountPromise = (async () => {
      try {
        await this.#context.unroute('**/*', this.#handler);
      } catch (error) {
        if (!this.#mounted) return;
        throw snapshotError(SNAPSHOT_ERROR_CODES.MOUNT_CLEANUP_FAILED,
          'snapshot route cleanup could not be confirmed', error);
      }
      this.#mounted = false;
      this.#onUnmount();
    })();
    try {
      await this.#unmountPromise;
    } finally {
      if (this.#mounted) this.#unmountPromise = null;
    }
  }
}

class NetworkInterceptor {
  #mounts = new WeakMap();

  async mount(lease, snapshotPackage, options = {}) {
    if (!lease?.valid || !lease.context || !snapshotPackage?.resources) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.MOUNT_INVALID,
        'a valid browser lease and verified snapshot package are required');
    }
    const mode = options.mode ?? 'offline-strict';
    const onMissingResource = options.onMissingResource ?? 'abort';
    if (mode !== 'offline-strict' || onMissingResource !== 'abort') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'only offline-strict replay with abort-on-miss is supported');
    }
    if (this.#mounts.has(lease.context)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.MOUNT_INVALID,
        'the lease already has a mounted snapshot');
    }
    const diagnostics = { fulfilled: 0, aborted: 0, redirected: 0, misses: [] };
    const handler = async route => {
      const request = route.request();
      const key = resourceKey(request.method(), request.url());
      const resource = snapshotPackage.resources.get(key);
      if (!resource) {
        diagnostics.aborted += 1;
        diagnostics.misses.push(Object.freeze({
          method: request.method(),
          url: sanitizeUrlForDiagnostics(request.url()),
          code: SNAPSHOT_ERROR_CODES.REPLAY_MISS,
        }));
        await route.abort('blockedbyclient').catch(() => {});
        return;
      }
      try {
        const location = resource.headers.location;
        if (resource.status >= 300 && resource.status < 400 && location) {
          const target = new URL(location, resource.url).toString();
          const targetResource = snapshotPackage.resources.get(resourceKey(request.method(), target));
          if (!targetResource) {
            diagnostics.aborted += 1;
            diagnostics.misses.push(Object.freeze({
              method: request.method(),
              url: sanitizeUrlForDiagnostics(target),
              code: SNAPSHOT_ERROR_CODES.REPLAY_MISS,
            }));
            await route.abort('blockedbyclient').catch(() => {});
            return;
          }
          diagnostics.redirected += 1;
          if (request.resourceType() === 'document') {
            const script = `<!doctype html><script>location.replace(${JSON.stringify(target)})</script>`;
            await route.fulfill({
              status: 200,
              headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
              body: script,
            });
            diagnostics.fulfilled += 1;
            return;
          }
          await route.fulfill({
            status: targetResource.status,
            headers: { ...targetResource.headers },
            body: request.method() === 'HEAD' ? Buffer.alloc(0) : targetResource.body,
          });
          diagnostics.fulfilled += 1;
          return;
        }
        await route.fulfill({
          status: resource.status,
          headers: { ...resource.headers },
          body: request.method() === 'HEAD' ? Buffer.alloc(0) : resource.body,
        });
        diagnostics.fulfilled += 1;
      } catch {
        diagnostics.aborted += 1;
        await route.abort('failed').catch(() => {});
      }
    };
    await lease.context.addInitScript(() => {
      try {
        Object.defineProperty(globalThis, 'WebSocket', {
          configurable: true,
          value: class BlockedSnapshotWebSocket {
            constructor() { throw new Error('web sockets disabled by offline replay'); }
          },
        });
        if (navigator.serviceWorker) {
          Object.defineProperty(navigator.serviceWorker, 'register', {
            configurable: true,
            value: () => Promise.reject(new Error('service workers disabled by offline replay')),
          });
        }
      } catch {
        // Browser context serviceWorkers=block remains the primary policy.
      }
    });
    await lease.context.route('**/*', handler);
    const onUnmount = () => this.#mounts.delete(lease.context);
    const mount = new SnapshotMount({
      context: lease.context,
      handler,
      onUnmount,
      diagnostics,
    });
    this.#mounts.set(lease.context, mount);
    return mount;
  }
}

module.exports = { NetworkInterceptor, SnapshotMount, resourceKey };
