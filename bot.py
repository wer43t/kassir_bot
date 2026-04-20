import asyncio
import logging
import re
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import parser as kparser
import scheduler as sched
from config import BOT_TOKEN, CHECK_INTERVAL_MINUTES, ALLOWED_DOMAINS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

PAGE_SIZE = 5


def is_valid_kassir_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and any(
            p.netloc == d or p.netloc.endswith("." + d) for d in ALLOWED_DOMAINS
        )
    except Exception:
        return False


def extract_url(text: str) -> str | None:
    m = re.search(r"https?://[^\s]+", text)
    return m.group(0).rstrip(".,)>") if m else None


@dp.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await msg.answer(
        "Слежу за появлением билетов на kassir.ru.\n\n"
        "Пришли ссылку на страницу спектакля или концерта - "
        f"буду проверять каждые {CHECK_INTERVAL_MINUTES} мин "
        "и напишу когда появятся новые даты или билеты.\n\n"
        "/list - подписки\n"
        "/help - как это работает",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(
        "/list - список подписок\n"
        "/check - проверить прямо сейчас\n\n"
        "Как работает: парсим страницу шоу, собираем все сеансы с их event_id, "
        "для каждого дёргаем api.kassir.ru/api/events/{id}/order-kit и смотрим "
        "на quotas[].ticketsCount. Если появился новый сеанс или билеты вернулись - пишем.",
        parse_mode="HTML",
    )


def _list_keyboard(subs: list[dict], page: int) -> tuple[str, object]:
    total = len(subs)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    chunk = subs[start:start + PAGE_SIZE]

    lines = []
    builder = InlineKeyboardBuilder()
    for i, s in enumerate(chunk, start + 1):
        title = s["title"] or s["url"]
        lines.append(f"{i}. <b>{title}</b>\n   <code>{s['url']}</code>")
        builder.button(text=f"x {i}. {title[:28]}", callback_data=f"unsub:{s['id']}")
    builder.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="< назад", callback_data=f"list:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="вперёд >", callback_data=f"list:{page + 1}"))
    if nav:
        builder.row(*nav)

    page_info = f" {page + 1}/{pages}" if pages > 1 else ""
    header = f"<b>Подписки{page_info} · {total} шт</b>:\n\n"
    text = header + "\n\n".join(lines) + "\n\nНажми чтобы отписаться:"
    return text, builder.as_markup()


@dp.message(Command("list"))
async def cmd_list(msg: Message) -> None:
    subs = await db.list_subscriptions(msg.chat.id)
    if not subs:
        await msg.answer("Нет подписок. Пришли ссылку с kassir.ru.")
        return
    text, kb = _list_keyboard(subs, 0)
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("list:"))
async def cb_list_page(cb: CallbackQuery) -> None:
    page = int(cb.data[len("list:"):])
    subs = await db.list_subscriptions(cb.message.chat.id)
    if not subs:
        await cb.answer("Подписок нет.", show_alert=True)
        return
    text, kb = _list_keyboard(subs, page)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@dp.message(Command("check"))
async def cmd_check(msg: Message) -> None:
    subs = await db.list_subscriptions(msg.chat.id)
    if not subs:
        await msg.answer("Нет подписок.")
        return
    m = await msg.answer("Проверяю...")
    await sched.check_all(bot)
    await m.edit_text("Готово. Если что изменилось - написал выше.")


@dp.callback_query(F.data.startswith("unsub:"))
async def cb_unsub(cb: CallbackQuery) -> None:
    sub_id = int(cb.data[len("unsub:"):])
    if await db.remove_subscription_by_id(cb.message.chat.id, sub_id):
        await cb.answer("Удалено")
        await cb.message.edit_text("Подписка удалена.")
    else:
        await cb.answer("Уже удалено.", show_alert=True)


@dp.message(F.text)
async def handle_url(msg: Message) -> None:
    url = extract_url(msg.text or "")
    if not url:
        await msg.answer("Пришли ссылку на kassir.ru.")
        return
    if not is_valid_kassir_url(url):
        await msg.answer("Ссылка должна быть с kassir.ru.")
        return

    if await db.get_subscription_id(msg.chat.id, url) is not None:
        await msg.answer("Уже слежу за этой страницей.\n/list - управление подписками.")
        return

    status = await msg.answer("Загружаю страницу...")

    page = await kparser.fetch_page_data(url)
    if page.error:
        await status.edit_text(f"Не удалось загрузить: {page.error}")
        return

    sub_id, _ = await db.add_subscription(msg.chat.id, url, page.title)

    lines = []
    for sess in page.sessions:
        avail = await kparser.fetch_order_kit(sess.event_id)
        has_tickets = 1 if avail.has_tickets else 0
        await db.upsert_event(sub_id, sess.event_id, sess.label, has_tickets)

        status_str = "есть" if avail.has_tickets else "нет"
        price = f" · от {int(avail.min_price):,} ₽".replace(",", "\u202f") if avail.min_price else ""
        cnt = f" ({avail.total_tickets} шт)" if avail.has_tickets else ""
        lines.append(f"  {sess.label} - {status_str}{price}{cnt}")

    title = page.title or url
    sessions_text = "\n".join(lines) if lines else "  сеансов не найдено"

    await status.edit_text(
        f"Добавлено.\n\n"
        f"<b>{title}</b>\n\n"
        f"Текущие сеансы:\n{sessions_text}\n\n"
        f"Проверка каждые {CHECK_INTERVAL_MINUTES} мин.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def main() -> None:
    await db.init_db()
    scheduler = sched.create_scheduler(bot)
    scheduler.start()
    log.info("bot started, interval %d min", CHECK_INTERVAL_MINUTES)
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
