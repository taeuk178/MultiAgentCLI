export type ProviderId = "claude" | "codex" | "gemini";
export type HealthStatus = "healthy" | "error" | "unknown" | "disabled";

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  glyph: string;
  color: string;
  bgColor: string;
  ctxWindow: number;
  supportsResume: boolean;
  hasShellAuth: boolean;
}

export const PROVIDERS: Record<ProviderId, ProviderInfo> = {
  claude: {
    id: "claude",
    label: "Claude",
    glyph: "C",
    color: "var(--p-claude)",
    bgColor: "var(--p-claude-bg)",
    ctxWindow: 200_000,
    supportsResume: true,
    hasShellAuth: true,
  },
  codex: {
    id: "codex",
    label: "Codex",
    glyph: "X",
    color: "var(--p-codex)",
    bgColor: "var(--p-codex-bg)",
    ctxWindow: 200_000,
    supportsResume: true,
    hasShellAuth: true,
  },
  gemini: {
    id: "gemini",
    label: "Gemini",
    glyph: "G",
    color: "var(--p-gemini)",
    bgColor: "var(--p-gemini-bg)",
    ctxWindow: 1_000_000,
    supportsResume: false,
    hasShellAuth: false,
  },
};

export const PROVIDER_IDS: ProviderId[] = ["claude", "codex", "gemini"];

export interface SessionInfo {
  id: string;
  startedAt: number;
  ctxTokens: number;
}

export interface PtyTab {
  tabId: string;
  providerId: ProviderId;
  conversationId: string;
}

export interface ConversationEntry {
  id: string;
  title: string;
  tabs: PtyTab[];
  provider: ProviderId;
  advisor: ProviderId | null;
  project: string | null;
  sessions: Record<ProviderId, SessionInfo | null>;
}
