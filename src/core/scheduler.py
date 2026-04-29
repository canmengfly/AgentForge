"""APScheduler singleton — manages periodic datasource sync jobs."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def schedule_ds(ds_id: int, interval_minutes: int) -> None:
    from src.api.routes.datasources import _run_incremental_sync
    sch = get_scheduler()
    job_id = f"ds_sync_{ds_id}"
    sch.add_job(
        _run_incremental_sync,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[ds_id],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=120,
    )
    logger.info("Scheduled datasource %d every %d min", ds_id, interval_minutes)


def unschedule_ds(ds_id: int) -> None:
    sch = get_scheduler()
    job_id = f"ds_sync_{ds_id}"
    if sch.get_job(job_id):
        sch.remove_job(job_id)
        logger.info("Unscheduled datasource %d", ds_id)


def next_run_at(ds_id: int) -> str | None:
    sch = get_scheduler()
    job = sch.get_job(f"ds_sync_{ds_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def start_scheduler() -> None:
    """Start the scheduler and restore all persisted sync schedules."""
    sch = get_scheduler()
    if not sch.running:
        sch.start()

    from src.core.database import SessionLocal
    from src.core.models import DataSource
    db = SessionLocal()
    try:
        scheduled = (
            db.query(DataSource)
            .filter(DataSource.sync_interval.isnot(None))
            .all()
        )
        for ds in scheduled:
            schedule_ds(ds.id, ds.sync_interval)
        if scheduled:
            logger.info("Restored %d scheduled datasource(s)", len(scheduled))
    finally:
        db.close()


def stop_scheduler() -> None:
    sch = get_scheduler()
    if sch.running:
        sch.shutdown(wait=False)
