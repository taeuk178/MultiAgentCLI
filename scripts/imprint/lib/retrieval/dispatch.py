"""W1 commit dispatcher — single-writer commit 직후 변경 분석 → J5 / J6 enqueue.

핵심: 매 commit 마다 모든 summary 를 재생성하지 않는다. 변경된 entity / feature /
decision 이 있을 때만 incremental update job 을 큐에 넣는다.

호출 흐름:
  ingest_document(...) 또는 manual search_entries 변경 직후
  → dispatch_commit(project_id, changed_source_documents=..., decision_chunk_inserted=...)
  → ingest_queue 에 J5/J6 enqueue (priority 5)

drain_jobs(...) 가 큐를 처리할 때 payload.kind 별 핸들러로 라우팅.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import contradiction as cd_mod
from . import ingest_queue as queue_mod
from . import summary as summary_mod
from ._common import log


@dataclass
class CommitChangeSet:
    project_id: str
    changed_source_document_ids: list[str]      # source_documents INSERT 또는 UPDATE
    decision_chunk_inserted: bool        # normalized_type='decision' 새 row
    entity_link_changed: bool            # entry_entities 변화 (alias merge / split)
    supersede_changed: bool              # supersedes_entry_id 또는 is_current flip
    new_chunk_inserted: bool = False     # NER 트리거 — 새 chunk 가 INSERT 됐을 때


def dispatch_commit(change: CommitChangeSet) -> dict[str, list[str]]:
    """변경에 따라 J5/J6 enqueue. 큐에 넣은 job id 들을 반환.

    feature summary regen 이 필요한지는 dispatcher 가 conservatively 판단:
    - changed_source_document_ids 가 있으면 → J5 (해당 document 들 + project)
    - entity_link_changed 가 true → J5 (영향 범위 추정 어려워 project 전체 재생성)
    - decision_chunk_inserted 또는 supersede_changed → J6
    """
    summary_jobs: list[str] = []
    contradiction_jobs: list[str] = []

    if change.changed_source_document_ids:
        for doc_id in change.changed_source_document_ids:
            qid = queue_mod.enqueue(
                change.project_id,
                {"kind": "summary_regen", "level": "document",
                 "source_document_id": doc_id, "project_id": change.project_id},
                priority=queue_mod.PRIORITY_J5_SUMMARY,
            )
            summary_jobs.append(qid)
    if change.entity_link_changed:
        qid = queue_mod.enqueue(
            change.project_id,
            {"kind": "summary_regen", "level": "project", "project_id": change.project_id},
            priority=queue_mod.PRIORITY_J5_SUMMARY,
        )
        summary_jobs.append(qid)
    if change.decision_chunk_inserted or change.supersede_changed:
        qid = queue_mod.enqueue(
            change.project_id,
            {"kind": "contradiction_scan", "project_id": change.project_id},
            priority=queue_mod.PRIORITY_J6_CONTRADICTION,
        )
        contradiction_jobs.append(qid)

    ner_jobs: list[str] = []
    if change.new_chunk_inserted and change.changed_source_document_ids:
        for doc_id in change.changed_source_document_ids:
            qid = queue_mod.enqueue(
                change.project_id,
                {"kind": "ner_extract", "project_id": change.project_id, "source_document_id": doc_id},
                priority=queue_mod.PRIORITY_J4_ENTITY,
            )
            ner_jobs.append(qid)

    if not summary_jobs and not contradiction_jobs and not ner_jobs:
        log("INFO", f"dispatch_commit: no jobs for project={change.project_id}")
    return {"summary": summary_jobs, "contradiction": contradiction_jobs, "ner": ner_jobs}


def handle_payload(payload: dict[str, Any]) -> None:
    """drain handler 가 호출. payload.kind 별 라우팅."""
    kind = payload.get("kind")
    if kind == "ingest":
        # Phase 7a 의 ingest payload — ingest 모듈로 위임.
        from .ingest import ingest_document
        ingest_document(**payload["args"])
        return
    if kind == "summary_regen":
        level = payload.get("level", "project")
        if level == "document":
            doc_id = payload["source_document_id"]
            project_id = payload.get("project_id")
            if project_id is None:
                # payload 에 project_id 가 누락된 경우 source_documents 에서 lookup.
                from ._common import db_connect
                conn = db_connect()
                try:
                    row = conn.execute(
                        "SELECT project_id FROM source_documents WHERE id = ?", (doc_id,)
                    ).fetchone()
                    project_id = row["project_id"] if row else None
                finally:
                    conn.close()
            if not project_id:
                raise ValueError(f"summary_regen: cannot resolve project_id for document={doc_id}")
            summary_mod.regenerate_for_document(project_id, doc_id)
            return
        if level == "project":
            project_id = payload.get("project_id")
            if not project_id:
                raise ValueError("summary_regen project: project_id required")
            summary_mod.regenerate_project(project_id)
            return
        raise ValueError(f"summary_regen unknown level: {level!r}")
    if kind == "contradiction_scan":
        project_id = payload.get("project_id")
        if not project_id:
            raise ValueError("contradiction_scan: project_id required")
        cd_mod.scan_and_store(project_id)
        return
    if kind == "ner_extract":
        from . import ner as ner_mod
        project_id = payload.get("project_id")
        source_document_id = payload.get("source_document_id")
        if not project_id or not source_document_id:
            raise ValueError("ner_extract: project_id and source_document_id required")
        ner_mod.extract_for_document(project_id, source_document_id)
        ner_mod.refresh_aliases(project_id)
        return
    raise ValueError(f"unknown queue payload kind={kind!r}")
