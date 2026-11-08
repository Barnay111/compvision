from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from src.models.event import Event, EventCreate
from src.services.event_service import EventService
from src.repositories.event_repo import PostgresEventRepository
from src.core.database import get_db

router = APIRouter(prefix="/events", tags=["events"])

def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    repo = PostgresEventRepository(session=db)
    return EventService(repository=repo)

@router.post("/", response_model=Event)
async def create_event(event: EventCreate, service: EventService = Depends(get_event_service)):
    return await service.register_event(event)

@router.get("/branch/{branch_id}", response_model=List[Event])
async def list_branch_events(
    branch_id: int,
    limit: int | None = Query(None, ge=1, le=5000, description="Return only the N most recent events"),
    service: EventService = Depends(get_event_service),
):
    return await service.get_branch_events(branch_id, limit)
