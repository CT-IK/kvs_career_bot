import html

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, distinct
from pathlib import Path

from database.models import User, Vacancy, Company, Division
from database.db import async_session_maker
from config import FACULTIES, ADMIN_IDS
from services.course_utils import COURSE_LEVELS, format_course_label, parse_course_callback
from services.user_names import format_full_name, validate_name_part


def get_feedback_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build keyboard for admin actions on user feedback."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить пользователю", callback_data=f"admin_reply_{user_id}")]
        ]
    )


def resolve_image_path(*candidates: Path) -> Path | None:
    """Return the first existing path from provided image candidates."""
    for path in candidates:
        if path.exists():
            return path
    return None


# Пути к картинкам (c fallback по расширениям)
ASSETS_PATH = Path(__file__).parent.parent / "assets" / "images"
MENU_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "menu_picture.jpg",
    ASSETS_PATH / "menu_picture.jpeg",
    ASSETS_PATH / "menu_picture.png",
)
VACANCY_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "vacancy_card.jpg",
    ASSETS_PATH / "vacancy_card.jpeg",
    ASSETS_PATH / "vacancy_card.png",
)
ABOUT_US_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "about_us.jpg",
    ASSETS_PATH / "about_us.jpeg",
    ASSETS_PATH / "about_us.png",
)
COMPANY_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "company_card.jpg",
    ASSETS_PATH / "company_card.jpeg",
    ASSETS_PATH / "company_card.png",
)
DIVISION_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "division_card.jpg",
    ASSETS_PATH / "division_card.jpeg",
    ASSETS_PATH / "division_card.png",
)

router = Router()


# Состояния для обратной связи
class FeedbackStates(StatesGroup):
    waiting_for_message = State()


# Маппинг факультетов из бота в поля БД
FACULTY_TO_DB_FIELD = {
    "ИТиАБД": "itiabd",
    "МЭО": "meo",
    "ФЭБ": "feb",
    "СНиМК": "snimk",
    "НАБ": "nab",
    "ВШУ": "vshu",
    "ФФ": "finfak",
    "ЮФ": "yurfak"
}

# Эмодзи для сфер
SPHERE_EMOJI: dict[str, str] = {}


def normalize_sphere_name(sphere: str | None) -> str | None:
    """Normalize sphere values from DB/callbacks and drop empty ones."""
    if sphere is None:
        return None
    normalized = sphere.strip()
    return normalized or None


async def get_available_spheres(session) -> list[tuple[str, int]]:
    """Return all non-empty vacancy spheres with counts."""
    normalized_sphere = func.trim(Vacancy.sphere)
    result = await session.execute(
        select(normalized_sphere.label("sphere"), func.count(Vacancy.id))
        .where(Vacancy.sphere.is_not(None), normalized_sphere != "")
        .group_by(normalized_sphere)
        .order_by(func.count(Vacancy.id).desc(), normalized_sphere.asc())
    )
    return [(sphere, count) for sphere, count in result.all() if sphere]


async def get_vacancies_for_sphere(session, sphere: str | None) -> list[Vacancy]:
    """Load vacancies for one sphere in the same order as the general list."""
    normalized = normalize_sphere_name(sphere)
    if not normalized:
        return []

    result = await session.execute(
        select(Vacancy)
        .where(func.trim(Vacancy.sphere) == normalized)
        .order_by(Vacancy.created_at.desc())
    )
    return result.scalars().all()


async def get_sphere_vacancies_count(session, sphere: str | None) -> int:
    """Count vacancies for a sphere after normalization."""
    normalized = normalize_sphere_name(sphere)
    if not normalized:
        return 0

    result = await session.execute(
        select(func.count(Vacancy.id))
        .where(func.trim(Vacancy.sphere) == normalized)
    )
    return result.scalar() or 0


def get_main_menu_keyboard(user_faculty: str = None, vacancies_count: int = 0):
    """Главное меню с кнопками"""
    keyboard = [
        [InlineKeyboardButton(text="Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="Обратная связь", callback_data="feedback")],
        [InlineKeyboardButton(text="Компании-партнёры", callback_data="companies_list")],
        [InlineKeyboardButton(text="Вакансии", callback_data="vacancies_menu")],
        [InlineKeyboardButton(text="О нас", callback_data="about_us")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_vacancy_keyboard(vacancy_id: int, current_index: int, total: int, filter_type: str = "all", sphere: str = None, has_company_desc: bool = False, organization: str = None):
    """Клавиатура для навигации по вакансиям"""
    keyboard = []
    
    # Кнопки навигации (в одну строку)
    nav_buttons = []
    
    # Кнопка "В начало" если не на первой
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="❮❮", callback_data=f"vac_{filter_type}_0_{sphere or ''}"))
    
    # Кнопка "Назад"
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="❮",
            callback_data=f"vac_{filter_type}_{current_index - 1}_{sphere or ''}"
        ))
    
    # Счётчик
    nav_buttons.append(InlineKeyboardButton(
        text=f"{current_index + 1}/{total}",
        callback_data="noop"
    ))
    
    # Кнопка "Вперед"
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="❯",
            callback_data=f"vac_{filter_type}_{current_index + 1}_{sphere or ''}"
        ))
    
    # Кнопка "В конец" если не на последней
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="❯❯", callback_data=f"vac_{filter_type}_{total - 1}_{sphere or ''}"))

    keyboard.append(nav_buttons)
    
    # Кнопка "О компании" если есть описание
    if has_company_desc and organization:
        keyboard.append([InlineKeyboardButton(
            text="О компании",
            callback_data=f"about_company_{vacancy_id}_{filter_type}_{current_index}_{sphere or ''}"
        )])
    
    # Последняя строка - действия
    action_buttons = []
    if filter_type == "sphere" and sphere:
        action_buttons.append(InlineKeyboardButton(text="К сферам", callback_data="vacancies_by_sphere"))
    action_buttons.append(InlineKeyboardButton(text="Меню", callback_data="main_menu"))
    keyboard.append(action_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def check_company_has_description(session, organization: str) -> bool:
    """Проверить есть ли у компании описание"""
    if not organization:
        return False
    result = await session.execute(
        select(Company).where(Company.name == organization, Company.description != None, Company.description != "")
    )
    return result.scalar_one_or_none() is not None


def format_vacancy_caption(vacancy: Vacancy) -> str:
    """Форматирование вакансии для caption под картинкой (до 1024 символов)"""

    
    # Компактный формат для caption
    lines = [
        f"💼 <b>Вакансия: </b>{vacancy.position}",
        f"<b>Компания: </b>{vacancy.organization}",
        ""
    ]
    
    # Основная информация
    if vacancy.sphere:
        lines.append(f"<b>Сфера: </b>{vacancy.sphere}")
    if vacancy.salary:
        lines.append(f"<b>Зарплата: </b>{vacancy.salary}")
    if vacancy.schedule:
        lines.append(f"<b>График: </b>{vacancy.schedule}")
    if vacancy.work_format:
        lines.append(f"<b>Формат: </b>{vacancy.work_format}")
    if vacancy.employment_format:
        lines.append(f"<b>Тип занятости: </b>{vacancy.employment_format}")
    
    # Описание (краткое)
    if vacancy.description:
        desc = vacancy.description[:150] + "..." if len(vacancy.description) > 150 else vacancy.description
        lines.append(f"\n<blockquote>{desc}</blockquote>")
    
    text = "\n".join(lines)
    
    # Обрезаем если слишком длинный (лимит Telegram 1024)
    if len(text) > 1000:
        text = text[:997] + "..."
    
    return text


def format_vacancy(vacancy: Vacancy, show_match: bool = False, user_faculty: str = None) -> str:
    """Форматирование вакансии для текстового отображения (используется в меню без картинок)"""
    # Определяем эмодзи для сферы
    lines = [
        f"💼 <b>Вакансия: </b>{vacancy.position}",
        f"<b>Компания: </b>{vacancy.organization}",
        ""
    ]

    # Основная информация
    if vacancy.sphere:
        lines.append(f"<b>Сфера: </b>{vacancy.sphere}")
    if vacancy.salary:
        lines.append(f"<b>Зарплата: </b>{vacancy.salary}")
    if vacancy.schedule:
        lines.append(f"<b>График: </b>{vacancy.schedule}")
    if vacancy.work_format:
        lines.append(f"<b>Формат: </b>{vacancy.work_format}")
    if vacancy.employment_format:
        lines.append(f"<b>Тип занятости: </b>{vacancy.employment_format}")

    # Описание (краткое)
    if vacancy.description:
        desc = vacancy.description[:150] + "..." if len(vacancy.description) > 150 else vacancy.description
        lines.append(f"\n<blockquote>{desc}</blockquote>")

    text = "\n".join(lines)
    # Особенности (бейджи)
    features = []
    if vacancy.feature1:
        features.append(f"✓ {vacancy.feature1}")
    if vacancy.feature2:
        features.append(f"✓ {vacancy.feature2}")
    if vacancy.feature3:
        features.append(f"✓ {vacancy.feature3}")
    
    if features:
        text += f"\n<b>Преимущества:</b>\n" + "\n".join(features)
    
    return text


async def get_user_vacancies_count(session, user_faculty: str) -> int:
    """Получить количество вакансий для факультета пользователя"""
    db_field = FACULTY_TO_DB_FIELD.get(user_faculty)
    if not db_field:
        return 0
    
    filter_condition = getattr(Vacancy, db_field) == True
    result = await session.execute(
        select(func.count(Vacancy.id)).where(filter_condition)
    )
    return result.scalar() or 0


async def show_main_menu_or_registration(message: Message, state: FSMContext, user_id: int):
    """Show registration flow for new users or the main menu for existing ones."""
    await state.clear()

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_registered:
            from handlers.registration import start_registration

            await start_registration(message, state)
            return

        vacancies_count = await get_user_vacancies_count(session, user.faculty)

        welcome_text = f"""
❤️ <b>Комитет Внешних Связей</b> 🖤

Привет, <b>{user.first_name}</b>! 

Для тебя сейчас: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
        keyboard = get_main_menu_keyboard(user.faculty, vacancies_count)

        if MENU_IMAGE_PATH:
            photo = FSInputFile(MENU_IMAGE_PATH)
            await message.answer_photo(
                photo=photo,
                caption=welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start - главное меню"""
    await show_main_menu_or_registration(message, state, message.from_user.id)


@router.message(Command("vacancies"))
async def cmd_vacancies(message: Message):
    """Команда для просмотра вакансий"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_registered:
            await message.answer(
                "❌ Для просмотра вакансий нужно зарегистрироваться.\n"
                "Нажми /start для регистрации."
            )
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        welcome_text = f"""
❤️ <b>Комитет Внешних Связей</b> 🖤

Привет, <b>{user.first_name}</b>! 

Для тебя сейчас: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
        keyboard = get_main_menu_keyboard(user.faculty, vacancies_count)
        
        if MENU_IMAGE_PATH:
            photo = FSInputFile(MENU_IMAGE_PATH)
            await message.answer_photo(
                photo=photo,
                caption=welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Обработка возврата в главное меню"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка", show_alert=True)
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        welcome_text = f"""
❤️ <b>Комитет Внешних Связей</b> 🖤

Привет, <b>{user.first_name}</b>! 

Для тебя сейчас: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
        keyboard = get_main_menu_keyboard(user.faculty, vacancies_count)
        
        # Всегда показываем картинку с caption
        await callback.message.delete()
        if MENU_IMAGE_PATH:
            photo = FSInputFile(MENU_IMAGE_PATH)
            await callback.message.answer_photo(
                photo=photo,
                caption=welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.message.answer(
                welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    """Пустой callback для счётчика"""
    await callback.answer()


@router.callback_query(F.data == "feedback")
async def callback_feedback(callback: CallbackQuery, state: FSMContext):
    """Обратная связь"""
    text = """
        💬 <b>Обратная связь</b>

Напиши своё сообщение, и мы обязательно его получим!

<i>Это может быть вопрос, предложение или сообщение о проблеме.</i>
"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="main_menu")]
    ])
    
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    
    await state.set_state(FeedbackStates.waiting_for_message)
    await callback.answer()


@router.callback_query(F.data == "about_us")
async def callback_about_us(callback: CallbackQuery):
    """О нас"""
    text = """
❤️ <b>О Комитете Внешних Связей</b> 🖤

Комитет Внешних Связей — это часть Студенческого совета Финансового Университета, которая отвечает за взаимодействие со внешними организациями, партнёрами и спонсорами и помогает студентам с карьерой и возможностями вне учёбы.

<b>Наша миссия:</b>
Помочь каждому студенту найти работу мечты и начать успешную карьеру.

<b>Что мы делаем:</b>
• Собираем актуальные вакансии
• Сотрудничаем с топовыми компаниями
• Помогаем с трудоустройством

💼 <b>Присоединяйся к нам!</b>
"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
    ])
    
    await callback.message.delete()
    if ABOUT_US_IMAGE_PATH:
        photo = FSInputFile(ABOUT_US_IMAGE_PATH)
        await callback.message.answer_photo(
            photo=photo,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.message(FeedbackStates.waiting_for_message)
async def process_feedback_message(message: Message, state: FSMContext, bot: Bot):
    """Forward feedback to admins with escaped user content."""
    await state.clear()
    
    # Получаем информацию о пользователе
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
    
    # Формируем сообщение для админов
    user_info_raw = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    user_name_raw = (
        format_full_name(user.first_name, user.last_name, user.patronymic)
        if user else message.from_user.full_name
    )
    faculty_raw = user.faculty if user else "Не указан"
    feedback_text = message.text or message.caption or "[Не текстовое сообщение]"

    user_info = html.escape(user_info_raw)
    user_name = html.escape(user_name_raw)
    faculty = html.escape(faculty_raw)
    feedback_text = html.escape(feedback_text)
    
    admin_text = f"""
<b>Новое сообщение обратной связи</b>

<b>От:</b> {user_name}
<b>Контакт:</b> {user_info}
<b>Факультет:</b> {faculty}

━━━━━━━━━━━━━━━━━━━━
💬 <b>Сообщение:</b>
{feedback_text}
"""
    
    # Отправляем всем админам
    sent_count = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                parse_mode="HTML",
                reply_markup=get_feedback_admin_keyboard(message.from_user.id),
            )
            sent_count += 1
        except Exception:
            pass
    
    # Подтверждение пользователю
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Спасибо за обратную связь. Мы постараемся ответить как можно скорее.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
    )


@router.callback_query(F.data == "vacancies_menu")
async def callback_vacancies_menu(callback: CallbackQuery):
    """Меню вакансий"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка", show_alert=True)
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        text = f"""
          <b>Вакансии</b>

Выбери способ просмотра:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Для меня ({vacancies_count})", callback_data="my_vacancies")],
            [InlineKeyboardButton(text="Все вакансии", callback_data="all_vacancies")],
            [InlineKeyboardButton(text="По сферам", callback_data="vacancies_by_sphere")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
        
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()


@router.callback_query(F.data == "my_vacancies")
async def callback_my_vacancies(callback: CallbackQuery):
    """Показать вакансии для факультета пользователя"""
    async with async_session_maker() as session:
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
        
        if not vacancies:
            await callback.message.edit_text(
                f"😔 <b>Нет вакансий</b>\n\n"
                f"К сожалению, для факультета <b>{user.faculty}</b> пока нет доступных вакансий.\n\n"
                "Попробуй посмотреть все вакансии или зайди позже.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Все вакансии", callback_data="all_vacancies")],
                    [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # Проверяем есть ли описание компании
        has_company_desc = await check_company_has_description(session, vacancy.organization)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "my", has_company_desc=has_company_desc, organization=vacancy.organization)
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
                "😔 <b>Нет вакансий</b>\n\n"
                "В базе пока нет вакансий.\n"
                "Администратор может синхронизировать их из Google Sheets.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # Проверяем есть ли описание компании
        has_company_desc = await check_company_has_description(session, vacancy.organization)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "all", has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data == "vacancies_by_sphere")
async def callback_vacancies_by_sphere(callback: CallbackQuery):
    """Показать вакансии по сферам"""
    async with async_session_maker() as session:
        # Получаем уникальные сферы с количеством вакансий
        spheres = await get_available_spheres(session)
        
        text = "<b>Выбери сферу:</b>\n\n" \
               "Нажми на интересующую сферу, чтобы посмотреть вакансии:"
        
        if not spheres:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
            ])
            text = "😔 Нет вакансий для фильтрации по сферам."
        else:
            keyboard_rows = []
            for sphere, count in spheres:
                keyboard_rows.append([InlineKeyboardButton(
                    text=f"{sphere} ({count})",
                    callback_data=f"sphere_{sphere}"
                )])
            keyboard_rows.append([InlineKeyboardButton(text="Меню", callback_data="main_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        # Если текущее сообщение - фото, удаляем и отправляем текст
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text(
            text,
            parse_mode="HTML",
                reply_markup=keyboard
            )
        await callback.answer()


@router.callback_query(F.data.startswith("sphere_"))
async def callback_sphere_vacancies(callback: CallbackQuery):
    """Показать вакансии конкретной сферы"""
    sphere = normalize_sphere_name(callback.data.replace("sphere_", "", 1))
    if not sphere:
        await callback.answer("Сфера не найдена", show_alert=True)
        return

    async with async_session_maker() as session:
        vacancies = await get_vacancies_for_sphere(session, sphere)
        
        if not vacancies:
            await callback.message.edit_text(
                f"😔 Нет вакансий в сфере «{sphere}»",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="К сферам", callback_data="vacancies_by_sphere")],
                    [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]

        caption =format_vacancy_caption(vacancy)
        
        # Проверяем есть ли описание компании
        has_company_desc = await check_company_has_description(session, vacancy.organization)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "sphere", sphere, has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data.startswith("vac_"))
async def callback_vacancy_navigation(callback: CallbackQuery):
    """Навигация по вакансиям с редактированием картинки"""
    parts = callback.data.split("_", 3)
    if len(parts) < 3:
        await callback.answer("Ошибка навигации", show_alert=True)
        return
    
    filter_type = parts[1]
    target_index = int(parts[2])
    sphere = normalize_sphere_name(parts[3]) if len(parts) > 3 else None
    
    async with async_session_maker() as session:
        if filter_type == "my":
            result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if not user or not user.faculty:
                await callback.answer("Ошибка: факультет не указан", show_alert=True)
                return
            
            db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
            if not db_field:
                await callback.answer("Ошибка", show_alert=True)
                return
            
            filter_condition = getattr(Vacancy, db_field) == True
            result = await session.execute(
                select(Vacancy).where(filter_condition).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        elif filter_type == "sphere" and sphere:
            vacancies = await get_vacancies_for_sphere(session, sphere)
        elif filter_type == "division" and sphere:
            # sphere содержит division_id
            division_id = int(sphere)
            division_result = await session.execute(
                select(Division).where(Division.id == division_id)
            )
            division = division_result.scalar_one_or_none()
            if division:
                company_result = await session.execute(
                    select(Company).where(Company.id == division.company_id)
                )
                company = company_result.scalar_one_or_none()
                if company:
                    result = await session.execute(
                        select(Vacancy).where(
                            Vacancy.organization == company.name,
                            Vacancy.division == division.name
                        ).order_by(Vacancy.created_at.desc())
                    )
                    vacancies = result.scalars().all()
                else:
                    vacancies = []
            else:
                vacancies = []
        elif filter_type == "company" and sphere:
            # sphere содержит company_id
            company_id = int(sphere)
            company_result = await session.execute(
                select(Company).where(Company.id == company_id)
            )
            company = company_result.scalar_one_or_none()
            if company:
                result = await session.execute(
                    select(Vacancy).where(Vacancy.organization == company.name).order_by(Vacancy.created_at.desc())
                )
                vacancies = result.scalars().all()
            else:
                vacancies = []
        else:
            result = await session.execute(
                select(Vacancy).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        
        if target_index < 0 or target_index >= len(vacancies):
            await callback.answer("Достигнут конец списка", show_alert=True)
            return
        
        vacancy = vacancies[target_index]
        
        # Формируем caption
        if filter_type == "sphere" and sphere:
            emoji = SPHERE_EMOJI.get(sphere, "💼")
            caption = f"{emoji} <b>Сфера: {sphere}</b>\n\n" + format_vacancy_caption(vacancy)
        else:
            caption = format_vacancy_caption(vacancy)
        
        # Проверяем есть ли описание компании
        has_company_desc = await check_company_has_description(session, vacancy.organization)
        
        # Получаем или генерируем изображение
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        
        # Редактируем медиа (картинку) вместо текста
        new_media = InputMediaPhoto(
            media=photo,
            caption=caption,
            parse_mode="HTML"
        )
        
        await callback.message.edit_media(
            media=new_media,
            reply_markup=get_vacancy_keyboard(vacancy.id, target_index, len(vacancies), filter_type, sphere, has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    """Профиль пользователя"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("Ошибка: пользователь не найден", show_alert=True)
            return
        
        # Получаем количество вакансий для пользователя
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        text = f"""
          👤 <b>Мой профиль</b>

<b>Имя:</b> {user.first_name}
<b>Фамилия:</b> {user.last_name}
<b>Отчество:</b> {user.patronymic or "--"}
<b>Курс:</b> {format_course_label(user.course)}
<b>Факультет:</b> {user.faculty}
<b>Откуда узнал:</b> {user.info_source}


Доступно вакансий: <b>{vacancies_count}</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Изменить ФИО", callback_data="edit_name")],
            [InlineKeyboardButton(text="Изменить курс", callback_data="edit_course")],
            [InlineKeyboardButton(text="Изменить факультет", callback_data="edit_faculty")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
        
        # Если текущее сообщение - фото, удаляем и отправляем текст
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        await callback.answer()


@router.callback_query(F.data == "companies_list")
async def callback_companies_list(callback: CallbackQuery):
    """Показать список компаний для пользователя"""
    async with async_session_maker() as session:
        vacancy_companies_result = await session.execute(
            select(distinct(Vacancy.organization))
            .where(Vacancy.organization.isnot(None), Vacancy.organization != "")
        )
        vacancy_companies = {row[0] for row in vacancy_companies_result.all() if row[0]}

        if vacancy_companies:
            existing_companies_result = await session.execute(
                select(Company).where(Company.name.in_(vacancy_companies))
            )
            existing_company_names = {company.name for company in existing_companies_result.scalars().all()}
            missing_company_names = sorted(vacancy_companies - existing_company_names)
            for company_name in missing_company_names:
                session.add(Company(name=company_name, description=None))
            if missing_company_names:
                await session.commit()

        # Получаем все компании, даже если описание пока не заполнено
        result = await session.execute(
            select(Company)
            .where(Company.name.isnot(None), Company.name != "")
            .order_by(Company.name)
        )
        companies = result.scalars().all()
        
        if not companies:
            # Если текущее сообщение - фото, удаляем и отправляем текст
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(
                    "<b>Компании</b>\n\n"
                    "Пока нет информации о компаниях.\n"
                    "Загляни позже!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
                    ])
                )
            else:
                await callback.message.edit_text(
                    "<b>Компании</b>\n\n"
                    "Пока нет информации о компаниях.\n"
                    "Загляни позже!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
                    ])
                )
            await callback.answer()
            return
        
        text = f"""
          <b>Компании</b>

Выбери компанию, чтобы узнать о ней больше:
"""
        
        # Создаём кнопки для каждой компании
        keyboard = []
        for company in companies:
            keyboard.append([
                InlineKeyboardButton(
                    text=f" {company.name}",
                    callback_data=f"view_company_{company.id}"
                )
            ])
        keyboard.append([InlineKeyboardButton(text="Меню", callback_data="main_menu")])
        
        # Если текущее сообщение - фото, удаляем и отправляем текст
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        else:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        await callback.answer()


@router.callback_query(F.data.startswith("view_company_"))
async def callback_view_company(callback: CallbackQuery):
    """Показать информацию о компании"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(Company).where(Company.id == company_id)
        )
        company = result.scalar_one_or_none()
        
        if not company:
            await callback.answer("Компания не найдена", show_alert=True)
            return
        
        # Считаем количество вакансий от этой компании
        vacancies_result = await session.execute(
            select(func.count(Vacancy.id)).where(Vacancy.organization == company.name)
        )
        vacancies_count = vacancies_result.scalar() or 0
        
        # Проверяем есть ли подразделения
        divisions_result = await session.execute(
            select(Division).where(Division.company_id == company_id)
        )
        divisions = divisions_result.scalars().all()
        
        text = f"""
<b>{company.name}</b>

{company.description or 'Описание отсутствует'}

Вакансий: <b>{vacancies_count}</b>
Подразделений: <b>{len(divisions)}</b>
"""
        
        # Формируем клавиатуру
        keyboard_buttons = []
        if divisions:
            keyboard_buttons.append([InlineKeyboardButton(text="Подразделения", callback_data=f"company_divisions_{company_id}")])
        if vacancies_count > 0:
            keyboard_buttons.append([InlineKeyboardButton(text="Все вакансии компании", callback_data=f"company_vacancies_{company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="К списку компаний", callback_data="companies_list")])
        keyboard_buttons.append([InlineKeyboardButton(text="Меню", callback_data="main_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Показываем картинку с caption
        await callback.message.delete()
        if COMPANY_IMAGE_PATH:
            photo = FSInputFile(COMPANY_IMAGE_PATH)
            await callback.message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        await callback.answer()


@router.callback_query(F.data.startswith("company_divisions_"))
async def callback_company_divisions(callback: CallbackQuery):
    """Список подразделений компании"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # Получаем компанию
        company_result = await session.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            await callback.answer("Компания не найдена", show_alert=True)
            return
        
        # Получаем подразделения
        divisions_result = await session.execute(
            select(Division).where(Division.company_id == company_id).order_by(Division.name)
        )
        divisions = divisions_result.scalars().all()
        
        if not divisions:
            await callback.answer("У этой компании нет подразделений", show_alert=True)
            return
        
        text = f"""
<b>Подразделения {company.name}</b>

Выбери подразделение:
"""
        
        # Кнопки подразделений
        keyboard_buttons = []
        for div in divisions:
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"{div.name}", callback_data=f"view_division_{div.id}")
            ])
        keyboard_buttons.append([InlineKeyboardButton(text="К компании", callback_data=f"view_company_{company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="Меню", callback_data="main_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.delete()
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()


@router.callback_query(F.data.startswith("view_division_"))
async def callback_view_division(callback: CallbackQuery):
    """Просмотр подразделения"""
    division_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # Получаем подразделение с компанией
        division_result = await session.execute(
            select(Division).where(Division.id == division_id)
        )
        division = division_result.scalar_one_or_none()
        
        if not division:
            await callback.answer("Подразделение не найдено", show_alert=True)
            return
        
        # Получаем компанию
        company_result = await session.execute(
            select(Company).where(Company.id == division.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        # Считаем вакансии подразделения
        vacancies_result = await session.execute(
            select(func.count(Vacancy.id)).where(
                Vacancy.organization == company.name,
                Vacancy.division == division.name
            )
        )
        vacancies_count = vacancies_result.scalar() or 0
        
        text = f"""
<b>{division.name}</b>
{company.name}

{division.description or 'Описание подразделения'}

Вакансий: <b>{vacancies_count}</b>
"""
        
        # Формируем клавиатуру
        keyboard_buttons = []
        if vacancies_count > 0:
            keyboard_buttons.append([InlineKeyboardButton(text="Вакансии подразделения", callback_data=f"division_vacancies_{division_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="К подразделениям", callback_data=f"company_divisions_{division.company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="Меню", callback_data="main_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Показываем картинку с caption
        await callback.message.delete()
        if DIVISION_IMAGE_PATH:
            photo = FSInputFile(DIVISION_IMAGE_PATH)
            await callback.message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        await callback.answer()


@router.callback_query(F.data.startswith("division_vacancies_"))
async def callback_division_vacancies(callback: CallbackQuery):
    """Вакансии подразделения"""
    division_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # Получаем подразделение
        division_result = await session.execute(
            select(Division).where(Division.id == division_id)
        )
        division = division_result.scalar_one_or_none()
        
        if not division:
            await callback.answer("Подразделение не найдено", show_alert=True)
            return
        
        # Получаем компанию
        company_result = await session.execute(
            select(Company).where(Company.id == division.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        # Получаем вакансии подразделения
        vacancies_result = await session.execute(
            select(Vacancy).where(
                Vacancy.organization == company.name,
                Vacancy.division == division.name
            ).order_by(Vacancy.created_at.desc())
        )
        vacancies = vacancies_result.scalars().all()
        
        if not vacancies:
            await callback.answer("Нет вакансий в этом подразделении", show_alert=True)
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        keyboard = get_vacancy_keyboard(
            vacancy.id, 0, len(vacancies), 
            filter_type="division", 
            sphere=str(division_id),
            has_company_desc=True,
            organization=vacancy.organization
        )
        
        await callback.message.delete()
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()


@router.callback_query(F.data.startswith("company_vacancies_"))
async def callback_company_vacancies(callback: CallbackQuery):
    """Все вакансии компании"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # Получаем компанию
        company_result = await session.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            await callback.answer("Компания не найдена", show_alert=True)
            return
        
        # Получаем вакансии компании
        vacancies_result = await session.execute(
            select(Vacancy).where(Vacancy.organization == company.name).order_by(Vacancy.created_at.desc())
        )
        vacancies = vacancies_result.scalars().all()
        
        if not vacancies:
            await callback.answer("Нет вакансий от этой компании", show_alert=True)
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        keyboard = get_vacancy_keyboard(
            vacancy.id, 0, len(vacancies), 
            filter_type="company", 
            sphere=str(company_id),
            has_company_desc=True,
            organization=vacancy.organization
        )
        
        await callback.message.delete()
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()


# Состояния для редактирования профиля
class EditProfileStates(StatesGroup):
    editing_name = State()
    editing_course = State()
    editing_faculty = State()


@router.callback_query(F.data == "edit_name")
async def callback_edit_name(callback: CallbackQuery, state: FSMContext):
    """Редактирование ФИО"""
    await callback.message.edit_text(
        "✏️ <b>Редактирование ФИО</b>\n\n"
        "Введи новое имя, фамилию и отчество через пробел.\n"
        'Если отчества нет, напиши: <b>Нет</b>\n\n'
        "<i>Например: Иван Иванов Нет</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
        ])
    )
    await state.set_state(EditProfileStates.editing_name)
    await callback.answer()


@router.message(EditProfileStates.editing_name)
async def process_edit_name(message: Message, state: FSMContext):
    """Обработка нового ФИО"""
    # Если пользователь ввёл команду - игнорируем
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    parts = message.text.strip().split()
    
    if len(parts) != 3:
        await message.answer(
            "❌ Введи имя, фамилию и отчество через пробел.\n"
            'Если отчества нет, напиши: <b>Нет</b>\n'
            "<i>Например: Иван Иванов Нет</i>",
            parse_mode="HTML"
        )
        return
    
    first_name_raw, last_name_raw, patronymic_raw = parts
    first_name_valid, first_name, first_name_error = validate_name_part(first_name_raw, "Имя")
    if not first_name_valid:
        await message.answer(first_name_error)
        return

    last_name_valid, last_name, last_name_error = validate_name_part(last_name_raw, "Фамилия")
    if not last_name_valid:
        await message.answer(last_name_error)
        return

    patronymic_valid, patronymic, patronymic_error = validate_name_part(
        patronymic_raw,
        "Отчество",
        allow_none_literal=True
    )
    if not patronymic_valid:
        await message.answer(patronymic_error + '\nЕсли отчества нет, напиши "Нет".')
        return
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.first_name = first_name
            user.last_name = last_name
            user.patronymic = patronymic
            await session.commit()
    
    await state.clear()
    await message.answer(
        f"✅ ФИО изменено на: <b>{format_full_name(first_name, last_name, patronymic)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
    )


@router.callback_query(F.data == "edit_course")
async def callback_edit_course(callback: CallbackQuery, state: FSMContext):
    """Редактирование курса"""
    keyboard_rows = []
    for level_key, level_title, years, _offset in COURSE_LEVELS:
        keyboard_rows.append([InlineKeyboardButton(text=level_title, callback_data="noop")])
        keyboard_rows.append([
            InlineKeyboardButton(text=str(year), callback_data=f"set_course_{level_key}_{year}")
            for year in years
        ])
    keyboard_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="profile")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback.message.edit_text(
        "<b>Выбери свой курс:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_course_"))
async def callback_set_course(callback: CallbackQuery):
    """Установка курса"""
    _level, _year, course = parse_course_callback(callback.data, "set_course")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.course = course
            await session.commit()
    
    await callback.message.edit_text(
        f"✅ Курс изменён на: <b>{format_course_label(course)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "edit_faculty")
async def callback_edit_faculty(callback: CallbackQuery):
    """Редактирование факультета"""
    keyboard = []
    row = []
    for faculty in FACULTIES.values():
        row.append(InlineKeyboardButton(text=faculty, callback_data=f"set_faculty_{faculty}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="profile")])
    
    await callback.message.edit_text(
        "<b>Выбери свой факультет:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_faculty_"))
async def callback_set_faculty(callback: CallbackQuery):
    """Установка факультета"""
    faculty = callback.data.replace("set_faculty_", "")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.faculty = faculty
            await session.commit()
        
        # Получаем новое количество вакансий
        vacancies_count = await get_user_vacancies_count(session, faculty)
        
        await callback.message.edit_text(
        f"✅ Факультет изменён на: <b>{faculty}</b>\n\n"
        f"Теперь тебе доступно <b>{vacancies_count}</b> вакансий!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Посмотреть вакансии", callback_data="my_vacancies")],
            [InlineKeyboardButton(text="К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
        ])
    )
    await callback.answer()


# ==================== О КОМПАНИИ ====================

@router.callback_query(F.data.startswith("about_company_"))
async def callback_about_company(callback: CallbackQuery):
    """Показать информацию о компании"""
    # Формат: about_company_{vacancy_id}_{filter_type}_{index}_{sphere}
    parts = callback.data.split("_", 5)
    if len(parts) < 5:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    vacancy_id = int(parts[2])
    filter_type = parts[3]
    current_index = int(parts[4])
    sphere = normalize_sphere_name(parts[5]) if len(parts) > 5 else None
    
    async with async_session_maker() as session:
        # Получаем вакансию
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()
        
        if not vacancy:
            await callback.answer("Вакансия не найдена", show_alert=True)
            return
        
        # Получаем описание компании
        company_result = await session.execute(
            select(Company).where(Company.name == vacancy.organization)
        )
        company = company_result.scalar_one_or_none()
        
        if not company or not company.description:
            await callback.answer("Описание компании не найдено", show_alert=True)
            return
        
        # Формируем текст
        text = f"<b>{vacancy.organization}</b>\n\n"
        text += f"{company.description}"
        
        # Удаляем фото и показываем текст
        await callback.message.delete()
        
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Назад к вакансии",
                    callback_data=f"back_to_vac_{vacancy_id}_{filter_type}_{current_index}_{sphere or ''}"
                )],
                [InlineKeyboardButton(text="Меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()


@router.callback_query(F.data.startswith("back_to_vac_"))
async def callback_back_to_vacancy(callback: CallbackQuery):
    """Вернуться к вакансии из описания компании"""
    # Формат: back_to_vac_{vacancy_id}_{filter_type}_{index}_{sphere}
    parts = callback.data.split("_", 6)
    if len(parts) < 6:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    vacancy_id = int(parts[3])
    filter_type = parts[4]
    current_index = int(parts[5])
    sphere = normalize_sphere_name(parts[6]) if len(parts) > 6 else None
    
    async with async_session_maker() as session:
        # Получаем вакансию
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()
        
        if not vacancy:
            await callback.answer("Вакансия не найдена", show_alert=True)
            return
        
        # Получаем общее количество вакансий для правильной навигации
        if filter_type == "my":
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if user and user.faculty:
                db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
                if db_field:
                    filter_condition = getattr(Vacancy, db_field) == True
                    count_result = await session.execute(
                        select(func.count(Vacancy.id)).where(filter_condition)
                    )
                    total = count_result.scalar() or 1
                else:
                    total = 1
            else:
                total = 1
        elif filter_type == "sphere" and sphere:
            total = await get_sphere_vacancies_count(session, sphere) or 1
        else:
            count_result = await session.execute(
                select(func.count(Vacancy.id))
            )
            total = count_result.scalar() or 1
        
        # Формируем caption
        if filter_type == "sphere" and sphere:
            emoji = SPHERE_EMOJI.get(sphere, "💼")
            caption = f"{emoji} <b>Сфера: {sphere}</b>\n\n" + format_vacancy_caption(vacancy)
        else:
            caption = format_vacancy_caption(vacancy)
        
        # Проверяем есть ли описание компании
        has_company_desc = await check_company_has_description(session, vacancy.organization)
        
        # Удаляем текст и отправляем фото
        await callback.message.delete()
        
        photo = FSInputFile(VACANCY_IMAGE_PATH)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, current_index, total, filter_type, sphere, has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()
