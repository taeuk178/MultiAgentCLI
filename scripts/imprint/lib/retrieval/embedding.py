"""BGE-M3 1024-dim embedding loader.

lazy spawn: 첫 호출에 모델 로드. sentence-transformers 미설치 시 None 반환 →
호출자(retrieve) 가 vector path 를 skip 하고 FTS-only fallback.
"""
from __future__ import annotations

import os
import struct
import threading
from typing import Sequence

from ._common import log

# 1024 dim float32. 실제 모델은 BGE-M3.
EMBEDDING_DIM = 1024
EMBEDDING_BYTES = EMBEDDING_DIM * 4
MODEL_NAME = os.environ.get("IMPRINT_EMBEDDING_MODEL") or "BAAI/bge-m3"

_lock = threading.Lock()
_model = None
_load_failed = False


def _try_load_model():
    """sentence-transformers 가 있으면 BGE-M3 로드, 없으면 None."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            cache_dir = os.environ.get("IMPRINT_MODEL_CACHE_DIR")
            log("INFO", f"loading embedding model {MODEL_NAME} (cold-load) cache={cache_dir or 'default'}")
            _model = SentenceTransformer(MODEL_NAME, cache_folder=cache_dir)
        except Exception as exc:
            _load_failed = True
            log("WARN", f"embedding model load failed: {exc!r} — falling back to FTS-only")
            _model = None
    return _model


def is_available() -> bool:
    """모델이 로드 가능한지. lazy 호출."""
    if os.environ.get("IMPRINT_DISABLE_EMBEDDING") == "1":
        return False
    return _try_load_model() is not None


def embed_texts(texts: Sequence[str]) -> list[bytes] | None:
    """texts 각각에 대해 1024-d float32 BLOB 리스트. 모델 미가용 시 None."""
    if not texts:
        return []
    if os.environ.get("IMPRINT_DISABLE_EMBEDDING") == "1":
        return None
    model = _try_load_model()
    if model is None:
        return None
    try:
        vecs = model.encode(list(texts), normalize_embeddings=True)
    except Exception as exc:
        log("ERROR", f"embedding encode failed: {exc!r}")
        return None
    out: list[bytes] = []
    for v in vecs:
        if len(v) != EMBEDDING_DIM:
            # 모델이 차원 다른 경우 — 호환성 깨지므로 통째로 fail.
            log("ERROR", f"embedding dim mismatch: got {len(v)} expected {EMBEDDING_DIM}")
            return None
        out.append(struct.pack(f"{EMBEDDING_DIM}f", *v.tolist()))
    return out


def embed_text(text: str) -> bytes | None:
    """single text → BLOB. None 이면 호출자가 vector path skip."""
    out = embed_texts([text])
    if out is None or not out:
        return None
    return out[0]


def cosine_similarity_blob(a: bytes, b: bytes) -> float:
    """두 BLOB 간 cosine similarity. sqlite-vec 미가용 시 numpy 또는 stdlib fallback."""
    if len(a) != EMBEDDING_BYTES or len(b) != EMBEDDING_BYTES:
        return 0.0
    va = struct.unpack(f"{EMBEDDING_DIM}f", a)
    vb = struct.unpack(f"{EMBEDDING_DIM}f", b)
    # normalize_embeddings=True 면 norm=1 가정 가능. 안전하게 직접 계산.
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(va, vb):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))
