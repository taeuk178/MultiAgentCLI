import type { CSSProperties, ReactNode } from "react";
import type { ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface ProviderDotProps {
  providerId: ProviderId;
  size?: number;
  style?: CSSProperties;
}

export function ProviderDot({
  providerId,
  size = 6,
  style,
}: ProviderDotProps) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: PROVIDERS[providerId].color,
        flexShrink: 0,
        display: "inline-block",
        ...style,
      }}
    />
  );
}

export function Keycap({ children }: { children: ReactNode }) {
  return (
    <kbd
      style={{
        fontFamily: "var(--mono)",
        fontSize: 10,
        padding: "1px 5px",
        borderRadius: 3,
        background: "rgba(255,255,255,0.06)",
        border: "1px solid var(--border)",
        color: "var(--fg-2)",
      }}
    >
      {children}
    </kbd>
  );
}

interface GhostButtonProps {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  style?: CSSProperties;
}

export function GhostButton({
  children,
  onClick,
  disabled,
  title,
  style,
}: GhostButtonProps) {
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
        ...style,
      }}
      onMouseEnter={(e) => {
        if (disabled) return;
        e.currentTarget.style.background = "rgba(255,255,255,0.04)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      {children}
    </button>
  );
}

interface IconButtonProps {
  children: ReactNode;
  active?: boolean;
  disabled?: boolean;
  title?: string;
  onClick?: () => void;
  size?: number;
  style?: CSSProperties;
}

export function IconButton({
  children,
  active,
  disabled,
  title,
  onClick,
  size = 28,
  style,
}: IconButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        width: size,
        height: size,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: 6,
        border: "1px solid transparent",
        background: active ? "rgba(255,255,255,0.08)" : "transparent",
        color: active ? "var(--fg)" : "var(--fg-dim)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        transition: "all 120ms",
        flexShrink: 0,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (disabled) return;
        e.currentTarget.style.background = "rgba(255,255,255,0.06)";
        e.currentTarget.style.color = "var(--fg)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = active
          ? "rgba(255,255,255,0.08)"
          : "transparent";
        e.currentTarget.style.color = active ? "var(--fg)" : "var(--fg-dim)";
      }}
    >
      {children}
    </button>
  );
}
