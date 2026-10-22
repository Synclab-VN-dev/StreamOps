export type MaxrollProviderErrorCode =
  | 'INVALID_CONFIG' | 'INVALID_INPUT' | 'UNSUPPORTED_INPUT' | 'SNAPSHOT_MISMATCH'
  | 'RUNTIME_MISMATCH' | 'RUNTIME_NOT_READY' | 'APPLY_FAILED' | 'READBACK_MISMATCH'
  | 'METRICS_INCOMPLETE' | 'STALE_METRICS' | 'SESSION_INVALIDATED'
  | 'TIMEOUT' | 'CANCELLED' | 'CLEANUP_FAILED';

export interface MetricDefinition {
  readonly id: string;
  readonly internalId: number;
  readonly category: string;
  readonly name: string;
}

export interface MaxrollPatchProfileConfig {
  providerVersion: string;
  runtimeVersion: string;
  gamePatch: string;
  snapshotId: string;
  snapshotManifestSha256: string;
  sourceUrl: string;
  assetUrl: string;
  assetSha256: string;
  metricCatalog: readonly MetricDefinition[];
  supportedBuildSchemaVersion?: string;
  supportedChangeTypes?: readonly string[];
  provenanceSource?: string;
  displayProvenanceSource?: string;
  selectors: Readonly<{
    ready: string;
    buildInput: string;
    applyButton: string;
    readback: string;
    phase: string;
    metrics: string;
    runtimeVersion: string;
    gamePatch: string;
    assetSha256: string;
  }>;
}

export interface MaxrollBuild {
  readonly class: 'Rogue';
  readonly level: 50;
  readonly difficulty: 'Torment I';
  readonly equipment: Readonly<{
    Helm: Readonly<{ itemId: 'runic-skullcap'; modifiers: readonly ('of-dampening')[] }>;
  }>;
}

export interface EvaluationInput {
  readonly build: MaxrollBuild;
  readonly changes?: readonly Readonly<Record<string, unknown>>[];
  readonly buildSchemaVersion: string;
  readonly mode?: 'EVALUATE' | 'PREVIEW' | 'COMMIT' | 'RESET';
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

export interface EvaluationResult {
  readonly build: MaxrollBuild;
  readonly metrics: readonly Readonly<Record<string, unknown>>[];
  readonly provenance: Readonly<Record<string, unknown>>;
}

export interface ProviderSessionOptions {
  readonly providerVersion?: string;
  readonly contractVersion?: 'd4-rulekit-application/v1';
  readonly expectedGamePatch?: string;
  readonly snapshotId: string;
  readonly snapshotManifestSha256: string;
  readonly buildSchemaVersion: string;
  readonly build: MaxrollBuild;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

export interface ProviderSession {
  evaluate(input: EvaluationInput): Promise<EvaluationResult>;
  checkpoint(options?: { signal?: AbortSignal }): Promise<unknown>;
  restore(checkpoint: unknown, options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<EvaluationResult>;
  close(options?: { signal?: AbortSignal }): Promise<void>;
}

export interface BrowserPort {
  acquire(options?: Readonly<Record<string, unknown>>): Promise<unknown>;
}

export interface SnapshotPort {
  verify(snapshotId: string): Promise<Readonly<Record<string, unknown>>>;
  load(snapshotId: string): Promise<Readonly<Record<string, unknown>>>;
  mount(lease: unknown, snapshotId: string, options: Readonly<Record<string, unknown>>): Promise<unknown>;
}

export class MaxrollProviderError extends Error {
  readonly code: MaxrollProviderErrorCode;
  readonly details?: Readonly<Record<string, unknown>>;
}

export const ERROR_CODES: Readonly<Record<MaxrollProviderErrorCode, MaxrollProviderErrorCode>>;
export const METRIC_CATALOG: readonly MetricDefinition[];

export class MaxrollPatchProfile {
  constructor(config: MaxrollPatchProfileConfig);
  readonly providerVersion: string;
  readonly runtimeVersion: string;
  readonly gamePatch: string;
  readonly snapshotId: string;
  readonly snapshotManifestSha256: string;
  readonly sourceUrl: string;
  readonly assetUrl: string;
  readonly assetSha256: string;
  readonly metricCatalog: readonly MetricDefinition[];
  readonly supportedBuildSchemaVersion: string;
  capability(): Readonly<Record<string, unknown>>;
}

export class MaxrollBuildMapper {
  constructor(profile: MaxrollPatchProfile);
  map(build: MaxrollBuild, changes: readonly Readonly<Record<string, unknown>>[], buildSchemaVersion: string): Readonly<{
    desired: MaxrollBuild;
    fingerprint: string;
  }>;
}

export class MaxrollProvider {
  constructor(options: Readonly<{
    browser: BrowserPort;
    snapshots: SnapshotPort;
    profile: MaxrollPatchProfile;
    sessionTimeoutMs?: number;
  }>);
  readonly id: 'maxroll';
  readonly version: string;
  getCapabilities(): Readonly<Record<string, unknown>>;
  createSession(options: ProviderSessionOptions): Promise<ProviderSession>;
}

export class MaxrollSession implements ProviderSession {
  evaluate(input: EvaluationInput): Promise<EvaluationResult>;
  checkpoint(options?: { signal?: AbortSignal }): Promise<unknown>;
  restore(checkpoint: unknown, options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<EvaluationResult>;
  close(options?: { signal?: AbortSignal }): Promise<void>;
}

export class MaxrollRuntimeAdapter {}
export class MaxrollMetricsExtractor {}
