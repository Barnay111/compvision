from typing import List
from src.models.employee import Employee, EmployeeCreate
from src.repositories.employee_repo import EmployeeRepository

class EmployeeService:
    def __init__(self, repository: EmployeeRepository):
        self.repository = repository

    async def get_employee(self, employee_id: int) -> Employee:
        employee = await self.repository.get_by_id(employee_id)
        if not employee:
            raise ValueError(f"Employee with ID {employee_id} not found")
        return employee

    async def add_employee(self, employee_data: EmployeeCreate) -> Employee:
        # Here we could add business logic, e.g. checking if branch exists
        return await self.repository.create(employee_data)

    async def get_all_employees(self) -> List[Employee]:
        return await self.repository.get_all()
