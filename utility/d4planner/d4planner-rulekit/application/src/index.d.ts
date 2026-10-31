export type MetricStatus = 'OBSERVED' | 'UNKNOWN' | 'UNSUPPORTED' | 'ERROR';
export type SessionStatus = 'ACTIVE' | 'CLOSING' | 'CLOSED' | 'EXPIRED' | 'QUARANTINED';
export type ChangeType = 'equipment.replace' | 'skill.setRank' | 'effect.set' | (string & {});

export interface BuildChange {
  readonly type: ChangeType;
  readonly [key: string]: unknown;
}

export interface ProviderCapabilities {
  readonly version: string;
  readonly policyVersion?: string;
  readonly stateModel: 'stateful' | 'stateless';
  readonly metricCoverage?: 'EXACT' | 'DYNAMIC_APPLICABLE';
  readonly metricIds: readonly string[];
  readonly changeTypes: readonly string[];
}

export interface ProviderMetric {
  readonly id: string;
  readonly name?: string;
  readonly rawValue?: number | string | boolean | null;
  readonly displayValue?: string | null;
  readonly unit?: string | null;
  readonly status: MetricStatus;
  readonly provenance?: Readonly<Record<string, unknown>> | null;
}

export interface EvaluationInput {
  readonly contractVersion: typeof CONTRACT_VERSION;
  readonly buildSchemaVersion: string;
  readonly snapshotId: string | null;
  readonly snapshotManifestSha256: string | null;
  readonly build: Readonly<Record<string, unknown>>;
  readonly changes: readonly BuildChange[];
  readonly mode: 'EVALUATE' | 'PREVIEW' | 'COMMIT' | 'RESET';
  readonly signal: AbortSignal;
}

export interface ProviderEvaluationResult {
  readonly build: Readonly<Record<string, unknown>>;
  readonly metrics: readonly ProviderMetric[];
  readonly provenance?: Readonly<Record<string, unknown>>;
}

export interface ProviderSession {
  evaluate(input: EvaluationInput): Promise<ProviderEvaluationResult>;
  checkpoint?(options: { signal: AbortSignal }): Promise<unknown>;
  restore?(checkpoint: unknown, options: { signal: AbortSignal }): Promise<void>;
  close(options: { signal: AbortSignal }): Promise<void>;
}

export interface CalculationProvider {
  readonly id: string;
  readonly version: string;
  readonly available?: boolean;
  getCapabilities(): ProviderCapabilities;
  createSession(options: Readonly<{
    contractVersion: typeof CONTRACT_VERSION;
    buildSchemaVersion: string;
    snapshotId: string | null;
    snapshotManifestSha256: string | null;
    build: Readonly<Record<string, unknown>>;
    signal: AbortSignal;
  }>): Promise<ProviderSession>;
}

export interface ApplicationOptions {
  providers: readonly CalculationProvider[];
  maxSessions?: number;
  sessionTtlMs?: number;
  operationTimeoutMs?: number;
  cleanupTimeoutMs?: number;
  clock?: () => number;
  scheduler?: Readonly<{
    setTimeout(callback: () => void, delayMs: number): unknown;
    clearTimeout(handle: unknown): void;
  }>;
}

export interface CreateSessionOptions {
  contractVersion: typeof CONTRACT_VERSION;
  providerId: string;
  providerVersion: string;
  snapshotId: string | null;
  snapshotManifestSha256: string | null;
  buildSchemaVersion: string;
  build: Readonly<Record<string, unknown>>;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export interface SessionView {
  readonly sessionId: string;
  readonly status: SessionStatus;
  readonly revision: number;
  readonly providerId: string;
  readonly providerVersion: string;
  readonly snapshotId: string | null;
  readonly snapshotManifestSha256: string | null;
  readonly contractVersion: typeof CONTRACT_VERSION;
  readonly buildSchemaVersion: string;
  readonly buildFingerprint: string;
  readonly createdAt: number;
  readonly touchedAt: number;
  readonly diagnostics: Readonly<Record<string, unknown>>;
}

export interface EvaluationOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  bypassCache?: boolean;
}

export interface NormalizedMetric extends Required<Omit<ProviderMetric, 'rawValue' | 'displayValue' | 'unit' | 'provenance'>> {
  readonly rawValue: number | string | boolean | null;
  readonly displayValue: string | null;
  readonly unit: string | null;
  readonly provenance: Readonly<Record<string, unknown>> | null;
}

export interface EvaluationResponse {
  readonly sessionId: string;
  readonly revision: number;
  readonly providerId: string;
  readonly providerVersion: string;
  readonly snapshotId: string | null;
  readonly snapshotManifestSha256: string | null;
  readonly inputFingerprint: string;
  readonly metrics: readonly NormalizedMetric[];
  readonly provenance: Readonly<Record<string, unknown>>;
  readonly timing: Readonly<{ durationMs: number }>;
  readonly cache: Readonly<{ hit: boolean; key: string }>;
}

export interface ChangeRequest extends EvaluationOptions {
  readonly expectedRevision: number;
  readonly changes: readonly BuildChange[];
}

export interface PreviewResponse {
  readonly sessionId: string;
  readonly revision: number;
  readonly previewToken: string;
  readonly baseBuildFingerprint: string;
  readonly candidateBuildFingerprint: string;
  readonly before: readonly NormalizedMetric[];
  readonly after: readonly NormalizedMetric[];
  readonly delta: readonly Readonly<Record<string, unknown>>[];
  readonly provenance: Readonly<Record<string, unknown>>;
}

export interface CommitRequest extends ChangeRequest { readonly previewToken: string; }

export const CONTRACT_VERSION: 'd4-rulekit-application/v1';

export type ApplicationErrorCode =
  | 'INVALID_INPUT' | 'PROVIDER_NOT_FOUND' | 'PROVIDER_UNAVAILABLE'
  | 'SESSION_NOT_FOUND' | 'SESSION_CLOSED' | 'SESSION_QUARANTINED' | 'SESSION_EXPIRED'
  | 'QUOTA_EXCEEDED' | 'REVISION_CONFLICT' | 'STALE_PREVIEW' | 'UNSUPPORTED_CHANGE'
  | 'PROVIDER_FAILURE' | 'RECOVERY_FAILED' | 'TIMEOUT' | 'CANCELLED';

export class ApplicationError extends Error {
  readonly code: ApplicationErrorCode;
  readonly details?: Readonly<Record<string, unknown>>;
}

export const ERROR_CODES: Readonly<Record<ApplicationErrorCode, ApplicationErrorCode>>;

export class D4RuleKitApplication {
  constructor(options: ApplicationOptions);
  listProviders(): readonly Readonly<Record<string, unknown>>[];
  createSession(options: CreateSessionOptions): Promise<SessionView>;
  evaluate(sessionId: string, options?: EvaluationOptions): Promise<EvaluationResponse>;
  previewChanges(sessionId: string, request: ChangeRequest): Promise<PreviewResponse>;
  commitChanges(sessionId: string, request: CommitRequest): Promise<Readonly<{ session: SessionView; result: EvaluationResponse }>>;
  resetSession(sessionId: string, options?: EvaluationOptions & { expectedRevision?: number }): Promise<SessionView>;
  getSession(sessionId: string): SessionView;
  closeSession(sessionId: string): Promise<Readonly<{ sessionId: string; closed: true; alreadyClosed: boolean }>>;
}
