import { useCallback, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { ProjectRow } from "./components/ProjectRow";
import { HUD } from "./components/HUD";
import { Composer } from "./components/Composer";
import { ChatPane } from "./components/ChatPane";
import { providerChat } from "./lib/ipc";
import {
  type ChatMessage,
  type ConversationEntry,
  type HealthStatus,
  PROVIDERS,
  PROVIDER_IDS,
  type ProviderId,
} from "./lib/types";

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
  const [health] = useState<Record<ProviderId, HealthStatus>>({
    claude: "healthy",
    codex: "healthy",
    gemini: "healthy",
  });
  const [pendingConvId, setPendingConvId] = useState<string | null>(null);
  const isRunning = pendingConvId === activeConvId;
  const [logsOpen, setLogsOpen] = useState(false);
  const [composerText, setComposerText] = useState("");

  const activeConv = conversations.find((c) => c.id === activeConvId) ?? null;

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
      updateConv(activeConvId, { provider });
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
    const userMessage = makeMessage("user", message);
    const history = [...activeConv.messages, userMessage];

    updateConv(activeConv.id, { messages: history });
    setPendingConvId(activeConv.id);

    try {
      const prompt = buildChatPrompt(history);
      const response = await providerChat(provider, prompt, activeConv.project);
      const providerMessage = makeMessage("provider", response || "(빈 응답)", provider);
      updateConv(activeConv.id, { messages: [...history, providerMessage] });
    } catch (err) {
      const providerMessage = makeMessage(
        "provider",
        `실행 실패: ${err instanceof Error ? err.message : String(err)}`,
        provider,
      );
      updateConv(activeConv.id, { messages: [...history, providerMessage] });
    } finally {
      setPendingConvId(null);
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
          health={health}
          logsOpen={logsOpen}
          onToggleLogs={() => setLogsOpen((v) => !v)}
          onRefreshHealth={() => {}}
        />

        <ProjectRow
          conv={activeConv}
          onProjectChange={handleProjectChange}
        />

        <HUD
          conv={activeConv}
          health={health}
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
              {PROVIDERS[activeProvider].label}가 입력 중...
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
    </div>
  );
}

function makeMessage(
  role: ChatMessage["role"],
  content: string,
  providerId?: ProviderId,
): ChatMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    providerId,
    content,
    createdAt: Date.now(),
  };
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
