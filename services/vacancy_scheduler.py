"""Daily background scheduler for vacancy sync and card generation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import (
    VACANCY_SYNC_HOUR,
    VACANCY_SYNC_MINUTE,
    VACANCY_SYNC_SCHEDULE_ENABLED,
    VACANCY_SYNC_TIMEZONE,
)
from database.db import async_session_maker
from services.google_sheets import sync_vacancies_to_db

logger = logging.getLogger(__name__)


MSK_FIXED_TIMEZONE = timezone(timedelta(hours=3), name="MSK")


def get_vacancy_sync_timezone() -> tzinfo:
    """Resolve the configured timezone with a safe fallback."""
    try:
        return ZoneInfo(VACANCY_SYNC_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Timezone %r is unavailable. Falling back to fixed MSK (UTC+3).",
            VACANCY_SYNC_TIMEZONE,
        )
        return MSK_FIXED_TIMEZONE


def get_next_vacancy_sync_run(now: datetime, *, hour: int, minute: int) -> datetime:
    """Return the next scheduled run after the given timezone-aware datetime."""
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return scheduled_today
    return scheduled_today + timedelta(days=1)


async def run_vacancy_sync_job() -> int:
    """Synchronize vacancies into SQL and rebuild vacancy cards."""
    logger.info("Starting scheduled vacancy sync")
    async with async_session_maker() as session:
        synced_count = await sync_vacancies_to_db(session)
    logger.info("Scheduled vacancy sync finished: synced=%s", synced_count)
    return synced_count


async def run_daily_vacancy_sync_scheduler() -> None:
    """Run vacancy sync every day at the configured Moscow time."""
    if not VACANCY_SYNC_SCHEDULE_ENABLED:
        logger.info("Daily vacancy sync scheduler is disabled")
        return

    timezone = get_vacancy_sync_timezone()
    logger.info(
        "Daily vacancy sync scheduler enabled at %02d:%02d (%s)",
        VACANCY_SYNC_HOUR,
        VACANCY_SYNC_MINUTE,
        getattr(timezone, "key", None) or timezone.tzname(None) or str(timezone),
    )

    try:
        while True:
            now = datetime.now(timezone)
            next_run = get_next_vacancy_sync_run(
                now,
                hour=VACANCY_SYNC_HOUR,
                minute=VACANCY_SYNC_MINUTE,
            )
            sleep_seconds = max(1.0, (next_run - now).total_seconds())
            logger.info("Next vacancy sync scheduled for %s", next_run.isoformat())
            await asyncio.sleep(sleep_seconds)

            try:
                await run_vacancy_sync_job()
            except Exception:
                logger.exception("Scheduled vacancy sync failed")
    except asyncio.CancelledError:
        logger.info("Daily vacancy sync scheduler stopped")
        raise
