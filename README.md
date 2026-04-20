# kassir-bot

Телеграм-бот для мониторинга билетов на kassir.ru. Присылаешь ссылку на страницу шоу - бот следит за появлением новых дат и возвратом билетов в продажу.

## Как работает

Страница шоу на kassir.ru содержит компонент выбора дат (`li.event-date-selector-tab`), где каждый сеанс имеет свой `event_id` в href-фрагменте. Бот парсит этот список, затем для каждого `event_id` делает запрос к внутреннему API:

```
POST https://api.kassir.ru/api/events/{id}/order-kit?domain=kzn.kassir.ru&platformState=website
```

В ответе смотрим на `quotas[].ticketsCount`. Если появился новый event_id или счётчик вырос с нуля - уведомление в телеграм.

Работает только с российского IP - `api.kassir.ru` режет остальные.

## Установка

```bash
git clone https://github.com/you/kassir-bot
cd kassir-bot

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# вписать BOT_TOKEN в .env

python bot.py
```

## Docker

```bash
cp .env.example .env
# вписать BOT_TOKEN в .env

docker compose up -d
docker compose logs -f
```

База хранится в named volume, при пересборке не теряется.

## Конфигурация

| Переменная       | По умолчанию    | Описание                    |
|------------------|-----------------|-----------------------------|
| `BOT_TOKEN`      | -               | Токен от @BotFather          |
| `CHECK_INTERVAL` | `15`            | Интервал проверки в минутах |
| `DB_PATH`        | `kassir_bot.db` | Путь к SQLite базе          |

## Команды

| Команда  | Действие                              |
|----------|---------------------------------------|
| `/list`  | Список подписок с кнопками отписки    |
| `/check` | Принудительная проверка прямо сейчас  |
| `/help`  | Справка                               |
| `<url>`  | Добавить страницу шоу в мониторинг    |
