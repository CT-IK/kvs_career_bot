from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.vacancies import show_main_menu_or_registration
from services.subscription import (
    get_subscription_keyboard,
    get_subscription_text,
    is_user_subscribed,
)

router = Router()


@router.callback_query(F.data == "check_subscription")
async def callback_check_subscription(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Re-check subscription and open the bot if the user has access."""
    if not callback.message:
        await callback.answer("Не удалось проверить подписку.", show_alert=True)
        return

    if not await is_user_subscribed(bot, callback.from_user.id):
        try:
            await callback.message.edit_text(
                get_subscription_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_subscription_keyboard(),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                get_subscription_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_subscription_keyboard(),
            )

        await callback.answer("Подписка на канал не найдена.", show_alert=True)
        return

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    await callback.answer("Подписка подтверждена.")
    await show_main_menu_or_registration(callback.message, state, callback.from_user.id)
