import { useCallback, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { ProjectRow } from "./components/ProjectRow";
import { HUD } from "./components/HUD";
import { Composer } from "./components/Composer";
import { TerminalPane } from "./components/TerminalPane";
import { ptyCreate, ptyWrite } from "./lib/ipc";
import {
  type ConversationEntry,
  type HealthStatus,
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
  const [isRunning] = useState(false);
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
    const conv = makeConversation();
    for (const tab of conv.tabs) {
      try {
        await ptyCreate(tab.tabId, tab.providerId, 120, 40);
      } catch (err) {
        console.warn(`[pty] ${tab.providerId} failed:`, err);
      }
    }
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

  const handleAdvisorChange = useCallback(
    (advisor: ProviderId | null) => {
      if (!activeConvId) return;
      updateConv(activeConvId, { advisor });
    },
    [activeConvId, updateConv]
  );

  const handleSend = useCallback(() => {
    if (!composerText.trim() || !activeConv) return;
    const tab = activeConv.tabs.find(
      (t) => t.providerId === activeConv.provider
    );
    if (tab) {
      ptyWrite(tab.tabId, composerText + "\r").catch(console.error);
    }
    setComposerText("");
  }, [composerText, activeConv]);

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
          isRunning={isRunning}
          onAdvisorChange={handleAdvisorChange}
          onClearChat={() => {}}
        />

        <HUD
          conv={activeConv}
          health={health}
          isRunning={isRunning}
          onProviderSwitch={handleProviderSwitch}
        />

        {/* Terminal area */}
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
          {activeConv ? (
            activeConv.tabs.map(({ tabId, providerId }) => (
              <div
                key={tabId}
                style={{
                  position: "absolute",
                  inset: 0,
                  display:
                    providerId === activeProvider ? "block" : "none",
                }}
              >
                <TerminalPane
                  tabId={tabId}
                  active={providerId === activeProvider}
                />
              </div>
            ))
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

        <Composer
          value={composerText}
          provider={activeProvider}
          isRunning={isRunning}
          disabled={!activeConv}
          onChange={setComposerText}
          onSend={handleSend}
          onStop={() => {}}
        />
      </div>
    </div>
  );
}
