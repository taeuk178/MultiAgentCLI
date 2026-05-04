import { useEffect, useState } from "react";
import type { ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  activeProvider: ProviderId;
  pendingLabel: string | null;
  pendingStartedAt: number | null;
}

export function RunningStatusBar({
  activeProvider,
  pendingLabel,
  pendingStartedAt,
}: Props) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!pendingStartedAt) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [pendingStartedAt]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "9px 22px",
        borderTop: "1px solid var(--divider)",
        background: "var(--bg-content)",
        color: "var(--fg-dim)",
        fontFamily: "var(--ui)",
        fontSize: 12,
        flexShrink: 0,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: PROVIDERS[activeProvider].color,
          animation: "led-pulse 1.2s ease-in-out infinite",
          flexShrink: 0,
        }}
      />
      <span>
        {pendingLabel ?? `${PROVIDERS[activeProvider].label}가 입력 중...`}
        {pendingStartedAt ? ` ${formatElapsed(now - pendingStartedAt)}` : ""}
      </span>
    </div>
  );
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes === 0) {
    return `(${seconds}s)`;
  }

  return `(${minutes}m ${seconds}s)`;
}
