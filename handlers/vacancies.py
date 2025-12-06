from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from database.models import User, Vacancy
from database.db import async_session_maker
from config import FACULTIES

router = Router()

# Маппинг факультетов из бота в поля БД
FACULTY_TO_DB_FIELD = {
    "ИТиАБД": "itiabd",
    "МЭО": "meo",
    "ФЭБ": "feb",
    "СНиМК": "snimk",
    "НАБ": "nab",
    "ФШУ": "vshu",
    "ФФ": "finfak",
    "ЮФ": "yurfak"
}


def get_main_menu_keyboard():
    """Главное меню с кнопками"""
    keyboard = [
        [InlineKeyboardButton(text="📋 Мои вакансии", callback_data="my_vacancies")],
        [InlineKeyboardButton(text="🔍 Все вакансии", callback_data="all_vacancies")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_vacancy_keyboard(vacancy_id: int, current_index: int, total: int, filter_type: str = "all"):
    """Клавиатура для навигации по вакансиям"""
    keyboard = []
    
    # Кнопки навигации
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data=f"vacancy_{filter_type}_{current_index - 1}"
        ))
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ▶️", 
            callback_data=f"vacancy_{filter_type}_{current_index + 1}"
        ))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Кнопка возврата
    keyboard.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_vacancy(vacancy: Vacancy) -> str:
    """Форматирование вакансии для отображения"""
    text = f"🏢 <b>{vacancy.organization}</b>\n\n"
    text += f"💼 <b>Вакансия:</b> {vacancy.position}\n"
    
    if vacancy.sphere:
        text += f"📊 <b>Сфера:</b> {vacancy.sphere}\n"
    if vacancy.salary:
        text += f"💰 <b>Зарплата:</b> {vacancy.salary}\n"
    if vacancy.schedule:
        text += f"⏰ <b>График:</b> {vacancy.schedule}\n"
    if vacancy.work_format:
        text += f"📍 <b>Формат:</b> {vacancy.work_format}\n"
    if vacancy.employment_format:
        text += f"📝 <b>Формат трудоустройства:</b> {vacancy.employment_format}\n"
    
    if vacancy.description:
        text += f"\n📄 <b>Описание:</b>\n{vacancy.description}\n"
    
    # Особенности
    features = []
    if vacancy.feature1:
        features.append(f"• {vacancy.feature1}")
    if vacancy.feature2:
        features.append(f"• {vacancy.feature2}")
    if vacancy.feature3:
        features.append(f"• {vacancy.feature3}")
    
    if features:
        text += f"\n✨ <b>Особенности:</b>\n" + "\n".join(features)
    
    return text


@router.message(Command("vacancies"))
async def cmd_vacancies(message: Message):
    """Команда для просмотра вакансий"""
    async with async_session_maker() as session:
        # Проверяем, зарегистрирован ли пользователь
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_registered:
            await message.answer(
                "Для просмотра вакансий необходимо пройти регистрацию.\n"
                "Используйте команду /start"
            )
            return
        
        await message.answer(
            "👋 Добро пожаловать в раздел вакансий!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard()
        )


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Обработка возврата в главное меню"""
    await callback.message.edit_text(
        "👋 Добро пожаловать в раздел вакансий!\n\n"
        "Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "my_vacancies")
async def callback_my_vacancies(callback: CallbackQuery):
    """Показать вакансии для факультета пользователя"""
    async with async_session_maker() as session:
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.faculty:
            await callback.answer("Ошибка: факультет не указан", show_alert=True)
            return
        
        # Получаем поле БД для факультета
        db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
        if not db_field:
            await callback.answer("Ошибка: неизвестный факультет", show_alert=True)
            return
        
        # Получаем вакансии для факультета
        filter_condition = getattr(Vacancy, db_field) == True
        result = await session.execute(
            select(Vacancy).where(filter_condition).order_by(Vacancy.created_at.desc())
        )
        vacancies = result.scalars().all()
        
        if not vacancies:
            await callback.message.edit_text(
                f"😔 К сожалению, для вашего факультета ({user.faculty}) пока нет доступных вакансий.\n\n"
                "Попробуйте посмотреть все вакансии или зайдите позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔍 Все вакансии", callback_data="all_vacancies")],
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        # Показываем первую вакансию
        vacancy = vacancies[0]
        text = format_vacancy(vacancy)
        text += f"\n\n📊 <i>Вакансия 1 из {len(vacancies)}</i>"
        
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "my")
        )
        
        await callback.answer()


@router.callback_query(F.data == "all_vacancies")
async def callback_all_vacancies(callback: CallbackQuery):
    """Показать все вакансии"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Vacancy).order_by(Vacancy.created_at.desc())
        )
        vacancies = result.scalars().all()
        
        if not vacancies:
            await callback.message.edit_text(
                "😔 В базе пока нет вакансий.\n"
                "Администратор может синхронизировать вакансии из Google Sheets командой /sync_vacancies",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        # Показываем первую вакансию
        vacancy = vacancies[0]
        text = format_vacancy(vacancy)
        text += f"\n\n📊 <i>Вакансия 1 из {len(vacancies)}</i>"
        
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "all")
        )
        
        await callback.answer()


@router.callback_query(F.data.startswith("vacancy_"))
async def callback_vacancy_navigation(callback: CallbackQuery):
    """Навигация по вакансиям"""
    # Парсим callback data: vacancy_{filter_type}_{index}
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("Ошибка навигации", show_alert=True)
        return
    
    filter_type = parts[1]  # "my" или "all"
    target_index = int(parts[2])
    
    async with async_session_maker() as session:
        if filter_type == "my":
            # Получаем вакансии для факультета пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if not user or not user.faculty:
                await callback.answer("Ошибка: факультет не указан", show_alert=True)
                return
            
            db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
            if not db_field:
                await callback.answer("Ошибка: неизвестный факультет", show_alert=True)
                return
            
            filter_condition = getattr(Vacancy, db_field) == True
            result = await session.execute(
                select(Vacancy).where(filter_condition).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        else:
            # Получаем все вакансии
            result = await session.execute(
                select(Vacancy).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        
        if target_index < 0 or target_index >= len(vacancies):
            await callback.answer("Достигнут конец списка", show_alert=True)
            return
        
        vacancy = vacancies[target_index]
        text = format_vacancy(vacancy)
        text += f"\n\n📊 <i>Вакансия {target_index + 1} из {len(vacancies)}</i>"
        
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, target_index, len(vacancies), filter_type)
        )
        
        await callback.answer()


@router.callback_query(F.data == "settings")
async def callback_settings(callback: CallbackQuery):
    """Настройки пользователя"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден", show_alert=True)
            return
        
        text = "⚙️ <b>Ваши настройки:</b>\n\n"
        text += f"👤 <b>Имя:</b> {user.first_name} {user.last_name}\n"
        text += f"🎓 <b>Курс:</b> {user.course}\n"
        text += f"🏛️ <b>Факультет:</b> {user.faculty}\n"
        text += f"📢 <b>Узнали от:</b> {user.info_source}\n"
        
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()

