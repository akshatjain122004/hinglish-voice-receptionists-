from datetime import datetime, timedelta

from sqlmodel import select

from app import booking, tools
from app import db as db_module
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
        book("9829012345", "Ravi", "cleaning", _a_free_slot(), now=NOW)
        result = tools.cancel_appointment(phone="9829012345")
        assert result["ok"] is True

    def test_no_booking_is_an_error_not_an_exception(self, db):
        result = tools.cancel_appointment(phone="9829012345")
        assert result["ok"] is False
        assert "error" in result


class TestRescheduleAppointment:
    def test_reschedules_to_a_free_slot(self, db):
        book("9829012345", "Ravi", "cleaning", _a_free_slot(), now=NOW)
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
    def test_found_when_top_match_scores_above_threshold(self, monkeypatch):
        monkeypatch.setattr(
            tools.rag,
            "retrieve",
            lambda question, k=1, **kw: [
                {"question": "Cleaning ki fees kitni hai?", "answer": "500 rupaye.", "score": 0.84}
            ],
        )
        result = tools.answer_faq(question="fees kitni hai?")
        assert result == {"ok": True, "found": True, "answer": "500 rupaye."}

    def test_not_found_when_top_match_scores_below_threshold(self, db, monkeypatch):
        monkeypatch.setattr(
            tools.rag,
            "retrieve",
            lambda question, k=1, **kw: [
                {
                    "question": "Consultation ka charge kya hai?",
                    "answer": "200 rupaye.",
                    "score": 0.44,
                }
            ],
        )
        result = tools.answer_faq(question="cricket score kya hai?")
        assert result == {"ok": True, "found": False}

    def test_not_found_when_collection_is_empty(self, db, monkeypatch):
        monkeypatch.setattr(tools.rag, "retrieve", lambda question, k=1, **kw: [])
        result = tools.answer_faq(question="anything")
        assert result == {"ok": True, "found": False}

    def test_logs_unanswered_question_when_not_found(self, db, monkeypatch):
        monkeypatch.setattr(tools.rag, "retrieve", lambda question, k=1, **kw: [])
        tools.answer_faq(question="cricket score kya hai?", phone="+919829012345")

        with db_module.get_session() as session:
            logged = session.exec(select(db_module.UnansweredQuestion)).all()
        assert len(logged) == 1
        assert logged[0].question == "cricket score kya hai?"
        assert logged[0].caller_phone == "+919829012345"

    def test_does_not_log_when_found(self, db, monkeypatch):
        monkeypatch.setattr(
            tools.rag,
            "retrieve",
            lambda question, k=1, **kw: [
                {"question": "Cleaning ki fees kitni hai?", "answer": "500 rupaye.", "score": 0.84}
            ],
        )
        tools.answer_faq(question="fees kitni hai?", phone="+919829012345")

        with db_module.get_session() as session:
            logged = session.exec(select(db_module.UnansweredQuestion)).all()
        assert logged == []


class TestTransferToHuman:
    def test_logs_a_callback_request_and_promises_clinic_hours(self, db):
        result = tools.transfer_to_human(
            reason="caller wants a human", phone="9829012345", message="Pain in the tooth"
        )
        assert result["ok"] is True
        assert result["callback_requested"] is True
        hours = booking.clinic_hours()
        assert result["callback_hours_open"] == hours["open"]
        assert result["callback_hours_close"] == hours["close"]

        with db_module.get_session() as session:
            requests = session.exec(select(db_module.CallbackRequest)).all()
        assert len(requests) == 1
        assert requests[0].phone == "9829012345"
        assert requests[0].reason == "caller wants a human"
        assert requests[0].message == "Pain in the tooth"
        assert requests[0].name is None
        assert requests[0].status == "pending"

    def test_message_is_optional(self, db):
        result = tools.transfer_to_human(reason="caller wants a human", phone="9829012345")
        assert result["ok"] is True
        with db_module.get_session() as session:
            requests = session.exec(select(db_module.CallbackRequest)).all()
        assert requests[0].message is None


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


def _schema_for(name: str) -> dict:
    return next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == name)["function"]


class TestToolSchemasDontAskForPhone:
    """The caller's phone number comes from the channel (Twilio caller ID,
    WhatsApp sender, etc.), never from the LLM — see app.agent.Agent."""

    def test_book_appointment_schema_has_no_phone_param(self):
        schema = _schema_for("book_appointment")
        assert "phone" not in schema["parameters"]["properties"]
        assert "phone" not in schema["parameters"]["required"]

    def test_cancel_appointment_schema_has_no_phone_param(self):
        schema = _schema_for("cancel_appointment")
        assert "phone" not in schema["parameters"]["properties"]

    def test_reschedule_appointment_schema_has_no_phone_param(self):
        schema = _schema_for("reschedule_appointment")
        assert "phone" not in schema["parameters"]["properties"]
        assert schema["parameters"]["required"] == ["new_start"]


class TestServiceEnumInSchemas:
    def test_check_slots_service_enum_matches_clinic_services(self):
        schema = _schema_for("check_slots")
        assert schema["parameters"]["properties"]["service"]["enum"] == booking.service_names()

    def test_book_appointment_service_enum_matches_clinic_services(self):
        schema = _schema_for("book_appointment")
        assert schema["parameters"]["properties"]["service"]["enum"] == booking.service_names()


class TestCallToolInjectsCallerPhone:
    def test_book_appointment_gets_caller_phone_injected(self, db):
        result = tools.call_tool(
            "book_appointment",
            {"name": "Ravi", "service": "cleaning", "start": "kal shaam saade paanch"},
            now=NOW,
            caller_phone="9829012345",
        )
        assert result["ok"] is True
        assert result["appointment"]["phone"] == "+919829012345"

    def test_cancel_appointment_gets_caller_phone_injected(self, db):
        book("9829012345", "Ravi", "cleaning", _a_free_slot(), now=NOW)
        result = tools.call_tool("cancel_appointment", {}, caller_phone="9829012345")
        assert result["ok"] is True

    def test_explicit_llm_supplied_phone_is_ignored_in_favour_of_caller_phone(self, db):
        # The schema no longer exposes `phone`, but defend against a model
        # hallucinating the field anyway: the real caller identity always wins.
        result = tools.call_tool(
            "book_appointment",
            {
                "name": "Ravi",
                "service": "cleaning",
                "start": "kal shaam saade paanch",
                "phone": "0000000000",
            },
            now=NOW,
            caller_phone="9829012345",
        )
        assert result["ok"] is True
        assert result["appointment"]["phone"] == "+919829012345"

    def test_no_caller_phone_is_an_error_not_an_exception(self, db):
        result = tools.call_tool(
            "book_appointment",
            {"name": "Ravi", "service": "cleaning", "start": "kal shaam saade paanch"},
            now=NOW,
        )
        assert result["ok"] is False
        assert "error" in result

    def test_transfer_to_human_gets_caller_phone_injected(self, db):
        result = tools.call_tool(
            "transfer_to_human",
            {"reason": "caller wants a human"},
            caller_phone="9829012345",
        )
        assert result["ok"] is True
        with db_module.get_session() as session:
            requests = session.exec(select(db_module.CallbackRequest)).all()
        assert requests[0].phone == "9829012345"
