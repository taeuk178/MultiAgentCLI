import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { ProjectRow } from "./components/ProjectRow";
import { HUD } from "./components/HUD";
import { Composer } from "./components/Composer";
import { ChatPane } from "./components/ChatPane";
import { providerChat, providerStatuses } from "./lib/ipc";
import {
  type ChatMessage,
  type ConversationEntry,
  type HealthStatus,
  PROVIDERS,
  PROVIDER_IDS,
  type ProviderId,
  type ProviderRuntimeStatus,
} from "./lib/types";

type SidebarPanelMode = "local" | "remote";

let convCounter = 1;

function makeConversation(defaultProvider: ProviderId = "claude"): ConversationEntry {
  const id = `conv-${Date.now()}`;
  return {
    id,
    title: `Conversation ${convCounter++}`,
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

export default function App() {
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [providerRuntime, setProviderRuntime] = useState<
    Record<ProviderId, ProviderRuntimeStatus>
  >(makeDefaultProviderRuntime());
  const [pendingConvId, setPendingConvId] = useState<string | null>(null);
  const isRunning = pendingConvId === activeConvId;
  const [pendingLabel, setPendingLabel] = useState<string | null>(null);
  const [pendingStartedAt, setPendingStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [composerText, setComposerText] = useState("");
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);
  const [rightSidebarMode, setRightSidebarMode] =
    useState<SidebarPanelMode>("local");

  const activeConv = conversations.find((c) => c.id === activeConvId) ?? null;

  useEffect(() => {
    if (!pendingStartedAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [pendingStartedAt]);

  useEffect(() => {
    let cancelled = false;

    providerStatuses()
      .then((statuses) => {
        if (cancelled) return;
        setProviderRuntime((prev) => {
          const next = { ...prev };
          for (const status of statuses) {
            next[status.providerId] = status;
          }
          return next;
        });
      })
      .catch(() => {
        if (cancelled) return;
        setProviderRuntime((prev) => {
          const next = { ...prev };
          for (const id of PROVIDER_IDS) {
            next[id] = { ...next[id], health: "error" };
          }
          return next;
        });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const updateConv = useCallback(
    (id: string, patch: Partial<ConversationEntry>) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, ...patch } : c))
      );
    },
    []
  );

  const handleNew = useCallback(async () => {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "프로젝트 폴더 선택",
    });
    const projectPath = typeof selected === "string" ? selected : null;

    const conv = makeConversation();
    if (projectPath) conv.project = projectPath;
    setConversations((prev) => [conv, ...prev]);
    setActiveConvId(conv.id);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== id);
        if (id === activeConvId) {
          setActiveConvId(next[0]?.id ?? null);
        }
        return next;
      });
    },
    [activeConvId]
  );

  const handleProviderSwitch = useCallback(
    (provider: ProviderId) => {
      if (!activeConvId || isRunning) return;
      updateConv(activeConvId, {
        provider,
        advisor: activeConv?.advisor === provider ? null : activeConv?.advisor ?? null,
      });
    },
    [activeConvId, activeConv?.advisor, isRunning, updateConv]
  );

  const handleAdvisorChange = useCallback(
    (advisor: ProviderId | null) => {
      if (!activeConvId || isRunning) return;
      updateConv(activeConvId, { advisor });
    },
    [activeConvId, isRunning, updateConv]
  );

  const handleProjectChange = useCallback(
    (path: string) => {
      if (!activeConvId || !activeConv) return;
      updateConv(activeConvId, { project: path });
    },
    [activeConvId, activeConv, updateConv]
  );

  const handleClearChat = useCallback(
    (id: string) => {
      const conv = conversations.find((c) => c.id === id);
      if (!conv) return;
      updateConv(id, { messages: [] });
    },
    [conversations, updateConv]
  );

  const handleSend = useCallback(async () => {
    if (!composerText.trim() || !activeConv || isRunning) return;
    const message = composerText.trim();
    setComposerText("");
    const provider = activeConv.provider;
    const advisor = activeConv.advisor;
    const userMessage = makeMessage("user", message);
    const history = [...activeConv.messages, userMessage];

    updateConv(activeConv.id, { messages: history });
    setPendingConvId(activeConv.id);
    setPendingStartedAt(Date.now());
    setNow(Date.now());

    try {
      const response = advisor
        ? await runAdvisedChat(provider, advisor, history, activeConv.project, setPendingLabel)
        : await runSingleProviderChat(provider, history, activeConv.project, setPendingLabel);
      const providerMessage = makeMessage(
        "provider",
        response || "(빈 응답)",
        provider,
        advisor ?? undefined,
      );
      updateConv(activeConv.id, { messages: [...history, providerMessage] });
    } catch (err) {
      const providerMessage = makeMessage(
        "provider",
        `실행 실패: ${err instanceof Error ? err.message : String(err)}`,
        provider,
        advisor ?? undefined,
      );
      updateConv(activeConv.id, { messages: [...history, providerMessage] });
    } finally {
      setPendingConvId(null);
      setPendingLabel(null);
      setPendingStartedAt(null);
    }
  }, [composerText, activeConv, isRunning, updateConv]);

  const activeProvider = activeConv?.provider ?? "claude";

  return (
    <div
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        background: "var(--bg-window)",
      }}
    >
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        onSelect={setActiveConvId}
        onDelete={handleDelete}
        onNew={handleNew}
        onClearChat={handleClearChat}
      />

      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          background: "var(--bg-content)",
        }}
      >
        <TitleBar
          health={providerHealth(providerRuntime)}
          rightSidebarOpen={rightSidebarOpen}
          onToggleRightSidebar={() => setRightSidebarOpen((v) => !v)}
        />

        <ProjectRow
          conv={activeConv}
          isRunning={isRunning}
          onAdvisorChange={handleAdvisorChange}
          onProjectChange={handleProjectChange}
        />

        <HUD
          conv={activeConv}
          health={providerHealth(providerRuntime)}
          providerStatuses={providerRuntime}
          isRunning={isRunning}
          onProviderSwitch={handleProviderSwitch}
        />

        {/* Chat area */}
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
          {activeConv ? (
            <ChatPane
              messages={activeConv.messages}
              activeProvider={activeProvider}
              isRunning={isRunning}
            />
          ) : (
            <div
              style={{
                width: "100%",
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexDirection: "column",
                gap: 14,
                color: "var(--fg-dim)",
                userSelect: "none",
              }}
            >
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 14,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "var(--mono)",
                  fontSize: 22,
                  fontWeight: 700,
                  background: "var(--p-claude-bg)",
                  color: "var(--p-claude)",
                  border: "1px solid var(--p-claude)",
                }}
              >
                C
              </div>
              <div style={{ textAlign: "center" }}>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 600,
                    color: "var(--fg)",
                    marginBottom: 6,
                  }}
                >
                  New Chat를 눌러 시작하세요
                </div>
                <div style={{ fontSize: 12, color: "var(--fg-dim)" }}>
                  사이드바의 New Chat 버튼으로 대화를 만드세요.
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {(["⌘", "↵", "send", "·", "esc", "stop"] as const).map(
                  (k, i) =>
                    k === "·" ? (
                      <span
                        key={i}
                        style={{ alignSelf: "center", color: "var(--fg-faint)" }}
                      >
                        ·
                      </span>
                    ) : k === "send" || k === "stop" ? (
                      <span
                        key={i}
                        style={{
                          alignSelf: "center",
                          fontSize: 11,
                          color: "var(--fg-dim)",
                        }}
                      >
                        {k}
                      </span>
                    ) : (
                      <kbd
                        key={i}
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: 10.5,
                          padding: "2px 6px",
                          borderRadius: 4,
                          background: "rgba(255,255,255,0.06)",
                          border: "1px solid var(--border)",
                          color: "var(--fg-2)",
                        }}
                      >
                        {k}
                      </kbd>
                    )
                )}
              </div>
            </div>
          )}
        </div>

        {activeConv && isRunning && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "9px 22px",
              borderTop: "1px solid var(--divider)",
              background: "var(--bg-content)",
              color: "var(--fg-dim)",
              fontFamily: "var(--ui)",
              fontSize: 12,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: PROVIDERS[activeProvider].color,
                animation: "led-pulse 1.2s ease-in-out infinite",
                flexShrink: 0,
              }}
            />
            <span>
              {pendingLabel ?? `${PROVIDERS[activeProvider].label}가 입력 중...`}
              {pendingStartedAt ? ` ${formatElapsed(now - pendingStartedAt)}` : ""}
            </span>
          </div>
        )}

        {activeConv && (
          <Composer
            value={composerText}
            provider={activeProvider}
            isRunning={isRunning}
            disabled={!activeConv}
            onChange={setComposerText}
            onSend={handleSend}
          />
        )}
      </div>

      {rightSidebarOpen && (
        <RightSidebar
          mode={rightSidebarMode}
          onModeChange={setRightSidebarMode}
        />
      )}
    </div>
  );
}

function makeDefaultProviderRuntime(): Record<ProviderId, ProviderRuntimeStatus> {
  return {
    claude: { providerId: "claude", health: "unknown", model: "checking" },
    codex: { providerId: "codex", health: "unknown", model: "checking" },
    gemini: { providerId: "gemini", health: "unknown", model: "checking" },
  };
}

function providerHealth(
  runtime: Record<ProviderId, ProviderRuntimeStatus>,
): Record<ProviderId, HealthStatus> {
  return {
    claude: runtime.claude.health,
    codex: runtime.codex.health,
    gemini: runtime.gemini.health,
  };
}

function RightSidebar({
  mode,
  onModeChange,
}: {
  mode: SidebarPanelMode;
  onModeChange: (mode: SidebarPanelMode) => void;
}) {
  const isLocal = mode === "local";

  return (
    <aside
      style={{
        width: 280,
        height: "100%",
        flexShrink: 0,
        borderLeft: "1px solid var(--divider)",
        background: isLocal ? "#2b2b2e" : "#050505",
        color: "var(--fg)",
        display: "flex",
        flexDirection: "column",
        transition: "background 160ms",
      }}
    >
      <div
        style={{
          height: 44,
          display: "flex",
          alignItems: "center",
          padding: "0 12px",
          borderBottom: "1px solid var(--divider)",
          gap: 6,
        }}
      >
        {(["local", "remote"] as const).map((tab) => {
          const active = mode === tab;

          return (
            <button
              key={tab}
              onClick={() => onModeChange(tab)}
              style={{
                height: 26,
                padding: "0 11px",
                borderRadius: 6,
                border: active
                  ? "1px solid var(--border-strong)"
                  : "1px solid transparent",
                background: active
                  ? "rgba(255,255,255,0.10)"
                  : "rgba(255,255,255,0.03)",
                color: active ? "var(--fg)" : "var(--fg-dim)",
                fontSize: 11.5,
                fontWeight: active ? 700 : 500,
                fontFamily: "var(--ui)",
                cursor: "pointer",
                textTransform: "capitalize",
              }}
            >
              {tab}
            </button>
          );
        })}
      </div>

      <div
        style={{
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          color: "var(--fg-dim)",
          fontSize: 12,
          lineHeight: 1.45,
        }}
      >
        <div
          style={{
            color: "var(--fg)",
            fontSize: 13,
            fontWeight: 700,
          }}
        >
          {isLocal ? "Local" : "Remote"}
        </div>
        <div>
          {isLocal
            ? "로컬 세션과 연결된 항목을 표시할 영역입니다."
            : "원격 세션과 연결된 항목을 표시할 영역입니다."}
        </div>
      </div>
    </aside>
  );
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes === 0) {
    return `(${seconds}s)`;
  }

  return `(${minutes}m ${seconds}s)`;
}

function makeMessage(
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

async function runSingleProviderChat(
  provider: ProviderId,
  messages: ChatMessage[],
  project: string | null,
  setPendingLabel: (label: string | null) => void,
): Promise<string> {
  setPendingLabel(`${PROVIDERS[provider].label}가 입력 중...`);
  return providerChat(provider, buildChatPrompt(messages), project);
}

async function runAdvisedChat(
  provider: ProviderId,
  advisor: ProviderId,
  messages: ChatMessage[],
  project: string | null,
  setPendingLabel: (label: string | null) => void,
): Promise<string> {
  const userMessage = messages[messages.length - 1]?.content ?? "";
  const primaryName = PROVIDERS[provider].label;
  const advisorName = PROVIDERS[advisor].label;

  setPendingLabel(`${primaryName}가 초안을 작성 중...`);
  const draft = await providerChat(provider, buildDraftPrompt(messages), project);

  setPendingLabel(`${advisorName}가 초안을 검토 중...`);
  const review = await providerChat(
    advisor,
    buildAdvisorPrompt(userMessage, draft, primaryName),
    project,
  );

  setPendingLabel(`${primaryName}와 ${advisorName}가 최종 답변을 조율 중...`);
  return providerChat(
    provider,
    buildFinalPrompt(messages, draft, review, advisorName),
    project,
  );
}

function buildChatPrompt(messages: ChatMessage[]): string {
  const transcript = messages
    .map((message) => {
      const speaker = message.role === "user" ? "User" : "Assistant";
      return `${speaker}: ${message.content}`;
    })
    .join("\n\n");

  return [
    "You are a chat assistant in a multi-provider desktop app.",
    "Reply only to the latest user message.",
    "Do not repeat this transcript unless the user asks for it.",
    "",
    transcript,
  ].join("\n");
}

function buildDraftPrompt(messages: ChatMessage[]): string {
  return [
    "You are the primary provider in a multi-provider chat orchestration.",
    "Write a clear draft answer to the latest user message.",
    "Do not mention that this is a draft.",
    "",
    buildChatPrompt(messages),
  ].join("\n");
}

function buildAdvisorPrompt(
  userMessage: string,
  draft: string,
  primaryName: string,
): string {
  return [
    "You are the advisor provider in a multi-provider chat orchestration.",
    `The primary provider (${primaryName}) wrote this draft answer:`,
    "",
    draft,
    "",
    "User's latest message:",
    userMessage,
    "",
    "Review the draft. Point out what should be corrected, strengthened, removed, or kept.",
    "Return concise, actionable feedback for the primary provider. Do not answer the user directly.",
  ].join("\n");
}

function buildFinalPrompt(
  messages: ChatMessage[],
  draft: string,
  review: string,
  advisorName: string,
): string {
  return [
    "You are the primary provider in a multi-provider chat orchestration.",
    "Use your draft and the advisor feedback to produce the final answer for the user.",
    "Do not expose the orchestration steps unless the user asks.",
    "Reply only with the final answer.",
    "",
    "Conversation:",
    buildChatPrompt(messages),
    "",
    "Your draft:",
    draft,
    "",
    `${advisorName}'s feedback:`,
    review,
  ].join("\n");
}
