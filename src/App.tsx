import { useCallback, useState } from "react";
import { TerminalPane } from "./components/TerminalPane";
import { ptyCreate } from "./lib/ipc";
import {
  type ConversationEntry,
  PROVIDER_IDS,
  PROVIDERS,
  type ProviderId,
} from "./lib/types";

let convCounter = 1;

function makeConversation(): ConversationEntry {
  const id = `conv-${Date.now()}`;
  return {
    id,
    title: `Conversation ${convCounter++}`,
    tabs: PROVIDER_IDS.map((pid) => ({
      tabId: `${id}-${pid}`,
      providerId: pid,
      conversationId: id,
    })),
  };
}

export default function App() {
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [activeProvider, setActiveProvider] = useState<ProviderId>("claude");

  const activeConv =
    conversations.find((c) => c.id === activeConvId) ?? null;

  const handleNew = useCallback(async () => {
    const conv = makeConversation();
    for (const tab of conv.tabs) {
      try {
        await ptyCreate(tab.tabId, tab.providerId, 120, 40);
      } catch (err) {
        console.warn(`[pty] ${tab.providerId} failed to start:`, err);
      }
    }
    setConversations((prev) => [...prev, conv]);
    setActiveConvId(conv.id);
    setActiveProvider("claude");
  }, []);

  return (
    <div style={{ display: "flex", width: "100%", height: "100%" }}>
      {/* ── Sidebar ── */}
      <aside
        style={{
          width: 240,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          background: "#111111",
          borderRight: "1px solid #2a2a2a",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "12px 16px",
            borderBottom: "1px solid #2a2a2a",
            fontSize: 13,
            fontWeight: 600,
            color: "#e8e8e8",
            letterSpacing: "-0.01em",
          }}
        >
          Multi Agent CLI
        </div>

        {/* New conversation */}
        <button
          onClick={handleNew}
          style={{
            margin: "10px 12px 6px",
            padding: "7px 12px",
            background: "#1c1c1c",
            border: "1px solid #2a2a2a",
            borderRadius: 6,
            color: "#e8e8e8",
            fontSize: 12,
            fontFamily: "inherit",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          + New Conversation
        </button>

        {/* Conversation list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {conversations.map((conv) => {
            const isActive = conv.id === activeConvId;
            return (
              <button
                key={conv.id}
                onClick={() => setActiveConvId(conv.id)}
                style={{
                  display: "block",
                  width: "100%",
                  padding: "8px 16px",
                  background: isActive ? "#1c1c1c" : "transparent",
                  color: isActive ? "#e8e8e8" : "#888888",
                  fontSize: 12,
                  fontFamily: "inherit",
                  cursor: "pointer",
                  textAlign: "left",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  border: "none",
                  borderLeft: isActive
                    ? "2px solid #d97757"
                    : "2px solid transparent",
                }}
              >
                {conv.title}
              </button>
            );
          })}
        </div>

        {/* Provider color dots */}
        <div
          style={{
            display: "flex",
            gap: 8,
            padding: "10px 16px",
            borderTop: "1px solid #2a2a2a",
          }}
        >
          {PROVIDER_IDS.map((pid) => (
            <div
              key={pid}
              title={PROVIDERS[pid].label}
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: PROVIDERS[pid].color,
              }}
            />
          ))}
        </div>
      </aside>

      {/* ── Main ── */}
      <main
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          background: "#0a0a0a",
        }}
      >
        {activeConv ? (
          <>
            {/* Provider tab bar */}
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                padding: "0 8px",
                borderBottom: "1px solid #2a2a2a",
                flexShrink: 0,
              }}
            >
              {activeConv.tabs.map(({ providerId }) => {
                const info = PROVIDERS[providerId];
                const isActive = providerId === activeProvider;
                return (
                  <button
                    key={providerId}
                    onClick={() => setActiveProvider(providerId)}
                    style={{
                      padding: "8px 20px",
                      background: isActive ? "#1c1c1c" : "transparent",
                      color: isActive ? info.color : "#666666",
                      fontSize: 12,
                      fontWeight: isActive ? 600 : 400,
                      fontFamily: "inherit",
                      cursor: "pointer",
                      border: "none",
                      borderBottom: isActive
                        ? `2px solid ${info.color}`
                        : "2px solid transparent",
                      transition: "color 0.15s, border-color 0.15s",
                    }}
                  >
                    {info.label}
                  </button>
                );
              })}
            </div>

            {/* Terminal panes */}
            <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
              {activeConv.tabs.map(({ tabId, providerId }) => (
                <div
                  key={tabId}
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: providerId === activeProvider ? "block" : "none",
                  }}
                >
                  <TerminalPane
                    tabId={tabId}
                    active={providerId === activeProvider}
                  />
                </div>
              ))}
            </div>
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#3a3a3a",
              fontSize: 13,
            }}
          >
            New Conversation을 눌러 시작하세요
          </div>
        )}
      </main>
    </div>
  );
}
