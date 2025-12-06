# Docker инструкции

## Быстрый старт

1. **Создайте `.env` файл:**
   ```bash
   cp env.example .env
   ```
   Заполните все необходимые переменные.

2. **Поместите `credentials.json`** в корень проекта (если используете Google Sheets).

3. **Запустите контейнеры:**
   ```bash
   docker-compose up -d
   ```

4. **Просмотр логов:**
   ```bash
   docker-compose logs -f bot
   ```

## Автоматические миграции

Миграции применяются автоматически при запуске контейнера бота:
- Бот ждет, пока PostgreSQL станет доступен
- Затем автоматически создаются все необходимые таблицы
- После этого запускается бот

## Управление контейнерами

```bash
# Остановка
docker-compose down

# Остановка с удалением volumes (удалит все данные!)
docker-compose down -v

# Пересборка образа
docker-compose build

# Перезапуск
docker-compose restart bot

# Просмотр статуса
docker-compose ps
```

## Доступ к PostgreSQL

```bash
# Подключение через psql
docker-compose exec postgres psql -U postgres -d kvs_bot

# Или извне (если порт проброшен)
psql -h localhost -p 5432 -U postgres -d kvs_bot
```

## Разработка

Для разработки можно использовать `docker-compose.override.yml`:
```bash
cp docker-compose.override.yml.example docker-compose.override.yml
```

Это позволит монтировать код в контейнер для hot-reload.

## Troubleshooting

### Бот не запускается
1. Проверьте логи: `docker-compose logs bot`
2. Убедитесь, что `.env` файл заполнен правильно
3. Проверьте, что PostgreSQL запущен: `docker-compose ps`

### Ошибки подключения к БД
1. Убедитесь, что PostgreSQL контейнер здоров: `docker-compose ps`
2. Проверьте переменные окружения в `.env`
3. Попробуйте пересоздать контейнеры: `docker-compose down && docker-compose up -d`

### Миграции не применяются
Миграции применяются при каждом запуске контейнера. Если таблицы не создаются:
1. Проверьте логи: `docker-compose logs bot | grep миграций`
2. Убедитесь, что у пользователя БД есть права на создание таблиц
3. Попробуйте подключиться к БД вручную и проверить подключение

