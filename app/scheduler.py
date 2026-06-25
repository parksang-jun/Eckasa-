"""APScheduler 로 제품을 순환하며 자동으로 릴스를 제작·게시한다.

- SCHEDULE_CRON(.env)에 따라 주기 실행
- 매 실행마다 next_product_for_rotation() 으로 '가장 오래 안 올린' 제품을 골라 게시
- 대시보드에서 start/stop 토글 가능
"""
from __future__ import annotations

import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings
from . import db, pipeline

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()
JOB_ID = "eckasa_rotation"


def _tick() -> None:
    """스케줄 1회 실행: 다음 제품을 골라 제작·게시."""
    product_id = db.next_product_for_rotation()
    if product_id is None:
        print("[scheduler] 게시할 제품이 없습니다.")
        return
    print(f"[scheduler] 제품 {product_id} 자동 장면 광고 게시 시작")
    try:
        # 기본 배경/모델 프리셋으로 장면 광고 생성·게시 (fal.ai 필요)
        pipeline.run_scene_job(product_id, publish=True)
    except Exception as e:  # noqa: BLE001
        print(f"[scheduler] 실패: {e}")


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
            _scheduler.start()
    return _scheduler


def is_running() -> bool:
    sch = _scheduler
    return bool(sch and sch.get_job(JOB_ID))


def start(cron: Optional[str] = None) -> str:
    cron = cron or settings.schedule_cron
    sch = get_scheduler()
    trigger = CronTrigger.from_crontab(cron, timezone="Asia/Seoul")
    sch.add_job(_tick, trigger=trigger, id=JOB_ID, replace_existing=True,
                max_instances=1, coalesce=True)
    db.set_setting("schedule_enabled", "1")
    db.set_setting("schedule_cron", cron)
    return cron


def stop() -> None:
    sch = get_scheduler()
    if sch.get_job(JOB_ID):
        sch.remove_job(JOB_ID)
    db.set_setting("schedule_enabled", "0")


def init_from_settings() -> None:
    """서버 시작 시 저장된 설정/`.env` 기준으로 스케줄러를 복원한다."""
    enabled = db.get_setting("schedule_enabled")
    if enabled is None:
        enabled = "1" if settings.schedule_enabled else "0"
    if enabled == "1":
        cron = db.get_setting("schedule_cron") or settings.schedule_cron
        start(cron)
        print(f"[scheduler] 자동 게시 활성화: {cron}")
