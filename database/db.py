from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, SEED_DEMO_DATA

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session():
    async with async_session_maker() as session:
        yield session

async def init_db():
    """Create missing tables and optionally seed demo data."""
    from database.models import Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Таблицы базы данных успешно созданы/проверены")
        
        if SEED_DEMO_DATA:
            await seed_demo_data()
    except Exception as e:
        print(f"❌ Ошибка при создании таблиц: {e}")
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
                
                print(f"✅ Добавлена компания: {company_data['name']} с {len(company_data['divisions'])} подразделениями")
        
        await session.commit()
    
    print("✅ Демо-данные загружены")

