from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
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


def get_faculty_keyboard():
    """Клавиатура выбора факультета"""
    keyboard = []
    buttons = []
    for faculty_key, faculty_name in FACULTIES.items():
        buttons.append(KeyboardButton(text=faculty_name))
        if len(buttons) == 2:
            keyboard.append(buttons)
            buttons = []
    if buttons:
        keyboard.append(buttons)
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_info_source_keyboard():
    """Клавиатура выбора источника информации"""
    keyboard = []
    for source_key, source_name in INFO_SOURCES.items():
        keyboard.append([KeyboardButton(text=source_name)])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    async with async_session_maker() as session:
        # Проверяем, зарегистрирован ли пользователь
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user and user.is_registered:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Посмотреть вакансии", callback_data="my_vacancies")]
            ])
            await message.answer(
                f"Привет, {user.first_name}! Ты уже зарегистрирован.\n"
                "Используй /vacancies для просмотра вакансий.",
                reply_markup=keyboard
            )
            return
        
        # Начинаем регистрацию
        await message.answer(
            "Привет! Добро пожаловать в бот вакансий!\n\n"
            "Для начала нужно пройти регистрацию.\n"
            "Пожалуйста, введи своё имя:"
        )
        await state.set_state(RegistrationStates.waiting_for_first_name)


@router.message(RegistrationStates.waiting_for_first_name)
async def process_first_name(message: Message, state: FSMContext):
    """Обработка имени"""
    first_name = message.text.strip()
    if len(first_name) < 2:
        await message.answer("Имя слишком короткое. Пожалуйста, введи корректное имя:")
        return
    
    await state.update_data(first_name=first_name)
    await message.answer("Отлично! Теперь введи свою фамилию:")
    await state.set_state(RegistrationStates.waiting_for_last_name)


@router.message(RegistrationStates.waiting_for_last_name)
async def process_last_name(message: Message, state: FSMContext):
    """Обработка фамилии"""
    last_name = message.text.strip()
    if len(last_name) < 2:
        await message.answer("Фамилия слишком короткая. Пожалуйста, введи корректную фамилию:")
        return
    
    await state.update_data(last_name=last_name)
    await message.answer("Введи свой курс обучения (1-6):")
    await state.set_state(RegistrationStates.waiting_for_course)


@router.message(RegistrationStates.waiting_for_course)
async def process_course(message: Message, state: FSMContext):
    """Обработка курса"""
    try:
        course = int(message.text.strip())
        if course < 1 or course > 6:
            await message.answer("Курс должен быть от 1 до 6. Пожалуйста, введи корректный курс:")
            return
    except ValueError:
        await message.answer("Пожалуйста, введи число от 1 до 6:")
        return
    
    await state.update_data(course=course)
    await message.answer(
        "Выбери свой факультет:",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_faculty)


@router.message(RegistrationStates.waiting_for_faculty)
async def process_faculty(message: Message, state: FSMContext):
    """Обработка факультета"""
    faculty_text = message.text.strip()
    
    # Проверяем, что выбранный факультет есть в списке
    if faculty_text not in FACULTIES.values():
        await message.answer("Пожалуйста, выбери факультет из предложенных вариантов:")
        return
    
    await state.update_data(faculty=faculty_text)
    await message.answer(
        "Откуда ты узнал о проекте?",
        reply_markup=get_info_source_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_info_source)


@router.message(RegistrationStates.waiting_for_info_source)
async def process_info_source(message: Message, state: FSMContext):
    """Обработка источника информации и завершение регистрации"""
    info_source_text = message.text.strip()
    
    # Проверяем, что выбранный источник есть в списке
    if info_source_text not in INFO_SOURCES.values():
        await message.answer("Пожалуйста, выбери источник из предложенных вариантов:")
        return
    
    data = await state.get_data()
    
    # Сохраняем пользователя в БД
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Обновляем существующего пользователя
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            user.course = data["course"]
            user.faculty = data["faculty"]
            user.info_source = info_source_text
            user.is_registered = True
            user.registered_at = datetime.utcnow()
            user.last_activity = datetime.utcnow()
        else:
            # Создаем нового пользователя
            user = User(
                telegram_id=message.from_user.id,
                first_name=data["first_name"],
                last_name=data["last_name"],
                course=data["course"],
                faculty=data["faculty"],
                info_source=info_source_text,
                is_registered=True,
                registered_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            session.add(user)
        
        await session.commit()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Посмотреть вакансии", callback_data="my_vacancies")]
    ])
    
    await message.answer(
        f"Отлично, {data['first_name']}! Регистрация завершена.\n\n"
        "Теперь ты можешь просматривать вакансии, подходящие для твоего факультета.\n"
        "Используй /vacancies для просмотра доступных вакансий.",
        reply_markup=keyboard
    )
    
    await state.clear()

