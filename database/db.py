import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, text
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, SEED_DEMO_DATA

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _safe_print(message: str) -> None:
    """Print logs without crashing on non-UTF8 Windows consoles."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)

async def get_session():
    async with async_session_maker() as session:
        yield session

async def init_db():
    """Create missing tables and optionally seed demo data."""
    from database.models import Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS patronymic VARCHAR(100)"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(64)"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS ioo BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_username_lower ON users (LOWER(username))"))
        _safe_print("✅ Таблицы базы данных успешно созданы/проверены")
        
        if SEED_DEMO_DATA:
            await seed_demo_data()
    except Exception as e:
        _safe_print(f"❌ Ошибка при создании таблиц: {e}")
        raise


async def seed_demo_data():
    """Seed demo companies/divisions for MVP environments."""
    from database.models import Company, Division
    
    # Демо компании и подразделения
    DEMO_DATA = [
        {
            "name": "Сбербанк",
            "description": "Крупнейший банк России и Восточной Европы. Предоставляет полный спектр банковских услуг для частных и корпоративных клиентов.",
            "divisions": [
                {"name": "IT-департамент", "description": "Разработка и поддержка банковских систем, мобильных приложений и цифровых сервисов."},
                {"name": "Аналитика", "description": "Data Science, машинное обучение, бизнес-аналитика и исследования."},
                {"name": "Розничный бизнес", "description": "Работа с частными клиентами, продажи банковских продуктов."},
            ]
        },
        {
            "name": "Яндекс",
            "description": "Технологическая компания, разрабатывающая поисковую систему, сервисы такси, доставки, облачные технологии и многое другое.",
            "divisions": [
                {"name": "Поиск", "description": "Разработка поисковых алгоритмов и машинного обучения."},
                {"name": "Яндекс.Такси", "description": "Сервис заказа такси и курьерской доставки."},
                {"name": "Яндекс.Маркет", "description": "Маркетплейс и e-commerce направление."},
            ]
        },
        {
            "name": "Тинькофф",
            "description": "Онлайн-банк и финансовая экосистема. Известен инновационным подходом и отсутствием отделений.",
            "divisions": [
                {"name": "Разработка", "description": "Backend, Frontend, Mobile разработка банковских продуктов."},
                {"name": "Тинькофф Инвестиции", "description": "Брокерские услуги и инвестиционные продукты."},
                {"name": "Бизнес", "description": "Продукты для малого и среднего бизнеса."},
            ]
        },
    ]
    
    async with async_session_maker() as session:
        for company_data in DEMO_DATA:
            # Проверяем, есть ли уже такая компания
            result = await session.execute(
                select(Company).where(Company.name == company_data["name"])
            )
            company = result.scalar_one_or_none()
            
            if not company:
                # Создаём компанию
                company = Company(
                    name=company_data["name"],
                    description=company_data["description"]
                )
                session.add(company)
                await session.flush()  # Получаем ID
                
                # Создаём подразделения
                for div_data in company_data["divisions"]:
                    division = Division(
                        company_id=company.id,
                        name=div_data["name"],
                        description=div_data["description"]
                    )
                    session.add(division)
                
                _safe_print(f"✅ Добавлена компания: {company_data['name']} с {len(company_data['divisions'])} подразделениями")
        
        await session.commit()
    
    _safe_print("✅ Демо-данные загружены")

