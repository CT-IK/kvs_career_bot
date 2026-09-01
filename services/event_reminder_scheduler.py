from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from config import (
    EVENT_REMINDER_POLL_SECONDS,
    EVENT_REMINDERS_ENABLED,
    MINIAPP_PUBLIC_URL,
)
from database.db import async_session_maker
from database.models import MiniappEvent, MiniappEventRegistration
from services.max_bot import MaxApiError, max_bot

logger = logging.getLogger(__name__)


def _display_timezone():
    try:
        return ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=3))


def _event_url() -> str:
    return f"{MINIAPP_PUBLIC_URL.split('#', 1)[0]}#/notifications"


def _reminder_text(event: MiniappEvent, kind: str) -> str:
    starts_at = event.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    local_start = starts_at.astimezone(_display_timezone())
    heading = (
        "До мероприятия осталось меньше суток"
        if kind == "day"
        else "До мероприятия осталось меньше двух часов"
    )
    lines = [
        heading,
        "",
        event.title,
        f"{local_start:%d.%m.%Y в %H:%M} (МСК)",
    ]
    if event.place:
        lines.append(event.place)
    return "\n".join(lines)


async def _send_reminders(
    registrations: list[tuple[MiniappEventRegistration, MiniappEvent]],
    kind: str,
    sent_at: datetime,
) -> int:
    sent = 0
    marker = (
        "reminder_day_sent_at"
        if kind == "day"
        else "reminder_two_hours_sent_at"
    )
    async with async_session_maker() as session:
        for registration, event in registrations:
            db_registration = await session.get(MiniappEventRegistration, registration.id)
            if not db_registration or getattr(db_registration, marker):
                continue
            try:
                await max_bot.send_message(
                    db_registration.max_user_id,
                    _reminder_text(event, kind),
                    button={"text": "Открыть мои события", "url": _event_url()},
                )
            except MaxApiError as exc:
                # A blocked bot or unavailable chat is a permanent failure for
                # this reminder; mark it handled to avoid retrying every minute.
                logger.warning(
                    "Cannot deliver %s event reminder to %s: %s",
                    kind,
                    db_registration.max_user_id,
                    exc,
                )
                setattr(db_registration, marker, sent_at)
            except Exception:
                logger.exception(
                    "Temporary failure delivering %s event reminder to %s",
                    kind,
                    db_registration.max_user_id,
                )
                continue
            else:
                setattr(db_registration, marker, sent_at)
                sent += 1
            await session.commit()
    return sent


async def run_event_reminder_job(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    async with async_session_maker() as session:
        base = (
            select(MiniappEventRegistration, MiniappEvent)
            .join(MiniappEvent, MiniappEvent.id == MiniappEventRegistration.event_id)
            .where(
                MiniappEvent.is_active.is_(True),
                MiniappEventRegistration.status == "confirmed",
                MiniappEventRegistration.max_user_id.is_not(None),
                MiniappEvent.starts_at.is_not(None),
                MiniappEvent.starts_at > now,
            )
        )
        day_rows = (
            await session.execute(
                base.where(
                    MiniappEvent.starts_at > now + timedelta(hours=2),
                    MiniappEvent.starts_at <= now + timedelta(days=1),
                    MiniappEventRegistration.reminder_day_sent_at.is_(None),
                )
            )
        ).all()
        two_hour_rows = (
            await session.execute(
                base.where(
                    MiniappEvent.starts_at <= now + timedelta(hours=2),
                    MiniappEventRegistration.reminder_two_hours_sent_at.is_(None),
                )
            )
        ).all()

    day_sent = await _send_reminders(day_rows, "day", now)
    two_hour_sent = await _send_reminders(two_hour_rows, "two_hours", now)
    return {"day": day_sent, "twoHours": two_hour_sent}


async def run_event_reminder_scheduler() -> None:
    if not EVENT_REMINDERS_ENABLED:
        logger.info("Event reminder scheduler is disabled")
        return

    logger.info(
        "Event reminder scheduler enabled: poll every %s seconds",
        EVENT_REMINDER_POLL_SECONDS,
    )
    try:
        while True:
            try:
                result = await run_event_reminder_job()
                if result["day"] or result["twoHours"]:
                    logger.info("Event reminders sent: %s", result)
            except Exception:
                logger.exception("Event reminder scheduler iteration failed")
            await asyncio.sleep(EVENT_REMINDER_POLL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Event reminder scheduler stopped")
        raise
