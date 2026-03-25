import html
import re
from datetime import datetime, timedelta
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import desc, func, select

from database.db import async_session_maker
from database.models import User, UserAction

CALLBACK_PREFIXES: list[tuple[str, str]] = [
    ("admin_event_photo_delete_", "admin_event_photo_delete"),
    ("admin_event_delete_", "admin_event_delete"),
    ("admin_event_toggle_", "admin_event_toggle"),
    ("admin_event_view_", "admin_event_view"),
    ("admin_event_edit_", "admin_event_edit"),
    ("admin_reply_", "admin_reply"),
    ("company_divisions_", "company_divisions"),
    ("company_vacancies_", "company_vacancies"),
    ("division_vacancies_", "division_vacancies"),
    ("view_company_", "view_company"),
    ("view_division_", "view_division"),
    ("view_event_", "view_event"),
    ("event_register_", "event_register"),
    ("about_company_", "about_company"),
    ("back_to_vac_", "back_to_vac"),
    ("set_course_", "set_course"),
    ("set_faculty_", "set_faculty"),
    ("reg_course_", "reg_course"),
    ("reg_faculty_", "reg_faculty"),
    ("reg_source_", "reg_source"),
    ("sphere_", "sphere"),
    ("vac_", "vac_navigation"),
    ("comp_edit_", "comp_edit"),
    ("comp_delete_", "comp_delete"),
]

MESSAGE_PREVIEW_LIMIT = 300
RECENT_PREVIEW_LIMIT = 48


def normalize_callback_action(callback_data: str | None) -> str:
    if not callback_data:
        return "callback:empty"

    value = callback_data.strip()
    for prefix, action in CALLBACK_PREFIXES:
        if value.startswith(prefix):
            return f"callback:{action}"

    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    parts = [part for part in normalized.split("_") if part and not part.isdigit()]
    compact = "_".join(parts[:4]) if parts else "unknown"
    return f"callback:{compact}"


def extract_message_action(message: Message) -> tuple[str, str | None]:
    text = (message.text or "").strip()
    caption = (message.caption or "").strip()

    if text.startswith("/"):
        command = text.split()[0].split("@")[0].lstrip("/").lower()
        return f"command:{command or 'unknown'}", text[:MESSAGE_PREVIEW_LIMIT]

    if text:
        return "message:text", text[:MESSAGE_PREVIEW_LIMIT]
    if caption:
        return "message:caption", caption[:MESSAGE_PREVIEW_LIMIT]
    if message.photo:
        return "message:photo", "[photo]"
    if message.video:
        return "message:video", "[video]"
    if message.animation:
        return "message:animation", "[animation]"
    if message.document:
        return "message:document", message.document.file_name or "[document]"
    if message.voice:
        return "message:voice", "[voice]"
    if message.sticker:
        return "message:sticker", message.sticker.emoji or "[sticker]"
    if message.contact:
        return "message:contact", "[contact]"
    if message.location:
        return "message:location", "[location]"

    return "message:other", None


def extract_event_details(event: TelegramObject) -> tuple[str, str, str | None, str | None]:
    if isinstance(event, CallbackQuery):
        chat_type = event.message.chat.type if event.message else None
        return "callback_query", normalize_callback_action(event.data), event.data, chat_type

    if isinstance(event, Message):
        action, raw_value = extract_message_action(event)
        return "message", action, raw_value, event.chat.type

    update_type = type(event).__name__.lower()
    return update_type, f"{update_type}:unknown", None, None


async def get_fsm_state_name(data: dict[str, Any]) -> str | None:
    state: FSMContext | None = data.get("state")
    if not state:
        return None

    try:
        return await state.get_state()
    except Exception:
        return None


async def build_user_action(
    event: TelegramObject,
    data: dict[str, Any],
    db_user: User | None,
    normalized_username: str | None,
) -> UserAction:
    update_type, action, raw_value, chat_type = extract_event_details(event)
    return UserAction(
        user_id=db_user.id if db_user else None,
        telegram_id=db_user.telegram_id if db_user else data["event_from_user"].id,
        username=normalized_username,
        update_type=update_type,
        action=action,
        raw_value=raw_value,
        chat_type=chat_type,
        fsm_state=await get_fsm_state_name(data),
    )


def _format_user_label(username: str | None, telegram_id: int) -> str:
    if username:
        return f"@{html.escape(username)}"
    return f"<code>{telegram_id}</code>"


def _format_raw_preview(action: str, raw_value: str | None) -> str:
    if not raw_value:
        return ""

    preview = " ".join(raw_value.split())
    if len(preview) > RECENT_PREVIEW_LIMIT:
        preview = f"{preview[:RECENT_PREVIEW_LIMIT - 3]}..."

    escaped = html.escape(preview)
    if action.startswith("message:"):
        return f" ({escaped})"
    return f" <code>{escaped}</code>"


async def get_metrics_text() -> str:
    now = datetime.utcnow()
    last_day = now - timedelta(days=1)
    last_week = now - timedelta(days=7)

    async with async_session_maker() as session:
        total_actions = (
            await session.execute(select(func.count(UserAction.id)))
        ).scalar() or 0
        total_users = (
            await session.execute(select(func.count(func.distinct(UserAction.telegram_id))))
        ).scalar() or 0
        day_actions = (
            await session.execute(select(func.count(UserAction.id)).where(UserAction.created_at >= last_day))
        ).scalar() or 0
        day_users = (
            await session.execute(
                select(func.count(func.distinct(UserAction.telegram_id))).where(UserAction.created_at >= last_day)
            )
        ).scalar() or 0
        week_actions = (
            await session.execute(select(func.count(UserAction.id)).where(UserAction.created_at >= last_week))
        ).scalar() or 0
        week_users = (
            await session.execute(
                select(func.count(func.distinct(UserAction.telegram_id))).where(UserAction.created_at >= last_week)
            )
        ).scalar() or 0

        update_counts = (
            await session.execute(
                select(UserAction.update_type, func.count(UserAction.id))
                .group_by(UserAction.update_type)
                .order_by(func.count(UserAction.id).desc(), UserAction.update_type.asc())
            )
        ).all()

        top_actions = (
            await session.execute(
                select(UserAction.action, func.count(UserAction.id))
                .where(UserAction.created_at >= last_week)
                .group_by(UserAction.action)
                .order_by(func.count(UserAction.id).desc(), UserAction.action.asc())
                .limit(10)
            )
        ).all()

        top_users = (
            await session.execute(
                select(
                    UserAction.telegram_id,
                    func.max(UserAction.username),
                    func.count(UserAction.id),
                )
                .where(UserAction.created_at >= last_week)
                .group_by(UserAction.telegram_id)
                .order_by(func.count(UserAction.id).desc(), UserAction.telegram_id.asc())
                .limit(10)
            )
        ).all()

        recent_actions = (
            await session.execute(
                select(
                    UserAction.created_at,
                    UserAction.telegram_id,
                    UserAction.username,
                    UserAction.action,
                    UserAction.raw_value,
                    UserAction.fsm_state,
                )
                .order_by(desc(UserAction.created_at), desc(UserAction.id))
                .limit(10)
            )
        ).all()

    lines = [
        "<b>Метрика действий</b>",
        "",
        f"<b>Всего событий:</b> {total_actions}",
        f"<b>Пользователей с действиями:</b> {total_users}",
        f"<b>За 24 часа:</b> {day_actions} событий / {day_users} пользователей",
        f"<b>За 7 дней:</b> {week_actions} событий / {week_users} пользователей",
    ]

    if update_counts:
        lines.extend(["", "<b>По типу обновлений:</b>"])
        for update_type, count in update_counts:
            lines.append(f"• {html.escape(str(update_type))}: {count}")

    if top_actions:
        lines.extend(["", "<b>Топ действий за 7 дней:</b>"])
        for action, count in top_actions:
            lines.append(f"• {html.escape(str(action))}: {count}")

    if top_users:
        lines.extend(["", "<b>Самые активные пользователи за 7 дней:</b>"])
        for telegram_id, username, count in top_users:
            lines.append(f"• {_format_user_label(username, telegram_id)}: {count}")

    if recent_actions:
        lines.extend(["", "<b>Последние события:</b>"])
        for created_at, telegram_id, username, action, raw_value, fsm_state in recent_actions:
            label = _format_user_label(username, telegram_id)
            timestamp = created_at.strftime("%d.%m %H:%M")
            state_suffix = f" [{html.escape(fsm_state)}]" if fsm_state else ""
            lines.append(
                f"• {timestamp} {label}: {html.escape(str(action))}{state_suffix}{_format_raw_preview(action, raw_value)}"
            )

    return "\n".join(lines)
