// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import manifest from "../tests/visual/golden/manifest.json";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../tests/visual/golden");
const sha256 = (path: string) => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");

describe("independent MagicPath production Golden", () => {
  it("pins the exact approved project/component/revision", () => {
    expect(manifest.source).toMatchObject({
      environment: "MagicPath production",
      projectId: "458763473602621440",
      componentId: "458765764401446912",
      revisionId: "464988421014827008",
      mode: "READ_ONLY",
    });
  });

  it("fails closed if the exported preview bytes drift", () => {
    expect(sha256(manifest.preview.path)).toBe(manifest.preview.sha256);
    expect(manifest.sourceContext).toEqual({
      selectedRevisionId: manifest.source.revisionId,
      baseRevisionId: manifest.source.revisionId,
      editableFileCount: 3,
    });
  });

  it("does not pretend missing interaction-state Goldens passed", () => {
    expect(manifest.referenceCoverage.filter(item => item.status === "BLOCKED").map(item => item.case)).toEqual([
      "target-selector-open", "partial-equipment", "no-data", "invalid-target", "disconnected",
    ]);
  });
});
