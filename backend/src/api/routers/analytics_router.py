from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.models.analytics import AnalyticsResponse, LiveStats
from src.repositories.event_repo import PostgresEventRepository
from src.services.analytics_service import MAX_RANGE_DAYS, AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_analytics_service(db: AsyncSession = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(repository=PostgresEventRepository(session=db))


def parse_tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=400, detail=f"Unknown time zone: {tz}")


@router.get("/branch/{branch_id}", response_model=AnalyticsResponse)
async def branch_analytics(
    branch_id: int,
    date_from: date = Query(..., description="First day of the period (local date, inclusive)"),
    date_to: date = Query(..., description="Last day of the period (local date, inclusive)"),
    tz: str = Query("UTC", description="IANA time zone used to split days and hours, e.g. Asia/Almaty"),
    service: AnalyticsService = Depends(get_analytics_service),
):
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must not be earlier than date_from")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Period is limited to {MAX_RANGE_DAYS} days")
    return await service.get_analytics(branch_id, date_from, date_to, parse_tz(tz))


@router.get("/branch/{branch_id}/live", response_model=LiveStats)
async def branch_live(
    branch_id: int,
    tz: str = Query("UTC"),
    service: AnalyticsService = Depends(get_analytics_service),
):
    return await service.get_live(branch_id, parse_tz(tz))
