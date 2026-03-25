from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select, update

from database.db import async_session_maker
from database.models import User as UserModel
from services.admins import normalize_username
from services.user_metrics import build_user_action


class ActivityMiddleware(BaseMiddleware):
    """Middleware для обновления активности и username пользователя."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user: User = data.get("event_from_user")

        if user:
            try:
                normalized_username = normalize_username(user.username)
                async with async_session_maker() as session:
                    if normalized_username:
                        await session.execute(
                            update(UserModel)
                            .where(
                                UserModel.username == normalized_username,
                                UserModel.telegram_id != user.id,
                            )
                            .values(username=None)
                        )

                    result = await session.execute(
                        select(UserModel).where(UserModel.telegram_id == user.id)
                    )
                    db_user = result.scalar_one_or_none()

                    if db_user:
                        db_user.username = normalized_username
                        db_user.last_activity = datetime.utcnow()
                    else:
                        db_user = UserModel(
                            telegram_id=user.id,
                            username=normalized_username,
                            first_name=user.first_name,
                            last_name=user.last_name,
                            is_registered=False,
                            registered_at=None,
                            last_activity=datetime.utcnow(),
                        )
                        session.add(db_user)
                        await session.flush()

                    session.add(
                        await build_user_action(
                            event=event,
                            data=data,
                            db_user=db_user,
                            normalized_username=normalized_username,
                        )
                    )

                    await session.commit()
            except Exception:
                pass

        return await handler(event, data)
