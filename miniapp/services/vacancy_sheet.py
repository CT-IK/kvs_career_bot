from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

PROJECT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_DIR / ".env")
load_dotenv()

SHEET_CACHE_TTL_SECONDS = max(15, int(os.getenv("MINIAPP_SHEET_CACHE_TTL_SECONDS", "300")))

HEADER_ALIASES = {
    "organization": ("Организация",),
    "division": ("Подразделение",),
    "position": ("Вакансия",),
    "sphere": ("Сфера",),
    "salary": ("ЗП",),
    "schedule": ("График",),
    "work_format": ("Формат",),
    "description": ("Описание",),
    "employment_format": ("Формат трудоустройства",),
    "feature1": ("Особенность 1",),
    "feature2": ("Особенность 2",),
    "feature3": ("Особенность 3",),
    "vacancy_url": ("Ссылка на вакансию",),
}

# Same 9 faculty checkbox columns the Telegram bot reads in services/google_sheets.py
# (FACULTY_SHEET_TO_DB) — sheet header paired with the short label used in the bot's
# faculty menu (config.py FACULTIES), in that menu's display order.
FACULTY_COLUMNS = [
    ("ИТиАБД", "ИТиАБД"),
    ("ИОО", "ИОО"),
    ("МЭО", "МЭО"),
    ("ФЭБ", "ФЭБ"),
    ("СНиМК", "СНиМК"),
    ("НАБ", "НАБ"),
    ("ВШУ", "ВШУ"),
    ("ФинФак", "ФФ"),
    ("ЮрФак", "ЮФ"),
]

FACULTY_CHECKED_VALUES = {"да", "yes", "1", "x", "✓", "true", "т", "+"}

BRAND_COLORS = ["#21A33B", "#159DD8", "#F40909", "#EC1C24", "#6266FF", "#C40016", "#009F62"]
METRO_COLORS = ["#D0183D", "#1268B3", "#159B55", "#EC7D00", "#7B61FF", "#C40016"]

# Known employer logos (freely-licensed files from Wikimedia Commons, served from
# assets/images/logos/), each with its real brand color for the vacancy-detail
# banner. Matched against the "Организация" cell by substring so minor spelling
# variants in the sheet still resolve. Companies without a verified free-licensed
# logo (e.g. Газпромбанк, Билайн, Росатом) intentionally have none — they fall
# back to the colored-initial avatar and hashed banner color, same as any
# unrecognized organization.
COMPANY_LOGOS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("sberbank", "svg", "#21A038", ("сбербанк", "сбер")),
    ("tbank", "svg", "#FFDD2D", ("т-банк", "тбанк", "тинькофф", "tinkoff", "t-bank")),
    ("vtb", "svg", "#002882", ("втб",)),
    ("alfabank", "svg", "#EF3124", ("альфа-банк", "альфабанк", "alfa-bank", "alfa bank")),
    ("raiffeisen", "svg", "#FFE600", ("райффайзен", "raiffeisen")),
    ("rosbank", "svg", "#002F87", ("росбанк", "rosbank")),
    ("yandex", "svg", "#FC3F1D", ("яндекс", "yandex")),
    ("vk", "svg", "#0077FF", ("вконтакте", "vkontakte", "vk company", "mail.ru", "мейл.ру")),
    ("mts", "svg", "#FF0000", ("мтс", "mts")),
    ("megafon", "svg", "#00B956", ("мегафон", "megafon")),
    ("rostelecom", "svg", "#7B2BF9", ("ростелеком", "rostelecom")),
    ("ozon", "svg", "#005BFF", ("озон", "ozon")),
    ("wildberries", "png", "#CB11AB", ("wildberries", "вайлдберриз")),
    ("x5group", "svg", "#F37021", ("x5 group", "икс 5", "икс5", "пятёрочка", "пятерочка", "перекрёсток", "перекресток")),
    ("magnit", "svg", "#E30713", ("магнит", "magnit")),
    ("rosneft", "svg", "#1A1A1A", ("роснефть", "rosneft")),
    ("lukoil", "svg", "#EE1C25", ("лукойл", "lukoil")),
    ("aeroflot", "svg", "#00256C", ("аэрофлот", "aeroflot")),
    ("rzd", "svg", "#DA4216", ("ржд", "российские железные дороги", "russian railways")),
    ("kept_kpmg", "svg", "#00338D", ("kept", "кэпт", "kpmg", "кпмг")),
    ("deloitte", "svg", "#86BC25", ("deloitte", "делойт")),
    ("pwc", "svg", "#D04A02", ("pwc", "технологии доверия", "pricewaterhousecoopers")),
    ("ey", "svg", "#FFE600", ("эрнст энд янг", "ernst & young", "б1", "b1")),
    ("sibur", "svg", "#00A19C", ("сибур", "sibur")),
    ("cbrf", "svg", "#6D6E71", ("банк россии", "центральный банк", "центробанк", "цб рф")),
    # Kept last: "газпром" alone would also match the unrelated Газпромбанк/Газпром нефть
    # subsidiaries, which don't have their own verified logo asset — excluded explicitly below.
    ("gazprom", "svg", "#0079C1", ("газпром",)),
]

GAZPROM_SUBSIDIARY_EXCLUSIONS = ("газпромбанк", "газпромнефть", "газпром нефть")

# Real brand color known, but no verified free-licensed logo exists for it (see
# the COMPANY_LOGOS comment) — e.g. Газпромбанк's own site/brandbook uses this
# blue, distinct from parent Газпром's. Still worth using instead of the
# generic per-name hash, even with no image to show.
BRAND_COLOR_ONLY: list[tuple[str, tuple[str, ...]]] = [
    ("#0072BC", ("газпромбанк", "gazprombank")),
]


def _match_company(organization: str) -> tuple[str | None, str | None, str]:
    """Return (logo_slug, logo_ext, brandColor) for an organization.

    logo_slug/logo_ext are None when there's no verified free-licensed logo,
    even if the real brand color is known (see BRAND_COLOR_ONLY) — falls back
    to the generic per-name hash color only when neither is known.
    """
    normalized = organization.casefold()
    is_gazprom_subsidiary = any(term in normalized for term in GAZPROM_SUBSIDIARY_EXCLUSIONS)

    if not is_gazprom_subsidiary:
        for slug, ext, color, aliases in COMPANY_LOGOS:
            if any(alias in normalized for alias in aliases):
                return slug, ext, color

    for color, aliases in BRAND_COLOR_ONLY:
        if any(alias in normalized for alias in aliases):
            return None, None, color

    return None, None, _brand_color(organization)

_cache: dict[str, Any] = {"expires_at": 0.0, "items": None, "loaded_at": None}


class VacancySheetError(RuntimeError):
    """Raised when Google Sheets cannot be read for the miniapp."""


def _resolve_credentials_path() -> Path:
    raw_path = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip() or "credentials.json"
    path = Path(raw_path)
    if path.is_absolute():
        return path

    project_path = PROJECT_DIR / path
    if project_path.exists():
        return project_path

    return Path.cwd() / path


def _get_spreadsheet():
    credentials_path = _resolve_credentials_path()
    if not credentials_path.exists():
        raise VacancySheetError(f"Google credentials file not found: {credentials_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    client = gspread.authorize(credentials)

    spreadsheet_url = os.getenv("GOOGLE_SHEETS_URL", "").strip()
    spreadsheet_name = os.getenv("GOOGLE_SHEET_NAME", "").strip()
    if spreadsheet_url:
        return client.open_by_url(spreadsheet_url)
    if spreadsheet_name:
        return client.open(spreadsheet_name)
    raise VacancySheetError("GOOGLE_SHEETS_URL or GOOGLE_SHEET_NAME must be configured")


def _get_value(row: dict[str, str], key: str) -> str:
    for header in HEADER_ALIASES[key]:
        value = row.get(header)
        if value is not None:
            return str(value).strip()
    return ""


def _stable_index(value: str, modulo: int) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def _brand_color(company: str) -> str:
    return BRAND_COLORS[_stable_index(company or "KVS", len(BRAND_COLORS))]


def _metro_color(value: str) -> str:
    return METRO_COLORS[_stable_index(value or "default", len(METRO_COLORS))]


def _kind(value: str) -> str:
    normalized = value.casefold()
    if "стаж" in normalized:
        return "Стажировка"
    if "вак" in normalized:
        return "Вакансия"
    return value or "Вакансия"


def _features(*values: str) -> list[str]:
    return [value for value in values if value]


def _is_faculty_checked(value: str) -> bool:
    return value.strip().casefold() in FACULTY_CHECKED_VALUES


def _faculties_for_row(row: dict[str, str]) -> list[str]:
    return [label for header, label in FACULTY_COLUMNS if _is_faculty_checked(row.get(header, ""))]


def _to_frontend_vacancy(row: dict[str, str], row_number: int) -> dict[str, Any] | None:
    organization = _get_value(row, "organization")
    title = _get_value(row, "position")
    if not organization or not title:
        return None

    division = _get_value(row, "division")
    sphere = _get_value(row, "sphere") or "Другое"
    faculties = _faculties_for_row(row)
    salary = _get_value(row, "salary") or "По договорённости"
    schedule = _get_value(row, "schedule")
    work_format = _get_value(row, "work_format") or "Гибрид"
    employment_format = _kind(_get_value(row, "employment_format"))
    description = _get_value(row, "description") or "Описание появится позже."
    features = _features(_get_value(row, "feature1"), _get_value(row, "feature2"), _get_value(row, "feature3"))
    vacancy_url = _get_value(row, "vacancy_url")
    logo_slug, logo_ext, brand_color = _match_company(organization)

    return {
        "id": f"sheet-{row_number}",
        "sourceRow": row_number,
        "company": {
            "id": f"company-{_stable_index(organization, 100000)}",
            "name": organization,
            "initial": organization[:1].upper() or "K",
            "brandColor": brand_color,
            "logoUrl": f"/assets/images/logos/{logo_slug}.{logo_ext}" if logo_slug else None,
            "verified": True,
        },
        "division": division,
        "title": title,
        "salary": salary,
        "metro": division or schedule or "Уточняется",
        "metroColor": _metro_color(division or schedule or organization),
        "format": work_format,
        "kind": employment_format,
        "sphere": sphere,
        "faculties": faculties,
        "category": faculties[0] if faculties else "Без факультета",
        "experience": features[0] if features else "Без опыта",
        "description": description,
        "fullDescription": description,
        "requirements": features or ["Требования уточняются у работодателя"],
        "offer": [value for value in [salary, schedule, work_format, employment_format] if value],
        "applyUrl": vacancy_url,
    }


def _rows_from_sheet() -> list[dict[str, str]]:
    spreadsheet = _get_spreadsheet()
    sheet = spreadsheet.sheet1
    values = sheet.get_all_values()
    if len(values) < 3:
        return []

    headers = [header.strip() for header in values[1]]
    rows: list[dict[str, str]] = []
    for row_index, raw_row in enumerate(values[2:], start=3):
        mapped = {
            header: raw_row[index].strip() if index < len(raw_row) else ""
            for index, header in enumerate(headers)
            if header
        }
        mapped["_row_number"] = str(row_index)
        rows.append(mapped)
    return rows


def load_vacancies_from_google_sheet(force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    now = time.monotonic()
    if not force_refresh and _cache["items"] is not None and now < _cache["expires_at"]:
        return list(_cache["items"]), _cache["loaded_at"]

    items = []
    for row in _rows_from_sheet():
        item = _to_frontend_vacancy(row, int(row["_row_number"]))
        if item:
            items.append(item)

    loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _cache.update({
        "items": items,
        "loaded_at": loaded_at,
        "expires_at": now + SHEET_CACHE_TTL_SECONDS,
    })
    return list(items), loaded_at


def filter_vacancies(items: list[dict[str, Any]], query: str = "", category: str = "Все") -> list[dict[str, Any]]:
    normalized_query = query.strip().casefold()
    normalized_category = category.strip()

    def matches(item: dict[str, Any]) -> bool:
        if normalized_category and normalized_category != "Все" and normalized_category not in item.get("faculties", []):
            return False
        if not normalized_query:
            return True
        haystack = " ".join(
            str(value)
            for value in [
                item["title"],
                item["company"]["name"],
                item.get("division", ""),
                item["salary"],
                item["format"],
                item["kind"],
                item.get("sphere", ""),
                *item.get("faculties", []),
                item["description"],
            ]
        ).casefold()
        return normalized_query in haystack

    return [item for item in items if matches(item)]


def build_categories(items: list[dict[str, Any]]) -> list[str]:
    # Faculty order mirrors the bot's own faculty menu (config.py FACULTIES),
    # not an alphabetical sort, so the chips line up with what students expect.
    present = {label for item in items for label in item.get("faculties", [])}
    ordered = [label for _, label in FACULTY_COLUMNS if label in present]
    return ["Все", *ordered]
