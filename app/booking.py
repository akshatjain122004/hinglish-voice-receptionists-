"""Pure-Python booking and slot logic. No AI here — the agent only calls these
functions and must never invent a slot, price or timing itself.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlmodel import select

from app import db

IST = ZoneInfo("Asia/Kolkata")

CLINIC_PATH = Path(__file__).resolve().parent.parent / "data" / "clinic.yaml"

PART_OF_DAY = {
    "morning": (time(0, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(16, 0)),
    "evening": (time(16, 0), time(20, 0)),
    "night": (time(20, 0), time(23, 59, 59)),
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SlotTakenError(Exception):
    """Raised when a slot was booked between the availability check and the booking."""


class InvalidBookingError(ValueError):
    """Raised for an unknown service, a bad phone number, or an out-of-range date."""


def _load_clinic() -> dict:
    return yaml.safe_load(CLINIC_PATH.read_text())


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def normalize_phone(raw: str) -> str:
    """Normalise an Indian phone number to E.164 (+91XXXXXXXXXX)."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+91") and len(digits) == 13:
        return digits
    if digits.startswith("91") and len(digits) == 12:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 11:
        return "+91" + digits[1:]
    if len(digits) == 10:
        return "+91" + digits
    raise InvalidBookingError(f"invalid phone number: {raw}")


def service_names() -> list[str]:
    """Valid service identifiers, e.g. for a tool schema enum."""
    return sorted(_load_clinic()["services"])


def clinic_hours() -> dict[str, str]:
    """The clinic's open/close times (e.g. `{"open": "10:00", "close":
    "20:00"}`), for a tool result that needs to state them — CLAUDE.md's
    "business rules belong in code, never the prompt" rule means a reply
    promising a callback "during clinic hours" (BUILD_PLAN 5.9) must get the
    actual hours from here, not a value baked into app/prompts.py."""
    return _load_clinic()["hours"]


def _service_duration(clinic: dict, service: str) -> timedelta:
    if service not in clinic["services"]:
        raise InvalidBookingError(f"unknown service: {service}")
    return timedelta(minutes=clinic["services"][service]["duration_minutes"])


def _in_part_of_day(t: time, part_of_day: str) -> bool:
    if part_of_day not in PART_OF_DAY:
        raise InvalidBookingError(f"unknown part_of_day: {part_of_day}")
    start, end = PART_OF_DAY[part_of_day]
    return start <= t < end


def get_free_slots(day: date, service: str, part_of_day: str | None = None) -> list[datetime]:
    clinic = _load_clinic()
    duration = _service_duration(clinic, service)

    if WEEKDAYS[day.weekday()] == clinic["weekly_off"]:
        return []

    slot_step = timedelta(minutes=clinic["slot_minutes"])
    day_open = datetime.combine(day, _parse_time(clinic["hours"]["open"]), tzinfo=IST)
    day_close = datetime.combine(day, _parse_time(clinic["hours"]["close"]), tzinfo=IST)
    lunch_start = datetime.combine(day, _parse_time(clinic["lunch_break"]["start"]), tzinfo=IST)
    lunch_end = datetime.combine(day, _parse_time(clinic["lunch_break"]["end"]), tzinfo=IST)

    with db.get_session() as session:
        busy = session.exec(
            select(db.Appointment).where(
                db.Appointment.status == "confirmed",
                db.Appointment.start < day_close,
                db.Appointment.end > day_open,
            )
        ).all()
    busy_ranges = [(a.start, a.end) for a in busy]

    slots = []
    cursor = day_open
    while cursor + duration <= day_close:
        slot_end = cursor + duration
        overlaps_lunch = cursor < lunch_end and slot_end > lunch_start
        overlaps_booking = any(
            cursor < b_end and slot_end > b_start for b_start, b_end in busy_ranges
        )
        if (
            not overlaps_lunch
            and not overlaps_booking
            and (part_of_day is None or _in_part_of_day(cursor.time(), part_of_day))
        ):
            slots.append(cursor)
        cursor += slot_step

    return slots


def book(
    phone: str,
    name: str,
    service: str,
    start: datetime,
    *,
    now: datetime | None = None,
) -> db.Appointment:
    clinic = _load_clinic()
    duration = _service_duration(clinic, service)
    now = now or datetime.now(IST)

    if start < now:
        raise InvalidBookingError("cannot book in the past")
    window_days = clinic.get("booking_window_days", 30)
    if start > now + timedelta(days=window_days):
        raise InvalidBookingError(f"cannot book more than {window_days} days ahead")

    phone = normalize_phone(phone)
    end = start + duration

    with db.get_session() as session:
        conflict = session.exec(
            select(db.Appointment).where(
                db.Appointment.status == "confirmed",
                db.Appointment.start < end,
                db.Appointment.end > start,
            )
        ).first()
        if conflict:
            raise SlotTakenError(f"slot {start} is already booked")

        appointment = db.Appointment(
            patient_name=name,
            phone=phone,
            service=service,
            start=start,
            end=end,
            status="confirmed",
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)
        return appointment


def _find_confirmed(session, identifier: int | str) -> db.Appointment:
    if isinstance(identifier, int):
        appt = session.get(db.Appointment, identifier)
    else:
        phone = normalize_phone(identifier)
        appt = session.exec(
            select(db.Appointment)
            .where(db.Appointment.phone == phone, db.Appointment.status == "confirmed")
            .order_by(db.Appointment.start)
        ).first()
    if appt is None or appt.status != "confirmed":
        raise InvalidBookingError("no confirmed appointment found")
    return appt


def cancel(identifier: int | str) -> None:
    """Cancel by appointment id or by phone number (the next upcoming booking)."""
    with db.get_session() as session:
        appt = _find_confirmed(session, identifier)
        appt.status = "cancelled"
        session.add(appt)
        session.commit()


def reschedule(
    appointment_id: int, new_start: datetime, *, now: datetime | None = None
) -> db.Appointment:
    now = now or datetime.now(IST)
    if new_start < now:
        raise InvalidBookingError("cannot reschedule into the past")

    with db.get_session() as session:
        appt = _find_confirmed(session, appointment_id)
        duration = appt.end - appt.start
        new_end = new_start + duration

        conflict = session.exec(
            select(db.Appointment).where(
                db.Appointment.id != appt.id,
                db.Appointment.status == "confirmed",
                db.Appointment.start < new_end,
                db.Appointment.end > new_start,
            )
        ).first()
        if conflict:
            raise SlotTakenError(f"slot {new_start} is already booked")

        appt.start = new_start
        appt.end = new_end
        session.add(appt)
        session.commit()
        session.refresh(appt)
        return appt


def find_by_phone(phone: str) -> list[db.Appointment]:
    phone = normalize_phone(phone)
    with db.get_session() as session:
        return session.exec(
            select(db.Appointment)
            .where(db.Appointment.phone == phone, db.Appointment.status == "confirmed")
            .order_by(db.Appointment.start)
        ).all()


def _demo() -> None:  # pragma: no cover - exercised via manual check, not pytest
    from datetime import date as date_cls

    db.create_all()
    day = date_cls.today() + timedelta(days=1)
    while not get_free_slots(day, "cleaning"):
        day += timedelta(days=1)

    print(f"Free cleaning slots on {day}:")
    for slot in get_free_slots(day, "cleaning"):
        print(" ", slot.strftime("%H:%M"))

    first = get_free_slots(day, "cleaning")[0]
    book("+919829012345", "Demo Patient", "cleaning", first)
    print(f"\nBooked {first.strftime('%H:%M')}. Free cleaning slots on {day} now:")
    for slot in get_free_slots(day, "cleaning"):
        print(" ", slot.strftime("%H:%M"))


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--demo" in sys.argv:
        _demo()
