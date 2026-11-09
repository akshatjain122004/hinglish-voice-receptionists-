from datetime import UTC, datetime

from sqlmodel import select

from app import booking
from app import db as db_module
from app.voice_bot import CallLogger, placeholder_caller_phone


def test_call_logger_start_creates_a_call_log_row(db):
    logger = CallLogger(caller="webrtc-session-1")
    logger.start(now=datetime(2026, 11, 9, 10, 0, tzinfo=UTC))

    with db_module.get_session() as session:
        rows = session.exec(select(db_module.CallLog)).all()
        assert len(rows) == 1
        assert rows[0].caller == "webrtc-session-1"
        assert rows[0].started_at == datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
        assert rows[0].transcript == ""
        assert rows[0].ended_at is None


def test_record_turn_appends_to_the_transcript(db):
    logger = CallLogger(caller="webrtc-session-1")
    logger.start()

    logger.record_turn("Kal shaam ko cleaning ka slot milega?", "Kal saade paanch baje free hai.")
    logger.record_turn("Saade paanch theek hai", "Confirm ho gaya hai.")

    with db_module.get_session() as session:
        row = session.exec(select(db_module.CallLog)).one()
        assert "Kal shaam ko cleaning ka slot milega?" in row.transcript
        assert "Kal saade paanch baje free hai." in row.transcript
        assert "Saade paanch theek hai" in row.transcript
        assert row.transcript.index("Kal shaam") < row.transcript.index("Saade paanch theek")


def test_end_sets_ended_at_and_outcome(db):
    logger = CallLogger(caller="webrtc-session-1")
    logger.start()

    logger.end("booked", now=datetime(2026, 11, 9, 10, 5, tzinfo=UTC))

    with db_module.get_session() as session:
        row = session.exec(select(db_module.CallLog)).one()
        assert row.ended_at == datetime(2026, 11, 9, 10, 5, tzinfo=UTC)
        assert row.outcome == "booked"


def test_record_turn_before_start_raises():
    logger = CallLogger(caller="webrtc-session-1")

    try:
        logger.record_turn("hi", "hello")
        assert False, "expected a RuntimeError"
    except RuntimeError:
        pass


class TestPlaceholderCallerPhone:
    """A browser WebRTC call has no real phone number yet (that arrives
    with Twilio in Phase 8) — Agent still needs *some* caller_phone, since
    book_appointment/cancel_appointment/reschedule_appointment all require
    one (see app.tools.PHONE_INJECTED_TOOLS)."""

    def test_is_a_validly_shaped_e164_number(self):
        phone = placeholder_caller_phone("some-webrtc-session-id")

        assert booking.normalize_phone(phone) == phone

    def test_is_deterministic_for_the_same_session_id(self):
        assert placeholder_caller_phone("abc") == placeholder_caller_phone("abc")

    def test_differs_across_sessions(self):
        """Keeps concurrent browser testers' bookings from colliding on one
        shared phone number (booking.py keys cancel/reschedule by phone)."""
        assert placeholder_caller_phone("session-a") != placeholder_caller_phone("session-b")
