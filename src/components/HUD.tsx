import type { ConversationEntry, HealthStatus, ProviderId } from "../lib/types";
import { PROVIDER_IDS, PROVIDERS } from "../lib/types";

interface Props {
  conv: ConversationEntry | null;
  health: Record<ProviderId, HealthStatus>;
  isRunning: boolean;
  onProviderSwitch: (provider: ProviderId) => void;
}

const LED_COLOR: Record<HealthStatus, string> = {
  healthy: "var(--ok)",
  error: "var(--danger)",
  unknown: "var(--fg-faint)",
  disabled: "var(--fg-faint)",
};

function sessionAge(startedAt: number): string {
  const m = Math.round((Date.now() - startedAt) / 60_000);
  return m + "m";
}

function ctxPct(ctxTokens: number, ctxWindow: number): number {
  return Math.round((ctxTokens / ctxWindow) * 100);
}

interface CardProps {
  provider: ProviderId;
  active: boolean;
  health: HealthStatus;
  sessionAgeStr: string;
  ctxPctNum: number;
  streaming: boolean;
  disabled: boolean;
  onClick: () => void;
}

function HUDCard({
  provider,
  active,
  health,
  sessionAgeStr,
  ctxPctNum,
  streaming,
  disabled,
  onClick,
}: CardProps) {
  const info = PROVIDERS[provider];
  const ledColor = LED_COLOR[health];
  const barWidth = Math.min(100, ctxPctNum * 4);

  const activeBorderStyle = active
    ? {
        borderColor: info.color,
        boxShadow: `0 0 0 1px ${info.color} inset`,
      }
    : {};

  return (
    <button
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
      onMouseEnter={(e) => {
        if (disabled) return;
        (e.currentTarget as HTMLElement).style.background = "var(--bg-card-hi)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = active
          ? "var(--bg-card-hi)"
          : "var(--bg-card)";
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
        <span>session:{sessionAgeStr}</span>
        <span style={{ color: "var(--fg-faint)" }}>·</span>
        <span>ctx:{ctxPctNum}%</span>
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

export function HUD({ conv, health, isRunning, onProviderSwitch }: Props) {
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
        const session = conv?.sessions[pid] ?? null;
        const active = conv?.provider === pid;
        const streaming = false; // wired up at M6

        return (
          <HUDCard
            key={pid}
            provider={pid}
            active={!!active}
            health={health[pid]}
            sessionAgeStr={session ? sessionAge(session.startedAt) : "—"}
            ctxPctNum={
              session
                ? ctxPct(session.ctxTokens, PROVIDERS[pid].ctxWindow)
                : 0
            }
            streaming={streaming}
            disabled={isRunning && !active}
            onClick={() => onProviderSwitch(pid)}
          />
        );
      })}
    </div>
  );
}
