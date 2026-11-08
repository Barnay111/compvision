import re
from datetime import date
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_time(v: str) -> str:
    if not _TIME_RE.match(v):
        raise ValueError("send_time must be HH:MM")
    return v


def _check_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone: {v}")
    return v


class RecipientBase(BaseModel):
    branch_id: int
    name: str = Field(min_length=1, max_length=100)
    telegram_chat_id: str = Field(min_length=1, max_length=64, pattern=r"^-?\d+$|^@\w{5,}$")
    send_time: str = "09:00"
    tz: str = "Asia/Qyzylorda"
    enabled: bool = True

    @field_validator("send_time")
    @classmethod
    def valid_time(cls, v):
        return _check_time(v)

    @field_validator("tz")
    @classmethod
    def valid_tz(cls, v):
        return _check_tz(v)


class RecipientCreate(RecipientBase):
    pass


class RecipientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    send_time: Optional[str] = None
    tz: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("send_time")
    @classmethod
    def valid_time(cls, v):
        return v if v is None else _check_time(v)

    @field_validator("tz")
    @classmethod
    def valid_tz(cls, v):
        return v if v is None else _check_tz(v)


class Recipient(RecipientBase):
    id: int
    last_sent_date: Optional[date] = None

    class Config:
        from_attributes = True


class TelegramChat(BaseModel):
    chat_id: str
    title: str
    type: str


class TelegramStatus(BaseModel):
    configured: bool
    bot_username: Optional[str] = None
    error: Optional[str] = None


class ReportPreview(BaseModel):
    branch_id: int
    date: date
    text: str


class SendResult(BaseModel):
    ok: bool
    detail: str = ""


class TelegramChats(BaseModel):
    chats: List[TelegramChat]
