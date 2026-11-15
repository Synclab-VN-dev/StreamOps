import { invoke as tauriInvoke } from '@tauri-apps/api/core';

/** Renderer-side boundary only. Authorization belongs to native/server handlers. */
export interface HudPlatform {
  readonly kind: 'desktop' | 'web';
  readonly nativeWindow: boolean;
  readonly reportStorageKey?: string;
  invoke: typeof tauriInvoke;
}

const desktop: HudPlatform = {
  kind: 'desktop',
  nativeWindow: true,
  invoke: tauriInvoke,
};
let active: HudPlatform = desktop;
let locked = false;

/** Called by application bootstrap before mounting React, never by remote input. */
export function configurePlatform(platform: HudPlatform): void {
  if (locked) throw new Error('PLATFORM_ALREADY_IN_USE');
  active = platform;
}

export function hudPlatform(): HudPlatform {
  locked = true;
  return active;
}

// Keep a stable function identity for ReportIssue effects and injected test bridges.
export const invoke: typeof tauriInvoke = (...args) => hudPlatform().invoke(...args);
