import { useEffect, useRef } from "react";
import type { ChatMessage, ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  messages: ChatMessage[];
  activeProvider: ProviderId;
  isRunning: boolean;
}

export function ChatPane({ messages, activeProvider, isRunning }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isRunning]);

  if (messages.length === 0) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--fg-dim)",
          fontSize: 13,
          userSelect: "none",
        }}
      >
        {PROVIDERS[activeProvider].label}에게 메시지를 보내세요.
      </div>
    );
  }

  return (
    <div
      style={{
        height: "100%",
        overflowY: "auto",
        padding: "18px 22px 28px",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {messages.map((message) => {
          const isUser = message.role === "user";
          const provider = message.providerId
            ? PROVIDERS[message.providerId]
            : PROVIDERS[activeProvider];

          return (
            <article
              key={message.id}
              style={{
                alignSelf: isUser ? "flex-end" : "flex-start",
                maxWidth: "min(780px, 82%)",
                display: "flex",
                flexDirection: "column",
                gap: 5,
              }}
            >
              <div
                style={{
                  alignSelf: isUser ? "flex-end" : "flex-start",
                  fontSize: 11,
                  fontWeight: 700,
                  color: isUser ? "var(--fg-dim)" : provider.color,
                }}
              >
                {isUser ? "You" : provider.label}
              </div>
              <div
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "10px 12px",
                  background: isUser ? "var(--bg-card-hi)" : "var(--bg-card)",
                  color: "var(--fg)",
                  fontFamily: "var(--ui)",
                  fontSize: 13,
                  lineHeight: 1.55,
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                }}
              >
                {message.content}
              </div>
            </article>
          );
        })}
        {isRunning && (
          <article
            style={{
              alignSelf: "flex-start",
              maxWidth: "min(780px, 82%)",
              color: "var(--fg-dim)",
              fontFamily: "var(--mono)",
              fontSize: 12,
            }}
          >
            {PROVIDERS[activeProvider].label} 응답 대기 중...
          </article>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
