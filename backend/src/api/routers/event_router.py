from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from src.models.event import Event, EventCreate, IdentifyRequest, IdentifyResult
from src.services.event_service import EventService
from src.repositories.employee_repo import PostgresEmployeeRepository
from src.repositories.event_repo import PostgresEventRepository
from src.core.database import get_db

router = APIRouter(prefix="/events", tags=["events"])

def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    repo = PostgresEventRepository(session=db)
    return EventService(repository=repo)

async def ensure_employee(employee_id: int | None, db: AsyncSession):
    if employee_id is not None and await PostgresEmployeeRepository(session=db).get_by_id(employee_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Employee {employee_id} not found: the faces/<employee_id>_<name> folder must use an existing id",
        )

@router.post("/", response_model=Event)
async def create_event(
    event: EventCreate,
    service: EventService = Depends(get_event_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        await ensure_employee(event.employee_id, db)
    except HTTPException as e:
        # Never lose a camera event over a misnamed faces folder: keep it, just without the employee link.
        print(f"Warning: {e.detail}; event stored without employee_id")
        event = event.model_copy(update={"employee_id": None})
    return await service.register_event(event)

@router.post("/identify", response_model=IdentifyResult)
async def identify_person(
    request: IdentifyRequest,
    service: EventService = Depends(get_event_service),
    db: AsyncSession = Depends(get_db),
):
    await ensure_employee(request.employee_id, db)
    return IdentifyResult(updated=await service.identify(request))

@router.get("/branch/{branch_id}", response_model=List[Event])
async def list_branch_events(
    branch_id: int,
    limit: int | None = Query(None, ge=1, le=5000, description="Return only the N most recent events"),
    service: EventService = Depends(get_event_service),
):
    return await service.get_branch_events(branch_id, limit)
