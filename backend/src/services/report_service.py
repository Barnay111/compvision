"""Daily visitor reports delivered to Telegram, plus the background scheduler that sends them."""

import asyncio
import html
import logging
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.models.db_models import DBReportRecipient
from src.models.report import Recipient, RecipientCreate, RecipientUpdate
from src.repositories.event_repo import EventRepository, PostgresEventRepository
from src.services import telegram
from src.services.analytics_service import compute_analytics, local_midnight_ts, MAX_DWELL_SEC

log = logging.getLogger("reports")

SCHEDULER_TICK_SEC = 30
RETRY_AFTER_SEC = 600  # after a failed send, wait this long before trying the same recipient again

_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]
_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _day(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]}"


def _num(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def _delta(current: int, previous: int, label: str) -> str:
    if previous == 0:
        return ""
    pct = round((current - previous) / previous * 100)
    if pct == 0:
        return f" (≈ как {label})"
    return f" ({'▲ +' if pct > 0 else '▼ −'}{abs(pct)}% к {label})"


def _minutes(m: Optional[float]) -> str:
    if m is None:
        return "—"
    if m < 60:
        return f"{round(m)} мин"
    h, rest = divmod(round(m), 60)
    return f"{h} ч {rest} мин" if rest else f"{h} ч"


async def build_daily_report(repo: EventRepository, branch_id: int, day: date, tz: ZoneInfo) -> str:
    start, end = local_midnight_ts(day, tz), local_midnight_ts(day + timedelta(days=1), tz)
    events = await repo.get_in_range(branch_id, start, end + MAX_DWELL_SEC)
    a = compute_analytics(branch_id, events, day, day, tz, prev_visits=0)
    s = a.summary

    week_ago = day - timedelta(days=7)
    same_day_last_week = await repo.count_visits(
        branch_id, local_midnight_ts(week_ago, tz), local_midnight_ts(week_ago + timedelta(days=1), tz)
    )
    week_start = day - timedelta(days=6)
    week_visits = await repo.count_visits(branch_id, local_midnight_ts(week_start, tz), end)

    lines = [f"📊 <b>Посетители за {_day(day)}</b>", f"Филиал #{branch_id}", ""]
    if not any(start <= e.timestamp < end for e in events):
        lines.append("⚠️ За день не было ни одного события с камеры — проверьте, что камера и модуль работают.")
    else:
        peak = s.peak_hour
        peak_visits = a.by_hour[peak].visits if peak is not None else 0
        lines += [
            f"👥 Визитов: <b>{_num(s.visits)}</b>{_delta(s.visits, same_day_last_week, _day(week_ago).split(',')[0] + ' прошлой недели')}",
            f"⏰ Пиковый час: {peak:02d}:00–{(peak + 1) % 24:02d}:00 ({peak_visits} чел.)" if peak is not None else "⏰ Пиковый час: —",
            f"⏱ Время внутри: {_minutes(s.median_dwell_min)} (медиана)",
            f"🔁 Вернулись после выхода: {_num(s.returning)}",
        ]
    lines += ["", f"📈 За 7 дней: {_num(week_visits)} визитов, в среднем {_num(week_visits / 7)} в день"]
    if settings.DASHBOARD_URL:
        lines.append(f'\n<a href="{html.escape(settings.DASHBOARD_URL, quote=True)}#analytics">Открыть дашборд</a>')
    return "\n".join(lines)


def _local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def _due_today(recipient: DBReportRecipient, now: datetime) -> bool:
    hh, mm = map(int, recipient.send_time.split(":"))
    return (now.hour, now.minute) >= (hh, mm) and recipient.last_sent_date != now.date()


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.events = PostgresEventRepository(session=session)

    async def list(self, branch_id: Optional[int] = None) -> List[Recipient]:
        query = select(DBReportRecipient).order_by(DBReportRecipient.id)
        if branch_id is not None:
            query = query.where(DBReportRecipient.branch_id == branch_id)
        rows = (await self.session.execute(query)).scalars().all()
        return [Recipient.model_validate(r) for r in rows]

    async def _get(self, recipient_id: int) -> DBReportRecipient:
        row = await self.session.get(DBReportRecipient, recipient_id)
        if row is None:
            raise LookupError("Recipient not found")
        return row

    async def create(self, data: RecipientCreate) -> Recipient:
        row = DBReportRecipient(**data.model_dump())
        # Don't fire today's report the moment someone is added after the send time; start tomorrow.
        if _due_today(row, _local_now(row.tz)):
            row.last_sent_date = _local_now(row.tz).date()
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return Recipient.model_validate(row)

    async def update(self, recipient_id: int, data: RecipientUpdate) -> Recipient:
        row = await self._get(recipient_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await self.session.commit()
        await self.session.refresh(row)
        return Recipient.model_validate(row)

    async def delete(self, recipient_id: int) -> None:
        await self.session.delete(await self._get(recipient_id))
        await self.session.commit()

    async def preview(self, branch_id: int, day: date, tz: str) -> str:
        return await build_daily_report(self.events, branch_id, day, ZoneInfo(tz))

    async def send_test(self, recipient_id: int) -> None:
        row = await self._get(recipient_id)
        await telegram.send_message(
            row.telegram_chat_id,
            f"✅ CompVision подключён.\nЕжедневный отчёт по филиалу #{row.branch_id} будет приходить в {row.send_time}.",
        )

    async def send_report_now(self, recipient_id: int) -> None:
        row = await self._get(recipient_id)
        yesterday = _local_now(row.tz).date() - timedelta(days=1)
        await telegram.send_message(row.telegram_chat_id, await self.preview(row.branch_id, yesterday, row.tz))

    async def send_due(self, failed_at: Dict[int, float]) -> int:
        """Sends yesterday's report to every recipient whose send time has come today. Returns how many were sent."""
        rows = (await self.session.execute(
            select(DBReportRecipient).where(DBReportRecipient.enabled.is_(True))
        )).scalars().all()
        sent = 0
        for row in rows:
            now = _local_now(row.tz)
            if not _due_today(row, now) or time.time() - failed_at.get(row.id, 0) < RETRY_AFTER_SEC:
                continue
            try:
                text = await self.preview(row.branch_id, now.date() - timedelta(days=1), row.tz)
                await telegram.send_message(row.telegram_chat_id, text)
            except Exception as e:  # keep the scheduler alive whatever happens with one recipient
                failed_at[row.id] = time.time()
                log.warning("Daily report to recipient %s failed: %s", row.id, e)
                continue
            failed_at.pop(row.id, None)
            row.last_sent_date = now.date()
            await self.session.commit()
            sent += 1
            log.info("Daily report sent to recipient %s (%s)", row.id, row.name)
        return sent


async def report_scheduler() -> None:
    """Background loop started with the API: checks every SCHEDULER_TICK_SEC who is due a report."""
    failed_at: Dict[int, float] = {}
    while True:
        try:
            if settings.TELEGRAM_BOT_TOKEN:
                async with AsyncSessionLocal() as session:
                    await ReportService(session).send_due(failed_at)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Report scheduler tick failed")
        await asyncio.sleep(SCHEDULER_TICK_SEC)
