from abc import ABC, abstractmethod
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from src.models.employee import Employee, EmployeeCreate
from src.models.db_models import DBEmployee

class EmployeeRepository(ABC):
    @abstractmethod
    async def get_by_id(self, employee_id: int) -> Optional[Employee]:
        pass

    @abstractmethod
    async def create(self, employee: EmployeeCreate) -> Employee:
        pass

    @abstractmethod
    async def get_all(self) -> List[Employee]:
        pass

class InMemoryEmployeeRepository(EmployeeRepository):
    # Mock implementation for MVP/testing purposes
    def __init__(self):
        self.employees = {}
        self.current_id = 1

    async def get_by_id(self, employee_id: int) -> Optional[Employee]:
        return self.employees.get(employee_id)

    async def create(self, employee: EmployeeCreate) -> Employee:
        new_employee = Employee(id=self.current_id, **employee.model_dump())
        self.employees[self.current_id] = new_employee
        self.current_id += 1
        return new_employee

    async def get_all(self) -> List[Employee]:
        return list(self.employees.values())

class PostgresEmployeeRepository(EmployeeRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, employee_id: int) -> Optional[Employee]:
        result = await self.session.execute(select(DBEmployee).where(DBEmployee.id == employee_id))
        db_employee = result.scalars().first()
        if db_employee:
            return Employee.model_validate(db_employee)
        return None

    async def create(self, employee: EmployeeCreate) -> Employee:
        db_employee = DBEmployee(**employee.model_dump())
        self.session.add(db_employee)
        await self.session.commit()
        await self.session.refresh(db_employee)
        return Employee.model_validate(db_employee)

    async def get_all(self) -> List[Employee]:
        result = await self.session.execute(select(DBEmployee))
        db_employees = result.scalars().all()
        return [Employee.model_validate(db_emp) for db_emp in db_employees]
