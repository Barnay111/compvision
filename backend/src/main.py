import asyncio

from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from src.core.config import settings
from src.core.database import engine, Base
from src.models.db_models import DBEmployee, DBEvent, DBReportRecipient
from src.api.routers import analytics_router, employee_router, event_router, report_router
from src.services.report_service import report_scheduler

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for AI Restaurant Monitoring System",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        # Create all tables in the database
        await conn.run_sync(Base.metadata.create_all)
        # create_all doesn't alter existing tables: bring older cv_events tables up to date.
        await conn.execute(text(
            "ALTER TABLE cv_events ADD COLUMN IF NOT EXISTS is_returning BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_cv_events_branch_ts ON cv_events (branch_id, timestamp)"
        ))
        await conn.execute(text("ALTER TABLE cv_events ADD COLUMN IF NOT EXISTS employee_id INTEGER"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_cv_events_employee_id ON cv_events (employee_id)"
        ))
        # person_id outgrew INTEGER when cv_module started counting it from its start time in ms.
        await conn.execute(text(
            "DO $$ BEGIN "
            "IF (SELECT data_type FROM information_schema.columns "
            "    WHERE table_name = 'cv_events' AND column_name = 'person_id') = 'integer' THEN "
            "  ALTER TABLE cv_events ALTER COLUMN person_id TYPE BIGINT; "
            "END IF; END $$"
        ))
    if settings.REPORTS_ENABLED:
        app.state.report_task = asyncio.create_task(report_scheduler())


@app.on_event("shutdown")
async def on_shutdown():
    task = getattr(app.state, "report_task", None)
    if task:
        task.cancel()

app.include_router(employee_router.router)
app.include_router(event_router.router)
app.include_router(analytics_router.router)
app.include_router(report_router.router)

@app.get("/")
async def root():
    return {"message": "Welcome to CompVision Restaurant AI API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.API_HOST, port=settings.API_PORT)
