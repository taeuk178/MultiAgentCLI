import type {
  ChatMessage,
  ConversationEntry,
  HealthStatus,
  ProviderId,
  ProviderRuntimeStatus,
} from "../lib/types";
import { PROVIDER_IDS, PROVIDERS } from "../lib/types";

interface Props {
  conv: ConversationEntry | null;
  providerStatuses: Record<ProviderId, ProviderRuntimeStatus>;
  isRunning: boolean;
  onProviderSwitch: (provider: ProviderId) => void;
}

const LED_COLOR: Record<HealthStatus, string> = {
  healthy: "var(--ok)",
  error: "var(--danger)",
  unknown: "var(--fg-faint)",
  disabled: "var(--fg-faint)",
};

function ctxPct(ctxTokens: number, ctxWindow: number): number {
  return Math.round((ctxTokens / ctxWindow) * 100);
}

function estimateContextTokens(messages: ChatMessage[]): number {
  return Math.ceil(
    messages.reduce((sum, message) => sum + message.content.length, 0) / 4,
  );
}

interface CardProps {
  providerId: ProviderId;
  runtime: ProviderRuntimeStatus;
  active: boolean;
  contextUsedPercent: number | null;
  streaming: boolean;
  disabled: boolean;
  onClick: () => void;
}

function HUDCard({
  providerId,
  runtime,
  active,
  contextUsedPercent,
  streaming,
  disabled,
  onClick,
}: CardProps) {
  const info = PROVIDERS[providerId];
  const health = runtime.health;
  const ledColor = LED_COLOR[health];
  const barWidth = contextUsedPercent == null ? 0 : Math.min(100, contextUsedPercent);

  const activeBorderStyle = active
    ? {
        borderColor: info.color,
        boxShadow: `0 0 0 1px ${info.color} inset`,
      }
    : {};

  return (
    <button
      className={active ? "hud-card is-active" : "hud-card"}
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "11px 14px 12px",
        borderRadius: 9,
        border: "1px solid var(--border)",
        background: active ? "var(--bg-card-hi)" : "var(--bg-card)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        transition: "all 140ms",
        textAlign: "left",
        fontFamily: "var(--ui)",
        color: "inherit",
        minWidth: 0,
        ...activeBorderStyle,
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          fontSize: 12.5,
          fontWeight: 600,
          color: "var(--fg)",
        }}
      >
        {/* LED */}
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: ledColor,
            opacity: health === "disabled" ? 0.5 : 1,
            flexShrink: 0,
          }}
        />
        <span>{info.label}</span>
      </div>

      {/* Meta row */}
      <div
        style={{
          display: "flex",
          gap: 8,
          fontFamily: "var(--mono)",
          fontSize: 10.5,
          color: "var(--fg-dim)",
        }}
      >
        <span title={runtime.model}>model:{runtime.model}</span>
        <span style={{ color: "var(--fg-faint)" }}>·</span>
        <span>Context Used {formatPercent(contextUsedPercent)}</span>
        <span style={{ color: "var(--fg-faint)" }}>·</span>
        <span>
          5h {formatPercent(runtime.fiveHourPercent)}
          {formatReset(runtime.fiveHourResetSeconds)}
        </span>
      </div>

      {/* Progress bar */}
      <div
        style={{
          height: 3,
          borderRadius: 2,
          background: "rgba(255,255,255,0.05)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            borderRadius: 2,
            width: `${barWidth}%`,
            background: info.color,
            transition: "width 200ms",
            animation: streaming
              ? "stream-pulse 1.6s ease-in-out infinite"
              : "none",
          }}
        />
      </div>
    </button>
  );
}

export function HUD({
  conv,
  providerStatuses,
  isRunning,
  onProviderSwitch,
}: Props) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        padding: "12px 14px",
        borderBottom: "1px solid var(--divider)",
        background: "var(--bg-content)",
        flexShrink: 0,
      }}
    >
      {/* "Provider" label */}
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "var(--fg-dim)",
          letterSpacing: "0.3px",
          textTransform: "uppercase",
          alignSelf: "flex-start",
          paddingTop: 14,
          minWidth: 64,
          userSelect: "none",
        }}
      >
        Provider
      </div>

      {/* Cards */}
      {PROVIDER_IDS.map((pid) => {
        const active = conv?.provider === pid;
        const streaming = false; // wired up at M6
        const ctxTokens = estimateContextTokens(conv?.messages ?? []);
        const runtime = providerStatuses[pid];
        const fallbackCtxPct =
          ctxTokens > 0 ? ctxPct(ctxTokens, PROVIDERS[pid].ctxWindow) : null;
        const contextUsedPercent = runtime.contextUsedPercent ?? fallbackCtxPct;

        return (
          <HUDCard
            key={pid}
            providerId={pid}
            runtime={runtime}
            active={!!active}
            contextUsedPercent={contextUsedPercent}
            streaming={streaming}
            disabled={isRunning && !active}
            onClick={() => onProviderSwitch(pid)}
          />
        );
      })}
    </div>
  );
}

function formatPercent(percent: number | null): string {
  return percent == null ? "--" : `${percent}%`;
}

function formatReset(seconds: number | null): string {
  if (seconds == null) {
    return "";
  }

  const totalMinutes = Math.max(0, Math.ceil(seconds / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return ` (${hours}h${minutes}m)`;
}
