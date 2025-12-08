from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User
from database.db import async_session_maker
from config import FACULTIES, INFO_SOURCES
from datetime import datetime

router = Router()


class RegistrationStates(StatesGroup):
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_course = State()
    waiting_for_faculty = State()
    waiting_for_info_source = State()


def get_course_keyboard():
    """Инлайн клавиатура выбора курса"""
    keyboard = [
        [
            InlineKeyboardButton(text="1", callback_data="reg_course_1"),
            InlineKeyboardButton(text="2", callback_data="reg_course_2"),
            InlineKeyboardButton(text="3", callback_data="reg_course_3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="reg_course_4"),
            InlineKeyboardButton(text="5", callback_data="reg_course_5"),
            InlineKeyboardButton(text="6", callback_data="reg_course_6"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_faculty_keyboard():
    """Инлайн клавиатура выбора факультета"""
    keyboard = []
    row = []
    for faculty_key, faculty_name in FACULTIES.items():
        row.append(InlineKeyboardButton(text=faculty_name, callback_data=f"reg_faculty_{faculty_name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_info_source_keyboard():
    """Инлайн клавиатура выбора источника информации"""
    keyboard = []
    for source_key, source_name in INFO_SOURCES.items():
        keyboard.append([InlineKeyboardButton(text=source_name, callback_data=f"reg_source_{source_name}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def start_registration(message: Message, state: FSMContext):
    """Начало регистрации - вызывается из других модулей"""
    welcome_text = """
╔══════════════════════════╗
   🎓 <b>Комитет Внешних Связей</b>
╚══════════════════════════╝

👋 <b>Добро пожаловать!</b>

Я помогу тебе найти подходящие вакансии
для твоего факультета.

Для начала пройди короткую регистрацию.

━━━━━━━━━━━━━━━━━━━━
📝 <b>Шаг 1 из 4:</b> Введи своё имя
"""
    await message.answer(
        welcome_text,
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.waiting_for_first_name)


@router.message(RegistrationStates.waiting_for_first_name)
async def process_first_name(message: Message, state: FSMContext):
    """Обработка имени"""
    # Если пользователь ввёл команду - игнорируем (команда обработается другим роутером)
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    first_name = message.text.strip()
    if len(first_name) < 2:
        await message.answer(
            "❌ Имя слишком короткое.\n"
            "Введи корректное имя (минимум 2 символа):"
        )
        return
    
    await state.update_data(first_name=first_name)
    await message.answer(
        f"✅ Привет, <b>{first_name}</b>!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Шаг 2 из 4:</b> Теперь введи свою фамилию",
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.waiting_for_last_name)


@router.message(RegistrationStates.waiting_for_last_name)
async def process_last_name(message: Message, state: FSMContext):
    """Обработка фамилии"""
    # Если пользователь ввёл команду - игнорируем
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    last_name = message.text.strip()
    if len(last_name) < 2:
        await message.answer(
            "❌ Фамилия слишком короткая.\n"
            "Введи корректную фамилию (минимум 2 символа):"
        )
        return
    
    await state.update_data(last_name=last_name)
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Шаг 3 из 4:</b> Выбери свой курс",
        parse_mode="HTML",
        reply_markup=get_course_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_course)


@router.callback_query(F.data.startswith("reg_course_"), RegistrationStates.waiting_for_course)
async def process_course_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора курса через инлайн кнопку"""
    course = int(callback.data.replace("reg_course_", ""))
    await state.update_data(course=course)
    
    await callback.message.edit_text(
        f"✅ Выбран курс: <b>{course}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Шаг 4 из 4:</b> Выбери свой факультет",
        parse_mode="HTML",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_faculty)
    await callback.answer()


@router.callback_query(F.data.startswith("reg_faculty_"), RegistrationStates.waiting_for_faculty)
async def process_faculty_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора факультета через инлайн кнопку"""
    faculty = callback.data.replace("reg_faculty_", "")
    await state.update_data(faculty=faculty)
    
    await callback.message.edit_text(
        f"✅ Выбран факультет: <b>{faculty}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>Последний вопрос:</b>\nОткуда ты узнал о проекте?",
        parse_mode="HTML",
        reply_markup=get_info_source_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_info_source)
    await callback.answer()


@router.callback_query(F.data.startswith("reg_source_"), RegistrationStates.waiting_for_info_source)
async def process_info_source_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора источника информации и завершение регистрации"""
    info_source = callback.data.replace("reg_source_", "")
    data = await state.get_data()
    
    # Сохраняем пользователя в БД
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            user.course = data["course"]
            user.faculty = data["faculty"]
            user.info_source = info_source
            user.is_registered = True
            user.registered_at = datetime.utcnow()
            user.last_activity = datetime.utcnow()
        else:
            user = User(
                telegram_id=callback.from_user.id,
                first_name=data["first_name"],
                last_name=data["last_name"],
                course=data["course"],
                faculty=data["faculty"],
                info_source=info_source,
                is_registered=True,
                registered_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            session.add(user)
        
        await session.commit()
    
    # Получаем количество вакансий для нового пользователя
    from handlers.vacancies import get_user_vacancies_count, get_main_menu_keyboard
    async with async_session_maker() as session:
        vacancies_count = await get_user_vacancies_count(session, data["faculty"])
    
    success_text = f"""
╔══════════════════════════╗
      ✅ <b>Регистрация завершена!</b>
╚══════════════════════════╝

Добро пожаловать, <b>{data['first_name']}</b>!

📚 Твой факультет: <b>{data['faculty']}</b>
🎯 Для тебя доступно: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
    
    await callback.message.edit_text(
        success_text,
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(data["faculty"], vacancies_count)
    )
    
    await state.clear()
    await callback.answer("🎉 Регистрация завершена!")


# Обработка текстового ввода для курса (fallback)
@router.message(RegistrationStates.waiting_for_course)
async def process_course_text(message: Message, state: FSMContext):
    """Обработка курса текстом (если пользователь не нажал кнопку)"""
    # Если пользователь ввёл команду - игнорируем
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    try:
        course = int(message.text.strip())
        if course < 1 or course > 6:
            await message.answer(
                "❌ Курс должен быть от 1 до 6.\n"
                "Выбери курс из кнопок выше или введи число:",
                reply_markup=get_course_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, выбери курс из кнопок:",
            reply_markup=get_course_keyboard()
        )
        return
    
    await state.update_data(course=course)
    await message.answer(
        f"✅ Выбран курс: <b>{course}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>Шаг 4 из 4:</b> Выбери свой факультет",
        parse_mode="HTML",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_faculty)
