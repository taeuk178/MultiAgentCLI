import { useEffect, useRef } from "react";
import { IconAttach, IconSend, IconStop } from "./Icons";
import type { ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  value: string;
  provider: ProviderId;
  advisor?: ProviderId | null;
  isRunning: boolean;
  disabled?: boolean;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({
  value,
  provider,
  advisor,
  isRunning,
  disabled,
  onChange,
  onSend,
  onStop,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }, [value]);

  const placeholder = isRunning
    ? "Running… press esc to stop"
    : advisor
    ? `Message ${PROVIDERS[provider].label} + ${PROVIDERS[advisor].label} — ⌘+Return to send`
    : `Message ${PROVIDERS[provider].label} — Return for new line, ⌘+Return to send`;

  return (
    <div
      style={{
        borderTop: "1px solid var(--divider)",
        background: "var(--bg-content)",
        padding: "8px 16px 14px",
        flexShrink: 0,
      }}
    >
      {/* Flow badge */}
      {advisor && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            color: "var(--fg-dim)",
            marginBottom: 8,
          }}
        >
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              background: PROVIDERS[provider].bgColor,
              color: PROVIDERS[provider].color,
              fontWeight: 700,
            }}
          >
            {PROVIDERS[provider].glyph} {PROVIDERS[provider].label}
          </span>
          <span style={{ color: "var(--fg-faint)" }}>→</span>
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              background: PROVIDERS[advisor].bgColor,
              color: PROVIDERS[advisor].color,
              fontWeight: 700,
            }}
          >
            {PROVIDERS[advisor].glyph} {PROVIDERS[advisor].label}
          </span>
          <span style={{ color: "var(--fg-faint)", marginLeft: 4, fontSize: 10 }}>
            동시 전송
          </span>
        </div>
      )}
      <div
        className="composer-box"
        style={{
          border: `1px solid ${isRunning ? "rgba(240,180,41,0.4)" : "var(--border)"}`,
          background: "var(--bg-input)",
          borderRadius: 10,
          padding: "10px 12px 8px",
          transition: "border-color 140ms, box-shadow 140ms",
        }}
      >
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              onSend();
            }
            if (e.key === "Escape" && isRunning) {
              e.preventDefault();
              onStop();
            }
          }}
          placeholder={placeholder}
          rows={1}
          disabled={isRunning || disabled}
          style={{
            width: "100%",
            background: "transparent",
            border: "none",
            outline: "none",
            resize: "none",
            color: "var(--fg)",
            fontFamily: "var(--ui)",
            fontSize: 13.5,
            lineHeight: 1.5,
            minHeight: 22,
            maxHeight: 160,
          }}
        />

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginTop: 6,
          }}
        >
          {/* Attach */}
          <button
            title="Attach file"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 28,
              height: 28,
              borderRadius: 6,
              color: "var(--fg-dim)",
              background: "transparent",
              cursor: "pointer",
              transition: "color 120ms",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLElement).style.color = "var(--fg)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLElement).style.color = "var(--fg-dim)")
            }
          >
            <IconAttach size={13} />
          </button>

          {/* Keycap hint */}
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10.5,
              color: "var(--fg-dim)",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
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
              ⌘
            </kbd>
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
              ↵
            </kbd>
            <span>send</span>
          </span>

          <div style={{ flex: 1 }} />

          {/* Send / Stop */}
          {isRunning ? (
            <button
              onClick={onStop}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                height: 24,
                padding: "0 9px",
                borderRadius: 6,
                border: "1px solid rgba(255,95,87,0.3)",
                background: "transparent",
                color: "#ff8b85",
                fontSize: 11.5,
                fontWeight: 500,
                cursor: "pointer",
                transition: "background 120ms",
                fontFamily: "var(--ui)",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background =
                  "rgba(255,95,87,0.12)";
                (e.currentTarget as HTMLElement).style.borderColor =
                  "rgba(255,95,87,0.5)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "transparent";
                (e.currentTarget as HTMLElement).style.borderColor =
                  "rgba(255,95,87,0.3)";
              }}
            >
              <IconStop size={12} />
              <span>Stop</span>
            </button>
          ) : (
            <button
              onClick={onSend}
              disabled={!value.trim() || disabled}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                height: 24,
                padding: "0 9px",
                borderRadius: 6,
                border: "1px solid transparent",
                background: "var(--accent)",
                color: "white",
                fontSize: 11.5,
                fontWeight: 500,
                cursor: !value.trim() || disabled ? "not-allowed" : "pointer",
                opacity: !value.trim() || disabled ? 0.45 : 1,
                boxShadow:
                  "0 1px 0 rgba(255,255,255,0.15) inset, 0 1px 2px rgba(0,0,0,0.3)",
                transition: "background 120ms",
                fontFamily: "var(--ui)",
              }}
              onMouseEnter={(e) => {
                if (!value.trim() || disabled) return;
                (e.currentTarget as HTMLElement).style.background = "#6f9cf2";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--accent)";
              }}
            >
              <IconSend size={13} />
              <span>Send</span>
            </button>
          )}
        </div>
      </div>

      {/* Focus-within style via a global scoped rule */}
      <style>{`
        .composer-box:focus-within {
          border-color: var(--accent) !important;
          box-shadow: 0 0 0 3px rgba(91,141,239,0.18);
        }
      `}</style>
    </div>
  );
}
