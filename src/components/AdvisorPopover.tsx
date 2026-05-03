import { useEffect, useRef, useState } from "react";
import { IconCheck, IconChevDown } from "./Icons";
import type { ProviderId } from "../lib/types";
import { PROVIDER_IDS, PROVIDERS } from "../lib/types";

interface Props {
  advisor: ProviderId | null;
  provider: ProviderId;
  disabled?: boolean;
  onChange: (advisor: ProviderId | null) => void;
}

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label="Toggle advisor"
      style={{
        width: 28,
        height: 16,
        borderRadius: 8,
        background: on ? "var(--accent)" : "rgba(255,255,255,0.10)",
        position: "relative",
        cursor: "pointer",
        transition: "background 140ms",
        flexShrink: 0,
        border: "none",
        padding: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: on ? 14 : 2,
          width: 12,
          height: 12,
          borderRadius: "50%",
          background: "white",
          transition: "left 140ms",
        }}
      />
    </button>
  );
}

export function AdvisorPopover({ advisor, provider, disabled, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const on = !!advisor;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggle = () => {
    if (on) onChange(null);
    else onChange(PROVIDER_IDS.find((p) => p !== provider) ?? null);
  };

  const picks = PROVIDER_IDS.filter((p) => p !== provider);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      {/* Trigger button */}
      <button
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          height: 28,
          padding: "0 10px",
          borderRadius: 6,
          border: "1px solid var(--border)",
          background: "var(--bg-card)",
          color: "var(--fg-2)",
          fontSize: 11.5,
          fontWeight: 500,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.45 : 1,
          transition: "background 120ms, border-color 120ms",
          whiteSpace: "nowrap",
        }}
        onMouseEnter={(e) => {
          if (disabled) return;
          (e.currentTarget as HTMLElement).style.background = "var(--bg-card-hi)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.background = "var(--bg-card)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
        }}
      >
        {/* LED */}
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: on ? "var(--accent)" : "var(--fg-faint)",
            boxShadow: on ? "0 0 0 2px rgba(91,141,239,0.22)" : "none",
            flexShrink: 0,
          }}
        />
        <span>Advisor</span>
        {on ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "1px 5px",
              borderRadius: 3,
              fontFamily: "var(--mono)",
              fontSize: 10,
              fontWeight: 700,
              marginLeft: 2,
              background: PROVIDERS[advisor!].bgColor,
              color: PROVIDERS[advisor!].color,
            }}
          >
            {PROVIDERS[advisor!].glyph} {PROVIDERS[advisor!].label}
          </span>
        ) : (
          <span style={{ color: "var(--fg-faint)", fontSize: 11 }}>Off</span>
        )}
        <span style={{ color: "var(--fg-dim)", display: "inline-flex", marginLeft: 2 }}>
          <IconChevDown size={10} />
        </span>
      </button>

      {/* Popover */}
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            width: 280,
            background: "var(--bg-overlay)",
            border: "1px solid var(--border-strong)",
            borderRadius: 9,
            boxShadow:
              "0 12px 32px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.3)",
            padding: 12,
            zIndex: 50,
            display: "flex",
            flexDirection: "column",
            gap: 10,
            animation: "pop-in 140ms ease-out",
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Toggle on={on} onToggle={toggle} />
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--fg)" }}>
                Advisor
              </span>
              <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.5 }}>
                A second model reviews the primary's draft before the final answer.
              </span>
            </div>
          </div>

          {on && (
            <>
              {/* Section label */}
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.4px",
                  textTransform: "uppercase",
                  color: "var(--fg-dim)",
                }}
              >
                Reviewer
              </div>

              {/* Picks */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {picks.map((p) => {
                  const info = PROVIDERS[p];
                  const selected = advisor === p;
                  return (
                    <button
                      key={p}
                      onClick={() => onChange(p)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "8px 10px",
                        borderRadius: 6,
                        border: selected
                          ? "1px solid var(--accent)"
                          : "1px solid var(--border)",
                        background: selected
                          ? "rgba(91,141,239,0.08)"
                          : "var(--bg-card)",
                        color: "var(--fg-2)",
                        fontSize: 12,
                        textAlign: "left",
                        cursor: "pointer",
                        transition: "all 120ms",
                      }}
                      onMouseEnter={(e) => {
                        if (!selected)
                          (e.currentTarget as HTMLElement).style.background =
                            "var(--bg-card-hi)";
                      }}
                      onMouseLeave={(e) => {
                        if (!selected)
                          (e.currentTarget as HTMLElement).style.background =
                            "var(--bg-card)";
                      }}
                    >
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: info.color,
                          flexShrink: 0,
                        }}
                      />
                      <span style={{ flex: 1 }}>{info.label}</span>
                      <span
                        style={{
                          color: "var(--fg-faint)",
                          fontFamily: "var(--mono)",
                          fontSize: 10.5,
                        }}
                      >
                        {(info.ctxWindow / 1000).toFixed(0)}k ctx
                      </span>
                      <span style={{ opacity: selected ? 1 : 0, color: "var(--accent)" }}>
                        <IconCheck size={12} />
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Flow diagram */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "8px 10px",
                  borderRadius: 6,
                  background: "rgba(255,255,255,0.03)",
                  fontFamily: "var(--mono)",
                  fontSize: 10.5,
                  color: "var(--fg-dim)",
                  flexWrap: "wrap",
                }}
              >
                <span
                  style={{
                    padding: "1px 5px",
                    borderRadius: 3,
                    color: PROVIDERS[provider].color,
                  }}
                >
                  {PROVIDERS[provider].glyph} draft
                </span>
                <span style={{ color: "var(--fg-faint)" }}>→</span>
                <span
                  style={{
                    padding: "1px 5px",
                    borderRadius: 3,
                    color: PROVIDERS[advisor!].color,
                  }}
                >
                  {PROVIDERS[advisor!].glyph} review
                </span>
                <span style={{ color: "var(--fg-faint)" }}>→</span>
                <span
                  style={{
                    padding: "1px 5px",
                    borderRadius: 3,
                    color: PROVIDERS[provider].color,
                  }}
                >
                  {PROVIDERS[provider].glyph} synth
                </span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
