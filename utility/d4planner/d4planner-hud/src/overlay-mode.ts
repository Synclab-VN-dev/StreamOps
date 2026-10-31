export type OverlayMode = "INTERACTIVE" | "PASSIVE";

export type OverlayStatus = { interactive: boolean };

export function labelForMode(status: OverlayStatus): OverlayMode {
  return status.interactive ? "INTERACTIVE" : "PASSIVE";
}

export function nextInteractive(status: OverlayStatus): boolean {
  return !status.interactive;
}
