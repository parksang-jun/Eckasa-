"""작업 취소 관리 (협조적 취소).

백그라운드 스레드로 도는 작업을 강제로 죽이는 건 위험해서, '취소 요청' 플래그를
메모리에 두고 파이프라인이 각 단계 사이에서 이 플래그를 확인해 스스로 멈춘다.
(현재 진행 중인 한 단계 — 예: AI 이미지 생성 호출 — 가 끝난 뒤 취소됨)

단일 프로세스(uvicorn) + 스레드 구조라 메모리 집합으로 충분하다.
서버를 재시작하면 진행 중이던 작업도 사라지므로 영속화는 불필요.
"""
from __future__ import annotations

import threading
from typing import Set

_lock = threading.Lock()
_requested: Set[int] = set()


def request_cancel(job_id: int) -> None:
    with _lock:
        _requested.add(int(job_id))


def is_cancelled(job_id: int) -> bool:
    with _lock:
        return int(job_id) in _requested


def clear(job_id: int) -> None:
    with _lock:
        _requested.discard(int(job_id))
