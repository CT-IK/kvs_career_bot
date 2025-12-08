FROM python:3.12-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f -v

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Копирование скрипта ожидания PostgreSQL
COPY scripts/wait-for-postgres.sh /app/wait-for-postgres.sh
RUN chmod +x /app/wait-for-postgres.sh

# Создание entrypoint скрипта
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "Ожидание PostgreSQL..."\n\
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do\n\
  echo "PostgreSQL недоступен - ожидание..."\n\
  sleep 2\n\
done\n\
\n\
echo "PostgreSQL доступен!"\n\
\n\
echo "Применение миграций..."\n\
python -c "import asyncio; from database.db import init_db; asyncio.run(init_db())"\n\
\n\
echo "Запуск бота..."\n\
exec python main.py\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

