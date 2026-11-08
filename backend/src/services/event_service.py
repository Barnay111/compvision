from src.models.event import Event, EventCreate
from src.repositories.event_repo import EventRepository
from typing import List

class EventService:
    def __init__(self, repository: EventRepository):
        self.repository = repository

    async def register_event(self, event_data: EventCreate) -> Event:
        # In the future, this is where we'd match the person_id to a real employee
        # and create attendance records (clock in/clock out).
        # For now, just save the raw event.
        return await self.repository.create(event_data)

    async def get_branch_events(self, branch_id: int, limit: int | None = None) -> List[Event]:
        return await self.repository.get_by_branch(branch_id, limit)
