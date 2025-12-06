from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
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


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ панель"""
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к админ панели.")
        return
    
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
            faculties_stats[faculty] = result.scalar() or 0
        
        # Статистика по источникам информации
        sources_stats = {}
        sources = ["ВК-группа проекта", "ВК/Тг информера факультета", "от одногруппников", "от Координатора"]
        for source in sources:
            result = await session.execute(
                select(func.count(User.id)).where(User.info_source == source)
            )
            sources_stats[source] = result.scalar() or 0
        
        # Статистика вакансий
        total_vacancies_result = await session.execute(
            select(func.count(Vacancy.id))
        )
        total_vacancies = total_vacancies_result.scalar() or 0
        
        # Формируем сообщение
        stats_text = "📊 <b>Статистика бота</b>\n\n"
        stats_text += f"👥 <b>Пользователи:</b>\n"
        stats_text += f"   Всего: {total_users}\n"
        stats_text += f"   Зарегистрировано: {registered_users}\n"
        stats_text += f"   Не зарегистрировано: {total_users - registered_users}\n\n"
        
        stats_text += f"📋 <b>Вакансии:</b>\n"
        stats_text += f"   Всего в базе: {total_vacancies}\n\n"
        
        stats_text += f"🎓 <b>По факультетам:</b>\n"
        for faculty, count in faculties_stats.items():
            if count > 0:  # Показываем только факультеты с пользователями
                stats_text += f"   {faculty}: {count}\n"
        
        stats_text += f"\n📢 <b>Источники информации:</b>\n"
        for source, count in sources_stats.items():
            stats_text += f"   {source}: {count}\n"
        
        await message.answer(stats_text, parse_mode="HTML")


@router.message(Command("sync_vacancies"))
async def cmd_sync_vacancies(message: Message):
    """Синхронизация вакансий из Google Sheets"""
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return
    
    await message.answer("🔄 Начинаю синхронизацию вакансий из Google Sheets...")
    
    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
            await message.answer(f"✅ Синхронизация завершена! Обработано вакансий: {synced_count}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при синхронизации: {str(e)}")

