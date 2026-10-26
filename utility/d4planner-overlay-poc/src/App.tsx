import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { productionHudDataSource, type IHudDataSource } from "./hud-data-source";
import type { AssessmentStatus, CriterionComparison, EquipmentRow, TypedValue } from "./hud-model";
import { useHudController } from "./use-hud-controller";
import "./App.css";

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
  const source = useMemo(() => dataSource ?? productionHudDataSource(), [dataSource]);
  const hud = useHudController(source);
  const [expanded, setExpanded] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null);
  const [affixOpen, setAffixOpen] = useState(false);
  const [effectOpen, setEffectOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const snapshot = hud.snapshot;
  const selected = snapshot?.equipment.find(row => row.slotId === selectedSlot) ?? null;

  useEffect(() => {
    const width = !expanded || !snapshot ? 280 : selected ? 886 : 544;
    invoke("set_overlay_extent", { width, height: selected ? 620 : 560 }).catch(() => undefined);
  }, [expanded, selected, snapshot]);

  useEffect(() => {
    if (!selectedSlot || snapshot?.equipment.some(row => row.slotId === selectedSlot)) return;
    setSelectedSlot(null);
  }, [snapshot, selectedSlot]);

  useEffect(() => {
    if (hud.connection !== "CONNECTED" || snapshot?.context.state !== "BOUND"
      || snapshot.health.scoreFreshness !== "CURRENT" || snapshot.score.status !== "SCORED") return;
    const modelUpdatedAt = new Date().toISOString();
    const frame = requestAnimationFrame(() => {
      invoke("report_hud_pipeline", {
        snapshot,
        modelUpdatedAt,
        visibleRenderedAt: new Date().toISOString(),
      }).catch(() => undefined);
    });
    return () => cancelAnimationFrame(frame);
  }, [hud.connection, snapshot]);

  function resetComparison() {
    setSelectedSlot(null); setAffixOpen(false); setEffectOpen(false); setShowAll(false);
  }

  async function drag(event: React.MouseEvent) {
    if (event.button === 0) await invoke("drag_overlay").catch(() => undefined);
  }

  const scoreText = snapshot?.score.status === "SCORED" && snapshot.score.value !== null
    ? String(halfUp(snapshot.score.value)) : "—";
  const targetName = snapshot?.context.target?.buildDisplayName ?? "SELECT TARGET";
  const current = hud.connection === "CONNECTED" && snapshot?.health.scoreFreshness === "CURRENT";

  return <main className="surface" data-connection={hud.connection}>
    <div className="panels">
      <section className="panel summary" aria-label="D4Planner Equipment HUD">
        <header className="summary-head" onMouseDown={drag}>
          <button className="summary-toggle" onClick={() => { setExpanded(value => !value); resetComparison(); }} aria-expanded={expanded}>
            <span className="target-title"><span className="bolt">ϟ</span>{targetName.toUpperCase()}</span>
            <span className="score"><b>{scoreText}</b><small>/100</small></span>
            <span className="issue-count">{snapshot?.score.failIssueCount ?? 0} issues · {snapshot?.score.warnCount ?? 0} warnings</span>
            <span className="chevron">{expanded ? "⌃" : "⌄"}</span>
          </button>
          <button className="menu-button" aria-label="Open target menu" aria-expanded={menuOpen} onClick={() => { setMenuOpen(value => !value); if (!menuOpen) void hud.refreshTargets(); }}>⋮</button>
          {menuOpen && <div className="target-menu" role="menu">
            <strong>▣ Target Build</strong>
            {hud.targets.length === 0 && <p className="empty-targets">No Target JSON files</p>}
            {hud.targets.map(entry => <button key={entry.targetId} role="menuitem" disabled={entry.validation !== "VALID" || hud.pendingTargetId !== null}
              aria-current={snapshot?.context.target?.targetId === entry.targetId}
              onClick={() => void hud.selectTarget(entry)}>
              <span>{entry.displayName}</span>
              <small>{entry.validation === "VALID" ? (hud.pendingTargetId === entry.targetId ? "Selecting…" : "Valid") : entry.errorCodes.join(", ")}</small>
            </button>)}
          </div>}
        </header>

        {!current && <div className={`freshness ${hud.connection.toLowerCase()}`} role="status">
          {hud.connection === "DISCONNECTED" ? "Disconnected — assessment is not current" : snapshot?.score.status === "NO_DATA" ? "NO DATA" : "Connecting…"}
        </div>}
        {hud.error && <div className="hud-error" role="alert">{hud.error}</div>}

        {expanded && <div className="summary-body">
          <button className="equipment-link" aria-pressed={selectedSlot !== null} onClick={() => { if (selectedSlot) resetComparison(); else if (snapshot?.equipment[0]) setSelectedSlot(snapshot.equipment[0].slotId); }}>
            <span className="shield">⬡</span><span><b>Equipment</b><small>{snapshot?.score.failIssueCount ?? 0} issues · {snapshot?.score.warnCount ?? 0} warnings</small></span>
            <span>{snapshot?.score.itemsPassing ?? 0}/{snapshot?.score.itemsTargeted ?? 0}</span><span>›</span>
          </button>
          <button className="pin" aria-pressed="true" onClick={() => void invoke("set_overlay_pin", { pinned: true })}>⌖ Pinned</button>
        </div>}
      </section>

      {expanded && snapshot && <aside className="panel equipment" aria-label="Equipment list">
        <div className="panel-title"><span>⬡ <b>Equipment</b></span><button aria-label="Close equipment" onClick={resetComparison}>×</button></div>
        <p>{targetName} · Select an item</p>
        {snapshot.equipment.length === 0 && <div className="empty-equipment">No Equipment assessment data</div>}
        {snapshot.equipment.map(row => <button className={`equipment-row ${selectedSlot === row.slotId ? "selected" : ""}`} key={row.slotId} onClick={() => { setSelectedSlot(row.slotId); setAffixOpen(false); setEffectOpen(false); setShowAll(false); }}>
          <span className={`status ${row.status.toLowerCase()}`}>{symbol(row.status)}</span>
          <span><b>{row.slotLabel}</b><small>{row.currentItem?.displayName ?? (row.currentPresence === "CONFIRMED_ABSENT" ? "Empty (confirmed)" : "Not observed")}</small></span><span>›</span>
        </button>)}
      </aside>}

      {expanded && selected && <Compare row={selected} targetName={targetName} affixOpen={affixOpen} effectOpen={effectOpen} showAll={showAll}
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
