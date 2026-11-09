// @vitest-environment jsdom
// DOM-event coverage, not evidence of a Windows IME/RustDesk reproduction.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReportIssue } from "./ReportIssue";

afterEach(cleanup);
beforeEach(() => localStorage.clear());

const fields = ["Title", "Actual", "Expected", "Steps to Reproduce"];
const preview = { reportId: "ime-test", runId: "synthetic", bytes: 0, completeness: "BEST_EFFORT", files: [] };
// The second phrase is an actual native Telex result for the synthetic keys
// "tieengs vieetj issue expected". The form must not guess how to "repair" it.
const committed = "English issue expected / tiếng việt isue ễpcted";

function input(element: HTMLTextAreaElement, value: string, composing: boolean) {
  fireEvent.input(element, {
    target: { value }, data: value, isComposing: composing,
    inputType: composing ? "insertCompositionText" : "insertText",
  });
}

describe("Report Issue committed text", () => {
  it.each(fields)("preserves composition in %s across parent renders and sends exact committed text", async label => {
    const bridge = vi.fn(async (command: string) => command === "collect_issue_report" ? preview : {
      reportId: preview.reportId, status: "COMPLETE", issueUrl: "https://github.com/Synclab-VN-dev/StreamOps/issues/1",
    });
    const { rerender } = render(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
    for (const name of fields) input(screen.getByLabelText<HTMLTextAreaElement>(name), "Synthetic baseline", false);
    const field = screen.getByLabelText(label) as HTMLTextAreaElement;
    field.focus();
    fireEvent.compositionStart(field, { data: "" });
    for (const value of ["T", "Ti", "Tiê", "Tiên", "Tiếng"]) {
      fireEvent.compositionUpdate(field, { data: value });
      input(field, value, true);
      rerender(<ReportIssue bridge={bridge as never} onClose={() => {}} />);
      expect(screen.getByLabelText(label)).toBe(field);
      expect(document.activeElement).toBe(field);
      expect(field.value).toBe(value);
    }
    fireEvent.compositionEnd(field, { data: "Tiếng" });
    input(field, committed, false);
    fireEvent.click(screen.getByText("Preview collection"));
    await screen.findByText("Run synthetic");
    fireEvent.click(screen.getByLabelText(/I reviewed the public/));
    fireEvent.click(screen.getByText("Submit issue"));
    const key = ["title", "actual", "expected", "steps"][fields.indexOf(label)];
    await waitFor(() => expect(bridge).toHaveBeenCalledWith("submit_issue_report", expect.objectContaining({
      description: expect.objectContaining({ [key]: committed }),
    })));
  });

  it.each(["input-before-end", "input-after-end"])("retains the final composition value with %s", order => {
    const { rerender } = render(<ReportIssue onClose={() => {}} />);
    const field = screen.getByLabelText("Actual") as HTMLTextAreaElement;
    input(field, "Before  after", false);
    field.setSelectionRange(7, 7);
    fireEvent.compositionStart(field);
    input(field, "Before tiê after", true);
    const final = "Before tiếng after";
    if (order === "input-before-end") input(field, final, true);
    fireEvent.compositionEnd(field, { data: "tiếng" });
    if (order === "input-after-end") input(field, final, false);
    rerender(<ReportIssue onClose={() => {}} />);
    expect(field.value).toBe(final);
  });

  it("preserves cancellation, deletion, and subsequent English input", () => {
    render(<ReportIssue onClose={() => {}} />);
    const field = screen.getByLabelText("Steps to Reproduce") as HTMLTextAreaElement;
    input(field, "Original", false);
    fireEvent.compositionStart(field);
    input(field, "Original tiê", true);
    fireEvent.compositionEnd(field, { data: "" });
    input(field, "Original", false);
    fireEvent.input(field, { target: { value: "Origina" }, inputType: "deleteContentBackward" });
    input(field, "Original websocket expected issue", false);
    expect(field.value).toBe("Original websocket expected issue");
  });
});
