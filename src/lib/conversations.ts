import type {
  ChatMessage,
  ConversationMode,
  ConversationEntry,
  HealthStatus,
  ProviderId,
  ProviderRuntimeStatus,
} from "./types";
import { PROVIDER_IDS } from "./types";

let convCounter = 1;

export function makeConversation(
  defaultProvider: ProviderId = "claude",
  mode: ConversationMode = "quick",
): ConversationEntry {
  const id = `conv-${Date.now()}`;

  return {
    id,
    title: `Conversation ${convCounter++}`,
    mode,
    tabs: PROVIDER_IDS.map((pid) => ({
      tabId: `${id}-${pid}`,
      providerId: pid,
      conversationId: id,
    })),
    provider: defaultProvider,
    advisor: null,
    project: null,
    messages: [],
    sessions: { claude: null, codex: null, gemini: null },
  };
}

export function makeMessage(
  role: ChatMessage["role"],
  content: string,
  providerId?: ProviderId,
  advisorId?: ProviderId,
): ChatMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    providerId,
    advisorId,
    content,
    createdAt: Date.now(),
  };
}

export function makeDefaultProviderRuntime(): Record<
  ProviderId,
  ProviderRuntimeStatus
> {
  return Object.fromEntries(
    PROVIDER_IDS.map((providerId) => [
      providerId,
      {
        providerId,
        health: "unknown",
        model: "checking",
        contextUsedPercent: null,
        fiveHourPercent: null,
        fiveHourResetSeconds: null,
      },
    ]),
  ) as Record<ProviderId, ProviderRuntimeStatus>;
}

export function providerHealth(
  runtime: Record<ProviderId, ProviderRuntimeStatus>,
): Record<ProviderId, HealthStatus> {
  return Object.fromEntries(
    PROVIDER_IDS.map((providerId) => [providerId, runtime[providerId].health]),
  ) as Record<ProviderId, HealthStatus>;
}
