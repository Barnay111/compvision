from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class DayPoint(BaseModel):
    date: date
    visits: int


class HourPoint(BaseModel):
    hour: int          # 0..23, local time
    visits: int        # total over the period
    avg: float         # average per day


class WeekdayPoint(BaseModel):
    weekday: int       # 0 = Monday .. 6 = Sunday
    visits: int
    avg: float         # average per occurrence of this weekday in the period


class DwellBucket(BaseModel):
    label: str
    min_minutes: float
    max_minutes: Optional[float]
    count: int


class AnalyticsSummary(BaseModel):
    visits: int
    prev_visits: int                 # same-length period right before this one
    avg_per_day: float
    returning: int                   # re-entries after a short exit (not counted as visits)
    avg_dwell_min: Optional[float]
    median_dwell_min: Optional[float]
    peak_hour: Optional[int]
    busiest_day: Optional[DayPoint]


class AnalyticsResponse(BaseModel):
    branch_id: int
    date_from: date
    date_to: date
    tz: str
    days: int
    summary: AnalyticsSummary
    by_day: List[DayPoint]
    by_hour: List[HourPoint]
    by_weekday: List[WeekdayPoint]
    dwell: List[DwellBucket]


class LiveStats(BaseModel):
    branch_id: int
    inside_now: int
    visits_today: int
    last_event_at: Optional[float]
