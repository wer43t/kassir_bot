import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

import db
import parser as kparser
from config import CHECK_INTERVAL_MINUTES

log = logging.getLogger(__name__)


def _fmt_price(price: float | None) -> str:
    return f" · от {int(price):,} ₽".replace(",", "\u202f") if price else ""


def _fmt_sectors(sectors: list[str]) -> str:
    return f" · {', '.join(sectors)}" if sectors else ""


async def check_subscription(bot: Bot, sub: dict) -> None:
    sub_id, chat_id, page_url = sub["id"], sub["chat_id"], sub["url"]

    page = await kparser.fetch_page_data(page_url)
    if page.error:
        log.warning("[sub %d] page error: %s", sub_id, page.error)
        return

    if page.title and page.title != sub["title"]:
        await db.update_title(sub_id, page.title)

    title = page.title or sub["title"] or page_url

    if not page.sessions:
        return

    for sess in page.sessions:
        prev_tickets = await db.get_event_ticket_status(sub_id, sess.event_id)

        avail = await kparser.fetch_order_kit(sess.event_id)
        has_tickets = 1 if avail.has_tickets else 0

        is_new = await db.upsert_event(sub_id, sess.event_id, sess.label, has_tickets)

        price = _fmt_price(avail.min_price)
        sectors = _fmt_sectors(avail.sectors)
        link = f'<a href="{sess.url}">Купить</a>'

        if is_new and avail.has_tickets:
            text = (
                f"<b>{title}</b>\n\n"
                f"Новая дата: <b>{sess.label}</b>\n"
                f"{avail.total_tickets} билетов{price}{sectors}\n\n"
                f"{link}"
            )
            await _send(bot, chat_id, text)

        elif is_new:
            text = (
                f"<b>{title}</b>\n\n"
                f"Новая дата: <b>{sess.label}</b>\n"
                f"Билетов пока нет\n\n"
                f'<a href="{sess.url}">Открыть</a>'
            )
            await _send(bot, chat_id, text)

        elif prev_tickets == 0 and has_tickets == 1:
            text = (
                f"<b>{title}</b>\n\n"
                f"Появились билеты: <b>{sess.label}</b>\n"
                f"{avail.total_tickets} шт{price}{sectors}\n\n"
                f"{link}"
            )
            await _send(bot, chat_id, text)


async def _send(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML",
                               disable_web_page_preview=True)
    except Exception as e:
        log.warning("send_message to %s failed: %s", chat_id, e)


async def check_all(bot: Bot) -> None:
    subs = await db.all_subscriptions()
    if not subs:
        return
    log.info("checking %d subscriptions", len(subs))
    for sub in subs:
        try:
            await check_subscription(bot, sub)
        except Exception as e:
            log.exception("sub %s: %s", sub["id"], e)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        check_all,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        kwargs={"bot": bot},
        id="check_all",
        replace_existing=True,
    )
    return scheduler
