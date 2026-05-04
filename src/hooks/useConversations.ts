import { useCallback, useMemo, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { makeConversation } from "../lib/conversations";
import type { ConversationEntry, ProviderId } from "../lib/types";

export function useConversations(pendingConvId: string | null) {
  const [conversations, setConversations] = useState<ConversationEntry[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  const activeConv = useMemo(
    () => conversations.find((conv) => conv.id === activeConvId) ?? null,
    [activeConvId, conversations],
  );

  const updateConv = useCallback((id: string, patch: Partial<ConversationEntry>) => {
    setConversations((prev) =>
      prev.map((conv) => (conv.id === id ? { ...conv, ...patch } : conv)),
    );
  }, []);

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
        const next = prev.filter((conv) => conv.id !== id);
        if (id === activeConvId) {
          setActiveConvId(next[0]?.id ?? null);
        }
        return next;
      });
    },
    [activeConvId],
  );

  const handleProviderSwitch = useCallback(
    (provider: ProviderId) => {
      if (!activeConvId || pendingConvId === activeConvId) return;
      updateConv(activeConvId, {
        provider,
        advisor: activeConv?.advisor === provider ? null : activeConv?.advisor ?? null,
      });
    },
    [activeConv?.advisor, activeConvId, pendingConvId, updateConv],
  );

  const handleAdvisorChange = useCallback(
    (advisor: ProviderId | null) => {
      if (!activeConvId || pendingConvId === activeConvId) return;
      updateConv(activeConvId, { advisor });
    },
    [activeConvId, pendingConvId, updateConv],
  );

  const handleProjectChange = useCallback(
    (path: string) => {
      if (!activeConvId) return;
      updateConv(activeConvId, { project: path });
    },
    [activeConvId, updateConv],
  );

  const handleClearChat = useCallback(
    (id: string) => {
      if (!conversations.some((conv) => conv.id === id)) return;
      updateConv(id, { messages: [] });
    },
    [conversations, updateConv],
  );

  return {
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
  };
}
