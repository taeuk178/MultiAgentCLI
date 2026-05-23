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
    # model judge 는 TC-08 에서만 활성화
    env["IMPRINT_DISABLE_MODEL_JUDGE"] = "1"
    env["IMPRINT_BYPASS_HOOKS"] = "1"  # background host CLI 호출 시 hook 무한재귀 방지

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


def codex_hook_env(env: dict) -> dict:
    out = dict(env)
    out.pop("IMPRINT_BYPASS_HOOKS", None)
    out["IMPRINT_NO_SEED"] = "1"
    out.pop("CLAUDE_PLUGIN_ROOT", None)
    out["PLUGIN_ROOT"] = str(ROOT)
    return out


def make_fake_claude(home: str) -> str:
    path = Path(home) / "fake-claude"
    raw_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    path.write_text(
        f"""#!/bin/sh
joined="$*"
stdin="$(cat)"
joined="$joined $stdin"
case "$joined" in
  *"Extract low-cost flat memory chunks"*)
    printf '%s\\n' '[{{"chunk_type":"fix","text":"A 버튼 클릭 테스트 명령을 수정했습니다. {raw_token}","keywords":["A 버튼","{raw_token}"]}}]'
    ;;
  *"Extract cross-turn implementation memory"*)
    printf '%s\\n' '[{{"chunk_type":"summary","text":"A 버튼 구현 흐름을 세션 rollup으로 요약했습니다.","keywords":["A 버튼","rollup"]}}]'
    ;;
  *"Extract persistent memory chunks"*)
    printf '%s\\n' '[{{"chunk_type":"decision","text":"A 버튼 클릭은 {raw_token} 없이 테스트 모드를 시작합니다.","keywords":["A 버튼","{raw_token}"]}}]'
    ;;
  *"contradiction judge"*)
    printf '%s\\n' '{{"verdict":"contradiction","score":0.95,"reason":"새 결정이 기존 즉시 진입 결정을 대체합니다."}}'
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


def make_fake_codex(home: str) -> str:
    path = Path(home) / "fake-codex"
    raw_token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    path.write_text(
        f"""#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    out="$1"
  fi
  shift
done
joined="$*"
stdin="$(cat)"
joined="$joined $stdin"
case "$joined" in
  *"Extract low-cost flat memory chunks"*)
    result='[{{"chunk_type":"fix","text":"A 버튼 클릭 테스트 명령을 수정했습니다. {raw_token}","keywords":["A 버튼","{raw_token}"]}}]'
    ;;
  *"Extract cross-turn implementation memory"*)
    result='[{{"chunk_type":"summary","text":"A 버튼 구현 흐름을 세션 rollup으로 요약했습니다.","keywords":["A 버튼","rollup"]}}]'
    ;;
  *"Extract persistent memory chunks"*)
    result='[{{"chunk_type":"decision","text":"A 버튼 클릭은 {raw_token} 없이 테스트 모드를 시작합니다.","keywords":["A 버튼","{raw_token}"]}}]'
    ;;
  *"contradiction judge"*)
    result='{{"verdict":"contradiction","score":0.95,"reason":"새 결정이 기존 즉시 진입 결정을 대체합니다."}}'
    ;;
  *"Return STRICT JSON with EXACTLY these keys"*)
    result='{{"ambiguity_score":0.1,"keywords":["A 버튼","클릭","button click"],"refined_prompt":null}}'
    ;;
  *)
    result='[]'
    ;;
esac
if [ -n "$out" ]; then
  printf '%s\\n' "$result" > "$out"
else
  printf '%s\\n' "$result"
fi
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
    raw_type='spec',
    generate_context_prefix=False, generate_embedding=False,
    dispatch=False,
)
print(stats.chunks_inserted)
""" % (str(LIB_DIR),)
    rc, out, err = run_python(env, code)
    chunks = int(out) if out else 0
    docs = db_query(home, "SELECT count(*) FROM source_documents WHERE source_ref='tc01'")[0][0]
    case.metrics = {"chunks": chunks, "source_documents": docs, "rc": rc}
    case.passed = rc == 0 and chunks == 1 and docs == 1
    case.detail = f"chunks={chunks} source_documents={docs}"
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
            "  raw_type='spec', generate_context_prefix=False,\n"
            "  generate_embedding=False, dispatch=False)\n"
            "print(stats.chunks_inserted)") % (str(LIB_DIR), long_doc)
    rc, out, err = run_python(env, code)
    chunks = int(out) if out else 0
    sections = db_query(
        home,
        "SELECT count(DISTINCT section_path) FROM search_entries WHERE source_document_id IN (SELECT id FROM source_documents WHERE source_ref='tc02')",
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


def _search_script_output(env: dict, query: str, cwd: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "imprint" / "search.sh"), query],
        env=env, capture_output=True, text=True, cwd=cwd,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _remember_script_output(env: dict, args: list[str], cwd: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "imprint" / "remember.sh"), *args],
        env=env, capture_output=True, text=True, cwd=cwd,
    )
    return proc.returncode, proc.stdout, proc.stderr


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
            "rows = conn.execute(\"SELECT id FROM source_documents WHERE project_id='p_test'\").fetchall()\n"
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
            "      raw_type='spec', generate_context_prefix=False,\n"
            "      generate_embedding=False, dispatch=False)\n"
            "    print(s.__dict__)\n") % (str(LIB_DIR), initial, updated)
    rc, out, err = run_python(env, code)
    rows = db_query(
        home,
        "SELECT chunk_index, section_path, is_current, valid_to FROM search_entries "
        "WHERE source_document_id IN (SELECT id FROM source_documents WHERE source_ref='tc07') "
        "ORDER BY chunk_index",
    )
    current_count = sum(1 for r in rows if r[2] == 1)
    obsolete_count = sum(1 for r in rows if r[2] == 0 and r[3] is not None)
    case.metrics = {"total_rows": len(rows), "current": current_count, "obsolete": obsolete_count}
    case.passed = current_count == 2 and obsolete_count == 1
    case.detail = f"total={len(rows)} current={current_count} obsolete={obsolete_count}"


def tc_08_contradiction_llm(env: dict, home: str, case: CaseResult) -> None:
    """model judge 활성 경로를 fake Codex host 로 결정적으로 검증."""
    env_llm = dict(env)
    env_llm.pop("IMPRINT_DISABLE_MODEL_JUDGE", None)
    env_llm["IMPRINT_CODEX_BIN"] = make_fake_codex(home)

    code = ("import sys; sys.path.insert(0, %r)\n"
            "from retrieval.entity import upsert_entity\n"
            "from retrieval._common import db_connect, new_id, now_iso\n"
            "eid = upsert_entity('p_test', 'ui_element', 'tc08_btn', 'TC08 버튼')\n"
            "conn = db_connect()\n"
            "conn.execute(\"INSERT INTO source_documents (id, project_id, source_type, source_ref, raw_text, checksum, source_updated_at, created_at, updated_at) VALUES ('tc08_d1','p_test','meeting','tc08_m1','x','c1','2026-04-10T10:00:00Z','2026-04-10','2026-04-10')\")\n"
            "conn.execute(\"INSERT INTO source_documents (id, project_id, source_type, source_ref, raw_text, checksum, source_updated_at, created_at, updated_at) VALUES ('tc08_d2','p_test','meeting','tc08_m2','y','c2','2026-05-01T10:00:00Z','2026-05-01','2026-05-01')\")\n"
            "conn.execute(\"INSERT INTO search_entries (id, project_id, source_document_id, chunk_index, section_path, text, retrieval_text, raw_type, normalized_type, source_updated_at, valid_from, is_current, created_at) VALUES ('tc08_c1','p_test','tc08_d1',0,'TC08','test 버튼 클릭 시 즉시 테스트 모드로 진입한다.','...','decision','decision','2026-04-10T10:00:00Z','2026-04-10',1,'2026-04-10')\")\n"
            "conn.execute(\"INSERT INTO search_entries (id, project_id, source_document_id, chunk_index, section_path, text, retrieval_text, raw_type, normalized_type, source_updated_at, valid_from, is_current, created_at) VALUES ('tc08_c2','p_test','tc08_d2',0,'TC08','test 버튼 클릭 시 확인 모달 후 테스트 모드로 진입한다.','...','decision','decision','2026-05-01T10:00:00Z','2026-05-01',1,'2026-05-01')\")\n"
            "conn.execute('INSERT INTO entry_entities VALUES (?, ?, ?, ?)', ('tc08_c1', eid, 'test 버튼', 0.9))\n"
            "conn.execute('INSERT INTO entry_entities VALUES (?, ?, ?, ?)', ('tc08_c2', eid, 'test 버튼', 0.9))\n"
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
    """model judge 강제 timeout (1ms) + NLI 비활성 → rule fallback + needs_retry."""
    env_t = dict(env)
    env_t.pop("IMPRINT_DISABLE_MODEL_JUDGE", None)
    env_t["IMPRINT_MODEL_JUDGE_TIMEOUT_MS"] = "1"  # 사실상 즉시 timeout

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
            "ids.append(enqueue('p_test', {'kind': 'ner_extract', 'project_id': 'p_test', 'source_document_id': 'fake1'}, priority=9))\n"
            "ids.append(enqueue('p_test', {'kind': 'ner_extract', 'project_id': 'p_test', 'source_document_id': 'fake2'}, priority=9))\n"
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
            "SELECT raw_type, text, metadata_json FROM search_entries "
            "WHERE project_id = ? AND source_event_id IS NOT NULL",
            (ROOT_PROJECT_ID,),
        ).fetchall()
    finally:
        conn.close()

    all_event_text = "\n".join(row[1] for row in event_rows)
    all_text = "\n".join(row[1] for row in chunk_rows)
    raw_absent = (
        raw_token not in all_event_text
        and raw_token not in all_text
        and raw_password not in all_event_text
        and raw_password not in all_text
    )
    redacted_present = (
        "gh*_[REDACTED]" in all_event_text
        and "[REDACTED]" in all_event_text
    )
    prefilled = "[Project memory context]" in next_out

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
        and raw_absent
        and redacted_present
    )
    case.detail = (
        f"events={len(event_rows)} chunks={len(chunk_rows)} "
        f"redacted={redacted_present} prefilled={prefilled}"
    )


def tc_12_memory_search_fixture(env: dict, home: str, case: CaseResult) -> None:
    """search_entries 기본 RAG 경로: search/list/inject fixture."""
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
                INSERT OR REPLACE INTO search_entries
                  (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
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
                INSERT OR REPLACE INTO search_entries
                  (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
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


def tc_14_retrieve_search_entries_primary(env: dict, home: str, case: CaseResult) -> None:
    """search_entries primary search retrieves entries and excludes source_status."""
    now = "2026-05-16T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
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
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
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
    plain_text = "\n".join(c.get("text", "") for c in plain_chunks)
    routed_text = "\n".join(c.get("text", "") for c in routed_chunks)
    status_leaked = any(
        c.get("raw_type") == "source_status" or c.get("entry_id") == "tc14-source-status"
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


def tc_20_legacy_migration_backfill(env: dict, home: str, case: CaseResult) -> None:
    """legacy memory_chunks 를 explicit migration 으로 search_entries에 흡수."""
    now = "2026-05-22T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            """
            CREATE TABLE memory_chunks (
              id TEXT PRIMARY KEY, project_id TEXT, source_event_id TEXT,
              chunk_type TEXT, text TEXT, metadata_json TEXT DEFAULT '{}',
              created_at TEXT, pinned INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_chunks
              (id, project_id, source_event_id, chunk_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "tc20-memory",
                PROJECT_ID,
                "tc20-event",
                "decision",
                "초대 링크 공유하기 구현은 딥링크 토큰을 생성해 로그인 feature로 전달한다.",
                json.dumps({
                    "source_type": "chat",
                    "evidence_level": "assistant_extracted",
                    "text_hash": "tc20hash",
                }),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rc, out, err = run_cmd(
        env,
        [sys.executable, "-m", "retrieval.cli", "migrate-search-entries"],
    )
    stats = json.loads(out) if out else {}
    rc_noop, out_noop, _ = run_cmd(
        env,
        [sys.executable, "-m", "retrieval.cli", "migrate-search-entries"],
    )
    stats_noop = json.loads(out_noop) if out_noop else {}
    rows = db_query(
        home,
        """
        SELECT id, raw_type, normalized_type, metadata_json, origin
        FROM search_entries
        WHERE id = 'tc20-memory'
        """,
    )
    retrieved = _retrieve_plain_json(env, "로그인 feature 공유하기 구현 알려줘")
    candidates = retrieved.get("candidates") or []
    bridged_candidate = next(
        (
            c for c in candidates
            if c.get("entry_id") == "tc20-memory"
            and "딥링크 토큰" in c.get("text", "")
        ),
        None,
    )
    metadata = json.loads(rows[0][3]) if rows else {}
    checks = {
        "cli_ok": rc == 0,
        "one_migrated": len(rows) == 1 and stats.get("entries_from_memory") == 1,
        "type_mapped": bool(rows and rows[0][1] == "decision" and rows[0][2] == "decision"),
        "provenance": metadata.get("migrated_from") == "memory_chunks"
        and metadata.get("text_hash") == "tc20hash",
        "retrieve_search_entries": bridged_candidate is not None,
        "noop_no_backup": rc_noop == 0 and stats_noop.get("backup") is None,
    }
    case.metrics = checks | {
        "stats": stats,
        "noop": stats_noop,
        "rows": len(rows),
        "err": err[:120],
    }
    case.passed = all(checks.values())
    case.detail = (
        f"migrated={stats.get('entries_from_memory')} rows={len(rows)} "
        f"retrieve_search_entries={checks['retrieve_search_entries']} "
        f"noop_backup={stats_noop.get('backup')}"
    )


def tc_21_search_skill_dispatcher(env: dict, home: str, case: CaseResult) -> None:
    """User-facing /search dispatcher reaches the hybrid retrieval path."""
    project_root = tempfile.mkdtemp(prefix="imprint-search-project-")
    pid_proc = subprocess.run(
        ["bash", "-lc", f"source {ROOT / 'scripts' / 'imprint' / 'lib' / 'common.sh'}; project_id"],
        env=env, capture_output=True, text=True, cwd=project_root,
    )
    pid = pid_proc.stdout.strip()
    now = "2026-05-23T00:00:00Z"

    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO projects VALUES (?, ?, ?, ?, ?)",
            (pid, project_root, "search-fixture", now, now),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 0)
            """,
            (
                "tc21-search-memory",
                pid,
                "decision",
                "아틀라스 검색 스킬은 /search 이름으로 hybrid retrieval 엔진을 호출한다.",
                "{}",
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rc, out, err = _search_script_output(env, "아틀라스 검색 스킬", project_root)
    checks = {
        "script_ok": pid_proc.returncode == 0 and bool(pid) and rc == 0,
        "entry_retrieved": "hybrid retrieval 엔진" in out,
    }
    case.metrics = checks | {"stdout_len": len(out), "error": err[:120]}
    case.passed = all(checks.values())
    case.detail = (
        f"script={checks['script_ok']} retrieved={checks['entry_retrieved']} "
        f"stdout={len(out)}"
    )


def tc_22_remember_skill_dispatcher(env: dict, home: str, case: CaseResult) -> None:
    """User-facing /remember dispatcher stores directly through search_entries."""
    project_root = tempfile.mkdtemp(prefix="imprint-remember-project-")
    pid_proc = subprocess.run(
        ["bash", "-lc", f"source {ROOT / 'scripts' / 'imprint' / 'lib' / 'common.sh'}; project_id"],
        env=env, capture_output=True, text=True, cwd=project_root,
    )
    pid = pid_proc.stdout.strip()
    now = "2026-05-23T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO projects VALUES (?, ?, ?, ?, ?)",
            (pid, project_root, "remember-fixture", now, now),
        )
        conn.commit()
    finally:
        conn.close()

    rc, out, err = _remember_script_output(
        env,
        ["아틀라스 저장 스킬은 /remember 이름으로 search_entries에 저장한다.", "--require"],
        project_root,
    )
    rc_bad, _, err_bad = _remember_script_output(
        env,
        ["오타 옵션은 저장되면 안 된다.", "--row"],
        project_root,
    )
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        rows = conn.execute(
            """
            SELECT id, raw_type, text, pinned, metadata_json
            FROM search_entries
            WHERE project_id = ? AND text LIKE '%/remember 이름%'
            """,
            (pid,),
        ).fetchall()
        bridge_rows = conn.execute(
            """
            SELECT d.source_ref, c.raw_type, c.normalized_type
            FROM source_documents d
            JOIN search_entries c ON c.source_document_id = d.id
            WHERE d.project_id = ? AND d.source_ref LIKE 'search_entries:%'
            """,
            (pid,),
        ).fetchall()
        bad_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM search_entries
            WHERE project_id = ? AND text LIKE '%오타 옵션%'
            """,
            (pid,),
        ).fetchone()[0]
    finally:
        conn.close()
    log_text = (Path(home) / "plugin.log").read_text() if (Path(home) / "plugin.log").exists() else ""

    checks = {
        "script_ok": pid_proc.returncode == 0 and bool(pid) and rc == 0 and "remembered" in out,
        "stored": len(rows) == 1
        and rows[0][1] == "note"
        and rows[0][3] == 1
        and json.loads(rows[0][4]).get("importance") == "require",
        "no_bridge": len(bridge_rows) == 0,
        "typo_rejected": rc_bad == 2
        and "unknown option --row" in err_bad
        and bad_rows == 0
        and "remember unknown option: --row" in log_text,
    }
    case.metrics = checks | {
        "rows": len(rows),
        "bridge_rows": len(bridge_rows),
        "bad_rows": bad_rows,
        "error": (err or err_bad)[:120],
    }
    case.passed = all(checks.values())
    case.detail = (
        f"script={checks['script_ok']} stored={checks['stored']} "
        f"no_bridge={checks['no_bridge']} typo_rejected={checks['typo_rejected']}"
    )


def tc_23_setup_vector_logging(env: dict, home: str, case: CaseResult) -> None:
    """Vector setup reports Korean progress and rejects typo options with logs."""
    rc, out, err = run_cmd(env, ["bash", "scripts/imprint/setup.sh", "vector", "--status"])
    rc_bad, _, err_bad = run_cmd(env, ["bash", "scripts/imprint/setup.sh", "vector", "--bogus"])
    log_text = (Path(home) / "plugin.log").read_text() if (Path(home) / "plugin.log").exists() else ""

    checks = {
        "status_ok": rc == 0,
        "stdout_progress": "[imprint setup] status 시작" in out
        and "[imprint setup] status 완료" in out
        and "vector_ready:" in out,
        "log_progress": "setup: status 시작" in log_text
        and "setup: status 완료" in log_text,
        "typo_rejected": rc_bad == 2
        and "알 수 없는 vector 옵션: --bogus" in err_bad
        and "ERROR: setup: 알 수 없는 vector 옵션: --bogus" in log_text,
    }
    case.metrics = checks | {
        "status_rc": rc,
        "bad_rc": rc_bad,
        "stdout": out[:160],
        "stderr": (err or err_bad)[:160],
    }
    case.passed = all(checks.values())
    case.detail = (
        f"status={checks['status_ok']} progress={checks['stdout_progress']} "
        f"log={checks['log_progress']} typo={checks['typo_rejected']}"
    )


def tc_24_extract_eval_harness(env: dict, home: str, case: CaseResult) -> None:
    """Offline eval harness accepts a pluggable extractor and scores search hits."""
    code = """
import json, sys
sys.path.insert(0, %r)
import ingestion
from retrieval.extract_eval import run_eval

def fake_model(_prompt, **_kwargs):
    return json.dumps([
        {
            "chunk_type": "decision",
            "text": "ShareLinkBuilder가 공유 링크 생성을 담당한다.",
            "keywords": ["ShareLinkBuilder", "공유 링크"],
        }
    ], ensure_ascii=False)

ingestion.run_background_model = fake_model
fixture = {
    "id": "decision-rich-baseline",
    "turns": [
        {"role": "user", "text": "공유 링크 생성을 LoginViewModel에 넣어도 될까요?"},
        {"role": "assistant", "text": "결정: ShareLinkBuilder가 공유 링크 생성을 담당한다. 이유: LoginViewModel 책임을 분리하기 위해서다."},
    ],
    "questions": [
        {"query": "ShareLinkBuilder 왜 만들었지", "expected_terms": ["ShareLinkBuilder"]},
    ],
}
with ingestion.db() as conn:
    out = run_eval(
        conn,
        project_id=%r,
        fixture=fixture,
        extractor=ingestion.extract_chunks_from_response,
    )
print(json.dumps(out, ensure_ascii=False))
""" % (str(LIB_DIR), PROJECT_ID)
    rc, out, err = run_python(env, code)
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {}
    checks = {
        "ok": rc == 0,
        "inserted": result.get("inserted") == 1,
        "matched": result.get("matched") == 1 and result.get("total") == 1,
        "pluggable": result.get("fixture_id") == "decision-rich-baseline",
    }
    case.metrics = checks | {"result": result, "err": err[:120]}
    case.passed = all(checks.values())
    case.detail = (
        f"inserted={result.get('inserted')} matched={result.get('matched')}/{result.get('total')}"
    )
    if not case.passed:
        case.detail += f" err={err[:120]}"


def tc_25_retrieval_text_override(env: dict, home: str, case: CaseResult) -> None:
    """Search entry writes can store a capped curated retrieval surface."""
    code = """
import json, sys
sys.path.insert(0, %r)
from retrieval._common import db_connect
from retrieval.entries import build_retrieval_surface, insert_search_entry

surface = build_retrieval_surface(
    text="공유 링크 생성 책임을 분리했다.",
    reason="LoginViewModel 책임이 커져서 별도 builder로 뺐다.",
    files=["Sources/Auth/ShareLinkBuilder.swift"],
    symbols=["ShareLinkBuilder"],
)
capped = build_retrieval_surface(
    text="짧은 결정",
    reason="r" * 400,
    max_chars=120,
)
conn = db_connect()
try:
    eid = insert_search_entry(
        conn,
        project_id=%r,
        origin="assistant_extract",
        raw_type="decision",
        text="공유 링크 생성 책임을 분리했다.",
        retrieval_text=surface,
        metadata={"source_uri": "tc25", "evidence_level": "middle"},
    )
    row = conn.execute(
        "SELECT text, retrieval_text FROM search_entries WHERE id = ?",
        (eid,),
    ).fetchone()
    conn.commit()
finally:
    conn.close()
print(json.dumps({
    "entry_id": eid,
    "text": row[0],
    "retrieval_text": row[1],
    "capped_len": len(capped),
    "capped": capped,
}, ensure_ascii=False))
""" % (str(LIB_DIR), PROJECT_ID)
    rc, out, err = run_python(env, code)
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {}
    retrieved = _retrieve_plain_json(env, "ShareLinkBuilder 왜")
    candidates = retrieved.get("candidates") or []
    hit = next((c for c in candidates if c.get("entry_id") == result.get("entry_id")), None)
    retrieval_text = result.get("retrieval_text") or ""
    checks = {
        "ok": rc == 0,
        "display_text_plain": result.get("text") == "공유 링크 생성 책임을 분리했다.",
        "surface_has_file": "Sources/Auth/ShareLinkBuilder.swift" in retrieval_text,
        "surface_has_symbol": "ShareLinkBuilder" in retrieval_text,
        "surface_capped": result.get("capped_len", 9999) <= 120,
        "search_hit": hit is not None,
    }
    case.metrics = checks | {"result": result, "err": err[:120]}
    case.passed = all(checks.values())
    case.detail = (
        f"hit={checks['search_hit']} capped={result.get('capped_len')} "
        f"surface={len(retrieval_text)}"
    )
    if not case.passed:
        case.detail += f" err={err[:120]}"


def tc_26_decision_rich_extract(env: dict, home: str, case: CaseResult) -> None:
    """Decision extract keeps reason/file/symbol metadata, redacts, and preserves flat chunks."""
    code = """
import json, sys
sys.path.insert(0, %r)
import ingestion

secret = "ghp_" + "A" * 24
response = (
    "결정: ShareLinkBuilder를 Sources/Auth/ShareLinkBuilder.swift에 둡니다. "
    "이유: LoginViewModel 책임을 줄입니다. "
    f"토큰 {secret}은 저장하면 안 됩니다. "
    "검증은 pytest tests/test_share_link.py 입니다."
)

def fake_model(_prompt, **_kwargs):
    return json.dumps([
        {
            "chunk_type": "decision",
            "text": "ShareLinkBuilder로 공유 링크 생성을 분리한다.",
            "keywords": ["ShareLinkBuilder", "공유 링크"],
            "reason": f"LoginViewModel 책임 분리 때문에 {secret}를 참고했다.",
            "files": ["Sources/Auth/ShareLinkBuilder.swift", "Sources/Fake.swift"],
            "symbols": ["ShareLinkBuilder", "GhostSymbol"],
            "alternatives": [f"LoginViewModel에 계속 둔다 {secret}"],
            "tests": ["pytest tests/test_share_link.py"],
        },
    ], ensure_ascii=False)

ingestion.run_background_model = fake_model
chunks = ingestion.extract_chunks_from_response(response)
with ingestion.db() as conn:
    ids = []
    for ch in chunks:
        ids.append(ingestion.insert_extracted_chunk(
            conn,
            %r,
            None,
            ch["chunk_type"],
            ch["text"],
            ch.get("keywords") or [],
            reason=ch.get("reason"),
            files=ch.get("files"),
            symbols=ch.get("symbols"),
            alternatives=ch.get("alternatives"),
            tests=ch.get("tests"),
        ))
    conn.commit()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT raw_type, text, retrieval_text, metadata_json FROM search_entries "
        f"WHERE id IN ({placeholders}) ORDER BY raw_type",
        tuple(ids),
    ).fetchall()

print(json.dumps({
    "chunks": chunks,
    "rows": [
        {
            "raw_type": r[0],
            "text": r[1],
            "retrieval_text": r[2],
            "metadata": json.loads(r[3] or "{}"),
        }
        for r in rows
    ],
    "secret": secret,
}, ensure_ascii=False))
""" % (str(LIB_DIR), PROJECT_ID)
    rc, out, err = run_python(env, code)
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        result = {}
    chunks = result.get("chunks") or []
    rows = result.get("rows") or []
    decision_chunk = next((c for c in chunks if c.get("chunk_type") == "decision"), {})
    decision_row = next((r for r in rows if r.get("raw_type") == "decision"), {})
    metadata = decision_row.get("metadata") or {}
    retrieval_text = decision_row.get("retrieval_text") or ""
    metadata_blob = json.dumps(metadata, ensure_ascii=False)
    secret = result.get("secret") or ""
    checks = {
        "ok": rc == 0,
        "kept_real_file": metadata.get("files") == ["Sources/Auth/ShareLinkBuilder.swift"],
        "dropped_fake_file": "Sources/Fake.swift" not in metadata_blob,
        "kept_real_symbol": metadata.get("symbols") == ["ShareLinkBuilder"],
        "dropped_fake_symbol": "GhostSymbol" not in metadata_blob,
        "redacted_metadata": bool(secret) and secret not in metadata_blob and "gh*_[REDACTED]" in metadata_blob,
        "redacted_surface": bool(secret) and secret not in retrieval_text and "gh*_[REDACTED]" in retrieval_text,
        "surface_signal": "Sources/Auth/ShareLinkBuilder.swift" in retrieval_text and "ShareLinkBuilder" in retrieval_text,
        "surface_capped": len(retrieval_text) <= 1500,
        "chunk_shape": decision_chunk.get("reason") and decision_chunk.get("files") == ["Sources/Auth/ShareLinkBuilder.swift"],
    }
    case.metrics = checks | {"result": result, "err": err[:120]}
    case.passed = all(checks.values())
    case.detail = (
        f"rows={len(rows)} file={checks['kept_real_file']} "
        f"redacted={checks['redacted_surface']}"
    )
    if not case.passed:
        case.detail += f" err={err[:120]}"


def tc_27_stop_session_and_flat_extract(env: dict, home: str, case: CaseResult) -> None:
    """Stop stores session_id metadata and flat extract excludes rich decision types."""
    env_h = codex_hook_env(env)
    stop_input = json.dumps(
        {
            "hook_event_name": "Stop",
            "last_assistant_message": "결정: A 대신 B로 바꿉니다. 수정: 테스트 명령을 고쳤습니다.",
            "session_id": "tc27-session",
        },
        ensure_ascii=False,
    )
    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/stop.sh"], input_text=stop_input)
    rows = db_query(
        home,
        """
        SELECT json_extract(metadata_json, '$.session_id'), text_clean
        FROM events
        WHERE kind = 'llm_response'
          AND text_clean LIKE '%A 대신 B%'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
    )
    code = """
import json, sys
sys.path.insert(0, %r)
import ingestion

def fake_model(_prompt, **_kwargs):
    return json.dumps([
        {"chunk_type": "decision", "text": "B안으로 바꾼다.", "keywords": ["B안"]},
        {"chunk_type": "fix", "text": "테스트 명령을 고쳤다.", "keywords": ["테스트"]},
    ], ensure_ascii=False)

ingestion.run_background_model = fake_model
print(json.dumps({
    "flat": ingestion.extract_chunks_from_response("결정과 수정이 함께 있음", mode="flat"),
    "rich": ingestion.extract_chunks_from_response("결정과 수정이 함께 있음", mode="rich"),
}, ensure_ascii=False))
""" % (str(LIB_DIR),)
    rc_py, out, err_py = run_python(env, code)
    parsed = json.loads(out) if out else {}
    flat_types = [c.get("chunk_type") for c in parsed.get("flat") or []]
    rich_types = [c.get("chunk_type") for c in parsed.get("rich") or []]
    checks = {
        "stop_ok": rc == 0,
        "session_metadata": bool(rows and rows[0][0] == "tc27-session"),
        "flat_excludes_decision": flat_types == ["fix"],
        "rich_excludes_fix": rich_types == ["decision"],
        "py_ok": rc_py == 0,
    }
    case.metrics = checks | {"flat": flat_types, "rich": rich_types, "err": (err or err_py)[:120]}
    case.passed = all(checks.values())
    case.detail = f"session={rows[0][0] if rows else None} flat={flat_types} rich={rich_types}"


def tc_28_rollup_session_cursor(env: dict, home: str, case: CaseResult) -> None:
    """Rollup creates rich entries once and cursor prevents duplicate reruns."""
    code = """
import json, sqlite3, sys
sys.path.insert(0, %r)
import ingestion
from retrieval import rollup
from retrieval.retrieve import retrieve

def fake_model(_prompt, **_kwargs):
    return json.dumps([
        {
            "chunk_type": "decision",
            "text": "공유 링크 구현은 B안인 ShareLinkBuilder로 분리한다.",
            "keywords": ["ShareLinkBuilder", "B안", "공유 링크"],
            "reason": "A안은 LoginViewModel 책임이 커져서 폐기했다.",
            "files": ["Sources/Auth/ShareLinkBuilder.swift"],
            "symbols": ["ShareLinkBuilder"],
            "tests": ["pytest tests/test_share_link.py"],
        }
    ], ensure_ascii=False)

ingestion.run_background_model = fake_model
with ingestion.db() as conn:
    rows = [
        ("tc28-01", "user_message", "처음엔 LoginViewModel에 공유 링크를 넣는 A안으로 갈까요?", "2026-05-24T01:00:00Z"),
        ("tc28-02", "llm_response", "A안은 가능하지만 LoginViewModel 책임이 커집니다.", "2026-05-24T01:01:00Z"),
        ("tc28-03", "user_message", "책임이 커지면 별도 builder가 낫지 않나요?", "2026-05-24T01:02:00Z"),
        ("tc28-04", "llm_response", "결정: Sources/Auth/ShareLinkBuilder.swift의 ShareLinkBuilder로 B안 분리합니다. pytest tests/test_share_link.py로 검증합니다.", "2026-05-24T01:03:00Z"),
    ]
    for event_id, kind, text, created_at in rows:
        conn.execute(
            "INSERT INTO events (id, project_id, source, kind, text_clean, metadata_json, noise, created_at) "
            "VALUES (?, ?, 'eval', ?, ?, ?, 0, ?)",
            (event_id, %r, kind, text, json.dumps({"session_id": "tc28-session"}, ensure_ascii=False), created_at),
        )
    conn.commit()

first = rollup.rollup_session(%r, "tc28-session", all_batches=True).to_dict()
second = rollup.rollup_session(%r, "tc28-session", all_batches=True).to_dict()
with ingestion.db() as conn:
    entries = conn.execute(
        "SELECT raw_type, text, retrieval_text, metadata_json FROM search_entries "
        "WHERE project_id = ? AND json_extract(metadata_json, '$.session_id') = 'tc28-session'",
        (%r,),
    ).fetchall()
    state = conn.execute(
        "SELECT last_event_id FROM extract_state WHERE project_id = ? AND session_id = 'tc28-session'",
        (%r,),
    ).fetchone()
result = retrieve("ShareLinkBuilder 왜 B안", %r, top_k=5)
haystack = "\\n".join([c.text + "\\n" + c.retrieval_text for c in result.candidates])
print(json.dumps({
    "first": first,
    "second": second,
    "entries": [
        {"raw_type": r[0], "text": r[1], "retrieval_text": r[2], "metadata": json.loads(r[3] or "{}")}
        for r in entries
    ],
    "state": state[0] if state else None,
    "haystack": haystack,
}, ensure_ascii=False))
""" % (str(LIB_DIR), PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID)
    rc, out, err = run_python(env, code)
    parsed = json.loads(out) if out else {}
    entries = parsed.get("entries") or []
    blob = json.dumps(entries, ensure_ascii=False)
    haystack = parsed.get("haystack") or ""
    checks = {
        "ok": rc == 0,
        "first_inserted": (parsed.get("first") or {}).get("entries_inserted") == 1,
        "second_noop": (parsed.get("second") or {}).get("events_processed") == 0,
        "one_entry": len(entries) == 1,
        "cursor_last": parsed.get("state") == "tc28-04",
        "metadata_range": "tc28-01" in blob and "tc28-04" in blob,
        "search_recovers": "ShareLinkBuilder" in haystack and "A안은 LoginViewModel 책임" in haystack,
    }
    case.metrics = checks | {"parsed": parsed, "err": err[:160]}
    case.passed = all(checks.values())
    case.detail = (
        f"inserted={(parsed.get('first') or {}).get('entries_inserted')} "
        f"second={(parsed.get('second') or {}).get('events_processed')} entries={len(entries)}"
    )
    if not case.passed:
        case.detail += f" err={err[:120]}"


def tc_29_rollup_stale_and_bounded(env: dict, home: str, case: CaseResult) -> None:
    """Stale session selection excludes current session and bounded batches advance cursor."""
    code = """
import json, sys
sys.path.insert(0, %r)
import ingestion
from retrieval import rollup

def fake_model(_prompt, **_kwargs):
    return json.dumps([
        {"chunk_type": "summary", "text": "bounded batch 요약", "keywords": ["bounded"]}
    ], ensure_ascii=False)

ingestion.run_background_model = fake_model
with ingestion.db() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO projects VALUES (?, ?, ?, ?, ?)",
        (%r, %r, "root", "2026-05-24", "2026-05-24"),
    )
    events = [
        ("tc29-old-1", "tc29-old", "user_message", "오래된 세션 1", "2020-01-01T01:00:00Z"),
        ("tc29-old-2", "tc29-old", "llm_response", "오래된 세션 2", "2020-01-01T01:01:00Z"),
        ("tc29-current-1", "tc29-current", "user_message", "현재 세션", "2020-01-01T01:00:00Z"),
        ("tc29-fresh-1", "tc29-fresh", "user_message", "최신 세션", "2999-01-01T00:00:00Z"),
        ("tc29-b-1", "tc29-bounded", "user_message", "bounded 1", "2026-05-24T02:00:00Z"),
        ("tc29-b-2", "tc29-bounded", "llm_response", "bounded 2", "2026-05-24T02:01:00Z"),
        ("tc29-b-3", "tc29-bounded", "user_message", "bounded 3", "2026-05-24T02:02:00Z"),
    ]
    for event_id, session_id, kind, text, created_at in events:
        conn.execute(
            "INSERT INTO events (id, project_id, source, kind, text_clean, metadata_json, noise, created_at) "
            "VALUES (?, ?, 'eval', ?, ?, ?, 0, ?)",
            (event_id, %r, kind, text, json.dumps({"session_id": session_id}, ensure_ascii=False), created_at),
        )
    conn.execute(
        "INSERT INTO events (id, project_id, source, kind, text_clean, metadata_json, noise, created_at) "
        "VALUES ('tc29-root-1', ?, 'eval', 'llm_response', 'root stale session', ?, 0, '2020-01-01T01:00:00Z')",
        (%r, json.dumps({"session_id": "tc29-root"}, ensure_ascii=False)),
    )
    conn.commit()

stale = rollup.stale_sessions(%r, exclude_session="tc29-current", stale_minutes=30, max_sessions=10)
first = rollup.rollup_session(%r, "tc29-bounded", batch_events=2, max_chars=120).to_dict()
second = rollup.rollup_session(%r, "tc29-bounded", batch_events=2, max_chars=120).to_dict()
print(json.dumps({"stale": stale, "first": first, "second": second}, ensure_ascii=False))
""" % (str(LIB_DIR), ROOT_PROJECT_ID, str(ROOT), PROJECT_ID, ROOT_PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID)
    rc, out, err = run_python(env, code)
    parsed = json.loads(out) if out else {}
    env_cli = dict(env)
    env_cli["IMPRINT_CODEX_BIN"] = make_fake_codex(home)
    rc_script, out_script, err_script = run_cmd(
        env_cli,
        ["bash", "scripts/imprint/rollup.sh", "--stale", "--exclude-session", "tc29-current", "--json"],
    )
    try:
        script_json = json.loads(out_script) if out_script else {}
    except json.JSONDecodeError:
        script_json = {}
    stale = parsed.get("stale") or []
    checks = {
        "ok": rc == 0,
        "old_selected": "tc29-old" in stale,
        "current_excluded": "tc29-current" not in stale,
        "fresh_excluded": "tc29-fresh" not in stale,
        "first_batch_two": (parsed.get("first") or {}).get("events_processed") == 2,
        "second_batch_one": (parsed.get("second") or {}).get("events_processed") == 1,
        "script_ok": (
            rc_script == 0
            and script_json.get("project_id") == ROOT_PROJECT_ID
            and "tc29-root" in (script_json.get("sessions") or [])
        ),
    }
    case.metrics = checks | {"parsed": parsed, "script": script_json, "err": (err or err_script)[:160]}
    case.passed = all(checks.values())
    case.detail = (
        f"stale={stale} first={(parsed.get('first') or {}).get('events_processed')} "
        f"second={(parsed.get('second') or {}).get('events_processed')} script={rc_script}"
    )
    if not case.passed:
        case.detail += f" err={err[:120]}"


def tc_30_rollup_extract_without_write_lock(env: dict, home: str, case: CaseResult) -> None:
    """Slow rollup extraction must not hold a DB write lock."""
    code = """
import json, os, sqlite3, sys, threading, time
from pathlib import Path
sys.path.insert(0, %r)
import ingestion
from retrieval import rollup

entered = threading.Event()
release = threading.Event()

def slow_extract(_text, *, mode="rich"):
    entered.set()
    release.wait(timeout=3)
    return [
        {"chunk_type": "summary", "text": "느린 rollup 요약", "keywords": ["slow", "rollup"]}
    ]

ingestion.extract_chunks_from_response = slow_extract
with ingestion.db() as conn:
    rows = [
        ("tc30-01", "user_message", "느린 rollup 시작", "2026-05-24T03:00:00Z"),
        ("tc30-02", "llm_response", "느린 rollup 응답", "2026-05-24T03:01:00Z"),
    ]
    for event_id, kind, text, created_at in rows:
        conn.execute(
            "INSERT INTO events (id, project_id, source, kind, text_clean, metadata_json, noise, created_at) "
            "VALUES (?, ?, 'eval', ?, ?, ?, 0, ?)",
            (event_id, %r, kind, text, json.dumps({"session_id": "tc30-rollup"}, ensure_ascii=False), created_at),
        )
    conn.commit()

result = {}

def worker():
    try:
        result["stats"] = rollup.rollup_session_once(%r, "tc30-rollup").to_dict()
    except Exception as exc:
        result["error"] = repr(exc)

t = threading.Thread(target=worker)
t.start()
entered_ok = entered.wait(timeout=2)
writer_ok = False
writer_err = ""
try:
    db_path = Path(os.environ["IMPRINT_HOME"]) / "app.sqlite"
    conn = sqlite3.connect(str(db_path), timeout=0.1)
    conn.execute("PRAGMA busy_timeout = 100")
    conn.execute(
        "INSERT INTO events (id, project_id, source, kind, text_clean, metadata_json, noise, created_at) "
        "VALUES ('tc30-writer', ?, 'eval', 'user_message', 'concurrent writer', '{}', 0, '2026-05-24T03:01:30Z')",
        (%r,),
    )
    conn.commit()
    writer_ok = True
except Exception as exc:
    writer_err = repr(exc)
finally:
    try:
        conn.close()
    except Exception:
        pass
    release.set()
    t.join(timeout=4)

with ingestion.db() as conn:
    writer_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE id = 'tc30-writer'"
    ).fetchone()[0]
print(json.dumps({
    "entered_ok": entered_ok,
    "writer_ok": writer_ok,
    "writer_err": writer_err,
    "writer_count": writer_count,
    "worker": result,
}, ensure_ascii=False))
""" % (str(LIB_DIR), PROJECT_ID, PROJECT_ID, PROJECT_ID)
    rc, out, err = run_python(env, code)
    parsed = json.loads(out) if out else {}
    worker = parsed.get("worker") or {}
    stats = worker.get("stats") or {}
    checks = {
        "ok": rc == 0,
        "entered": parsed.get("entered_ok") is True,
        "writer_ok": parsed.get("writer_ok") is True,
        "writer_persisted": parsed.get("writer_count") == 1,
        "worker_ok": not worker.get("error") and stats.get("entries_inserted") == 1,
    }
    case.metrics = checks | {"parsed": parsed, "err": err[:160]}
    case.passed = all(checks.values())
    case.detail = (
        f"writer={parsed.get('writer_ok')} entries={stats.get('entries_inserted')} "
        f"err={parsed.get('writer_err') or worker.get('error') or ''}"
    )


def tc_15_first_turn_working_overlay(env: dict, home: str, case: CaseResult) -> None:
    """UserPromptSubmit sync mini-chunk + prefill/search working overlay."""
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
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 0)
            """,
            (
                "tc15-retrieved",
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
            SELECT id, 'raw_turn' AS raw_type, text_clean AS text, metadata_json
            FROM events
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
            ORDER BY created_at
            """,
            (ROOT_PROJECT_ID,),
        ).fetchall()
        noise_working = conn.execute(
            """
            SELECT COUNT(*)
            FROM events
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
              AND text_clean LIKE '%응%'
            """,
            (ROOT_PROJECT_ID,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT OR REPLACE INTO source_documents
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
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_document_id, chunk_index, section_path, text,
               retrieval_text, raw_type, normalized_type,
               source_updated_at, valid_from, is_current, created_at)
            VALUES (?, ?, ?, 0, 'TC15', ?, ?, 'spec', 'spec', ?, ?, 1, ?)
            """,
            (
                "tc15-entry",
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
    entry_ids = {c.get("entry_id") for c in candidates}
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
            and md.get("source_type") == "chat"
            and md.get("evidence_level") == "raw_turn"
            and md.get("grounded") is False
            and md.get("need_retrieval") is True
        )
        rewrite_ok = (
            "onclick" in (md.get("query_rewrite") or "")
            and len(md.get("query_surfaces") or []) >= 2
        )

    checks = {
        "ups": rc_ups == 0,
        "working_chunk": working_ok,
        "rewrite": rewrite_ok,
        "prefill_working": (
            "[Query context]" in ups_out
            and "[working] A 버튼 클릭 동작 알려줘" in ups_out
        ),
        "prefill_retrieved": "테스트 모드" in ups_out,
        "noise_no_working": rc_noise == 0 and noise_working == 0,
        "retrieve_union_working": any(c.get("source_type") == "working" for c in candidates),
        "retrieve_keeps_search_entries": "tc15-entry" in entry_ids,
    }
    case.metrics = checks | {
        "working_rows": len(working_rows),
        "retrieved": len(candidates),
    }
    case.passed = all(checks.values())
    case.detail = (
        f"working={len(working_rows)} prefill={checks['prefill_working']}/{checks['prefill_retrieved']} "
        f"retrieve={len(candidates)} union={checks['retrieve_union_working']} entry={checks['retrieve_keeps_search_entries']}"
    )
    if not case.passed and ups_err:
        case.detail += f" ups_err={ups_err[:120]}"


def tc_16_context_section_policy(env: dict, home: str, case: CaseResult) -> None:
    """working metadata/gate/provenance + low-confidence trace policy."""
    env_h = hook_env(env)
    env_h["IMPRINT_CLAUDE_BIN"] = make_fake_claude(home)
    env_h["IMPRINT_WORKING_TTL_HOURS"] = "1"
    env_h["IMPRINT_WORKING_MAX_PER_SESSION"] = "2"
    rc, _, err = run_cmd(env_h, ["bash", "scripts/imprint/session-start.sh"])
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    now = "2026-05-16T00:00:00Z"
    old = "2026-05-15T00:00:00Z"
    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        for idx, created in enumerate([old, now, now, now]):
            conn.execute(
                """
                INSERT OR REPLACE INTO search_entries
                  (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
                VALUES (?, ?, NULL, 'raw_turn', ?, ?, ?, 0)
                """,
                (
                    f"tc16-working-{idx}",
                    ROOT_PROJECT_ID,
                    f"tc16 working {idx}",
                    json.dumps({
                        "memory_tier": "working",
                        "memory_kind": "raw_turn",
                        "session_visible": True,
                        "session_id": "tc16-clean",
                    }),
                    created,
                ),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
            VALUES ('tc16-persistent-keep', ?, NULL, 'decision', 'persistent memory 유지', '{}', ?, 0)
            """,
            (ROOT_PROJECT_ID, old),
        )
        conn.commit()
    finally:
        conn.close()

    cleanup_input = json.dumps({"prompt": "A 버튼 클릭 동작 알려줘", "session_id": "tc16-clean"}, ensure_ascii=False)
    rc_clean, _, _ = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=cleanup_input,
    )
    gate_input = json.dumps({"prompt": "PR 올려줘", "session_id": "tc16-gate"}, ensure_ascii=False)
    rc_gate, gate_out, _ = run_cmd(
        env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=gate_input,
    )

    code = """
import sys; sys.path.insert(0, %r)
from ingestion import db, insert_external_chunk, insert_extracted_chunk, insert_source_status_chunk
with db() as conn:
    insert_external_chunk(conn, %r, 'spec', '외부 원문 근거', {'source':'notion','url':'https://notion.so/tc16'})
    insert_extracted_chunk(conn, %r, None, 'decision', 'assistant 추출 근거', ['assistant'])
    insert_source_status_chunk(conn, %r, source='slack', status='fetch_failed', text='slack failed', metadata={'url':'https://x.slack.com/archives/C/p1'})
    conn.commit()
""" % (str(LIB_DIR), ROOT_PROJECT_ID, ROOT_PROJECT_ID, ROOT_PROJECT_ID)
    rc_prov, _, err_prov = run_python(env, code)

    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        working_clean_count = conn.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.memory_tier') = 'working'
              AND json_extract(metadata_json, '$.session_id') = 'tc16-clean'
            """,
            (ROOT_PROJECT_ID,),
        ).fetchone()[0]
        persistent_keep = conn.execute(
            "SELECT COUNT(*) FROM search_entries WHERE id = 'tc16-persistent-keep'",
        ).fetchone()[0]
        gate_md_raw = conn.execute(
            """
            SELECT metadata_json FROM events
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.session_id') = 'tc16-gate'
            ORDER BY created_at DESC LIMIT 1
            """,
            (ROOT_PROJECT_ID,),
        ).fetchone()
        provenance_rows = conn.execute(
            """
            SELECT raw_type, origin, source_document_id, metadata_json FROM search_entries
            WHERE text IN ('외부 원문 근거', 'assistant 추출 근거', 'slack failed')
            ORDER BY raw_type
            """
        ).fetchall()
        conn.execute(
            """
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
            VALUES ('tc16-primary', ?, NULL, 'decision', '청운 플래그는 primary entry에서 확인합니다.', '{}', ?, 0)
            """,
            (PROJECT_ID, now),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO search_entries
              (id, project_id, source_event_id, raw_type, text, metadata_json, created_at, pinned)
            VALUES ('tc16-working-low', ?, NULL, 'raw_turn', '청운 플래그 알려줘', ?, ?, 0)
            """,
            (
                PROJECT_ID,
                json.dumps({
                    "memory_tier": "working",
                    "memory_kind": "raw_turn",
                    "session_visible": True,
                    "session_id": "tc16-low",
                }),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    gate_md = json.loads(gate_md_raw[0]) if gate_md_raw else {}
    provenance = []
    origins = {}
    for ctype, origin, source_document_id, md_raw in provenance_rows:
        origins[ctype] = {"origin": origin, "source_document_id": source_document_id}
        try:
            provenance.append(json.loads(md_raw))
        except json.JSONDecodeError:
            provenance.append({})

    env_r = dict(env)
    env_r["IMPRINT_SESSION_ID"] = "tc16-low"
    low = _retrieve_plain_json(env_r, "청운 플래그 알려줘")
    low_chunks = low.get("candidates") or []
    low_text = "\n".join(c.get("text", "") for c in low_chunks)

    checks = {
        "cleanup": rc_clean == 0 and working_clean_count >= 1 and persistent_keep == 1,
        "gate": (
            rc_gate == 0
            and gate_md.get("need_retrieval") is False
            and "retrieved-memory search skipped" in gate_out
        ),
        "provenance": (
            rc_prov == 0
            and any(p.get("evidence_level") == "raw_source" and p.get("grounded") is True and p.get("source_uri") for p in provenance)
            and any(p.get("evidence_level") == "assistant_extracted" and p.get("source_type") == "chat" for p in provenance)
            and any(p.get("evidence_level") == "status_marker" and p.get("grounded") is False for p in provenance)
        ),
        "origin_invariant": (
            origins.get("spec", {}).get("origin") == "external_fetch"
            and origins.get("spec", {}).get("source_document_id") is None
            and origins.get("source_status", {}).get("origin") == "source_status"
            and origins.get("decision", {}).get("origin") == "assistant_extract"
        ),
        "low_conf_trace": (
            (low.get("trace") or {}).get("fallback_triggered") is False
            and "primary entry" in low_text
        ),
    }
    case.metrics = checks | {
        "working_clean_count": working_clean_count,
        "low_chunks": len(low_chunks),
    }
    case.passed = all(checks.values())
    case.detail = (
        f"cleanup={checks['cleanup']} gate={checks['gate']} "
        f"provenance={checks['provenance']} origin={checks['origin_invariant']} "
        f"low_trace={checks['low_conf_trace']}"
    )
    if not case.passed and err_prov:
        case.detail += f" prov_err={err_prov[:120]}"


def tc_17_observability_dedup_status(env: dict, home: str, case: CaseResult) -> None:
    """retrieve trace JSON + text_hash dedup + /memory status."""
    env_p = dict(env)
    env_p["IMPRINT_PROFILE"] = "1"
    code = """
import sys; sys.path.insert(0, %r)
from ingestion import db, insert_external_chunk, insert_extracted_chunk
from ingestion import now_iso
with db() as conn:
    conn.execute(
        "INSERT OR REPLACE INTO events "
        "(id, project_id, conversation_id, source, kind, text_clean, metadata_json, noise, created_at) "
        "VALUES ('tc17-event', %r, NULL, 'test', 'llm_response', 'assistant', '{}', 0, ?)",
        (now_iso(),),
    )
    insert_external_chunk(conn, %r, 'spec', '관측 원문 근거', {'source':'notion','url':'https://notion.so/tc17'})
    insert_external_chunk(conn, %r, 'spec', '관측 원문 근거', {'source':'notion','url':'https://notion.so/tc17'})
    insert_extracted_chunk(conn, %r, 'tc17-event', 'decision', '관측 플래그는 dedup entry에서 확인합니다.', ['관측'])
    insert_extracted_chunk(conn, %r, 'tc17-event', 'decision', '관측 플래그는 dedup entry에서 확인합니다.', ['관측'])
    conn.commit()
""" % (str(LIB_DIR), PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID)
    rc_setup, _, err_setup = run_python(env_p, code)

    conn = sqlite3.connect(str(Path(home) / "app.sqlite"))
    try:
        external_count = conn.execute(
            """
            SELECT COUNT(*) FROM search_entries
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.source_uri') = 'https://notion.so/tc17'
            """,
            (PROJECT_ID,),
        ).fetchone()[0]
        extracted_count = conn.execute(
            """
            SELECT COUNT(*) FROM search_entries
            WHERE project_id = ? AND source_event_id = 'tc17-event'
            """,
            (PROJECT_ID,),
        ).fetchone()[0]
    finally:
        conn.close()

    plain = _retrieve_plain_json(env_p, "관측 플래그 알려줘")
    routed = _retrieve_json(env_p, "관측 플래그 알려줘")
    trace = plain.get("trace") or {}
    candidates = plain.get("candidates") or []
    assistant_candidate = next(
        (c for c in candidates if c.get("evidence_level") == "assistant_extracted"),
        {},
    )
    routed_trace = routed.get("trace") or {}

    rc_status, status_out, status_err = run_cmd(
        env_p, ["bash", "scripts/imprint/memory.sh", "status", "--json"],
    )
    try:
        status_json = json.loads(status_out) if status_out else {}
    except json.JSONDecodeError:
        status_json = {}

    profile_path = Path(home) / "profile.jsonl"
    profile_text = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""

    checks = {
        "dedup": rc_setup == 0 and external_count == 1 and extracted_count == 1,
        "trace": (
            bool(trace.get("query_surfaces"))
            and isinstance(trace.get("fallback_triggered"), bool)
            and isinstance(trace.get("fallback_reasons"), list)
            and bool(trace.get("rerank_gate_reason"))
        ),
        "candidate_meta": (
            assistant_candidate.get("context_section") == "retrieved_memory"
            and assistant_candidate.get("text_hash")
            and isinstance(assistant_candidate.get("penalties"), list)
        ),
        "routed_trace": bool(routed_trace.get("query_surfaces")),
        "status": rc_status == 0 and (status_json.get("db") or {}).get("ok") is True,
        "profile": "retrieve_done" in profile_text,
    }
    case.metrics = checks | {
        "external_count": external_count,
        "extracted_count": extracted_count,
        "fallback_reasons": trace.get("fallback_reasons"),
        "status_rc": rc_status,
    }
    case.passed = all(checks.values())
    case.detail = (
        f"dedup={checks['dedup']} trace={checks['trace']} "
        f"candidate_meta={checks['candidate_meta']} status={checks['status']}"
    )
    if not case.passed:
        extra = err_setup or status_err or plain.get("_error") or routed.get("_error")
        if extra:
            case.detail += f" err={str(extra)[:160]}"


def tc_18_codex_hook_io(env: dict, home: str, case: CaseResult) -> None:
    """Codex hook JSON output + compact Guardrail + last_assistant_message Stop 경로."""
    env_h = codex_hook_env(env)
    env_h["IMPRINT_CODEX_BIN"] = make_fake_codex(home)

    rc, session_out, err = run_cmd(
        env_h,
        ["bash", "scripts/imprint/session-start.sh"],
        input_text=json.dumps({"hook_event_name": "SessionStart"}, ensure_ascii=False),
    )
    if rc != 0:
        case.passed = False
        case.detail = f"session-start rc={rc} err={err[:120]}"
        return

    rc, compact_out, err = run_cmd(
        env_h,
        ["bash", "scripts/imprint/session-start.sh"],
        input_text=json.dumps(
            {"hook_event_name": "SessionStart", "matcher": "compact"},
            ensure_ascii=False,
        ),
    )
    if rc != 0:
        case.passed = False
        case.detail = f"compact session-start rc={rc} err={err[:120]}"
        return

    with tempfile.TemporaryDirectory(prefix="imprint-guardrail-project-") as project_tmp:
        legacy_dir = Path(project_tmp) / ".imprint"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "soul.md").write_text("legacy guardrail 문구", encoding="utf-8")
        env_legacy = dict(env_h)
        env_legacy.pop("IMPRINT_NO_SEED", None)
        legacy_proc = subprocess.run(
            ["bash", str(ROOT / "scripts" / "imprint" / "session-start.sh")],
            input=json.dumps({"hook_event_name": "SessionStart"}, ensure_ascii=False),
            env=env_legacy,
            capture_output=True,
            text=True,
            cwd=project_tmp,
        )
        legacy_guardrail = legacy_dir / "Guardrail.md"
        legacy_migrated = (
            legacy_proc.returncode == 0
            and legacy_guardrail.exists()
            and legacy_guardrail.read_text(encoding="utf-8") == "legacy guardrail 문구"
        )

    ups_input = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "A 버튼 클릭 동작 알려줘",
            "session_id": "codex-session",
        },
        ensure_ascii=False,
    )
    rc, ups_out, err = run_cmd(env_h, ["bash", "scripts/imprint/user-prompt-submit.sh"], input_text=ups_input)
    if rc != 0:
        case.passed = False
        case.detail = f"ups rc={rc} err={err[:120]}"
        return

    stop_input = json.dumps(
        {
            "hook_event_name": "Stop",
            "last_assistant_message": "A 버튼 클릭은 테스트 모드를 시작합니다.",
        },
        ensure_ascii=False,
    )
    rc, stop_out, err = run_cmd(env_h, ["bash", "scripts/imprint/stop.sh"], input_text=stop_input)
    if rc != 0:
        case.passed = False
        case.detail = f"stop rc={rc} err={err[:120]}"
        return

    try:
        session_json = json.loads(session_out)
        ups_json = json.loads(ups_out)
        stop_json = json.loads(stop_out)
        legacy_json = json.loads(legacy_proc.stdout)
    except json.JSONDecodeError as exc:
        case.passed = False
        case.detail = f"json parse failed: {exc}"
        return

    session_ctx = session_json.get("hookSpecificOutput", {}).get("additionalContext", "")
    compact_json = json.loads(compact_out)
    compact_ctx = compact_json.get("hookSpecificOutput", {}).get("additionalContext", "")
    legacy_ctx = legacy_json.get("hookSpecificOutput", {}).get("additionalContext", "")
    ups_ctx = ups_json.get("hookSpecificOutput", {}).get("additionalContext", "")
    rows = db_query(
        home,
        "SELECT kind, text_clean FROM events "
        "WHERE kind='llm_response' AND source='codex' "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
    )
    case.metrics = {
        "session_json": bool(session_ctx),
        "compact_guardrail": bool(compact_ctx),
        "legacy_guardrail": legacy_migrated and "legacy guardrail 문구" in legacy_ctx,
        "ups_json": bool(ups_ctx),
        "stop_continue": stop_json.get("continue"),
        "llm_response": len(rows),
    }
    case.passed = (
        "[imprint Guardrail" in session_ctx
        and "[imprint Guardrail" in compact_ctx
        and case.metrics["legacy_guardrail"]
        and "[Project memory context]" in ups_ctx
        and stop_json.get("continue") is True
        and len(rows) == 1
        and "테스트 모드" in rows[0][1]
    )
    case.detail = (
        f"session_json={bool(session_ctx)} compact={bool(compact_ctx)} "
        f"legacy={case.metrics['legacy_guardrail']} ups_json={bool(ups_ctx)} "
        f"stop_continue={stop_json.get('continue')} llm_response={len(rows)}"
    )


def tc_19_legacy_db_migration(env: dict, home: str, case: CaseResult) -> None:
    """새 기본 DB가 비어 있으면 ~/.claude/imprint/app.sqlite 에서 1회 migration."""

    def seed_db(path: Path, entry_id: str, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.executescript(SCHEMA_PATH.read_text())
        conn.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            ("legacy_project", "/legacy", "legacy", "2026-05-01", "2026-05-01"),
        )
        conn.execute(
            "INSERT INTO search_entries "
            "(id, project_id, raw_type, text, metadata_json, created_at, pinned) "
            "VALUES (?, ?, 'decision', ?, '{}', '2026-05-01T00:00:00Z', 0)",
            (entry_id, "legacy_project", text),
        )
        conn.commit()
        conn.close()

    with tempfile.TemporaryDirectory(prefix="imprint-migrate-") as tmp:
        tmp_home = Path(tmp)
        old_db = tmp_home / ".claude" / "imprint" / "app.sqlite"
        new_db = tmp_home / ".imprint" / "app.sqlite"
        seed_db(old_db, "legacy_chunk", "legacy 데이터")

        env_m = dict(os.environ)
        env_m["HOME"] = str(tmp_home)
        env_m["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
        env_m["IMPRINT_NO_SEED"] = "1"
        env_m.pop("IMPRINT_HOME", None)
        rc, _, err = run_cmd(env_m, ["bash", "scripts/imprint/session-start.sh"], input_text="{}")
        if rc != 0:
            case.passed = False
            case.detail = f"migration session-start rc={rc} err={err[:120]}"
            return
        conn = sqlite3.connect(str(new_db))
        try:
            migrated_rows = conn.execute(
                "SELECT id, text FROM search_entries WHERE id='legacy_chunk'"
            ).fetchall()
        finally:
            conn.close()
        legacy_removed = not old_db.exists()

    with tempfile.TemporaryDirectory(prefix="imprint-migrate-keep-") as tmp:
        tmp_home = Path(tmp)
        old_db = tmp_home / ".claude" / "imprint" / "app.sqlite"
        new_db = tmp_home / ".imprint" / "app.sqlite"
        seed_db(old_db, "old_chunk", "old 데이터")
        seed_db(new_db, "new_chunk", "new 데이터")

        env_m = dict(os.environ)
        env_m["HOME"] = str(tmp_home)
        env_m["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
        env_m["IMPRINT_NO_SEED"] = "1"
        env_m.pop("IMPRINT_HOME", None)
        rc, _, err = run_cmd(env_m, ["bash", "scripts/imprint/session-start.sh"], input_text="{}")
        if rc != 0:
            case.passed = False
            case.detail = f"no-overwrite session-start rc={rc} err={err[:120]}"
            return
        conn = sqlite3.connect(str(new_db))
        try:
            kept_new = conn.execute(
                "SELECT COUNT(*) FROM search_entries WHERE id='new_chunk'"
            ).fetchone()[0]
            copied_old = conn.execute(
                "SELECT COUNT(*) FROM search_entries WHERE id='old_chunk'"
            ).fetchone()[0]
        finally:
            conn.close()
        legacy_kept_when_new_has_data = old_db.exists()

    case.metrics = {
        "migrated": len(migrated_rows),
        "legacy_removed": legacy_removed,
        "kept_new": kept_new,
        "copied_old_when_new_has_data": copied_old,
        "legacy_kept_when_new_has_data": legacy_kept_when_new_has_data,
    }
    case.passed = (
        len(migrated_rows) == 1
        and migrated_rows[0][1] == "legacy 데이터"
        and legacy_removed
        and kept_new == 1
        and copied_old == 0
        and legacy_kept_when_new_has_data
    )
    case.detail = (
        f"migrated={len(migrated_rows)} legacy_removed={legacy_removed} "
        f"kept_new={kept_new} copied_old_when_new_has_data={copied_old}"
    )


# -----------------------------------------------------------------------------
# 러너
# -----------------------------------------------------------------------------

CASES: list[tuple[str, str, callable]] = [
    ("TC-01", "Save 짧은 텍스트", tc_01_save_short),
    ("TC-02", "Save 긴 문서 (다중 chunk)", tc_02_save_long),
    ("TC-03", "Search 짧은 쿼리 (local)", tc_03_retrieve_short),
    ("TC-04", "Search 긴 쿼리 (feature)", tc_04_retrieve_feature),
    ("TC-05", "Search global 쿼리", tc_05_retrieve_global),
    ("TC-06", "Entity alias 매칭", tc_06_entity_alias),
    ("TC-07", "Document 갱신 + supersede", tc_07_supersede),
    ("TC-08", "Contradiction 감지 (model judge)", tc_08_contradiction_llm),
    ("TC-09", "요청 중간 중단 (timeout)", tc_09_interruption_timeout),
    ("TC-10", "동시 ingest priority drain", tc_10_priority_drain),
    ("TC-11", "Hook memory loop + redaction", tc_11_hook_memory_loop),
    ("TC-12", "Memory search/list/inject fixture", tc_12_memory_search_fixture),
    ("TC-13", "Source status + noise + profile", tc_13_source_noise_profile),
    ("TC-14", "Search search_entries primary", tc_14_retrieve_search_entries_primary),
    ("TC-15", "First-turn working overlay", tc_15_first_turn_working_overlay),
    ("TC-16", "RAG context section policy", tc_16_context_section_policy),
    ("TC-17", "Observability dedup status", tc_17_observability_dedup_status),
    ("TC-18", "Codex hook JSON I/O", tc_18_codex_hook_io),
    ("TC-19", "Legacy DB 자동 migration", tc_19_legacy_db_migration),
    ("TC-20", "Legacy migration/backfill", tc_20_legacy_migration_backfill),
    ("TC-21", "Search skill dispatcher", tc_21_search_skill_dispatcher),
    ("TC-22", "Remember skill dispatcher", tc_22_remember_skill_dispatcher),
    ("TC-23", "Setup vector progress logging", tc_23_setup_vector_logging),
    ("TC-24", "Extract eval harness", tc_24_extract_eval_harness),
    ("TC-25", "Retrieval text override", tc_25_retrieval_text_override),
    ("TC-26", "Decision-rich extract", tc_26_decision_rich_extract),
    ("TC-27", "Stop session + flat extract", tc_27_stop_session_and_flat_extract),
    ("TC-28", "Rollup session cursor", tc_28_rollup_session_cursor),
    ("TC-29", "Rollup stale/bounded", tc_29_rollup_stale_and_bounded),
    ("TC-30", "Rollup extract without write lock", tc_30_rollup_extract_without_write_lock),
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
