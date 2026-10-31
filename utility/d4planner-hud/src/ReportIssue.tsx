import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./report-issue.css";
export type Selection = {
  fe: boolean;
  be: boolean;
  rulekit: boolean;
  evidence: boolean;
  evidenceConsent: boolean;
};
type Preview = {
  consent?: Selection;
  description?: Description;
  reportId: string;
  runId: string;
  bytes: number;
  completeness: string;
  files: { name: string; bytes?: number; status: string; sha256?: string }[];
};
type Description = {
  issueType: string;
  title: string;
  actual: string;
  expected: string;
  steps: string;
};
type Bridge = <T>(
  command: string,
  args?: Record<string, unknown>,
) => Promise<T>;
export function ReportIssue({
  onClose,
  bridge = invoke,
}: {
  onClose(): void;
  bridge?: Bridge;
}) {
  const [tab, setTab] = useState<"report" | "logs">("report");
  const [selection, setSelection] = useState<Selection>({
    fe: true,
    be: true,
    rulekit: true,
    evidence: false,
    evidenceConsent: false,
  });
  const [form, setForm] = useState<Description>({
    issueType: "Other",
    title: "",
    actual: "",
    expected: "",
    steps: "",
  });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [state, setState] = useState<
    "idle" | "collecting" | "review" | "submitting" | "success" | "failure"
  >("idle");
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);
  const [url, setUrl] = useState("");
  useEffect(() => {
    const id = localStorage.getItem("d4planner.pendingReportId");
    if (id)
      void bridge<Preview>("resume_issue_report", { reportId: id })
        .then((p) => {
          setPreview(p);
          if (p.description) setForm(p.description);
          if (p.consent) setSelection(p.consent);
          setState("review");
        })
        .catch(() => setError("Previous draft could not be restored"));
  }, [bridge]);
  const busy = state === "collecting" || state === "submitting";
  const valid =
    !!(form.title.trim() && form.actual.trim() && form.expected.trim()) &&
    [form.actual, form.expected, form.steps].every(
      (text) => new TextEncoder().encode(text).length <= 8000,
    );
  function select(key: keyof Selection, value: boolean) {
    setSelection({
      ...selection,
      [key]: value,
      ...(key === "evidence" && !value ? { evidenceConsent: false } : {}),
    });
    setPreview(null);
    setConsent(false);
    setState("idle");
  }
  async function collect() {
    setState("collecting");
    setError("");
    setConsent(false);
    try {
      const p = await bridge<Preview>("collect_issue_report", { selection });
      setPreview(p);
      localStorage.setItem("d4planner.pendingReportId", p.reportId);
      setState("review");
    } catch (e) {
      setError(String(e));
      setState("failure");
    }
  }
  async function submit() {
    if (!preview || !consent) return;
    setState("submitting");
    setError("");
    try {
      const r = await bridge<{ issueUrl: string }>("submit_issue_report", {
        reportId: preview.reportId,
        description: form,
        consent,
      });
      localStorage.removeItem("d4planner.pendingReportId");
      setUrl(r.issueUrl);
      setState("success");
    } catch (e) {
      setError(String(e));
      setState("failure");
    }
  }
  async function close() {
    if (busy) return;
    await bridge("cancel_issue_report").catch(() => undefined);
    localStorage.removeItem("d4planner.pendingReportId");
    onClose();
  }
  return (
    <aside className="report-panel" aria-label="Report Issue">
      <header>
        <strong>Diagnostics &amp; Report Issue</strong>
        <button
          aria-label="Close report"
          disabled={busy}
          onClick={() => void close()}
        >
          ×
        </button>
      </header>
      <nav>
        <button aria-pressed={tab === "logs"} onClick={() => setTab("logs")}>
          Collect Logs
        </button>
        <button
          aria-pressed={tab === "report"}
          onClick={() => setTab("report")}
        >
          Report Issue
        </button>
      </nav>
      {tab === "logs" ? (
        <fieldset disabled={busy || state === "success"}>
          <legend>Sources for this run</legend>
          {(
            [
              ["fe", "FE"],
              ["be", "BE"],
              ["rulekit", "Rule Kit"],
              ["evidence", "Existing D4 Evidence"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={selection[key]}
                onChange={(e) => select(key, e.target.checked)}
              />
              {label}
            </label>
          ))}
          {selection.evidence && (
            <div role="note">
              <p>
                Existing D4 evidence may contain raw speech and gameplay
                content. It is encrypted but sensitive. Review before sending.
              </p>
              <label>
                <input
                  type="checkbox"
                  checked={selection.evidenceConsent}
                  onChange={(e) => select("evidenceConsent", e.target.checked)}
                />
                I consent to include existing D4 evidence
              </label>
            </div>
          )}
        </fieldset>
      ) : (
        <fieldset disabled={busy || state === "success"}>
          <legend>Tell us what happened</legend>
          <label>
            Issue Type
            <select
              value={form.issueType}
              onChange={(e) => {
                setForm({ ...form, issueType: e.target.value });
                setConsent(false);
              }}
            >
              {[
                "Incorrect Equipment",
                "Crash / Startup",
                "HUD / Display",
                "Rule Kit / Calculation",
                "Other",
              ].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          {(["title", "actual", "expected", "steps"] as const).map((key) => (
            <label key={key}>
              {
                {
                  title: "Title",
                  actual: "Actual",
                  expected: "Expected",
                  steps: "Steps to Reproduce",
                }[key]
              }
              <textarea
                rows={key === "title" ? 1 : 2}
                maxLength={key === "title" ? 100 : 8000}
                value={form[key]}
                onChange={(e) => {
                  setForm({ ...form, [key]: e.target.value });
                  setConsent(false);
                }}
              />
            </label>
          ))}
          <p>
            Issue text is public. Do not include credentials or private content
            in this form.
          </p>
        </fieldset>
      )}
      {state !== "success" && (
        <button
          disabled={busy || (selection.evidence && !selection.evidenceConsent)}
          onClick={() => void collect()}
        >
          Preview collection
        </button>
      )}
      {state === "collecting" && <p role="status">Collecting…</p>}
      {preview && (
        <section aria-label="Collection preview">
          <p>Run {preview.runId}</p>
          <p>
            {preview.completeness} · {preview.bytes} bytes
          </p>
          <ul>
            {preview.files.map((f) => (
              <li key={f.name}>
                {f.name} · {f.bytes ?? 0} bytes · {f.status}
              </li>
            ))}
          </ul>
          {preview.bytes === 0 && (
            <p>
              No diagnostic content available. The report can still describe the
              issue.
            </p>
          )}
        </section>
      )}
      {error && (
        <p role="alert">
          {error}. Draft and selections are retained. Retry when the connection
          or configuration is available.
        </p>
      )}
      {state === "submitting" && (
        <p role="status">Encrypting and submitting…</p>
      )}
      {state === "success" ? (
        <p role="status">
          Issue submitted:{" "}
          <a href={url} target="_blank" rel="noreferrer">
            {url}
          </a>
        </p>
      ) : (
        <footer>
          <label>
            <input
              type="checkbox"
              disabled={!preview || busy}
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            I reviewed the public issue text and exact file list and consent to
            submit.
          </label>
          <button
            disabled={!valid || !preview || !consent || busy}
            onClick={() => void submit()}
          >
            {state === "failure" ? "Retry submission" : "Submit issue"}
          </button>
        </footer>
      )}
    </aside>
  );
}
