import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve the project .env independently of the process working directory.
# The miniapp can be launched both from this directory and through the shim in
# the repository root; plain load_dotenv() silently used defaults in the latter.
load_dotenv(Path(__file__).resolve().with_name(".env"))


def _env_bool(name: str, default: bool = False) -> bool:
    """Convert environment variable to bool safely."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Convert environment variable to int safely."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_channel_username(name: str, default: str = "") -> str:
    """Normalize channel username for Telegram API calls."""
    value = os.getenv(name, default).strip()
    if not value:
        return ""
    if value.startswith("https://t.me/"):
        value = value.removeprefix("https://t.me/").strip("/")
    if value.startswith("http://t.me/"):
        value = value.removeprefix("http://t.me/").strip("/")
    if value.startswith("@") or value.lstrip("-").isdigit():
        return value
    return f"@{value}"

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
AUTO_RESTART_ENABLED = _env_bool("AUTO_RESTART_ENABLED", default=True)
AUTO_RESTART_DELAY_SECONDS = max(1, _env_int("AUTO_RESTART_DELAY_SECONDS", default=5))
REQUIRED_CHANNEL_USERNAME = _env_channel_username("REQUIRED_CHANNEL_USERNAME", "@kvskeepintouch")
REQUIRED_CHANNEL_URL = os.getenv(
    "REQUIRED_CHANNEL_URL",
    f"https://t.me/{REQUIRED_CHANNEL_USERNAME.lstrip('@')}" if REQUIRED_CHANNEL_USERNAME else ""
)

# MAX bot and mini app. Keep this token separate from BOT_TOKEN: using a
# Telegram token against MAX would make both initData validation and delivery
# fail in a way that is needlessly hard to diagnose.
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
MAX_ADMIN_IDS = (
    list(map(int, os.getenv("MAX_ADMIN_IDS", "").split(",")))
    if os.getenv("MAX_ADMIN_IDS")
    else []
)
MAX_API_BASE_URL = os.getenv(
    "MAX_API_BASE_URL",
    "https://platform-api2.max.ru",
).strip().rstrip("/")
MAX_REQUIRED_CHANNEL_ID = _env_int("MAX_REQUIRED_CHANNEL_ID", default=0)
MAX_REQUIRED_CHANNEL_URL = os.getenv("MAX_REQUIRED_CHANNEL_URL", "").strip()

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "kvs_bot")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# Google Sheets
GOOGLE_SHEETS_URL = os.getenv("GOOGLE_SHEETS_URL", "")
EVENTS_GOOGLE_SHEETS_URL = os.getenv(
    "EVENTS_GOOGLE_SHEETS_URL",
    "https://docs.google.com/spreadsheets/d/14WUklH3Ksg8OGS2d1_CLp2MTtEQfr8KfUotMUMY3Z_4/edit?gid=0#gid=0",
)
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "")
SEED_DEMO_DATA = _env_bool("SEED_DEMO_DATA", default=False)
VACANCY_SYNC_SCHEDULE_ENABLED = _env_bool("VACANCY_SYNC_SCHEDULE_ENABLED", default=True)
VACANCY_SYNC_HOUR = min(23, max(0, _env_int("VACANCY_SYNC_HOUR", default=0)))
VACANCY_SYNC_MINUTE = min(59, max(0, _env_int("VACANCY_SYNC_MINUTE", default=0)))
VACANCY_SYNC_TIMEZONE = os.getenv("VACANCY_SYNC_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
VACANCY_SYNC_ALLOW_EMPTY = _env_bool("VACANCY_SYNC_ALLOW_EMPTY", default=False)
# KVS Job miniapp
MINIAPP_ENABLED = _env_bool("MINIAPP_ENABLED", default=True)
MINIAPP_HOST = os.getenv("MINIAPP_HOST", "0.0.0.0").strip() or "0.0.0.0"
MINIAPP_PORT = max(1, min(65535, _env_int("MINIAPP_PORT", default=8000)))
MINIAPP_PUBLIC_URL = os.getenv("MINIAPP_PUBLIC_URL", "http://localhost:8000/miniapp").strip()
MINIAPP_DEV_ADMIN_ENABLED = _env_bool("MINIAPP_DEV_ADMIN_ENABLED", default=False)
EVENT_REMINDERS_ENABLED = _env_bool("EVENT_REMINDERS_ENABLED", default=True)
EVENT_REMINDER_POLL_SECONDS = max(30, _env_int("EVENT_REMINDER_POLL_SECONDS", default=60))

# Факультеты
FACULTIES = {
    "ИТиАБД": "ИТиАБД",
    "ИОО": "ИОО",
    "МЭО": "МЭО",
    "ФЭБ": "ФЭБ",
    "СНиМК": "СНиМК",
    "НАБ": "НАБ",
    "ВШУ": "ВШУ",
    "ФФ": "ФФ",
    "ЮФ": "ЮФ"
}

# Источники информации
INFO_SOURCES = {
    "ВК-группа проекта": "ВК-группа проекта",
    "ВК/Тг информера факультета": "ВК/Тг информера факультета",
    "от одногруппников": "от одногруппников",
    "от Координатора": "от Координатора"
}
