import { open } from "@tauri-apps/plugin-dialog";
import { AdvisorPopover } from "./AdvisorPopover";
import { IconFolder } from "./Icons";
import { GhostButton } from "./ui";
import type { ConversationEntry, ProviderId } from "../lib/types";

interface Props {
  conv: ConversationEntry | null;
  isRunning: boolean;
  onAdvisorChange: (advisor: ProviderId | null) => void;
  onProjectChange: (path: string) => void;
}

export function ProjectRow({
  conv,
  isRunning,
  onAdvisorChange,
  onProjectChange,
}: Props) {
  const provider = conv?.provider ?? "claude";

  const handlePickFolder = async () => {
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: conv?.project ?? undefined,
      title: "프로젝트 폴더 선택",
    });
    if (typeof selected === "string" && selected) {
      onProjectChange(selected);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 14px",
        borderBottom: "1px solid var(--divider)",
        background: "var(--bg-content)",
        flexShrink: 0,
      }}
    >
      {/* Project folder picker */}
      <GhostButton onClick={conv ? handlePickFolder : undefined} disabled={!conv}>
        <IconFolder size={13} />
        <span
          style={{
            color: conv?.project ? "var(--fg)" : "var(--fg-dim)",
            fontFamily: conv?.project ? "var(--mono)" : "var(--ui)",
            fontSize: conv?.project ? 11 : 11.5,
          }}
        >
          {conv?.project
            ? conv.project.split("/").pop()
            : "No project selected"}
        </span>
      </GhostButton>

      <div style={{ flex: 1 }} />

      <AdvisorPopover
        advisor={conv?.advisor ?? null}
        provider={provider}
        disabled={isRunning || !conv}
        onChange={onAdvisorChange}
      />
    </div>
  );
}
