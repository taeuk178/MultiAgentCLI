import { IconPlus, IconX } from "./Icons";
import type { ConversationEntry, ProviderId } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  conversations: ConversationEntry[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}

function ProviderDot({ providerId }: { providerId: ProviderId }) {
  return (
    <span
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: PROVIDERS[providerId].color,
        flexShrink: 0,
        display: "inline-block",
      }}
    />
  );
}

export function Sidebar({ conversations, activeId, onSelect, onDelete, onNew }: Props) {
  return (
    <aside
      style={{
        width: 240,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bg-sidebar)",
        borderRight: "1px solid var(--divider)",
      }}
    >
      {/* Traffic light region — native controls appear here */}
      <div
        style={{ height: 44, flexShrink: 0 }}
        {...{ "data-tauri-drag-region": true }}
      />

      {/* Section header */}
      <div
        style={{
          padding: "8px 12px 4px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: "0.5px",
          textTransform: "uppercase",
          color: "var(--fg-dim)",
        }}
      >
        <span>Conversations</span>
        <span
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10.5,
            fontWeight: 500,
            color: "var(--fg-faint)",
            letterSpacing: 0,
          }}
        >
          {conversations.length}
        </span>
      </div>

      {/* Conversation list */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0 6px 6px",
          display: "flex",
          flexDirection: "column",
          gap: 1,
        }}
      >
        {conversations.map((conv) => {
          const isActive = conv.id === activeId;
          return (
            <div
              key={conv.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(conv.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(conv.id)}
              style={{
                position: "relative",
                display: "flex",
                flexDirection: "column",
                gap: 3,
                padding: "7px 10px 8px",
                borderRadius: 6,
                cursor: "pointer",
                background: isActive ? "var(--bg-row-active)" : "transparent",
                transition: "background 100ms",
              }}
              onMouseEnter={(e) => {
                if (!isActive)
                  (e.currentTarget as HTMLElement).style.background =
                    "var(--bg-row-hover)";
                const btn = e.currentTarget.querySelector<HTMLElement>(".delete-x");
                if (btn) btn.style.display = "flex";
              }}
              onMouseLeave={(e) => {
                if (!isActive)
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                const btn = e.currentTarget.querySelector<HTMLElement>(".delete-x");
                if (btn) btn.style.display = "none";
              }}
            >
              {/* Title row */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 12.5,
                  fontWeight: 500,
                  color: "var(--fg)",
                  overflow: "hidden",
                }}
              >
                <ProviderDot providerId={conv.provider} />
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flex: 1,
                  }}
                >
                  {conv.title || "Untitled"}
                </span>
              </div>

              {/* Meta row */}
              <div
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: 10.5,
                  color: "var(--fg-dim)",
                  display: "flex",
                  gap: 4,
                  alignItems: "center",
                  overflow: "hidden",
                }}
              >
                <span>{PROVIDERS[conv.provider].label}</span>
                <span style={{ color: "var(--fg-faint)" }}>·</span>
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {conv.project ? conv.project.split("/").pop() : "no project"}
                </span>
              </div>

              {/* Delete button */}
              <button
                className="delete-x"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(conv.id);
                }}
                title="Delete"
                style={{
                  position: "absolute",
                  right: 8,
                  top: "50%",
                  transform: "translateY(-50%)",
                  width: 18,
                  height: 18,
                  borderRadius: 4,
                  display: "none",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--fg-dim)",
                  background: "transparent",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.background =
                    "rgba(255,255,255,0.08)";
                  (e.currentTarget as HTMLElement).style.color = "var(--fg)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                  (e.currentTarget as HTMLElement).style.color = "var(--fg-dim)";
                }}
              >
                <IconX size={11} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: 10,
          borderTop: "1px solid var(--divider)",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <button
          onClick={onNew}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            width: "100%",
            height: 28,
            padding: "0 12px",
            borderRadius: 6,
            background: "var(--accent)",
            color: "white",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.15) inset, 0 1px 2px rgba(0,0,0,0.3)",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLElement).style.background = "#6f9cf2")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLElement).style.background = "var(--accent)")
          }
        >
          <IconPlus size={13} />
          <span>New Chat</span>
        </button>
      </div>
    </aside>
  );
}
