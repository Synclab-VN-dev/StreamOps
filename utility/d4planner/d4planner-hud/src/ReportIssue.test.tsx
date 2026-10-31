// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ReportIssue } from "./ReportIssue";
const preview = {
  reportId: "test-id",
  runId: "run-1",
  bytes: 10,
  completeness: "BEST_EFFORT",
  files: [{ name: "fe.log", bytes: 10, status: "BEST_EFFORT" }],
};
afterEach(cleanup);
beforeEach(() => localStorage.clear());
function form() {
  for (const [label, value] of [
    ["Title", "Test"],
    ["Actual", "Failure"],
    ["Expected", "Success"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
describe("Report Issue", () => {
  it("keeps source choices across tabs and never implicitly opts into evidence", async () => {
    const bridge = vi.fn().mockResolvedValue(preview);
    render(<ReportIssue bridge={bridge} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Collect Logs"));
    expect(within(screen.getByRole("group", { name: "Sources for this run" })).getAllByRole("checkbox")).toHaveLength(4);
    expect((screen.getByLabelText("D4Planner Event Log") as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByLabelText("BE"));
    fireEvent.click(screen.getByLabelText("Rule Kit"));
    fireEvent.click(screen.getByText("Report Issue"));
    fireEvent.click(screen.getByText("Collect Logs"));
    expect((screen.getByLabelText("BE") as HTMLInputElement).checked).toBe(
      false,
    );
    fireEvent.click(screen.getByText("Preview collection"));
    await waitFor(() => expect(screen.getByText("Run run-1")).toBeTruthy());
    expect(bridge).toHaveBeenCalledWith("collect_issue_report", {
      selection: {
        fe: true,
        be: false,
        rulekit: false,
        evidence: false,
        evidenceConsent: false,
      },
    });
  });
  it("requires separate evidence consent and shows actual preview", async () => {
    const bridge = vi
      .fn()
      .mockResolvedValue({
        ...preview,
        files: [{ name: "events.jsonl", status: "UNAVAILABLE" }],
      });
    render(<ReportIssue bridge={bridge} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Collect Logs"));
    fireEvent.click(screen.getByLabelText("D4Planner Event Log"));
    expect(
      (screen.getByText("Preview collection") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(
      screen.getByLabelText("I consent to include raw D4Planner events"),
    );
    fireEvent.click(screen.getByText("Preview collection"));
    await waitFor(() =>
      expect(
        screen.getByText("events.jsonl · 0 bytes · UNAVAILABLE"),
      ).toBeTruthy(),
    );
  });
  it("preserves draft and reportId on offline failure, retries and shows actual URL", async () => {
    let attempts = 0;
    const bridge = vi.fn(async (command: string) => {
      if (command === "collect_issue_report") return preview;
      if (++attempts === 1) throw "GATEWAY_OFFLINE";
      return {
        issueUrl: "https://github.com/Synclab-VN-dev/StreamOps/issues/123",
        status: "COMPLETE", reportId: preview.reportId,
      };
    });
    render(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
    form();
    fireEvent.click(screen.getByText("Preview collection"));
    await waitFor(() => expect(screen.getByText("Run run-1")).toBeTruthy());
    fireEvent.click(screen.getByLabelText(/I reviewed the public/));
    fireEvent.click(screen.getByText("Submit issue"));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "GATEWAY_OFFLINE",
      ),
    );
    expect((screen.getByLabelText("Title") as HTMLTextAreaElement).value).toBe(
      "Test",
    );
    fireEvent.click(screen.getByText("Retry submission"));
    await waitFor(() =>
      expect(screen.getByRole("link").getAttribute("href")).toBe(
        "https://github.com/Synclab-VN-dev/StreamOps/issues/123",
      ),
    );
    const submissions = bridge.mock.calls.filter(
      (x) => x[0] === "submit_issue_report",
    );
    expect(submissions).toHaveLength(2);
  });
  it("source changes invalidate consent and stale preview", async () => {
    const bridge = vi.fn().mockResolvedValue(preview);
    render(<ReportIssue bridge={bridge} onClose={() => {}} />);
    form();
    fireEvent.click(screen.getByText("Preview collection"));
    await waitFor(() => expect(screen.getByText("Run run-1")).toBeTruthy());
    fireEvent.click(screen.getByLabelText(/I reviewed the public/));
    fireEvent.click(screen.getByText("Collect Logs"));
    fireEvent.click(screen.getByLabelText("FE"));
    expect(screen.queryByText("Run run-1")).toBeNull();
    expect(
      (screen.getByText("Submit issue") as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("review: remote outcome", () => {
  const issueUrl = "https://github.com/Synclab-VN-dev/StreamOps/issues/123";
  async function ready(bridge: BridgeForTest) {
    render(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
    form();
    fireEvent.click(screen.getByText("Preview collection"));
    await screen.findByText("Run run-1");
    fireEvent.click(screen.getByLabelText(/I reviewed the public/));
    fireEvent.click(screen.getByText("Submit issue"));
  }
  type BridgeForTest = ReturnType<typeof vi.fn>;
  it.each(["EXPIRED", "UPLOAD_PENDING", "UNKNOWN", undefined])("never claims uploaded for %s", async (status) => {
    const bridge = vi.fn(async (command: string) => command === "collect_issue_report" ? preview : { issueUrl, status, reportId: preview.reportId });
    await ready(bridge);
    await waitFor(() => expect(screen.queryByText("Encrypting and submitting…")).toBeNull());
    expect(screen.queryByText(/Issue submitted:/)).toBeNull();
    if (status === "EXPIRED") {
      expect(screen.getByText(/diagnostic asset has expired/i)).toBeTruthy();
      expect(screen.getByRole("link").getAttribute("href")).toBe(issueUrl);
      expect(localStorage.getItem("d4planner.pendingReportId")).toBeNull();
    } else {
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(localStorage.getItem("d4planner.pendingReportId")).toBe(preview.reportId);
    }
  });
  it("close after an uncertain remote outcome preserves reportId and reopen resumes it", async () => {
    const bridge = vi.fn(async (command: string) => {
      if (command === "collect_issue_report") return preview;
      if (command === "resume_issue_report") return { ...preview, pendingRemote: true, description: { issueType:"Other", title:"Test", actual:"Failure", expected:"Success", steps:"" } };
      throw "UPLOAD_PENDING";
    });
    await ready(bridge);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByLabelText("Close report"));
    await waitFor(() => expect(localStorage.getItem("d4planner.pendingReportId")).toBe(preview.reportId));
    expect(bridge.mock.calls.some(x => x[0] === "cancel_issue_report")).toBe(false);
    cleanup();
    render(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
    await screen.findByText("Run run-1");
    expect(bridge).toHaveBeenCalledWith("resume_issue_report", { reportId: preview.reportId });
    expect((screen.getByText("Preview collection") as HTMLButtonElement).disabled).toBe(true);
  });
});

it("explicit cancel discards only an unsent draft; rejected cancel keeps recovery pointer", async () => {
  let refuse = true;
  const bridge = vi.fn(async (command: string) => {
    if (command === "collect_issue_report") return preview;
    if (command === "cancel_issue_report" && refuse) throw "REPORT_RECONCILIATION_REQUIRED";
    return null;
  });
  render(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
  fireEvent.click(screen.getByText("Preview collection"));
  await screen.findByText("Run run-1");
  fireEvent.click(screen.getByText("Discard unsent draft"));
  await screen.findByRole("alert");
  expect(localStorage.getItem("d4planner.pendingReportId")).toBe(preview.reportId);
  refuse = false;
  fireEvent.click(screen.getByText("Discard unsent draft"));
  await waitFor(() => expect(screen.queryByText("Run run-1")).toBeNull());
  expect(localStorage.getItem("d4planner.pendingReportId")).toBeNull();
});
