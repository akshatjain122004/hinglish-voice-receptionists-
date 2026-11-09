"""Tool functions exposed to the LLM, with JSON schemas for function-calling.

Every tool validates its own input and returns a small JSON-serialisable
dict. On failure it returns ``{"ok": False, "error": "<reason>"}`` instead
of raising — the agent loop must never see a raw exception from a tool.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app import booking, rag, timeparse

# Tuned against real scores from the multilingual embedder (see
# tests/integration/test_rag_retrieval.py, re-measured after app.rag.ingest
# switched to indexing each FAQ by both its question alone and its
# question+answer): most in-scope FAQ questions score 0.57-0.9, but an
# adversarial one close to a real FAQ (e.g. "share market mein kya chal raha
# hai" vs. the "second opinion" FAQ) can reach ~0.56 while still being out of
# scope. 0.565 is the lowest threshold that rejects every out-of-scope case
# in that test; a couple of genuinely in-scope but oddly-phrased queries
# fall below it too (found: false instead of an answer) — acceptable given
# the project's "never invent or mismatch a fact" rule.
FAQ_SCORE_THRESHOLD = 0.565


class CheckSlotsInput(BaseModel):
    date: str
    service: str
    part_of_day: Literal["morning", "afternoon", "evening", "night"] | None = None


class BookAppointmentInput(BaseModel):
    name: str
    phone: str
    service: str
    start: str


class CancelAppointmentInput(BaseModel):
    phone: str


class RescheduleAppointmentInput(BaseModel):
    phone: str
    new_start: str


class AnswerFaqInput(BaseModel):
    question: str


class TransferToHumanInput(BaseModel):
    reason: str


def _error(exc: Exception) -> dict:
    return {"ok": False, "error": str(exc)}


def _appointment_dict(appointment: booking.db.Appointment) -> dict:
    return {
        "id": appointment.id,
        "patient_name": appointment.patient_name,
        "phone": appointment.phone,
        "service": appointment.service,
        "start": appointment.start.isoformat(),
        "end": appointment.end.isoformat(),
        "status": appointment.status,
    }


def check_slots(
    *,
    date: str,
    service: str,
    part_of_day: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(booking.IST)
    try:
        args = CheckSlotsInput(date=date, service=service, part_of_day=part_of_day)
        day = timeparse.parse_date(args.date, now=now)
        slots = booking.get_free_slots(day, args.service, args.part_of_day)
    except (ValidationError, timeparse.TimeParseError, booking.InvalidBookingError) as exc:
        return _error(exc)
    return {"ok": True, "slots": [slot.isoformat() for slot in slots]}


def book_appointment(
    *,
    name: str,
    phone: str,
    service: str,
    start: str,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(booking.IST)
    try:
        args = BookAppointmentInput(name=name, phone=phone, service=service, start=start)
        when = timeparse.parse(args.start, now=now)
        appointment = booking.book(args.phone, args.name, args.service, when, now=now)
    except (
        ValidationError,
        timeparse.TimeParseError,
        booking.InvalidBookingError,
        booking.SlotTakenError,
    ) as exc:
        return _error(exc)
    return {"ok": True, "appointment": _appointment_dict(appointment)}


def cancel_appointment(*, phone: str) -> dict:
    try:
        args = CancelAppointmentInput(phone=phone)
        booking.cancel(args.phone)
    except (ValidationError, booking.InvalidBookingError) as exc:
        return _error(exc)
    return {"ok": True}


def reschedule_appointment(
    *,
    phone: str,
    new_start: str,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(booking.IST)
    try:
        args = RescheduleAppointmentInput(phone=phone, new_start=new_start)
        upcoming = booking.find_by_phone(args.phone)
        if not upcoming:
            raise booking.InvalidBookingError("no confirmed appointment found")
        when = timeparse.parse(args.new_start, now=now)
        appointment = booking.reschedule(upcoming[0].id, when, now=now)
    except (
        ValidationError,
        timeparse.TimeParseError,
        booking.InvalidBookingError,
        booking.SlotTakenError,
    ) as exc:
        return _error(exc)
    return {"ok": True, "appointment": _appointment_dict(appointment)}


def answer_faq(*, question: str, phone: str | None = None) -> dict:
    try:
        args = AnswerFaqInput(question=question)
    except ValidationError as exc:
        return _error(exc)
    results = rag.retrieve(args.question, k=1)
    if not results or results[0]["score"] < FAQ_SCORE_THRESHOLD:
        rag.log_unanswered(args.question, phone)
        return {"ok": True, "found": False}
    return {"ok": True, "found": True, "answer": results[0]["answer"]}


def transfer_to_human(*, reason: str) -> dict:
    try:
        args = TransferToHumanInput(reason=reason)
    except ValidationError as exc:
        return _error(exc)
    return {"ok": True, "transferred": True, "reason": args.reason}


REGISTRY: dict[str, Callable[..., dict]] = {
    "check_slots": check_slots,
    "book_appointment": book_appointment,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment,
    "answer_faq": answer_faq,
    "transfer_to_human": transfer_to_human,
}


# The caller's phone number is channel identity (Twilio caller ID, WhatsApp
# sender, etc.) — the LLM is never asked for it and never supplies it; the
# agent injects it here instead. See app.agent.Agent(caller_phone=...).
PHONE_INJECTED_TOOLS = {
    "book_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "answer_faq",
}


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    now: datetime | None = None,
    caller_phone: str | None = None,
) -> dict:
    handler = REGISTRY.get(name)
    if handler is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    if name in PHONE_INJECTED_TOOLS and caller_phone is not None:
        arguments = {**arguments, "phone": caller_phone}
    try:
        if handler is cancel_appointment or handler is answer_faq or handler is transfer_to_human:
            return handler(**arguments)
        return handler(**arguments, now=now)
    except TypeError as exc:
        return {"ok": False, "error": f"invalid arguments for {name}: {exc}"}


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "check_slots",
            "description": "Check free appointment slots for a service on a given day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The day the caller asked about, in their own words, e.g. 'kal' or 'Friday'.",
                    },
                    "service": {
                        "type": "string",
                        "enum": booking.service_names(),
                        "description": "The exact service identifier.",
                    },
                    "part_of_day": {
                        "type": "string",
                        "enum": ["morning", "afternoon", "evening", "night"],
                        "description": "Optional time-of-day filter.",
                    },
                },
                "required": ["date", "service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment after the caller has confirmed the details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "service": {"type": "string", "enum": booking.service_names()},
                    "start": {
                        "type": "string",
                        "description": "The confirmed day and time, in the caller's own words.",
                    },
                },
                "required": ["name", "service", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel the caller's upcoming appointment.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Move the caller's upcoming appointment to a new day/time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_start": {
                        "type": "string",
                        "description": "The new confirmed day and time, in the caller's own words.",
                    },
                },
                "required": ["new_start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer_faq",
            "description": "Look up an answer to a clinic FAQ (fees, timings, parking, etc.).",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": "Hand the call over to clinic staff when the bot can't help.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]
