from pydantic import BaseModel
from typing import Literal, Optional

class EventBase(BaseModel):
    branch_id: int
    person_id: int
    action: str
    timestamp: float
    returning: bool = False  # re-entry of a visitor recognised by ReID
    employee_id: Optional[int] = None  # set when the person was recognised as an employee by face

class EventCreate(EventBase):
    action: Literal["ENTER", "EXIT"]

class Event(EventBase):
    id: int

    class Config:
        from_attributes = True


class IdentifyRequest(BaseModel):
    """cv_module recognised an employee's face: all events of this person belong to that employee."""
    branch_id: int
    person_id: int
    employee_id: int


class IdentifyResult(BaseModel):
    updated: int  # events that were linked to the employee by this request
