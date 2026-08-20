# Support Bot

Telegram-бот поддержки: пересылает сообщения пользователей администратору,
администратор отвечает реплаем — ответ уходит нужному пользователю.

Поддерживает два языка (русский и туркменский) с полностью редактируемыми
текстами и хранит все данные в PostgreSQL, так что при перезапуске
контейнера ничего не теряется.

## Возможности

- Выбор языка пользователем через кнопки при первом `/start`
- Смена языка в любой момент командой `/language`
- Все видимые пользователю тексты — в `locales/ru.json` и `locales/tk.json`
- Пересылка любых типов сообщений (текст, фото, видео, документы, голос,
  стикеры, геолокация, опросы и т.д.) в обе стороны
- Данные (пользователи, язык, привязка сообщений) — в PostgreSQL
- `/stats` — базовая статистика для администратора

## Структура проекта

```
.
├── main.py              # логика бота и обработчики
├── db.py                 # доступ к PostgreSQL (asyncpg)
├── i18n.py                # загрузка и выдача переводов
├── locales/
│   ├── ru.json            # русские тексты
│   └── tk.json             # туркменские тексты
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── .dockerignore
```

## Как редактировать тексты бота

Просто открой `locales/ru.json` или `locales/tk.json` и поменяй нужную
строку. Ключи (левая часть) трогать не нужно — только значения (правая
часть). После изменения текста нужно перезапустить контейнер бота
(`docker compose restart bot`), код менять не требуется.

## Как добавить новый язык

1. Скопируй `locales/ru.json` в `locales/<код_языка>.json` (например `en.json`).
2. Переведи значения.
3. Добавь кнопку выбора этого языка в `language_keyboard()` в `main.py`
   (единственное место в коде, которое знает о конкретных языках выбора —
   сама система переводов языконезависима и подхватит файл автоматически).

## Переменные окружения

Скопируй `.env.example` в `.env` и заполни:

- `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
- `ADMIN_CHAT_ID` — chat_id администратора (узнать можно, например, через [@userinfobot](https://t.me/userinfobot))
- `DATABASE_URL` — строка подключения к PostgreSQL
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — параметры для сервиса `db` в docker-compose

## Запуск на VPS через Docker

```bash
git clone <URL_ЭТОГО_РЕПОЗИТОРИЯ>
cd support-bot
cp .env.example .env
# отредактируй .env — впиши BOT_TOKEN и ADMIN_CHAT_ID

docker compose up -d --build
```

Проверить логи:

```bash
docker compose logs -f bot
```

Обновить после изменений в коде:

```bash
git pull
docker compose up -d --build
```

Данные PostgreSQL хранятся в именованном Docker-volume `pgdata` и переживают
`docker compose down` / `docker compose up`. Если нужно полностью сбросить
данные: `docker compose down -v`.

## Локальный запуск без Docker (для разработки)

Нужен доступный PostgreSQL (например, через `docker compose up -d db`).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить BOT_TOKEN, ADMIN_CHAT_ID, DATABASE_URL
python main.py
```
