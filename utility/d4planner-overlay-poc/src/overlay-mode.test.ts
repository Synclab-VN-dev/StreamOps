import { describe, expect, it } from "vitest";
import { labelForMode, nextInteractive } from "./overlay-mode";

describe("overlay interaction mode", () => {
  it("starts in interactive mode for recovery", () => {
    expect(labelForMode({ interactive: true })).toBe("INTERACTIVE");
  });
  it("labels click-through state as passive", () => {
    expect(labelForMode({ interactive: false })).toBe("PASSIVE");
  });
  it("toggles both ways", () => {
    expect(nextInteractive({ interactive: true })).toBe(false);
    expect(nextInteractive({ interactive: false })).toBe(true);
  });
});
