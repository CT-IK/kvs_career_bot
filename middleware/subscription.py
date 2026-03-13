from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS
from services.subscription import (
    get_subscription_keyboard,
    get_subscription_text,
    is_user_subscribed,
    subscription_required,
)


class SubscriptionMiddleware(BaseMiddleware):
    """Blocks bot usage until the user subscribes to the required channel."""

    def __init__(self, allowed_callback_data: set[str] | None = None):
        self.allowed_callback_data = allowed_callback_data or set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not subscription_required():
            return await handler(event, data)

        user = data.get("event_from_user")
        bot: Bot | None = data.get("bot")

        if not user or not bot or user.id in ADMIN_IDS:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.chat.type != "private":
                return await handler(event, data)

            if await is_user_subscribed(bot, user.id):
                return await handler(event, data)

            await event.answer(
                get_subscription_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_subscription_keyboard(),
            )
            return None

        if isinstance(event, CallbackQuery):
            if event.data in self.allowed_callback_data:
                return await handler(event, data)

            if not event.message or event.message.chat.type != "private":
                return await handler(event, data)

            if await is_user_subscribed(bot, user.id):
                return await handler(event, data)

            await event.answer("Сначала подпишись на канал.", show_alert=True)
            await event.message.answer(
                get_subscription_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_subscription_keyboard(),
            )
            return None

        return await handler(event, data)
