"""shell 에서 호출되는 dispatch 진입점.

usage:
  python3 -m retrieval.cli retrieve <project_id> <query> [top_k]
  python3 -m retrieval.cli ingest <project_id> <project_name> <source_type> <source_ref> [< raw_text]
  python3 -m retrieval.cli drain [project_id]
  python3 -m retrieval.cli supersede <project_id> <new_chunk_text> [section_path]
"""
from __future__ import annotations

import json
import sys

from . import ingest_queue
from .assembly import format_for_claude
from .ingest import ingest_document
from .retrieve import retrieve
from .version import find_supersede_candidates


def cmd_retrieve(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: retrieve <project_id> <query> [top_k]", file=sys.stderr)
        return 2
    project_id = argv[0]
    query = argv[1]
    top_k = int(argv[2]) if len(argv) > 2 else 10
    result = retrieve(query, project_id, top_k=top_k)
    formatted = format_for_claude(project_name=project_id, result=result)
    print(formatted)
    return 0


def cmd_retrieve_json(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: retrieve_json <project_id> <query> [top_k]", file=sys.stderr)
        return 2
    project_id = argv[0]
    query = argv[1]
    top_k = int(argv[2]) if len(argv) > 2 else 10
    result = retrieve(query, project_id, top_k=top_k)
    out = {
        "query": result.query,
        "normalized_query": result.normalized_query,
        "resolved_entities": result.resolved_entities,
        "rerank_used": result.rerank_used,
        "rerank_timeout": result.rerank_timeout,
        "embedding_used": result.embedding_used,
        "candidates": [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "section_path": c.section_path,
                "source_type": c.source_type,
                "source_updated_at": c.source_updated_at,
                "is_current": bool(c.is_current),
                "raw_chunk_type": c.raw_chunk_type,
                "normalized_chunk_type": c.normalized_chunk_type,
                "rrf_score": round(c.rrf_score, 6),
                "boost_score": round(c.boost_score, 6),
                "final_score": round(c.final_score, 6),
                "matched_entities": c.matched_entities,
                "chunk_text": c.chunk_text,
            }
            for c in result.candidates
        ],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_ingest(argv: list[str]) -> int:
    if len(argv) < 4:
        print("usage: ingest <project_id> <project_name> <source_type> <source_ref> [raw_chunk_type]",
              file=sys.stderr)
        return 2
    project_id, project_name, source_type, source_ref = argv[:4]
    raw_chunk_type = argv[4] if len(argv) > 4 else None
    raw_text = sys.stdin.read()
    if not raw_text.strip():
        print("error: raw_text required on stdin", file=sys.stderr)
        return 2
    stats = ingest_document(
        project_id=project_id,
        project_name=project_name,
        source_type=source_type,
        source_ref=source_ref,
        raw_text=raw_text,
        raw_chunk_type=raw_chunk_type,
        # CLI 는 latency budget 밖. context_prefix 기본 ON, embedding 도 가용 시 ON.
        generate_context_prefix=False,
        generate_embedding=True,
    )
    print(json.dumps(stats.__dict__, ensure_ascii=False))
    return 0


def cmd_drain(argv: list[str]) -> int:
    project_id = argv[0] if argv else None

    def _handler(payload: dict) -> None:
        # 현재 단계의 drain handler 는 ingest payload 만 처리.
        # payload = {"kind": "ingest", "args": {...ingest_document kwargs...}}
        kind = payload.get("kind")
        if kind == "ingest":
            ingest_document(**payload["args"])
        else:
            raise ValueError(f"unknown queue payload kind={kind!r}")

    stats = ingest_queue.drain(_handler, project_id=project_id)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


def cmd_supersede(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: supersede <project_id> <new_chunk_text> [section_path]", file=sys.stderr)
        return 2
    project_id = argv[0]
    new_text = argv[1]
    section = argv[2] if len(argv) > 2 else None
    candidates = find_supersede_candidates(project_id, new_text, section_path=section)
    out = [
        {
            "chunk_id": r["id"],
            "section_path": r["section_path"],
            "chunk_text": r["chunk_text"],
            "source_updated_at": r["source_updated_at"],
        }
        for r in candidates
    ]
    print(json.dumps(out, ensure_ascii=False))
    return 0


COMMANDS = {
    "retrieve": cmd_retrieve,
    "retrieve_json": cmd_retrieve_json,
    "ingest": cmd_ingest,
    "drain": cmd_drain,
    "supersede": cmd_supersede,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(f"usage: {sys.argv[0]} <{'|'.join(COMMANDS)}> ...", file=sys.stderr)
        return 2
    cmd = argv[0]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
