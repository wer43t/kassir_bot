import aiosqlite
from config import DB_PATH

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    url        TEXT    NOT NULL,
    title      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chat_id, url)
);

CREATE TABLE IF NOT EXISTS known_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    event_id        INTEGER NOT NULL,
    date_str        TEXT    NOT NULL DEFAULT '',
    -- Статус наличия билетов: NULL=неизвестно, 0=нет, 1=есть
    has_tickets     INTEGER,
    first_seen_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(subscription_id, event_id)
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_SQL)
        await db.commit()


async def add_subscription(chat_id: int, url: str, title: str) -> tuple[int, bool]:
    """Добавить подписку. Возвращает (id, is_new)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO subscriptions (chat_id, url, title) VALUES (?, ?, ?)",
            (chat_id, url, title),
        )
        await db.commit()
        if cursor.lastrowid and cursor.rowcount:
            return cursor.lastrowid, True
        row = await (await db.execute(
            "SELECT id FROM subscriptions WHERE chat_id=? AND url=?", (chat_id, url)
        )).fetchone()
        return row[0], False


async def get_subscription_id(chat_id: int, url: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute(
            "SELECT id FROM subscriptions WHERE chat_id=? AND url=?", (chat_id, url)
        )).fetchone()
        return row[0] if row else None


async def remove_subscription(chat_id: int, url: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM subscriptions WHERE chat_id=? AND url=?", (chat_id, url)
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_subscription_by_id(chat_id: int, sub_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM subscriptions WHERE id=? AND chat_id=?", (sub_id, chat_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def list_subscriptions(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT id, url, title, created_at FROM subscriptions WHERE chat_id=? ORDER BY created_at",
            (chat_id,),
        )).fetchall()
        return [dict(r) for r in rows]


async def all_subscriptions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT id, chat_id, url, title FROM subscriptions"
        )).fetchall()
        return [dict(r) for r in rows]


async def update_title(sub_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET title=? WHERE id=?", (title, sub_id))
        await db.commit()


async def get_known_events(sub_id: int) -> dict[int, dict]:
    """Возвращает {event_id: {date_str, has_tickets}}"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT event_id, date_str, has_tickets FROM known_events WHERE subscription_id=?",
            (sub_id,),
        )).fetchall()
        return {r["event_id"]: dict(r) for r in rows}


async def upsert_event(sub_id: int, event_id: int, date_str: str,
                       has_tickets: int | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO known_events (subscription_id, event_id, date_str, has_tickets) "
            "VALUES (?, ?, ?, ?)",
            (sub_id, event_id, date_str, has_tickets),
        )
        is_new = cur.rowcount > 0
        if not is_new:
            await db.execute(
                "UPDATE known_events SET has_tickets=?, date_str=? "
                "WHERE subscription_id=? AND event_id=?",
                (has_tickets, date_str, sub_id, event_id),
            )
        await db.commit()
        return is_new


async def get_event_ticket_status(sub_id: int, event_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute(
            "SELECT has_tickets FROM known_events WHERE subscription_id=? AND event_id=?",
            (sub_id, event_id),
        )).fetchone()
        return row[0] if row else None
