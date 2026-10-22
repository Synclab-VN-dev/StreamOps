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
