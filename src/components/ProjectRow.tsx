import { open } from "@tauri-apps/plugin-dialog";
import { AdvisorPopover } from "./AdvisorPopover";
import { IconFolder } from "./Icons";
import type { ConversationEntry, ProviderId } from "../lib/types";

interface Props {
  conv: ConversationEntry | null;
  isRunning: boolean;
  onAdvisorChange: (advisor: ProviderId | null) => void;
  onProjectChange: (path: string) => void;
}

function GhostBtn({
  children,
  onClick,
  disabled,
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        height: 24,
        padding: "0 9px",
        borderRadius: 6,
        border: "1px solid var(--border)",
        background: "transparent",
        color: "var(--fg-2)",
        fontSize: 11.5,
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        transition: "background 120ms",
        whiteSpace: "nowrap",
        fontFamily: "var(--ui)",
      }}
      onMouseEnter={(e) => {
        if (disabled) return;
        (e.currentTarget as HTMLElement).style.background =
          "rgba(255,255,255,0.04)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = "transparent";
      }}
    >
      {children}
    </button>
  );
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
      <GhostBtn onClick={conv ? handlePickFolder : undefined} disabled={!conv}>
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
      </GhostBtn>

      <div style={{ flex: 1 }} />

      {/* Advisor */}
      <AdvisorPopover
        advisor={conv?.advisor ?? null}
        provider={provider}
        disabled={isRunning || !conv}
        onChange={onAdvisorChange}
      />

    </div>
  );
}
