import html

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, FSInputFile, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, distinct
from pathlib import Path

from database.models import User, Vacancy, Company, Division, Event, EventRegistration
from database.db import async_session_maker
from config import FACULTIES
from services.admins import get_admin_ids
from services.company_utils import (
    clean_company_name,
    company_has_description,
    deduplicate_companies,
    find_company_by_name,
    get_company_aliases,
    normalize_company_name,
    normalized_company_sql,
)
from services.course_utils import COURSE_LEVELS, format_course_label, parse_course_callback
from services.event_photos import get_event_photo_input
from services.google_sheets import export_event_registrations_to_sheet
from services.image_generator import get_cached_or_generate
from services.user_names import format_full_name, validate_name_part
from services.vacancy_defaults import (
    DEFAULT_DESCRIPTION,
    DEFAULT_EMPLOYMENT_FORMAT,
    DEFAULT_SALARY,
    DEFAULT_SCHEDULE,
    DEFAULT_SPHERE,
    DEFAULT_WORK_FORMAT,
    present_features,
    present_value,
)


def get_feedback_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build keyboard for admin actions on user feedback."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="РћС‚РІРµС‚РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ", callback_data=f"admin_reply_{user_id}")]
        ]
    )


def resolve_image_path(*candidates: Path) -> Path | None:
    """Return the first existing path from provided image candidates."""
    for path in candidates:
        if path.exists():
            return path
    return None


# РџСѓС‚Рё Рє РєР°СЂС‚РёРЅРєР°Рј (c fallback РїРѕ СЂР°СЃС€РёСЂРµРЅРёСЏРј)
ASSETS_PATH = Path(__file__).parent.parent / "assets" / "images"
MENU_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "menu_picture.jpg",
    ASSETS_PATH / "menu_picture.jpeg",
    ASSETS_PATH / "menu_picture.png",
)
VACANCY_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "vacancy_card.png",
    ASSETS_PATH / "vacancy_card.jpeg",
    ASSETS_PATH / "vacancy_card.png",
)
ABOUT_US_IMAGE_PATHS = [
    path
    for path in (
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё РёРЅС„РѕСЂРј.png"),
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё РЅРѕРґ.png"),
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё РЅРїСЂ.png"),
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё РЅСЂРіРє.png"),
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё РЅСЂРєРє.png"),
        resolve_image_path(ASSETS_PATH / "РїР»Р°С€РєР° Рѕ РЅР°РїСЂР°РІР»РµРЅРёРё СЃРїРѕРЅСЃРѕСЂРєР°.png"),
    )
    if path is not None
]
COMPANY_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "company_card.png",
    ASSETS_PATH / "company_card.png",
    ASSETS_PATH / "company_card.png",
)
DIVISION_IMAGE_PATH = resolve_image_path(
    ASSETS_PATH / "division_card.png",
    ASSETS_PATH / "division_card.png",
    ASSETS_PATH / "division_card.png",
)


def get_vacancy_photo_input(vacancy: Vacancy):
    """Return a generated image for one vacancy with a static-template fallback."""
    try:
        image_bytes = get_cached_or_generate(vacancy)
        return BufferedInputFile(image_bytes, filename=f"vacancy_{vacancy.id}.png")
    except Exception:
        if VACANCY_IMAGE_PATH:
            return FSInputFile(VACANCY_IMAGE_PATH)
        raise

router = Router()


# РЎРѕСЃС‚РѕСЏРЅРёСЏ РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРІСЏР·Рё
class FeedbackStates(StatesGroup):
    waiting_for_message = State()


# РњР°РїРїРёРЅРі С„Р°РєСѓР»СЊС‚РµС‚РѕРІ РёР· Р±РѕС‚Р° РІ РїРѕР»СЏ Р‘Р”
FACULTY_TO_DB_FIELD = {
    "РРўРёРђР‘Р”": "itiabd",
    "РРћРћ": "ioo",
    "РњР­Рћ": "meo",
    "Р¤Р­Р‘": "feb",
    "РЎРќРёРњРљ": "snimk",
    "РќРђР‘": "nab",
    "Р’РЁРЈ": "vshu",
    "Р¤Р¤": "finfak",
    "Р®Р¤": "yurfak"
}

# Р­РјРѕРґР·Рё РґР»СЏ СЃС„РµСЂ
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
    """Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ СЃ РєРЅРѕРїРєР°РјРё"""
    keyboard = [
        [InlineKeyboardButton(text="РњРѕР№ РїСЂРѕС„РёР»СЊ", callback_data="profile")],
        [InlineKeyboardButton(text="РљРѕРјРїР°РЅРёРё-РїР°СЂС‚РЅРµСЂС‹", callback_data="companies_list")],
        [InlineKeyboardButton(text="Р’Р°РєР°РЅСЃРёРё", callback_data="vacancies_menu")],
        [InlineKeyboardButton(text="РњРµСЂРѕРїСЂРёСЏС‚РёСЏ", callback_data="events_list")],
        [InlineKeyboardButton(text="РћР±СЂР°С‚РЅР°СЏ СЃРІСЏР·СЊ", callback_data="feedback")],
        [InlineKeyboardButton(text="Рћ РЅР°СЃ", callback_data="about_us")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_main_menu_keyboard(user_faculty: str = None, vacancies_count: int = 0):
    """Build the main user menu."""
    keyboard = [
        [InlineKeyboardButton(text="РњРѕР№ РїСЂРѕС„РёР»СЊ", callback_data="profile")],
        [InlineKeyboardButton(text="РљРѕРјРїР°РЅРёРё-РїР°СЂС‚РЅРµСЂС‹", callback_data="companies_list")],
        [InlineKeyboardButton(text="Р’Р°РєР°РЅСЃРёРё", callback_data="vacancies_menu")],
        [InlineKeyboardButton(text="РњРµСЂРѕРїСЂРёСЏС‚РёСЏ", callback_data="events_list")],
        [InlineKeyboardButton(text="РћР±СЂР°С‚РЅР°СЏ СЃРІСЏР·СЊ", callback_data="feedback")],
        [InlineKeyboardButton(text="Рћ РЅР°СЃ", callback_data="about_us")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_vacancy_keyboard(vacancy_id: int, current_index: int, total: int, filter_type: str = "all", sphere: str = None, has_company_desc: bool = False, organization: str = None):
    """РљР»Р°РІРёР°С‚СѓСЂР° РґР»СЏ РЅР°РІРёРіР°С†РёРё РїРѕ РІР°РєР°РЅСЃРёСЏРј"""
    keyboard = []
    
    # РљРЅРѕРїРєРё РЅР°РІРёРіР°С†РёРё (РІ РѕРґРЅСѓ СЃС‚СЂРѕРєСѓ)
    nav_buttons = []
    
    # РљРЅРѕРїРєР° "Р’ РЅР°С‡Р°Р»Рѕ" РµСЃР»Рё РЅРµ РЅР° РїРµСЂРІРѕР№
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="вќ®вќ®", callback_data=f"vac_{filter_type}_0_{sphere or ''}"))
    
    # РљРЅРѕРїРєР° "РќР°Р·Р°Рґ"
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="вќ®",
            callback_data=f"vac_{filter_type}_{current_index - 1}_{sphere or ''}"
        ))
    
    # РЎС‡С‘С‚С‡РёРє
    nav_buttons.append(InlineKeyboardButton(
        text=f"{current_index + 1}/{total}",
        callback_data="noop"
    ))
    
    # РљРЅРѕРїРєР° "Р’РїРµСЂРµРґ"
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="вќЇ",
            callback_data=f"vac_{filter_type}_{current_index + 1}_{sphere or ''}"
        ))
    
    # РљРЅРѕРїРєР° "Р’ РєРѕРЅРµС†" РµСЃР»Рё РЅРµ РЅР° РїРѕСЃР»РµРґРЅРµР№
    if current_index < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="вќЇвќЇ", callback_data=f"vac_{filter_type}_{total - 1}_{sphere or ''}"))

    keyboard.append(nav_buttons)
    
    # РљРЅРѕРїРєР° "Рћ РєРѕРјРїР°РЅРёРё" РµСЃР»Рё РµСЃС‚СЊ РѕРїРёСЃР°РЅРёРµ
    if has_company_desc and organization:
        keyboard.append([InlineKeyboardButton(
            text="Рћ РєРѕРјРїР°РЅРёРё",
            callback_data=f"about_company_{vacancy_id}_{filter_type}_{current_index}_{sphere or ''}"
        )])
    
    # РџРѕСЃР»РµРґРЅСЏСЏ СЃС‚СЂРѕРєР° - РґРµР№СЃС‚РІРёСЏ
    action_buttons = []
    if filter_type == "sphere" and sphere:
        action_buttons.append(InlineKeyboardButton(text="Рљ СЃС„РµСЂР°Рј", callback_data="vacancies_by_sphere"))
    action_buttons.append(InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu"))
    keyboard.append(action_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def check_company_has_description(session, organization: str, vacancy_url: str | None = None) -> bool:
    """Return whether the vacancy has a company-details screen to show."""
    if vacancy_url and str(vacancy_url).strip():
        return True
    if not organization:
        return False
    company = await find_company_by_name(session, organization)
    return company_has_description(company) if company else False


async def get_canonical_company_by_id(session, company_id: int) -> Company | None:
    """Resolve a company ID to the preferred row among normalized duplicates."""
    company = (await session.execute(select(Company).where(Company.id == company_id))).scalar_one_or_none()
    if not company:
        return None

    aliases = await get_company_aliases(session, company.name)
    return aliases[0] if aliases else company


async def get_company_divisions(session, company_name: str | None) -> list[Division]:
    """Return divisions across all aliases of the same company."""
    aliases = await get_company_aliases(session, company_name)
    alias_ids = [company.id for company in aliases if company.id is not None]
    if not alias_ids:
        return []

    result = await session.execute(
        select(Division).where(Division.company_id.in_(alias_ids)).order_by(Division.name)
    )
    divisions = result.scalars().all()

    deduplicated: dict[str, Division] = {}
    for division in divisions:
        normalized_division_name = clean_company_name(division.name).casefold()
        if not normalized_division_name:
            continue
        existing = deduplicated.get(normalized_division_name)
        if existing is None or (division.description and not existing.description):
            deduplicated[normalized_division_name] = division

    return list(deduplicated.values())


async def get_company_vacancies(session, company_name: str | None, division_name: str | None = None) -> list[Vacancy]:
    """Load vacancies for a company using normalized organization matching."""
    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return []

    query = (
        select(Vacancy)
        .where(normalized_company_sql(Vacancy.organization) == normalized_name)
        .order_by(Vacancy.created_at.desc())
    )
    cleaned_division_name = clean_company_name(division_name)
    if cleaned_division_name:
        query = query.where(func.trim(Vacancy.division) == cleaned_division_name)

    result = await session.execute(query)
    return result.scalars().all()


async def get_company_vacancies_count(session, company_name: str | None, division_name: str | None = None) -> int:
    """Count vacancies for a company using normalized organization matching."""
    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return 0

    query = select(func.count(Vacancy.id)).where(normalized_company_sql(Vacancy.organization) == normalized_name)
    cleaned_division_name = clean_company_name(division_name)
    if cleaned_division_name:
        query = query.where(func.trim(Vacancy.division) == cleaned_division_name)

    result = await session.execute(query)
    return result.scalar() or 0


def format_vacancy_caption(vacancy: Vacancy) -> str:
    """Р¤РѕСЂРјР°С‚РёСЂРѕРІР°РЅРёРµ РІР°РєР°РЅСЃРёРё РґР»СЏ caption РїРѕРґ РєР°СЂС‚РёРЅРєРѕР№ (РґРѕ 1024 СЃРёРјРІРѕР»РѕРІ)"""

    def _truncate_plain_text(value: str | None, limit: int) -> str:
        text_value = (value or "").strip()
        if not text_value or limit <= 0:
            return ""
        if len(text_value) <= limit:
            return text_value
        return text_value[: max(limit - 3, 0)].rstrip() + "..."

    vacancy_url = (getattr(vacancy, "vacancy_url", "") or "").strip()
    sphere = present_value(vacancy.sphere, DEFAULT_SPHERE)
    salary = present_value(vacancy.salary, DEFAULT_SALARY)
    schedule = present_value(vacancy.schedule, DEFAULT_SCHEDULE)
    work_format = present_value(vacancy.work_format, DEFAULT_WORK_FORMAT)
    employment_format = present_value(vacancy.employment_format, DEFAULT_EMPLOYMENT_FORMAT)
    description_value = present_value(vacancy.description, DEFAULT_DESCRIPTION)
    title_text = html.escape(vacancy.position or "Р’Р°РєР°РЅСЃРёСЏ")
    title_html = (
        f'<a href="{html.escape(vacancy_url, quote=True)}">{title_text}</a>'
        if vacancy_url
        else title_text
    )

    lines = [
        f"рџ’ј <b>Р’Р°РєР°РЅСЃРёСЏ: </b>{title_html}",
        f"<b>РљРѕРјРїР°РЅРёСЏ: </b>{html.escape(vacancy.organization or 'РљРѕРјРїР°РЅРёСЏ')}",
        "",
        f"<b>Р РЋРЎвЂћР ВµРЎР‚Р В°: </b>{html.escape(sphere)}",
        f"<b>Р вЂ”Р В°РЎР‚Р С—Р В»Р В°РЎвЂљР В°: </b>{html.escape(salary)}",
        f"<b>Р вЂњРЎР‚Р В°РЎвЂћР С‘Р С”: </b>{html.escape(schedule)}",
        f"<b>Р В¤Р С•РЎР‚Р СР В°РЎвЂљ: </b>{html.escape(work_format)}",
        f"<b>Р СћР С‘Р С— Р В·Р В°Р Р…РЎРЏРЎвЂљР С•РЎРѓРЎвЂљР С‘: </b>{html.escape(employment_format)}",
    ]

    link_lines: list[str] = []
    if vacancy_url:
        link_lines = [
            "",
            "<b>РЎСЃС‹Р»РєР° РЅР° РІР°РєР°РЅСЃРёСЋ:</b>",
            f'<a href="{html.escape(vacancy_url, quote=True)}">{html.escape(_truncate_plain_text(vacancy_url, 110))}</a>',
        ]

    description_lines: list[str] = []
    if description_value:
        skeleton = "\n".join(lines + ["", "<blockquote></blockquote>"] + link_lines)
        remaining = max(40, 990 - len(skeleton))
        description = _truncate_plain_text(description_value, min(220, remaining))
        if description:
            description_lines = ["", f"<blockquote>{html.escape(description)}</blockquote>"]

    text = "\n".join(lines + description_lines + link_lines)
    if len(text) <= 1000:
        return text

    if description_value:
        for limit in (160, 120, 80, 40):
            description = _truncate_plain_text(description_value, limit)
            candidate_description_lines = ["", f"<blockquote>{html.escape(description)}</blockquote>"] if description else []
            candidate = "\n".join(lines + candidate_description_lines + link_lines)
            if len(candidate) <= 1000:
                return candidate

    if vacancy_url:
        for url_limit in (90, 70, 50, 30):
            compact_link_lines = [
                "",
                "<b>РЎСЃС‹Р»РєР° РЅР° РІР°РєР°РЅСЃРёСЋ:</b>",
                f'<a href="{html.escape(vacancy_url, quote=True)}">{html.escape(_truncate_plain_text(vacancy_url, url_limit))}</a>',
            ]
            candidate = "\n".join(lines + compact_link_lines)
            if len(candidate) <= 1000:
                return candidate

    return "\n".join(lines[:2])


def format_vacancy(vacancy: Vacancy, show_match: bool = False, user_faculty: str = None) -> str:
    vacancy_url = (getattr(vacancy, "vacancy_url", "") or "").strip()
    sphere = present_value(vacancy.sphere, DEFAULT_SPHERE)
    salary = present_value(vacancy.salary, DEFAULT_SALARY)
    schedule = present_value(vacancy.schedule, DEFAULT_SCHEDULE)
    work_format = present_value(vacancy.work_format, DEFAULT_WORK_FORMAT)
    employment_format = present_value(vacancy.employment_format, DEFAULT_EMPLOYMENT_FORMAT)
    description_value = present_value(vacancy.description, DEFAULT_DESCRIPTION)
    title_text = html.escape(vacancy.position or "Р’Р°РєР°РЅСЃРёСЏ")
    title_html = (
        f'<a href="{html.escape(vacancy_url, quote=True)}">{title_text}</a>'
        if vacancy_url
        else title_text
    )

    lines = [
        f"рџ’ј <b>Р’Р°РєР°РЅСЃРёСЏ: </b>{title_html}",
        f"<b>РљРѕРјРїР°РЅРёСЏ: </b>{html.escape(vacancy.organization or 'РљРѕРјРїР°РЅРёСЏ')}",
        "",
        f"<b>Р РЋРЎвЂћР ВµРЎР‚Р В°: </b>{html.escape(sphere)}",
        f"<b>Р вЂ”Р В°РЎР‚Р С—Р В»Р В°РЎвЂљР В°: </b>{html.escape(salary)}",
        f"<b>Р вЂњРЎР‚Р В°РЎвЂћР С‘Р С”: </b>{html.escape(schedule)}",
        f"<b>Р В¤Р С•РЎР‚Р СР В°РЎвЂљ: </b>{html.escape(work_format)}",
        f"<b>Р СћР С‘Р С— Р В·Р В°Р Р…РЎРЏРЎвЂљР С•РЎРѓРЎвЂљР С‘: </b>{html.escape(employment_format)}"
    ]

    if description_value:
        desc = description_value[:150] + "..." if len(description_value) > 150 else description_value
        lines.append(f"\n<blockquote>{html.escape(desc)}</blockquote>")

    if vacancy_url:
        lines.extend([
            "",
            "<b>РЎСЃС‹Р»РєР° РЅР° РІР°РєР°РЅСЃРёСЋ:</b>",
            f'<a href="{html.escape(vacancy_url, quote=True)}">{html.escape(vacancy_url)}</a>',
        ])

    text = "\n".join(lines)
    features = []
    if vacancy.feature1:
        features.append(f"вњ“ {html.escape(vacancy.feature1)}")
    if vacancy.feature2:
        features.append(f"вњ“ {html.escape(vacancy.feature2)}")
    if vacancy.feature3:
        features.append(f"вњ“ {html.escape(vacancy.feature3)}")
    
    if not features:
        features.append(f"- {html.escape(present_features()[0])}")

    if features:
        text += f"\n<b>РџСЂРµРёРјСѓС‰РµСЃС‚РІР°:</b>\n" + "\n".join(features)
    
    return text


async def get_user_vacancies_count(session, user_faculty: str) -> int:
    """РџРѕР»СѓС‡РёС‚СЊ РєРѕР»РёС‡РµСЃС‚РІРѕ РІР°РєР°РЅСЃРёР№ РґР»СЏ С„Р°РєСѓР»СЊС‚РµС‚Р° РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"""
    db_field = FACULTY_TO_DB_FIELD.get(user_faculty)
    if not db_field:
        return 0
    
    filter_condition = getattr(Vacancy, db_field) == True
    result = await session.execute(
        select(func.count(Vacancy.id)).where(filter_condition)
    )
    return result.scalar() or 0


def get_events_list_keyboard(events: list[Event]) -> InlineKeyboardMarkup:
    keyboard = []
    for event in events:
        title = event.title if len(event.title) <= 32 else f"{event.title[:29]}..."
        keyboard.append([InlineKeyboardButton(text=title, callback_data=f"view_event_{event.id}")])
    keyboard.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_event_keyboard(event_id: int, can_register: bool, already_registered: bool) -> InlineKeyboardMarkup:
    buttons = []
    if already_registered:
        buttons.append([InlineKeyboardButton(text="Р’С‹ СѓР¶Рµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅС‹", callback_data="noop")])
    elif can_register:
        buttons.append([InlineKeyboardButton(text="Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊСЃСЏ", callback_data=f"event_register_{event_id}")])
    buttons.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_event_text(event: Event, main_count: int, reserve_count: int, user_status: str | None = None) -> str:
    lines = [
        f"<b>{html.escape(event.title)}</b>",
        "",
        html.escape(event.description) if event.description else "РћРїРёСЃР°РЅРёРµ РїРѕРєР° РЅРµ Р·Р°РїРѕР»РЅРµРЅРѕ.",
    ]
    return "\n".join(lines)


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
вќ¤пёЏ <b>РљРѕРјРёС‚РµС‚ Р’РЅРµС€РЅРёС… РЎРІСЏР·РµР№</b> рџ–¤

РџСЂРёРІРµС‚, <b>{user.first_name}</b>! 

Р”Р»СЏ С‚РµР±СЏ СЃРµР№С‡Р°СЃ: <b>{vacancies_count}</b> РІР°РєР°РЅСЃРёР№

Р’С‹Р±РµСЂРё РґРµР№СЃС‚РІРёРµ:
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
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРѕРјР°РЅРґС‹ /start - РіР»Р°РІРЅРѕРµ РјРµРЅСЋ"""
    await show_main_menu_or_registration(message, state, message.from_user.id)


@router.message(Command("vacancies"))
async def cmd_vacancies(message: Message):
    """РљРѕРјР°РЅРґР° РґР»СЏ РїСЂРѕСЃРјРѕС‚СЂР° РІР°РєР°РЅСЃРёР№"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_registered:
            await message.answer(
                "вќЊ Р”Р»СЏ РїСЂРѕСЃРјРѕС‚СЂР° РІР°РєР°РЅСЃРёР№ РЅСѓР¶РЅРѕ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊСЃСЏ.\n"
                "РќР°Р¶РјРё /start РґР»СЏ СЂРµРіРёСЃС‚СЂР°С†РёРё."
            )
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        welcome_text = f"""
вќ¤пёЏ <b>РљРѕРјРёС‚РµС‚ Р’РЅРµС€РЅРёС… РЎРІСЏР·РµР№</b> рџ–¤

РџСЂРёРІРµС‚, <b>{user.first_name}</b>! 

Р”Р»СЏ С‚РµР±СЏ СЃРµР№С‡Р°СЃ: <b>{vacancies_count}</b> РІР°РєР°РЅСЃРёР№

Р’С‹Р±РµСЂРё РґРµР№СЃС‚РІРёРµ:
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
    """РћР±СЂР°Р±РѕС‚РєР° РІРѕР·РІСЂР°С‚Р° РІ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("РћС€РёР±РєР°", show_alert=True)
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        welcome_text = f"""
вќ¤пёЏ <b>РљРѕРјРёС‚РµС‚ Р’РЅРµС€РЅРёС… РЎРІСЏР·РµР№</b> рџ–¤

РџСЂРёРІРµС‚, <b>{user.first_name}</b>! 

Р”Р»СЏ С‚РµР±СЏ СЃРµР№С‡Р°СЃ: <b>{vacancies_count}</b> РІР°РєР°РЅСЃРёР№

Р’С‹Р±РµСЂРё РґРµР№СЃС‚РІРёРµ:
"""
        keyboard = get_main_menu_keyboard(user.faculty, vacancies_count)
        
        # Р’СЃРµРіРґР° РїРѕРєР°Р·С‹РІР°РµРј РєР°СЂС‚РёРЅРєСѓ СЃ caption
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
    """РџСѓСЃС‚РѕР№ callback РґР»СЏ СЃС‡С‘С‚С‡РёРєР°"""
    await callback.answer()


@router.callback_query(F.data == "feedback")
async def callback_feedback(callback: CallbackQuery, state: FSMContext):
    """РћР±СЂР°С‚РЅР°СЏ СЃРІСЏР·СЊ"""
    text = """
        рџ’¬ <b>РћР±СЂР°С‚РЅР°СЏ СЃРІСЏР·СЊ</b>

РќР°РїРёС€Рё СЃРІРѕС‘ СЃРѕРѕР±С‰РµРЅРёРµ, Рё РјС‹ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕ РµРіРѕ РїРѕР»СѓС‡РёРј!

<i>Р­С‚Рѕ РјРѕР¶РµС‚ Р±С‹С‚СЊ РІРѕРїСЂРѕСЃ, РїСЂРµРґР»РѕР¶РµРЅРёРµ РёР»Рё СЃРѕРѕР±С‰РµРЅРёРµ Рѕ РїСЂРѕР±Р»РµРјРµ.</i>
"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="РћС‚РјРµРЅР°", callback_data="main_menu")]
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
    """Рћ РЅР°СЃ"""
    text = """
вќ¤пёЏ <b>Рћ РљРѕРјРёС‚РµС‚Рµ Р’РЅРµС€РЅРёС… РЎРІСЏР·РµР№</b> рџ–¤

РљРѕРјРёС‚РµС‚ Р’РЅРµС€РЅРёС… РЎРІСЏР·РµР№ вЂ” СЌС‚Рѕ С‡Р°СЃС‚СЊ РЎС‚СѓРґРµРЅС‡РµСЃРєРѕРіРѕ СЃРѕРІРµС‚Р° Р¤РёРЅР°РЅСЃРѕРІРѕРіРѕ РЈРЅРёРІРµСЂСЃРёС‚РµС‚Р°, РєРѕС‚РѕСЂР°СЏ РѕС‚РІРµС‡Р°РµС‚ Р·Р° РІР·Р°РёРјРѕРґРµР№СЃС‚РІРёРµ СЃРѕ РІРЅРµС€РЅРёРјРё РѕСЂРіР°РЅРёР·Р°С†РёСЏРјРё, РїР°СЂС‚РЅС‘СЂР°РјРё Рё СЃРїРѕРЅСЃРѕСЂР°РјРё Рё РїРѕРјРѕРіР°РµС‚ СЃС‚СѓРґРµРЅС‚Р°Рј СЃ РєР°СЂСЊРµСЂРѕР№ Рё РІРѕР·РјРѕР¶РЅРѕСЃС‚СЏРјРё РІРЅРµ СѓС‡С‘Р±С‹.

<b>РќР°С€Р° РјРёСЃСЃРёСЏ:</b>
РџРѕРјРѕС‡СЊ РєР°Р¶РґРѕРјСѓ СЃС‚СѓРґРµРЅС‚Сѓ РЅР°Р№С‚Рё СЂР°Р±РѕС‚Сѓ РјРµС‡С‚С‹ Рё РЅР°С‡Р°С‚СЊ СѓСЃРїРµС€РЅСѓСЋ РєР°СЂСЊРµСЂСѓ.

<b>Р§С‚Рѕ РјС‹ РґРµР»Р°РµРј:</b>
вЂў РЎРѕР±РёСЂР°РµРј Р°РєС‚СѓР°Р»СЊРЅС‹Рµ РІР°РєР°РЅСЃРёРё
вЂў РЎРѕС‚СЂСѓРґРЅРёС‡Р°РµРј СЃ С‚РѕРїРѕРІС‹РјРё РєРѕРјРїР°РЅРёСЏРјРё
вЂў РџРѕРјРѕРіР°РµРј СЃ С‚СЂСѓРґРѕСѓСЃС‚СЂРѕР№СЃС‚РІРѕРј

рџ’ј <b>РџСЂРёСЃРѕРµРґРёРЅСЏР№СЃСЏ Рє РЅР°Рј!</b>
"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
    ])
    
    await callback.message.delete()
    if ABOUT_US_IMAGE_PATHS:
        media = []
        for index, path in enumerate(ABOUT_US_IMAGE_PATHS):
            if index == 0:
                media.append(
                    InputMediaPhoto(
                        media=FSInputFile(path),
                        caption=text,
                        parse_mode="HTML",
                    )
                )
            else:
                media.append(InputMediaPhoto(media=FSInputFile(path)))
        await callback.message.answer_media_group(media=media)
        await callback.message.answer("Р’С‹Р±РµСЂРё РґРµР№СЃС‚РІРёРµ:", reply_markup=keyboard)
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.message(FeedbackStates.waiting_for_message)
async def process_feedback_message(message: Message, state: FSMContext, bot: Bot):
    """Forward feedback to admins with escaped user content."""
    await state.clear()
    
    # РџРѕР»СѓС‡Р°РµРј РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ РїРѕР»СЊР·РѕРІР°С‚РµР»Рµ
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
    
    # Р¤РѕСЂРјРёСЂСѓРµРј СЃРѕРѕР±С‰РµРЅРёРµ РґР»СЏ Р°РґРјРёРЅРѕРІ
    user_info_raw = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    user_name_raw = (
        format_full_name(user.first_name, user.last_name, user.patronymic)
        if user else message.from_user.full_name
    )
    faculty_raw = user.faculty if user else "РќРµ СѓРєР°Р·Р°РЅ"
    content_label = "[РќРµ С‚РµРєСЃС‚РѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ]"
    if message.photo:
        content_label = "[Р¤РѕС‚Рѕ]"
    elif message.animation:
        content_label = "[GIF]"
    elif message.video:
        content_label = "[Р’РёРґРµРѕ]"
    elif message.document:
        content_label = "[Р”РѕРєСѓРјРµРЅС‚]"
    elif message.voice:
        content_label = "[Р“РѕР»РѕСЃРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ]"
    elif message.audio:
        content_label = "[РђСѓРґРёРѕ]"
    elif message.video_note:
        content_label = "[Р’РёРґРµРѕ-СЃРѕРѕР±С‰РµРЅРёРµ]"
    elif message.sticker:
        content_label = "[РЎС‚РёРєРµСЂ]"

    feedback_text = message.text or message.caption or content_label
    has_attachment = any(
        (
            message.photo,
            message.animation,
            message.video,
            message.document,
            message.voice,
            message.audio,
            message.video_note,
            message.sticker,
        )
    )

    user_info = html.escape(user_info_raw)
    user_name = html.escape(user_name_raw)
    faculty = html.escape(faculty_raw)
    feedback_text = html.escape(feedback_text)
    
    admin_text = f"""
<b>РќРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РѕР±СЂР°С‚РЅРѕР№ СЃРІСЏР·Рё</b>

<b>РћС‚:</b> {user_name}
<b>РљРѕРЅС‚Р°РєС‚:</b> {user_info}
<b>Р¤Р°РєСѓР»СЊС‚РµС‚:</b> {faculty}

в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ
рџ’¬ <b>РЎРѕРѕР±С‰РµРЅРёРµ:</b>
{feedback_text}
"""
    
    # РћС‚РїСЂР°РІР»СЏРµРј РІСЃРµРј Р°РґРјРёРЅР°Рј
    sent_count = 0
    for admin_id in await get_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                parse_mode="HTML",
                reply_markup=get_feedback_admin_keyboard(message.from_user.id),
            )
            if has_attachment:
                await message.copy_to(chat_id=admin_id)
            sent_count += 1
        except Exception:
            pass
    
    # РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ
    await message.answer(
        "вњ… <b>РЎРѕРѕР±С‰РµРЅРёРµ РѕС‚РїСЂР°РІР»РµРЅРѕ!</b>\n\n"
        "РЎРїР°СЃРёР±Рѕ Р·Р° РѕР±СЂР°С‚РЅСѓСЋ СЃРІСЏР·СЊ. РњС‹ РїРѕСЃС‚Р°СЂР°РµРјСЃСЏ РѕС‚РІРµС‚РёС‚СЊ РєР°Рє РјРѕР¶РЅРѕ СЃРєРѕСЂРµРµ.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
    )


@router.callback_query(F.data == "events_list")
async def callback_events_list(callback: CallbackQuery):
    """Show available events for users."""
    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        ).scalar_one_or_none()
        if not user or not user.is_registered:
            await callback.answer("РЎРЅР°С‡Р°Р»Р° РїСЂРѕР№РґРё СЂРµРіРёСЃС‚СЂР°С†РёСЋ С‡РµСЂРµР· /start", show_alert=True)
            return

        events = (
            await session.execute(
                select(Event).where(Event.is_active.is_(True)).order_by(Event.created_at.desc(), Event.id.desc())
            )
        ).scalars().all()

    if not events:
        text = "<b>РњРµСЂРѕРїСЂРёСЏС‚РёСЏ</b>\n\nРЎРµР№С‡Р°СЃ РґРѕСЃС‚СѓРїРЅС‹С… РјРµСЂРѕРїСЂРёСЏС‚РёР№ РЅРµС‚."
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]]
        )
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
        return

    text = "<b>РњРµСЂРѕРїСЂРёСЏС‚РёСЏ</b>\n\nР’С‹Р±РµСЂРё РјРµСЂРѕРїСЂРёСЏС‚РёРµ, С‡С‚РѕР±С‹ РїРѕСЃРјРѕС‚СЂРµС‚СЊ РѕРїРёСЃР°РЅРёРµ Рё Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊСЃСЏ."
    keyboard = get_events_list_keyboard(events)
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("view_event_"))
async def callback_view_event(callback: CallbackQuery):
    """Show one event card."""
    try:
        event_id = int(callback.data.replace("view_event_", ""))
    except ValueError:
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID РјРµСЂРѕРїСЂРёСЏС‚РёСЏ", show_alert=True)
        return

    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        ).scalar_one_or_none()
        if not user or not user.is_registered:
            await callback.answer("РЎРЅР°С‡Р°Р»Р° РїСЂРѕР№РґРё СЂРµРіРёСЃС‚СЂР°С†РёСЋ С‡РµСЂРµР· /start", show_alert=True)
            return

        event = (
            await session.execute(
                select(Event).where(Event.id == event_id, Event.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if not event:
            await callback.answer("РњРµСЂРѕРїСЂРёСЏС‚РёРµ РЅРµ РЅР°Р№РґРµРЅРѕ", show_alert=True)
            return

        main_count = (
            await session.execute(
                select(func.count(EventRegistration.id)).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.status == "main",
                )
            )
        ).scalar() or 0
        reserve_count = (
            await session.execute(
                select(func.count(EventRegistration.id)).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.status == "reserve",
                )
            )
        ).scalar() or 0
        registration = (
            await session.execute(
                select(EventRegistration).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.user_id == user.id,
                )
            )
        ).scalar_one_or_none()

    text = build_event_text(event, main_count, reserve_count, registration.status if registration else None)
    keyboard = get_event_keyboard(event.id, can_register=True, already_registered=registration is not None)
    await callback.message.delete()
    if event.photo_file_id:
        try:
            await callback.message.answer_photo(
                photo=get_event_photo_input(event.photo_file_id),
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("event_register_"))
async def callback_event_register(callback: CallbackQuery):
    """Register a user for an event with main/reserve allocation."""
    try:
        event_id = int(callback.data.replace("event_register_", ""))
    except ValueError:
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID РјРµСЂРѕРїСЂРёСЏС‚РёСЏ", show_alert=True)
        return

    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        ).scalar_one_or_none()
        if not user or not user.is_registered:
            await callback.answer("РЎРЅР°С‡Р°Р»Р° РїСЂРѕР№РґРё СЂРµРіРёСЃС‚СЂР°С†РёСЋ С‡РµСЂРµР· /start", show_alert=True)
            return

        event = (
            await session.execute(
                select(Event).where(Event.id == event_id, Event.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if not event:
            await callback.answer("РњРµСЂРѕРїСЂРёСЏС‚РёРµ РЅРµ РЅР°Р№РґРµРЅРѕ", show_alert=True)
            return

        existing_registration = (
            await session.execute(
                select(EventRegistration).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing_registration:
            await callback.answer("РўС‹ СѓР¶Рµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅ РЅР° СЌС‚Рѕ РјРµСЂРѕРїСЂРёСЏС‚РёРµ", show_alert=True)
            return

        main_count = (
            await session.execute(
                select(func.count(EventRegistration.id)).where(
                    EventRegistration.event_id == event.id,
                    EventRegistration.status == "main",
                )
            )
        ).scalar() or 0
        status = "main" if main_count < event.capacity else "reserve"
        session.add(EventRegistration(event_id=event.id, user_id=user.id, status=status))
        await session.flush()
        try:
            await export_event_registrations_to_sheet(session, event)
        except Exception:
            pass
        await session.commit()

        response_text = event.success_message if status == "main" else event.reserve_message

    await callback.message.answer(
        response_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Рљ РјРµСЂРѕРїСЂРёСЏС‚РёСЋ", callback_data=f"view_event_{event_id}")],
                [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")],
            ]
        ),
    )
    await callback.answer("Р РµРіРёСЃС‚СЂР°С†РёСЏ СЃРѕС…СЂР°РЅРµРЅР°")


@router.callback_query(F.data == "vacancies_menu")
async def callback_vacancies_menu(callback: CallbackQuery):
    """РњРµРЅСЋ РІР°РєР°РЅСЃРёР№"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("РћС€РёР±РєР°", show_alert=True)
            return
        
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        text = f"""
          <b>Р’Р°РєР°РЅСЃРёРё</b>

Р’С‹Р±РµСЂРё СЃРїРѕСЃРѕР± РїСЂРѕСЃРјРѕС‚СЂР°:
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Р”Р»СЏ РјРµРЅСЏ ({vacancies_count})", callback_data="my_vacancies")],
            [InlineKeyboardButton(text="Р’СЃРµ РІР°РєР°РЅСЃРёРё", callback_data="all_vacancies")],
            [InlineKeyboardButton(text="РџРѕ СЃС„РµСЂР°Рј", callback_data="vacancies_by_sphere")],
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
        
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()


@router.callback_query(F.data == "my_vacancies")
async def callback_my_vacancies(callback: CallbackQuery):
    """РџРѕРєР°Р·Р°С‚СЊ РІР°РєР°РЅСЃРёРё РґР»СЏ С„Р°РєСѓР»СЊС‚РµС‚Р° РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.faculty:
            await callback.answer("РћС€РёР±РєР°: С„Р°РєСѓР»СЊС‚РµС‚ РЅРµ СѓРєР°Р·Р°РЅ", show_alert=True)
            return
        
        db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
        if not db_field:
            await callback.answer("РћС€РёР±РєР°: РЅРµРёР·РІРµСЃС‚РЅС‹Р№ С„Р°РєСѓР»СЊС‚РµС‚", show_alert=True)
            return
        
        filter_condition = getattr(Vacancy, db_field) == True
        result = await session.execute(
            select(Vacancy).where(filter_condition).order_by(Vacancy.created_at.desc())
        )
        vacancies = result.scalars().all()
        
        if not vacancies:
            await callback.message.edit_text(
                f"рџ” <b>РќРµС‚ РІР°РєР°РЅСЃРёР№</b>\n\n"
                f"Рљ СЃРѕР¶Р°Р»РµРЅРёСЋ, РґР»СЏ С„Р°РєСѓР»СЊС‚РµС‚Р° <b>{user.faculty}</b> РїРѕРєР° РЅРµС‚ РґРѕСЃС‚СѓРїРЅС‹С… РІР°РєР°РЅСЃРёР№.\n\n"
                "РџРѕРїСЂРѕР±СѓР№ РїРѕСЃРјРѕС‚СЂРµС‚СЊ РІСЃРµ РІР°РєР°РЅСЃРёРё РёР»Рё Р·Р°Р№РґРё РїРѕР·Р¶Рµ.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Р’СЃРµ РІР°РєР°РЅСЃРёРё", callback_data="all_vacancies")],
                    [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        has_company_desc = await check_company_has_description(session, vacancy.organization, vacancy.vacancy_url)
        
        # РЈРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рё РѕС‚РїСЂР°РІР»СЏРµРј С„РѕС‚Рѕ
        await callback.message.delete()
        
        photo = get_vacancy_photo_input(vacancy)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "my", has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data == "all_vacancies")
async def callback_all_vacancies(callback: CallbackQuery):
    """РџРѕРєР°Р·Р°С‚СЊ РІСЃРµ РІР°РєР°РЅСЃРёРё"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Vacancy).order_by(Vacancy.created_at.desc())
        )
        vacancies = result.scalars().all()
        
        if not vacancies:
            await callback.message.edit_text(
                "рџ” <b>РќРµС‚ РІР°РєР°РЅСЃРёР№</b>\n\n"
                "Р’ Р±Р°Р·Рµ РїРѕРєР° РЅРµС‚ РІР°РєР°РЅСЃРёР№.\n"
                "РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ РјРѕР¶РµС‚ СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°С‚СЊ РёС… РёР· Google Sheets.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]
        caption = format_vacancy_caption(vacancy)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        has_company_desc = await check_company_has_description(session, vacancy.organization, vacancy.vacancy_url)
        
        # РЈРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рё РѕС‚РїСЂР°РІР»СЏРµРј С„РѕС‚Рѕ
        await callback.message.delete()
        
        photo = get_vacancy_photo_input(vacancy)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "all", has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data == "vacancies_by_sphere")
async def callback_vacancies_by_sphere(callback: CallbackQuery):
    """РџРѕРєР°Р·Р°С‚СЊ РІР°РєР°РЅСЃРёРё РїРѕ СЃС„РµСЂР°Рј"""
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј СѓРЅРёРєР°Р»СЊРЅС‹Рµ СЃС„РµСЂС‹ СЃ РєРѕР»РёС‡РµСЃС‚РІРѕРј РІР°РєР°РЅСЃРёР№
        spheres = await get_available_spheres(session)
        
        text = "<b>Р’С‹Р±РµСЂРё СЃС„РµСЂСѓ:</b>\n\n" \
               "РќР°Р¶РјРё РЅР° РёРЅС‚РµСЂРµСЃСѓСЋС‰СѓСЋ СЃС„РµСЂСѓ, С‡С‚РѕР±С‹ РїРѕСЃРјРѕС‚СЂРµС‚СЊ РІР°РєР°РЅСЃРёРё:"
        
        if not spheres:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
            ])
            text = "рџ” РќРµС‚ РІР°РєР°РЅСЃРёР№ РґР»СЏ С„РёР»СЊС‚СЂР°С†РёРё РїРѕ СЃС„РµСЂР°Рј."
        else:
            keyboard_rows = []
            for sphere, count in spheres:
                keyboard_rows.append([InlineKeyboardButton(
                    text=f"{sphere} ({count})",
                    callback_data=f"sphere_{sphere}"
                )])
            keyboard_rows.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        # Р•СЃР»Рё С‚РµРєСѓС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ - С„РѕС‚Рѕ, СѓРґР°Р»СЏРµРј Рё РѕС‚РїСЂР°РІР»СЏРµРј С‚РµРєСЃС‚
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
    """РџРѕРєР°Р·Р°С‚СЊ РІР°РєР°РЅСЃРёРё РєРѕРЅРєСЂРµС‚РЅРѕР№ СЃС„РµСЂС‹"""
    sphere = normalize_sphere_name(callback.data.replace("sphere_", "", 1))
    if not sphere:
        await callback.answer("РЎС„РµСЂР° РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
        return

    async with async_session_maker() as session:
        vacancies = await get_vacancies_for_sphere(session, sphere)
        
        if not vacancies:
            await callback.message.edit_text(
                f"рџ” РќРµС‚ РІР°РєР°РЅСЃРёР№ РІ СЃС„РµСЂРµ В«{sphere}В»",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Рљ СЃС„РµСЂР°Рј", callback_data="vacancies_by_sphere")],
                    [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
                ])
            )
            await callback.answer()
            return
        
        vacancy = vacancies[0]

        caption =format_vacancy_caption(vacancy)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        has_company_desc = await check_company_has_description(session, vacancy.organization, vacancy.vacancy_url)
        
        # РЈРґР°Р»СЏРµРј СЃС‚Р°СЂРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рё РѕС‚РїСЂР°РІР»СЏРµРј С„РѕС‚Рѕ
        await callback.message.delete()
        
        photo = get_vacancy_photo_input(vacancy)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, 0, len(vacancies), "sphere", sphere, has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()


@router.callback_query(F.data.startswith("vac_"))
async def callback_vacancy_navigation(callback: CallbackQuery):
    """РќР°РІРёРіР°С†РёСЏ РїРѕ РІР°РєР°РЅСЃРёСЏРј СЃ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµРј РєР°СЂС‚РёРЅРєРё"""
    parts = callback.data.split("_", 3)
    if len(parts) < 3:
        await callback.answer("РћС€РёР±РєР° РЅР°РІРёРіР°С†РёРё", show_alert=True)
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
                await callback.answer("РћС€РёР±РєР°: С„Р°РєСѓР»СЊС‚РµС‚ РЅРµ СѓРєР°Р·Р°РЅ", show_alert=True)
                return
            
            db_field = FACULTY_TO_DB_FIELD.get(user.faculty)
            if not db_field:
                await callback.answer("РћС€РёР±РєР°", show_alert=True)
                return
            
            filter_condition = getattr(Vacancy, db_field) == True
            result = await session.execute(
                select(Vacancy).where(filter_condition).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        elif filter_type == "sphere" and sphere:
            vacancies = await get_vacancies_for_sphere(session, sphere)
        elif filter_type == "division" and sphere:
            # sphere СЃРѕРґРµСЂР¶РёС‚ division_id
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
                    vacancies = await get_company_vacancies(session, company.name, division.name)
                else:
                    vacancies = []
            else:
                vacancies = []
        elif filter_type == "company" and sphere:
            # sphere СЃРѕРґРµСЂР¶РёС‚ company_id
            company_id = int(sphere)
            company_result = await session.execute(
                select(Company).where(Company.id == company_id)
            )
            company = company_result.scalar_one_or_none()
            if company:
                vacancies = await get_company_vacancies(session, company.name)
            else:
                vacancies = []
        else:
            result = await session.execute(
                select(Vacancy).order_by(Vacancy.created_at.desc())
            )
            vacancies = result.scalars().all()
        
        if target_index < 0 or target_index >= len(vacancies):
            await callback.answer("Р”РѕСЃС‚РёРіРЅСѓС‚ РєРѕРЅРµС† СЃРїРёСЃРєР°", show_alert=True)
            return
        
        vacancy = vacancies[target_index]
        
        # Р¤РѕСЂРјРёСЂСѓРµРј caption
        if filter_type == "sphere" and sphere:
            emoji = SPHERE_EMOJI.get(sphere, "рџ’ј")
            caption = f"{emoji} <b>РЎС„РµСЂР°: {sphere}</b>\n\n" + format_vacancy_caption(vacancy)
        else:
            caption = format_vacancy_caption(vacancy)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        has_company_desc = await check_company_has_description(session, vacancy.organization, vacancy.vacancy_url)
        
        # РџРѕР»СѓС‡Р°РµРј РёР»Рё РіРµРЅРµСЂРёСЂСѓРµРј РёР·РѕР±СЂР°Р¶РµРЅРёРµ
        photo = get_vacancy_photo_input(vacancy)
        
        # Р РµРґР°РєС‚РёСЂСѓРµРј РјРµРґРёР° (РєР°СЂС‚РёРЅРєСѓ) РІРјРµСЃС‚Рѕ С‚РµРєСЃС‚Р°
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
    """РџСЂРѕС„РёР»СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.answer("РћС€РёР±РєР°: РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РєРѕР»РёС‡РµСЃС‚РІРѕ РІР°РєР°РЅСЃРёР№ РґР»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
        vacancies_count = await get_user_vacancies_count(session, user.faculty)
        
        text = f"""
          рџ‘¤ <b>РњРѕР№ РїСЂРѕС„РёР»СЊ</b>

<b>РРјСЏ:</b> {user.first_name}
<b>Р¤Р°РјРёР»РёСЏ:</b> {user.last_name}
<b>РћС‚С‡РµСЃС‚РІРѕ:</b> {user.patronymic or "--"}
<b>РљСѓСЂСЃ:</b> {format_course_label(user.course)}
<b>Р¤Р°РєСѓР»СЊС‚РµС‚:</b> {user.faculty}
<b>РћС‚РєСѓРґР° СѓР·РЅР°Р»:</b> {user.info_source}


Р”РѕСЃС‚СѓРїРЅРѕ РІР°РєР°РЅСЃРёР№: <b>{vacancies_count}</b>
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="РР·РјРµРЅРёС‚СЊ Р¤РРћ", callback_data="edit_name")],
            [InlineKeyboardButton(text="РР·РјРµРЅРёС‚СЊ РєСѓСЂСЃ", callback_data="edit_course")],
            [InlineKeyboardButton(text="РР·РјРµРЅРёС‚СЊ С„Р°РєСѓР»СЊС‚РµС‚", callback_data="edit_faculty")],
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
        
        # Р•СЃР»Рё С‚РµРєСѓС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ - С„РѕС‚Рѕ, СѓРґР°Р»СЏРµРј Рё РѕС‚РїСЂР°РІР»СЏРµРј С‚РµРєСЃС‚
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
    """РџРѕРєР°Р·Р°С‚СЊ СЃРїРёСЃРѕРє РєРѕРјРїР°РЅРёР№ РґР»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"""
    text = "<b>РљРѕРјРїР°РЅРёРё-РїР°СЂС‚РЅРµСЂС‹</b>\n\nР’ СЂР°Р·СЂР°Р±РѕС‚РєРµ, СЃРєРѕСЂРѕ Р±СѓРґРµС‚."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ]
    )

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    await callback.message.answer("рџ¤—")
    await callback.answer()
    return

    async with async_session_maker() as session:
        vacancy_companies_result = await session.execute(
            select(distinct(Vacancy.organization))
            .where(Vacancy.organization.isnot(None), Vacancy.organization != "")
        )
        vacancy_companies = {row[0] for row in vacancy_companies_result.all() if row[0]}

        if vacancy_companies:
            existing_companies_result = await session.execute(
                select(Company).where(Company.name.isnot(None), Company.name != "")
            )
            existing_company_names = {
                normalize_company_name(company.name)
                for company in existing_companies_result.scalars().all()
                if normalize_company_name(company.name)
            }
            missing_company_names = sorted(
                clean_company_name(company_name)
                for company_name in vacancy_companies
                if normalize_company_name(company_name) not in existing_company_names
            )
            for company_name in missing_company_names:
                session.add(Company(name=company_name, description=None))
            if missing_company_names:
                await session.commit()

        # РџРѕР»СѓС‡Р°РµРј РІСЃРµ РєРѕРјРїР°РЅРёРё, РґР°Р¶Рµ РµСЃР»Рё РѕРїРёСЃР°РЅРёРµ РїРѕРєР° РЅРµ Р·Р°РїРѕР»РЅРµРЅРѕ
        result = await session.execute(
            select(Company)
            .where(Company.name.isnot(None), Company.name != "")
            .order_by(Company.name)
        )
        companies = deduplicate_companies(result.scalars().all())
        
        if not companies:
            # Р•СЃР»Рё С‚РµРєСѓС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ - С„РѕС‚Рѕ, СѓРґР°Р»СЏРµРј Рё РѕС‚РїСЂР°РІР»СЏРµРј С‚РµРєСЃС‚
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(
                    "<b>РљРѕРјРїР°РЅРёРё</b>\n\n"
                    "РџРѕРєР° РЅРµС‚ РёРЅС„РѕСЂРјР°С†РёРё Рѕ РєРѕРјРїР°РЅРёСЏС….\n"
                    "Р—Р°РіР»СЏРЅРё РїРѕР·Р¶Рµ!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
                    ])
                )
            else:
                await callback.message.edit_text(
                    "<b>РљРѕРјРїР°РЅРёРё</b>\n\n"
                    "РџРѕРєР° РЅРµС‚ РёРЅС„РѕСЂРјР°С†РёРё Рѕ РєРѕРјРїР°РЅРёСЏС….\n"
                    "Р—Р°РіР»СЏРЅРё РїРѕР·Р¶Рµ!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
                    ])
                )
            await callback.answer()
            return
        
        text = f"""
          <b>РљРѕРјРїР°РЅРёРё</b>

Р’С‹Р±РµСЂРё РєРѕРјРїР°РЅРёСЋ, С‡С‚РѕР±С‹ СѓР·РЅР°С‚СЊ Рѕ РЅРµР№ Р±РѕР»СЊС€Рµ:
"""
        
        # РЎРѕР·РґР°С‘Рј РєРЅРѕРїРєРё РґР»СЏ РєР°Р¶РґРѕР№ РєРѕРјРїР°РЅРёРё
        keyboard = []
        for company in companies:
            keyboard.append([
                InlineKeyboardButton(
                    text=f" {clean_company_name(company.name)}",
                    callback_data=f"view_company_{company.id}"
                )
            ])
        keyboard.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
        
        # Р•СЃР»Рё С‚РµРєСѓС‰РµРµ СЃРѕРѕР±С‰РµРЅРёРµ - С„РѕС‚Рѕ, СѓРґР°Р»СЏРµРј Рё РѕС‚РїСЂР°РІР»СЏРµРј С‚РµРєСЃС‚
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
    """РџРѕРєР°Р·Р°С‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ РєРѕРјРїР°РЅРёРё"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        company = await get_canonical_company_by_id(session, company_id)
        
        if not company:
            await callback.answer("РљРѕРјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return
        
        # РЎС‡РёС‚Р°РµРј РєРѕР»РёС‡РµСЃС‚РІРѕ РІР°РєР°РЅСЃРёР№ РѕС‚ СЌС‚РѕР№ РєРѕРјРїР°РЅРёРё
        vacancies_count = await get_company_vacancies_count(session, company.name)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ
        divisions = await get_company_divisions(session, company.name)
        
        text = f"""
<b>{clean_company_name(company.name)}</b>

{company.description or 'РћРїРёСЃР°РЅРёРµ РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚'}

Р’Р°РєР°РЅСЃРёР№: <b>{vacancies_count}</b>
РџРѕРґСЂР°Р·РґРµР»РµРЅРёР№: <b>{len(divisions)}</b>
"""
        
        # Р¤РѕСЂРјРёСЂСѓРµРј РєР»Р°РІРёР°С‚СѓСЂСѓ
        keyboard_buttons = []
        if divisions:
            keyboard_buttons.append([InlineKeyboardButton(text="РџРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ", callback_data=f"company_divisions_{company_id}")])
        if vacancies_count > 0:
            keyboard_buttons.append([InlineKeyboardButton(text="Р’СЃРµ РІР°РєР°РЅСЃРёРё РєРѕРјРїР°РЅРёРё", callback_data=f"company_vacancies_{company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="Рљ СЃРїРёСЃРєСѓ РєРѕРјРїР°РЅРёР№", callback_data="companies_list")])
        keyboard_buttons.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # РџРѕРєР°Р·С‹РІР°РµРј РєР°СЂС‚РёРЅРєСѓ СЃ caption
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
    """РЎРїРёСЃРѕРє РїРѕРґСЂР°Р·РґРµР»РµРЅРёР№ РєРѕРјРїР°РЅРёРё"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РєРѕРјРїР°РЅРёСЋ
        company = await get_canonical_company_by_id(session, company_id)
        
        if not company:
            await callback.answer("РљРѕРјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ
        divisions = await get_company_divisions(session, company.name)
        
        if not divisions:
            await callback.answer("РЈ СЌС‚РѕР№ РєРѕРјРїР°РЅРёРё РЅРµС‚ РїРѕРґСЂР°Р·РґРµР»РµРЅРёР№", show_alert=True)
            return
        
        text = f"""
<b>РџРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ {company.name}</b>

Р’С‹Р±РµСЂРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёРµ:
"""
        
        # РљРЅРѕРїРєРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёР№
        keyboard_buttons = []
        for div in divisions:
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"{div.name}", callback_data=f"view_division_{div.id}")
            ])
        keyboard_buttons.append([InlineKeyboardButton(text="Рљ РєРѕРјРїР°РЅРёРё", callback_data=f"view_company_{company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
        
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
    """РџСЂРѕСЃРјРѕС‚СЂ РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ"""
    division_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РїРѕРґСЂР°Р·РґРµР»РµРЅРёРµ СЃ РєРѕРјРїР°РЅРёРµР№
        division_result = await session.execute(
            select(Division).where(Division.id == division_id)
        )
        division = division_result.scalar_one_or_none()
        
        if not division:
            await callback.answer("РџРѕРґСЂР°Р·РґРµР»РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РєРѕРјРїР°РЅРёСЋ
        company_result = await session.execute(
            select(Company).where(Company.id == division.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        # РЎС‡РёС‚Р°РµРј РІР°РєР°РЅСЃРёРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ
        vacancies_count = await get_company_vacancies_count(session, company.name, division.name)
        
        text = f"""
<b>{division.name}</b>
{company.name}

{division.description or 'РћРїРёСЃР°РЅРёРµ РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ'}

Р’Р°РєР°РЅСЃРёР№: <b>{vacancies_count}</b>
"""
        
        # Р¤РѕСЂРјРёСЂСѓРµРј РєР»Р°РІРёР°С‚СѓСЂСѓ
        keyboard_buttons = []
        if vacancies_count > 0:
            keyboard_buttons.append([InlineKeyboardButton(text="Р’Р°РєР°РЅСЃРёРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ", callback_data=f"division_vacancies_{division_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="Рљ РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏРј", callback_data=f"company_divisions_{division.company_id}")])
        keyboard_buttons.append([InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # РџРѕРєР°Р·С‹РІР°РµРј РєР°СЂС‚РёРЅРєСѓ СЃ caption
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
    """Р’Р°РєР°РЅСЃРёРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ"""
    division_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РїРѕРґСЂР°Р·РґРµР»РµРЅРёРµ
        division_result = await session.execute(
            select(Division).where(Division.id == division_id)
        )
        division = division_result.scalar_one_or_none()
        
        if not division:
            await callback.answer("РџРѕРґСЂР°Р·РґРµР»РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РєРѕРјРїР°РЅРёСЋ
        company_result = await session.execute(
            select(Company).where(Company.id == division.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        # РџРѕР»СѓС‡Р°РµРј РІР°РєР°РЅСЃРёРё РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ
        vacancies = await get_company_vacancies(session, company.name, division.name)
        
        if not vacancies:
            await callback.answer("РќРµС‚ РІР°РєР°РЅСЃРёР№ РІ СЌС‚РѕРј РїРѕРґСЂР°Р·РґРµР»РµРЅРёРё", show_alert=True)
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
        photo = get_vacancy_photo_input(vacancy)
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()


@router.callback_query(F.data.startswith("company_vacancies_"))
async def callback_company_vacancies(callback: CallbackQuery):
    """Р’СЃРµ РІР°РєР°РЅСЃРёРё РєРѕРјРїР°РЅРёРё"""
    company_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РєРѕРјРїР°РЅРёСЋ
        company = await get_canonical_company_by_id(session, company_id)
        
        if not company:
            await callback.answer("РљРѕРјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РІР°РєР°РЅСЃРёРё РєРѕРјРїР°РЅРёРё
        vacancies = await get_company_vacancies(session, company.name)
        
        if not vacancies:
            await callback.answer("РќРµС‚ РІР°РєР°РЅСЃРёР№ РѕС‚ СЌС‚РѕР№ РєРѕРјРїР°РЅРёРё", show_alert=True)
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
        photo = get_vacancy_photo_input(vacancy)
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await callback.answer()


# РЎРѕСЃС‚РѕСЏРЅРёСЏ РґР»СЏ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ РїСЂРѕС„РёР»СЏ
class EditProfileStates(StatesGroup):
    editing_name = State()
    editing_course = State()
    editing_faculty = State()


@router.callback_query(F.data == "edit_name")
async def callback_edit_name(callback: CallbackQuery, state: FSMContext):
    """Р РµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ Р¤РРћ"""
    await callback.message.edit_text(
        "вњЏпёЏ <b>Р РµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ Р¤РРћ</b>\n\n"
        "Р’РІРµРґРё РЅРѕРІРѕРµ РёРјСЏ, С„Р°РјРёР»РёСЋ Рё РѕС‚С‡РµСЃС‚РІРѕ С‡РµСЂРµР· РїСЂРѕР±РµР».\n"
        'Р•СЃР»Рё РѕС‚С‡РµСЃС‚РІР° РЅРµС‚, РЅР°РїРёС€Рё: <b>РќРµС‚</b>\n\n'
        "<i>РќР°РїСЂРёРјРµСЂ: РРІР°РЅ РРІР°РЅРѕРІ РќРµС‚</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="вќЊ РћС‚РјРµРЅР°", callback_data="profile")]
        ])
    )
    await state.set_state(EditProfileStates.editing_name)
    await callback.answer()


@router.message(EditProfileStates.editing_name)
async def process_edit_name(message: Message, state: FSMContext):
    """РћР±СЂР°Р±РѕС‚РєР° РЅРѕРІРѕРіРѕ Р¤РРћ"""
    # Р•СЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РІРІС‘Р» РєРѕРјР°РЅРґСѓ - РёРіРЅРѕСЂРёСЂСѓРµРј
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    parts = message.text.strip().split()
    
    if len(parts) != 3:
        await message.answer(
            "вќЊ Р’РІРµРґРё РёРјСЏ, С„Р°РјРёР»РёСЋ Рё РѕС‚С‡РµСЃС‚РІРѕ С‡РµСЂРµР· РїСЂРѕР±РµР».\n"
            'Р•СЃР»Рё РѕС‚С‡РµСЃС‚РІР° РЅРµС‚, РЅР°РїРёС€Рё: <b>РќРµС‚</b>\n'
            "<i>РќР°РїСЂРёРјРµСЂ: РРІР°РЅ РРІР°РЅРѕРІ РќРµС‚</i>",
            parse_mode="HTML"
        )
        return
    
    first_name_raw, last_name_raw, patronymic_raw = parts
    first_name_valid, first_name, first_name_error = validate_name_part(first_name_raw, "РРјСЏ")
    if not first_name_valid:
        await message.answer(first_name_error)
        return

    last_name_valid, last_name, last_name_error = validate_name_part(last_name_raw, "Р¤Р°РјРёР»РёСЏ")
    if not last_name_valid:
        await message.answer(last_name_error)
        return

    patronymic_valid, patronymic, patronymic_error = validate_name_part(
        patronymic_raw,
        "РћС‚С‡РµСЃС‚РІРѕ",
        allow_none_literal=True
    )
    if not patronymic_valid:
        await message.answer(patronymic_error + '\nР•СЃР»Рё РѕС‚С‡РµСЃС‚РІР° РЅРµС‚, РЅР°РїРёС€Рё "РќРµС‚".')
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
        f"вњ… Р¤РРћ РёР·РјРµРЅРµРЅРѕ РЅР°: <b>{format_full_name(first_name, last_name, patronymic)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Рљ РїСЂРѕС„РёР»СЋ", callback_data="profile")],
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
    )


@router.callback_query(F.data == "edit_course")
async def callback_edit_course(callback: CallbackQuery, state: FSMContext):
    """Р РµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ РєСѓСЂСЃР°"""
    keyboard_rows = []
    for level_key, level_title, years, _offset in COURSE_LEVELS:
        keyboard_rows.append([InlineKeyboardButton(text=level_title, callback_data="noop")])
        keyboard_rows.append([
            InlineKeyboardButton(text=str(year), callback_data=f"set_course_{level_key}_{year}")
            for year in years
        ])
    keyboard_rows.append([InlineKeyboardButton(text="вќЊ РћС‚РјРµРЅР°", callback_data="profile")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await callback.message.edit_text(
        "<b>Р’С‹Р±РµСЂРё СЃРІРѕР№ РєСѓСЂСЃ:</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_course_"))
async def callback_set_course(callback: CallbackQuery):
    """РЈСЃС‚Р°РЅРѕРІРєР° РєСѓСЂСЃР°"""
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
        f"вњ… РљСѓСЂСЃ РёР·РјРµРЅС‘РЅ РЅР°: <b>{format_course_label(course)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Рљ РїСЂРѕС„РёР»СЋ", callback_data="profile")],
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "edit_faculty")
async def callback_edit_faculty(callback: CallbackQuery):
    """Р РµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ С„Р°РєСѓР»СЊС‚РµС‚Р°"""
    keyboard = []
    row = []
    for faculty in FACULTIES.values():
        row.append(InlineKeyboardButton(text=faculty, callback_data=f"set_faculty_{faculty}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="вќЊ РћС‚РјРµРЅР°", callback_data="profile")])
    
    await callback.message.edit_text(
        "<b>Р’С‹Р±РµСЂРё СЃРІРѕР№ С„Р°РєСѓР»СЊС‚РµС‚:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_faculty_"))
async def callback_set_faculty(callback: CallbackQuery):
    """РЈСЃС‚Р°РЅРѕРІРєР° С„Р°РєСѓР»СЊС‚РµС‚Р°"""
    faculty = callback.data.replace("set_faculty_", "")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            user.faculty = faculty
            await session.commit()
        
        # РџРѕР»СѓС‡Р°РµРј РЅРѕРІРѕРµ РєРѕР»РёС‡РµСЃС‚РІРѕ РІР°РєР°РЅСЃРёР№
        vacancies_count = await get_user_vacancies_count(session, faculty)
        
        await callback.message.edit_text(
        f"вњ… Р¤Р°РєСѓР»СЊС‚РµС‚ РёР·РјРµРЅС‘РЅ РЅР°: <b>{faculty}</b>\n\n"
        f"РўРµРїРµСЂСЊ С‚РµР±Рµ РґРѕСЃС‚СѓРїРЅРѕ <b>{vacancies_count}</b> РІР°РєР°РЅСЃРёР№!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="РџРѕСЃРјРѕС‚СЂРµС‚СЊ РІР°РєР°РЅСЃРёРё", callback_data="my_vacancies")],
            [InlineKeyboardButton(text="Рљ РїСЂРѕС„РёР»СЋ", callback_data="profile")],
            [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
        ])
    )
    await callback.answer()


# ==================== Рћ РљРћРњРџРђРќРР ====================

@router.callback_query(F.data.startswith("about_company_"))
async def callback_about_company(callback: CallbackQuery):
    """РџРѕРєР°Р·Р°С‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ РєРѕРјРїР°РЅРёРё"""
    # Р¤РѕСЂРјР°С‚: about_company_{vacancy_id}_{filter_type}_{index}_{sphere}
    parts = callback.data.split("_", 5)
    if len(parts) < 5:
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    
    vacancy_id = int(parts[2])
    filter_type = parts[3]
    current_index = int(parts[4])
    sphere = normalize_sphere_name(parts[5]) if len(parts) > 5 else None
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РІР°РєР°РЅСЃРёСЋ
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()
        
        if not vacancy:
            await callback.answer("Р’Р°РєР°РЅСЃРёСЏ РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        company = await find_company_by_name(session, vacancy.organization)
        
        vacancy_url = (getattr(vacancy, "vacancy_url", "") or "").strip()
        company_description = (getattr(company, "description", "") or "").strip()

        if not company_description and not vacancy_url:
            await callback.answer("РћРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё Рё СЃСЃС‹Р»РєР° РЅР° РІР°РєР°РЅСЃРёСЋ РЅРµ РЅР°Р№РґРµРЅС‹", show_alert=True)
            return

        # Р¤РѕСЂРјРёСЂСѓРµРј С‚РµРєСЃС‚
        vacancy_title = html.escape(vacancy.position or "Р’Р°РєР°РЅСЃРёСЏ")
        vacancy_title_html = (
            f'<a href="{html.escape(vacancy_url, quote=True)}">{vacancy_title}</a>'
            if vacancy_url
            else f"<b>{vacancy_title}</b>"
        )

        text = f"<b>{html.escape(vacancy.organization or 'РљРѕРјРїР°РЅРёСЏ')}</b>\n\n"
        text += f"рџ’ј {vacancy_title_html}\n\n"
        text += company_description or "РћРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё РїРѕРєР° РЅРµ Р·Р°РїРѕР»РЅРµРЅРѕ."
        if vacancy_url:
            visible_url = html.escape(vacancy_url)
            escaped_url = html.escape(vacancy_url, quote=True)
            text += f"\n\n<b>РЎСЃС‹Р»РєР° РЅР° РІР°РєР°РЅСЃРёСЋ:</b>\n<a href=\"{escaped_url}\">{visible_url}</a>"
        
        # РЈРґР°Р»СЏРµРј С„РѕС‚Рѕ Рё РїРѕРєР°Р·С‹РІР°РµРј С‚РµРєСЃС‚
        await callback.message.delete()
        
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="РќР°Р·Р°Рґ Рє РІР°РєР°РЅСЃРёРё",
                    callback_data=f"back_to_vac_{vacancy_id}_{filter_type}_{current_index}_{sphere or ''}"
                )],
                [InlineKeyboardButton(text="РњРµРЅСЋ", callback_data="main_menu")]
            ])
        )
        await callback.answer()


@router.callback_query(F.data.startswith("back_to_vac_"))
async def callback_back_to_vacancy(callback: CallbackQuery):
    """Р’РµСЂРЅСѓС‚СЊСЃСЏ Рє РІР°РєР°РЅСЃРёРё РёР· РѕРїРёСЃР°РЅРёСЏ РєРѕРјРїР°РЅРёРё"""
    # Р¤РѕСЂРјР°С‚: back_to_vac_{vacancy_id}_{filter_type}_{index}_{sphere}
    parts = callback.data.split("_", 6)
    if len(parts) < 6:
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    
    vacancy_id = int(parts[3])
    filter_type = parts[4]
    current_index = int(parts[5])
    sphere = normalize_sphere_name(parts[6]) if len(parts) > 6 else None
    
    async with async_session_maker() as session:
        # РџРѕР»СѓС‡Р°РµРј РІР°РєР°РЅСЃРёСЋ
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()
        
        if not vacancy:
            await callback.answer("Р’Р°РєР°РЅСЃРёСЏ РЅРµ РЅР°Р№РґРµРЅР°", show_alert=True)
            return
        
        # РџРѕР»СѓС‡Р°РµРј РѕР±С‰РµРµ РєРѕР»РёС‡РµСЃС‚РІРѕ РІР°РєР°РЅСЃРёР№ РґР»СЏ РїСЂР°РІРёР»СЊРЅРѕР№ РЅР°РІРёРіР°С†РёРё
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
        
        # Р¤РѕСЂРјРёСЂСѓРµРј caption
        if filter_type == "sphere" and sphere:
            emoji = SPHERE_EMOJI.get(sphere, "рџ’ј")
            caption = f"{emoji} <b>РЎС„РµСЂР°: {sphere}</b>\n\n" + format_vacancy_caption(vacancy)
        else:
            caption = format_vacancy_caption(vacancy)
        
        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РѕРїРёСЃР°РЅРёРµ РєРѕРјРїР°РЅРёРё
        has_company_desc = await check_company_has_description(session, vacancy.organization, vacancy.vacancy_url)
        
        # РЈРґР°Р»СЏРµРј С‚РµРєСЃС‚ Рё РѕС‚РїСЂР°РІР»СЏРµРј С„РѕС‚Рѕ
        await callback.message.delete()
        
        photo = get_vacancy_photo_input(vacancy)
        
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_vacancy_keyboard(vacancy.id, current_index, total, filter_type, sphere, has_company_desc=has_company_desc, organization=vacancy.organization)
        )
        await callback.answer()

