from datetime import date, datetime, time, timedelta

import pytest

from app import booking
from app.booking import IST

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)  # Monday


def _dt(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def test_empty_day_cleaning_slots_within_hours_no_lunch_overlap(db):
    slots = booking.get_free_slots(date(2026, 11, 10), "cleaning")
    assert slots
    for s in slots:
        assert s.time() >= time(10, 0)
        end = s + timedelta(minutes=30)
        assert end.time() <= time(20, 0)
        lunch_start = s.replace(hour=14, minute=0)
        lunch_end = s.replace(hour=15, minute=0)
        assert not (s < lunch_end and end > lunch_start)


def test_weekly_off_day_has_no_slots(db):
    # 2026-11-15 is a Sunday, the clinic's weekly off.
    assert booking.get_free_slots(date(2026, 11, 15), "cleaning") == []


def test_existing_booking_excludes_overlapping_starts(db):
    start = _dt(17, 30)
    booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    slots = booking.get_free_slots(date(2026, 11, 10), "cleaning")
    assert start not in slots
    # a slot starting at 17:15 would end at 17:45, overlapping the 17:30-18:00 booking
    assert _dt(17, 15) not in slots


def test_slot_ending_exactly_at_closing_time_is_included(db):
    # consultation is 15 min; clinic closes at 20:00, so 19:45 start -> 20:00 end.
    slots = booking.get_free_slots(date(2026, 11, 10), "consultation")
    assert _dt(19, 45) in slots


def test_slot_crossing_closing_time_is_excluded(db):
    slots = booking.get_free_slots(date(2026, 11, 10), "consultation")
    assert _dt(19, 50) not in slots


def test_book_a_free_slot_saves_confirmed_appointment(db):
    start = _dt(11, 0)
    appt = booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    assert appt.status == "confirmed"
    assert appt.phone == "+919829012345"


def test_double_booking_is_rejected(db):
    start = _dt(17, 30)
    booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    with pytest.raises(booking.SlotTakenError):
        booking.book("+919800000000", "Sita", "cleaning", start, now=NOW)


def test_book_in_the_past_raises(db):
    past = NOW - timedelta(days=1)
    with pytest.raises(ValueError):
        booking.book("+919829012345", "Ravi", "cleaning", past, now=NOW)


def test_cancel_then_rebook_same_slot_works(db):
    start = _dt(11, 0)
    appt = booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    booking.cancel(appt.id)
    rebooked = booking.book("+919800000000", "Sita", "cleaning", start, now=NOW)
    assert rebooked.status == "confirmed"


def test_reschedule_to_a_taken_slot_raises_and_keeps_original(db):
    taken_start = _dt(17, 30)
    booking.book("+919800000000", "Sita", "cleaning", taken_start, now=NOW)

    my_start = _dt(11, 0)
    my_appt = booking.book("+919829012345", "Ravi", "cleaning", my_start, now=NOW)

    with pytest.raises(booking.SlotTakenError):
        booking.reschedule(my_appt.id, taken_start, now=NOW)

    appointments = booking.find_by_phone("+919829012345")
    assert appointments[0].start == my_start


def test_evening_filter_only_returns_evening_slots(db):
    slots = booking.get_free_slots(date(2026, 11, 10), "cleaning", "evening")
    assert slots
    assert all(16 <= s.hour < 20 for s in slots)


def test_unknown_service_raises(db):
    with pytest.raises(booking.InvalidBookingError):
        booking.get_free_slots(date(2026, 11, 10), "massage")


def test_unknown_part_of_day_raises(db):
    with pytest.raises(booking.InvalidBookingError):
        booking.get_free_slots(date(2026, 11, 10), "cleaning", "midnight")


def test_booking_too_far_ahead_raises(db):
    far_future = NOW + timedelta(days=31)
    with pytest.raises(booking.InvalidBookingError):
        booking.book("+919829012345", "Ravi", "cleaning", far_future, now=NOW)


def test_cancel_by_phone_cancels_next_upcoming_appointment(db):
    start = _dt(11, 0)
    booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    booking.cancel("+919829012345")
    assert booking.find_by_phone("+919829012345") == []


def test_cancel_unknown_appointment_raises(db):
    with pytest.raises(booking.InvalidBookingError):
        booking.cancel(999)


def test_reschedule_into_the_past_raises(db):
    start = _dt(11, 0)
    appt = booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    with pytest.raises(booking.InvalidBookingError):
        booking.reschedule(appt.id, NOW - timedelta(days=1), now=NOW)


def test_service_names_returns_sorted_clinic_services():
    assert booking.service_names() == [
        "cleaning",
        "consultation",
        "filling",
        "root_canal",
        "whitening",
    ]


def test_find_by_phone_returns_only_confirmed_upcoming_appointments(db):
    start = _dt(11, 0)
    booking.book("+919829012345", "Ravi", "cleaning", start, now=NOW)
    appointments = booking.find_by_phone("98290 12345")
    assert len(appointments) == 1
    assert appointments[0].start == start
