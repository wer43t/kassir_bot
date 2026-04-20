FROM python:3.12-slim

WORKDIR /app

# Зависимости отдельным слоем — кэшируются при пересборке
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД хранится в volume, не в образе
VOLUME ["/data"]
ENV DB_PATH=/data/kassir_bot.db

CMD ["python", "bot.py"]
