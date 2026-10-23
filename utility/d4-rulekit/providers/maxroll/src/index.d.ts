export type MaxrollProviderErrorCode =
  | 'INVALID_CONFIG' | 'INVALID_INPUT' | 'UNSUPPORTED_INPUT' | 'SNAPSHOT_MISMATCH'
  | 'RUNTIME_MISMATCH' | 'RUNTIME_NOT_READY' | 'APPLY_FAILED' | 'READBACK_MISMATCH'
  | 'METRICS_INCOMPLETE' | 'STALE_METRICS' | 'SESSION_INVALIDATED'
  | 'TIMEOUT' | 'CANCELLED' | 'CLEANUP_FAILED'
  | 'PROFILE_NOT_IN_SNAPSHOT' | 'PROFILE_VARIANT_NOT_FOUND'
  | 'NATIVE_BUILD_INVALID' | 'OUTPUT_EXISTS' | 'EXPORT_FAILED';

export interface MaxrollBuildExportOptions {
  readonly url: string;
  readonly snapshotRoot: string;
  readonly snapshotId: string;
  readonly expectedManifestSha256: string;
  readonly profile?: number;
  readonly outputPath: string;
}

export interface MaxrollBuildProfileInventoryOptions {
  readonly url: string;
  readonly snapshotRoot: string;
  readonly snapshotId: string;
  readonly expectedManifestSha256: string;
}

export interface MaxrollBuildExportResult {
  readonly outputPath: string;
  readonly bytes: number;
  readonly sha256: string;
  readonly nativeStateSha256: string;
  readonly profile: Readonly<Record<string, unknown>>;
  readonly provenance: Readonly<Record<string, unknown>>;
}

export const EXPORT_SCHEMA_VERSION: 'maxroll-native-build-export/v1';
export function exportMaxrollBuildFromSnapshot(
  options: MaxrollBuildExportOptions,
): Promise<MaxrollBuildExportResult>;
export function listMaxrollBuildProfilesFromSnapshot(
  options: MaxrollBuildProfileInventoryOptions,
): Promise<Readonly<Record<string, unknown>>>;

export interface MetricDefinition {
  readonly id: string;
  readonly internalId: number;
  readonly category: string;
  readonly name: string;
  readonly rawValueType: 'finite-number';
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
  runtimeKind?: 'synthetic-dom-v1' | 'maxroll-ui-cdp-v1';
  realRuntime?: Readonly<Record<string, unknown>>;
  authorizationRef?: string;
  selectors?: Readonly<{
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
  readonly runtimeKind: 'synthetic-dom-v1' | 'maxroll-ui-cdp-v1';
  readonly realRuntime?: Readonly<Record<string, unknown>>;
  readonly authorizationRef?: string;
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
    componentFactory?: MaxrollComponentFactory;
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
export class RealMaxrollRuntimeAdapter {}
export class RealMaxrollMetricsExtractor {}

export class MaxrollComponentFactory {
  constructor(options?: Readonly<{
    runtimeKind?: 'synthetic-dom-v1' | 'maxroll-ui-cdp-v1';
    RuntimeAdapter?: new (options: Readonly<Record<string, unknown>>) => unknown;
    BuildMapper?: new (profile: MaxrollPatchProfile) => unknown;
    MetricsExtractor?: new (profile: MaxrollPatchProfile) => unknown;
  }>);
  readonly runtimeKind: 'synthetic-dom-v1' | 'maxroll-ui-cdp-v1';
  createRuntimeAdapter(options: Readonly<Record<string, unknown>>): unknown;
  createBuildMapper(profile: MaxrollPatchProfile): unknown;
  createMetricsExtractor(profile: MaxrollPatchProfile): unknown;
}

export const MAXROLL_32173552_REFERENCE: Readonly<{
  gamePatch: '3.2.1.73552';
  applicationAssetPath: string;
  applicationAssetSha256: string;
  breakpoint: Readonly<{ lineNumber: number; columnNumber: number }>;
}>;
export const MAXROLL_32173552_D12AM6KT_REFERENCE: Readonly<{
  gamePatch: '3.2.1.73552';
  applicationAssetPath: string;
  applicationAssetSha256: string;
  breakpoint: Readonly<{ lineNumber: number; columnNumber: number }>;
}>;
export const REAL_MAXROLL_COMPONENT_FACTORY: MaxrollComponentFactory;
export interface Maxroll32173552RealProfileConfig {
  snapshotId: string;
  snapshotManifestSha256: string;
  sourceUrl: string;
  metricCatalog: readonly MetricDefinition[];
  providerVersion?: string;
  runtimeVersion?: string;
  assetUrl?: string;
  supportedBuildSchemaVersion?: string;
  supportedChangeTypes?: readonly string[];
  realRuntime?: Readonly<Record<string, unknown>>;
  authorizationRef: string;
}
export function createMaxroll32173552RealProfile(
  config: Maxroll32173552RealProfileConfig,
): MaxrollPatchProfile;
export function createMaxroll32173552D12aM6KTCandidateProfile(
  config: Maxroll32173552RealProfileConfig,
): MaxrollPatchProfile;
