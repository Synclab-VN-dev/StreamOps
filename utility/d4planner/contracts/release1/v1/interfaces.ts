/** Normative port shapes for d4planner-r1-contract/1.0.0-candidate.1.
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
  }>): Promise<unknown>;
}

/** Reads only durable committed BE state. FE never reads DB/files through it. */
export interface HudDataSource {
  snapshot(): Promise<unknown>;
  subscribe(afterHudRevision: number, sink: (snapshot: unknown) => Promise<void>): Promise<() => void>;
}

export interface HudPublisher {
  publishAfterCommit(snapshot: unknown): Promise<void>;
  forceResync(reason: 'REVISION_GAP' | 'BACKEND_GENERATION_CHANGED' | 'SLOW_CONSUMER'): Promise<void>;
}
