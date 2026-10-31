export type MaxrollProviderErrorCode =
  | 'INVALID_CONFIG' | 'INVALID_INPUT' | 'UNSUPPORTED_INPUT' | 'SNAPSHOT_MISMATCH'
  | 'RUNTIME_MISMATCH' | 'RUNTIME_NOT_READY' | 'APPLY_FAILED' | 'READBACK_MISMATCH'
  | 'METRICS_INCOMPLETE' | 'STALE_METRICS' | 'SESSION_INVALIDATED'
  | 'TIMEOUT' | 'CANCELLED' | 'CLEANUP_FAILED'
  | 'PROFILE_NOT_IN_SNAPSHOT' | 'PROFILE_VARIANT_NOT_FOUND'
  | 'NATIVE_BUILD_INVALID' | 'OUTPUT_EXISTS' | 'EXPORT_FAILED'
  | 'ENGINE_IDENTITY_UNVERIFIED' | 'INPUT_READBACK_UNVERIFIED' | 'OUTPUT_NOT_LINKED'
  | 'CANONICAL_BUILD_INVALID' | 'CANONICAL_MAPPING_INCOMPLETE' | 'ENTITY_NOT_FOUND'
  | 'ILLEGAL_COMBINATION';

export const CANONICAL_SCHEMA_VERSION: 'd4-build/v1';
export const CODEC_VERSION: 'maxroll-native/3.2.1.73552-D12aM6KT-v1';
export const D12_COMPATIBILITY: Readonly<{
  gamePatch: '3.2.1.73552';
  snapshotId: 'maxroll-20261023T034150Z';
  snapshotManifestSha256: string;
  engineAssetSha256: string;
  catalogVersion: '3.2.1.73552';
  catalogResourceSha256: string;
}>;

export interface CanonicalD4Build {
  readonly schemaVersion: 'd4-build/v1';
  readonly game: Readonly<{ id: 'diablo-iv'; patch: '3.2.1.73552' }>;
  readonly character: Readonly<{ classId: string; level: number; worldTier: number }>;
  readonly equipment: Readonly<{ slots: readonly CanonicalEquipmentSlot[] }>;
  readonly skills: Readonly<{ allocations: readonly CanonicalRankAllocation[];
    bar: readonly (string | null)[] }>;
  readonly paragon: Readonly<{ boards: readonly CanonicalParagonBoard[] }>;
  readonly effects: CanonicalEffects;
  readonly world: Readonly<{ renownSkills?: number; renownParagon?: number }>;
  readonly calculationContext: Readonly<{ season: 15;
    options: Readonly<Record<string, CanonicalCalculationOption>> }>;
  readonly provenance?: Readonly<{ codecVersion?: string;
    sourceNativeStateSha256?: string | null; source?: string }>;
}

export interface CanonicalModifier { readonly entityId: string; readonly values: readonly number[];
  readonly greater?: boolean; readonly hidden?: boolean; readonly uniquePriority?: number;
  readonly upgradeRank?: number }
export interface CanonicalItem { readonly baseItemId: string; readonly itemPower: number;
  readonly affixes: readonly CanonicalModifier[]; readonly implicits: readonly CanonicalModifier[];
  readonly aspects: readonly CanonicalModifier[]; readonly tempers: readonly CanonicalModifier[];
  readonly sockets: readonly Readonly<{ entityId: string }>[]; readonly customName?: string;
  readonly upgradeRank?: number; readonly mythic?: boolean }
export interface CanonicalEquipmentSlot { readonly slotId: string; readonly item: CanonicalItem }
export interface CanonicalRankAllocation { readonly nodeId: string; readonly rank: number }
export interface CanonicalValueAllocation { readonly nodeId: string;
  readonly value: boolean | 0 | 1 }
export interface CanonicalParagonBoard { readonly boardId: string; readonly rotation: 0 | 1 | 2 | 3;
  readonly allocations: readonly CanonicalValueAllocation[]; readonly position?: Readonly<Record<string, unknown>>;
  readonly glyph?: Readonly<{ glyphId: string; level: number }> }
export type CanonicalCalculationOption = Readonly<{ active?: boolean; flags?: readonly boolean[];
  params?: readonly (number | string)[] }> | Readonly<Record<string, boolean | number | string>>;
export interface CanonicalEffects extends Readonly<Record<string, unknown>> {
  readonly elixirs: readonly (string | number)[];
  readonly warPlans: readonly Readonly<Record<string, boolean | 0 | 1>>[];
}

export class MaxrollEntityCatalog {
  constructor(data: Readonly<Record<string, unknown>>, provenance?: Readonly<Record<string, unknown>>,
    runtimeDefinitions?: Readonly<Record<string, unknown>>);
  readonly counts: Readonly<Record<string, number>>;
  readonly provenance: Readonly<Record<string, unknown>>;
  coverageInventory(): Readonly<Record<string, unknown>>;
  auditCoverage(): Readonly<Record<string, unknown>>;
  metricCatalog(classId?: string | number | null): readonly MetricDefinition[];
  firstEquippable(classId: string | number): Readonly<{ itemId: string; slotId: string }>;
  starterParagonBoard(classId: string | number): string;
  optionReadbackDefinitions(): Readonly<Record<string, unknown>>;
  canonicalCalculationOptions(options: Readonly<Record<string, unknown>>):
    Readonly<Record<string, unknown>>;
}

export class MaxrollD12CanonicalCodec {
  constructor(options: Readonly<{ catalog: MaxrollEntityCatalog }>);
  nativeToCanonical(fixture: Readonly<Record<string, unknown>>): CanonicalD4Build;
  canonicalToNative(build: CanonicalD4Build): Readonly<Record<string, unknown>>;
  runtimeStateToCanonical(runtimeState: Readonly<Record<string, unknown>>,
    provenance?: CanonicalD4Build['provenance']): CanonicalD4Build;
  loaderIdentity(build: CanonicalD4Build): Readonly<{ className: string; season: number }>;
}

export const CHANGE_TYPES: readonly string[];
export class UniversalMaxrollBuildMapper {
  constructor(profile: Readonly<Record<string, unknown>>, options: Readonly<{
    codec: MaxrollD12CanonicalCodec;
  }>);
  map(build: CanonicalD4Build, changes: readonly Readonly<Record<string, unknown>>[],
    buildSchemaVersion: string): Readonly<Record<string, unknown>>;
}
export class UniversalMaxrollComponentFactory {
  constructor(options: Readonly<{
    codec: MaxrollD12CanonicalCodec;
    plannerId: string;
    profileUrl: string;
  }>);
}
export class NativeStateMaxrollRuntimeAdapter {
  constructor(options: Readonly<Record<string, unknown>>);
}
export function createD12NativeLoaderMetadata(options: Readonly<{
  plannerId: string;
  className: string;
  season: number;
}>): Readonly<Record<string, unknown>>;

export function loadMaxrollEntityCatalog(options: Readonly<{
  snapshotRoot: string;
  snapshotId: string;
  expectedManifestSha256: string;
  store?: unknown;
}>): Promise<MaxrollEntityCatalog>;

export function createMaxroll32173552D12aM6KTUniversalProfile(
  config: MaxrollPatchProfileConfig | (Omit<MaxrollPatchProfileConfig, 'metricCatalog'> & {
    catalog: MaxrollEntityCatalog;
  }),
): MaxrollPatchProfile;

export interface MaxrollBuildAttestationOptions {
  readonly inputPath: string;
  readonly outputPath: string;
  readonly snapshotRoot: string;
  readonly snapshotId: string;
  readonly expectedManifestSha256: string;
  readonly chromiumExecutablePath: string;
  readonly timeoutMs?: number;
}

export interface MaxrollBuildAttestationResult {
  readonly outputPath: string;
  readonly outputSha256: string;
  readonly rawCount: number;
  readonly displayCount: number;
  readonly sourceReplay: 'EXACT';
}

export const ATTESTATION_SCHEMA_VERSION: 'maxroll-character-stats-attestation/v1';
export function attestMaxrollBuildFixture(
  options: MaxrollBuildAttestationOptions,
): Promise<MaxrollBuildAttestationResult>;

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

export const CLASS_FIXTURE_SCHEMA_VERSION: 'maxroll-class-fixture-capture/v1';
export const MATRIX_SCHEMA_VERSION: 'maxroll-class-fixture-matrix/v1';
export class MaxrollClassFixtureCapturer {
  constructor(dependencies?: Readonly<Record<string, unknown>>);
  capture(options: Readonly<{
    outputRoot: string;
    snapshotRoot: string;
    snapshotId: string;
    expectedManifestSha256: string;
    chromiumExecutablePath: string;
    matrix: Readonly<Record<string, unknown>>;
    reuseRoot?: string;
    timeoutMs?: number;
  }>): Promise<Readonly<Record<string, unknown>>>;
}

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
  metricCoverage?: 'EXACT' | 'DYNAMIC_APPLICABLE';
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
  readonly metricCoverage: 'EXACT' | 'DYNAMIC_APPLICABLE';
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
