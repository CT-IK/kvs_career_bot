import os
from dotenv import load_dotenv

load_dotenv()


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

