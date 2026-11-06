export interface DomConfig {
  snapshotRoot: string; snapshotId: string; manifestSha256: string; executablePath: string;
  timeoutMs?: number; quietMs?: number;
}
export interface NativeBuildJson {
  schemaVersion: 'maxroll-native-build-export/v1'; format: 'MAXROLL_NATIVE_STATE';
  nativeState: Record<string, unknown>;
  integrity: { algorithm: 'sha256'; nativeStateSha256: string };
  [key: string]: unknown;
}
export interface DomMetric {
  id: string; name: string; section: string; rawValue: null;
  status: 'DISPLAY_OBSERVED' | 'NOT_RENDERED' | 'NOT_APPLICABLE';
  displayValue: string | null; displayNumber: number | null;
  precision?: { kind: 'DISPLAY_QUANTIZED'; quantum: number; lower: number; upper: number };
  selector?: string; inferredZero?: false;
}
export interface DomResult {
  schemaVersion: 'maxroll-dom-calculation/v1'; path: 'DOM'; status: 'DISPLAY_COMPLETE';
  evaluationId: string; inputFingerprint: string; metrics: DomMetric[]; additionalMetrics: DomMetric[];
  coverage: { requested: number; observed: number; notRendered: number; notApplicable: number; exactRaw: 0; allVisibleRows: number };
  completion: { kind: 'FRESH_DOCUMENT_NATIVE_READBACK_DOM_SETTLED'; quietMs: number; nativeReadbackSha256: string; loaderRequests: number; rawCalculationAttestation: false };
  provenance: { snapshotId: string; manifestSha256: string; gameVersion: string; offline: boolean; network: unknown };
  timingsMs: { startup: number; buildApply: number; calculation: number; domExtraction: number; endToEnd: number };
}
export class DomCalculationPath {
  constructor(config: DomConfig);
  start(): Promise<void>;
  evaluate(build: NativeBuildJson, options?: { metricIds?: string[] }): Promise<DomResult>;
  close(): Promise<void>;
}
