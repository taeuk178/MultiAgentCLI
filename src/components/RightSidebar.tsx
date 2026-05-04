export type SidebarPanelMode = "local" | "remote";

interface Props {
  mode: SidebarPanelMode;
  onModeChange: (mode: SidebarPanelMode) => void;
}

export function RightSidebar({ mode, onModeChange }: Props) {
  const isLocal = mode === "local";

  return (
    <aside
      style={{
        width: 280,
        height: "100%",
        flexShrink: 0,
        borderLeft: "1px solid var(--divider)",
        background: isLocal ? "#2b2b2e" : "#050505",
        color: "var(--fg)",
        display: "flex",
        flexDirection: "column",
        transition: "background 160ms",
      }}
    >
      <div
        style={{
          height: 44,
          display: "flex",
          alignItems: "center",
          padding: "0 12px",
          borderBottom: "1px solid var(--divider)",
          gap: 6,
        }}
      >
        {(["local", "remote"] as const).map((tab) => {
          const active = mode === tab;

          return (
            <button
              key={tab}
              onClick={() => onModeChange(tab)}
              style={{
                height: 26,
                padding: "0 11px",
                borderRadius: 6,
                border: active
                  ? "1px solid var(--border-strong)"
                  : "1px solid transparent",
                background: active
                  ? "rgba(255,255,255,0.10)"
                  : "rgba(255,255,255,0.03)",
                color: active ? "var(--fg)" : "var(--fg-dim)",
                fontSize: 11.5,
                fontWeight: active ? 700 : 500,
                fontFamily: "var(--ui)",
                cursor: "pointer",
                textTransform: "capitalize",
              }}
            >
              {tab}
            </button>
          );
        })}
      </div>

      <div
        style={{
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          color: "var(--fg-dim)",
          fontSize: 12,
          lineHeight: 1.45,
        }}
      >
        <div
          style={{
            color: "var(--fg)",
            fontSize: 13,
            fontWeight: 700,
          }}
        >
          {isLocal ? "Local" : "Remote"}
        </div>
        <div>
          {isLocal
            ? "로컬 세션과 연결된 항목을 표시할 영역입니다."
            : "원격 세션과 연결된 항목을 표시할 영역입니다."}
        </div>
      </div>
    </aside>
  );
}
