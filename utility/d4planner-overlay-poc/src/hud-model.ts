export type AssessmentStatus = "PASS" | "FAIL" | "WARN" | "UNKNOWN";
export type TypedValue =
  | { type: "NUMBER"; value: number; unit: "PERCENT" | "FLAT" | "RANK" | "SECONDS" | "NONE" }
  | { type: "TEXT"; value: string; unit: "NONE" }
  | { type: "BOOLEAN"; value: boolean; unit: "NONE" };

export interface ParameterComparison {
  parameterId: string;
  label: string;
  comparator: "AT_LEAST" | "AT_MOST" | "EQUAL" | "BETWEEN" | "PRESENT";
  expected: TypedValue | { type: "NUMBER_RANGE"; minimum: number; maximum: number; unit: string } | { type: "PRESENCE"; value: true; unit: "NONE" };
  actual: TypedValue | null;
  status: Exclude<AssessmentStatus, "FAIL">;
  reasonCode: string;
}

export interface CriterionComparison {
  criterionId: string;
  targetOrder: number;
  kind: "AFFIX" | "EFFECT";
  label: string;
  displayText: string;
  core: boolean;
  status: AssessmentStatus;
  reasonCode: string;
  parameters: ParameterComparison[];
}

export interface EquipmentRow {
  slotId: string;
  slotLabel: string;
  targetItem: { itemId: string; displayName: string };
  currentItem: { itemId: string; displayName: string; observedAt: string; source: string } | null;
  currentPresence: "OBSERVED" | "CONFIRMED_ABSENT" | "UNKNOWN";
  status: AssessmentStatus;
  reasonCode: string;
  comparisons: CriterionComparison[];
}

export interface HudSnapshot {
  schemaVersion: "d4planner-hud/v1";
  hudRevision: number;
  producedAt: string;
  backend: { runtimeInstanceId: string; generation: number };
  context: {
    state: "STARTUP" | "TARGET_ONLY" | "CHARACTER_ONLY" | "BOUND" | "TARGET_UNAVAILABLE";
    character: { characterId: string; displayName: string; currentRevision: number } | null;
    target: { targetId: string; displayName: string; buildDisplayName: string; contentSha256: string; selectionRevision: number; policyVersion: string } | null;
    binding: { runtimeInstanceId: string; targetId: string; targetSha256: string; characterId: string; currentRevision: number; selectionRevision: number; policyVersion: string } | null;
    selectionError: { code: string; attemptedTargetId: string } | null;
  };
  health: { capture: "HEALTHY" | "STALE" | "UNKNOWN" | "ERROR"; scoreFreshness: "CURRENT" | "STALE" | "NO_DATA"; ruleKit: string };
  score: {
    status: "SCORED" | "NO_DATA";
    value: number | null;
    passedWeight: number;
    evaluableWeight: number;
    failIssueCount: number;
    warnCount: number;
    itemsPassing: number;
    itemsTargeted: number;
  };
  equipment: EquipmentRow[];
  recommendation: { action: string; displayText: string; reasonCodes: string[]; criterionIds: string[] } | null;
  provenance: { lastObservedAt: string | null; captureRevision: number | null };
}

export interface TargetListEntry {
  targetId: string;
  displayName: string;
  contentSha256: string;
  byteLength: number;
  validation: "VALID" | "INVALID";
  errorCodes: string[];
}

export type SelectionResult =
  | { status: "ACTIVATED"; targetId: string; contentSha256: string; selectionRevision: number }
  | { status: "TARGET_CHANGED" | "TARGET_NOT_FOUND" | "TARGET_INVALID" | "REJECTED"; targetId: string; message: string };
