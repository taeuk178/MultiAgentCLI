export type ProviderId = "claude" | "codex" | "gemini";

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  color: string;
}

export const PROVIDERS: Record<ProviderId, ProviderInfo> = {
  claude: { id: "claude", label: "Claude", color: "#d97757" },
  codex: { id: "codex", label: "Codex", color: "#4a9eff" },
  gemini: { id: "gemini", label: "Gemini", color: "#34a853" },
};

export const PROVIDER_IDS: ProviderId[] = ["claude", "codex", "gemini"];

export interface PtyTab {
  tabId: string;
  providerId: ProviderId;
  conversationId: string;
}

export interface ConversationEntry {
  id: string;
  title: string;
  tabs: PtyTab[];
}
