"""contradiction detection — 후보 생성 + NLI 판정 + model judge fallback + 3구간 분기.

판정 우선순위 (명세):
  1) 로컬 NLI (mDeBERTa-v3-base-mnli-xnli) — 500ms timeout
  2) NLI 실패/timeout 또는 mid confidence (0.4~0.6) → model judge
  3) 둘 다 실패/timeout → status=candidate 로 저장해 다음 배치에서 재시도

NLI / model runtime 모두 미설치/미인증 시 rule 기반 약 신호로 status=candidate 보존.
자동 dismiss 금지 — false negative 영구 손실 방지.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ._common import db_connect, log, new_id, now_iso
from .model_runtime import run_background_model

# Local NLI model and fallback judge runtime settings.
# NLI is fast/optional; model judge is slower but helps mid-confidence pairs.
NLI_MODEL_NAME = os.environ.get("IMPRINT_NLI_MODEL") or "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
NLI_TIMEOUT_MS = int(os.environ.get("IMPRINT_NLI_TIMEOUT_MS") or "500")
MODEL_JUDGE_TIMEOUT_MS = int(os.environ.get("IMPRINT_MODEL_JUDGE_TIMEOUT_MS") or "30000")

# Candidate generation only compares decisions close enough in source update time.
TIME_GAP_DAYS = int(os.environ.get("IMPRINT_CONTRADICTION_TIME_GAP_DAYS") or "90")

# 3구간 임계 — 명세 예시값. 측정 후 캘리브레이션.
HIGH_THRESHOLD = float(os.environ.get("IMPRINT_CONTRADICTION_HIGH") or "0.8")
MID_THRESHOLD = float(os.environ.get("IMPRINT_CONTRADICTION_MID") or "0.4")

# NLI 가 mid 영역(low confidence) 일 때 model judge 로 보강할 범위.
MODEL_REFINE_LOW = float(os.environ.get("IMPRINT_MODEL_REFINE_LOW") or "0.4")
MODEL_REFINE_HIGH = float(os.environ.get("IMPRINT_MODEL_REFINE_HIGH") or "0.6")

_lock = threading.Lock()
_pipeline = None
_load_failed = False


@dataclass
class CandidatePair:
    entry_a_id: str
    entry_b_id: str
    entity_id: str | None
    scope_key: str | None
    a_text: str
    b_text: str


@dataclass
class CandidateStats:
    pairs_examined: int = 0
    pairs_inserted: int = 0
    pairs_skipped: int = 0
    nli_used: int = 0
    nli_skipped: int = 0


def _try_load_pipeline():
    global _pipeline, _load_failed
    if _pipeline is not None or _load_failed:
        return _pipeline
    with _lock:
        if _pipeline is not None or _load_failed:
            return _pipeline
        try:
            from transformers import pipeline  # type: ignore

            cache_dir = os.environ.get("IMPRINT_MODEL_CACHE_DIR")
            log("INFO", f"loading NLI pipeline {NLI_MODEL_NAME} (cold-load) cache={cache_dir or 'default'}")
            kwargs = {"model_kwargs": {"cache_dir": cache_dir}} if cache_dir else {}
            _pipeline = pipeline(
                "zero-shot-classification",
                model=NLI_MODEL_NAME,
                **kwargs,
            )
        except Exception as exc:
            _load_failed = True
            log("WARN", f"NLI pipeline load failed: {exc!r} — falling back to model judge / rule")
            _pipeline = None
    return _pipeline


def is_nli_available() -> bool:
    if os.environ.get("IMPRINT_DISABLE_NLI") == "1":
        return False
    return _try_load_pipeline() is not None


def _nli_score(premise: str, hypothesis: str) -> tuple[float, str] | None:
    """premise 가 hypothesis 와 contradicts 할 score 와 짧은 reason. timeout 시 None.

    zero-shot 분류기를 'contradiction / entailment / neutral' 라벨로 호출하고
    contradiction prob 만 반환.
    """
    pipeline = _try_load_pipeline()
    if pipeline is None:
        return None
    timeout = NLI_TIMEOUT_MS / 1000.0
    holder: dict = {}

    def _run() -> None:
        try:
            res = pipeline(
                premise,
                candidate_labels=["contradiction", "entailment", "neutral"],
                hypothesis_template="이 진술은 다음과 {}: {}",
            )
            scores = dict(zip(res["labels"], res["scores"]))
            holder["score"] = scores.get("contradiction", 0.0)
            holder["reason"] = f"nli contradiction={scores.get('contradiction',0):.2f} entailment={scores.get('entailment',0):.2f}"
        except Exception as exc:
            log("ERROR", f"NLI predict failed: {exc!r}")
            holder["score"] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if "score" not in holder or holder["score"] is None:
        return None
    return float(holder["score"]), holder.get("reason", "")


_MODEL_JUDGE_PROMPT = """You are a contradiction judge for Korean engineering decisions.

Two decision statements about the same feature are given. Decide whether they
contradict each other (i.e., one decision invalidates the other).

Reply with a single JSON object on one line, no prose:
{"verdict": "contradiction"|"entailment"|"neutral", "score": 0.0~1.0, "reason": "<one short Korean sentence>"}

- verdict=contradiction: 둘이 충돌. score 는 contradict 정도 (0.7~1.0).
- verdict=entailment: 둘이 같은 방향. score 는 0.0~0.3 (낮을수록 충돌 약함).
- verdict=neutral: 관련 없거나 판단 불가. score 0.4~0.6.

Statement A: {a}
Statement B: {b}

JSON:"""


def _model_judge(a_text: str, b_text: str) -> tuple[float, str] | None:
    """model runtime으로 두 결정문이 충돌하는지 판정.

    반환: (contradiction_score, reason). 실패/timeout 시 None.
    timeout 은 MODEL_JUDGE_TIMEOUT_MS — NLI 보다 길게 두는 것이 합리적 (model 호출 RTT
    가 NLI inference 보다 큼). 명세 500 ms 는 NLI 한정.
    """
    if os.environ.get("IMPRINT_DISABLE_MODEL_JUDGE") == "1":
        return None
    prompt = _MODEL_JUDGE_PROMPT.replace("{a}", a_text[:1500]).replace("{b}", b_text[:1500])
    out = run_background_model(prompt, timeout=MODEL_JUDGE_TIMEOUT_MS / 1000.0, task="contradiction")
    if out is None:
        log("WARN", "model judge failed")
        return None

    out = out.strip()
    if not out:
        return None
    # JSON 한 줄만 추출. 모델이 코드펜스를 둘러싸도 매치되도록.
    m = re.search(r"\{[^{}]*\}", out)
    if not m:
        log("WARN", f"model judge non-JSON: {out[:200]!r}")
        return None
    try:
        data = json.loads(m.group(0))
        verdict = (data.get("verdict") or "").lower()
        score = float(data.get("score") or 0.0)
        reason = str(data.get("reason") or "")[:200]
    except (ValueError, json.JSONDecodeError) as exc:
        log("WARN", f"model judge parse failed: {exc!r} raw={out[:200]!r}")
        return None

    # verdict 와 score 정합성 보정 — 모델이 "neutral" 라며 0.9 주는 등 모순 시
    # verdict 우선으로 score 클램프.
    if verdict == "contradiction":
        score = max(score, 0.7)
    elif verdict == "entailment":
        score = min(score, 0.3)
    elif verdict == "neutral":
        score = max(0.4, min(score, 0.6))
    return score, f"model verdict={verdict} reason={reason}"


def _classify_status(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "candidate"
    return "neutral"  # mid · low 모두 neutral — 자동 dismiss 금지.


@dataclass
class JudgeResult:
    score: float
    reason: str
    detector: str            # nli | model | rule | retry
    needs_retry: bool        # True 면 status=candidate 로 강제 (다음 배치에서 재판정)


def _judge_pair(a_text: str, b_text: str, *, use_nli: bool, use_llm: bool) -> JudgeResult:
    """판정 파이프라인 — NLI primary → model fallback → rule weak signal.

    명세 우선순위:
      1) NLI 시도 (500 ms timeout).
      2) NLI 가 실패/timeout 또는 mid confidence (MODEL_REFINE_LOW~HIGH) 면 model judge.
      3) 둘 다 실패 → rule 약 신호로 status=candidate 보존 (재시도).
    """
    nli_out: tuple[float, str] | None = None
    if use_nli and is_nli_available():
        nli_out = _nli_score(a_text, b_text)

    # NLI 가 high confidence (high or low extreme) 결과면 그대로 채택.
    if nli_out is not None:
        score, reason = nli_out
        if score >= HIGH_THRESHOLD or score < MODEL_REFINE_LOW:
            return JudgeResult(score, reason, "nli", needs_retry=False)
        # mid 영역 → model judge 로 정밀화 시도. 실패하면 NLI 결과 그대로 보존.
        if use_llm:
            model_out = _model_judge(a_text, b_text)
            if model_out is not None:
                mscore, mreason = model_out
                return JudgeResult(mscore, f"{reason}; {mreason}", "model", needs_retry=False)
        return JudgeResult(score, reason, "nli", needs_retry=False)

    # NLI 실패/미가용 → model judge primary.
    if use_llm:
        model_out = _model_judge(a_text, b_text)
        if model_out is not None:
            mscore, mreason = model_out
            return JudgeResult(mscore, mreason, "model", needs_retry=False)

    # 마지막 fallback — rule 약 신호. score 0.5 (mid neutral) 로 두되 needs_retry=True
    # 로 status=candidate 강제. 다음 배치에서 NLI/model runtime 가용해지면 재판정.
    weak_score = 0.5 if a_text != b_text else 0.0
    return JudgeResult(
        weak_score,
        "rule weak signal — judge unavailable, retry next batch",
        "rule",
        needs_retry=True,
    )


def _ts_to_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _within_time_gap(a_ts: str | None, b_ts: str | None, days: int) -> bool:
    da = _ts_to_dt(a_ts)
    db = _ts_to_dt(b_ts)
    if not da or not db:
        return True  # timestamp 없으면 일단 후보로 둠.
    return abs((da - db).total_seconds()) < days * 86400


def candidate_pairs_for_project(
    project_id: str,
    conn: sqlite3.Connection | None = None,
) -> list[CandidatePair]:
    """same entity + decision + same section_path + time gap < TIME_GAP_DAYS 후보 생성.

    O(n²) 회피를 위해 entity / section_path 별로 group by 하고 그 안에서만 쌍을 만든다.
    """
    own = conn is None
    if own:
        conn = db_connect()
    try:
        # entity_id 가 있는 decision chunk 만 후보. 없으면 section_path 만으로 group.
        cur = conn.execute(
            """
            SELECT c.id, c.text, c.section_path, c.source_updated_at,
                   ce.entity_id
            FROM search_entries c
            LEFT JOIN entry_entities ce ON ce.entry_id = c.id
            WHERE c.project_id = ?
              AND c.normalized_type = 'decision'
              AND c.is_current = 1
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        # group by (entity_id, section_path).
        groups: dict[tuple[str | None, str | None], list[sqlite3.Row]] = {}
        for r in rows:
            key = (r["entity_id"], r["section_path"])
            groups.setdefault(key, []).append(r)

        pairs: list[CandidatePair] = []
        for (eid, sec), grp in groups.items():
            if len(grp) < 2:
                continue
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    a, b = grp[i], grp[j]
                    if not _within_time_gap(a["source_updated_at"], b["source_updated_at"], TIME_GAP_DAYS):
                        continue
                    pairs.append(CandidatePair(
                        entry_a_id=a["id"], entry_b_id=b["id"],
                        entity_id=eid, scope_key=sec,
                        a_text=a["text"], b_text=b["text"],
                    ))
        return pairs
    finally:
        if own:
            conn.close()


def scan_and_store(
    project_id: str,
    *,
    use_nli: bool = True,
    use_llm: bool = True,
    max_pairs: int = 200,
) -> CandidateStats:
    """후보 생성 → NLI/LLM 판정 → contradictions 테이블에 저장.

    이미 같은 (chunk_a, chunk_b, detector) 쌍이 confirmed/dismissed 상태로 저장돼 있으면
    덮지 않는다 (사용자 결정 보호). neutral / candidate 는 score 갱신 가능.

    needs_retry=True 인 결과(NLI/LLM 둘 다 미가용) 는 status=candidate 로 보존해
    다음 scan 배치가 NLI/LLM 가용한 환경에서 재판정.
    """
    stats = CandidateStats()
    conn = db_connect()
    try:
        candidates = candidate_pairs_for_project(project_id, conn=conn)[:max_pairs]
        for c in candidates:
            stats.pairs_examined += 1
            # 정렬된 (a, b) 키 — UNIQUE constraint 와 일치.
            a_id, b_id = sorted((c.entry_a_id, c.entry_b_id))

            judged = _judge_pair(c.a_text, c.b_text, use_nli=use_nli, use_llm=use_llm)
            if judged.detector == "nli":
                stats.nli_used += 1
            elif judged.detector == "rule":
                stats.nli_skipped += 1

            # 같은 chunk pair 에 대해 이전 결정(confirmed/dismissed) 가 있으면 보호.
            existing = conn.execute(
                """
                SELECT id, status FROM contradictions
                WHERE entry_a_id = ? AND entry_b_id = ? AND detector = ?
                """,
                (a_id, b_id, judged.detector),
            ).fetchone()
            if existing and existing["status"] in ("confirmed", "dismissed"):
                stats.pairs_skipped += 1
                continue

            # status 결정 — needs_retry 면 강제로 candidate 로 두고 다음 배치 트리거.
            status = "candidate" if judged.needs_retry else _classify_status(judged.score)
            ts = now_iso()
            if existing:
                conn.execute(
                    """
                    UPDATE contradictions
                    SET contradiction_score = ?, status = ?, reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (judged.score, status, judged.reason, ts, existing["id"]),
                )
            else:
                cid = new_id()
                conn.execute(
                    """
                    INSERT INTO contradictions
                      (id, project_id, entity_id, scope_key,
                       entry_a_id, entry_b_id, contradiction_score, detector, status, reason,
                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, project_id, c.entity_id, c.scope_key,
                     a_id, b_id, judged.score, judged.detector, status, judged.reason, ts, ts),
                )
                stats.pairs_inserted += 1
        return stats
    finally:
        conn.close()


def confirmed_for_entity(
    project_id: str,
    entity_id: str,
    conn: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    """CCHECK 단계 — query 의 resolved entity 에 대한 confirmed 쌍만 read-only 조회."""
    own = conn is None
    if own:
        conn = db_connect()
    try:
        cur = conn.execute(
            """
            SELECT id, entry_a_id, entry_b_id, contradiction_score, reason, scope_key
            FROM contradictions
            WHERE project_id = ? AND entity_id = ? AND status = 'confirmed'
            ORDER BY contradiction_score DESC
            """,
            (project_id, entity_id),
        )
        return list(cur.fetchall())
    finally:
        if own:
            conn.close()


def confirm(contradiction_id: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute(
            "UPDATE contradictions SET status = 'confirmed', updated_at = ? WHERE id = ?",
            (now_iso(), contradiction_id),
        )
    finally:
        if own:
            conn.close()


def dismiss(contradiction_id: str, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db_connect()
    try:
        conn.execute(
            "UPDATE contradictions SET status = 'dismissed', updated_at = ? WHERE id = ?",
            (now_iso(), contradiction_id),
        )
    finally:
        if own:
            conn.close()
