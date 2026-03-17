from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import FSInputFile

EVENT_PHOTOS_DIR = Path(__file__).parent.parent / "assets" / "event_photos"


def _ensure_event_photos_dir() -> Path:
    EVENT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    return EVENT_PHOTOS_DIR


def _guess_extension(file_path: str | None) -> str:
    suffix = Path(file_path or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    return ".jpg"


def is_local_event_photo(photo_ref: str | None) -> bool:
    if not photo_ref:
        return False
    return Path(photo_ref).exists()


async def save_event_photo(bot: Bot, telegram_file_id: str, event_id: int) -> str:
    photos_dir = _ensure_event_photos_dir()
    file = await bot.get_file(telegram_file_id)
    extension = _guess_extension(file.file_path)
    destination = photos_dir / f"event_{event_id}_{uuid4().hex}{extension}"
    await bot.download(file, destination=destination)
    return str(destination)


def delete_event_photo(photo_ref: str | None) -> None:
    if not is_local_event_photo(photo_ref):
        return

    try:
        Path(photo_ref).unlink(missing_ok=True)
    except Exception:
        pass


def get_event_photo_input(photo_ref: str | None):
    if not photo_ref:
        return None
    if is_local_event_photo(photo_ref):
        return FSInputFile(photo_ref)
    return photo_ref
