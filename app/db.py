"""SQLite models and session management."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, Session, SQLModel, create_engine

DEFAULT_DATABASE_URL = "sqlite:///data/app.db"

engine = create_engine(DEFAULT_DATABASE_URL, connect_args={"check_same_thread": False})


class Appointment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    patient_name: str
    phone: str
    service: str
    start: datetime
    end: datetime
    status: str = "confirmed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CallLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    caller: str
    started_at: datetime
    ended_at: datetime | None = None
    transcript: str = ""
    outcome: str = ""


class UnansweredQuestion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question: str
    caller_phone: str | None = None
    asked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CallbackRequest(SQLModel, table=True):
    """A caller asking for a human (BUILD_PLAN 5.9) — a real transfer only
    comes in Phase 8 (Twilio); until then, this is the promise that a staff
    member calls back. `name` is nullable: the transfer_to_human tool schema
    never asks the LLM for it, so it's always None from that path for now."""

    id: int | None = Field(default=None, primary_key=True)
    phone: str
    name: str | None = None
    message: str | None = None
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "pending"


def create_all(target_engine=None) -> None:
    SQLModel.metadata.create_all(target_engine or engine)


def get_session() -> Session:
    return Session(engine)
