'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');

class SerialExecutor {
  #tail = Promise.resolve();
  run(operation) {
    const result = this.#tail.then(operation, operation);
    this.#tail = result.catch(() => undefined);
    return result;
  }
}

async function bounded(operation, options = {}) {
  const timeoutMs = options.timeoutMs ?? 5_000;
  const external = options.signal;
  if (external?.aborted) throw new ApplicationError(ERROR_CODES.CANCELLED, 'operation cancelled');
  const controller = new AbortController();
  let reason = ERROR_CODES.TIMEOUT;
  let timer;
  let listener;
  const abortPromise = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(new ApplicationError(reason, reason === ERROR_CODES.TIMEOUT ? 'operation timed out' : 'operation cancelled'));
      controller.abort();
    }, timeoutMs);
    listener = () => {
      reason = ERROR_CODES.CANCELLED;
      reject(new ApplicationError(ERROR_CODES.CANCELLED, 'operation cancelled'));
      controller.abort();
    };
    external?.addEventListener('abort', listener, { once: true });
  });
  try {
    return await Promise.race([operation(controller.signal), abortPromise]);
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', listener);
  }
}

module.exports = { bounded, SerialExecutor };
