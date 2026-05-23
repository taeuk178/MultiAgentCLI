"""shell 에서 호출되는 dispatch 진입점.

usage:
  python3 -m retrieval.cli retrieve <project_id> <query> [top_k]
  python3 -m retrieval.cli retrieve_json <project_id> <query> [top_k]
  python3 -m retrieval.cli routed <project_id> <query>
  python3 -m retrieval.cli routed_json <project_id> <query>
  python3 -m retrieval.cli ingest <project_id> <project_name> <source_type> <source_ref> [raw_type]
  python3 -m retrieval.cli drain [project_id]
  python3 -m retrieval.cli supersede <project_id> <new_text> [section_path]
  python3 -m retrieval.cli classify <query>
  python3 -m retrieval.cli summarize <project_id> [source_document_id]
  python3 -m retrieval.cli contradiction-scan <project_id>
  python3 -m retrieval.cli migrate-search-entries
  python3 -m retrieval.cli rollup-session <project_id> <session_id> [--all] [--json]
  python3 -m retrieval.cli rollup-latest <project_id> [--all] [--json]
  python3 -m retrieval.cli rollup-stale <project_id> [--exclude-session <id>] [--max-sessions <n>] [--json]
"""
from __future__ import annotations

import json
import sys

from . import contradiction as cd_mod
from . import dispatch as dispatch_mod
from . import ingest_queue
from . import migrate_search_entries
from . import summary as summary_mod
from .assembly import format_for_claude, format_routed_for_claude
from .ingest import ingest_document
from .retrieve import retrieve
from . import rollup as rollup_mod
from .routing import routed_retrieve
from .scope import classify
from .version import find_supersede_candidates
from . import embedding as emb_mod


def _candidate_json(c):
    return {
        "chunk_id": c.chunk_id,
        "entry_id": c.entry_id,
        "document_id": c.document_id,
        "source_document_id": c.source_document_id,
        "section_path": c.section_path,
        "source_type": c.source_type,
        "source_updated_at": c.source_updated_at,
        "is_current": bool(c.is_current),
        "raw_chunk_type": c.raw_chunk_type,
        "raw_type": c.raw_type,
        "normalized_chunk_type": c.normalized_chunk_type,
        "normalized_type": c.normalized_type,
        "rrf_score": round(c.rrf_score, 6),
        "boost_score": round(c.boost_score, 6),
        "final_score": round(c.final_score, 6),
        "matched_entities": c.matched_entities,
        "context_section": c.lane,
        "lane": c.lane,
        "evidence_level": c.evidence_level,
        "grounded": c.grounded,
        "source_uri": c.source_uri,
        "text_hash": c.text_hash,
        "penalties": c.penalties,
        "chunk_text": c.chunk_text,
        "text": c.text,
    }


def _retrieval_trace_json(result):
    return {
        "query_surfaces": result.query_surfaces,
        "fallback_triggered": result.fallback_triggered,
        "fallback_reasons": result.fallback_reasons,
        "low_confidence_reasons": result.low_confidence_reasons,
        "rerank_gate_reason": result.rerank_gate_reason,
    }


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
        "trace": _retrieval_trace_json(result),
        "candidates": [_candidate_json(c) for c in result.candidates],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_ingest(argv: list[str]) -> int:
    if len(argv) < 4:
        print("usage: ingest <project_id> <project_name> <source_type> <source_ref> [raw_type]",
              file=sys.stderr)
        return 2
    project_id, project_name, source_type, source_ref = argv[:4]
    raw_type = argv[4] if len(argv) > 4 else None
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
        raw_chunk_type=raw_type,
        # CLI 는 latency budget 밖. context_prefix 기본 ON, embedding 도 가용 시 ON.
        generate_context_prefix=False,
        generate_embedding=True,
    )
    print(json.dumps(stats.__dict__, ensure_ascii=False))
    return 0


def cmd_drain(argv: list[str]) -> int:
    project_id = argv[0] if argv else None
    stats = ingest_queue.drain(dispatch_mod.handle_payload, project_id=project_id)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


def cmd_routed(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: routed <project_id> <query>", file=sys.stderr)
        return 2
    project_id, query = argv[0], argv[1]
    result = routed_retrieve(query, project_id)
    print(format_routed_for_claude(project_name=project_id, result=result))
    return 0


def cmd_routed_json(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: routed_json <project_id> <query>", file=sys.stderr)
        return 2
    project_id, query = argv[0], argv[1]
    result = routed_retrieve(query, project_id)
    out = {
        "query": result.query,
        "scope": {
            "scope": result.scope.scope,
            "matched_keyword": result.scope.matched_keyword,
            "fallback": result.scope.fallback,
            "reason": result.scope.reason,
        },
        "resolved_entities": result.resolved_entities,
        "summaries": [
            {
                "summary_id": s.summary_id, "level": s.level, "target_key": s.target_key,
                "title": s.title, "summary_text": s.summary_text,
                "is_current": bool(s.is_current), "score": round(s.score, 6),
            } for s in result.search_summaries
        ],
        "chunks": [
            _candidate_json(c) for c in result.chunks
        ],
        "trace": result.trace,
        "ground_chunks": result.ground_chunks,
        "contradictions": result.contradictions,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_classify(argv: list[str]) -> int:
    if not argv:
        print("usage: classify <query>", file=sys.stderr)
        return 2
    d = classify(argv[0])
    print(json.dumps({
        "scope": d.scope, "matched_keyword": d.matched_keyword,
        "fallback": d.fallback, "reason": d.reason,
    }, ensure_ascii=False))
    return 0


def cmd_summarize(argv: list[str]) -> int:
    if not argv:
        print("usage: summarize <project_id> [source_document_id]", file=sys.stderr)
        return 2
    project_id = argv[0]
    if len(argv) > 1:
        stats = summary_mod.regenerate_for_document(project_id, argv[1])
    else:
        sid = summary_mod.regenerate_project(project_id)
        stats = summary_mod.SummaryStats(project_summaries=1 if sid else 0)
    print(json.dumps(stats.__dict__, ensure_ascii=False))
    return 0


def cmd_contradiction_scan(argv: list[str]) -> int:
    if not argv:
        print("usage: contradiction-scan <project_id>", file=sys.stderr)
        return 2
    stats = cd_mod.scan_and_store(argv[0])
    print(json.dumps(stats.__dict__, ensure_ascii=False))
    return 0


def cmd_migrate_search_entries(_argv: list[str]) -> int:
    stats = migrate_search_entries.migrate()
    print(json.dumps(stats, ensure_ascii=False))
    return 0


def cmd_embed_entries(argv: list[str]) -> int:
    if not argv:
        print("usage: embed-entries <project_id> [--all]", file=sys.stderr)
        return 2
    project_id = argv[0]
    include_all = "--all" in argv[1:]
    if not emb_mod.is_available():
        print(json.dumps({"examined": 0, "embedded": 0, "embedding_used": False}, ensure_ascii=False))
        return 1
    from ._common import db_connect

    conn = db_connect()
    try:
        where = "project_id = ?"
        params: list[object] = [project_id]
        if not include_all:
            where += " AND embedding IS NULL"
        rows = conn.execute(
            f"SELECT id, retrieval_text FROM search_entries WHERE {where} AND is_current = 1",
            params,
        ).fetchall()
        texts = [r["retrieval_text"] for r in rows]
        blobs = emb_mod.embed_texts(texts) if texts else []
        for row, blob in zip(rows, blobs or []):
            conn.execute("UPDATE search_entries SET embedding = ? WHERE id = ?", (blob, row["id"]))
        conn.commit()
        print(json.dumps({
            "examined": len(rows),
            "embedded": len(blobs or []),
            "embedding_used": bool(blobs),
        }, ensure_ascii=False))
        return 0
    finally:
        conn.close()


def cmd_extract_entities(argv: list[str]) -> int:
    """청크 → entity mention 추출 + alias 자동 등록 (review queue)."""
    if not argv:
        print("usage: extract-entities <project_id> [source_document_id]", file=sys.stderr)
        return 2
    from . import ner as ner_mod
    project_id = argv[0]
    if len(argv) > 1:
        stats = ner_mod.extract_for_document(project_id, argv[1])
    else:
        # project 전체 — 모든 current document 순회.
        from ._common import db_connect
        conn = db_connect()
        try:
            doc_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM source_documents WHERE project_id = ? AND is_deleted = 0",
                (project_id,),
            ).fetchall()]
        finally:
            conn.close()
        agg = ner_mod.NerStats()
        for did in doc_ids:
            s = ner_mod.extract_for_document(project_id, did)
            agg.chunks_examined += s.chunks_examined
            agg.chunks_skipped += s.chunks_skipped
            agg.mentions_extracted += s.mentions_extracted
            agg.entities_created += s.entities_created
            agg.aliases_added += s.aliases_added
            agg.aliases_auto_confirmed += s.aliases_auto_confirmed
        stats = agg
    promoted = ner_mod.refresh_aliases(project_id)
    out = stats.__dict__ | {"aliases_promoted": promoted}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _print_rollup(data: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
        return
    if "results" in data:
        print(
            f"rollup stale sessions={len(data.get('sessions') or [])} "
            f"entries={data.get('entries_inserted', 0)}"
        )
        for result in data.get("results") or []:
            print(
                f"- {result.get('session_id')}: batches={result.get('batches')} "
                f"events={result.get('events_processed')} entries={result.get('entries_inserted')}"
            )
        return
    print(
        f"rollup session={data.get('session_id')} batches={data.get('batches')} "
        f"events={data.get('events_processed')} entries={data.get('entries_inserted')} "
        f"remaining={data.get('remaining')}"
    )


def cmd_rollup_session(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: rollup-session <project_id> <session_id> [--all] [--json]", file=sys.stderr)
        return 2
    project_id, session_id = argv[:2]
    flags = set(argv[2:])
    unknown = [a for a in argv[2:] if a not in {"--all", "--json"}]
    if unknown:
        print(f"unknown option: {unknown[0]}", file=sys.stderr)
        return 2
    stats = rollup_mod.rollup_session(project_id, session_id, all_batches="--all" in flags)
    _print_rollup(stats.to_dict(), as_json="--json" in flags)
    return 0


def cmd_rollup_latest(argv: list[str]) -> int:
    if not argv:
        print("usage: rollup-latest <project_id> [--all] [--json]", file=sys.stderr)
        return 2
    project_id = argv[0]
    flags = set(argv[1:])
    unknown = [a for a in argv[1:] if a not in {"--all", "--json"}]
    if unknown:
        print(f"unknown option: {unknown[0]}", file=sys.stderr)
        return 2
    session_id = rollup_mod.latest_session(project_id)
    if not session_id:
        data = {"project_id": project_id, "session_id": "", "batches": 0, "events_processed": 0, "entries_inserted": 0}
        _print_rollup(data, as_json="--json" in flags)
        return 0
    stats = rollup_mod.rollup_session(project_id, session_id, all_batches="--all" in flags)
    _print_rollup(stats.to_dict(), as_json="--json" in flags)
    return 0


def cmd_rollup_stale(argv: list[str]) -> int:
    if not argv:
        print("usage: rollup-stale <project_id> [--exclude-session <id>] [--max-sessions <n>] [--all] [--json]", file=sys.stderr)
        return 2
    project_id = argv[0]
    exclude_session = ""
    max_sessions = rollup_mod.DEFAULT_MAX_STALE_SESSIONS
    all_batches = False
    as_json = False
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--exclude-session":
            if i + 1 >= len(argv):
                print("usage: --exclude-session <id>", file=sys.stderr)
                return 2
            exclude_session = argv[i + 1]
            i += 2
        elif arg == "--max-sessions":
            if i + 1 >= len(argv):
                print("usage: --max-sessions <n>", file=sys.stderr)
                return 2
            try:
                max_sessions = int(argv[i + 1])
            except ValueError:
                print("error: --max-sessions must be an integer", file=sys.stderr)
                return 2
            i += 2
        elif arg == "--all":
            all_batches = True
            i += 1
        elif arg == "--json":
            as_json = True
            i += 1
        else:
            print(f"unknown option: {arg}", file=sys.stderr)
            return 2
    data = rollup_mod.rollup_stale(
        project_id,
        exclude_session=exclude_session,
        max_sessions=max_sessions,
        all_batches=all_batches,
    )
    _print_rollup(data, as_json=as_json)
    return 0


def cmd_entities(argv: list[str]) -> int:
    """`/memory entities` 류 review queue UI 의 텍스트 백엔드.

    sub: list-pending | confirm <alias_id> | reject <alias_id>
    """
    if not argv:
        print("usage: entities <list-pending|confirm|reject> [args]", file=sys.stderr)
        return 2
    from .entity import confirm_alias, reject_alias
    from ._common import db_connect

    sub = argv[0]
    if sub == "list-pending":
        if len(argv) < 2:
            print("usage: entities list-pending <project_id>", file=sys.stderr)
            return 2
        project_id = argv[1]
        conn = db_connect()
        try:
            cur = conn.execute(
                """
                SELECT a.id, a.alias, a.confidence, a.created_at,
                       e.canonical_name, e.entity_type, e.display_name
                FROM entity_aliases a
                JOIN entities e ON e.id = a.entity_id
                WHERE e.project_id = ? AND a.status = 'pending'
                ORDER BY a.created_at DESC
                """,
                (project_id,),
            )
            rows = [{
                "alias_id": r["id"], "alias": r["alias"], "confidence": r["confidence"],
                "canonical_name": r["canonical_name"], "entity_type": r["entity_type"],
                "display_name": r["display_name"], "created_at": r["created_at"],
            } for r in cur.fetchall()]
        finally:
            conn.close()
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    if sub == "confirm":
        if len(argv) < 2:
            print("usage: entities confirm <alias_id>", file=sys.stderr)
            return 2
        confirm_alias(argv[1])
        print(json.dumps({"alias_id": argv[1], "status": "confirmed"}))
        return 0
    if sub == "reject":
        if len(argv) < 2:
            print("usage: entities reject <alias_id>", file=sys.stderr)
            return 2
        reject_alias(argv[1])
        print(json.dumps({"alias_id": argv[1], "status": "rejected"}))
        return 0
    print(f"unknown sub: {sub}", file=sys.stderr)
    return 2


def cmd_supersede(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: supersede <project_id> <new_text> [section_path]", file=sys.stderr)
        return 2
    project_id = argv[0]
    new_text = argv[1]
    section = argv[2] if len(argv) > 2 else None
    candidates = find_supersede_candidates(project_id, new_text, section_path=section)
    out = [
        {
            "entry_id": r["id"],
            "section_path": r["section_path"],
            "text": r["text"],
            "source_updated_at": r["source_updated_at"],
        }
        for r in candidates
    ]
    print(json.dumps(out, ensure_ascii=False))
    return 0


COMMANDS = {
    "retrieve": cmd_retrieve,
    "retrieve_json": cmd_retrieve_json,
    "routed": cmd_routed,
    "routed_json": cmd_routed_json,
    "ingest": cmd_ingest,
    "drain": cmd_drain,
    "supersede": cmd_supersede,
    "classify": cmd_classify,
    "summarize": cmd_summarize,
    "contradiction-scan": cmd_contradiction_scan,
    "migrate-search-entries": cmd_migrate_search_entries,
    "embed-entries": cmd_embed_entries,
    "extract-entities": cmd_extract_entities,
    "rollup-session": cmd_rollup_session,
    "rollup-latest": cmd_rollup_latest,
    "rollup-stale": cmd_rollup_stale,
    "entities": cmd_entities,
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
