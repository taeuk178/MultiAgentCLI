"""Codex background runtime for imprint.

The memory/retrieval core is local and deterministic. This module only handles
the small background GPT calls used for prompt analysis, response extraction,
summary generation, NER, and contradiction judging.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from ._common import log, profile_emit


def call_codex(
    prompt: str,
    *,
    timeout: int | float,
    needs_tools: bool = False,
    task: str = "codex",
) -> str | None:
    """Run a background prompt through `codex exec`.

    Codex auth and model selection come from the user's normal Codex CLI
    configuration unless `IMPRINT_CODEX_MODEL` is set.
    """
    bin_path = os.environ.get("IMPRINT_CODEX_BIN") or "codex"
    model = os.environ.get("IMPRINT_CODEX_MODEL") or ""
    cwd = os.environ.get("IMPRINT_CODEX_CWD") or os.getcwd()
    wrapped_prompt = (
        "You are a non-interactive background helper for the imprint memory plugin.\n"
        "Do not run shell commands. Do not edit files. Return only the requested answer.\n\n"
        f"{prompt}"
    )

    t0 = time.monotonic()
    rc: int | None = None
    err: str | None = None
    out = ""
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
        rc = result.returncode
        try:
            out = Path(output_path).read_text(encoding="utf-8")
        except OSError:
            out = result.stdout or ""
        if rc != 0:
            log("WARN", f"codex exec rc={rc}: {result.stderr[:300]}")
            return None
        return out
    except FileNotFoundError:
        err = "FileNotFoundError"
        log("WARN", f"codex CLI not found at {bin_path}")
        return None
    except subprocess.TimeoutExpired:
        err = "TimeoutExpired"
        log("WARN", f"codex exec timeout after {timeout}s")
        return None
    except OSError as exc:
        err = "OSError"
        log("WARN", f"codex exec error: {exc}")
        return None
    finally:
        profile_emit(
            "call_codex",
            task=task,
            timeout=int(float(timeout) * 1000),
            needs_tools=needs_tools,
            rc=rc,
            err=err,
            stdout_bytes=len(out.encode("utf-8")) if out else 0,
            ms=int((time.monotonic() - t0) * 1000),
        )
        if output_path:
            try:
                Path(output_path).unlink()
            except OSError:
                pass
