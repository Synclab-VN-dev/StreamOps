'use strict';

const { BrowserInfrastructure } = require('./infrastructure');
const { BrowserInfrastructureError, ERROR_CODES } = require('./errors');
const { DEFAULT_CONFIG } = require('./config');
const { SNAPSHOT_ERROR_CODES, WebSnapshotError } = require('./snapshot/errors');
const { NetworkInterceptor, SnapshotMount } = require('./snapshot/interceptor');
const { DEFAULT_CAPTURE_OPTIONS, WebSnapshotManager } = require('./snapshot/manager');
const {
  DEFAULT_STORE_LIMITS,
  FileSystemSnapshotStore,
  SNAPSHOT_SCHEMA_VERSION,
} = require('./snapshot/store');

module.exports = {
  BrowserInfrastructure,
  BrowserInfrastructureError,
  ERROR_CODES,
  DEFAULT_CONFIG,
  DEFAULT_CAPTURE_OPTIONS,
  DEFAULT_STORE_LIMITS,
  FileSystemSnapshotStore,
  NetworkInterceptor,
  SNAPSHOT_ERROR_CODES,
  SNAPSHOT_SCHEMA_VERSION,
  SnapshotMount,
  WebSnapshotError,
  WebSnapshotManager,
};
