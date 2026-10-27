import type {
  BrowserContext,
  BrowserContextOptions,
  BrowserTypeLaunchOptions,
  CDPSession,
  Page,
} from 'playwright-core';

export type BrowserState = 'running' | 'restarting' | 'degraded' | 'stopped';

export interface BrowserConfig {
  maxContexts?: number;
  maxQueue?: number;
  acquireTimeoutMs?: number;
  leaseTimeoutMs?: number;
  cleanupTimeoutMs?: number;
  headless?: boolean;
  executablePath?: string;
  launchOptions?: BrowserTypeLaunchOptions;
  contextOptions?: BrowserContextOptions;
  logger?: (event: Readonly<Record<string, unknown>>) => void;
}

export interface LeaseOptions {
  timeoutMs?: number;
  leaseTimeoutMs?: number;
  signal?: AbortSignal;
}

export interface BrowserStatus {
  state: BrowserState;
  pid: number | null;
  activeLeases: number;
  pendingQueue: number;
  restartCount: number;
  uptimeMs: number;
}

export interface BrowserMetrics {
  launchCount: number;
  launchFailures: number;
  restartCount: number;
  crashCount: number;
  acquireRequested: number;
  acquireSucceeded: number;
  releaseCount: number;
  queueTimeoutCount: number;
  cancellationCount: number;
  leaseExpirationCount: number;
  cleanupFailureCount: number;
  recoveryCount: number;
  recoveryFailureCount: number;
  peakContexts: number;
  currentContexts: number;
  pendingQueue: number;
  totalAcquireWaitMs: number;
  averageAcquireWaitMs: number;
  lastLaunchDurationMs: number | null;
}

export interface BrowserLease {
  readonly id: string;
  readonly context: BrowserContext;
  readonly page: Page;
  readonly valid: boolean;
  readonly invalidReason: BrowserInfrastructureErrorCode | null;
  createCDPSession(): Promise<CDPSession>;
  release(): Promise<void>;
}

export interface BrowserInfrastructureContract {
  start(config?: BrowserConfig): Promise<void>;
  stop(): Promise<void>;
  restart(): Promise<void>;
  getStatus(): BrowserStatus;
  getMetrics(): BrowserMetrics;
  acquire(options?: LeaseOptions): Promise<BrowserLease>;
  release(leaseId: string): Promise<void>;
  withLease<T>(options: LeaseOptions, run: (lease: BrowserLease) => Promise<T>): Promise<T>;
}

export type BrowserInfrastructureErrorCode =
  | 'NOT_RUNNING'
  | 'CAPACITY_EXCEEDED'
  | 'QUEUE_TIMEOUT'
  | 'LEASE_EXPIRED'
  | 'BROWSER_DISCONNECTED'
  | 'CLEANUP_FAILED'
  | 'CANCELLED'
  | 'INVALID_CONFIG';

export class BrowserInfrastructureError extends Error {
  readonly code: BrowserInfrastructureErrorCode;
}

export const ERROR_CODES: Readonly<Record<BrowserInfrastructureErrorCode, BrowserInfrastructureErrorCode>>;
export const DEFAULT_CONFIG: Readonly<Required<Omit<BrowserConfig, 'executablePath' | 'logger'>> & {
  executablePath: undefined;
  logger: undefined;
}>;

export class BrowserInfrastructure implements BrowserInfrastructureContract {
  constructor(config?: BrowserConfig);
  start(config?: BrowserConfig): Promise<void>;
  stop(): Promise<void>;
  restart(): Promise<void>;
  getStatus(): BrowserStatus;
  getMetrics(): BrowserMetrics;
  acquire(options?: LeaseOptions): Promise<BrowserLease>;
  release(leaseId: string): Promise<void>;
  withLease<T>(options: LeaseOptions, run: (lease: BrowserLease) => Promise<T>): Promise<T>;
}

export type SnapshotErrorCode =
  | 'INVALID_OPTIONS'
  | 'INVALID_SNAPSHOT'
  | 'SNAPSHOT_NOT_FOUND'
  | 'DUPLICATE_SNAPSHOT'
  | 'INTEGRITY_MISMATCH'
  | 'RESOURCE_MISSING'
  | 'RESOURCE_CONFLICT'
  | 'RESOURCE_LIMIT'
  | 'STORAGE_LIMIT'
  | 'STORAGE_IO'
  | 'CAPTURE_TIMEOUT'
  | 'CAPTURE_CANCELLED'
  | 'POLICY_BLOCKED'
  | 'SENSITIVE_RESPONSE'
  | 'REPLAY_MISS'
  | 'MOUNT_INVALID'
  | 'MOUNT_CLEANUP_FAILED';

export class WebSnapshotError extends Error {
  readonly code: SnapshotErrorCode;
  readonly cause?: unknown;
}

export const SNAPSHOT_ERROR_CODES: Readonly<Record<SnapshotErrorCode, SnapshotErrorCode>>;
export const SNAPSHOT_SCHEMA_VERSION: 'web-snapshot/v1';

export interface SnapshotLimits {
  maxSnapshots?: number;
  maxResources?: number;
  maxResourceBytes?: number;
  maxTotalBytes?: number;
}

export const DEFAULT_STORE_LIMITS: Readonly<Required<SnapshotLimits>>;
export const DEFAULT_CAPTURE_OPTIONS: Readonly<Required<Omit<SnapshotLimits, 'maxSnapshots'>> & {
  timeoutMs: number;
  responseBodyTimeoutMs: number;
}>;

export interface SnapshotResourceDraft {
  readonly key: string;
  readonly method: 'GET' | 'HEAD';
  readonly url: string;
  readonly status: number;
  readonly headers: Readonly<Record<string, string>>;
  readonly redirectedFrom: string | null;
  readonly body: Uint8Array | string;
}

export interface SnapshotResourceManifest extends Omit<SnapshotResourceDraft, 'body'> {
  readonly sha256: string;
  readonly size: number;
  readonly blob: string;
}

export interface WebSnapshotDraft {
  readonly schemaVersion: 'web-snapshot-draft/v1';
  readonly snapshotId: string;
  readonly sourceUrl: string;
  readonly capturedAt: string;
  readonly allowedOrigins: readonly string[];
  readonly site?: string;
  readonly version?: string;
  readonly browserVersion: string | null;
  readonly playwrightVersion: string;
  readonly resources: readonly SnapshotResourceDraft[];
  readonly capture: Readonly<{
    durationMs: number;
    blockedRequestCount: number;
    blockedWebSocketCount: number;
    excludedResponseCount: number;
    redactedResponseCount: number;
    strippedSensitiveRequestCount: number;
    blockedRequests: readonly Readonly<{ method: string; url: string }>[];
    serviceWorkerPolicy: 'block';
    completion?: CaptureCompletionEvidence;
  }>;
}

export interface WebSnapshotManifest {
  readonly schemaVersion: 'web-snapshot/v1';
  readonly snapshotId: string;
  readonly sourceUrl: string;
  readonly capturedAt: string;
  readonly allowedOrigins: readonly string[];
  readonly site: string | null;
  readonly version: string | null;
  readonly browserVersion: string | null;
  readonly playwrightVersion: string;
  readonly serviceWorkerPolicy: 'block';
  readonly resources: readonly SnapshotResourceManifest[];
  readonly resourceCount: number;
  readonly totalBytes: number;
  readonly integrity: Readonly<{
    algorithm: 'sha256';
    manifest: Readonly<{ algorithm: 'sha256'; anchor: 'manifest.sha256' }>;
  }>;
}

export interface SnapshotVerification {
  readonly snapshotId: string;
  readonly valid: true;
  readonly resourceCount: number;
  readonly totalBytes: number;
  readonly algorithm: 'sha256';
  readonly manifestSha256: string;
}

export interface SnapshotFilter {
  site?: string;
  version?: string;
  origin?: string;
}

export interface CaptureResourceDescriptor {
  readonly method: string;
  readonly url: string;
  readonly resourceType: string;
}

export interface CaptureCompletionPolicy {
  minimumObservationMs: number;
  quietWindowMs: number;
}

export interface CaptureCompletionEvidence extends Readonly<CaptureCompletionPolicy> {
  readonly policy: 'bounded-quiescence/v1';
  readonly pendingRequests: number;
  readonly failedRequests: readonly Readonly<{method: string; url: string}>[];
  readonly nodes: readonly CaptureResourceDescriptor[];
  readonly roots: readonly Readonly<{method: string; url: string}>[];
  readonly edges: readonly Readonly<{
    from: Readonly<{method: string; url: string}>;
    to: Readonly<{method: string; url: string}>;
  }>[];
}

export interface CapturePolicy extends Omit<SnapshotLimits, 'maxSnapshots'> {
  completion?: CaptureCompletionPolicy;
  responseBodyTimeoutMs?: number;
  requestHeaderPolicy?: 'block-sensitive' | 'strip-sensitive' | 'fresh-anonymous-context';
  navigationWaitUntil?: 'load' | 'domcontentloaded' | 'networkidle' | 'commit';
  settleWaitUntil?: 'load' | 'domcontentloaded' | 'networkidle';
  sensitiveQueryParameters?: readonly string[];
  sensitiveJsonFields?: readonly string[];
  sensitiveResponseNames?: readonly string[];
  allowResource?: (resource: CaptureResourceDescriptor) => boolean | Promise<boolean>;
  responsePolicy?: (
    response: Readonly<{
      method: 'GET' | 'HEAD';
      url: string;
      status: number;
      headers: Readonly<Record<string, string>>;
      contentType: string | null;
      body: Uint8Array;
    }>,
  ) => SnapshotResponseDecision | void | Promise<SnapshotResponseDecision | void>;
}

export type SnapshotResponseDecision =
  | Readonly<{ action: 'default' | 'exclude' | 'include-sensitive' }>
  | Readonly<{
      action: 'redact';
      body: Uint8Array | string;
      headers?: Readonly<Record<string, string>>;
    }>;

export interface SnapshotCaptureOptions {
  url: string;
  allowedOrigins: readonly string[];
  snapshotId?: string;
  site?: string;
  version?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  capturePolicy?: CapturePolicy;
  interact?: (session: Readonly<{ page: Page; signal: AbortSignal }>) => Promise<void>;
}

export interface SnapshotPackage {
  readonly manifest: WebSnapshotManifest;
  readonly resources: ReadonlyMap<string, Readonly<SnapshotResourceManifest & { body: Uint8Array }>>;
}

export interface SnapshotStoreContract {
  save(snapshot: WebSnapshotDraft): Promise<WebSnapshotManifest>;
  load(snapshotId: string): Promise<WebSnapshotManifest>;
  list(filter?: SnapshotFilter): Promise<readonly WebSnapshotManifest[]>;
  verify(snapshotId: string): Promise<SnapshotVerification>;
  loadPackage(snapshotId: string): Promise<SnapshotPackage>;
}

export class FileSystemSnapshotStore implements SnapshotStoreContract {
  constructor(options: { rootDir: string; limits?: SnapshotLimits; fsImpl?: unknown });
  readonly limits: Readonly<Required<SnapshotLimits>>;
  save(snapshot: WebSnapshotDraft): Promise<WebSnapshotManifest>;
  load(snapshotId: string): Promise<WebSnapshotManifest>;
  list(filter?: SnapshotFilter): Promise<readonly WebSnapshotManifest[]>;
  verify(snapshotId: string): Promise<SnapshotVerification>;
  loadPackage(snapshotId: string): Promise<SnapshotPackage>;
}

export interface SnapshotMountDiagnostics {
  readonly fulfilled: number;
  readonly aborted: number;
  readonly redirected: number;
  readonly transportOffline: boolean;
  readonly misses: readonly Readonly<{ method: string; url: string; code: 'REPLAY_MISS' }>[];
}

export class SnapshotMount {
  readonly mounted: boolean;
  getDiagnostics(): SnapshotMountDiagnostics;
  unmount(): Promise<void>;
}

export interface SnapshotReplayOptions {
  mode?: 'offline-strict';
  onMissingResource?: 'abort';
}

export class NetworkInterceptor {
  mount(
    lease: BrowserLease,
    snapshotPackage: SnapshotPackage,
    options?: SnapshotReplayOptions,
  ): Promise<SnapshotMount>;
}

export class WebSnapshotManager {
  constructor(options: {
    browser: BrowserInfrastructureContract;
    store: SnapshotStoreContract;
    interceptor?: NetworkInterceptor;
    logger?: (event: Readonly<Record<string, unknown>>) => void;
  });
  capture(options: SnapshotCaptureOptions): Promise<WebSnapshotDraft>;
  save(snapshot: WebSnapshotDraft): Promise<WebSnapshotManifest>;
  load(snapshotId: string): Promise<WebSnapshotManifest>;
  list(filter?: SnapshotFilter): Promise<readonly WebSnapshotManifest[]>;
  verify(snapshotId: string): Promise<SnapshotVerification>;
  mount(
    lease: BrowserLease,
    snapshotId: string,
    options?: SnapshotReplayOptions,
  ): Promise<SnapshotMount>;
}
