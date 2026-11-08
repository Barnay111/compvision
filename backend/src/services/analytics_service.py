"""Visitor analytics computed from raw ENTER/EXIT events.

Definitions:
- visit: an ENTER event that is not a ReID-recognised re-entry (returning=False);
- dwell time: from a visit's first ENTER to the last EXIT of the same person_id before
  that person's next visit (short exits for a smoke break stay inside one visit).
"""

import statistics
import time
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.models.analytics import (
    AnalyticsResponse,
    AnalyticsSummary,
    DayPoint,
    DwellBucket,
    HourPoint,
    LiveStats,
    WeekdayPoint,
)
from src.models.event import Event
from src.repositories.event_repo import EventRepository

MAX_DWELL_SEC = 6 * 3600     # longer "visits" are tracking errors (missed EXIT), ignored for dwell stats
LIVE_WINDOW_SEC = 12 * 3600  # people who entered earlier than this are not considered inside
MAX_RANGE_DAYS = 366

DWELL_BUCKETS = [  # (label, min minutes, max minutes)
    ("< 5 мин", 0, 5),
    ("5–15 мин", 5, 15),
    ("15–30 мин", 15, 30),
    ("30–60 мин", 30, 60),
    ("1–2 ч", 60, 120),
    ("> 2 ч", 120, None),
]


def local_midnight_ts(d: date, tz: ZoneInfo) -> float:
    return datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()


def is_visit(ev: Event) -> bool:
    return ev.action == "ENTER" and not ev.returning


def visit_dwells(events: Iterable[Event]) -> List[Tuple[float, float]]:
    """Returns (visit_start_ts, dwell_seconds) for every visit that has an EXIT. Events must be time-ordered."""
    open_visits = {}  # person_id -> [start_ts, last_exit_ts | None]
    result = []

    def close(person_id):
        start, last_exit = open_visits.pop(person_id)
        if last_exit is not None and 0 <= last_exit - start <= MAX_DWELL_SEC:
            result.append((start, last_exit - start))

    for ev in events:
        if is_visit(ev):
            if ev.person_id in open_visits:
                close(ev.person_id)
            open_visits[ev.person_id] = [ev.timestamp, None]
        elif ev.action == "EXIT" and ev.person_id in open_visits:
            open_visits[ev.person_id][1] = ev.timestamp
    for person_id in list(open_visits):
        close(person_id)
    return result


def compute_analytics(
    branch_id: int,
    events: List[Event],
    date_from: date,
    date_to: date,
    tz: ZoneInfo,
    prev_visits: int,
    now: Optional[float] = None,
) -> AnalyticsResponse:
    """`events` must be time-ordered and cover [date_from, date_to + MAX_DWELL_SEC) so dwell of late visits is known."""
    now = time.time() if now is None else now
    start_ts = local_midnight_ts(date_from, tz)
    end_ts = local_midnight_ts(date_to + timedelta(days=1), tz)

    days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    today = datetime.fromtimestamp(now, tz).date()
    # Averages only over days that have already started (a "this month" range shouldn't be diluted by future days).
    elapsed_days = [d for d in days if d <= today] or days[:1]

    per_day = {d: 0 for d in days}
    per_hour = [0] * 24
    per_weekday = [0] * 7
    returning = 0

    for ev in events:
        if not (start_ts <= ev.timestamp < end_ts) or ev.action != "ENTER":
            continue
        if ev.returning:
            returning += 1
            continue
        local = datetime.fromtimestamp(ev.timestamp, tz)
        per_day[local.date()] = per_day.get(local.date(), 0) + 1
        per_hour[local.hour] += 1
        per_weekday[local.weekday()] += 1

    visits = sum(per_day.values())
    weekday_occurrences = [0] * 7
    for d in elapsed_days:
        weekday_occurrences[d.weekday()] += 1

    dwells_min = [dwell / 60 for start, dwell in visit_dwells(events) if start_ts <= start < end_ts]
    dwell = [
        DwellBucket(
            label=label,
            min_minutes=lo,
            max_minutes=hi,
            count=sum(1 for m in dwells_min if m >= lo and (hi is None or m < hi)),
        )
        for label, lo, hi in DWELL_BUCKETS
    ]

    by_day = [DayPoint(date=d, visits=per_day[d]) for d in days]
    busiest = max(by_day, key=lambda p: p.visits) if visits else None

    summary = AnalyticsSummary(
        visits=visits,
        prev_visits=prev_visits,
        avg_per_day=round(visits / len(elapsed_days), 1),
        returning=returning,
        avg_dwell_min=round(statistics.fmean(dwells_min), 1) if dwells_min else None,
        median_dwell_min=round(statistics.median(dwells_min), 1) if dwells_min else None,
        peak_hour=per_hour.index(max(per_hour)) if visits else None,
        busiest_day=busiest,
    )

    return AnalyticsResponse(
        branch_id=branch_id,
        date_from=date_from,
        date_to=date_to,
        tz=str(tz.key),
        days=len(days),
        summary=summary,
        by_day=by_day,
        by_hour=[
            HourPoint(hour=h, visits=per_hour[h], avg=round(per_hour[h] / len(elapsed_days), 2)) for h in range(24)
        ],
        by_weekday=[
            WeekdayPoint(
                weekday=w,
                visits=per_weekday[w],
                avg=round(per_weekday[w] / weekday_occurrences[w], 1) if weekday_occurrences[w] else 0.0,
            )
            for w in range(7)
        ],
        dwell=dwell,
    )


def compute_live(branch_id: int, events: List[Event], tz: ZoneInfo, now: Optional[float] = None) -> LiveStats:
    """`events` must be time-ordered and cover at least the last LIVE_WINDOW_SEC and today."""
    now = time.time() if now is None else now
    today_start = local_midnight_ts(datetime.fromtimestamp(now, tz).date(), tz)

    last_action = {}
    for ev in events:
        if ev.timestamp >= now - LIVE_WINDOW_SEC:
            last_action[ev.person_id] = ev.action

    return LiveStats(
        branch_id=branch_id,
        inside_now=sum(1 for action in last_action.values() if action == "ENTER"),
        visits_today=sum(1 for ev in events if ev.timestamp >= today_start and is_visit(ev)),
        last_event_at=events[-1].timestamp if events else None,
    )


class AnalyticsService:
    def __init__(self, repository: EventRepository):
        self.repository = repository

    async def get_analytics(self, branch_id: int, date_from: date, date_to: date, tz: ZoneInfo) -> AnalyticsResponse:
        start_ts = local_midnight_ts(date_from, tz)
        end_ts = local_midnight_ts(date_to + timedelta(days=1), tz)
        events = await self.repository.get_in_range(branch_id, start_ts, end_ts + MAX_DWELL_SEC)

        # Previous period of the same length, cut at the same point in time when the current one is still
        # running (today until 14:00 is compared with yesterday until 14:00, not with the whole of yesterday).
        span = (date_to - date_from).days + 1
        prev_start = local_midnight_ts(date_from - timedelta(days=span), tz)
        elapsed = max(0.0, min(time.time(), end_ts) - start_ts)
        prev_end = min(start_ts, prev_start + elapsed)
        prev_visits = await self.repository.count_visits(branch_id, prev_start, prev_end)

        return compute_analytics(branch_id, events, date_from, date_to, tz, prev_visits)

    async def get_live(self, branch_id: int, tz: ZoneInfo) -> LiveStats:
        now = time.time()
        today_start = local_midnight_ts(datetime.fromtimestamp(now, tz).date(), tz)
        events = await self.repository.get_in_range(branch_id, min(today_start, now - LIVE_WINDOW_SEC), now + 60)
        return compute_live(branch_id, events, tz, now)
