from src.models.event import Event, EventCreate, IdentifyRequest
from src.repositories.event_repo import EventRepository
from typing import List

class EventService:
    def __init__(self, repository: EventRepository):
        self.repository = repository

    async def register_event(self, event_data: EventCreate) -> Event:
        return await self.repository.create(event_data)

    async def get_branch_events(self, branch_id: int, limit: int | None = None) -> List[Event]:
        return await self.repository.get_by_branch(branch_id, limit)

    async def identify(self, request: IdentifyRequest) -> int:
        """The face is often seen only after the person crossed the line, so earlier events are linked here."""
        return await self.repository.link_employee(request.branch_id, request.person_id, request.employee_id)
