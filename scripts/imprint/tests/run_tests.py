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
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # imprint repo root
LIB_DIR = ROOT / "scripts" / "imprint" / "lib"
SCHEMA_PATH = LIB_DIR / "schema.sql"

PROJECT_ID = "p_test"


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


def db_query(home: str, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        cur = conn.execute(sql, params)
        return list(cur.fetchall())
    finally:
        conn.close()


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


def tc_03_retrieve_short(env: dict, home: str, case: CaseResult) -> None:
    out = _retrieve_json(env, "test 버튼")
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
