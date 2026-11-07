from datetime import datetime, timedelta

from app import tools
from app.booking import IST, book, get_free_slots

NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)


def _a_free_slot(service: str = "cleaning") -> datetime:
    day = NOW.date() + timedelta(days=1)
    while True:
        slots = get_free_slots(day, service)
        if slots:
            return slots[0]
        day += timedelta(days=1)


class TestCheckSlots:
    def test_returns_ok_with_slots_for_a_valid_request(self, db):
        result = tools.check_slots(date="kal", service="cleaning", now=NOW)
        assert result["ok"] is True
        assert isinstance(result["slots"], list)
        assert all(isinstance(s, str) for s in result["slots"])

    def test_filters_by_part_of_day(self, db):
        result = tools.check_slots(date="kal", service="cleaning", part_of_day="evening", now=NOW)
        assert result["ok"] is True
        for iso in result["slots"]:
            assert datetime.fromisoformat(iso).hour >= 16

    def test_unknown_service_is_an_error_not_an_exception(self, db):
        result = tools.check_slots(date="kal", service="massage", now=NOW)
        assert result["ok"] is False
        assert "error" in result

    def test_unparsable_date_is_an_error_not_an_exception(self, db):
        result = tools.check_slots(date="whenever", service="cleaning", now=NOW)
        assert result["ok"] is False
        assert "error" in result


class TestBookAppointment:
    def test_books_a_free_slot(self, db):
        result = tools.book_appointment(
            name="Ravi",
            phone="98290 12345",
            service="cleaning",
            start="kal shaam saade paanch",
            now=NOW,
        )
        assert result["ok"] is True
        assert result["appointment"]["phone"] == "+919829012345"
        assert result["appointment"]["service"] == "cleaning"

    def test_bad_phone_is_an_error_not_an_exception(self, db):
        result = tools.book_appointment(
            name="Ravi",
            phone="not-a-phone",
            service="cleaning",
            start="kal shaam saade paanch",
            now=NOW,
        )
        assert result["ok"] is False
        assert "error" in result

    def test_double_booking_is_an_error_not_an_exception(self, db):
        start = "kal shaam saade paanch"
        tools.book_appointment(
            name="Ravi", phone="9829012345", service="cleaning", start=start, now=NOW
        )
        result = tools.book_appointment(
            name="Sita", phone="9800000000", service="cleaning", start=start, now=NOW
        )
        assert result["ok"] is False
        assert "error" in result


class TestCancelAppointment:
    def test_cancels_an_existing_booking(self, db):
        book("9829012345", "Ravi", "cleaning", _a_free_slot())
        result = tools.cancel_appointment(phone="9829012345")
        assert result["ok"] is True

    def test_no_booking_is_an_error_not_an_exception(self, db):
        result = tools.cancel_appointment(phone="9829012345")
        assert result["ok"] is False
        assert "error" in result


class TestRescheduleAppointment:
    def test_reschedules_to_a_free_slot(self, db):
        book("9829012345", "Ravi", "cleaning", _a_free_slot())
        result = tools.reschedule_appointment(
            phone="9829012345", new_start="parso shaam saade chhe", now=NOW
        )
        assert result["ok"] is True

    def test_no_booking_is_an_error_not_an_exception(self, db):
        result = tools.reschedule_appointment(
            phone="9829012345", new_start="kal shaam saade paanch", now=NOW
        )
        assert result["ok"] is False
        assert "error" in result


class TestAnswerFaq:
    def test_stub_always_reports_not_found(self, db):
        result = tools.answer_faq(question="fees kitni hai?")
        assert result == {"ok": True, "found": False}


class TestTransferToHuman:
    def test_acknowledges_the_reason(self, db):
        result = tools.transfer_to_human(reason="caller wants a human")
        assert result["ok"] is True
        assert result["transferred"] is True


class TestCallTool:
    def test_dispatches_to_the_named_tool(self, db):
        result = tools.call_tool("check_slots", {"date": "kal", "service": "cleaning"}, now=NOW)
        assert result["ok"] is True

    def test_unknown_tool_is_an_error_not_an_exception(self, db):
        result = tools.call_tool("delete_everything", {}, now=NOW)
        assert result["ok"] is False
        assert "error" in result

    def test_missing_argument_is_an_error_not_an_exception(self, db):
        result = tools.call_tool("book_appointment", {"name": "Ravi"}, now=NOW)
        assert result["ok"] is False
        assert "error" in result


def test_tool_schemas_cover_every_tool():
    names = {schema["function"]["name"] for schema in tools.TOOL_SCHEMAS}
    assert names == {
        "check_slots",
        "book_appointment",
        "cancel_appointment",
        "reschedule_appointment",
        "answer_faq",
        "transfer_to_human",
    }
