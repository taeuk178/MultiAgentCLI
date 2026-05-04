import { IconSidebar } from "./Icons";
import { IconButton } from "./ui";
import type { HealthStatus, ProviderId } from "../lib/types";
import { PROVIDERS, PROVIDER_IDS } from "../lib/types";

interface Props {
  health: Record<ProviderId, HealthStatus>;
  rightSidebarOpen: boolean;
  onToggleRightSidebar: () => void;
}

const STATUS_LABEL: Record<HealthStatus, string> = {
  healthy: "Ready",
  error: "Unavailable",
  unknown: "Checking…",
  disabled: "Disabled",
};

const LED_COLOR: Record<HealthStatus, string> = {
  healthy: "var(--ok)",
  error: "var(--danger)",
  unknown: "var(--fg-faint)",
  disabled: "var(--fg-faint)",
};

const TOOLTIP: Record<ProviderId, string> = {
  claude: "claude auth status: ok",
  codex: "codex login status: ok",
  gemini: "Installed. OAuth verified on first prompt.",
};

function HealthPill({
  provider,
  status,
}: {
  provider: ProviderId;
  status: HealthStatus;
}) {
  const info = PROVIDERS[provider];
  const ledColor = LED_COLOR[status];

  return (
    <div
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        height: 24,
        padding: "0 9px",
        borderRadius: 12,
        border: "1px solid var(--border)",
        background: "var(--bg-card)",
        fontSize: 11,
        fontWeight: 500,
        color: "var(--fg-2)",
        cursor: "default",
        userSelect: "none",
      }}
      className="health-pill-wrap"
    >
      {/* LED */}
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          flexShrink: 0,
          background: ledColor,
          boxShadow:
            status === "healthy"
              ? "0 0 0 2px rgba(62,207,142,0.18)"
              : "none",
        }}
      />
      {/* Glyph */}
      <span
        style={{
          fontFamily: "var(--mono)",
          fontSize: 10,
          fontWeight: 700,
          color: "var(--fg-dim)",
          marginRight: 1,
        }}
      >
        {info.glyph}
      </span>
      {/* Label */}
      <span>{STATUS_LABEL[status]}</span>

      {/* Tooltip */}
      <span
        className="health-tip"
        style={{
          position: "absolute",
          top: "calc(100% + 6px)",
          right: 0,
          background: "#0e0e10",
          border: "1px solid var(--border-strong)",
          color: "var(--fg-2)",
          fontSize: 11,
          padding: "6px 9px",
          borderRadius: 6,
          whiteSpace: "nowrap",
          pointerEvents: "none",
          opacity: 0,
          transition: "opacity 120ms",
          zIndex: 100,
          boxShadow: "0 6px 16px rgba(0,0,0,0.4)",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.opacity = "1";
        }}
      >
        {TOOLTIP[provider]}
      </span>

      <style>{`
        .health-pill-wrap:hover .health-tip { opacity: 1 !important; }
      `}</style>
    </div>
  );
}

export function TitleBar({
  health,
  rightSidebarOpen,
  onToggleRightSidebar,
}: Props) {
  return (
    <div
      style={{
        background: "var(--bg-window)",
        borderBottom: "1px solid var(--divider)",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          height: 44,
          padding: "0 14px",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
        {...{ "data-tauri-drag-region": true }}
      >
        {/* Title */}
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            letterSpacing: "-0.1px",
            color: "var(--fg)",
            userSelect: "none",
          }}
        >
          MultiAgentCLI
        </span>

        {/* Version chip */}
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            color: "var(--fg-dim)",
            padding: "2px 6px",
            borderRadius: 4,
            background: "rgba(255,255,255,0.05)",
            userSelect: "none",
          }}
        >
          v0.1.0
        </span>

        <div style={{ flex: 1 }} {...{ "data-tauri-drag-region": true }} />

        {/* Health pills */}
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {PROVIDER_IDS.map((p) => (
            <HealthPill key={p} provider={p} status={health[p]} />
          ))}
        </div>

        <div style={{ width: 4 }} />

        <IconButton
          title={rightSidebarOpen ? "Hide right sidebar" : "Show right sidebar"}
          active={rightSidebarOpen}
          onClick={onToggleRightSidebar}
        >
          <span style={{ transform: "scaleX(-1)", display: "inline-flex" }}>
            <IconSidebar size={14} />
          </span>
        </IconButton>
      </div>
    </div>
  );
}
