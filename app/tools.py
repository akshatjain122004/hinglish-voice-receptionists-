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

from app import booking, db, rag, timeparse

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
    phone: str
    message: str | None = None


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


_SUGGESTED_SLOTS_LIMIT = 3


def _suggested_slots(slots: list[datetime], limit: int = _SUGGESTED_SLOTS_LIMIT) -> list[datetime]:
    """Up to `limit` slots, evenly spread across `slots` rather than just
    the first few (BUILD_PLAN 5.10b) - so a reply offering these covers the
    available window, not three slots bunched at the start of the day."""
    if len(slots) <= limit:
        return slots
    step = (len(slots) - 1) / (limit - 1)
    indices = sorted({round(i * step) for i in range(limit)})
    return [slots[i] for i in indices]


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
    return {
        "ok": True,
        # `slots` stays the full list (the no-hallucination eval check and
        # must_not_hallucinate rely on every real slot being present here);
        # `suggested`/`total` are what the prompt tells the LLM to actually
        # read aloud, so a reply doesn't run past the 2-sentence limit
        # listing 8 slots (BUILD_PLAN 5.10b, found live during 5.10's
        # eval-debt pass - code_switch_001's failure was exactly this).
        "slots": [slot.isoformat() for slot in slots],
        "suggested": [slot.isoformat() for slot in _suggested_slots(slots)],
        "total": len(slots),
    }


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


def transfer_to_human(*, reason: str, phone: str, message: str | None = None) -> dict:
    """Logs a `CallbackRequest` and promises a callback during clinic hours.

    `phone` comes from `call_tool`'s `PHONE_INJECTED_TOOLS`, never the LLM
    (same pattern as `book_appointment`). A real transfer only comes in
    Phase 8 (Twilio); for now this always succeeds — there's no failure mode
    to log a callback request."""
    try:
        args = TransferToHumanInput(reason=reason, phone=phone, message=message)
    except ValidationError as exc:
        return _error(exc)
    with db.get_session() as session:
        session.add(db.CallbackRequest(phone=args.phone, message=args.message, reason=args.reason))
        session.commit()
    hours = booking.clinic_hours()
    return {
        "ok": True,
        "callback_requested": True,
        "callback_hours_open": hours["open"],
        "callback_hours_close": hours["close"],
    }


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
    "transfer_to_human",
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
            "description": (
                "Ask clinic staff to call the caller back, since a real transfer isn't "
                "available yet. Phone is already known from the call; never ask for it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the caller needs a human, e.g. 'wants to speak to a person'.",
                    },
                    "message": {
                        "type": "string",
                        "description": "A short note for staff on what the caller needs, if they gave one.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
