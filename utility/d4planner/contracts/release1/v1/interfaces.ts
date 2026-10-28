/** Normative port shapes for d4planner-r1-contract/1.0.0-candidate.5.
 * Language-neutral ports, not a runtime SDK. Implementations preserve boundaries;
 * schemas/ is the sole source of serialized field definitions and required fields.
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

/** Opaque port payloads, NOT a second serialized-payload definition.
 * References below are relative to schemas/. JSON Schemas and ADR semantic
 * invariants are normative. A boundary validator produces these values; adapters
 * may generate their implementation-language types from the schemas.
 * The unique-symbol brand is compile-time only and is never sent on the wire.
 */
declare const validatedSchema: unique symbol;
export type SchemaPayload<Reference extends string> = {
  readonly [validatedSchema]: Reference;
};
export type TargetListEntry = SchemaPayload<'ws.schema.json#/$defs/targetEntry'>;
export type ApprovedWeightProfile = SchemaPayload<'target.schema.json#/$defs/weightProfile'>;
export type HudContextState = SchemaPayload<'ws.schema.json#/$defs/expectedKnownContext/properties/state'>;
export type TypedValue = SchemaPayload<'hud.schema.json#/$defs/typedValue'>;
export type HudSnapshot = SchemaPayload<'hud.schema.json#'>;
export type DiscoverActiveContextRequest = SchemaPayload<'ws.schema.json#/$defs/discoveryRequestContext'>;
export type KnownHudContext = SchemaPayload<'ws.schema.json#/$defs/expectedKnownContext'>;
export type ResyncKnownContextRequest = SchemaPayload<'ws.schema.json#/$defs/resyncRequestContext'>;
export type SnapshotRequestContext = SchemaPayload<'ws.schema.json#/$defs/snapshotRequestContext'>;
export type AuthoritativeHudSnapshot = SchemaPayload<'ws.schema.json#/$defs/snapshot'>;
export type IncrementalHudUpdate = SchemaPayload<'ws.schema.json#/$defs/update'>;

/** Operation timeout is distinct from WS session/lease lifetime. */
export interface SnapshotRecoveryPolicy {
  /** Both values are finite positive deployment configuration. */
  readonly requestTimeoutMs: number;
  readonly maxDiscoveryAttempts: number;
}

/** Retained across a transport reconnect; never retained across backend identity change. */
export interface HudReconnectCheckpoint {
  readonly runtimeInstanceId: string;
  readonly backendGeneration: number;
  readonly hudRevisionHighWater: number;
  readonly knownContext: KnownHudContext;
}

export type HelloAcceptedDisposition =
  | 'SAME_BACKEND_RECONNECT'
  | 'NEW_BACKEND_IDENTITY';

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
