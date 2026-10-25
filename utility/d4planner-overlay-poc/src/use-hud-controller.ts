import { useEffect, useRef, useState } from "react";
import type { HudDataEvent, IHudDataSource } from "./hud-data-source";
import type { HudSnapshot, SelectionResult, TargetListEntry } from "./hud-model";

function acceptsSnapshot(current: HudSnapshot | null, next: HudSnapshot): boolean {
  if (!current) return true;
  if (current.backend.runtimeInstanceId !== next.backend.runtimeInstanceId || current.backend.generation !== next.backend.generation) return true;
  return next.hudRevision >= current.hudRevision;
}

export function useHudController(source: IHudDataSource) {
  const [snapshot, setSnapshot] = useState<HudSnapshot | null>(null);
  const [targets, setTargets] = useState<TargetListEntry[]>([]);
  const [connection, setConnection] = useState<"CONNECTING" | "CONNECTED" | "DISCONNECTED">("CONNECTING");
  const [error, setError] = useState<string | null>(null);
  const [pendingTarget, setPendingTarget] = useState<{ targetId: string; contentSha256: string } | null>(null);
  const selectionToken = useRef(0);

  useEffect(() => {
    let mounted = true;
    let disconnect: (() => void) | undefined;
    const listener = (event: HudDataEvent) => {
      if (!mounted) return;
      if (event.type === "CONNECTION") {
        setConnection(event.state);
        if (event.state === "DISCONNECTED") setError(event.reason ?? "Connection lost");
      } else if (event.type === "TARGETS") {
        setTargets(event.targets);
      } else {
        setSnapshot(current => acceptsSnapshot(current, event.snapshot) ? event.snapshot : current);
        setPendingTarget(current => {
          if (!current) return null;
          const target = event.snapshot.context.target;
          return target?.targetId === current.targetId && target.contentSha256 === current.contentSha256 ? null : current;
        });
      }
    };
    source.connect(listener).then(stop => { if (mounted) disconnect = stop; else stop(); }).catch(reason => {
      if (mounted) { setConnection("DISCONNECTED"); setError(String(reason)); }
    });
    return () => { mounted = false; disconnect?.(); };
  }, [source]);

  async function refreshTargets() {
    try { await source.refreshTargets(); setError(null); } catch (reason) { setError(String(reason)); }
  }

  async function selectTarget(entry: TargetListEntry) {
    if (entry.validation !== "VALID") return;
    const token = ++selectionToken.current;
    setPendingTarget({ targetId: entry.targetId, contentSha256: entry.contentSha256 });
    setError(null);
    let result: SelectionResult;
    try {
      result = await source.selectTarget({ targetId: entry.targetId, expectedSha256: entry.contentSha256 });
    } catch (reason) {
      if (token === selectionToken.current) { setPendingTarget(null); setError(String(reason)); }
      return;
    }
    if (token !== selectionToken.current) return;
    if (result.status !== "ACTIVATED") {
      setPendingTarget(null);
      setError(result.message);
    } else if (result.targetId !== entry.targetId || result.contentSha256 !== entry.contentSha256) {
      setPendingTarget(null);
      setError("Target activation acknowledgement does not match the requested ID/hash");
    }
    // ACTIVATED still waits for the authoritative snapshot with the matching binding.
  }

  return { snapshot, targets, connection, error, pendingTargetId: pendingTarget?.targetId ?? null, refreshTargets, selectTarget };
}
