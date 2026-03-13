import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest
from config import BOT_TOKEN
from database.db import init_db, async_session_maker
from handlers import registration, admin, vacancies, subscription
from middleware.activity import ActivityMiddleware
from middleware.subscription import SubscriptionMiddleware
from services.google_sheets import ensure_vacancies_seeded
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

    logger.info("Проверка вакансий в БД...")
    try:
        async with async_session_maker() as session:
            seeded_count = await ensure_vacancies_seeded(session)
        logger.info("Вакансии в БД: %s", seeded_count)
    except Exception as e:
        logger.warning(f"Не удалось выполнить начальную синхронизацию вакансий: {e}")
    
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
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware(allowed_callback_data={"check_subscription"}))
    
    # Регистрация роутеров (порядок важен!)
    dp.include_router(subscription.router)
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

