import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { labelForMode, nextInteractive, type OverlayStatus } from "./overlay-mode";

const mockData = [
  { name: "Equipment", score: "8 / 10", percent: 80 },
  { name: "Charms", score: "6 / 8", percent: 75 },
];

export default function App() {
  const [status, setStatus] = useState<OverlayStatus>({ interactive: true });
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let mounted = true;
    let sawEvent = false;
    let unlisten: UnlistenFn | undefined;
    async function initialize() {
      unlisten = await listen<OverlayStatus>("overlay-mode-changed", (event) => {
        sawEvent = true;
        if (mounted) setStatus(event.payload);
      });
      const current = await invoke<OverlayStatus>("get_overlay_status");
      if (mounted) {
        // A global hotkey might have fired while get_overlay_status was pending.
        // Do not replace its newer event with a stale initial snapshot.
        if (!sawEvent) setStatus(current);
        setReady(true);
      }
    }
    initialize().catch((reason: unknown) => {
      if (mounted) setError(String(reason));
    });
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, []);

  async function setMode() {
    if (!ready || busy || !status.interactive) return;
    setBusy(true);
    try {
      setStatus(await invoke<OverlayStatus>("set_overlay_mode", {
        interactive: nextInteractive(status),
      }));
      setError(null);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function drag(event: React.MouseEvent) {
    if (!status.interactive || event.button !== 0) return;
    try {
      await invoke("drag_overlay");
    } catch (reason) {
      setError(String(reason));
    }
  }

  return (
    <main className="surface">
      <section className="hud" aria-label="D4 Planner Overlay POC">
        <header className="hud-header" onMouseDown={drag}>
          <div className="identity">
            <span className="bolt" aria-hidden>ϟ</span>
            <div><strong>CHARGE BOLT</strong><small>D4 PLANNER · POC</small></div>
          </div>
          <span className="live"><span className="dot" /> MOCK</span>
        </header>

        <div className="body">
          <div className="score-row">
            <div><span className="big">78</span><span className="total"> / 100</span></div>
            <span className="issues">3 issues</span>
          </div>
          <div className="score-rail"><span /></div>
          <div className="metrics">
            {mockData.map((item) => (
              <div className="metric" key={item.name}>
                <span>{item.name}</span>
                <div className="mini"><span style={{ width: String(item.percent) + "%" }} /></div>
                <b>{item.score}</b>
              </div>
            ))}
          </div>
        </div>

        <footer>
          <span className="state">{ready ? labelForMode(status) : "CONNECTING"}</span>
          <button disabled={!status.interactive || !ready || busy} onClick={setMode}>
            Enable pass-through
          </button>
        </footer>
      </section>
      <div className="hint">Ctrl + Shift + F10: toggle · F11: exit</div>
      {error && <div className="error" role="alert">{error}</div>}
    </main>
  );
}
