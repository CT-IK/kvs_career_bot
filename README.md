# KVS Career Bot

Telegram-бот на `aiogram` и `PostgreSQL` для карьерного проекта КВС. Бот ведет регистрацию пользователей, показывает вакансии и компании-партнеры, поддерживает мероприятия, админские сценарии и собирает полную метрику пользовательских действий.

## Что умеет бот

### Для пользователей

- регистрация с заполнением ФИО, курса, факультета и источника информации;
- главное меню с разделами профиля, вакансий, компаний, мероприятий, обратной связи и блока "О нас";
- показ вакансий по факультету, всех вакансий и вакансий по сферам;
- карточки компаний и подразделений с переходом к связанным вакансиям;
- просмотр и редактирование своего профиля;
- просмотр списка активных мероприятий и регистрация в основной список или резерв;
- обязательная проверка подписки на канал перед использованием бота.

### Для администраторов

- админ-панель с оперативной статистикой по пользователям, вакансиям, компаниям и мероприятиям;
- отдельный экран метрики действий пользователей;
- синхронизация вакансий из Google Sheets;
- создание, редактирование, публикация и удаление мероприятий;
- рассылка всем пользователям;
- личные сообщения пользователю по `username`;
- ответы на обратную связь через бот;
- выдача прав администратора из интерфейса бота.

## Метрика действий

Бот автоматически пишет историю пользовательских действий в таблицу `user_actions`. События создаются на уровне middleware и включают:

- пользователя и его `telegram_id`;
- тип апдейта (`message`, `callback_query` и т.д.);
- нормализованное действие, например `command:start`, `callback:view_event`, `message:text`;
- сырое значение события;
- `chat_type`;
- текущее `fsm_state`;
- время события.

В админке доступны:

- общее число событий;
- число уникальных пользователей с действиями;
- активность за 24 часа и 7 дней;
- топ действий;
- самые активные пользователи;
- последние зафиксированные события.

## Основные команды

- `/start` — вход в бот и запуск регистрации;
- `/vacancies` — быстрый переход в раздел вакансий;
- `/admin` — вход в админ-панель;
- `/sync_vacancies` — ручная синхронизация вакансий из Google Sheets.

## Стек

- Python 3.13+
- aiogram 3
- SQLAlchemy Async + asyncpg
- PostgreSQL 15
- Google Sheets API через `gspread`
- Pillow для генерации изображений карточек
- Docker / Docker Compose

## Конфигурация

Проект читает настройки из `.env`.

### Обязательные переменные

- `BOT_TOKEN` — токен Telegram-бота;
- `DB_HOST` — хост PostgreSQL;
- `DB_PORT` — порт PostgreSQL;
- `DB_NAME` — имя базы;
- `DB_USER` — пользователь базы;
- `DB_PASSWORD` — пароль базы.

### Админские и системные настройки

- `ADMIN_IDS` — список Telegram ID администраторов через запятую;
- `AUTO_RESTART_ENABLED` — включение автоперезапуска после падения;
- `AUTO_RESTART_DELAY_SECONDS` — задержка перед рестартом;
- `SEED_DEMO_DATA` — загружать ли демонстрационные компании и подразделения.

### Настройки подписки

- `REQUIRED_CHANNEL_USERNAME` — username или numeric id обязательного канала;
- `REQUIRED_CHANNEL_URL` — ссылка на канал.

### Настройки Google Sheets

- `GOOGLE_SHEETS_URL` — таблица с вакансиями;
- `EVENTS_GOOGLE_SHEETS_URL` — таблица для регистрации на мероприятия;
- `GOOGLE_CREDENTIALS_FILE` — путь до JSON-ключа сервисного аккаунта;
- `GOOGLE_SHEET_NAME` — имя листа с вакансиями.

## Локальный запуск

1. Установите зависимости:

```bash
pip install -r requirements.txt
```

2. Создайте `.env` в корне проекта. Пример:

```env
BOT_TOKEN=your_bot_token
ADMIN_IDS=Ваши админы

DB_HOST=localhost
DB_PORT=5432
DB_NAME=kvs_bot
DB_USER=postgres
DB_PASSWORD=postgres

REQUIRED_CHANNEL_USERNAME=@kvskeepintouch
REQUIRED_CHANNEL_URL=https://t.me/kvskeepintouch

GOOGLE_SHEETS_URL=
EVENTS_GOOGLE_SHEETS_URL=
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_SHEET_NAME=

AUTO_RESTART_ENABLED=true
AUTO_RESTART_DELAY_SECONDS=5
SEED_DEMO_DATA=false
```

3. Создайте базу данных:

```sql
CREATE DATABASE kvs_bot;
```

4. Если нужен импорт вакансий и работа с регистрациями на мероприятия через Google Sheets, положите JSON-ключ сервисного аккаунта в файл `credentials.json` и выдайте ему доступ к таблицам.

5. Запустите бота:

```bash
python main.py
```

При старте бот:

- создает недостающие таблицы;
- применяет легкие schema-updates из `database/db.py`;
- при необходимости подтягивает вакансии из Google Sheets;
- прогревает кэш изображений карточек вакансий.

## Запуск через Docker Compose

Быстрый сценарий:

```bash
docker-compose up -d --build
```

Полезные команды:

```bash
docker-compose logs -f bot
docker-compose down
```

Что поднимается:

- контейнер `postgres` с volume `postgres_data`;
- контейнер `bot`;
- volume `images_cache` для кэша сгенерированных изображений.

`docker-compose.yml` монтирует:

- `.env` в `/app/.env`;
- `credentials.json` в `/app/credentials.json`;
- кэш изображений в `/app/cache/images`.

Подробности по Docker-сценариям и диагностике смотрите в [DOCKER.md](/C:/Users/ilyag/PycharmProjects/KVS_Bot/kvs_career_bot/DOCKER.md).

## Работа с Google Sheets

Используются две независимые интеграции:

- таблица вакансий для синхронизации записей в БД;
- таблица мероприятий, куда выгружаются участники по каждому событию.

Для работы интеграции нужно:

1. создать сервисный аккаунт в Google Cloud;
2. включить Google Sheets API;
3. скачать JSON-ключ;
4. сохранить его как `credentials.json` или указать путь в `GOOGLE_CREDENTIALS_FILE`;
5. выдать сервисному аккаунту доступ к нужным таблицам.

## Структура проекта

```text
kvs_career_bot/
├── main.py
├── config.py
├── database/
│   ├── db.py
│   └── models.py
├── handlers/
│   ├── admin.py
│   ├── registration.py
│   ├── subscription.py
│   └── vacancies.py
├── middleware/
│   ├── activity.py
│   └── subscription.py
├── services/
│   ├── admins.py
│   ├── company_utils.py
│   ├── course_utils.py
│   ├── event_photos.py
│   ├── google_sheets.py
│   ├── image_generator.py
│   ├── subscription.py
│   ├── user_metrics.py
│   └── user_names.py
├── scripts/
│   ├── generate_vacancies.py
│   ├── wait-for-postgres.sh
│   └── README_GENERATE.md
├── assets/
├── cache/
├── Dockerfile
├── docker-compose.yml
└── DOCKER.md
```

### Кратко по модулям

- `main.py` — инициализация бота, middleware, роутеров и автоперезапуска;
- `database/models.py` — ORM-модели пользователей, вакансий, компаний, мероприятий, регистраций и действий пользователей;
- `database/db.py` — подключение к БД и автоинициализация схемы;
- `handlers/vacancies.py` — основная пользовательская логика;
- `handlers/registration.py` — пошаговая регистрация;
- `handlers/admin.py` — админ-панель и административные сценарии;
- `middleware/activity.py` — обновление `last_activity` и запись событий в аналитику;
- `middleware/subscription.py` — проверка обязательной подписки;
- `services/google_sheets.py` — импорт вакансий и экспорт участников мероприятий;
- `services/user_metrics.py` — нормализация и агрегация событий для аналитики;
- `services/image_generator.py` — генерация изображений карточек вакансий.

## Модели данных

Ключевые таблицы:

- `users` — профиль пользователя и его регистрационные данные;
- `vacancies` — вакансии и привязка к факультетам;
- `companies` и `divisions` — компании-партнеры и их подразделения;
- `events` — мероприятия;
- `event_registrations` — регистрация пользователей на мероприятия;
- `statistics` — агрегированные служебные показатели;
- `user_actions` — история действий пользователей для метрики.

## Генерация тестовых вакансий

Есть вспомогательный скрипт:

```bash
python scripts/generate_vacancies.py
python scripts/generate_vacancies.py 100
python scripts/generate_vacancies.py 50 --csv-only
python scripts/generate_vacancies.py 100 --clear
```

Скрипт умеет:

- генерировать CSV с тестовыми вакансиями;
- при настроенном Google Sheets загружать данные в таблицу;
- обновлять набор тестовых записей.

Подробности — в `scripts/README_GENERATE.md`.
