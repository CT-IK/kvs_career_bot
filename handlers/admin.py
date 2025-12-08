from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.models import User, Vacancy, Statistics
from database.db import async_session_maker
from config import ADMIN_IDS
from services.google_sheets import sync_vacancies_to_db

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


def get_admin_keyboard():
    """Клавиатура админ-панели"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Синхронизировать вакансии", callback_data="admin_sync")],
        [InlineKeyboardButton(text="📊 Обновить статистику", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")]
    ])


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ панель"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к админ панели.")
        return
    
    # Убираем ReplyKeyboard если была
    await message.answer("🔐", reply_markup=ReplyKeyboardRemove())
    
    stats_text = await get_stats_text()
    
    await message.answer(
        stats_text,
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )


async def get_stats_text() -> str:
    """Получить текст статистики"""
    async with async_session_maker() as session:
        # Статистика пользователей
        total_users_result = await session.execute(
            select(func.count(User.id))
        )
        total_users = total_users_result.scalar() or 0
        
        registered_users_result = await session.execute(
            select(func.count(User.id)).where(User.is_registered == True)
        )
        registered_users = registered_users_result.scalar() or 0
        
        # Статистика по факультетам
        faculties_stats = {}
        for faculty in ["ИТиАБД", "МЭО", "ФЭБ", "СНиМК", "НАБ", "ФШУ", "ФФ", "ЮФ"]:
            result = await session.execute(
                select(func.count(User.id)).where(User.faculty == faculty)
            )
            count = result.scalar() or 0
            if count > 0:
                faculties_stats[faculty] = count
        
        # Статистика по источникам информации
        sources_stats = {}
        sources = ["ВК-группа проекта", "ВК/Тг информера факультета", "от одногруппников", "от Координатора"]
        for source in sources:
            result = await session.execute(
                select(func.count(User.id)).where(User.info_source == source)
            )
            count = result.scalar() or 0
            if count > 0:
                sources_stats[source] = count
        
        # Статистика вакансий
        total_vacancies_result = await session.execute(
            select(func.count(Vacancy.id))
        )
        total_vacancies = total_vacancies_result.scalar() or 0
        
        # Формируем сообщение
        stats_text = """
╔══════════════════════════╗
      🔐 <b>Админ-панель</b>
╚══════════════════════════╝

"""
        stats_text += f"👥 <b>Пользователи:</b>\n"
        stats_text += f"   📊 Всего: <b>{total_users}</b>\n"
        stats_text += f"   ✅ Зарегистрировано: <b>{registered_users}</b>\n"
        stats_text += f"   ⏳ Не зарегистрировано: <b>{total_users - registered_users}</b>\n\n"
        
        stats_text += f"📋 <b>Вакансии в базе:</b> <b>{total_vacancies}</b>\n\n"
        
        if faculties_stats:
            stats_text += f"🎓 <b>По факультетам:</b>\n"
            for faculty, count in faculties_stats.items():
                stats_text += f"   • {faculty}: {count}\n"
            stats_text += "\n"
        
        if sources_stats:
            stats_text += f"📢 <b>Источники:</b>\n"
            for source, count in sources_stats.items():
                stats_text += f"   • {source}: {count}\n"
        
        return stats_text


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    """Обновить статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    stats_text = await get_stats_text()
    
    await callback.message.edit_text(
        stats_text,
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer("📊 Статистика обновлена")


@router.callback_query(F.data == "admin_sync")
async def callback_admin_sync(callback: CallbackQuery):
    """Синхронизация вакансий через кнопку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.answer("🔄 Начинаю синхронизацию...")
    
    await callback.message.edit_text(
        "🔄 <b>Синхронизация вакансий...</b>\n\n"
        "⏳ Загружаю данные из Google Sheets...",
        parse_mode="HTML"
    )
    
    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        
        stats_text = await get_stats_text()
        stats_text += f"\n\n✅ <b>Синхронизировано: {synced_count} вакансий</b>"
        
        await callback.message.edit_text(
            stats_text,
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка синхронизации:</b>\n\n<code>{str(e)}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )


@router.message(Command("sync_vacancies"))
async def cmd_sync_vacancies(message: Message):
    """Синхронизация вакансий из Google Sheets (команда)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде.")
        return
    
    await message.answer(
        "🔄 <b>Синхронизация вакансий...</b>\n\n"
        "⏳ Загружаю данные из Google Sheets...",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )
    
    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        
        await message.answer(
            f"✅ <b>Синхронизация завершена!</b>\n\n"
            f"📊 Загружено вакансий: <b>{synced_count}</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        await message.answer(
            f"❌ <b>Ошибка при синхронизации:</b>\n\n<code>{str(e)}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
