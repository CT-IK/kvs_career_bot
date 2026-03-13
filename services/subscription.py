import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import REQUIRED_CHANNEL_URL, REQUIRED_CHANNEL_USERNAME

logger = logging.getLogger(__name__)

ALLOWED_CHAT_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.RESTRICTED,
}


def subscription_required() -> bool:
    return bool(REQUIRED_CHANNEL_USERNAME)


def get_subscription_text() -> str:
    channel_name = REQUIRED_CHANNEL_USERNAME or "канал проекта"
    return (
        "Чтобы пользоваться ботом, нужна подписка на канал "
        f"<b>{channel_name}</b>.\n\n"
        "1. Подпишись по кнопке ниже.\n"
        "2. Потом нажми <b>Проверить подписку</b>."
    )


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться", url=REQUIRED_CHANNEL_URL)],
            [InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")],
        ]
    )


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    if not subscription_required():
        return True

    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_USERNAME, user_id)
    except TelegramAPIError as exc:
        logger.warning("Failed to check subscription for user %s: %s", user_id, exc)
        return False

    return member.status in ALLOWED_CHAT_MEMBER_STATUSES
