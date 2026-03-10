import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from sqlalchemy import distinct, func, select

from config import ADMIN_IDS
from database.db import async_session_maker
from database.models import Company, Statistics, User, Vacancy
from services.google_sheets import sync_vacancies_to_db

router = Router()


class CompanyEditStates(StatesGroup):
    """FSM states for company description editing."""

    waiting_for_description = State()


def is_admin(user_id: int) -> bool:
    """Return True when user is bot admin."""
    return user_id in ADMIN_IDS


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Build admin panel keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Синхронизировать вакансии", callback_data="admin_sync")],
            [InlineKeyboardButton(text="🏢 Компании", callback_data="admin_companies")],
            [InlineKeyboardButton(text="📊 Обновить статистику", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")],
        ]
    )


async def get_stats_text() -> str:
    """Collect and format admin dashboard statistics."""
    async with async_session_maker() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        registered_users = (
            await session.execute(select(func.count(User.id)).where(User.is_registered.is_(True)))
        ).scalar() or 0
        total_vacancies = (await session.execute(select(func.count(Vacancy.id)))).scalar() or 0
        total_company_descriptions = (
            await session.execute(select(func.count(Company.id)).where(Company.description.isnot(None), Company.description != ""))
        ).scalar() or 0
        total_stats_rows = (await session.execute(select(func.count(Statistics.id)))).scalar() or 0

        faculties_stats: dict[str, int] = {}
        for faculty in ["ИТиАБД", "МЭО", "ФЭБ", "СНиМК", "НАБ", "ВШУ", "ФФ", "ЮФ"]:
            count = (await session.execute(select(func.count(User.id)).where(User.faculty == faculty))).scalar() or 0
            if count:
                faculties_stats[faculty] = count

        sources_stats: dict[str, int] = {}
        for source in ["ВК-группа проекта", "ВК/Тг информера факультета", "от одногруппников", "от Координатора"]:
            count = (await session.execute(select(func.count(User.id)).where(User.info_source == source))).scalar() or 0
            if count:
                sources_stats[source] = count

    lines = [
        "🔐 <b>Админ-панель</b>",
        "",
        "👥 <b>Пользователи:</b>",
        f"   📊 Всего: <b>{total_users}</b>",
        f"   ✅ Зарегистрировано: <b>{registered_users}</b>",
        f"   ⏳ Не зарегистрировано: <b>{total_users - registered_users}</b>",
        "",
        f"📋 <b>Вакансии в базе:</b> <b>{total_vacancies}</b>",
        f"🏢 <b>Компаний с описанием:</b> <b>{total_company_descriptions}</b>",
        f"📈 <b>Строк статистики:</b> <b>{total_stats_rows}</b>",
        "",
    ]

    if faculties_stats:
        lines.append("🎓 <b>По факультетам:</b>")
        for faculty, count in faculties_stats.items():
            lines.append(f"   • {faculty}: {count}")
        lines.append("")

    if sources_stats:
        lines.append("📢 <b>Источники:</b>")
        for source, count in sources_stats.items():
            lines.append(f"   • {source}: {count}")

    return "\n".join(lines)


async def ensure_companies_from_vacancies() -> None:
    """Create missing `Company` rows from vacancy organizations."""
    async with async_session_maker() as session:
        organizations_result = await session.execute(
            select(distinct(Vacancy.organization))
            .where(Vacancy.organization.isnot(None), Vacancy.organization != "")
            .order_by(Vacancy.organization)
        )
        organizations = [row[0] for row in organizations_result.all() if row[0]]
        if not organizations:
            return

        existing_result = await session.execute(select(Company.name))
        existing = {row[0] for row in existing_result.all()}
        created = False
        for organization in organizations:
            if organization not in existing:
                session.add(Company(name=organization, description=None))
                created = True
        if created:
            await session.commit()


def companies_keyboard(companies: list[Company], back_callback: str = "admin_back") -> InlineKeyboardMarkup:
    """Build inline keyboard for company editing list."""
    rows = []
    for company in companies:
        marker = "✅" if company.description else "➖"
        display_name = company.name if len(company.name) <= 30 else f"{company.name[:27]}..."
        rows.append([InlineKeyboardButton(text=f"{marker} {display_name}", callback_data=f"comp_edit_{company.id}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Open admin panel."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к админ панели.")
        return

    await message.answer("🔐", reply_markup=ReplyKeyboardRemove())
    await message.answer(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery) -> None:
    """Refresh admin panel stats."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())
    await callback.answer("📊 Статистика обновлена")


@router.callback_query(F.data == "admin_sync")
async def callback_admin_sync(callback: CallbackQuery) -> None:
    """Sync vacancies from Google Sheets via inline button."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.answer("🔄 Начинаю синхронизацию...")
    await callback.message.edit_text(
        "🔄 <b>Синхронизация вакансий...</b>\n\n⏳ Загружаю данные из Google Sheets...",
        parse_mode="HTML",
    )

    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        await callback.message.edit_text(
            f"{await get_stats_text()}\n\n✅ <b>Синхронизировано: {synced_count} вакансий</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
    except Exception as exc:
        await callback.message.edit_text(
            f"❌ <b>Ошибка синхронизации:</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )


@router.message(Command("sync_vacancies"))
async def cmd_sync_vacancies(message: Message) -> None:
    """Sync vacancies from Google Sheets via command."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде.")
        return

    await message.answer(
        "🔄 <b>Синхронизация вакансий...</b>\n\n⏳ Загружаю данные из Google Sheets...",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        await message.answer(
            f"✅ <b>Синхронизация завершена!</b>\n\n📊 Загружено вакансий: <b>{synced_count}</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
    except Exception as exc:
        await message.answer(
            f"❌ <b>Ошибка при синхронизации:</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )


@router.callback_query(F.data == "admin_companies")
async def callback_admin_companies(callback: CallbackQuery) -> None:
    """Show companies list for admin description editing."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await ensure_companies_from_vacancies()
    async with async_session_maker() as session:
        companies = (
            await session.execute(select(Company).where(Company.name.isnot(None), Company.name != "").order_by(Company.name))
        ).scalars().all()

    if not companies:
        await callback.message.edit_text(
            "🏢 <b>Компании</b>\n\nВ базе пока нет компаний.\nСначала синхронизируй вакансии.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]
            ),
        )
        return

    with_description = sum(1 for company in companies if company.description)
    text = (
        "🏢 <b>Компании</b>\n\n"
        f"Всего: <b>{len(companies)}</b>\n"
        f"С описанием: <b>{with_description}</b>\n\n"
        "Выбери компанию для редактирования:"
    )

    # Avoid overly large keyboards for Telegram limits.
    preview = companies[:40]
    keyboard = companies_keyboard(preview)
    if len(companies) > len(preview):
        keyboard.inline_keyboard.insert(
            -1, [InlineKeyboardButton(text=f"📋 Показать все ({len(companies)})", callback_data="comp_list_all")]
        )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "comp_list_all")
async def callback_companies_list_all(callback: CallbackQuery) -> None:
    """Show full companies list for admin editing."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with async_session_maker() as session:
        companies = (await session.execute(select(Company).order_by(Company.name))).scalars().all()

    if not companies:
        await callback.answer("Список пуст", show_alert=True)
        return

    # Keep callback keyboard under Telegram limits.
    limited = companies[:80]
    await callback.message.edit_text(
        "🏢 <b>Все компании</b>\n\nВыбери компанию для редактирования:",
        parse_mode="HTML",
        reply_markup=companies_keyboard(limited, back_callback="admin_companies"),
    )


@router.callback_query(F.data.startswith("comp_edit_"))
async def callback_company_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Open company description editor."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        company_id = int(callback.data.replace("comp_edit_", ""))
    except ValueError:
        await callback.answer("Некорректный ID компании", show_alert=True)
        return

    async with async_session_maker() as session:
        company = (await session.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
        if not company:
            await callback.answer("Компания не найдена", show_alert=True)
            return

    await state.set_state(CompanyEditStates.waiting_for_description)
    await state.update_data(company_id=company_id)

    current_desc = company.description or "Не задано"
    text = (
        f"🏢 <b>{html.escape(company.name)}</b>\n\n"
        f"📝 <b>Текущее описание:</b>\n{html.escape(current_desc)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Отправь новое описание компании.\n\n"
        "<i>Поддерживается HTML форматирование.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить описание", callback_data=f"comp_delete_{company_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_companies")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("comp_delete_"))
async def callback_company_delete_desc(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete company description by company id."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        company_id = int(callback.data.replace("comp_delete_", ""))
    except ValueError:
        await callback.answer("Некорректный ID компании", show_alert=True)
        return

    async with async_session_maker() as session:
        company = (await session.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
        if not company:
            await callback.answer("Компания не найдена", show_alert=True)
            return
        company.description = None
        await session.commit()

    await state.clear()
    await callback.answer("🗑 Описание удалено")
    await callback_admin_companies(callback)


@router.message(CompanyEditStates.waiting_for_description)
async def process_company_description(message: Message, state: FSMContext) -> None:
    """Save company description sent by admin."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    company_id = data.get("company_id")
    if not company_id:
        await state.clear()
        await message.answer("❌ Ошибка: компания не найдена")
        return

    description = message.text or message.caption or ""
    async with async_session_maker() as session:
        company = (await session.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
        if not company:
            await state.clear()
            await message.answer("❌ Компания не найдена")
            return
        company.description = description
        company_name = company.name
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ <b>Описание сохранено!</b>\n\n🏢 <b>{html.escape(company_name)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏢 К компаниям", callback_data="admin_companies")],
                [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
            ]
        ),
    )


@router.callback_query(F.data == "admin_back")
async def callback_admin_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Return from submenus back to admin dashboard."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())
    await callback.answer()
