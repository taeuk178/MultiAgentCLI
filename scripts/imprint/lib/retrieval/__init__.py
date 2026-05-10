"""Retrieval pipeline: chunk + hybrid search + entity normalize + versioning.

공개 API 는 cli.py 의 dispatch 가 사용한다. 하위 모듈은 각자 독립 테스트 가능.
"""
from ._common import db_connect, log, now_iso, new_id, profile_emit, Span

__all__ = [
    "db_connect",
    "log",
    "now_iso",
    "new_id",
    "profile_emit",
    "Span",
]
