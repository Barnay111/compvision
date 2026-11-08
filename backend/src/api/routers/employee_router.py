from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from src.models.employee import Employee, EmployeeCreate
from src.services.employee_service import EmployeeService
from src.repositories.employee_repo import PostgresEmployeeRepository
from src.core.database import get_db

router = APIRouter(prefix="/employees", tags=["employees"])

# Dependency Injection setup
def get_employee_service(db: AsyncSession = Depends(get_db)) -> EmployeeService:
    repo = PostgresEmployeeRepository(session=db)
    return EmployeeService(repository=repo)

@router.post("/", response_model=Employee)
async def create_employee(employee: EmployeeCreate, service: EmployeeService = Depends(get_employee_service)):
    try:
        return await service.add_employee(employee)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[Employee])
async def list_employees(service: EmployeeService = Depends(get_employee_service)):
    return await service.get_all_employees()

@router.get("/{employee_id}", response_model=Employee)
async def get_employee(employee_id: int, service: EmployeeService = Depends(get_employee_service)):
    try:
        return await service.get_employee(employee_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
