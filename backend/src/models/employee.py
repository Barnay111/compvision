from pydantic import BaseModel
from typing import Optional

class EmployeeBase(BaseModel):
    first_name: str
    last_name: str
    branch_id: int
    role: str

class EmployeeCreate(EmployeeBase):
    pass

class Employee(EmployeeBase):
    id: int

    class Config:
        from_attributes = True
