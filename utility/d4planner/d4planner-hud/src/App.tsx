import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { productionHudDataSource, type IHudDataSource } from "./hud-data-source";
import type { AssessmentStatus, CriterionComparison, EquipmentRow, TypedValue } from "./hud-model";
import { useHudController } from "./use-hud-controller";
import "./App.css";
import { ReportIssue } from "./ReportIssue";
import { MenuIcon } from "./MenuIcon";

function symbol(status: AssessmentStatus) {
  return status === "PASS" ? "✓" : status === "FAIL" ? "✕" : status === "WARN" ? "⚠" : "?";
}

function displayValue(value: TypedValue | CriterionComparison["parameters"][number]["expected"] | null) {
  if (!value) return "Not observed";
  if (value.type === "NUMBER_RANGE") return `${value.minimum}–${value.maximum} ${value.unit}`;
  if (value.type === "PRESENCE") return "Present";
  if (value.type === "BOOLEAN") return value.value ? "Yes" : "No";
  if (value.type === "TEXT") return value.value;
  const suffix = value.unit === "PERCENT" ? "%" : value.unit === "RANK" ? " ranks" : value.unit === "SECONDS" ? "s" : "";
  return `${value.value}${suffix}`;
}

function halfUp(value: number) { return Math.floor(value + 0.5); }

export default function App({ dataSource }: { dataSource?: IHudDataSource }) {
  const [rendererInstanceId] = useState(() => crypto.randomUUID());
  const source = useMemo(() => dataSource ?? productionHudDataSource(), [dataSource]);
  const hud = useHudController(source);
  const [expanded, setExpanded] = useState(true);
  const [equipmentOpen, setEquipmentOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportTab, setReportTab] = useState<"report" | "logs">("report");
  const [menuOpen, setMenuOpen] = useState(false);
  const plannerPending = useRef(false);
  const [plannerOpening, setPlannerOpening] = useState(false);
  const [plannerError, setPlannerError] = useState<string | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  const [affixOpen, setAffixOpen] = useState(false);
  const [effectOpen, setEffectOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const snapshot = hud.assessmentRenderable ? hud.snapshot : null;
  const selected = snapshot?.equipment.find(row => row.slotId === selectedSlot) ?? null;

  useEffect(() => {
    const width = reportOpen ? 656 : !expanded || !equipmentOpen || !snapshot ? 280 : selected ? 886 : 544;
    invoke("set_overlay_extent", { width, height: reportOpen || selected ? 620 : 560 }).catch(() => undefined);
  }, [expanded, equipmentOpen, selected, snapshot, reportOpen]);

  useEffect(() => {
    if (!selectedSlot || snapshot?.equipment.some(row => row.slotId === selectedSlot)) return;
    setSelectedSlot(null);
  }, [snapshot, selectedSlot]);

  useEffect(() => {
    invoke("report_webview_diagnostic", {
      phase: "HUD_STATE",
      detail: JSON.stringify({
        connection: hud.connection,
        error: hud.error,
        hudRevision: snapshot?.hudRevision ?? null,
        contextState: snapshot?.context.state ?? null,
        scoreStatus: snapshot?.score.status ?? null,
      }),
    }).catch(() => undefined);
  }, [hud.connection, hud.error, snapshot]);

  useEffect(() => {
    if (!hud.authoritative || hud.connection !== "CONNECTED" || snapshot?.context.state !== "BOUND"
      || snapshot.health.scoreFreshness !== "CURRENT" || snapshot.score.status !== "SCORED") return;
    if (!hud.timing) return;
    let paintedFrame = 0;
    const frame = requestAnimationFrame(() => {
      paintedFrame = requestAnimationFrame(() => {
        invoke("report_hud_pipeline", {
          snapshot,
          rendererInstanceId,
          modelUpdatedAt: hud.timing!.modelUpdatedAt,
          wsReceivedAt: hud.timing!.wsReceivedAt ?? null,
          visibleRenderedAt: new Date().toISOString(),
        }).catch(() => undefined);
      });
    });
    return () => { cancelAnimationFrame(frame); cancelAnimationFrame(paintedFrame); };
  }, [hud.connection, hud.authoritative, snapshot, hud.timing, rendererInstanceId]);

  function resetComparison() {
    setSelectedSlot(null); setAffixOpen(false); setEffectOpen(false); setShowAll(false);
  }

  function openSupport(tab: "report" | "logs") {
    setReportTab(tab); setReportOpen(true); setMenuOpen(false); setEquipmentOpen(false); resetComparison();
  }

  async function createBuild() {
    if (plannerPending.current) return;
    plannerPending.current = true; setPlannerOpening(true); setPlannerError(null);
    try {
      await invoke("open_local_planner");
      setMenuOpen(false);
    } catch (error) {
      setMenuOpen(false); // Keep the failure message visible below the summary.
      const messages: Record<string, string> = {
        PLANNER_RELEASE_NOT_FOUND: "No compatible Planner UI snapshot release is available on GitHub.",
        PLANNER_RELEASE_ACCESS_DENIED: "Cannot access snapshot releases. Check the GitHub token in private/report-config.json.",
        PLANNER_DOWNLOAD_FAILED: "Snapshot download failed. Check your connection and try again.",
        PLANNER_RELEASE_UNTRUSTED: "Snapshot release integrity could not be verified.",
        PLANNER_DECRYPTION_KEY_REQUIRED: "Snapshot decryption key is missing. Configure private/snapshot-age-identity.txt.",
        PLANNER_DECRYPTION_FAILED: "Snapshot could not be decrypted or unpacked. Check the snapshot identity key.",
        PLANNER_RELEASE_ENUMERATION_LIMIT: "Snapshot release search exceeded its limit. Contact the maintainer.",
        PLANNER_SNAPSHOT_UNAVAILABLE: "Local Planner snapshot is unavailable. Provision a validated UI package.",
        PLANNER_SNAPSHOT_UNTRUSTED: "Local Planner snapshot could not be verified.",
        PLANNER_START_FAILED: "Local Planner could not start. Please try again.",
        PLANNER_HEALTH_FAILED: "Local Planner did not become ready. Please try again.",
        PLANNER_PORT_CONFLICT: "Local Planner port is in use. The other service was left running.",
        PLANNER_BUSY: "Local Planner is busy. Please try again.",
        PLANNER_UNAVAILABLE: "Local Planner is unavailable. Check the application runtime.",
      };
      setPlannerError(messages[String(error)] ?? messages.PLANNER_UNAVAILABLE);
    } finally { plannerPending.current = false; setPlannerOpening(false); }
  }

  async function drag(event: React.MouseEvent) {
    // Menu operations must receive their pointer-up/click; native dragging captures it.
    if (event.target instanceof Element && event.target.closest(".menu-button, .target-menu")) return;
    if (event.button === 0) await invoke("drag_overlay").catch(() => undefined);
  }

  const scoreText = snapshot?.score.status === "SCORED" && snapshot.score.value !== null
    ? String(halfUp(snapshot.score.value)) : "—";
  const targetName = snapshot?.context.target?.buildDisplayName ?? "SELECT TARGET";
  const current = hud.authoritative && hud.connection === "CONNECTED" && snapshot?.health.scoreFreshness === "CURRENT";

  return <main className="surface" data-connection={hud.connection} data-freshness={current ? "CURRENT" : "STALE"}>
    <div className="panels">
      <section className="panel summary" aria-label="D4Planner Equipment HUD">
        <header className="summary-head" onMouseDown={drag}>
          <button className="summary-toggle" onClick={() => { setExpanded(value => !value); setEquipmentOpen(false); resetComparison(); }} aria-expanded={expanded}>
            <span className="target-title"><span className="bolt">ϟ</span>{targetName.toUpperCase()}</span>
            <span className="score"><b>{scoreText}</b><small>/100</small></span>
            <span className="issue-count">{snapshot?.score.failIssueCount ?? 0} issues · {snapshot?.score.warnCount ?? 0} warnings</span>
            <span className="chevron">{expanded ? "⌃" : "⌄"}</span>
          </button>
          <button className="menu-button" aria-label="Open target menu" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => { setMenuOpen(value => !value); if (!menuOpen) void hud.refreshTargets(); }}><MenuIcon name="more" size={17} /></button>
          {menuOpen && <div className="target-menu" role="menu" aria-label="HUD actions">
            <button className="menu-action create-build" role="menuitem" aria-label={plannerOpening ? "Opening Planner…" : "Create Build"} aria-describedby="planner-action-description" disabled={plannerOpening} aria-busy={plannerOpening} onClick={() => void createBuild()}>
              <MenuIcon name="create" size={15} />
              <span className="menu-action-copy"><span>{plannerOpening ? "Opening Planner…" : "Create Build"}</span><small id="planner-action-description">Open Local Planner</small></span>
              <MenuIcon name="chevron" size={13} />
            </button>
            <strong className="target-menu-heading"><MenuIcon name="folder" size={14} /> Target Build</strong>
            {hud.targetListStatus === "LOADING" && <p role="status">Loading Targets…</p>}
            {hud.targetListStatus === "ERROR" && <div>
              <p role="alert">Target listing failed: {hud.targetListError}</p>
              <button onClick={() => void hud.refreshTargets()}>Retry Target list</button>
            </div>}
            {hud.targetListStatus === "READY" && hud.targets.length === 0 && <p className="empty-targets">No Target JSON files</p>}
            {hud.targets.map(entry => <button className="target-choice" key={entry.targetId} role="menuitem" disabled={entry.validation !== "VALID" || hud.pendingTargetId !== null}
              aria-current={snapshot?.context.target?.targetId === entry.targetId}
              onClick={() => { setMenuOpen(false); setEquipmentOpen(false); resetComparison(); void hud.selectTarget(entry); }}>
              <span>{entry.displayName}{snapshot?.context.target?.targetId === entry.targetId && <span aria-hidden="true">{"  ✓"}</span>}</span>
              {entry.validation !== "VALID" ? <small>{entry.errorCodes.join(", ")}</small> : hud.pendingTargetId === entry.targetId && <small>Selecting…</small>}
            </button>)}
            <div className="target-menu-footer">Validated JSON targets</div>
            <div className="support-heading">Support &amp; diagnostics</div>
            <button className="menu-action report-action" role="menuitem" aria-label="Report Issue" aria-describedby="report-action-description" onClick={() => openSupport("report")}>
              <MenuIcon name="bug" size={15} />
              <span className="menu-action-copy"><span>Report Issue</span><small id="report-action-description">Open report window</small></span>
              <MenuIcon name="chevron" size={13} />
            </button>
            <button className="collect-logs" role="menuitem" onClick={() => openSupport("logs")}><MenuIcon name="logs" size={14} /> Collect Logs</button>
            <p className="support-note">Review data before sharing</p>
          </div>}
        </header>

        {!current && <div className={`freshness ${hud.connection.toLowerCase()}`} role="status">
          {snapshot?.score.status === "NO_DATA" ? "NO DATA" : snapshot ? (hud.connection === "DISCONNECTED" ? "OFFLINE — Last-known assessment is not current" : "Last-known assessment is not current — resynchronizing") : (hud.connection === "DISCONNECTED" ? "NO DATA" : "Connecting…")}
        </div>}
        {snapshot?.health.captureRuntime && <div className="freshness" role="status">
          Capture: {snapshot.health.captureRuntime.state === "WAITING_FOR_GAME"
            ? "Waiting for Diablo IV"
            : snapshot.health.captureRuntime.state === "RUNNING"
              ? "Active — waiting for identified character data"
              : snapshot.health.captureRuntime.detail}
        </div>}
        {hud.error && <div className="hud-error" role="alert">{hud.error}</div>}
        {plannerOpening && <div className="freshness" role="status">Opening Planner…</div>}
        {plannerError && <div className="hud-error" role="alert">{plannerError}</div>}

        {expanded && <div className="summary-body">
          <button className="equipment-link" aria-pressed={equipmentOpen} onClick={() => { setEquipmentOpen(value => !value); resetComparison(); }}>
            <span className="shield">⬡</span><span><b>Equipment</b><small>{snapshot?.score.failIssueCount ?? 0} issues · {snapshot?.score.warnCount ?? 0} warnings</small></span>
            <span>{snapshot?.score.itemsPassing ?? 0}/{snapshot?.score.itemsTargeted ?? 0}</span><span>›</span>
          </button>
          <button className="pin" aria-pressed="true" onClick={() => void invoke("set_overlay_pin", { pinned: true })}>⌖ Pinned</button>
        </div>}
      </section>

      {reportOpen && <ReportIssue activeTab={reportTab} onTabChange={setReportTab} onClose={() => setReportOpen(false)} />}
      {expanded && equipmentOpen && snapshot && <aside className="panel equipment" aria-label="Equipment list">
        <div className="panel-title"><span>⬡ <b>Equipment</b></span><button aria-label="Close equipment" onClick={() => { setEquipmentOpen(false); resetComparison(); }}>×</button></div>
        <p>{targetName} · Select an item</p>
        {snapshot.equipment.length === 0 && <div className="empty-equipment">No Equipment assessment data</div>}
        {snapshot.equipment.map(row => <button className={`equipment-row ${selectedSlot === row.slotId ? "selected" : ""}`} key={row.slotId} onClick={() => { setSelectedSlot(row.slotId); setAffixOpen(false); setEffectOpen(false); setShowAll(false); }}>
          <span className={`status ${row.status.toLowerCase()}`}>{symbol(row.status)}</span>
          <span><b>{row.slotLabel}</b><small>{row.currentItem?.displayName ?? (row.currentPresence === "CONFIRMED_ABSENT" ? "Empty (confirmed)" : "Not observed")}</small></span><span>›</span>
        </button>)}
      </aside>}

      {expanded && equipmentOpen && selected && <Compare row={selected} targetName={targetName} affixOpen={affixOpen} effectOpen={effectOpen} showAll={showAll}
        onAffix={() => setAffixOpen(value => !value)} onEffect={() => setEffectOpen(value => !value)} onFilter={setShowAll} onClose={() => setSelectedSlot(null)} recommendation={snapshot?.recommendation?.displayText ?? "Insufficient evidence"} />}
    </div>
  </main>;
}

function Compare({ row, targetName, affixOpen, effectOpen, showAll, onAffix, onEffect, onFilter, onClose, recommendation }: {
  row: EquipmentRow; targetName: string; affixOpen: boolean; effectOpen: boolean; showAll: boolean;
  onAffix(): void; onEffect(): void; onFilter(value: boolean): void; onClose(): void; recommendation: string;
}) {
  const affixes = row.comparisons.filter(item => item.kind === "AFFIX");
  const effects = row.comparisons.filter(item => item.kind === "EFFECT");
  return <aside className="panel compare" aria-label="Item comparison">
    <div className="panel-title"><span><b>{row.slotLabel}</b> <span className={`status ${row.status.toLowerCase()}`}>{symbol(row.status)}</span></span><button aria-label="Close item comparison" onClick={onClose}>×</button></div>
    <p>{row.currentItem?.displayName ?? "Current unknown"} vs {row.targetItem.displayName} · {targetName}</p>
    <ComparisonSection title="Affixes" rows={affixes} open={affixOpen} showAll={showAll} onToggle={onAffix} onFilter={onFilter} />
    <ComparisonSection title="Effects" rows={effects} open={effectOpen} showAll={showAll} onToggle={onEffect} onFilter={onFilter} />
    <div className="recommendation"><small>⚒ RECOMMENDATION</small><b>{recommendation}</b></div>
  </aside>;
}

function ComparisonSection({ title, rows, open, showAll, onToggle, onFilter }: {
  title: string; rows: CriterionComparison[]; open: boolean; showAll: boolean; onToggle(): void; onFilter(value: boolean): void;
}) {
  const issues = rows.filter(row => row.status === "FAIL" || row.status === "WARN");
  const visible = showAll ? rows : issues;
  return <section className="comparison-section">
    <button className="comparison-toggle" aria-expanded={open} onClick={onToggle}><b>{title}</b><span>{issues.length} issues</span><span>{open ? "⌃" : "⌄"}</span></button>
    {open && <div className="comparison-content">
      <div className="filter"><b>CURRENT ↔ TARGET</b><span><button aria-pressed={!showAll} onClick={() => onFilter(false)}>Issues only</button><button aria-pressed={showAll} onClick={() => onFilter(true)}>All</button></span></div>
      {visible.length === 0 && <p>No matching criteria</p>}
      {visible.map(criterion => <article className="criterion" key={criterion.criterionId}>
        <div className={`criterion-reason ${criterion.status.toLowerCase()}`}>{symbol(criterion.status)} {criterion.label} · {criterion.reasonCode}</div>
        <p>{criterion.displayText}</p>
        {criterion.parameters.map(parameter => <div className="parameter" key={parameter.parameterId}>
          <span><small>Current</small><b>{displayValue(parameter.actual)}</b></span>
          <span><small>Target</small><b>{displayValue(parameter.expected)}</b></span>
        </div>)}
      </article>)}
    </div>}
  </section>;
}
