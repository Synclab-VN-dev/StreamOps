/** Normative port shapes for d4planner-r1-contract/1.0.0-candidate.4.
 * Implementations may use another language, but must preserve these boundaries.
 */

export type ProcessState =
  | 'STOPPED' | 'STARTING' | 'READY' | 'STOPPING' | 'EXITED' | 'FAILED';

export interface LaunchSpecification {
  readonly executable: string;
  readonly args: readonly string[];
  readonly workingDirectory: string;
  readonly environmentAllowList: Readonly<Record<string, string>>;
  readonly parentInstanceId: string;
  readonly generation: number;
  readonly readiness: Readonly<{ protocol: string; version: string; timeoutMs: number }>;
  readonly gracefulStopTimeoutMs: number;
  readonly killTimeoutMs: number;
}

export interface SpawnedProcess {
  readonly childInstanceId: string;
  readonly pid: number;
  readonly generation: number;
  waitForExit(): Promise<Readonly<{ exitCode: number | null; reason: string }>>;
}

/** OS/process mechanics only. No score, SQL, WebSocket, or Rule Kit calls. */
export interface ProcessDriver {
  spawn(specification: LaunchSpecification): Promise<SpawnedProcess>;
  requestGracefulStop(child: SpawnedProcess): Promise<void>;
  terminateOwnedChild(child: SpawnedProcess): Promise<void>;
}

/** Template Method lifecycle; start/stop calls are idempotent and serialized. */
export interface ManagedProcessTemplate {
  readonly ownerInstanceId: string;
  readonly state: ProcessState;
  readonly generation: number;
  start(): Promise<Readonly<{ state: 'READY'; childInstanceId: string; generation: number }>>;
  stop(reason: 'OWNER_EXIT' | 'RESTART' | 'USER_REQUEST'): Promise<void>;
  inspectHealth(): Promise<Readonly<{ ready: boolean; protocolVersion: string; reason: string }>>;
}

export interface BackendProcessWrapper extends ManagedProcessTemplate {}
export interface RuleKitProcessWrapper extends ManagedProcessTemplate {}

export interface RuleKitSessionRef {
  readonly workerInstanceId: string;
  readonly workerGeneration: number;
  readonly sessionId: string;
  readonly leaseExpiresAt: string;
}

/** The existing eight Application APIs; lifecycle is owned by the wrapper. */
export interface RuleKitClient {
  listProviders(): Promise<readonly unknown[]>;
  createSession(request: unknown): Promise<RuleKitSessionRef>;
  evaluate(sessionId: string, request?: unknown): Promise<unknown>;
  previewChanges(sessionId: string, request: unknown): Promise<unknown>;
  commitChanges(sessionId: string, request: unknown): Promise<unknown>;
  resetSession(sessionId: string, request?: unknown): Promise<unknown>;
  getSession(sessionId: string): Promise<unknown>;
  closeSession(sessionId: string): Promise<void>;
}

export interface TargetListEntry {
  readonly targetId: string;
  readonly displayName: string;
  readonly contentSha256: string;
  readonly byteLength: number;
  readonly validation: 'VALID' | 'INVALID';
  readonly errorCodes: readonly string[];
}

export interface ApprovedWeightProfile {
  readonly profileId: 'r1-equipment-weights/1.0.0';
  readonly coreWeight: 3;
  readonly nonCoreWeight: 1;
  readonly approval: Readonly<{
    status: 'APPROVED';
    decisionRef: 'https://github.com/Synclab-VN-dev/StreamOps/issues/138#issuecomment-6394334041';
  }>;
}

export type HudContextState =
  | 'STARTUP' | 'TARGET_ONLY' | 'CHARACTER_ONLY' | 'BOUND' | 'TARGET_UNAVAILABLE';

export type TypedValue =
  | Readonly<{ type: 'NUMBER'; value: number; unit: 'PERCENT' | 'FLAT' | 'RANK' | 'SECONDS' | 'NONE' }>
  | Readonly<{ type: 'TEXT'; value: string; unit: 'NONE' }>
  | Readonly<{ type: 'BOOLEAN'; value: boolean; unit: 'NONE' }>;

export interface HudSnapshot {
  readonly schemaVersion: 'd4planner-hud/v1';
  readonly hudRevision: number;
  readonly backend: Readonly<{ runtimeInstanceId: string; generation: number }>;
  readonly context: Readonly<{
    state: HudContextState;
    character: Readonly<{ characterId: string; displayName: string; currentRevision: number }> | null;
    target: Readonly<{ targetId: string; displayName: string; buildDisplayName: string;
      contentSha256: string; selectionRevision: number; policyVersion: string }> | null;
    binding: Readonly<{ runtimeInstanceId: string; characterId: string; currentRevision: number;
      targetId: string; targetSha256: string; selectionRevision: number;
      policyVersion: string }> | null;
    selectionError: Readonly<{ code: 'TARGET_NOT_FOUND' | 'TARGET_CHANGED' | 'TARGET_INVALID';
      attemptedTargetId: string; occurredAt: string }> | null;
  }>;
  readonly score: Readonly<{ status: 'SCORED' | 'NO_DATA'; value: number | null;
    passedWeight: number; evaluableWeight: number; failIssueCount: number;
    warnCount: number; itemsPassing: number; itemsTargeted: number }>;
  readonly equipment: readonly unknown[];
}

export interface DiscoverActiveContextRequest {
  readonly mode: 'DISCOVER_ACTIVE_CONTEXT';
  readonly reason: 'INITIAL_CONNECTION' | 'BACKEND_GENERATION_CHANGED' |
    'KNOWN_CONTEXT_CHANGED' | 'TIMEOUT_RETRY';
  /** Starts at one; a timeout retry increments it and may not exceed policy. */
  readonly attempt: number;
  readonly runtimeInstanceId: string;
  readonly minimumHudRevision: number;
}

/** Operation timeout is distinct from WS session/lease lifetime. */
export interface SnapshotRecoveryPolicy {
  /** Both values are finite positive deployment configuration. */
  readonly requestTimeoutMs: number;
  readonly maxDiscoveryAttempts: number;
}

export interface KnownHudContext {
  readonly state: HudContextState;
  readonly characterId: string | null;
  readonly targetId: string | null;
  readonly selectionRevision: number | null;
}

export interface ResyncKnownContextRequest {
  readonly mode: 'RESYNC_KNOWN_CONTEXT';
  readonly runtimeInstanceId: string;
  readonly minimumHudRevision: number;
  /** Nulls here assert known absence according to state; they never mean wildcard. */
  readonly expectedContext: KnownHudContext;
}

export type SnapshotRequestContext = DiscoverActiveContextRequest | ResyncKnownContextRequest;

export interface AuthoritativeHudSnapshot {
  readonly authoritative: true;
  readonly correlationId: string;
  readonly backendGeneration: number;
  readonly subscriptionId: string;
  readonly subscriptionAfterRevision: number;
  readonly requestContext: SnapshotRequestContext;
  readonly hud: HudSnapshot;
}

export interface IncrementalHudUpdate {
  readonly backendGeneration: number;
  readonly subscriptionId: string;
  readonly previousHudRevision: number;
  readonly hud: HudSnapshot;
}

/** Paths never cross this boundary. IDs are resolved beneath configuredRoot. */
export interface TargetRepository {
  readonly configuredRoot: string;
  list(): Promise<readonly TargetListEntry[]>;
  activate(request: Readonly<{ targetId: string; expectedSha256: string }>):
    Promise<Readonly<{ targetId: string; contentSha256: string; selectionRevision: number }>>;
  getActive(): Promise<Readonly<{ targetId: string; contentSha256: string; selectionRevision: number }> | null>;
}

export interface EquipmentAssessmentService {
  assess(input: Readonly<{
    runtimeInstanceId: string;
    characterId: string;
    currentRevision: number;
    targetId: string;
    targetSha256: string;
    selectionRevision: number;
    policyVersion: string;
    currentEquipmentEvidence: unknown;
    target: unknown;
  }>): Promise<HudSnapshot>;
}

/** Reads only durable committed BE state. FE never reads DB/files through it. */
export interface HudDataSource {
  snapshot(requestId: string, context: SnapshotRequestContext): Promise<AuthoritativeHudSnapshot>;
  subscribe(subscriptionId: string, afterHudRevision: number,
    sink: (update: IncrementalHudUpdate) => Promise<void>): Promise<() => void>;
}

export interface HudPublisher {
  publishAfterCommit(snapshot: HudSnapshot): Promise<void>;
  forceResync(reason: 'REVISION_GAP' | 'BACKEND_GENERATION_CHANGED' | 'SLOW_CONSUMER'): Promise<void>;
}
