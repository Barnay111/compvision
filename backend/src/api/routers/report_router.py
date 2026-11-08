from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.models.report import (
    Recipient,
    RecipientCreate,
    RecipientUpdate,
    ReportPreview,
    SendResult,
    TelegramChats,
    TelegramStatus,
)
from src.services import telegram
from src.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


def get_report_service(db: AsyncSession = Depends(get_db)) -> ReportService:
    return ReportService(session=db)


def _not_found(e: LookupError):
    raise HTTPException(status_code=404, detail=str(e))


@router.get("/telegram/status", response_model=TelegramStatus)
async def telegram_status():
    if not settings.TELEGRAM_BOT_TOKEN:
        return TelegramStatus(configured=False, error="TELEGRAM_BOT_TOKEN is not set in backend/.env")
    try:
        me = await telegram.get_me()
    except telegram.TelegramError as e:
        return TelegramStatus(configured=False, error=str(e))
    return TelegramStatus(configured=True, bot_username=me.get("username"))


@router.get("/telegram/chats", response_model=TelegramChats)
async def telegram_chats():
    """Chats that recently messaged the bot: ask the owner to press /start, then pick their chat here."""
    try:
        return TelegramChats(chats=await telegram.recent_chats())
    except telegram.TelegramError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/recipients", response_model=List[Recipient])
async def list_recipients(branch_id: Optional[int] = None, service: ReportService = Depends(get_report_service)):
    return await service.list(branch_id)


@router.post("/recipients", response_model=Recipient, status_code=201)
async def create_recipient(data: RecipientCreate, service: ReportService = Depends(get_report_service)):
    return await service.create(data)


@router.patch("/recipients/{recipient_id}", response_model=Recipient)
async def update_recipient(recipient_id: int, data: RecipientUpdate, service: ReportService = Depends(get_report_service)):
    try:
        return await service.update(recipient_id, data)
    except LookupError as e:
        _not_found(e)


@router.delete("/recipients/{recipient_id}", status_code=204)
async def delete_recipient(recipient_id: int, service: ReportService = Depends(get_report_service)):
    try:
        await service.delete(recipient_id)
    except LookupError as e:
        _not_found(e)


async def _send(action) -> SendResult:
    try:
        await action
    except LookupError as e:
        _not_found(e)
    except telegram.TelegramError as e:
        return SendResult(ok=False, detail=str(e))
    return SendResult(ok=True)


@router.post("/recipients/{recipient_id}/test", response_model=SendResult)
async def send_test(recipient_id: int, service: ReportService = Depends(get_report_service)):
    return await _send(service.send_test(recipient_id))


@router.post("/recipients/{recipient_id}/send", response_model=SendResult)
async def send_now(recipient_id: int, service: ReportService = Depends(get_report_service)):
    """Sends yesterday's report right away (doesn't affect the daily schedule)."""
    return await _send(service.send_report_now(recipient_id))


@router.get("/preview/{branch_id}", response_model=ReportPreview)
async def preview(
    branch_id: int,
    day: Optional[date] = Query(None, description="Report day; yesterday by default"),
    tz: str = Query("Asia/Qyzylorda"),
    service: ReportService = Depends(get_report_service),
):
    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown time zone: {tz}")
    day = day or (datetime.now(zone).date() - timedelta(days=1))
    return ReportPreview(branch_id=branch_id, date=day, text=await service.preview(branch_id, day, tz))
