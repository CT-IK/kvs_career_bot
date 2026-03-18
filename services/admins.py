from __future__ import annotations

from sqlalchemy import func, select

from config import ADMIN_IDS
from database.db import async_session_maker
from database.models import User


def normalize_username(username: str | None) -> str | None:
    if not username:
        return None

    normalized = username.strip().lstrip("@").casefold()
    return normalized or None


async def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True

    async with async_session_maker() as session:
        result = await session.execute(
            select(User.is_admin).where(User.telegram_id == user_id)
        )
        return bool(result.scalar())


async def get_admin_ids() -> list[int]:
    admin_ids = set(ADMIN_IDS)

    async with async_session_maker() as session:
        result = await session.execute(
            select(User.telegram_id).where(
                User.is_admin.is_(True),
                User.telegram_id.is_not(None),
            )
        )
        admin_ids.update(telegram_id for telegram_id in result.scalars().all() if telegram_id)

    return sorted(admin_ids)


async def grant_admin_by_username(username: str) -> tuple[str, User | None]:
    normalized_username = normalize_username(username)
    if not normalized_username:
        return "invalid_username", None

    async with async_session_maker() as session:
        user = (
            await session.execute(
                select(User)
                .where(func.lower(User.username) == normalized_username)
                .order_by(User.last_activity.desc().nullslast(), User.id.desc())
            )
        ).scalars().first()

        if not user:
            return "not_found", None

        if user.is_admin or user.telegram_id in ADMIN_IDS:
            return "already_admin", user

        user.is_admin = True
        await session.commit()
        return "granted", user
