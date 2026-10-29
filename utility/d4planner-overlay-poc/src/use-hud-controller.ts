import { useEffect, useRef, useState } from "react";
import type { HudDataEvent, IHudDataSource } from "./hud-data-source";
import type { HudSnapshot, SelectionResult, TargetListEntry } from "./hud-model";

function acceptsSnapshot(current: HudSnapshot | null, next: HudSnapshot): boolean {
  if (!current) return true;
  if (next.backend.generation < current.backend.generation) return false;
  if (next.backend.generation > current.backend.generation) return true;
  if (current.backend.runtimeInstanceId !== next.backend.runtimeInstanceId) return false;
  return next.hudRevision >= current.hudRevision;
}

export function useHudController(source: IHudDataSource) {
  const [snapshot, setSnapshot] = useState<HudSnapshot | null>(null);
  const [targetListStatus, setTargetListStatus] = useState<'IDLE' | 'LOADING' | 'READY' | 'ERROR'>('IDLE');
  const [targetListError, setTargetListError] = useState<string | null>(null);
  const [targets, setTargets] = useState<TargetListEntry[]>([]);
  const [connection, setConnection] = useState<"CONNECTING" | "CONNECTED" | "DISCONNECTED">("CONNECTING");
  const [assessmentRenderable, setAssessmentRenderable] = useState(false);
  const [authoritative, setAuthoritative] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [pendingTarget, setPendingTarget] = useState<{ targetId: string; contentSha256: string } | null>(null);
  const snapshotRef = useRef<HudSnapshot | null>(null);
  const selectionToken = useRef(0);

  useEffect(() => {
    let mounted = true;
    let disconnect: (() => void) | undefined;
    const listener = (event: HudDataEvent) => {
      if (!mounted) return;
      if (event.type === "CONNECTION") {
        setConnection(event.state);
        setAuthoritative(false);
        if (event.state === "DISCONNECTED") setConnectionError(event.reason ?? "Connection lost");
      } else if (event.type === "ASSESSMENT_INVALIDATED") {
        setAssessmentRenderable(false);
        setAuthoritative(false);
      } else if (event.type === "TARGET_LIST_STATE") {
        setTargetListStatus(event.status);
        setTargetListError(event.error);
        if (event.status !== 'READY') setTargets([]);
      } else if (event.type === "TARGETS") {
        setTargetListStatus('READY');
        setTargetListError(null);
        setTargets(event.targets);
      } else {
        if (!acceptsSnapshot(snapshotRef.current, event.snapshot)) return;
        snapshotRef.current = event.snapshot;
        setSnapshot(event.snapshot);
        setAuthoritative(true);
        setAssessmentRenderable(true);
        setConnectionError(null);
        setPendingTarget(current => {
          if (!current) return null;
          const target = event.snapshot.context.target;
          return target?.targetId === current.targetId && target.contentSha256 === current.contentSha256 ? null : current;
        });
      }
    };
    source.connect(listener).then(stop => { if (mounted) disconnect = stop; else stop(); }).catch(reason => {
      if (mounted) { setConnection("DISCONNECTED"); setConnectionError(String(reason)); }
    });
    return () => { mounted = false; disconnect?.(); };
  }, [source]);

  async function refreshTargets() {
    setTargetListStatus('LOADING'); setTargetListError(null); setTargets([]);
    try { await source.refreshTargets(); } catch (reason) {
      setTargetListStatus('ERROR'); setTargetListError(String(reason));
    }
  }

  async function selectTarget(entry: TargetListEntry) {
    if (entry.validation !== "VALID") return;
    const token = ++selectionToken.current;
    setPendingTarget({ targetId: entry.targetId, contentSha256: entry.contentSha256 });
    setOperationError(null);
    let result: SelectionResult;
    try {
      result = await source.selectTarget({ targetId: entry.targetId, expectedSha256: entry.contentSha256 });
    } catch (reason) {
      if (token === selectionToken.current) { setPendingTarget(null); setOperationError(String(reason)); }
      return;
    }
    if (token !== selectionToken.current) return;
    if (result.status !== "ACTIVATED") {
      setPendingTarget(null);
      setOperationError(result.message);
    } else if (result.targetId !== entry.targetId || result.contentSha256 !== entry.contentSha256) {
      setPendingTarget(null);
      setOperationError("Target activation acknowledgement does not match the requested ID/hash");
    }
    // ACTIVATED still waits for the authoritative snapshot with the matching binding.
  }

  return { snapshot, targets, targetListStatus, targetListError, connection, authoritative, assessmentRenderable, error: operationError ?? connectionError, pendingTargetId: pendingTarget?.targetId ?? null, refreshTargets, selectTarget };
}
