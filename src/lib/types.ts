export type HealthStatus = "healthy" | "error" | "unknown" | "disabled";
export type ChatRole = "user" | "provider";

export interface ProviderInfo {
  id: string;
  label: string;
  glyph: string;
  color: string;
  bgColor: string;
  ctxWindow: number;
  supportsResume: boolean;
  hasShellAuth: boolean;
}

export const PROVIDERS = {
  claude: {
    id: "claude",
    label: "Claude",
    glyph: "C",
    color: "var(--p-claude)",
    bgColor: "var(--p-claude-bg)",
    ctxWindow: 1_000_000,
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
} as const satisfies Record<string, ProviderInfo>;

export type ProviderId = keyof typeof PROVIDERS;

export const PROVIDER_IDS = Object.keys(PROVIDERS) as ProviderId[];

export interface ProviderRuntimeStatus {
  providerId: ProviderId;
  health: HealthStatus;
  model: string;
  contextUsedPercent: number | null;
  fiveHourPercent: number | null;
  fiveHourResetSeconds: number | null;
}

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

export interface ChatMessage {
  id: string;
  role: ChatRole;
  providerId?: ProviderId;
  advisorId?: ProviderId;
  content: string;
  createdAt: number;
}

export interface ConversationEntry {
  id: string;
  title: string;
  tabs: PtyTab[];
  provider: ProviderId;
  advisor: ProviderId | null;
  project: string | null;
  messages: ChatMessage[];
  sessions: Record<ProviderId, SessionInfo | null>;
}
