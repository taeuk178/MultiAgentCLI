import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { TitleBar } from "./components/TitleBar";
import { ProjectRow } from "./components/ProjectRow";
import { HUD } from "./components/HUD";
import { Composer } from "./components/Composer";
import { ChatPane } from "./components/ChatPane";
import { EmptyChatState } from "./components/EmptyChatState";
import {
  RightSidebar,
  type SidebarPanelMode,
} from "./components/RightSidebar";
import { RunningStatusBar } from "./components/RunningStatusBar";
import { useConversations } from "./hooks/useConversations";
import { usePendingChat } from "./hooks/usePendingChat";
import { useProviderRuntime } from "./hooks/useProviderRuntime";
import { onPtyExit, ptyCreate, ptyWrite } from "./lib/ipc";
import {
  type ChatFlowPhase,
  runAdvisedChat,
  runSingleProviderChat,
} from "./lib/chatFlow";
import { makeMessage } from "./lib/conversations";
import {
  PROVIDERS,
  type ConversationEntry,
  type ConversationMode,
  type ProviderId,
} from "./lib/types";

const TerminalPane = lazy(() =>
  import("./components/TerminalPane").then((module) => ({
    default: module.TerminalPane,
  })),
);

export default function App() {
  const [composerText, setComposerText] = useState("");
  const [newConversationMode, setNewConversationMode] =
    useState<ConversationMode>("quick");
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);
  const [rightSidebarMode, setRightSidebarMode] =
    useState<SidebarPanelMode>("local");
  const {
    pendingConvId,
    pendingLabel,
    pendingStartedAt,
    start: startPending,
    setLabel: setPendingLabel,
    clear: clearPending,
  } = usePendingChat();
  const conversationsState = useConversations(pendingConvId, newConversationMode);
  const {
    conversations,
    activeConvId,
    activeConv,
    setActiveConvId,
    updateConv,
    handleNew,
    handleDelete,
    handleProviderSwitch,
    handleAdvisorChange,
    handleProjectChange,
    handleClearChat,
  } = conversationsState;
  const { runtime: providerRuntime, health, refresh: refreshProviderRuntime } =
    useProviderRuntime();
  const isRunning = pendingConvId === activeConvId;
  const activeMode = activeConv ? activeConv.mode ?? "quick" : newConversationMode;
  const activeProvider = activeConv?.provider ?? "claude";
  const activeTab = useMemo(
    () => activeConv?.tabs.find((tab) => tab.providerId === activeProvider) ?? null,
    [activeConv, activeProvider],
  );
  const [interactiveTabs, setInteractiveTabs] = useState<Set<string>>(() => new Set());
  const [interactiveFailures, setInteractiveFailures] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const unlisten = onPtyExit(({ tab_id }) => {
      if (cancelled) return;
      setInteractiveTabs((prev) => {
        const next = new Set(prev);
        next.delete(tab_id);
        return next;
      });
    });

    return () => {
      cancelled = true;
      unlisten.then((fn) => fn());
    };
  }, []);

  const ensureInteractiveSession = useCallback(
    async (conv: ConversationEntry) => {
      const tab = conv.tabs.find((item) => item.providerId === conv.provider);
      if (!tab) {
        throw new Error("활성 provider 터미널 탭을 찾을 수 없습니다.");
      }
      if (interactiveTabs.has(tab.tabId)) {
        return tab;
      }

      await ptyCreate(tab.tabId, conv.provider, 120, 32, conv.project ?? undefined);
      setInteractiveTabs((prev) => new Set(prev).add(tab.tabId));
      setInteractiveFailures((prev) => {
        const next = { ...prev };
        delete next[tab.tabId];
        return next;
      });
      return tab;
    },
    [interactiveTabs],
  );

  const handlePtyControl = useCallback(
    async (data: string) => {
      if (activeMode !== "develop" || !activeConv) return;

      try {
        const tab = await ensureInteractiveSession(activeConv);
        await ptyWrite(tab.tabId, data);
      } catch (err) {
        const providerMessage = makeMessage(
          "provider",
          `터미널 제어 입력 실패: ${err instanceof Error ? err.message : String(err)}`,
          activeConv.provider,
        );
        updateConv(activeConv.id, {
          messages: [...activeConv.messages, providerMessage],
        });
      }
    },
    [activeConv, activeMode, ensureInteractiveSession, updateConv],
  );

  useEffect(() => {
    if (activeMode !== "develop" || !activeConv) return;
    const tab = activeConv.tabs.find((item) => item.providerId === activeConv.provider);
    if (!tab || interactiveFailures[tab.tabId]) return;

    ensureInteractiveSession(activeConv).catch((err) => {
      const message = err instanceof Error ? err.message : String(err);
      setInteractiveFailures((prev) => ({
        ...prev,
        [tab.tabId]: message,
      }));
      const providerMessage = makeMessage(
        "provider",
        `터미널 세션 시작 실패: ${message}`,
        activeConv.provider,
      );
      updateConv(activeConv.id, {
        messages: [...activeConv.messages, providerMessage],
      });
    });
  }, [activeConv, activeMode, ensureInteractiveSession, interactiveFailures, updateConv]);

  const handleSend = useCallback(async () => {
    if (!composerText.trim() || !activeConv || (activeMode === "quick" && isRunning)) {
      return;
    }
    const message = composerText.trim();
    setComposerText("");

    if (activeMode === "develop") {
      try {
        const targetTab = activeConv.tabs.find((item) => item.providerId === activeConv.provider);
        if (targetTab) {
          setInteractiveFailures((prev) => {
            const next = { ...prev };
            delete next[targetTab.tabId];
            return next;
          });
        }
        const tab = await ensureInteractiveSession(activeConv);
        await ptyWrite(tab.tabId, `${message}\r`);
      } catch (err) {
        const providerMessage = makeMessage(
          "provider",
          `터미널 세션 전송 실패: ${err instanceof Error ? err.message : String(err)}`,
          activeConv.provider,
        );
        updateConv(activeConv.id, {
          messages: [...activeConv.messages, providerMessage],
        });
      }
      return;
    }

    const provider = activeConv.provider;
    const advisor = activeConv.advisor;
    const userMessage = makeMessage("user", message);
    const history = [...activeConv.messages, userMessage];

    updateConv(activeConv.id, { messages: history });
    startPending(activeConv.id);
    const updatePendingPhase = pendingPhaseLabel(provider, advisor, setPendingLabel);

    try {
      const response = advisor
        ? await runAdvisedChat(provider, advisor, history, activeConv.project, updatePendingPhase)
        : await runSingleProviderChat(provider, history, activeConv.project, updatePendingPhase);
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
      refreshProviderRuntime().catch(() => undefined);
      clearPending();
    }
  }, [
    composerText,
    activeConv,
    activeMode,
    isRunning,
    ensureInteractiveSession,
    startPending,
    setPendingLabel,
    clearPending,
    refreshProviderRuntime,
    updateConv,
  ]);

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
        newConversationMode={newConversationMode}
        onNewConversationModeChange={setNewConversationMode}
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
          providerStatuses={providerRuntime}
          isRunning={isRunning}
          onProviderSwitch={handleProviderSwitch}
        />

        {/* Chat area */}
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
          {activeConv && activeMode === "develop" && activeTab ? (
            interactiveFailures[activeTab.tabId] ? (
              <TerminalLoading label={`세션 시작 실패: ${interactiveFailures[activeTab.tabId]}`} />
            ) : interactiveTabs.has(activeTab.tabId) ? (
              <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                <TerminalControlBar
                  onEnter={() => handlePtyControl("\r")}
                  onEscape={() => handlePtyControl("\x1b")}
                  onInterrupt={() => handlePtyControl("\x03")}
                />
                <div style={{ flex: 1, minHeight: 0 }}>
                  <Suspense fallback={<TerminalLoading label="터미널을 불러오는 중..." />}>
                    <TerminalPane
                      key={activeTab.tabId}
                      tabId={activeTab.tabId}
                      active
                    />
                  </Suspense>
                </div>
              </div>
            ) : (
              <TerminalLoading label={`${PROVIDERS[activeProvider].label} 세션 시작 중...`} />
            )
          ) : activeConv ? (
            <ChatPane
              messages={activeConv.messages}
              activeProvider={activeProvider}
              isRunning={isRunning}
            />
          ) : (
            <EmptyChatState />
          )}
        </div>

        {activeConv && isRunning && (
          <RunningStatusBar
            activeProvider={activeProvider}
            pendingLabel={pendingLabel}
            pendingStartedAt={pendingStartedAt}
          />
        )}

        {activeConv && (
          <Composer
            value={composerText}
            provider={activeProvider}
            mode={activeMode}
            isRunning={activeMode === "quick" && isRunning}
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

function TerminalLoading({ label }: { label: string }) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--fg-dim)",
        fontFamily: "var(--mono)",
        fontSize: 12,
      }}
    >
      {label}
    </div>
  );
}

function TerminalControlBar({
  onEnter,
  onEscape,
  onInterrupt,
}: {
  onEnter: () => void;
  onEscape: () => void;
  onInterrupt: () => void;
}) {
  const controls = [
    { label: "Enter", onClick: onEnter },
    { label: "Esc", onClick: onEscape },
    { label: "Ctrl+C", onClick: onInterrupt },
  ];

  return (
    <div
      style={{
        height: 30,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 10px",
        borderTop: "1px solid var(--divider)",
        borderBottom: "1px solid var(--divider)",
        background: "var(--bg-content)",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          color: "var(--fg-dim)",
          fontSize: 11,
          fontFamily: "var(--mono)",
          marginRight: 2,
        }}
      >
        output-only
      </span>
      {controls.map((control) => (
        <button
          key={control.label}
          className="terminal-control-button"
          onClick={control.onClick}
          style={{
            height: 20,
            padding: "0 7px",
            borderRadius: 4,
            border: "1px solid var(--border)",
            color: "var(--fg-2)",
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            background: "var(--bg-card)",
          }}
        >
          {control.label}
        </button>
      ))}
    </div>
  );
}

function pendingPhaseLabel(
  provider: ProviderId,
  advisor: ProviderId | null,
  setPendingLabel: (label: string | null) => void,
) {
  const primaryName = PROVIDERS[provider].label;
  const advisorName = advisor ? PROVIDERS[advisor].label : null;

  return (phase: ChatFlowPhase) => {
    switch (phase) {
      case "responding":
        setPendingLabel(`${primaryName}가 입력 중...`);
        return;
      case "drafting":
        setPendingLabel(`${primaryName}가 초안을 작성 중...`);
        return;
      case "reviewing":
        setPendingLabel(`${advisorName ?? "Advisor"}가 초안을 검토 중...`);
        return;
      case "synthesizing":
        setPendingLabel(
          `${primaryName}와 ${advisorName ?? "Advisor"}가 최종 답변을 조율 중...`,
        );
    }
  };
}
