from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import User as UserModel
from database.db import async_session_maker
from datetime import datetime


class ActivityMiddleware(BaseMiddleware):
    """Middleware для обновления активности пользователя"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем пользователя из события
        user: User = data.get("event_from_user")
        
        if user:
            # Обновляем активность пользователя
            try:
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(UserModel).where(UserModel.telegram_id == user.id)
                    )
                    db_user = result.scalar_one_or_none()
                    
                    if db_user:
                        db_user.last_activity = datetime.utcnow()
                        await session.commit()
            except Exception:
                # Игнорируем ошибки при обновлении активности
                pass
        
        return await handler(event, data)

