import re
import aiohttp
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional

ORDER_KIT_URL = "https://api.kassir.ru/api/events/{event_id}/order-kit?domain=kzn.kassir.ru&platformState=website"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://kzn.kassir.ru/",
    "Cache-Control": "no-cache",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://kzn.kassir.ru",
    "Referer": "https://kzn.kassir.ru/",
    "x-captcha-type": "SMART_CAPTCHA",
    "x-captcha-token": "",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

_FRAGMENT_RE = re.compile(r"#(\d{5,10})$")


@dataclass
class SessionInfo:
    event_id: int
    date_str: str
    time_str: str
    url: str

    @property
    def label(self) -> str:
        if self.time_str:
            return f"{self.date_str}, {self.time_str}"
        return self.date_str


@dataclass
class TicketAvailability:
    event_id: int
    total_tickets: int
    min_price: Optional[float]
    sectors: list[str]
    error: str = ""

    @property
    def has_tickets(self) -> bool:
        return self.total_tickets > 0 and not self.error


@dataclass
class PageData:
    title: str = ""
    sessions: list[SessionInfo] = field(default_factory=list)
    error: str = ""


def _extract_fragment_id(href: str) -> Optional[int]:
    m = _FRAGMENT_RE.search(href)
    return int(m.group(1)) if m else None


def _parse_sessions(soup: BeautifulSoup, base_url: str) -> list[SessionInfo]:
    sessions: dict[int, SessionInfo] = {}

    def make_url(event_id: int) -> str:
        return base_url.split("#")[0].rstrip("/") + f"#{event_id}"

    date_tabs = soup.select("li.event-date-selector-tab")

    if date_tabs:
        for tab in date_tabs:
            tab_link = tab.select_one("a[href]")
            if not tab_link:
                continue

            first_span = tab_link.find("span")
            if first_span:
                date_only = first_span.get_text(strip=True)
            else:
                date_text = tab_link.get_text(" ", strip=True)
                date_text = re.sub(r"(?i)\s*купить\s*", "", date_text)
                date_only = re.sub(r"\s+", " ", date_text).strip().split(",")[0]

            time_items = tab.select("li.date-selector-time-item a[href]")

            if time_items:
                for ti in time_items:
                    href = ti.get("href", "")
                    eid = _extract_fragment_id(href)
                    if not eid or eid in sessions:
                        continue
                    sessions[eid] = SessionInfo(
                        event_id=eid,
                        date_str=date_only,
                        time_str=ti.get_text(strip=True),
                        url=make_url(eid),
                    )
            else:
                href = tab_link.get("href", "")
                eid = _extract_fragment_id(href)
                if eid and eid not in sessions:
                    sessions[eid] = SessionInfo(
                        event_id=eid,
                        date_str=date_only,
                        time_str="",
                        url=make_url(eid),
                    )
    # для страниц с одной датой табов нет - event_id в canonical
    if not sessions:
        canonical_tag = soup.find("link", rel="canonical")
        canonical_href = canonical_tag.get("href", "") if canonical_tag else ""
        eid = _extract_fragment_id(canonical_href)
        if eid:
            date_el = soup.select_one("[data-selenide=\"eventScheduleDate\"]")
            if date_el:
                raw = re.sub(r"\s+", " ", date_el.get_text(" ", strip=True)).strip()
                parts = [p.strip() for p in raw.split(",")]
                date_only = parts[0] if parts else raw
                time_only = parts[1].strip() if len(parts) > 1 else ""
            else:
                date_only, time_only = f"#{eid}", ""
            sessions[eid] = SessionInfo(
                event_id=eid,
                date_str=date_only,
                time_str=time_only,
                url=make_url(eid),
            )

    # последний вариант - fragment прямо в URL от пользователя
    if not sessions:
        eid = _extract_fragment_id(base_url)
        if eid:
            sessions[eid] = SessionInfo(
                event_id=eid,
                date_str="",
                time_str="",
                url=base_url,
            )

    return list(sessions.values())


async def fetch_page_data(page_url: str) -> PageData:
    try:
        async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
            async with session.get(
                page_url,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return PageData(error=f"HTTP {resp.status}")
                html = await resp.text()
    except Exception as e:
        return PageData(error=str(e))

    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if h1 := soup.find("h1"):
        title = h1.get_text(" ", strip=True)
    if not title:
        if og := soup.find("meta", property="og:title"):
            title = (og.get("content") or "").strip()

    return PageData(title=title, sessions=_parse_sessions(soup, page_url))


async def fetch_order_kit(event_id: int) -> TicketAvailability:
    url = ORDER_KIT_URL.format(event_id=event_id)
    try:
        async with aiohttp.ClientSession(headers=API_HEADERS) as session:
            async with session.post(
                url, data=b"{}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return TicketAvailability(
                        event_id=event_id, total_tickets=0,
                        min_price=None, sectors=[],
                        error=f"HTTP {resp.status}",
                    )
                data = await resp.json(content_type=None)
    except Exception as e:
        return TicketAvailability(
            event_id=event_id, total_tickets=0,
            min_price=None, sectors=[], error=str(e),
        )

    total = sum(q.get("ticketsCount", 0) for q in data.get("quotas", []))

    sector_ids = {
        q["sectorId"]
        for q in data.get("quotas", [])
        if q.get("ticketsCount", 0) > 0
    }
    sectors = [s["name"] for s in data.get("sectors", []) if s["id"] in sector_ids]

    min_price: Optional[float] = None
    for tg in data.get("tariffGroups", []):
        for t in tg.get("tariffs", []):
            p = t.get("price")
            if p is not None and (min_price is None or p < min_price):
                min_price = p

    return TicketAvailability(
        event_id=event_id,
        total_tickets=total,
        min_price=min_price,
        sectors=sectors,
    )
