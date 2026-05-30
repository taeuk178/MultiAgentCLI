"""Explicit `/remember` storage helpers.

Long manual notes are split into search_entries chunks, but grouped through
metadata_json so retrieval can treat them like one remembered document.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

from ingestion import redact_text

from . import embedding as emb_mod
from ._common import db_connect, new_id
from .chunking import ChunkConfig, ChunkSpec, split_document
from .entries import cap_retrieval_text, insert_search_entry


REMEMBER_CHUNK_CONFIG = ChunkConfig(
    target_tokens=400,
    max_tokens=800,
    min_tokens=60,
    overlap_ratio=0.0,
)
AUTO_SPLIT_CHARS = 1200
AUTO_SPLIT_LINES = 20
AUTO_SPLIT_HEADINGS = 2
VALID_IMPORTANCE = {"require", "high", "middle", "low"}


@dataclass
class RememberStats:
    group_id: str | None
    title: str
    entries_inserted: int
    ids: list[str]
    split: bool
    embedding_used: bool
    redacted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "title": self.title,
            "entries_inserted": self.entries_inserted,
            "ids": self.ids,
            "split": self.split,
            "embedding_used": self.embedding_used,
            "redacted": self.redacted,
        }


def _heading_count(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s+\S", text or "", flags=re.MULTILINE))


def should_split(text: str, mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return (
        len(text) >= AUTO_SPLIT_CHARS
        or len(text.splitlines()) >= AUTO_SPLIT_LINES
        or _heading_count(text) >= AUTO_SPLIT_HEADINGS
    )


def extract_title(text: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:120]
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if m:
            return m.group(1).strip()[:120]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:60]
    return "remember"


def _single_chunk(text: str) -> list[ChunkSpec]:
    return [ChunkSpec(chunk_index=0, section_path="", chunk_text=text)]


def _preserve_heading(chunk: ChunkSpec) -> None:
    if not chunk.section_path or chunk.chunk_text.lstrip().startswith("#"):
        return
    heading = chunk.section_path.split(" > ")[-1].strip()
    if heading:
        chunk.chunk_text = f"## {heading}\n\n{chunk.chunk_text}"


def _retrieval_text(*, title: str, chunk: ChunkSpec, chunk_count: int) -> str:
    prefix = [f"Remember title: {title}"]
    if chunk_count > 1:
        prefix.append(f"Remember chunk: {chunk.chunk_index + 1}/{chunk_count}")
    if chunk.section_path:
        prefix.append(f"Section: {chunk.section_path}")
    return cap_retrieval_text("\n".join([*prefix, chunk.chunk_text]))


def remember_text(
    *,
    project_id: str,
    text: str,
    raw_type: str = "note",
    importance: str = "middle",
    pinned: int = 0,
    redact: bool = False,
    title: str | None = None,
    split_mode: str = "auto",
) -> RememberStats:
    if importance not in VALID_IMPORTANCE:
        raise ValueError(f"unknown importance: {importance}")
    original = text
    safe_text = redact_text(text)
    was_redacted = redact or safe_text != original
    doc_title = redact_text(extract_title(safe_text, title))
    split = should_split(safe_text, split_mode)
    chunks = list(split_document(safe_text, REMEMBER_CHUNK_CONFIG)) if split else _single_chunk(safe_text)
    if not chunks:
        chunks = _single_chunk(safe_text)
        split = False
    for chunk in chunks:
        _preserve_heading(chunk)

    group_id = new_id() if len(chunks) > 1 else None
    chunk_count = len(chunks)
    retrieval_texts = [_retrieval_text(title=doc_title, chunk=c, chunk_count=chunk_count) for c in chunks]
    embeddings: list[bytes | None] = [None] * chunk_count
    embedding_used = False
    if emb_mod.is_available():
        blobs = emb_mod.embed_texts(retrieval_texts) or []
        if blobs:
            for i, blob in enumerate(blobs[:chunk_count]):
                embeddings[i] = blob
            embedding_used = True

    ids: list[str] = []
    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for idx, chunk in enumerate(chunks):
                metadata: dict[str, Any] = {
                    "importance": importance,
                    "remember_title": doc_title,
                    "split": split,
                    "split_mode": split_mode,
                }
                if was_redacted:
                    metadata["redacted"] = True
                if group_id:
                    metadata.update({
                        "chunk_group_id": group_id,
                        "chunk_group_title": doc_title,
                        "chunk_index": idx,
                        "chunk_count": chunk_count,
                    })
                eid = insert_search_entry(
                    conn,
                    project_id=project_id,
                    origin="manual_remember",
                    raw_type=raw_type,
                    text=chunk.chunk_text,
                    metadata=metadata,
                    chunk_index=idx,
                    section_path=chunk.section_path or None,
                    pinned=pinned,
                    embedding=embeddings[idx],
                    generate_embedding=False,
                    retrieval_text=retrieval_texts[idx],
                )
                ids.append(eid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    return RememberStats(
        group_id=group_id,
        title=doc_title,
        entries_inserted=len(ids),
        ids=ids,
        split=split and len(ids) > 1,
        embedding_used=embedding_used,
        redacted=was_redacted,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="remember", add_help=False)
    parser.add_argument("project_id")
    parser.add_argument("parts", nargs="*")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--title")
    parser.add_argument("--split", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--no-split", action="store_true")
    parser.add_argument("--type", default="note")
    parser.add_argument("--require", action="store_true")
    parser.add_argument("--high", action="store_true")
    parser.add_argument("--middle", action="store_true")
    parser.add_argument("--low", action="store_true")
    parser.add_argument("--pin", action="store_true")
    parser.add_argument("--redact", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = parse_args(argv)
    if ns.stdin:
        text = sys.stdin.read()
    else:
        text = " ".join(ns.parts)
    if not text.strip():
        print("remember requires <text>", file=sys.stderr)
        return 1
    importance = "middle"
    pinned = 0
    if ns.require:
        importance, pinned = "require", 1
    elif ns.high:
        importance, pinned = "high", 1
    elif ns.low:
        importance = "low"
    elif ns.middle:
        importance = "middle"
    if ns.pin:
        pinned = 1
    split_mode = "never" if ns.no_split else ns.split
    stats = remember_text(
        project_id=ns.project_id,
        text=text,
        raw_type=ns.type,
        importance=importance,
        pinned=pinned,
        redact=ns.redact,
        title=ns.title,
        split_mode=split_mode,
    )
    if ns.json:
        print(json.dumps(stats.to_dict(), ensure_ascii=False))
    else:
        target = stats.group_id or (stats.ids[0] if stats.ids else "")
        print(
            f"remembered {target} "
            f"(entries={stats.entries_inserted}, importance={importance}, "
            f"pinned={pinned}, split={str(stats.split).lower()}, redacted={str(stats.redacted).lower()})"
        )
    return 0
