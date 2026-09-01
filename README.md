# KVS Career Bot

Telegram-бот на `aiogram` и `PostgreSQL` для карьерного проекта КВС. Бот регистрирует пользователей, показывает вакансии и компании, ведет мероприятия, собирает метрики действий и поддерживает админские сценарии.

## Что умеет бот

### Пользовательская часть

- регистрация с заполнением ФИО, курса, факультета и источника информации;
- обязательная проверка подписки на канал перед доступом к основным разделам;
- каталог вакансий:
  - подборка по факультету;
  - общий список;
  - фильтрация по сферам;
- карточки вакансий, компаний и подразделений;
- просмотр и редактирование профиля;
- список мероприятий и регистрация в основной список или резерв;
- обратная связь через бот;
- раздел "О нас".

### Админская часть

- статистика по пользователям, вакансиям, компаниям и мероприятиям;
- метрики пользовательских действий;
- ручная синхронизация вакансий из Google Sheets;
- создание, редактирование, публикация и удаление мероприятий;
- массовая рассылка;
- личные сообщения пользователям по `username`;
- ответы на обращения из обратной связи;
- управление администраторами через интерфейс бота.

## Как устроен поток вакансий

Источник вакансий в текущей реализации: `Google Sheets`, не локальный `.xlsx`.

Что происходит в приложении:

1. При старте бот создает недостающие таблицы в PostgreSQL.
2. Если таблица `vacancies` пустая, выполняется первичная загрузка вакансий из Google Sheets.
3. После синхронизации прогревается кэш карточек вакансий.
4. Ежедневно запускается фоновая синхронизация вакансий по расписанию.
5. Администратор может запустить ту же синхронизацию вручную через `/sync_vacancies`.

По умолчанию ежедневный запуск настроен на `05:30` по Москве.

## Команды

- `/start` - запуск бота и регистрация;
- `/vacancies` - переход в раздел вакансий;
- `/admin` - вход в админ-панель;
- `/sync_vacancies` - ручная синхронизация вакансий из Google Sheets.

## Стек

- Python `3.13+`
- `aiogram 3`
- `SQLAlchemy Async`
- `asyncpg`
- `PostgreSQL 15`
- `gspread` и `google-auth` для Google Sheets
- `Pillow` для генерации карточек
- `Docker` / `Docker Compose`

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
│   ├── user_names.py
│   └── vacancy_scheduler.py
├── scripts/
│   ├── generate_vacancies.py
│   ├── README_GENERATE.md
│   └── wait-for-postgres.sh
├── assets/
├── cache/
├── Dockerfile
├── docker-compose.yml
└── DOCKER.md
```

Ключевые модули:

- `main.py` - запуск бота, регистрация middleware, startup-процедуры и фоновый scheduler;
- `database/db.py` - подключение к БД и простые schema-updates при старте;
- `database/models.py` - ORM-модели пользователей, вакансий, компаний, событий и метрик;
- `services/google_sheets.py` - импорт вакансий и экспорт регистраций на мероприятия;
- `services/image_generator.py` - генерация и актуализация карточек вакансий;
- `services/vacancy_scheduler.py` - ежедневная синхронизация вакансий по расписанию;
- `middleware/activity.py` - логирование действий пользователей в аналитику.

## Данные и сущности

Основные таблицы:

- `users` - профиль пользователя;
- `vacancies` - вакансии и факультетные флаги;
- `companies` - компании;
- `divisions` - подразделения компаний;
- `events` - мероприятия;
- `event_registrations` - регистрации пользователей на мероприятия;
- `statistics` - агрегированные служебные показатели;
- `user_actions` - история действий пользователей.

## Конфигурация

Проект читает настройки из `.env`.

### Основные переменные

- `BOT_TOKEN` - токен Telegram-бота;
- `ADMIN_IDS` - список Telegram ID администраторов через запятую;
- `MAX_BOT_TOKEN` - токен бота MAX; используется для проверки initData и всех уведомлений о мероприятиях;
- `MAX_ADMIN_IDS` - список MAX ID администраторов миниаппа через запятую;
- `MAX_REQUIRED_CHANNEL_ID` - числовой ID обязательного канала MAX;
- `MAX_REQUIRED_CHANNEL_URL` - публичная ссылка на обязательный канал MAX;
- `MAX_API_BASE_URL` - адрес Bot API MAX (по умолчанию `https://platform-api2.max.ru`);

Для проверки подписки MAX-бот должен быть назначен администратором канала. Без этого API MAX не возвращает список участников. После настройки укажите ID канала, ссылку, токен и MAX ID администраторов в `.env`, затем перезапустите сервис.
- `DB_HOST` - хост PostgreSQL;
- `DB_PORT` - порт PostgreSQL;
- `DB_NAME` - имя базы;
- `DB_USER` - пользователь базы;
- `DB_PASSWORD` - пароль базы.

### Проверка подписки

- `REQUIRED_CHANNEL_USERNAME` - username или numeric id обязательного канала;
- `REQUIRED_CHANNEL_URL` - ссылка на канал.

### Google Sheets

- `GOOGLE_SHEETS_URL` - таблица с вакансиями;
- `GOOGLE_SHEET_NAME` - имя таблицы, если не используется URL;
- `EVENTS_GOOGLE_SHEETS_URL` - таблица для листов с участниками мероприятий;
- `GOOGLE_CREDENTIALS_FILE` - путь до JSON-ключа сервисного аккаунта.

### Поведение приложения

- `AUTO_RESTART_ENABLED` - автоперезапуск после падения;
- `AUTO_RESTART_DELAY_SECONDS` - задержка перед рестартом;
- `SEED_DEMO_DATA` - загрузка демо-компаний и подразделений;
- `VACANCY_SYNC_SCHEDULE_ENABLED` - включение ежедневной синхронизации вакансий;
- `VACANCY_SYNC_HOUR` - час запуска синхронизации;
- `VACANCY_SYNC_MINUTE` - минута запуска синхронизации;
- `VACANCY_SYNC_TIMEZONE` - timezone для расписания, по умолчанию `Europe/Moscow`.
- `VACANCY_SYNC_ALLOW_EMPTY` - разрешение применить пустой снимок; рекомендуется оставлять `false`, чтобы ошибка источника не удалила текущие вакансии.
- `MINIAPP_PUBLIC_URL` - публичный HTTPS-адрес Mini App, который открывается из уведомлений;
- `EVENT_REMINDERS_ENABLED` - включает напоминания о добавленных мероприятиях;
- `EVENT_REMINDER_POLL_SECONDS` - интервал проверки напоминаний, минимум 30 секунд.

## Локальный запуск

Все команды ниже предполагают, что рабочая директория: `kvs_career_bot/`.

### 1. Установите зависимости

```bash
pip install -r requirements.txt
```

### 2. Создайте `.env`

```env
BOT_TOKEN=your_bot_token
ADMIN_IDS=123456789,987654321

DB_HOST=localhost
DB_PORT=5432
DB_NAME=kvs_bot
DB_USER=postgres
DB_PASSWORD=postgres

REQUIRED_CHANNEL_USERNAME=@kvskeepintouch
REQUIRED_CHANNEL_URL=https://t.me/kvskeepintouch

GOOGLE_SHEETS_URL=
GOOGLE_SHEET_NAME=
EVENTS_GOOGLE_SHEETS_URL=
GOOGLE_CREDENTIALS_FILE=credentials.json

AUTO_RESTART_ENABLED=true
AUTO_RESTART_DELAY_SECONDS=5
SEED_DEMO_DATA=false

MINIAPP_PUBLIC_URL=https://example.com/miniapp
EVENT_REMINDERS_ENABLED=true
EVENT_REMINDER_POLL_SECONDS=60

VACANCY_SYNC_SCHEDULE_ENABLED=true
VACANCY_SYNC_HOUR=0
VACANCY_SYNC_MINUTE=0
VACANCY_SYNC_TIMEZONE=Europe/Moscow
VACANCY_SYNC_ALLOW_EMPTY=false
```

Mini App читает вакансии из PostgreSQL и поэтому не ждёт Google Sheets при
первом открытии. В 00:00 источник загружается в фоне и применяется одной
транзакцией: исчезнувшие вакансии удаляются, новые добавляются, изменённые
обновляются. При ошибке или пустом ответе предыдущий список остаётся доступен.

### 3. Создайте базу данных

```sql
CREATE DATABASE kvs_bot;
```

### 4. Подготовьте доступ к Google Sheets

Если нужны импорт вакансий и выгрузка регистраций:

1. Создайте сервисный аккаунт в Google Cloud.
2. Включите Google Sheets API и Google Drive API.
3. Скачайте JSON-ключ.
4. Сохраните его как `credentials.json` или укажите путь в `GOOGLE_CREDENTIALS_FILE`.
5. Выдайте сервисному аккаунту доступ к нужным таблицам.

### 5. Запустите бот

```bash
python main.py
```

## Запуск через Docker Compose

Быстрый запуск:

```bash
docker-compose up -d --build
```

Полезные команды:

```bash
docker-compose logs -f bot
docker-compose ps
docker-compose down
```

`docker-compose.yml` поднимает:

- контейнер `postgres`;
- контейнер `bot`;
- volume для кэша карточек вакансий.

Подробности по Docker-сценарию и диагностике: [DOCKER.md](./DOCKER.md)

## Формат таблицы вакансий

Бот работает с первой вкладкой таблицы вакансий.

Ожидания по структуре:

- заголовки находятся во `2` строке;
- данные начинаются с `3` строки;
- для факультетов используются отдельные колонки.

Основные колонки:

- `Организация`
- `Подразделение`
- `Вакансия`
- `Сфера`
- `ЗП`
- `График`
- `Формат`
- `Описание`
- `Формат трудоустройства`
- `Особенность 1`
- `Особенность 2`
- `Особенность 3`

Факультетные колонки:

- `ИТиАБД`
- `ИОО`
- `ФинФак`
- `ВШУ`
- `НАБ`
- `СНиМК`
- `МЭО`
- `ФЭБ`
- `ЮрФак`

## Карточки вакансий

Карточки вакансий рендерятся из PNG-шаблона и кэшируются на диске.

Когда кэш обновляется:

- при старте приложения;
- после синхронизации вакансий;
- по ежедневному расписанию вместе с автосинком;
- при ручной синхронизации через `/sync_vacancies`.

## Метрики и аналитика

Бот пишет историю действий пользователей в `user_actions`.

Фиксируются, в частности:

- `telegram_id` пользователя;
- тип апдейта;
- нормализованное действие;
- исходное значение события;
- `chat_type`;
- `fsm_state`;
- время события.

Эти данные используются в админском экране метрик.

## Тестовые вакансии

В проекте есть вспомогательный генератор:

```bash
python scripts/generate_vacancies.py
python scripts/generate_vacancies.py 100
python scripts/generate_vacancies.py 50 --csv-only
python scripts/generate_vacancies.py 100 --clear
```

Скрипт умеет:

- генерировать тестовые вакансии;
- сохранять их в CSV;
- при настроенном доступе записывать их в Google Sheets.

Подробности: `scripts/README_GENERATE.md`.
