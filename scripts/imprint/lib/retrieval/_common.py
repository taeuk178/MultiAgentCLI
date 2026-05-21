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

# Shared runtime paths for retrieval modules.
# IMPRINT_HOME lets tests and users isolate app.sqlite/plugin.log/profile.jsonl.
IMPRINT_HOME = Path(os.environ.get("IMPRINT_HOME") or (Path.home() / ".imprint"))
IMPRINT_DB = IMPRINT_HOME / "app.sqlite"
IMPRINT_LOG = IMPRINT_HOME / "plugin.log"
IMPRINT_PROFILE_FILE = IMPRINT_HOME / "profile.jsonl"
LEGACY_CLAUDE_DB = Path.home() / ".claude" / "imprint" / "app.sqlite"
DATA_TABLES = (
    "events",
    "memory_chunks",
    "documents",
    "chunks_v2",
    "summaries",
    "entities",
    "entity_aliases",
    "contradictions",
    "source_status",
)


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


def _has_user_data(db_path: Path) -> bool:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        for table in DATA_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count > 0:
                return True
        return False
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _remove_legacy_files(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{db_path}{suffix}").unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log("WARN", f"legacy claude db cleanup skipped path={db_path}{suffix} err={exc!r}")


def migrate_legacy_claude_db_if_needed() -> None:
    if os.environ.get("IMPRINT_DISABLE_LEGACY_MIGRATION") == "1":
        return
    if IMPRINT_HOME != Path.home() / ".imprint":
        return
    if not LEGACY_CLAUDE_DB.exists():
        return
    try:
        if _has_user_data(IMPRINT_DB) or not _has_user_data(LEGACY_CLAUDE_DB):
            return
        IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{LEGACY_CLAUDE_DB}?mode=ro", uri=True)
        dst = sqlite3.connect(str(IMPRINT_DB))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        if _has_user_data(IMPRINT_DB):
            _remove_legacy_files(LEGACY_CLAUDE_DB)
            log("INFO", f"legacy claude db migrated old={LEGACY_CLAUDE_DB} new={IMPRINT_DB} cleanup=removed")
    except sqlite3.Error as exc:
        log("WARN", f"legacy claude db migration skipped: {exc!r}")


_VEC_LOAD_FAILED = False


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """sqlite-vec extension 로드. 가용하면 retrieve 가 vec0 virtual table 사용 가능.

    미설치 시 retrieve 가 Python cosine fallback. extension 로딩이 OS/SQLite 빌드별로
    실패할 수 있어 한 번 실패한 프로세스에서는 다시 시도하지 않음 (전역 플래그).
    """
    global _VEC_LOAD_FAILED
    if _VEC_LOAD_FAILED or os.environ.get("IMPRINT_DISABLE_SQLITE_VEC") == "1":
        return False
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:
        _VEC_LOAD_FAILED = True
        log("WARN", f"sqlite-vec load failed: {exc!r} — using Python cosine fallback")
        return False


def db_connect(*, load_vec: bool = False) -> sqlite3.Connection:
    IMPRINT_HOME.mkdir(parents=True, exist_ok=True)
    migrate_legacy_claude_db_if_needed()
    conn = sqlite3.connect(str(IMPRINT_DB), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        has_chunks_v2 = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_v2'"
        ).fetchone()
        if has_chunks_v2:
            has_metadata = conn.execute(
                "SELECT COUNT(*) FROM pragma_table_info('chunks_v2') WHERE name = 'metadata_json'"
            ).fetchone()[0]
            if not has_metadata:
                conn.execute("ALTER TABLE chunks_v2 ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
    except sqlite3.Error as exc:
        log("WARN", f"light schema migration skipped: {exc!r}")
    if load_vec:
        _try_load_sqlite_vec(conn)
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
