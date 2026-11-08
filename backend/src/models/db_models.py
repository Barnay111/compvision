from sqlalchemy import Boolean, Column, Date, Float, Index, Integer, String
from src.core.database import Base

class DBEmployee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, index=True)
    last_name = Column(String, index=True)
    branch_id = Column(Integer, index=True)
    role = Column(String)

class DBEvent(Base):
    __tablename__ = "cv_events"

    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, index=True)
    person_id = Column(Integer, index=True)
    action = Column(String) # ENTER or EXIT
    timestamp = Column(Float)
    returning = Column("is_returning", Boolean, nullable=False, default=False, server_default="false")

    __table_args__ = (Index("ix_cv_events_branch_ts", "branch_id", "timestamp"),)


class DBReportRecipient(Base):
    """Someone who gets the daily visitor report in Telegram."""
    __tablename__ = "report_recipients"

    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, index=True, nullable=False)
    name = Column(String, nullable=False)
    telegram_chat_id = Column(String, nullable=False)
    send_time = Column(String, nullable=False, default="09:00")   # local "HH:MM"
    tz = Column(String, nullable=False, default="Asia/Qyzylorda")
    enabled = Column(Boolean, nullable=False, default=True)
    last_sent_date = Column(Date, nullable=True)                  # local date the last daily report went out
