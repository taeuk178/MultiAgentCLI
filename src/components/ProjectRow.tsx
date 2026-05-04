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
  const mode = conv?.mode ?? "quick";

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

      {conv && <ModeChip mode={mode} />}

      <AdvisorPopover
        advisor={conv?.advisor ?? null}
        provider={provider}
        disabled={isRunning || !conv || mode === "develop"}
        onChange={onAdvisorChange}
      />
    </div>
  );
}

function ModeChip({ mode }: { mode: "quick" | "develop" }) {
  return (
    <span
      style={{
        height: 24,
        display: "inline-flex",
        alignItems: "center",
        padding: "0 8px",
        borderRadius: 6,
        border: "1px solid var(--border)",
        background: "var(--bg-card)",
        color: "var(--fg-dim)",
        fontFamily: "var(--mono)",
        fontSize: 10.5,
        fontWeight: 700,
      }}
    >
      {mode === "quick" ? "Quick" : "Dev"}
    </span>
  );
}
