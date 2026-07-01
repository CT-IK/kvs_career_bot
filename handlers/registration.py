import html
import logging
import re
from pathlib import Path

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User
from database.db import async_session_maker
from config import FACULTIES, INFO_SOURCES
from datetime import datetime
from services.admins import normalize_username
from services.course_utils import COURSE_LEVELS, format_course_label, parse_course_callback
from services.user_names import validate_name_part

router = Router()
REGISTRATION_TOTAL_STEPS = 7
logger = logging.getLogger(__name__)
CONGRATULATION_GIF_PATH = Path(__file__).parent.parent / "assets" / "congratulation" / "pug.gif"
PRIVACY_POLICY_URL = "https://docs.google.com/document/d/1oHQcLz6OMFWezlRRNkx1HHEkNfH__JBaA5FOdKa4o5k/edit?tab=t.0#heading=h.ydfzj89gl84q"
PERSONAL_DATA_CONSENT_URL = "https://docs.google.com/document/d/1PXvgwN2rzhsJ-VTgnj9hQxl4b58kOd7d6cRLvfQQL6U/edit?usp=sharing"
NO_FACULTY_LABEL = "Нет моего направления"
ALLOWED_EMAIL_DOMAIN = "edu.fa.ru"
ADMIN_EMAIL = "253103@edu.fa.ru"
EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@edu\.fa\.ru$", re.IGNORECASE)


class RegistrationStates(StatesGroup):
    waiting_for_consent = State()
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_patronymic = State()
    waiting_for_email = State()
    waiting_for_course = State()
    waiting_for_faculty = State()
    waiting_for_info_source = State()


def normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def validate_email(value: str | None) -> tuple[bool, str, str]:
    email = normalize_email(value)
    if not email:
        return False, "", "❌ Введи почту."
    if not EMAIL_RE.fullmatch(email):
        return (
            False,
            "",
            f"❌ Почта должна быть в домене <b>{ALLOWED_EMAIL_DOMAIN}</b>.\n"
            "Например: <code>name@edu.fa.ru</code>",
        )
    return True, email, ""


def is_admin_email(email: str | None) -> bool:
    return normalize_email(email) == ADMIN_EMAIL


def get_step_text(step: int, total: int, title: str, question: str) -> str:
    return f"""
❤️ <b>Комитет Внешних Связей</b> 🖤

<b>{title}</b>

Я помогу тебе найти подходящие вакансии, стажировки
и карьерные возможности по твоему факультету. 💼

<b>Шаг {step} из {total}</b>
<blockquote>{question}</blockquote>
""".strip()


def get_consent_text() -> str:
    return """
❤️ <b>Комитет Внешних Связей</b> 🖤

<b>Перед началом работы ознакомься с документами</b>

Пожалуйста, изучи:
• <a href="{privacy_url}">Политику конфиденциальности бота</a>
• <a href="{consent_url}">Согласие на обработку персональных данных</a>

<blockquote>Нажимая кнопку «Далее», ты подтверждаешь, что ознакомился(ась) с Политикой конфиденциальности бота и выражаешь согласие на обработку персональных данных.</blockquote>
""".strip().format(
        privacy_url=html.escape(PRIVACY_POLICY_URL, quote=True),
        consent_url=html.escape(PERSONAL_DATA_CONSENT_URL, quote=True),
    )


def get_consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика конфиденциальности", url=PRIVACY_POLICY_URL)],
            [InlineKeyboardButton(text="Согласие на обработку ПДн", url=PERSONAL_DATA_CONSENT_URL)],
            [InlineKeyboardButton(text="Далее", callback_data="reg_accept_documents")],
        ]
    )


async def prompt_first_name(target: Message, state: FSMContext):
    welcome_text = get_step_text(
        step=1,
        total=REGISTRATION_TOTAL_STEPS,
        title="Добро пожаловать!",
        question="Введи своё имя",
    )
    await target.answer(
        welcome_text,
        parse_mode="HTML",
    )

    await state.set_state(RegistrationStates.waiting_for_first_name)


async def prompt_existing_user_email(target: Message, state: FSMContext):
    await state.update_data(email_only=True)
    await target.answer(
        """
❤️ <b>Комитет Внешних Связей</b> 🖤

Для продолжения укажи свою почту в домене <b>edu.fa.ru</b>.
""".strip(),
        parse_mode="HTML",
    )
    await state.set_state(RegistrationStates.waiting_for_email)


def get_course_keyboard():
    """Инлайн клавиатура выбора курса"""
    keyboard = []
    for level_key, level_title, years, _offset in COURSE_LEVELS:
        keyboard.append([InlineKeyboardButton(text=level_title, callback_data="noop")])
        keyboard.append([
            InlineKeyboardButton(text=str(year), callback_data=f"reg_course_{level_key}_{year}")
            for year in years
        ])
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
    keyboard.append([InlineKeyboardButton(text=NO_FACULTY_LABEL, callback_data=f"reg_faculty_{NO_FACULTY_LABEL}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_info_source_keyboard():
    """Инлайн клавиатура выбора источника информации"""
    keyboard = []
    for source_key, source_name in INFO_SOURCES.items():
        keyboard.append([InlineKeyboardButton(text=source_name, callback_data=f"reg_source_{source_name}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def start_registration(message: Message, state: FSMContext):
    """Начало регистрации - вызывается из других модулей"""
    await message.answer(
        get_consent_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_consent_keyboard(),
    )
    await state.set_state(RegistrationStates.waiting_for_consent)


@router.callback_query(F.data == "reg_accept_documents", RegistrationStates.waiting_for_consent)
async def process_documents_consent(callback: CallbackQuery, state: FSMContext):
    """Переход к регистрации после подтверждения ознакомления с документами."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await prompt_first_name(callback.message, state)
    await callback.answer()


@router.message(RegistrationStates.waiting_for_consent)
async def process_waiting_for_consent(message: Message):
    """Подсказываем пользователю, что переход возможен только по кнопке."""
    await message.answer(
        "Чтобы продолжить, ознакомься с документами выше и нажми кнопку «Далее».",
        reply_markup=get_consent_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(RegistrationStates.waiting_for_first_name)
async def process_first_name(message: Message, state: FSMContext):
    """Обработка имени"""
    # Если пользователь ввёл команду - игнорируем (команда обработается другим роутером)
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    is_valid, first_name, error_text = validate_name_part(message.text, "Имя")
    if not is_valid:
        await message.answer(
            error_text + "\nВведи корректное имя:"
        )
        return
    
    await state.update_data(first_name=first_name)
    await message.answer(
        get_step_text(
            step=2,
            total=REGISTRATION_TOTAL_STEPS,
            title=f"Приятно познакомиться, {html.escape(first_name)}!",
            question="Теперь введи свою фамилию",
        ),
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
    
    is_valid, last_name, error_text = validate_name_part(message.text, "Фамилия")
    if not is_valid:
        await message.answer(
            error_text + "\nВведи корректную фамилию:"
        )
        return
    
    await state.update_data(last_name=last_name)
    await message.answer(
        get_step_text(
            step=3,
            total=REGISTRATION_TOTAL_STEPS,
            title="Ещё немного",
            question='Введи своё отчество или напиши "Нет"',
        ),
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.waiting_for_patronymic)


@router.message(RegistrationStates.waiting_for_patronymic)
async def process_patronymic(message: Message, state: FSMContext):
    """Обработка отчества"""
    if message.text and message.text.startswith('/'):
        await state.clear()
        return

    is_valid, patronymic, error_text = validate_name_part(
        message.text,
        "Отчество",
        allow_none_literal=True
    )
    if not is_valid:
        await message.answer(
            error_text + '\nЕсли отчества нет, напиши "Нет".'
        )
        return

    await state.update_data(patronymic=patronymic)
    await message.answer(
        get_step_text(
            step=4,
            total=REGISTRATION_TOTAL_STEPS,
            title="Отлично, продолжаем",
            question="Введи свою почту в домене edu.fa.ru",
        ),
        parse_mode="HTML",
    )
    await state.set_state(RegistrationStates.waiting_for_email)


@router.message(RegistrationStates.waiting_for_email)
async def process_email(message: Message, state: FSMContext):
    """Обработка корпоративной почты."""
    if message.text and message.text.startswith('/'):
        await state.clear()
        return

    is_valid, email, error_text = validate_email(message.text)
    if not is_valid:
        await message.answer(error_text, parse_mode="HTML")
        return

    data = await state.get_data()
    if data.get("email_only"):
        should_open_admin = is_admin_email(email)
        async with async_session_maker() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.email = email
                if should_open_admin:
                    user.is_admin = True
                user.last_activity = datetime.utcnow()
                await session.commit()

        await state.clear()
        if should_open_admin:
            from handlers.admin import get_admin_keyboard, get_stats_text

            await message.answer(
                "Админ-доступ активирован по корпоративной почте.",
                parse_mode="HTML",
            )
            await message.answer(
                await get_stats_text(),
                parse_mode="HTML",
                reply_markup=get_admin_keyboard(),
            )
            return

        from handlers.vacancies import show_main_menu_or_registration

        await show_main_menu_or_registration(message, state, message.from_user.id)
        return

    await state.update_data(email=email)
    await message.answer(
        get_step_text(
            step=5,
            total=REGISTRATION_TOTAL_STEPS,
            title="Почта сохранена",
            question="Выбери свой курс",
        ),
        parse_mode="HTML",
        reply_markup=get_course_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_course)


@router.callback_query(F.data.startswith("reg_course_"), RegistrationStates.waiting_for_course)
async def process_course_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора курса через инлайн кнопку"""
    _level, _year, course = parse_course_callback(callback.data, "reg_course")
    await state.update_data(course=course)
    
    await callback.message.edit_text(
        get_step_text(
            step=6,
            total=REGISTRATION_TOTAL_STEPS,
            title=f"Курс: {format_course_label(course)}",
            question="Выбери свой факультет",
        ),
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
        get_step_text(
            step=7,
            total=REGISTRATION_TOTAL_STEPS,
            title=f"Факультет: {html.escape(faculty)}",
            question="Откуда ты узнал о проекте?",
        ),
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
    email = data.get("email")
    if not email:
        await callback.answer("Сначала укажи почту", show_alert=True)
        await callback.message.answer(
            get_step_text(
                step=4,
                total=REGISTRATION_TOTAL_STEPS,
                title="Нужна корпоративная почта",
                question="Введи свою почту в домене edu.fa.ru",
            ),
            parse_mode="HTML",
        )
        await state.set_state(RegistrationStates.waiting_for_email)
        return

    should_open_admin = is_admin_email(email)
    
    # Сохраняем пользователя в БД
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.username = normalize_username(callback.from_user.username)
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            user.patronymic = data.get("patronymic")
            user.email = email
            user.course = data["course"]
            user.faculty = data["faculty"]
            user.info_source = info_source
            if should_open_admin:
                user.is_admin = True
            user.is_registered = True
            user.registered_at = datetime.utcnow()
            user.last_activity = datetime.utcnow()
        else:
            user = User(
                telegram_id=callback.from_user.id,
                username=normalize_username(callback.from_user.username),
                first_name=data["first_name"],
                last_name=data["last_name"],
                patronymic=data.get("patronymic"),
                email=email,
                course=data["course"],
                faculty=data["faculty"],
                info_source=info_source,
                is_admin=should_open_admin,
                is_registered=True,
                registered_at=datetime.utcnow(),
                last_activity=datetime.utcnow()
            )
            session.add(user)
        
        await session.commit()
    
    from handlers.vacancies import show_main_menu_or_registration
    
    success_text = f"""
✅ <b>Регистрация завершена!</b>

""".strip()

    await callback.answer("🎉 Регистрация завершена!")

    if CONGRATULATION_GIF_PATH.exists():
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass

        try:
            await callback.message.answer_animation(
                animation=FSInputFile(CONGRATULATION_GIF_PATH),
                caption=success_text,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            logger.warning("Failed to send congratulation GIF: %s", CONGRATULATION_GIF_PATH)
            await callback.message.answer(
                success_text,
                parse_mode="HTML",
            )
    else:
        logger.warning("Congratulation GIF not found: %s", CONGRATULATION_GIF_PATH)
        try:
            await callback.message.edit_text(
                success_text,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            await callback.message.answer(
                success_text,
                parse_mode="HTML",
            )

    await state.clear()
    if should_open_admin:
        from handlers.admin import get_admin_keyboard, get_stats_text

        await callback.message.answer(
            "Админ-доступ активирован по корпоративной почте.",
            parse_mode="HTML",
        )
        await callback.message.answer(
            await get_stats_text(),
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
        return

    await show_main_menu_or_registration(callback.message, state, callback.from_user.id)


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
        if course < 1 or course > 8:
            await message.answer(
                "❌ Курс должен быть от 1 до 8.\n"
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
        get_step_text(
            step=6,
            total=REGISTRATION_TOTAL_STEPS,
            title=f"Курс: {format_course_label(course)}",
            question="Выбери свой факультет",
        ),
        parse_mode="HTML",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_faculty)
