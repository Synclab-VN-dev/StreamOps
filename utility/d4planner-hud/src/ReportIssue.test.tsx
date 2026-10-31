// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
        files: [{ name: "events.db", status: "UNAVAILABLE" }],
      });
    render(<ReportIssue bridge={bridge} onClose={() => {}} />);
    fireEvent.click(screen.getByText("Collect Logs"));
    fireEvent.click(screen.getByLabelText("Existing D4 Evidence"));
    expect(
      (screen.getByText("Preview collection") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(
      screen.getByLabelText("I consent to include existing D4 evidence"),
    );
    fireEvent.click(screen.getByText("Preview collection"));
    await waitFor(() =>
      expect(
        screen.getByText("events.db · 0 bytes · UNAVAILABLE"),
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
