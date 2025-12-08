from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, distinct
from database.models import User, Vacancy
from database.db import async_session_maker
from config import FACULTIES
from services.image_generator import get_cached_or_generate

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

# Эмодзи для сфер
SPHERE_EMOJI = {
    "IT": "💻",
    "Финансы": "💰",
    "Маркетинг": "📢",
    "Юриспруденция": "⚖️",
    "Логистика": "🚛",
    "Образование": "📚",
    "Медицина": "🏥",
    "Строительство": "🏗️",
    "Торговля": "🛒",
    "Консалтинг": "📊",
}


def get_main_menu_keyboard(user_faculty: str = None, vacancies_count: int = 0):
    """Главное меню с кнопками"""
    keyboard = [
        [InlineKeyboardButton(text=f"🎯 Для меня ({vacancies_count})", callback_data="my_vacancies")],
        [InlineKeyboardButton(text="🔍 Все вакансии", callback_data="all_vacancies")],
        [InlineKeyboardButton(text="📂 По сферам", callback_data="vacancies_by_sphere")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_vacancy_keyboard(vacancy_id: int, current_index: int, total: int, filter_type: str = "all", sphere: str = None):
    """Клавиатура для навигации по вакансиям"""
    keyboard = []
    
    # Кнопки навигации (в одну строку)
    nav_buttons = []
    
    # Кнопка "В начало" если не на первой
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="⏮️", callback_data=f"vac_{filter_type}_0_{sphere or ''}"))
    
    # Кнопка "Назад"
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️", 
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
            text="▶️", 
            callback_data=f"vac_{filter_type}_{current_index + 1}_{sphere or ''}"
        ))
    
    # Кнопка "В конец" если не на последней
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="⏭️", callback_data=f"vac_{filter_type}_{total - 1}_{sphere or ''}"))
    
    keyboard.append(nav_buttons)
    
    # Вторая строка - действия
    action_buttons = []
    if filter_type == "sphere" and sphere:
        action_buttons.append(InlineKeyboardButton(text="📂 К сферам", callback_data="vacancies_by_sphere"))
    action_buttons.append(InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"))
    keyboard.append(action_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_vacancy_caption(vacancy: Vacancy) -> str:
    """Форматирование вакансии для caption под картинкой (до 1024 символов)"""
    sphere_emoji = SPHERE_EMOJI.get(vacancy.sphere, "💼")
    
    # Компактный формат для caption
    lines = [
        f"🏢 <b>{vacancy.organization}</b>",
        f"📌 <b>{vacancy.position}</b>",
        ""
    ]
    
    # Основная информация
    if vacancy.sphere:
        lines.append(f"{sphere_emoji} {vacancy.sphere}")
    if vacancy.salary:
        lines.append(f"💵 {vacancy.salary}")
    if vacancy.schedule:
        lines.append(f"⏰ {vacancy.schedule}")
    if vacancy.work_format:
        lines.append(f"📍 {vacancy.work_format}")
    if vacancy.employment_format:
        lines.append(f"📋 {vacancy.employment_format}")
    
    # Описание (краткое)
    if vacancy.description:
        desc = vacancy.description[:150] + "..." if len(vacancy.description) > 150 else vacancy.description
        lines.append(f"\n📝 {desc}")
    
    text = "\n".join(lines)
    
    # Обрезаем если слишком длинный (лимит Telegram 1024)
    if len(text) > 1000:
        text = text[:997] + "..."
    
    return text


def format_vacancy(vacancy: Vacancy, show_match: bool = False, user_faculty: str = None) -> str:
    """Форматирование вакансии для текстового отображения (используется в меню без картинок)"""
    # Определяем эмодзи для сферы
    sphere_emoji = SPHERE_EMOJI.get(vacancy.sphere, "💼")
    
    # Заголовок с организацией
    text = f"━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🏢 <b>{vacancy.organization}</b>\n"
    text += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Должность (крупно)
    text += f"📌 <b>{vacancy.position}</b>\n\n"
    
    # Основная информация в компактном виде
    info_lines = []
    if vacancy.sphere:
        info_lines.append(f"{sphere_emoji} {vacancy.sphere}")
    if vacancy.salary:
        info_lines.append(f"💵 {vacancy.salary}")
    if vacancy.schedule:
        info_lines.append(f"⏰ {vacancy.schedule}")
    if vacancy.work_format:
        info_lines.append(f"📍 {vacancy.work_format}")
    if vacancy.employment_format:
        info_lines.append(f"📋 {vacancy.employment_format}")
    
    if info_lines:
        text += "\n".join(info_lines) + "\n"
    
    # Описание
    if vacancy.description:
        desc = vacancy.description[:300] + "..." if len(vacancy.description) > 300 else vacancy.description
        text += f"\n📝 {desc}\n"
    
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


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start - главное меню"""
    await state.clear()
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_registered:
            # Не зарегистрирован - показываем приветствие для регистрации
            from handlers.registration import start_registration
            await start_registration(message, state)
            return
        
        # Получаем количество вакансий для пользователя
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        # Красивое приветствие
        welcome_text = f"""
╔══════════════════════════╗
   🎓 <b>Комитет Внешних Связей</b>
╚══════════════════════════╝

Привет, <b>{user.first_name}</b>! 👋

📚 Факультет: <b>{user.faculty}</b>
🎯 Для тебя: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
        await message.answer(
            welcome_text,
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard(user.faculty, vacancies_count)
        )


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
        
        await message.answer(
            f"🎯 <b>Раздел вакансий</b>\n\n"
            f"Для тебя доступно <b>{vacancies_count}</b> вакансий",
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard(user.faculty, vacancies_count)
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
╔══════════════════════════╗
      🎓 <b>Комитет Внешних Связей</b>
╚══════════════════════════╝

Привет, <b>{user.first_name}</b>! 👋

📚 Факультет: <b>{user.faculty}</b>
🎯 Для тебя: <b>{vacancies_count}</b> вакансий

Выбери действие:
"""
        # Если текущее сообщение - фото, удаляем и отправляем текст
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(
                welcome_text,
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard(user.faculty, vacancies_count)
            )
        else:
            await callback.message.edit_text(
                welcome_text,
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard(user.faculty, vacancies_count)
            )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    """Пустой callback для счётчика"""
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
                    [InlineKeyboardButton(text="🔍 Все вакансии", callback_data="all_vacancies")],
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        image_bytes = get_cached_or_generate(vacancy)
        photo = BufferedInputFile(image_bytes, filename=f"vacancy_{vacancy.id}.png")
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
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
                "😔 <b>Нет вакансий</b>\n\n"
                "В базе пока нет вакансий.\n"
                "Администратор может синхронизировать их из Google Sheets.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        image_bytes = get_cached_or_generate(vacancy)
        photo = BufferedInputFile(image_bytes, filename=f"vacancy_{vacancy.id}.png")
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "all")
        )
        await callback.answer()


@router.callback_query(F.data == "vacancies_by_sphere")
async def callback_vacancies_by_sphere(callback: CallbackQuery):
    """Показать вакансии по сферам"""
    async with async_session_maker() as session:
        # Получаем уникальные сферы с количеством вакансий
        result = await session.execute(
            select(Vacancy.sphere, func.count(Vacancy.id))
            .where(Vacancy.sphere != None, Vacancy.sphere != "")
            .group_by(Vacancy.sphere)
            .order_by(func.count(Vacancy.id).desc())
        )
        spheres = result.all()
        
        text = "📂 <b>Выбери сферу:</b>\n\n" \
               "Нажми на интересующую сферу, чтобы посмотреть вакансии:"
        
        if not spheres:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
            ])
            text = "😔 Нет вакансий для фильтрации по сферам."
        else:
            keyboard_rows = []
            for sphere, count in spheres:
                emoji = SPHERE_EMOJI.get(sphere, "💼")
                keyboard_rows.append([InlineKeyboardButton(
                    text=f"{emoji} {sphere} ({count})",
                    callback_data=f"sphere_{sphere}"
                )])
            keyboard_rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")])
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
    sphere = callback.data.replace("sphere_", "")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(Vacancy).where(Vacancy.sphere == sphere).order_by(Vacancy.created_at.desc())
        )
        vacancies = result.scalars().all()
        
        if not vacancies:
            await callback.message.edit_text(
                f"😔 Нет вакансий в сфере «{sphere}»",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📂 К сферам", callback_data="vacancies_by_sphere")],
                    [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        emoji = SPHERE_EMOJI.get(sphere, "💼")
        caption = f"{emoji} <b>Сфера: {sphere}</b>\n\n" + format_vacancy_caption(vacancy)
        
        # Удаляем старое сообщение и отправляем фото
        await callback.message.delete()
        
        image_bytes = get_cached_or_generate(vacancy)
        photo = BufferedInputFile(image_bytes, filename=f"vacancy_{vacancy.id}.png")
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "sphere", sphere)
        )
        await callback.answer()


@router.callback_query(F.data.startswith("vac_"))
async def callback_vacancy_navigation(callback: CallbackQuery):
    """Навигация по вакансиям с редактированием картинки"""
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("Ошибка навигации", show_alert=True)
        return
    
    filter_type = parts[1]
    target_index = int(parts[2])
    sphere = parts[3] if len(parts) > 3 and parts[3] else None
    
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
            result = await session.execute(
                select(Vacancy).where(Vacancy.sphere == sphere).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
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
        
        # Получаем или генерируем изображение
        image_bytes = get_cached_or_generate(vacancy)
        photo = BufferedInputFile(image_bytes, filename=f"vacancy_{vacancy.id}.png")
        
        # Редактируем медиа (картинку) вместо текста
        new_media = InputMediaPhoto(
            media=photo,
            caption=caption,
            parse_mode="HTML"
        )
        
        await callback.message.edit_media(
            media=new_media,
            reply_markup=get_vacancy_keyboard(vacancy.id, target_index, len(vacancies), filter_type, sphere)
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
╔══════════════════════════╗
          👤 <b>Мой профиль</b>
╚══════════════════════════╝

👤 <b>Имя:</b> {user.first_name}
👤 <b>Фамилия:</b> {user.last_name}
🎓 <b>Курс:</b> {user.course}
🏛️ <b>Факультет:</b> {user.faculty}
📢 <b>Откуда узнал:</b> {user.info_source}

━━━━━━━━━━━━━━━━━━━━
🎯 Доступно вакансий: <b>{vacancies_count}</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_name")],
            [InlineKeyboardButton(text="🎓 Изменить курс", callback_data="edit_course")],
            [InlineKeyboardButton(text="🏛️ Изменить факультет", callback_data="edit_faculty")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
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


# Состояния для редактирования профиля
class EditProfileStates(StatesGroup):
    editing_name = State()
    editing_course = State()
    editing_faculty = State()


@router.callback_query(F.data == "edit_name")
async def callback_edit_name(callback: CallbackQuery, state: FSMContext):
    """Редактирование имени"""
    await callback.message.edit_text(
        "✏️ <b>Редактирование имени</b>\n\n"
        "Введи новое имя и фамилию через пробел:\n"
        "<i>Например: Иван Иванов</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
        ])
    )
    await state.set_state(EditProfileStates.editing_name)
    await callback.answer()


@router.message(EditProfileStates.editing_name)
async def process_edit_name(message: Message, state: FSMContext):
    """Обработка нового имени"""
    # Если пользователь ввёл команду - игнорируем
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    parts = message.text.strip().split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Введи имя и фамилию через пробел.\n"
            "<i>Например: Иван Иванов</i>",
            parse_mode="HTML"
        )
        return
    
    first_name, last_name = parts[0], parts[1]
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.first_name = first_name
            user.last_name = last_name
            await session.commit()
    
    await state.clear()
    await message.answer(
        f"✅ Имя изменено на: <b>{first_name} {last_name}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
        ])
    )


@router.callback_query(F.data == "edit_course")
async def callback_edit_course(callback: CallbackQuery, state: FSMContext):
    """Редактирование курса"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="set_course_1"),
            InlineKeyboardButton(text="2", callback_data="set_course_2"),
            InlineKeyboardButton(text="3", callback_data="set_course_3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="set_course_4"),
            InlineKeyboardButton(text="5", callback_data="set_course_5"),
            InlineKeyboardButton(text="6", callback_data="set_course_6"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
    ])
    
    await callback.message.edit_text(
        "🎓 <b>Выбери свой курс:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_course_"))
async def callback_set_course(callback: CallbackQuery):
    """Установка курса"""
    course = int(callback.data.replace("set_course_", ""))
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.course = course
            await session.commit()
    
    await callback.message.edit_text(
        f"✅ Курс изменён на: <b>{course}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
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
        "🏛️ <b>Выбери свой факультет:</b>",
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
        f"🎯 Теперь тебе доступно <b>{vacancies_count}</b> вакансий!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Посмотреть вакансии", callback_data="my_vacancies")],
            [InlineKeyboardButton(text="👤 К профилю", callback_data="profile")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
        ])
    )
    await callback.answer()
