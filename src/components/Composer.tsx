import { useEffect, useRef } from "react";
import { IconAttach, IconSend } from "./Icons";
import { IconButton, Keycap } from "./ui";
import type { ConversationMode, ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

const DEV_MODE_RAW_INPUT: Record<string, string> = {
  ArrowUp: "\x1b[A",
  ArrowDown: "\x1b[B",
  ArrowRight: "\x1b[C",
  ArrowLeft: "\x1b[D",
  Enter: "\r",
  Escape: "\x1b",
  Tab: "\t",
};

interface Props {
  value: string;
  provider: ProviderId;
  mode: ConversationMode;
  isRunning: boolean;
  disabled?: boolean;
  onChange: (v: string) => void;
  onSend: () => void;
  onRawInput?: (data: string) => void;
}

export function Composer({
  value,
  provider,
  mode,
  isRunning,
  disabled,
  onChange,
  onSend,
  onRawInput,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }, [value]);

  const placeholder = isRunning
    ? `${PROVIDERS[provider].label} 응답 대기 중`
    : mode === "develop"
      ? `${PROVIDERS[provider].label} 세션에 전송 - Cmd+Return`
      : `Message ${PROVIDERS[provider].label} - Cmd+Return`;

  return (
    <div
      style={{
        borderTop: "1px solid var(--divider)",
        background: "var(--bg-content)",
        padding: "8px 16px 14px",
        flexShrink: 0,
      }}
    >
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
              return;
            }

            if (mode === "develop" && !value && onRawInput && !e.nativeEvent.isComposing) {
              const rawInput = devModeRawInput(e.key);
              if (rawInput) {
                e.preventDefault();
                onRawInput(rawInput);
              }
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
          <IconButton
            title="Attach file"
            style={{ border: "none" }}
          >
            <IconAttach size={13} />
          </IconButton>

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
            <Keycap>⌘</Keycap>
            <Keycap>↵</Keycap>
            <span>send</span>
          </span>

          <div style={{ flex: 1 }} />

          {/* Send */}
          {isRunning ? (
            <button
              disabled
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                height: 24,
                padding: "0 9px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--fg-dim)",
                fontSize: 11.5,
                fontWeight: 500,
                cursor: "wait",
                opacity: 0.75,
                transition: "background 120ms",
                fontFamily: "var(--ui)",
              }}
            >
              <IconSend size={13} />
              <span>Send</span>
            </button>
          ) : (
            <button
              className="primary-button"
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
            >
              <IconSend size={13} />
              <span>Send</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function devModeRawInput(key: string): string | null {
  return DEV_MODE_RAW_INPUT[key] ?? null;
}
