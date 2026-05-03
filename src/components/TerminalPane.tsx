import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { onPtyOutput, ptyResize, ptyWrite } from "../lib/ipc";

interface Props {
  tabId: string;
  active: boolean;
}

const TERM_THEME = {
  background: "#0a0a0a",
  foreground: "#e8e8e8",
  cursor: "#e8e8e8",
  cursorAccent: "#0a0a0a",
  selectionBackground: "#4a4a4a55",
  black: "#0a0a0a",
  brightBlack: "#555555",
  red: "#ff5f5f",
  brightRed: "#ff8787",
  green: "#5faf5f",
  brightGreen: "#87d787",
  yellow: "#d7af5f",
  brightYellow: "#ffd787",
  blue: "#5f87d7",
  brightBlue: "#87afff",
  magenta: "#af5fd7",
  brightMagenta: "#d787ff",
  cyan: "#5fafaf",
  brightCyan: "#87d7d7",
  white: "#c8c8c8",
  brightWhite: "#e8e8e8",
};

export function TerminalPane({ tabId, active }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme: TERM_THEME,
      fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, monospace',
      fontSize: 13,
      lineHeight: 1.4,
      cursorStyle: "bar",
      cursorBlink: true,
      allowProposedApi: true,
      scrollback: 5000,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    const unlistenPromise = onPtyOutput(({ tab_id, data }) => {
      if (tab_id === tabId) term.write(data);
    });

    const disposeOnData = term.onData((data) => {
      ptyWrite(tabId, data).catch(console.error);
    });

    const observer = new ResizeObserver(() => {
      fit.fit();
      ptyResize(tabId, term.cols, term.rows).catch(console.error);
    });
    observer.observe(containerRef.current);

    return () => {
      unlistenPromise.then((fn) => fn());
      disposeOnData.dispose();
      observer.disconnect();
      term.dispose();
    };
  }, [tabId]);

  // Re-fit when tab becomes visible
  useEffect(() => {
    if (active && fitRef.current) {
      fitRef.current.fit();
    }
  }, [active]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        padding: "4px",
        display: active ? "block" : "none",
      }}
    />
  );
}
