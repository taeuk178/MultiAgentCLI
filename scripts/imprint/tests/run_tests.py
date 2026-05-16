"""imprint 보편 사용 시나리오 10개의 자동 테스트 러너.

`TestCase.md` 의 케이스 정의를 그대로 실행하고 케이스별 ms / pass-fail / counts 를
출력. 임시 IMPRINT_HOME 에서 동작 (사용자 DB 무영향).

사용:
  python3 scripts/imprint/tests/run_tests.py

종료 코드: 모든 케이스 PASS = 0, 하나라도 FAIL = 1.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import json
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # imprint repo root
LIB_DIR = ROOT / "scripts" / "imprint" / "lib"
SCHEMA_PATH = LIB_DIR / "schema.sql"

PROJECT_ID = "p_test"
ROOT_PROJECT_ID = hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:16]


@dataclass
class CaseResult:
    name: str
    label: str
    ms: int = 0
    passed: bool = False
    detail: str = ""
    metrics: dict = field(default_factory=dict)


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


@contextmanager
def stage(label: str, results: list[CaseResult]):
    case = CaseResult(name=label.split()[0], label=label)
    t0 = _now_ms()
    try:
        yield case
    finally:
        case.ms = _now_ms() - t0
        results.append(case)


def setup_env() -> tuple[str, dict]:
    home = tempfile.mkdtemp(prefix="imprint-test-")
    env = os.environ.copy()
    env["IMPRINT_HOME"] = home
    env["IMPRINT_DISABLE_EMBEDDING"] = "1"
    env["IMPRINT_DISABLE_RERANK"] = "1"
    env["IMPRINT_DISABLE_NLI"] = "1"
    env["IMPRINT_DISABLE_SUMMARY_LLM"] = "1"
    env["IMPRINT_DISABLE_NER_LLM"] = "1"
    # LLM judge 는 TC-08 에서만 활성화
    env["IMPRINT_DISABLE_LLM_JUDGE"] = "1"
    env["IMPRINT_BYPASS_HOOKS"] = "1"  # claude -p 호출 시 hook 무한재귀 방지

    db_path = Path(home) / "app.sqlite"
    schema_sql = SCHEMA_PATH.read_text()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    conn.execute(
        "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
        (PROJECT_ID, "/test", "demo", "2026-05-10", "2026-05-10"),
    )
    conn.commit()
    conn.close()
    return home, env


def setup_pythonpath(env: dict) -> dict:
    env = dict(env)
    env["PYTHONPATH"] = str(LIB_DIR) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def run_python(env: dict, code: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def run_cmd(env: dict, args: list[str], *, input_text: str = "") -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        input=input_text,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def db_query(home: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        cur = conn.execute(sql, params)
        return list(cur.fetchall())
    finally:
        conn.close()


def hook_env(env: dict) -> dict:
    out = dict(env)
    out.pop("IMPRINT_BYPASS_HOOKS", None)
    out["IMPRINT_NO_SEED"] = "1"
    out["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    return out


def make_fake_claude(home: str) -> str:
    path = Path(home) / "fake-claude"
    raw_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    path.write_text(
        f"""#!/bin/sh
joined="$*"
case "$joined" in
  *"Extract durable knowledge chunks"*)
    printf '%s\\n' '[{{"chunk_type":"decision","text":"A 버튼 클릭은 {raw_token} 없이 테스트 모드를 시작합니다.","keywords":["A 버튼","{raw_token}"]}}]'
    ;;
  *"Return STRICT JSON with EXACTLY these keys"*)
    printf '%s\\n' '{{"ambiguity_score":0.1,"keywords":["A 버튼","클릭","button click"],"refined_prompt":null}}'
    ;;
  *)
    printf '%s\\n' '[]'
    ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


# -----------------------------------------------------------------------------
# 케이스 구현
# -----------------------------------------------------------------------------

def tc_01_save_short(env: dict, home: str, case: CaseResult) -> None:
    code = """
import sys; sys.path.insert(0, %r)
from retrieval.ingest import ingest_document
stats = ingest_document(
    project_id='p_test', project_name='demo',
    source_type='notion', source_ref='tc01',
    raw_text='A 화면 우상단의 test 버튼을 클릭하면 테스트 모드로 진입한다.',
    raw_chunk_type='spec',
    generate_context_prefix=False, generate_embedding=False,
    dispatch=False,
)
print(stats.chunks_inserted)
""" % (str(LIB_DIR),)
    rc, out, err = run_python(env, code)
    chunks = int(out) if out else 0
    docs = db_query(home, "SELECT count(*) FROM documents WHERE source_ref='tc01'")[0][0]
    case.metrics = {"chunks": chunks, "documents": docs, "rc": rc}
    case.passed = rc == 0 and chunks == 1 and docs == 1
    case.detail = f"chunks={chunks} documents={docs}"
    if not case.passed and err:
        case.detail += f" err={err[:200]}"


def tc_02_save_long(env: dict, home: str, case: CaseResult) -> None:
    long_doc = """
# 결제 모듈 PRD

## 테스트모드 진입

A 화면 우상단의 test 버튼을 클릭하면 테스트 모드로 진입한다. 5월 변경으로 즉시 진입이 아니라 확인 모달을 먼저 거치도록 바뀌었다. 사용자 실수 방지가 목적이다. 모달은 두 개의 버튼을 제공한다 — 진입 확인과 취소. 취소 시 메인 화면으로 복귀한다.

## 디버그 토글

같은 UI 요소를 디버그 토글로 부르기도 한다. 슬랙 공지 이후 문구를 통일하기로 했다. 다만 코드상 식별자는 test_button 으로 유지한다. 마이그레이션 비용 때문이다.

## QA 절차

QA 절차는 별도 문서를 따른다. 자동화 스크립트는 nightly 로 회귀 검증한다. 실패 시 슬랙 #ios-payment 채널로 알림이 간다. 알림 포맷은 별도 정의되어 있다.
""".strip()
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.ingest import ingest_document\n"
            "stats = ingest_document(project_id='p_test', project_name='demo',\n"
            "  source_type='notion', source_ref='tc02', raw_text=%r,\n"
            "  raw_chunk_type='spec', generate_context_prefix=False,\n"
            "  generate_embedding=False, dispatch=False)\n"
            "print(stats.chunks_inserted)") % (str(LIB_DIR), long_doc)
    rc, out, err = run_python(env, code)
    chunks = int(out) if out else 0
    sections = db_query(
        home,
        "SELECT count(DISTINCT section_path) FROM chunks_v2 WHERE document_id IN (SELECT id FROM documents WHERE source_ref='tc02')",
    )[0][0]
    case.metrics = {"chunks": chunks, "sections": sections}
    case.passed = chunks >= 3 and sections >= 3
    case.detail = f"chunks={chunks} sections={sections}"


def _retrieve_json(env: dict, query: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "retrieval.cli", "routed_json", PROJECT_ID, query],
        env=env, capture_output=True, text=True, cwd=str(LIB_DIR),
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()}
    import json
    return json.loads(proc.stdout)


def _retrieve_plain_json(env: dict, query: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "retrieval.cli", "retrieve_json", PROJECT_ID, query],
        env=env, capture_output=True, text=True, cwd=str(LIB_DIR),
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()}
    import json
    return json.loads(proc.stdout)


def tc_03_retrieve_short(env: dict, home: str, case: CaseResult) -> None:
    out = _retrieve_json(env, "A 버튼 클릭 동작 알려줘")
    scope = (out.get("scope") or {}).get("scope")
    candidates = len(out.get("chunks") or [])
    summaries = len(out.get("summaries") or [])
    case.metrics = {"scope": scope, "chunks": candidates, "summaries": summaries}
    case.passed = scope == "local" and candidates >= 1
    case.detail = f"scope={scope} chunks={candidates} summaries={summaries}"


def tc_04_retrieve_feature(env: dict, home: str, case: CaseResult) -> None:
    # feature 분류를 위해 summary 필요 — TC-02 가 이미 chunk 들 만들었으니 summary 생성 강제.
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.summary import regenerate_for_document\n"
            "from retrieval._common import db_connect\n"
            "conn = db_connect()\n"
            "rows = conn.execute(\"SELECT id FROM documents WHERE project_id='p_test'\").fetchall()\n"
            "conn.close()\n"
            "for r in rows:\n"
            "    regenerate_for_document('p_test', r[0], use_llm=False, propagate_project=True)\n"
            "print('OK')") % (str(LIB_DIR),)
    rc, _, _ = run_python(env, code)
    out = _retrieve_json(env, "테스트 모드 진입 UX 시나리오 흐름 설명")
    scope = (out.get("scope") or {}).get("scope")
    summaries = len(out.get("summaries") or [])
    chunks = len(out.get("chunks") or [])
    case.metrics = {"scope": scope, "summaries": summaries, "chunks": chunks}
    case.passed = scope == "feature" and summaries >= 1 and chunks >= 1
    case.detail = f"scope={scope} summaries={summaries} chunks={chunks}"


def tc_05_retrieve_global(env: dict, home: str, case: CaseResult) -> None:
    out = _retrieve_json(env, "이 프로젝트의 테스트 관련 정책 전체 정리해줘")
    scope = (out.get("scope") or {}).get("scope")
    summaries = out.get("summaries") or []
    levels = sorted({s.get("level") for s in summaries})
    case.metrics = {"scope": scope, "summary_levels": levels, "summaries": len(summaries)}
    case.passed = scope == "global" and len(levels) >= 2
    case.detail = f"scope={scope} levels={levels}"


def tc_06_entity_alias(env: dict, home: str, case: CaseResult) -> None:
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.entity import upsert_entity, add_alias, confirm_alias\n"
            "eid = upsert_entity('p_test', 'ui_element', 'test_button', 'Test 버튼')\n"
            "for a in ['test 버튼', '디버그 토글']:\n"
            "    aid = add_alias(eid, a, confidence=0.95)\n"
            "    confirm_alias(aid)\n"
            "print(eid)") % (str(LIB_DIR),)
    rc, _, _ = run_python(env, code)
    out = _retrieve_json(env, "디버그 토글 누르면 어떻게 돼?")
    resolved = out.get("resolved_entities") or []
    matched_total = sum(len(c.get("matched_entities") or []) for c in (out.get("chunks") or []))
    case.metrics = {"resolved": len(resolved), "matched_entities": matched_total}
    case.passed = len(resolved) >= 1 and matched_total >= 1
    case.detail = f"resolved={[h.get('canonical_name') for h in resolved]} matched_total={matched_total}"


def tc_07_supersede(env: dict, home: str, case: CaseResult) -> None:
    initial = """
# 모듈 X

## A
A 슬롯 본문 v1 입니다.

## B
B 슬롯 본문 v1 입니다.

## C
C 슬롯 본문 v1 입니다.
""".strip()
    updated = """
# 모듈 X

## A
A 슬롯 본문 v2 (변경됨) 입니다.

## C
C 슬롯 본문 v2 (변경됨) 입니다.
""".strip()
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.ingest import ingest_document\n"
            "for txt in [%r, %r]:\n"
            "    s = ingest_document(project_id='p_test', project_name='demo',\n"
            "      source_type='notion', source_ref='tc07', raw_text=txt,\n"
            "      raw_chunk_type='spec', generate_context_prefix=False,\n"
            "      generate_embedding=False, dispatch=False)\n"
            "    print(s.__dict__)\n") % (str(LIB_DIR), initial, updated)
    rc, out, err = run_python(env, code)
    rows = db_query(
        home,
        "SELECT chunk_index, section_path, is_current, valid_to FROM chunks_v2 "
        "WHERE document_id IN (SELECT id FROM documents WHERE source_ref='tc07') "
        "ORDER BY chunk_index",
    )
    current_count = sum(1 for r in rows if r[2] == 1)
    obsolete_count = sum(1 for r in rows if r[2] == 0 and r[3] is not None)
    case.metrics = {"total_rows": len(rows), "current": current_count, "obsolete": obsolete_count}
    case.passed = current_count == 2 and obsolete_count == 1
    case.detail = f"total={len(rows)} current={current_count} obsolete={obsolete_count}"


def tc_08_contradiction_llm(env: dict, home: str, case: CaseResult) -> None:
    """LLM judge 활성. claude CLI 호출이 11~28s 소요."""
    env_llm = dict(env)
    env_llm.pop("IMPRINT_DISABLE_LLM_JUDGE", None)

    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.entity import upsert_entity\n"
            "from retrieval._common import db_connect, new_id, now_iso\n"
            "eid = upsert_entity('p_test', 'ui_element', 'tc08_btn', 'TC08 버튼')\n"
            "conn = db_connect()\n"
            "conn.execute(\"INSERT INTO documents (id, project_id, source_type, source_ref, raw_text, checksum, source_updated_at, created_at, updated_at) VALUES ('tc08_d1','p_test','meeting','tc08_m1','x','c1','2026-04-10T10:00:00Z','2026-04-10','2026-04-10')\")\n"
            "conn.execute(\"INSERT INTO documents (id, project_id, source_type, source_ref, raw_text, checksum, source_updated_at, created_at, updated_at) VALUES ('tc08_d2','p_test','meeting','tc08_m2','y','c2','2026-05-01T10:00:00Z','2026-05-01','2026-05-01')\")\n"
            "conn.execute(\"INSERT INTO chunks_v2 (id, project_id, document_id, chunk_index, section_path, chunk_text, retrieval_text, raw_chunk_type, normalized_chunk_type, source_updated_at, valid_from, is_current, created_at) VALUES ('tc08_c1','p_test','tc08_d1',0,'TC08','test 버튼 클릭 시 즉시 테스트 모드로 진입한다.','...','decision','decision','2026-04-10T10:00:00Z','2026-04-10',1,'2026-04-10')\")\n"
            "conn.execute(\"INSERT INTO chunks_v2 (id, project_id, document_id, chunk_index, section_path, chunk_text, retrieval_text, raw_chunk_type, normalized_chunk_type, source_updated_at, valid_from, is_current, created_at) VALUES ('tc08_c2','p_test','tc08_d2',0,'TC08','test 버튼 클릭 시 확인 모달 후 테스트 모드로 진입한다.','...','decision','decision','2026-05-01T10:00:00Z','2026-05-01',1,'2026-05-01')\")\n"
            "conn.execute('INSERT INTO chunk_entities VALUES (?, ?, ?, ?)', ('tc08_c1', eid, 'test 버튼', 0.9))\n"
            "conn.execute('INSERT INTO chunk_entities VALUES (?, ?, ?, ?)', ('tc08_c2', eid, 'test 버튼', 0.9))\n"
            "conn.close()\n"
            "from retrieval.contradiction import scan_and_store\n"
            "stats = scan_and_store('p_test')\n"
            "print(stats.__dict__)") % (str(LIB_DIR),)
    rc, out, err = run_python(env_llm, code)
    rows = db_query(
        home,
        "SELECT detector, status, contradiction_score FROM contradictions",
    )
    case.metrics = {
        "rows": len(rows),
        "detector": rows[0][0] if rows else None,
        "status": rows[0][1] if rows else None,
        "score": round(rows[0][2], 3) if rows else None,
        "stats": out,
    }
    case.passed = (
        len(rows) == 1
        and rows[0][1] == "candidate"
        and rows[0][2] >= 0.7
    )
    case.detail = (
        f"detector={rows[0][0] if rows else None} "
        f"status={rows[0][1] if rows else None} "
        f"score={round(rows[0][2], 3) if rows else None}"
    )


def tc_09_interruption_timeout(env: dict, home: str, case: CaseResult) -> None:
    """LLM judge 강제 timeout (1ms) + NLI 비활성 → rule fallback + needs_retry."""
    env_t = dict(env)
    env_t.pop("IMPRINT_DISABLE_LLM_JUDGE", None)
    env_t["IMPRINT_LLM_JUDGE_TIMEOUT_MS"] = "1"  # 사실상 즉시 timeout

    # 기존 contradictions 정리 후 재scan
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    conn.execute("DELETE FROM contradictions")
    conn.commit()
    conn.close()

    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.contradiction import scan_and_store\n"
            "stats = scan_and_store('p_test')\n"
            "print(stats.__dict__)") % (str(LIB_DIR),)
    rc, out, err = run_python(env_t, code)
    rows = db_query(home, "SELECT detector, status FROM contradictions")
    case.metrics = {
        "rows": len(rows),
        "detector": rows[0][0] if rows else None,
        "status": rows[0][1] if rows else None,
    }
    # rule fallback + status=candidate (needs_retry 보존)
    case.passed = (
        len(rows) == 1
        and rows[0][0] == "rule"
        and rows[0][1] == "candidate"
    )
    case.detail = f"detector={rows[0][0] if rows else None} status={rows[0][1] if rows else None}"


def tc_10_priority_drain(env: dict, home: str, case: CaseResult) -> None:
    """5건 enqueue (priority 1, 5, 5, 9, 9) → drain 순서가 priority asc."""
    code = ("import sys, json; sys.path.insert(0, %r)\n"
            "from retrieval.ingest_queue import enqueue, drain\n"
            "ids = []\n"
            "ids.append(enqueue('p_test', {'kind': 'ner_extract', 'project_id': 'p_test', 'document_id': 'fake1'}, priority=9))\n"
            "ids.append(enqueue('p_test', {'kind': 'ner_extract', 'project_id': 'p_test', 'document_id': 'fake2'}, priority=9))\n"
            "ids.append(enqueue('p_test', {'kind': 'summary_regen', 'level': 'project', 'project_id': 'p_test'}, priority=5))\n"
            "ids.append(enqueue('p_test', {'kind': 'summary_regen', 'level': 'project', 'project_id': 'p_test'}, priority=5))\n"
            "ids.append(enqueue('p_test', {'kind': 'fake_high', 'project_id': 'p_test'}, priority=1))\n"
            "order = []\n"
            "def handler(payload):\n"
            "    order.append(payload.get('kind'))\n"
            "    # fake_high 는 그냥 통과, ner_extract / summary_regen 은 실제 dispatch 가 fail 할 수 있어 raise 흡수\n"
            "    if payload.get('kind') == 'ner_extract':\n"
            "        return  # NER LLM 비활성이므로 no-op handler 로 처리\n"
            "    if payload.get('kind') == 'summary_regen':\n"
            "        return\n"
            "stats = drain(handler, project_id='p_test')\n"
            "print(json.dumps({'order': order, 'stats': stats}))") % (str(LIB_DIR),)
    rc, out, err = run_python(env, code)
    import json as _json
    parsed = _json.loads(out) if out else {}
    order = parsed.get("order") or []
    # priority asc → 1 (fake_high) 가 먼저, 그다음 5 (summary_regen) 2건, 마지막 9 (ner_extract) 2건
    expected_first = "fake_high"
    expected_middle = "summary_regen"
    expected_last = "ner_extract"
    valid_order = (
        len(order) == 5
        and order[0] == expected_first
        and order[1] == expected_middle and order[2] == expected_middle
        and order[3] == expected_last and order[4] == expected_last
    )
    case.metrics = {"drain_order": order, "stats": parsed.get("stats")}
    case.passed = valid_order
    case.detail = f"order={order}"


def tc_11_hook_memory_loop(env: dict, home: str, case: CaseResult) -> None:
    """SessionStart → UPS → Stop → 다음 UPS + redaction 회귀 검증."""
    env_h = hook_env(env)
    env_h["IMPRINT_CLAUDE_BIN"] = make_fake_claude(home)
    raw_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    raw_password = "password=super-secret-123"

    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/session-start.sh"])
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    prompt = f'A 버튼 클릭 동작 알려줘 token {raw_token}'
    ups_input = json.dumps({"prompt": prompt, "session_id": "tc11"}, ensure_ascii=False)
    rc, ups_out, err = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=ups_input,
    )
    if rc != 0:
        case.passed = False
        case.detail = f"ups rc={rc} err={err[:120]}"
        return

    transcript = Path(home) / "tc11-transcript.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "text",
                    "text": f"결정: A 버튼 클릭은 테스트 모드를 시작합니다. {raw_password}",
                }],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    stop_input = json.dumps({"transcript_path": str(transcript)}, ensure_ascii=False)
    rc, _, err = run_cmd(
        env_h, ["bash", "scripts/imprint/stop.sh"], input_text=stop_input,
    )
    if rc != 0:
        case.passed = False
        case.detail = f"stop rc={rc} err={err[:120]}"
        return

    time.sleep(0.5)
    next_input = json.dumps({"prompt": "A 버튼 클릭 동작 알려줘", "session_id": "tc11-next"}, ensure_ascii=False)
    rc, next_out, err = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=next_input,
    )

    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        event_rows = conn.execute(
            "SELECT kind, text_clean FROM events WHERE project_id = ? ORDER BY created_at",
            (ROOT_PROJECT_ID,),
        ).fetchall()
        chunk_rows = conn.execute(
            "SELECT chunk_type, text, metadata_json FROM memory_chunks "
            "WHERE project_id = ? AND source_event_id IS NOT NULL",
            (ROOT_PROJECT_ID,),
        ).fetchall()
    finally:
        conn.close()

    all_event_text = "\n".join(row[1] for row in event_rows)
    all_chunk_text = "\n".join(row[1] for row in chunk_rows)
    raw_absent = (
        raw_token not in all_event_text
        and raw_token not in all_chunk_text
        and raw_password not in all_event_text
        and raw_password not in all_chunk_text
    )
    redacted_present = (
        "gh*_[REDACTED]" in all_event_text
        and "[REDACTED]" in all_event_text
        and "gh*_[REDACTED]" in all_chunk_text
    )
    prefilled = "[Project memory context]" in next_out and "A 버튼 클릭은" in next_out

    case.metrics = {
        "events": len(event_rows),
        "chunks": len(chunk_rows),
        "raw_absent": raw_absent,
        "redacted_present": redacted_present,
        "prefilled": prefilled,
    }
    case.passed = (
        rc == 0
        and len(event_rows) >= 2
        and len(chunk_rows) >= 1
        and raw_absent
        and redacted_present
        and prefilled
    )
    case.detail = (
        f"events={len(event_rows)} chunks={len(chunk_rows)} "
        f"redacted={redacted_present} prefilled={prefilled}"
    )


def tc_12_memory_search_fixture(env: dict, home: str, case: CaseResult) -> None:
    """memory_chunks 기본 RAG 경로: search/list/inject fixture."""
    env_h = hook_env(env)
    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/session-start.sh"])
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    now = "2026-05-16T00:00:00Z"
    rows = [
        ("tc12-decision", "decision", "테스트모드 A 버튼 결정 사항입니다.", "{}", 1),
        ("tc12-fix", "fix", "테스트모드 클릭 오류를 수정했습니다.", "{}", 0),
        ("tc12-todo", "todo", "테스트모드 접근성 TODO를 확인해야 합니다.", "{}", 0),
        ("tc12-note", "note", "테스트모드 참고 노트입니다.", "{}", 0),
        ("tc12-spec", "spec", "테스트모드 노션 정책입니다.", '{"source":"notion","page_id":"tc12"}', 0),
        ("tc12-message", "message", "테스트모드 Slack 공지입니다.", '{"source":"slack","channel":"#tc12"}', 0),
        ("tc12-thread", "thread", "테스트모드 Slack thread 요약입니다.", '{"source":"slack","channel":"#tc12"}', 0),
    ]
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        for rid, ctype, text, metadata, pinned in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_chunks
                  (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (rid, ROOT_PROJECT_ID, ctype, text, metadata, now, pinned),
            )
        conn.commit()
    finally:
        conn.close()

    memory = ["bash", "scripts/imprint/memory.sh"]
    rc_s, search_out, search_err = run_cmd(env_h, memory + ["search", "테스트모드"])
    rc_short, short_out, _ = run_cmd(env_h, memory + ["search", "버튼"])
    rc_p, pinned_out, _ = run_cmd(env_h, memory + ["list", "--pinned", "--limit", "5"])
    rc_f, filtered_out, _ = run_cmd(
        env_h, memory + ["list", "--type", "spec", "--source", "notion", "--limit", "5"],
    )
    rc_i, inject_out, _ = run_cmd(env_h, memory + ["inject", "tc12-spec"])

    found_count = sum(1 for line in search_out.splitlines() if line.strip())
    checks = {
        "search_all_types": rc_s == 0 and found_count >= 7,
        "short_korean_fallback": rc_short == 0 and "tc12-decision" in short_out,
        "pinned_first": rc_p == 0 and pinned_out.splitlines() and pinned_out.splitlines()[0].startswith("tc12-decision|"),
        "type_source_filter": rc_f == 0 and "tc12-spec" in filtered_out and "tc12-message" not in filtered_out,
        "inject_text": rc_i == 0 and inject_out == "테스트모드 노션 정책입니다.",
    }
    case.metrics = checks | {"found_count": found_count}
    case.passed = all(checks.values())
    case.detail = (
        f"found={found_count} short={checks['short_korean_fallback']} pinned={checks['pinned_first']} "
        f"filter={checks['type_source_filter']} inject={checks['inject_text']}"
    )
    if not case.passed and search_err:
        case.detail += f" search_err={search_err[:120]}"


def tc_13_source_noise_profile(env: dict, home: str, case: CaseResult) -> None:
    """External source status, events.noise, profile summary."""
    env_h = hook_env(env)
    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/session-start.sh"])
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    old_fetch = "2026-01-01T00:00:00Z"
    now = "2026-05-16T00:00:00Z"
    rows = [
        ("tc13-stale", "spec", "오래된 Notion chunk", '{"source":"notion","url":"https://notion.so/x","fetched_at":"%s"}' % old_fetch),
        ("tc13-failed", "source_status", "Slack fetch failed", '{"source":"slack","status":"fetch_failed","url":"https://x.slack.com/archives/C/p1","fetched_at":"%s"}' % now),
        ("tc13-cap", "source_status", "Notion URL skipped", '{"source":"notion","status":"skipped_by_cap","url":"https://notion.so/y","fetched_at":"%s"}' % now),
    ]
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        for rid, ctype, text, metadata in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_chunks
                  (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
                VALUES (?, ?, NULL, ?, ?, ?, ?, 0)
                """,
                (rid, ROOT_PROJECT_ID, ctype, text, metadata, now),
            )
        conn.commit()
    finally:
        conn.close()

    memory = ["bash", "scripts/imprint/memory.sh"]
    env_status = dict(env_h)
    env_status["IMPRINT_STALE_DAYS"] = "30"
    rc_l, list_out, _ = run_cmd(env_status, memory + ["list", "--limit", "20"])
    rc_show, show_out, _ = run_cmd(env_status, memory + ["show", "tc13-stale", "--json"])

    noise_input = json.dumps({"prompt": "응", "session_id": "tc13"}, ensure_ascii=False)
    rc_n, _, _ = run_cmd(env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=noise_input)
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        noise_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE project_id = ? AND noise = 1",
            (ROOT_PROJECT_ID,),
        ).fetchone()[0]
    finally:
        conn.close()

    profile_path = Path(home) / "profile.jsonl"
    profile_path.write_text(
        "\n".join([
            json.dumps({"ts": "2026-05-16T00:00:00Z", "stage": "cmd_prefill", "dur_ms": 10}),
            json.dumps({"ts": "2026-05-16T00:00:01Z", "stage": "cmd_prefill", "dur_ms": 20}),
            json.dumps({"ts": "2026-05-16T00:00:02Z", "stage": "fetch_notion_url.payload", "payload_bytes": 1234}),
        ]) + "\n",
        encoding="utf-8",
    )
    rc_p, profile_out, _ = run_cmd(env_h, memory + ["profile", "--days", "9999", "--json"])
    try:
        profile = json.loads(profile_out)
    except json.JSONDecodeError:
        profile = {}
    try:
        shown = json.loads(show_out)
    except json.JSONDecodeError:
        shown = {}

    checks = {
        "list_stale": rc_l == 0 and "tc13-stale|spec|0|notion|stale|" in list_out,
        "list_failed": "tc13-failed|source_status|0|slack|fetch_failed|" in list_out,
        "list_cap": "tc13-cap|source_status|0|notion|skipped_by_cap|" in list_out,
        "show_status": rc_show == 0 and shown.get("source_status") == "stale",
        "noise": rc_n == 0 and noise_count >= 1,
        "profile": (
            rc_p == 0
            and profile.get("stages", {}).get("cmd_prefill", {}).get("count") == 2
            and profile.get("payloads", {}).get("fetch_notion_url.payload", {}).get("max_bytes") == 1234
        ),
    }
    case.metrics = checks
    case.passed = all(checks.values())
    case.detail = (
        f"stale={checks['list_stale']} failed={checks['list_failed']} "
        f"noise={checks['noise']} profile={checks['profile']}"
    )


def tc_14_retrieve_memory_fallback(env: dict, home: str, case: CaseResult) -> None:
    """chunks_v2 결과가 없으면 /retrieve 가 memory_chunks 를 read-only fallback."""
    now = "2026-05-16T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_chunks
              (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 0)
            """,
            (
                "tc14-memory",
                PROJECT_ID,
                "decision",
                "제피르 루틴은 설정 동기화를 시작합니다.",
                "{}",
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_chunks
              (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 1)
            """,
            (
                "tc14-source-status",
                PROJECT_ID,
                "source_status",
                "제피르 루틴 fetch failed marker 입니다.",
                '{"source":"notion","status":"fetch_failed"}',
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    plain = _retrieve_plain_json(env, "제피르 루틴 설정동기화 알려줘")
    routed = _retrieve_json(env, "제피르 루틴 설정동기화 알려줘")
    plain_chunks = plain.get("candidates") or []
    routed_chunks = routed.get("chunks") or []
    plain_text = "\n".join(c.get("chunk_text", "") for c in plain_chunks)
    routed_text = "\n".join(c.get("chunk_text", "") for c in routed_chunks)
    status_leaked = any(
        c.get("raw_chunk_type") == "source_status" or c.get("chunk_id") == "tc14-source-status"
        for c in plain_chunks + routed_chunks
    )
    checks = {
        "plain_memory": "설정 동기화" in plain_text,
        "routed_memory": "설정 동기화" in routed_text,
        "source_status_excluded": not status_leaked,
    }
    case.metrics = checks | {
        "plain_chunks": len(plain_chunks),
        "routed_chunks": len(routed_chunks),
        "scope": (routed.get("scope") or {}).get("scope"),
    }
    case.passed = all(checks.values())
    case.detail = (
        f"plain={len(plain_chunks)} routed={len(routed_chunks)} "
        f"status_excluded={checks['source_status_excluded']}"
    )


def tc_15_first_turn_working_overlay(env: dict, home: str, case: CaseResult) -> None:
    """UserPromptSubmit sync mini-chunk + prefill/retrieve working overlay."""
    env_h = hook_env(env)
    env_h["IMPRINT_CLAUDE_BIN"] = make_fake_claude(home)
    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/session-start.sh"])
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    now = "2026-05-16T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_chunks
              (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 0)
            """,
            (
                "tc15-durable",
                ROOT_PROJECT_ID,
                "decision",
                "A 버튼 클릭은 테스트 모드를 시작합니다.",
                "{}",
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    ups_input = json.dumps({"prompt": "A 버튼 클릭 동작 알려줘", "session_id": "tc15"}, ensure_ascii=False)
    rc_ups, ups_out, ups_err = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=ups_input,
    )

    noise_input = json.dumps({"prompt": "응", "session_id": "tc15"}, ensure_ascii=False)
    rc_noise, _, _ = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=noise_input,
    )

    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        working_rows = conn.execute(
            """
            SELECT id, chunk_type, text, metadata_json
            FROM memory_chunks
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
            ORDER BY created_at
            """,
            (ROOT_PROJECT_ID,),
        ).fetchall()
        noise_working = conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_chunks
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
              AND text LIKE '%응%'
            """,
            (ROOT_PROJECT_ID,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO documents
              (id, project_id, source_type, source_ref, title, raw_text,
               source_created_at, source_updated_at, created_at, updated_at, checksum)
            VALUES (?, ?, 'notion', 'tc15-doc', 'TC15', ?, ?, ?, ?, ?, 'tc15hash')
            """,
            (
                "tc15-doc",
                ROOT_PROJECT_ID,
                "A 버튼 클릭 문서",
                now,
                now,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO chunks_v2
              (id, project_id, document_id, chunk_index, section_path, chunk_text,
               retrieval_text, raw_chunk_type, normalized_chunk_type,
               source_updated_at, valid_from, is_current, created_at)
            VALUES (?, ?, ?, 0, 'TC15', ?, ?, 'spec', 'spec', ?, ?, 1, ?)
            """,
            (
                "tc15-cv2",
                ROOT_PROJECT_ID,
                "tc15-doc",
                "A 버튼 클릭 시 문서 기반 테스트 모드가 시작됩니다.",
                "A 버튼 클릭 button click handler action onClick onTap",
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    env_r = dict(env)
    env_r["IMPRINT_SESSION_ID"] = "tc15"
    proc = subprocess.run(
        [sys.executable, "-m", "retrieval.cli", "retrieve_json", ROOT_PROJECT_ID, "A 버튼 클릭 동작 알려줘"],
        env=env_r, capture_output=True, text=True, cwd=str(LIB_DIR),
    )
    try:
        retrieved = json.loads(proc.stdout)
    except json.JSONDecodeError:
        retrieved = {}
    candidates = retrieved.get("candidates") or []
    chunk_ids = {c.get("chunk_id") for c in candidates}
    working_ok = False
    rewrite_ok = False
    if working_rows:
        try:
            md = json.loads(working_rows[0][3] or "{}")
        except json.JSONDecodeError:
            md = {}
        working_ok = (
            working_rows[0][1] == "raw_turn"
            and md.get("memory_tier") == "working"
            and md.get("memory_kind") == "raw_turn"
            and md.get("session_visible") is True
        )
        rewrite_ok = "onclick" in (md.get("query_rewrite") or "")

    checks = {
        "ups": rc_ups == 0,
        "working_chunk": working_ok,
        "rewrite": rewrite_ok,
        "prefill_working": "[working] A 버튼 클릭 동작 알려줘" in ups_out,
        "prefill_durable": "테스트 모드" in ups_out,
        "noise_no_working": rc_noise == 0 and noise_working == 0,
        "retrieve_union_working": any(c.get("source_type") == "working" for c in candidates),
        "retrieve_keeps_chunks_v2": "tc15-cv2" in chunk_ids,
    }
    case.metrics = checks | {
        "working_rows": len(working_rows),
        "retrieved": len(candidates),
    }
    case.passed = all(checks.values())
    case.detail = (
        f"working={len(working_rows)} prefill={checks['prefill_working']}/{checks['prefill_durable']} "
        f"retrieve={len(candidates)} union={checks['retrieve_union_working']} cv2={checks['retrieve_keeps_chunks_v2']}"
    )
    if not case.passed and ups_err:
        case.detail += f" ups_err={ups_err[:120]}"


# -----------------------------------------------------------------------------
# 러너
# -----------------------------------------------------------------------------

CASES: list[tuple[str, str, callable]] = [
    ("TC-01", "Save 짧은 텍스트", tc_01_save_short),
    ("TC-02", "Save 긴 문서 (다중 chunk)", tc_02_save_long),
    ("TC-03", "Retrieve 짧은 쿼리 (local)", tc_03_retrieve_short),
    ("TC-04", "Retrieve 긴 쿼리 (feature)", tc_04_retrieve_feature),
    ("TC-05", "Retrieve global 쿼리", tc_05_retrieve_global),
    ("TC-06", "Entity alias 매칭", tc_06_entity_alias),
    ("TC-07", "Document 갱신 + supersede", tc_07_supersede),
    ("TC-08", "Contradiction 감지 (LLM judge)", tc_08_contradiction_llm),
    ("TC-09", "요청 중간 중단 (timeout)", tc_09_interruption_timeout),
    ("TC-10", "동시 ingest priority drain", tc_10_priority_drain),
    ("TC-11", "Hook memory loop + redaction", tc_11_hook_memory_loop),
    ("TC-12", "Memory search/list/inject fixture", tc_12_memory_search_fixture),
    ("TC-13", "Source status + noise + profile", tc_13_source_noise_profile),
    ("TC-14", "Retrieve memory_chunks fallback", tc_14_retrieve_memory_fallback),
    ("TC-15", "First-turn working overlay", tc_15_first_turn_working_overlay),
]


def main() -> int:
    home, env = setup_env()
    env = setup_pythonpath(env)
    print(f"IMPRINT_HOME={home}")
    print()

    results: list[CaseResult] = []
    total_t0 = _now_ms()
    for tc_id, label, fn in CASES:
        case = CaseResult(name=tc_id, label=label)
        t0 = _now_ms()
        try:
            fn(env, home, case)
        except Exception as exc:
            case.passed = False
            case.detail = f"EXCEPTION: {exc!r}"
        case.ms = _now_ms() - t0
        results.append(case)
        status = "PASS" if case.passed else "FAIL"
        print(f"{tc_id}  {status}  {case.ms:>5d} ms  | {case.label:30s} | {case.detail}")

    total_ms = _now_ms() - total_t0
    n_pass = sum(1 for r in results if r.passed)
    n_fail = len(results) - n_pass
    print()
    print(f"TOTAL  {n_pass} PASS / {n_fail} FAIL  {total_ms} ms")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
