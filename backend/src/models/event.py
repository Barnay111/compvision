from pydantic import BaseModel
from typing import Literal

class EventBase(BaseModel):
    branch_id: int
    person_id: int
    action: str
    timestamp: float
    returning: bool = False  # re-entry of a visitor recognised by ReID

class EventCreate(EventBase):
    action: Literal["ENTER", "EXIT"]

class Event(EventBase):
    id: int

    class Config:
        from_attributes = True
