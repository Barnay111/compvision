from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from src.models.event import Event, EventCreate
from src.models.db_models import DBEvent
from typing import List

class EventRepository(ABC):
    @abstractmethod
    async def create(self, event: EventCreate) -> Event:
        pass

    @abstractmethod
    async def get_by_branch(self, branch_id: int, limit: int | None = None) -> List[Event]:
        pass

    @abstractmethod
    async def get_in_range(self, branch_id: int, ts_from: float, ts_to: float) -> List[Event]:
        pass

    @abstractmethod
    async def count_visits(self, branch_id: int, ts_from: float, ts_to: float) -> int:
        pass

class PostgresEventRepository(EventRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event: EventCreate) -> Event:
        db_event = DBEvent(**event.model_dump())
        self.session.add(db_event)
        await self.session.commit()
        await self.session.refresh(db_event)
        return Event.model_validate(db_event)

    async def get_by_branch(self, branch_id: int, limit: int | None = None) -> List[Event]:
        query = (
            select(DBEvent)
            .where(DBEvent.branch_id == branch_id)
            .order_by(DBEvent.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [Event.model_validate(db_ev) for db_ev in result.scalars().all()]

    async def get_in_range(self, branch_id: int, ts_from: float, ts_to: float) -> List[Event]:
        query = (
            select(DBEvent)
            .where(DBEvent.branch_id == branch_id, DBEvent.timestamp >= ts_from, DBEvent.timestamp < ts_to)
            .order_by(DBEvent.timestamp)
        )
        result = await self.session.execute(query)
        return [Event.model_validate(db_ev) for db_ev in result.scalars().all()]

    async def count_visits(self, branch_id: int, ts_from: float, ts_to: float) -> int:
        """A visit is a first ENTER; re-entries recognised by ReID (returning=True) are not new visits."""
        query = select(func.count()).where(
            DBEvent.branch_id == branch_id,
            DBEvent.action == "ENTER",
            DBEvent.returning.is_(False),
            DBEvent.timestamp >= ts_from,
            DBEvent.timestamp < ts_to,
        )
        return (await self.session.execute(query)).scalar_one()
