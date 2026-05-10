"""cross-encoder rerank + LRU cache.

RG 게이트(count ≥ 10 AND top-1 < 0.85 AND cache miss) 통과 시에만 호출자가 부른다.
cross-encoder 미설치 시 그대로 입력 순서 반환 — graceful degradation.
timeout 200 ms 는 watcher 스레드로 강제 — 만료 시 입력 순서 그대로 반환, 실제
inference 는 백그라운드에서 끝나면 cache 에 저장.
"""
from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Sequence

from ._common import log

CROSS_ENCODER_NAME = os.environ.get("IMPRINT_RERANK_MODEL") or "BAAI/bge-reranker-v2-m3"
RERANK_TIMEOUT_MS = int(os.environ.get("IMPRINT_RERANK_TIMEOUT_MS") or "200")
RERANK_CACHE_SIZE = int(os.environ.get("IMPRINT_RERANK_CACHE_SIZE") or "64")

_lock = threading.Lock()
_model = None
_load_failed = False
_cache: "OrderedDict[str, list[int]]" = OrderedDict()
_cache_lock = threading.Lock()


def _try_load_model():
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            log("INFO", f"loading cross-encoder {CROSS_ENCODER_NAME} (cold-load)")
            _model = CrossEncoder(CROSS_ENCODER_NAME)
        except Exception as exc:
            _load_failed = True
            log("WARN", f"cross-encoder load failed: {exc!r} — rerank disabled")
            _model = None
    return _model


def is_available() -> bool:
    if os.environ.get("IMPRINT_DISABLE_RERANK") == "1":
        return False
    return _try_load_model() is not None


def cache_key(query: str, candidate_ids: Sequence[str], project_id: str) -> str:
    h = hashlib.sha256()
    h.update(project_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(query.encode("utf-8"))
    h.update(b"\x00")
    for cid in sorted(candidate_ids):
        h.update(cid.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def cache_get(key: str) -> list[int] | None:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return list(_cache[key])
    return None


def cache_put(key: str, ranking: list[int]) -> None:
    with _cache_lock:
        _cache[key] = list(ranking)
        _cache.move_to_end(key)
        while len(_cache) > RERANK_CACHE_SIZE:
            _cache.popitem(last=False)


def rerank(
    query: str,
    candidates: Sequence[tuple[str, str]],
    project_id: str,
    timeout_ms: int | None = None,
) -> list[int]:
    """입력 candidates 의 새 정렬 인덱스 반환.

    candidates: (chunk_id, retrieval_text) 시퀀스.
    반환: candidates 와 같은 길이의 정렬된 인덱스 리스트.
    timeout 또는 모델 미가용이면 [0, 1, 2, ...] 입력 순서 그대로 반환.
    """
    if not candidates:
        return []
    ids = [c[0] for c in candidates]
    key = cache_key(query, ids, project_id)
    cached = cache_get(key)
    if cached is not None and len(cached) == len(candidates):
        return cached

    model = _try_load_model()
    if model is None:
        return list(range(len(candidates)))

    timeout = (timeout_ms or RERANK_TIMEOUT_MS) / 1000.0
    result_holder: dict = {}

    def _run() -> None:
        try:
            pairs = [(query, c[1]) for c in candidates]
            scores = model.predict(pairs)
            order = sorted(range(len(candidates)), key=lambda i: -float(scores[i]))
            result_holder["order"] = order
        except Exception as exc:
            log("ERROR", f"rerank predict failed: {exc!r}")
            result_holder["order"] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if "order" not in result_holder:
        # timeout — 입력 순서로 fallback. 끝난 결과는 백그라운드에서 cache 에 저장.
        def _save_when_done() -> None:
            t.join()
            order = result_holder.get("order")
            if order is not None:
                cache_put(key, order)

        threading.Thread(target=_save_when_done, daemon=True).start()
        return list(range(len(candidates)))

    order = result_holder["order"]
    if order is None:
        return list(range(len(candidates)))
    cache_put(key, order)
    return order
