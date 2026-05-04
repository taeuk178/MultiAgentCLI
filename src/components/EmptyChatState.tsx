import { Keycap } from "./ui";

export function EmptyChatState() {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 14,
        color: "var(--fg-dim)",
        userSelect: "none",
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--mono)",
          fontSize: 22,
          fontWeight: 700,
          background: "var(--p-claude-bg)",
          color: "var(--p-claude)",
          border: "1px solid var(--p-claude)",
        }}
      >
        C
      </div>
      <div style={{ textAlign: "center" }}>
        <div
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: "var(--fg)",
            marginBottom: 6,
          }}
        >
          New Chat를 눌러 시작하세요
        </div>
        <div style={{ fontSize: 12, color: "var(--fg-dim)" }}>
          사이드바의 New Chat 버튼으로 대화를 만드세요.
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <Keycap>⌘</Keycap>
        <Keycap>↵</Keycap>
        <span
          style={{
            alignSelf: "center",
            fontSize: 11,
            color: "var(--fg-dim)",
          }}
        >
          send
        </span>
        <span style={{ alignSelf: "center", color: "var(--fg-faint)" }}>·</span>
        <span
          style={{
            alignSelf: "center",
            fontSize: 11,
            color: "var(--fg-dim)",
          }}
        >
          esc stop
        </span>
      </div>
    </div>
  );
}
