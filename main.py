import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest
from config import BOT_TOKEN
from database.db import init_db
from handlers import registration, admin, vacancies
from middleware.activity import ActivityMiddleware
from services.image_generator import pregenerate_vacancy_images

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Основная функция запуска бота"""
    # Проверка токена
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Проверьте файл .env")
        return
    
    # Инициализация базы данных (миграции применяются автоматически в Docker)
    # В Docker это уже сделано в entrypoint.sh, но для локального запуска тоже нужно
    logger.info("Проверка базы данных...")
    try:
        await init_db()
        logger.info("База данных готова")
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
        return
    
    # Прегенерация изображений вакансий (создаём недостающие)
    logger.info("Проверка кэша изображений...")
    try:
        await pregenerate_vacancy_images()
    except Exception as e:
        logger.warning(f"Ошибка при прегенерации изображений: {e}")
    
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация middleware
    dp.update.middleware(ActivityMiddleware())
    
    # Регистрация роутеров (порядок важен!)
    # vacancies первым - там /start для всех
    dp.include_router(vacancies.router)
    dp.include_router(registration.router)
    dp.include_router(admin.router)
    
    # Обработчик ошибок для старых callback queries
    @dp.errors()
    async def error_handler(event: ErrorEvent):
        exception = event.exception
        if isinstance(exception, TelegramBadRequest):
            if "query is too old" in str(exception):
                # Игнорируем старые callback queries - это нормально после перезапуска
                return True
        logger.error(f"Ошибка: {exception}")
        return True
    
    logger.info("Бот запущен")
    
    # Запуск бота
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

