import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import AUTO_RESTART_DELAY_SECONDS, AUTO_RESTART_ENABLED, BOT_TOKEN
from config import MINIAPP_ENABLED, MINIAPP_HOST, MINIAPP_PORT
from database.db import async_session_maker, init_db
from handlers import admin, registration, subscription, vacancies
from middleware.activity import ActivityMiddleware
from middleware.subscription import SubscriptionMiddleware
from services.google_sheets import ensure_vacancies_seeded
from services.image_generator import pregenerate_vacancy_images
from services.vacancy_scheduler import run_daily_vacancy_sync_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%"
           ""
           "(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class FatalStartupError(RuntimeError):
    """Raised when the bot cannot recover without config changes."""



async def run_miniapp_server():
    """Run the KVS Job miniapp web server inside the bot process."""
    import uvicorn

    config = uvicorn.Config(
        "miniapp.app:app",
        host=MINIAPP_HOST,
        port=MINIAPP_PORT,
        log_level="info",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    await server.serve()
async def run_bot_once():
    """Run a single bot lifecycle until shutdown or crash."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Check your .env file.")
        raise FatalStartupError("BOT_TOKEN is not configured")

    logger.info("Checking database...")
    await init_db()
    logger.info("Database is ready")

    logger.info("Checking vacancies seed...")
    try:
        async with async_session_maker() as session:
            seeded_count = await ensure_vacancies_seeded(session)
        logger.info("Vacancies in database: %s", seeded_count)
    except Exception as exc:
        logger.warning("Initial vacancies sync failed: %s", exc)

    logger.info("Checking image cache...")
    try:
        await pregenerate_vacancy_images()
    except Exception as exc:
        logger.warning("Image pregeneration failed: %s", exc)

    background_tasks = []
    vacancy_sync_task = asyncio.create_task(
        run_daily_vacancy_sync_scheduler(),
        name="daily-vacancy-sync",
    )
    background_tasks.append(vacancy_sync_task)

    if MINIAPP_ENABLED:
        logger.info("Starting KVS Job miniapp server on %s:%s", MINIAPP_HOST, MINIAPP_PORT)
        background_tasks.append(
            asyncio.create_task(run_miniapp_server(), name="kvs-job-miniapp-server")
        )

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(ActivityMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(
        SubscriptionMiddleware(allowed_callback_data={"check_subscription"})
    )

    dp.include_router(subscription.router)
    dp.include_router(vacancies.router)
    dp.include_router(registration.router)
    dp.include_router(admin.router)

    @dp.errors()
    async def error_handler(event: ErrorEvent):
        exception = event.exception
        if isinstance(exception, TelegramBadRequest) and "query is too old" in str(exception):
            return True

        logger.error("Unhandled bot error: %s", exception)
        return True

    logger.info("Bot started")

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task
        await bot.session.close()


async def main():
    """Restart the bot after unexpected crashes when enabled."""
    attempt = 1
    while True:
        try:
            await run_bot_once()
            logger.info("Bot stopped gracefully")
            return
        except FatalStartupError:
            raise
        except Exception:
            logger.exception("Bot crashed on attempt #%s", attempt)
            if not AUTO_RESTART_ENABLED:
                raise

            logger.info(
                "Restarting bot in %s seconds",
                AUTO_RESTART_DELAY_SECONDS,
            )
            attempt += 1
            await asyncio.sleep(AUTO_RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
