"""
Генератор изображений для вакансий в стиле брендбука
Цвета: #FFFFFF, #F0F0F0, #B20B13, #282826
"""

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from typing import Optional
import textwrap
import os
import hashlib
from pathlib import Path

# Папка для кэша изображений
CACHE_DIR = Path("/app/cache/images")

# Цветовая палитра брендбука
COLORS = {
    "white": "#FFFFFF",
    "light_gray": "#F0F0F0",
    "accent": "#B20B13",  # Красный акцент
    "dark": "#282826",
}

# Размеры изображения
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Получить шрифт нужного размера"""
    # Пробуем разные шрифты
    font_paths = [
        # Linux/Docker
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        # Fallback
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    
    # Если ничего не найдено, используем дефолтный
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw) -> list:
    """Разбить текст на строки по ширине"""
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines


def generate_vacancy_image(
    organization: str,
    position: str,
    salary: str = "",
    schedule: str = "",
    work_format: str = "",
    sphere: str = "",
    description: str = "",
    features: list = None,
) -> BytesIO:
    """
    Генерация изображения вакансии в стиле брендбука
    """
    # Создаём изображение с тёмным фоном
    img = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), COLORS["dark"])
    draw = ImageDraw.Draw(img)
    
    # Шрифты
    font_title = get_font(72, bold=True)
    font_org = get_font(42, bold=True)
    font_label = get_font(28, bold=True)
    font_value = get_font(32, bold=False)
    font_desc = get_font(28, bold=False)
    
    y_offset = 60
    padding = 60
    content_width = IMAGE_WIDTH - (padding * 2)
    
    # === Верхняя красная полоса ===
    draw.rectangle([(0, 0), (IMAGE_WIDTH, 12)], fill=COLORS["accent"])
    
    # === Организация (красным) ===
    org_lines = wrap_text(organization.upper(), font_org, content_width, draw)
    for line in org_lines:
        draw.text((padding, y_offset), line, font=font_org, fill=COLORS["accent"])
        bbox = draw.textbbox((0, 0), line, font=font_org)
        y_offset += bbox[3] - bbox[1] + 10
    
    y_offset += 20
    
    # === Должность (белым, крупно) ===
    position_lines = wrap_text(position.upper(), font_title, content_width, draw)
    for line in position_lines:
        draw.text((padding, y_offset), line, font=font_title, fill=COLORS["white"])
        bbox = draw.textbbox((0, 0), line, font=font_title)
        y_offset += bbox[3] - bbox[1] + 5
    
    y_offset += 40
    
    # === Красная разделительная линия ===
    draw.rectangle([(padding, y_offset), (IMAGE_WIDTH - padding, y_offset + 4)], fill=COLORS["accent"])
    y_offset += 30
    
    # === Информационные блоки ===
    info_items = []
    if salary:
        info_items.append(("💰 ЗАРПЛАТА", salary))
    if schedule:
        info_items.append(("⏰ ГРАФИК", schedule))
    if work_format:
        info_items.append(("📍 ФОРМАТ", work_format))
    if sphere:
        info_items.append(("📊 СФЕРА", sphere))
    
    for label, value in info_items:
        # Лейбл (красным)
        draw.text((padding, y_offset), label, font=font_label, fill=COLORS["accent"])
        bbox = draw.textbbox((0, 0), label, font=font_label)
        y_offset += bbox[3] - bbox[1] + 5
        
        # Значение (белым)
        draw.text((padding, y_offset), value, font=font_value, fill=COLORS["white"])
        bbox = draw.textbbox((0, 0), value, font=font_value)
        y_offset += bbox[3] - bbox[1] + 25
    
    y_offset += 20
    
    # === Описание ===
    if description:
        draw.text((padding, y_offset), "📄 ОПИСАНИЕ", font=font_label, fill=COLORS["accent"])
        bbox = draw.textbbox((0, 0), "📄 ОПИСАНИЕ", font=font_label)
        y_offset += bbox[3] - bbox[1] + 10
        
        # Обрезаем описание если слишком длинное
        desc_short = description[:250] + "..." if len(description) > 250 else description
        desc_lines = wrap_text(desc_short, font_desc, content_width, draw)
        
        for line in desc_lines[:5]:  # Максимум 5 строк
            draw.text((padding, y_offset), line, font=font_desc, fill=COLORS["light_gray"])
            bbox = draw.textbbox((0, 0), line, font=font_desc)
            y_offset += bbox[3] - bbox[1] + 5
        
        y_offset += 30
    
    # === Преимущества ===
    if features:
        draw.text((padding, y_offset), "✨ ПРЕИМУЩЕСТВА", font=font_label, fill=COLORS["accent"])
        bbox = draw.textbbox((0, 0), "✨ ПРЕИМУЩЕСТВА", font=font_label)
        y_offset += bbox[3] - bbox[1] + 15
        
        for feature in features[:3]:  # Максимум 3 преимущества
            if feature:
                text = f"→ {feature}"
                draw.text((padding, y_offset), text, font=font_desc, fill=COLORS["white"])
                bbox = draw.textbbox((0, 0), text, font=font_desc)
                y_offset += bbox[3] - bbox[1] + 10
    
    # === Нижняя красная полоса ===
    draw.rectangle([(0, IMAGE_HEIGHT - 12), (IMAGE_WIDTH, IMAGE_HEIGHT)], fill=COLORS["accent"])
    
    # === Логотип/бренд в углу ===
    brand_text = "КОМИТЕТ ВНЕШНИХ СВЯЗЕЙ"
    brand_font = get_font(24, bold=True)
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    brand_width = bbox[2] - bbox[0]
    draw.text(
        (IMAGE_WIDTH - padding - brand_width, IMAGE_HEIGHT - 60),
        brand_text,
        font=brand_font,
        fill=COLORS["accent"]
    )
    
    # Сохраняем в BytesIO
    buffer = BytesIO()
    img.save(buffer, format="PNG", quality=95)
    buffer.seek(0)
    
    return buffer


def generate_vacancy_card(vacancy) -> BytesIO:
    """
    Генерация карточки из объекта вакансии
    """
    features = []
    if hasattr(vacancy, 'feature1') and vacancy.feature1:
        features.append(vacancy.feature1)
    if hasattr(vacancy, 'feature2') and vacancy.feature2:
        features.append(vacancy.feature2)
    if hasattr(vacancy, 'feature3') and vacancy.feature3:
        features.append(vacancy.feature3)
    
    return generate_vacancy_image(
        organization=vacancy.organization or "Компания",
        position=vacancy.position or "Вакансия",
        salary=vacancy.salary or "",
        schedule=vacancy.schedule or "",
        work_format=vacancy.work_format or "",
        sphere=vacancy.sphere or "",
        description=vacancy.description or "",
        features=features,
    )


def get_vacancy_cache_path(vacancy_id: int) -> Path:
    """Получить путь к кэшированному изображению вакансии"""
    return CACHE_DIR / f"vacancy_{vacancy_id}.png"


def ensure_cache_dir():
    """Создать папку кэша если не существует"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cached_or_generate(vacancy) -> bytes:
    """
    Получить изображение из кэша или сгенерировать новое.
    Возвращает bytes для отправки в Telegram.
    """
    ensure_cache_dir()
    cache_path = get_vacancy_cache_path(vacancy.id)
    
    if cache_path.exists():
        # Читаем из кэша
        return cache_path.read_bytes()
    
    # Генерируем новое изображение
    buffer = generate_vacancy_card(vacancy)
    image_bytes = buffer.read()
    
    # Сохраняем в кэш
    cache_path.write_bytes(image_bytes)
    
    return image_bytes


def generate_and_cache(vacancy) -> bytes:
    """
    Сгенерировать изображение и сохранить в кэш (перезаписывает если есть).
    """
    ensure_cache_dir()
    cache_path = get_vacancy_cache_path(vacancy.id)
    
    buffer = generate_vacancy_card(vacancy)
    image_bytes = buffer.read()
    
    cache_path.write_bytes(image_bytes)
    
    return image_bytes


def is_cached(vacancy_id: int) -> bool:
    """Проверить есть ли изображение в кэше"""
    return get_vacancy_cache_path(vacancy_id).exists()


def clear_cache():
    """Очистить весь кэш изображений"""
    ensure_cache_dir()
    for file in CACHE_DIR.glob("*.png"):
        file.unlink()


def get_missing_cache_ids(vacancy_ids: list) -> list:
    """Получить список ID вакансий без кэша"""
    ensure_cache_dir()
    return [vid for vid in vacancy_ids if not is_cached(vid)]


async def pregenerate_vacancy_images():
    """
    Прегенерация изображений для всех вакансий без кэша.
    Вызывается при запуске бота.
    """
    from database.db import async_session_maker
    from database.models import Vacancy
    from sqlalchemy import select
    import logging
    
    logger = logging.getLogger(__name__)
    
    ensure_cache_dir()
    
    async with async_session_maker() as session:
        result = await session.execute(select(Vacancy))
        vacancies = result.scalars().all()
        
        if not vacancies:
            logger.info("📷 Нет вакансий для генерации изображений")
            return
        
        # Проверяем какие изображения отсутствуют
        missing = [v for v in vacancies if not is_cached(v.id)]
        
        if not missing:
            logger.info(f"📷 Все {len(vacancies)} изображений уже в кэше")
            return
        
        logger.info(f"📷 Генерация {len(missing)} изображений из {len(vacancies)}...")
        
        for i, vacancy in enumerate(missing, 1):
            try:
                generate_and_cache(vacancy)
                if i % 10 == 0:
                    logger.info(f"📷 Сгенерировано {i}/{len(missing)} изображений")
            except Exception as e:
                logger.error(f"❌ Ошибка генерации изображения для вакансии {vacancy.id}: {e}")
        
        logger.info(f"✅ Генерация изображений завершена: {len(missing)} новых")

