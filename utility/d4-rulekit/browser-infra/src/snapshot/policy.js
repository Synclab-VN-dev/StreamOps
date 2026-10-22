'use strict';

const { SNAPSHOT_ERROR_CODES, snapshotError } = require('./errors');

const DEFAULT_SENSITIVE_QUERY_NAMES = Object.freeze([
  'access_token', 'api_key', 'apikey', 'auth', 'authorization', 'jwt',
  'password', 'secret', 'session', 'sessionid', 'signature', 'token',
]);
const DEFAULT_SENSITIVE_JSON_NAMES = Object.freeze([
  ...DEFAULT_SENSITIVE_QUERY_NAMES,
  'accessToken', 'refreshToken', 'client_secret', 'date_of_birth', 'dob',
  'email', 'full_name', 'phone', 'phone_number', 'private_key', 'ssn',
]);
const REDACTED_VALUE = '[REDACTED]';
const SENSITIVE_REQUEST_HEADERS = new Set([
  'authorization', 'cookie', 'proxy-authorization', 'x-api-key', 'x-auth-token',
]);
const SAFE_RESPONSE_HEADERS = new Set([
  'accept-ranges', 'access-control-allow-origin', 'cache-control', 'content-language',
  'content-type', 'etag', 'expires', 'last-modified', 'location', 'vary',
]);

function normalizeOrigins(origins) {
  if (!Array.isArray(origins) || origins.length === 0) {
    throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
      'allowedOrigins must be a non-empty array');
  }
  const normalized = origins.map(value => {
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error();
      return url.origin;
    } catch {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'allowedOrigins contains an invalid HTTP(S) origin');
    }
  });
  return Object.freeze([...new Set(normalized)].sort());
}

function validateSnapshotId(snapshotId) {
  if (typeof snapshotId !== 'string'
      || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(snapshotId)
      || snapshotId.includes('..')) {
    throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
      'snapshotId must be a safe 1-128 character identifier');
  }
  return snapshotId;
}

function validateSafeUrl(value, allowedOrigins, sensitiveNames = DEFAULT_SENSITIVE_QUERY_NAMES) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'URL is invalid');
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw snapshotError(SNAPSHOT_ERROR_CODES.POLICY_BLOCKED,
      'only credential-free HTTP(S) URLs are supported');
  }
  if (!allowedOrigins.includes(url.origin)) {
    throw snapshotError(SNAPSHOT_ERROR_CODES.POLICY_BLOCKED,
      'URL origin is not allowlisted');
  }
  const names = new Set(sensitiveNames.map(name => name.toLowerCase()));
  for (const name of url.searchParams.keys()) {
    if (names.has(name.toLowerCase())) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.POLICY_BLOCKED,
        'URL contains a sensitive query parameter');
    }
  }
  url.hash = '';
  return url.toString();
}

function hasSensitiveRequestHeaders(headers) {
  return Object.keys(headers ?? {}).some(name => SENSITIVE_REQUEST_HEADERS.has(name.toLowerCase()));
}

function sanitizeResponseHeaders(headers) {
  const sanitized = {};
  for (const [name, value] of Object.entries(headers ?? {})) {
    const lower = name.toLowerCase();
    if (SAFE_RESPONSE_HEADERS.has(lower)) sanitized[lower] = String(value);
  }
  delete sanitized['set-cookie'];
  delete sanitized['content-length'];
  delete sanitized['content-encoding'];
  return Object.freeze(sanitized);
}

function sanitizeUrlForDiagnostics(value) {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch {
    return '[invalid-url]';
  }
}

function containsSensitiveLocation(value, baseUrl, sensitiveNames = DEFAULT_SENSITIVE_QUERY_NAMES) {
  let url;
  try {
    url = new URL(value, baseUrl);
  } catch {
    return true;
  }
  const names = new Set(sensitiveNames.map(name => name.toLowerCase()));
  for (const name of url.searchParams.keys()) {
    if (names.has(name.toLowerCase())) return true;
  }
  const fragment = url.hash.slice(1);
  if (fragment) {
    const fragmentParams = new URLSearchParams(fragment);
    for (const name of fragmentParams.keys()) {
      if (names.has(name.toLowerCase())) return true;
    }
    let lower;
    try {
      lower = decodeURIComponent(fragment).toLowerCase();
    } catch {
      return true;
    }
    if ([...names].some(name => lower.includes(`${name.toLowerCase()}=`))) return true;
  }
  return false;
}

function redactSensitiveJson(body, contentType, sensitiveNames = DEFAULT_SENSITIVE_JSON_NAMES) {
  if (!/^(application\/json|[^;]+\+json)(?:;|$)/i.test(contentType ?? '')) {
    return Object.freeze({ body, redactedFields: Object.freeze([]) });
  }
  let value;
  try {
    value = JSON.parse(body.toString('utf8'));
  } catch {
    return Object.freeze({ body, redactedFields: Object.freeze([]) });
  }
  const names = new Set(sensitiveNames.map(name => name.toLowerCase()));
  const fields = new Set();
  const visit = current => {
    if (Array.isArray(current)) return current.map(visit);
    if (!current || typeof current !== 'object') return current;
    const result = Object.create(null);
    for (const [key, child] of Object.entries(current)) {
      if (names.has(key.toLowerCase())) {
        result[key] = REDACTED_VALUE;
        fields.add(key);
      } else {
        result[key] = visit(child);
      }
    }
    return result;
  };
  const redacted = visit(value);
  if (fields.size === 0) {
    return Object.freeze({ body, redactedFields: Object.freeze([]) });
  }
  return Object.freeze({
    body: Buffer.from(JSON.stringify(redacted)),
    redactedFields: Object.freeze([...fields].sort()),
  });
}

module.exports = {
  DEFAULT_SENSITIVE_QUERY_NAMES,
  DEFAULT_SENSITIVE_JSON_NAMES,
  REDACTED_VALUE,
  containsSensitiveLocation,
  hasSensitiveRequestHeaders,
  normalizeOrigins,
  sanitizeResponseHeaders,
  sanitizeUrlForDiagnostics,
  redactSensitiveJson,
  validateSafeUrl,
  validateSnapshotId,
};
