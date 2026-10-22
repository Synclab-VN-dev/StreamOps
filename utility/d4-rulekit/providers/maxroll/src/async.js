'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');

class SerialExecutor {
  #tail = Promise.resolve();
  run(operation) {
    const result = this.#tail.then(operation, operation);
    this.#tail = result.catch(() => undefined);
    return result;
  }
}

async function bounded(operation, { signal, timeoutMs = 10_000 } = {}) {
  if (signal?.aborted) throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'operation cancelled');
  let timer;
  let abortListener;
  const boundary = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new MaxrollProviderError(ERROR_CODES.TIMEOUT, 'operation timed out')), timeoutMs);
    abortListener = () => reject(new MaxrollProviderError(ERROR_CODES.CANCELLED, 'operation cancelled'));
    signal?.addEventListener('abort', abortListener, { once: true });
  });
  try {
    return await Promise.race([operation(), boundary]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abortListener);
  }
}

module.exports = { bounded, SerialExecutor };
