import { useEffect, useRef, useState } from "react";
import { IconPlus, IconX } from "./Icons";
import { ProviderDot } from "./ui";
import type { ConversationEntry } from "../lib/types";
import { PROVIDERS } from "../lib/types";

interface Props {
  conversations: ConversationEntry[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
  onClearChat: (id: string) => void;
}

interface CtxMenu {
  id: string;
  x: number;
  y: number;
}

function ContextMenu({
  menu,
  onClearChat,
  onDelete,
  onClose,
}: {
  menu: CtxMenu;
  onClearChat: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const menuItem = (label: string, onClick: () => void, danger = false) => (
    <button
      className={danger ? "context-menu-item is-danger" : "context-menu-item"}
      onClick={() => {
        onClick();
        onClose();
      }}
      style={{
        display: "flex",
        alignItems: "center",
        width: "100%",
        padding: "6px 10px",
        borderRadius: 4,
        background: "transparent",
        color: danger ? "var(--danger)" : "var(--fg-2)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "var(--ui)",
        transition: "background 80ms",
        border: "none",
      }}
    >
      {label}
    </button>
  );

  return (
    <div
      ref={ref}
      style={{
        position: "fixed",
        left: menu.x,
        top: menu.y,
        zIndex: 200,
        background: "var(--bg-overlay)",
        border: "1px solid var(--border-strong)",
        borderRadius: 6,
        boxShadow: "0 8px 24px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.3)",
        padding: 4,
        minWidth: 160,
        animation: "pop-in 120ms ease-out",
      }}
    >
      {menuItem("Clear Chat", onClearChat)}
      <div style={{ height: 1, background: "var(--divider)", margin: "3px 0" }} />
      {menuItem("Delete", onDelete, true)}
    </div>
  );
}

export function Sidebar({
  conversations,
  activeId,
  onSelect,
  onDelete,
  onNew,
  onClearChat,
}: Props) {
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);

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
        position: "relative",
      }}
    >
      {/* Traffic light region */}
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
              className={isActive ? "conversation-row is-active" : "conversation-row"}
              key={conv.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(conv.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(conv.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                setCtxMenu({ id: conv.id, x: e.clientX, y: e.clientY });
              }}
              style={{
                position: "relative",
                display: "flex",
                flexDirection: "column",
                gap: 3,
                padding: "7px 10px 8px",
                borderRadius: 6,
                cursor: "pointer",
                transition: "background 100ms",
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
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--fg-dim)",
                  background: "transparent",
                  cursor: "pointer",
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
          className="primary-button"
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
        >
          <IconPlus size={13} />
          <span>New Chat</span>
        </button>
      </div>

      {/* Context menu */}
      {ctxMenu && (
        <ContextMenu
          menu={ctxMenu}
          onClearChat={() => onClearChat(ctxMenu.id)}
          onDelete={() => onDelete(ctxMenu.id)}
          onClose={() => setCtxMenu(null)}
        />
      )}
    </aside>
  );
}
