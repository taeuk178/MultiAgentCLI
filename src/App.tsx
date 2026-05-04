import { useCallback, useState } from "react";
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
import {
  type ChatFlowPhase,
  runAdvisedChat,
  runSingleProviderChat,
} from "./lib/chatFlow";
import { makeMessage } from "./lib/conversations";
import { PROVIDERS, type ProviderId } from "./lib/types";

export default function App() {
  const [composerText, setComposerText] = useState("");
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
  const conversationsState = useConversations(pendingConvId);
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

  const handleSend = useCallback(async () => {
    if (!composerText.trim() || !activeConv || isRunning) return;
    const message = composerText.trim();
    setComposerText("");
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
    isRunning,
    startPending,
    setPendingLabel,
    clearPending,
    refreshProviderRuntime,
    updateConv,
  ]);

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
          {activeConv ? (
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
