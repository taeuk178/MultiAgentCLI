"""Background model runtime for imprint.

The memory/retrieval core is host-neutral. This module is the thin adapter that
chooses the host CLI used for small background model calls.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from ._common import log, profile_emit

DEFAULT_ALLOWED_TOOLS_FETCH = os.environ.get(
    "IMPRINT_ALLOWED_TOOLS_FETCH",
    "mcp__claude_ai_Notion__*,"
    "mcp__notion__*,"
    "mcp__claude_ai_Slack__*,"
    "mcp__slack__*",
)


def current_host() -> str:
    raw = (os.environ.get("IMPRINT_HOST") or "").strip().lower()
    if raw in {"claude", "codex"}:
        return raw
    if os.environ.get("CODEX_PLUGIN_ROOT") or os.environ.get("CODEX_HOME"):
        return "codex"
    if os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("CLAUDE_CONFIG_DIR"):
        return "claude"
    if os.environ.get("PLUGIN_ROOT"):
        return "codex"
    if _has_executable(os.environ.get("IMPRINT_CODEX_BIN") or "codex"):
        return "codex"
    return "claude"


def run_background_model(
    prompt: str,
    *,
    timeout: int | float,
    needs_tools: bool = False,
    task: str = "model",
) -> str | None:
    host = current_host()
    t0 = time.monotonic()
    rc: int | None = None
    err: str | None = None
    out = ""
    try:
        if host == "codex":
            out, rc, err = _call_codex(prompt, timeout=timeout, needs_tools=needs_tools)
        else:
            out, rc, err = _call_claude(prompt, timeout=timeout, needs_tools=needs_tools)
        if rc != 0:
            return None
        return out
    finally:
        profile_emit(
            "run_background_model",
            host=host,
            task=task,
            timeout=int(float(timeout) * 1000),
            needs_tools=needs_tools,
            rc=rc,
            err=err,
            stdout_bytes=len(out.encode("utf-8")) if out else 0,
            ms=int((time.monotonic() - t0) * 1000),
        )


def _has_executable(name: str) -> bool:
    if "/" in name:
        return os.path.exists(name) and os.access(name, os.X_OK)
    path = os.environ.get("PATH", "")
    return any(os.access(os.path.join(p, name), os.X_OK) for p in path.split(os.pathsep) if p)


def _call_claude(prompt: str, *, timeout: int | float, needs_tools: bool) -> tuple[str, int | None, str | None]:
    bin_path = os.environ.get("IMPRINT_CLAUDE_BIN") or "claude"
    model = os.environ.get("IMPRINT_CLAUDE_MODEL") or "haiku"
    cmd = [bin_path, "-p", "--model", model, "--output-format", "text"]
    if needs_tools and DEFAULT_ALLOWED_TOOLS_FETCH:
        cmd.extend(["--allowed-tools", DEFAULT_ALLOWED_TOOLS_FETCH])
    cmd.extend(["--", prompt])

    env = os.environ.copy()
    env["IMPRINT_BYPASS_HOOKS"] = "1"
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log("WARN", f"claude CLI not found at {bin_path}")
        return "", None, "FileNotFoundError"
    except subprocess.TimeoutExpired:
        log("WARN", f"claude -p timeout after {timeout}s")
        return "", None, "TimeoutExpired"
    except OSError as exc:
        log("WARN", f"claude -p exec error: {exc}")
        return "", None, "OSError"

    if result.returncode != 0:
        log("WARN", f"claude -p rc={result.returncode}: {result.stderr[:300]}")
    return result.stdout or "", result.returncode, None


def _call_codex(prompt: str, *, timeout: int | float, needs_tools: bool) -> tuple[str, int | None, str | None]:
    bin_path = os.environ.get("IMPRINT_CODEX_BIN") or "codex"
    model = os.environ.get("IMPRINT_CODEX_MODEL") or ""
    cwd = os.environ.get("IMPRINT_CODEX_CWD") or os.getcwd()
    wrapped_prompt = (
        "You are a non-interactive background helper for the imprint memory plugin.\n"
        "Do not run shell commands. Do not edit files. Return only the requested answer.\n\n"
        f"{prompt}"
    )
    output_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, prefix="imprint-codex-", suffix=".txt") as tmp:
            output_path = tmp.name

        cmd = [
            bin_path,
            "-a",
            "never",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-C",
            cwd,
            "-o",
            output_path,
        ]
        if os.environ.get("IMPRINT_CODEX_IGNORE_RULES", "1") != "0":
            cmd.append("--ignore-rules")
        if model:
            cmd.extend(["-m", model])
        cmd.append("-")

        env = os.environ.copy()
        env["IMPRINT_BYPASS_HOOKS"] = "1"
        if needs_tools:
            log("INFO", "codex call requested tools; Codex MCP availability depends on local config")
        result = subprocess.run(
            cmd,
            input=wrapped_prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        try:
            out = Path(output_path).read_text(encoding="utf-8")
        except OSError:
            out = result.stdout or ""
        if result.returncode != 0:
            log("WARN", f"codex exec rc={result.returncode}: {result.stderr[:300]}")
        return out, result.returncode, None
    except FileNotFoundError:
        log("WARN", f"codex CLI not found at {bin_path}")
        return "", None, "FileNotFoundError"
    except subprocess.TimeoutExpired:
        log("WARN", f"codex exec timeout after {timeout}s")
        return "", None, "TimeoutExpired"
    except OSError as exc:
        log("WARN", f"codex exec error: {exc}")
        return "", None, "OSError"
    finally:
        if output_path:
            try:
                Path(output_path).unlink()
            except OSError:
                pass
