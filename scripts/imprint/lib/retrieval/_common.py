"""DB 연결, 경로, 로깅 등 retrieval 패키지 공통 헬퍼."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMPRINT_HOME = Path(os.environ.get("IMPRINT_HOME") or (Path.home() / ".claude" / "imprint"))
IMPRINT_DB = IMPRINT_HOME / "app.sqlite"
IMPRINT_LOG = IMPRINT_HOME / "plugin.log"
IMPRINT_PROFILE_FILE = IMPRINT_HOME / "profile.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def log(level: str, msg: str) -> None:
    try:
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        with IMPRINT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {level}: {msg}\n")
    except OSError:
        pass


def db_connect() -> sqlite3.Connection:
    IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(IMPRINT_DB), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def now_ms() -> int:
    return int(time.monotonic() * 1000)


# IMPRINT_PROFILE=1 이면 한 줄을 profile.jsonl 에 추가. 기본 OFF.
def profile_emit(stage: str, **kv: Any) -> None:
    if os.environ.get("IMPRINT_PROFILE", "0") != "1":
        return
    try:
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"ts": now_iso(), "pid": os.getpid(), "stage": stage, "kv": kv},
            ensure_ascii=False,
        )
        with IMPRINT_PROFILE_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Span:
    """진입/탈출 wall clock 측정용 컨텍스트 매니저. profile 가 OFF 여도 비용 거의 0."""

    __slots__ = ("stage", "kv", "_start")

    def __init__(self, stage: str, **kv: Any) -> None:
        self.stage = stage
        self.kv = kv
        self._start = 0

    def __enter__(self) -> "Span":
        self._start = now_ms()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed = now_ms() - self._start
        profile_emit(self.stage, ms=elapsed, **self.kv)
