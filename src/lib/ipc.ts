import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { ProviderId, ProviderRuntimeStatus } from "./types";

export interface PtyOutputPayload {
  tab_id: string;
  data: string;
}

export function ptyCreate(
  tabId: string,
  providerId: ProviderId,
  cols: number,
  rows: number,
  cwd?: string,
): Promise<void> {
  return invoke("pty_create", { tabId, providerId, cols, rows, cwd: cwd ?? null });
}

export function ptyWrite(tabId: string, data: string): Promise<void> {
  return invoke("pty_write", { tabId, data });
}

export function ptyResize(
  tabId: string,
  cols: number,
  rows: number,
): Promise<void> {
  return invoke("pty_resize", { tabId, cols, rows });
}

export function ptyClose(tabId: string): Promise<void> {
  return invoke("pty_close", { tabId });
}

export function providerChat(
  providerId: ProviderId,
  prompt: string,
  cwd?: string | null,
): Promise<string> {
  return invoke("provider_chat", { providerId, prompt, cwd: cwd ?? null });
}

export function providerStatuses(): Promise<ProviderRuntimeStatus[]> {
  return invoke("provider_statuses");
}

export function onPtyOutput(
  handler: (payload: PtyOutputPayload) => void,
): Promise<UnlistenFn> {
  return listen<PtyOutputPayload>("pty-output", (e) => handler(e.payload));
}
