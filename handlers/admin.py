import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove
from sqlalchemy import distinct, func, select

from config import ADMIN_IDS
from database.db import async_session_maker
from database.models import Company, Event, EventRegistration, Statistics, User, Vacancy
from services.company_utils import clean_company_name, normalize_company_name
from services.event_photos import delete_event_photo, get_event_photo_input, save_event_photo
from services.google_sheets import delete_event_spreadsheet, ensure_event_spreadsheet, export_event_registrations_to_sheet, sync_vacancies_to_db

router = Router()


class CompanyEditStates(StatesGroup):
    waiting_for_description = State()


class AdminReplyStates(StatesGroup):
    waiting_for_reply = State()


class AdminBroadcastStates(StatesGroup):
    waiting_for_message = State()


class AdminDirectMessageStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_message = State()


class EventCreateStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_capacity = State()
    waiting_for_success_message = State()
    waiting_for_reserve_message = State()
    waiting_for_photo = State()


class EventEditStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_capacity = State()
    waiting_for_photo = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Синхронизировать вакансии", callback_data="admin_sync")],
            [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="Сообщение по ID", callback_data="admin_direct_message")],
            [InlineKeyboardButton(text="Компании", callback_data="admin_companies")],
            [InlineKeyboardButton(text="Мероприятия", callback_data="admin_events")],
            [InlineKeyboardButton(text="Обновить статистику", callback_data="admin_stats")],
            [InlineKeyboardButton(text="Меню", callback_data="main_menu")],
        ]
    )


def get_reply_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_reply_cancel")]]
    )


def get_broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_broadcast_cancel")]]
    )


def get_direct_message_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_direct_message_cancel")]]
    )


def get_events_cancel_keyboard(back_callback: str = "admin_events") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data=back_callback)]]
    )


def companies_keyboard(companies: list[Company], back_callback: str = "admin_back") -> InlineKeyboardMarkup:
    rows = []
    for company in companies:
        marker = "Заполнено" if company.description else "Пусто"
        display_name = company.name if len(company.name) <= 28 else f"{company.name[:25]}..."
        rows.append([InlineKeyboardButton(text=f"{marker} | {display_name}", callback_data=f"comp_edit_{company.id}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_events_keyboard(events: list[Event]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Создать мероприятие", callback_data="admin_events_create")]]
    for event in events:
        prefix = "Активно" if event.is_active else "Скрыто"
        display_title = event.title if len(event.title) <= 26 else f"{event.title[:23]}..."
        rows.append(
            [InlineKeyboardButton(text=f"{prefix} | {display_title}", callback_data=f"admin_event_view_{event.id}")]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_event_admin_keyboard(event: Event) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Изменить название", callback_data=f"admin_event_edit_{event.id}_title")],
        [InlineKeyboardButton(text="Изменить описание", callback_data=f"admin_event_edit_{event.id}_description")],
        [InlineKeyboardButton(text="Изменить лимит", callback_data=f"admin_event_edit_{event.id}_capacity")],
        [InlineKeyboardButton(text="Сообщение для основного списка", callback_data=f"admin_event_edit_{event.id}_success")],
        [InlineKeyboardButton(text="Сообщение для резерва", callback_data=f"admin_event_edit_{event.id}_reserve")],
        [InlineKeyboardButton(text="Изменить фото", callback_data=f"admin_event_edit_{event.id}_photo")],
    ]
    if event.photo_file_id:
        rows.append([InlineKeyboardButton(text="Удалить фото", callback_data=f"admin_event_photo_delete_{event.id}")])
    rows.append(
        [
            InlineKeyboardButton(
                text="Скрыть" if event.is_active else "Опубликовать",
                callback_data=f"admin_event_toggle_{event.id}",
            )
        ]
    )
    if event.spreadsheet_url:
        rows.append([InlineKeyboardButton(text="Открыть лист", url=event.spreadsheet_url)])
    rows.append([InlineKeyboardButton(text="Удалить мероприятие", callback_data=f"admin_event_delete_{event.id}")])
    rows.append([InlineKeyboardButton(text="К списку мероприятий", callback_data="admin_events")])
    rows.append([InlineKeyboardButton(text="Админ-панель", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_stats_text() -> str:
    async with async_session_maker() as session:
        total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
        registered_users = (
            await session.execute(select(func.count(User.id)).where(User.is_registered.is_(True)))
        ).scalar() or 0
        total_vacancies = (await session.execute(select(func.count(Vacancy.id)))).scalar() or 0
        total_company_descriptions = (
            await session.execute(select(func.count(Company.id)).where(Company.description.isnot(None), Company.description != ""))
        ).scalar() or 0
        total_events = (await session.execute(select(func.count(Event.id)))).scalar() or 0
        active_events = (
            await session.execute(select(func.count(Event.id)).where(Event.is_active.is_(True)))
        ).scalar() or 0
        total_stats_rows = (await session.execute(select(func.count(Statistics.id)))).scalar() or 0

        faculties_result = await session.execute(
            select(User.faculty, func.count(User.id))
            .where(User.faculty.isnot(None), User.faculty != "")
            .group_by(User.faculty)
            .order_by(func.count(User.id).desc(), User.faculty.asc())
        )
        faculties_stats = [(faculty, count) for faculty, count in faculties_result.all() if faculty]

        sources_result = await session.execute(
            select(User.info_source, func.count(User.id))
            .where(User.info_source.isnot(None), User.info_source != "")
            .group_by(User.info_source)
            .order_by(func.count(User.id).desc(), User.info_source.asc())
        )
        sources_stats = [(source, count) for source, count in sources_result.all() if source]

    lines = [
        "<b>Админ-панель</b>",
        "",
        "<b>Пользователи:</b>",
        f"Всего: <b>{total_users}</b>",
        f"Зарегистрировано: <b>{registered_users}</b>",
        f"Не зарегистрировано: <b>{total_users - registered_users}</b>",
        "",
        f"<b>Вакансии в базе:</b> <b>{total_vacancies}</b>",
        f"<b>Компаний с описанием:</b> <b>{total_company_descriptions}</b>",
        f"<b>Мероприятий:</b> <b>{total_events}</b>",
        f"<b>Активных мероприятий:</b> <b>{active_events}</b>",
        f"<b>Строк статистики:</b> <b>{total_stats_rows}</b>",
    ]

    if faculties_stats:
        lines.append("")
        lines.append("<b>По факультетам:</b>")
        for faculty, count in faculties_stats:
            lines.append(f"• {html.escape(str(faculty))}: {count}")

    if sources_stats:
        lines.append("")
        lines.append("<b>Откуда узнали о боте:</b>")
        for source, count in sources_stats:
            lines.append(f"• {html.escape(str(source))}: {count}")

    return "\n".join(lines)


async def ensure_companies_from_vacancies() -> None:
    async with async_session_maker() as session:
        organizations_result = await session.execute(
            select(distinct(Vacancy.organization))
            .where(Vacancy.organization.isnot(None), Vacancy.organization != "")
            .order_by(Vacancy.organization)
        )
        organizations = [row[0] for row in organizations_result.all() if row[0]]
        if not organizations:
            return

        existing_result = await session.execute(select(Company.name).where(Company.name.isnot(None), Company.name != ""))
        existing = {normalize_company_name(row[0]) for row in existing_result.all() if normalize_company_name(row[0])}
        created = False
        for organization in organizations:
            normalized_name = normalize_company_name(organization)
            if normalized_name and normalized_name not in existing:
                session.add(Company(name=clean_company_name(organization), description=None))
                existing.add(normalized_name)
                created = True
        if created:
            await session.commit()


async def get_event_counts(session, event_id: int) -> tuple[int, int]:
    main_count = (
        await session.execute(
            select(func.count(EventRegistration.id)).where(
                EventRegistration.event_id == event_id,
                EventRegistration.status == "main",
            )
        )
    ).scalar() or 0
    reserve_count = (
        await session.execute(
            select(func.count(EventRegistration.id)).where(
                EventRegistration.event_id == event_id,
                EventRegistration.status == "reserve",
            )
        )
    ).scalar() or 0
    return main_count, reserve_count


def build_event_admin_text(event: Event, main_count: int, reserve_count: int) -> str:
    availability = max(event.capacity - main_count, 0)
    lines = [
        f"<b>{html.escape(event.title)}</b>",
        "",
        html.escape(event.description) if event.description else "Описание не заполнено.",
        "",
        f"<b>Статус:</b> {'Активно' if event.is_active else 'Скрыто'}",
        f"<b>Лимит:</b> {event.capacity}",
        f"<b>Основной список:</b> {main_count}",
        f"<b>Резерв:</b> {reserve_count}",
        f"<b>Свободных мест:</b> {availability}",
    ]
    if event.spreadsheet_url:
        lines.extend(["", f"<b>Лист:</b> {html.escape(event.spreadsheet_url)}"])
    return "\n".join(lines)


async def show_event_admin_message(target: Message, event: Event, main_count: int, reserve_count: int) -> None:
    text = build_event_admin_text(event, main_count, reserve_count)
    keyboard = get_event_admin_keyboard(event)
    if event.photo_file_id:
        try:
            await target.answer_photo(
                photo=get_event_photo_input(event.photo_file_id),
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass

    await target.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к админ-панели.")
        return

    await state.clear()
    await message.answer("Админ-режим", reply_markup=ReplyKeyboardRemove())
    await message.answer(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    stats_text = await get_stats_text()
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(stats_text, parse_mode="HTML", reply_markup=get_admin_keyboard())
        else:
            await callback.message.edit_text(stats_text, parse_mode="HTML", reply_markup=get_admin_keyboard())
        await callback.answer("Статистика обновлена")
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            await callback.answer("Статистика уже актуальна")
            return
        await callback.answer("Не удалось обновить статистику", show_alert=True)


@router.callback_query(F.data == "admin_sync")
async def callback_admin_sync(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.answer("Начинаю синхронизацию")
    await callback.message.edit_text(
        "<b>Синхронизация вакансий...</b>\n\nЗагружаю данные из Google Sheets.",
        parse_mode="HTML",
    )

    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        await callback.message.edit_text(
            f"{await get_stats_text()}\n\n<b>Синхронизировано вакансий: {synced_count}</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
    except Exception as exc:
        await callback.message.edit_text(
            f"<b>Ошибка синхронизации:</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )


@router.message(Command("sync_vacancies"))
async def cmd_sync_vacancies(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к этой команде.")
        return

    await state.clear()
    await message.answer(
        "<b>Синхронизация вакансий...</b>\n\nЗагружаю данные из Google Sheets.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        async with async_session_maker() as session:
            synced_count = await sync_vacancies_to_db(session)
        await message.answer(
            f"<b>Синхронизация завершена.</b>\n\nЗагружено вакансий: <b>{synced_count}</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
    except Exception as exc:
        await message.answer(
            f"<b>Ошибка синхронизации:</b>\n\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )


@router.callback_query(F.data == "admin_companies")
async def callback_admin_companies(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await ensure_companies_from_vacancies()
    async with async_session_maker() as session:
        companies = (
            await session.execute(select(Company).where(Company.name.isnot(None), Company.name != "").order_by(Company.name))
        ).scalars().all()

    if not companies:
        await callback.message.edit_text(
            "<b>Компании</b>\n\nВ базе пока нет компаний. Сначала синхронизируй вакансии.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="admin_back")]]
            ),
        )
        return

    with_description = sum(1 for company in companies if company.description)
    preview = companies[:40]
    keyboard = companies_keyboard(preview)
    if len(companies) > len(preview):
        keyboard.inline_keyboard.insert(
            -1,
            [InlineKeyboardButton(text=f"Показать все ({len(companies)})", callback_data="comp_list_all")],
        )

    await callback.message.edit_text(
        "<b>Компании</b>\n\n"
        f"Всего: <b>{len(companies)}</b>\n"
        f"С описанием: <b>{with_description}</b>\n\n"
        "Выбери компанию для редактирования:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "comp_list_all")
async def callback_companies_list_all(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    async with async_session_maker() as session:
        companies = (await session.execute(select(Company).order_by(Company.name))).scalars().all()

    if not companies:
        await callback.answer("Список пуст", show_alert=True)
        return

    limited = companies[:80]
    await callback.message.edit_text(
        "<b>Все компании</b>\n\nВыбери компанию для редактирования:",
        parse_mode="HTML",
        reply_markup=companies_keyboard(limited, back_callback="admin_companies"),
    )


@router.callback_query(F.data.startswith("comp_edit_"))
async def callback_company_edit(callback: CallbackQuery, state: FSMContext) -> None:
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
        f"<b>{html.escape(company.name)}</b>\n\n"
        f"<b>Текущее описание:</b>\n{html.escape(current_desc)}\n\n"
        "Отправь новое описание компании."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Удалить описание", callback_data=f"comp_delete_{company_id}")],
                [InlineKeyboardButton(text="Отмена", callback_data="admin_companies")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("comp_delete_"))
async def callback_company_delete_desc(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.answer("Описание удалено")
    await callback_admin_companies(callback, state)


@router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminBroadcastStates.waiting_for_message)
    await callback.message.answer(
        "Отправь одно сообщение, и бот разошлёт его всем пользователям.\n\n"
        "Поддерживаются обычные сообщения и вложения.",
        reply_markup=get_broadcast_cancel_keyboard(),
    )
    await callback.answer("Режим рассылки включён")


@router.callback_query(F.data == "admin_broadcast_cancel")
async def callback_admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup()
    await callback.message.answer("Рассылка отменена.")
    await callback.answer()


@router.callback_query(F.data == "admin_direct_message")
async def callback_admin_direct_message(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminDirectMessageStates.waiting_for_user_id)
    await callback.message.answer(
        "Отправь Telegram ID пользователя, которому нужно написать от имени бота.",
        reply_markup=get_direct_message_cancel_keyboard(),
    )
    await callback.answer("Режим сообщения по ID включён")


@router.callback_query(F.data == "admin_direct_message_cancel")
async def callback_admin_direct_message_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup()
    await callback.message.answer("Отправка сообщения по ID отменена.")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_reply_"))
async def callback_admin_reply(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    if callback.data == "admin_reply_cancel":
        await state.clear()
        await callback.message.edit_reply_markup()
        await callback.message.answer("Режим ответа отменён.")
        await callback.answer()
        return

    try:
        user_id = int(callback.data.replace("admin_reply_", ""))
    except ValueError:
        await callback.answer("Некорректный ID пользователя", show_alert=True)
        return

    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one_or_none()

    if user and (user.first_name or user.last_name):
        user_label = html.escape(" ".join(part for part in [user.first_name, user.last_name] if part))
    else:
        user_label = f"ID {user_id}"

    await state.set_state(AdminReplyStates.waiting_for_reply)
    await state.update_data(reply_user_id=user_id)
    await callback.message.answer(
        f"Ответ пользователю <b>{user_label}</b>.\n\n"
        "Отправь следующее сообщение, и бот перешлёт его пользователю.",
        parse_mode="HTML",
        reply_markup=get_reply_cancel_keyboard(),
    )
    await callback.answer("Режим ответа включён")


@router.callback_query(F.data == "admin_events")
async def callback_admin_events(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    async with async_session_maker() as session:
        events = (await session.execute(select(Event).order_by(Event.created_at.desc(), Event.id.desc()))).scalars().all()

    active_count = sum(1 for event in events if event.is_active)
    text = (
        "<b>Мероприятия</b>\n\n"
        f"Всего: <b>{len(events)}</b>\n"
        f"Активных: <b>{active_count}</b>\n\n"
        "Можно создавать, редактировать, удалять мероприятия и открывать их отдельные листы."
    )
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_events_keyboard(events),
        )
    else:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_events_keyboard(events),
        )
    await callback.answer()


@router.callback_query(F.data == "admin_events_create")
async def callback_admin_events_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(EventCreateStates.waiting_for_title)
    await callback.message.answer(
        "Создание мероприятия.\n\nОтправь название мероприятия.",
        reply_markup=get_events_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_view_"))
async def callback_admin_event_view(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    try:
        event_id = int(callback.data.replace("admin_event_view_", ""))
    except ValueError:
        await callback.answer("Некорректный ID мероприятия", show_alert=True)
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        main_count, reserve_count = await get_event_counts(session, event.id)

    await callback.message.delete()
    await show_event_admin_message(callback.message, event, main_count, reserve_count)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_edit_"))
async def callback_admin_event_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, _, _, event_id_raw, field = callback.data.split("_", 4)
        event_id = int(event_id_raw)
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return

    await state.clear()
    await state.update_data(event_id=event_id, edit_field=field)
    if field == "capacity":
        await state.set_state(EventEditStates.waiting_for_capacity)
        prompt = "Отправь новый лимит участников целым числом."
    elif field == "photo":
        await state.set_state(EventEditStates.waiting_for_photo)
        prompt = 'Отправь новое фото. Если нужно убрать фото, отправь слово "нет".'
    else:
        await state.set_state(EventEditStates.waiting_for_text)
        labels = {
            "title": "Отправь новое название мероприятия.",
            "description": "Отправь новое описание мероприятия.",
            "success": "Отправь новое сообщение для основного списка.",
            "reserve": "Отправь новое сообщение для резерва.",
        }
        prompt = labels.get(field, "Отправь новое значение.")

    await callback.message.answer(prompt, reply_markup=get_events_cancel_keyboard(f"admin_event_view_{event_id}"))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_event_photo_delete_"))
async def callback_admin_event_photo_delete(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        event_id = int(callback.data.replace("admin_event_photo_delete_", ""))
    except ValueError:
        await callback.answer("Некорректный ID мероприятия", show_alert=True)
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        delete_event_photo(event.photo_file_id)
        event.photo_file_id = None
        await session.commit()
        main_count, reserve_count = await get_event_counts(session, event.id)

    await state.clear()
    await callback.message.delete()
    await show_event_admin_message(callback.message, event, main_count, reserve_count)
    await callback.answer("Фото удалено")


@router.callback_query(F.data.startswith("admin_event_toggle_"))
async def callback_admin_event_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        event_id = int(callback.data.replace("admin_event_toggle_", ""))
    except ValueError:
        await callback.answer("Некорректный ID мероприятия", show_alert=True)
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        event.is_active = not event.is_active
        await session.commit()
        main_count, reserve_count = await get_event_counts(session, event.id)

    await callback.message.delete()
    await show_event_admin_message(callback.message, event, main_count, reserve_count)
    await callback.answer("Статус мероприятия обновлён")


@router.callback_query(F.data.startswith("admin_event_delete_"))
async def callback_admin_event_delete(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        event_id = int(callback.data.replace("admin_event_delete_", ""))
    except ValueError:
        await callback.answer("Некорректный ID мероприятия", show_alert=True)
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await callback.answer("Мероприятие не найдено", show_alert=True)
            return
        title = event.title
        delete_event_photo(event.photo_file_id)
        delete_event_spreadsheet(event)
        await session.delete(event)
        await session.commit()
        events = (await session.execute(select(Event).order_by(Event.created_at.desc(), Event.id.desc()))).scalars().all()

    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        f"<b>Мероприятие удалено:</b> {html.escape(title)}",
        parse_mode="HTML",
        reply_markup=get_events_keyboard(events),
    )
    await callback.answer()


@router.message(CompanyEditStates.waiting_for_description)
async def process_company_description(message: Message, state: FSMContext) -> None:
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
        await message.answer("Ошибка: компания не найдена.")
        return

    description = message.text or message.caption or ""
    async with async_session_maker() as session:
        company = (await session.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
        if not company:
            await state.clear()
            await message.answer("Компания не найдена.")
            return
        company.description = description
        company_name = company.name
        await session.commit()

    await state.clear()
    await message.answer(
        f"<b>Описание сохранено.</b>\n\nКомпания: <b>{html.escape(company_name)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="К компаниям", callback_data="admin_companies")],
                [InlineKeyboardButton(text="Админ-панель", callback_data="admin_back")],
            ]
        ),
    )


@router.message(AdminReplyStates.waiting_for_reply)
async def process_admin_reply(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    user_id = data.get("reply_user_id")
    if not user_id:
        await state.clear()
        await message.answer("Не удалось определить получателя.")
        return

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        if not message.text:
            await message.answer(
                "Не удалось отправить это сообщение пользователю. Попробуй текстовое сообщение.",
                reply_markup=get_reply_cancel_keyboard(),
            )
            return
        await bot.send_message(user_id, message.text)

    await state.clear()
    await message.answer("Ответ отправлен пользователю.")


@router.message(AdminDirectMessageStates.waiting_for_user_id)
async def process_admin_direct_message_user_id(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    raw_user_id = (message.text or "").strip()
    if not raw_user_id.lstrip("-").isdigit():
        await message.answer(
            "ID должен быть числом. Отправь корректный Telegram ID пользователя.",
            reply_markup=get_direct_message_cancel_keyboard(),
        )
        return

    target_user_id = int(raw_user_id)
    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.telegram_id == target_user_id))).scalar_one_or_none()

    await state.update_data(direct_message_user_id=target_user_id)
    await state.set_state(AdminDirectMessageStates.waiting_for_message)

    if user and (user.first_name or user.last_name):
        user_label = html.escape(" ".join(part for part in [user.first_name, user.last_name] if part))
        text = (
            f"Получатель: <b>{user_label}</b>\n"
            f"Telegram ID: <code>{target_user_id}</code>\n\n"
            "Отправь сообщение, и бот перешлёт его пользователю."
        )
    else:
        text = (
            f"Получатель: <code>{target_user_id}</code>\n\n"
            "Пользователь не найден в базе, но бот всё равно попробует отправить сообщение.\n"
            "Отправь сообщение."
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_direct_message_cancel_keyboard(),
    )


@router.message(AdminDirectMessageStates.waiting_for_message)
async def process_admin_direct_message(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    target_user_id = data.get("direct_message_user_id")
    if not target_user_id:
        await state.clear()
        await message.answer("Не удалось определить получателя.")
        return

    try:
        await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        if not message.text:
            await message.answer(
                "Не удалось отправить это вложение пользователю. Попробуй текстовое сообщение.",
                reply_markup=get_direct_message_cancel_keyboard(),
            )
            return
        try:
            await bot.send_message(target_user_id, message.text)
        except Exception as exc:
            await message.answer(
                f"Не удалось отправить сообщение.\n\nПричина: <code>{html.escape(str(exc))}</code>",
                parse_mode="HTML",
                reply_markup=get_direct_message_cancel_keyboard(),
            )
            return

    await state.clear()
    await message.answer(
        f"Сообщение отправлено пользователю <code>{target_user_id}</code>.",
        parse_mode="HTML",
        reply_markup=get_admin_keyboard(),
    )


@router.message(AdminBroadcastStates.waiting_for_message)
async def process_admin_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if message.text and message.text.startswith("/"):
        await state.clear()
        return

    async with async_session_maker() as session:
        recipients = (
            await session.execute(
                select(User.telegram_id)
                .where(User.telegram_id.isnot(None))
                .order_by(User.id)
            )
        ).scalars().all()

    if not recipients:
        await state.clear()
        await message.answer("В базе нет пользователей для рассылки.")
        return

    await message.answer(f"Начинаю рассылку. Получателей: <b>{len(recipients)}</b>", parse_mode="HTML")

    sent_count = 0
    failed_count = 0
    error_samples: list[str] = []
    for recipient_id in recipients:
        try:
            await message.copy_to(chat_id=recipient_id)
            sent_count += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await message.copy_to(chat_id=recipient_id)
                sent_count += 1
                await asyncio.sleep(0.05)
                continue
            except Exception as retry_exc:
                failed_count += 1
                if len(error_samples) < 5:
                    error_samples.append(f"{recipient_id}: {type(retry_exc).__name__}")
        except TelegramForbiddenError:
            failed_count += 1
            if len(error_samples) < 5:
                error_samples.append(f"{recipient_id}: forbidden")
        except TelegramBadRequest as exc:
            failed_count += 1
            if len(error_samples) < 5:
                error_samples.append(f"{recipient_id}: {str(exc)}")
        except Exception as exc:
            if message.text:
                try:
                    await bot.send_message(recipient_id, message.text)
                    sent_count += 1
                    await asyncio.sleep(0.05)
                    continue
                except Exception as fallback_exc:
                    if len(error_samples) < 5:
                        error_samples.append(f"{recipient_id}: {type(fallback_exc).__name__}")
            failed_count += 1
            if len(error_samples) < 5 and not message.text:
                error_samples.append(f"{recipient_id}: {type(exc).__name__}")

    await state.clear()
    summary_lines = [
        "Рассылка завершена.",
        "",
        f"Получателей: <b>{len(recipients)}</b>",
        f"Успешно: <b>{sent_count}</b>",
        f"Не доставлено: <b>{failed_count}</b>",
    ]
    if error_samples:
        summary_lines.extend(
            [
                "",
                "Первые ошибки:",
                html.escape("\n".join(error_samples)),
            ]
        )
    await message.answer(
        "\n".join(summary_lines),
        parse_mode="HTML",
        reply_markup=get_admin_keyboard(),
    )


def _parse_capacity(value: str) -> int | None:
    text = (value or "").strip()
    if not text.isdigit():
        return None
    capacity = int(text)
    if capacity <= 0:
        return None
    return capacity


@router.message(EventCreateStates.waiting_for_title)
async def process_event_create_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не должно быть пустым.")
        return

    await state.update_data(title=title)
    await state.set_state(EventCreateStates.waiting_for_description)
    await message.answer("Отправь описание мероприятия.", reply_markup=get_events_cancel_keyboard())


@router.message(EventCreateStates.waiting_for_description)
async def process_event_create_description(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    description = (message.text or message.caption or "").strip()
    if not description:
        await message.answer("Описание не должно быть пустым.")
        return

    await state.update_data(description=description)
    await state.set_state(EventCreateStates.waiting_for_capacity)
    await message.answer("Отправь лимит участников целым числом.", reply_markup=get_events_cancel_keyboard())


@router.message(EventCreateStates.waiting_for_capacity)
async def process_event_create_capacity(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    capacity = _parse_capacity(message.text or "")
    if capacity is None:
        await message.answer("Лимит должен быть положительным целым числом.")
        return

    await state.update_data(capacity=capacity)
    await state.set_state(EventCreateStates.waiting_for_success_message)
    await message.answer("Отправь сообщение для участников, которые попали в основной список.")


@router.message(EventCreateStates.waiting_for_success_message)
async def process_event_create_success(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    success_message = (message.text or message.caption or "").strip()
    if not success_message:
        await message.answer("Сообщение не должно быть пустым.")
        return

    await state.update_data(success_message=success_message)
    await state.set_state(EventCreateStates.waiting_for_reserve_message)
    await message.answer("Отправь сообщение для участников, которые попадут в резерв.")


@router.message(EventCreateStates.waiting_for_reserve_message)
async def process_event_create_reserve(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    reserve_message = (message.text or message.caption or "").strip()
    if not reserve_message:
        await message.answer("Сообщение не должно быть пустым.")
        return

    await state.update_data(reserve_message=reserve_message)
    await state.set_state(EventCreateStates.waiting_for_photo)
    await message.answer('Отправь фото мероприятия. Если фото не нужно, отправь слово "нет".')


@router.message(EventCreateStates.waiting_for_photo)
async def process_event_create_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    telegram_photo_file_id = None
    if message.photo:
        telegram_photo_file_id = message.photo[-1].file_id
    elif (message.text or "").strip().lower() != "нет":
        await message.answer('Отправь фото или слово "нет".')
        return

    data = await state.get_data()
    saved_photo_path = None
    try:
        async with async_session_maker() as session:
            event = Event(
                title=data["title"],
                description=data["description"],
                photo_file_id=None,
                capacity=data["capacity"],
                success_message=data["success_message"],
                reserve_message=data["reserve_message"],
                is_active=True,
            )
            session.add(event)
            await session.flush()
            if telegram_photo_file_id:
                saved_photo_path = await save_event_photo(bot, telegram_photo_file_id, event.id)
                event.photo_file_id = saved_photo_path
            spreadsheet_id, spreadsheet_url = ensure_event_spreadsheet(event)
            event.spreadsheet_id = spreadsheet_id
            event.spreadsheet_url = spreadsheet_url
            await session.commit()
            main_count, reserve_count = await get_event_counts(session, event.id)
    except Exception as exc:
        delete_event_photo(saved_photo_path)
        await message.answer(
            f"Не удалось создать мероприятие.\n\nПричина: <code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=get_events_cancel_keyboard(),
        )
        return

    await state.clear()
    await show_event_admin_message(message, event, main_count, reserve_count)
    if event.spreadsheet_url:
        await message.answer(
            f"Лист мероприятия создан:\n{event.spreadsheet_url}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть лист", url=event.spreadsheet_url)]]
            ),
        )
    else:
        await message.answer("Мероприятие создано, но ссылку на лист Google Sheets получить не удалось.")


@router.message(EventEditStates.waiting_for_text)
async def process_event_edit_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    value = (message.text or message.caption or "").strip()
    if not value:
        await message.answer("Значение не должно быть пустым.")
        return

    data = await state.get_data()
    event_id = data.get("event_id")
    field = data.get("edit_field")
    if not event_id or not field:
        await state.clear()
        await message.answer("Состояние редактирования потеряно.")
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await state.clear()
            await message.answer("Мероприятие не найдено.")
            return

        if field == "title":
            event.title = value
            spreadsheet_id, spreadsheet_url = ensure_event_spreadsheet(event)
            if spreadsheet_id:
                event.spreadsheet_id = spreadsheet_id
            if spreadsheet_url:
                event.spreadsheet_url = spreadsheet_url
        elif field == "description":
            event.description = value
        elif field == "success":
            event.success_message = value
        elif field == "reserve":
            event.reserve_message = value
        else:
            await state.clear()
            await message.answer("Неизвестное поле редактирования.")
            return

        await session.commit()
        main_count, reserve_count = await get_event_counts(session, event.id)

    await state.clear()
    await show_event_admin_message(message, event, main_count, reserve_count)


@router.message(EventEditStates.waiting_for_capacity)
async def process_event_edit_capacity(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    capacity = _parse_capacity(message.text or "")
    if capacity is None:
        await message.answer("Лимит должен быть положительным целым числом.")
        return

    data = await state.get_data()
    event_id = data.get("event_id")
    if not event_id:
        await state.clear()
        await message.answer("Состояние редактирования потеряно.")
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await state.clear()
            await message.answer("Мероприятие не найдено.")
            return
        event.capacity = capacity
        await session.commit()
        main_count, reserve_count = await get_event_counts(session, event.id)

    await state.clear()
    await show_event_admin_message(message, event, main_count, reserve_count)


@router.message(EventEditStates.waiting_for_photo)
async def process_event_edit_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    remove_photo = False
    telegram_photo_file_id = None
    if message.photo:
        telegram_photo_file_id = message.photo[-1].file_id
    elif (message.text or "").strip().lower() == "нет":
        remove_photo = True
    else:
        await message.answer('Отправь фото или слово "нет".')
        return

    data = await state.get_data()
    event_id = data.get("event_id")
    if not event_id:
        await state.clear()
        await message.answer("Состояние редактирования потеряно.")
        return

    async with async_session_maker() as session:
        event = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if not event:
            await state.clear()
            await message.answer("Мероприятие не найдено.")
            return
        old_photo_ref = event.photo_file_id
        if telegram_photo_file_id:
            event.photo_file_id = await save_event_photo(bot, telegram_photo_file_id, event.id)
            delete_event_photo(old_photo_ref)
        elif remove_photo:
            delete_event_photo(old_photo_ref)
            event.photo_file_id = None
        await session.commit()
        main_count, reserve_count = await get_event_counts(session, event.id)

    await state.clear()
    await show_event_admin_message(message, event, main_count, reserve_count)


@router.callback_query(F.data == "admin_back")
async def callback_admin_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())
    else:
        await callback.message.edit_text(await get_stats_text(), parse_mode="HTML", reply_markup=get_admin_keyboard())
    await callback.answer()
