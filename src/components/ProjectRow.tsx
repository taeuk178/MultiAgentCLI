import { AdvisorPopover } from "./AdvisorPopover";
import { IconFolder, IconLogin, IconLogout, IconTrash } from "./Icons";
import type { ConversationEntry, ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  conv: ConversationEntry | null;
  isRunning: boolean;
  onAdvisorChange: (advisor: ProviderId | null) => void;
  onClearChat: () => void;
}

function GhostBtn({
  children,
  onClick,
  disabled,
  danger,
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  danger?: boolean;
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
        border: danger
          ? "1px solid rgba(255,95,87,0.3)"
          : "1px solid var(--border)",
        background: "transparent",
        color: danger ? "#ff8b85" : "var(--fg-2)",
        fontSize: 11.5,
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        transition: "background 120ms, border-color 120ms",
        whiteSpace: "nowrap",
        fontFamily: "var(--ui)",
      }}
      onMouseEnter={(e) => {
        if (disabled) return;
        if (danger) {
          (e.currentTarget as HTMLElement).style.background =
            "rgba(255,95,87,0.12)";
          (e.currentTarget as HTMLElement).style.borderColor =
            "rgba(255,95,87,0.5)";
        } else {
          (e.currentTarget as HTMLElement).style.background =
            "rgba(255,255,255,0.04)";
        }
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = "transparent";
        (e.currentTarget as HTMLElement).style.borderColor = danger
          ? "rgba(255,95,87,0.3)"
          : "var(--border)";
      }}
    >
      {children}
    </button>
  );
}

export function ProjectRow({ conv, isRunning, onAdvisorChange, onClearChat }: Props) {
  const provider = conv?.provider ?? "claude";
  const info = PROVIDERS[provider];
  const hasMessages = false; // will be wired when chat is implemented

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
      {/* Project button */}
      <GhostBtn>
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

      {/* Login / Logout */}
      {info.hasShellAuth ? (
        <GhostBtn danger title={`Logout ${info.label}`}>
          <IconLogout size={13} />
          <span>Logout {info.label}</span>
        </GhostBtn>
      ) : (
        <GhostBtn title="Sign in via Terminal">
          <IconLogin size={13} />
          <span>Login via Terminal</span>
        </GhostBtn>
      )}

      {/* Clear chat */}
      <GhostBtn
        onClick={onClearChat}
        disabled={isRunning || !hasMessages || !conv}
        title="Clear Chat"
      >
        <IconTrash size={13} />
        <span>Clear Chat</span>
      </GhostBtn>
    </div>
  );
}
