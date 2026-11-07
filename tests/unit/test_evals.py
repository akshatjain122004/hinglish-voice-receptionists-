import pytest

from app.agent import LLMResponse
from app.evals import (
    EvalResult,
    check_must_mention,
    check_no_hallucination,
    check_tool_calls,
    count_sentences,
    load_golden_cases,
    render_report,
    run_all,
)


class TestLoadGoldenCases:
    def test_loads_at_least_twenty_cases(self):
        cases = load_golden_cases()
        assert len(cases) >= 20

    def test_every_case_has_id_turns_and_expected(self):
        for case in load_golden_cases():
            assert {"id", "turns", "expected"} <= case.keys()


class TestCountSentences:
    def test_single_sentence(self):
        assert count_sentences("Kal shaam saade paanch baje free hai.") == 1

    def test_two_sentences(self):
        assert count_sentences("Kal slot free hai. Confirm karu?") == 2

    def test_commas_are_not_sentence_breaks(self):
        assert count_sentences("Haan kal shaam saade paanch baje free hai, confirm karu?") == 1

    def test_empty_reply_is_zero_sentences(self):
        assert count_sentences("") == 0


class TestCheckToolCalls:
    def test_exact_match_passes(self):
        expected = [{"tool": "check_slots", "args": {"service": "cleaning"}}]
        actual = [
            {"tool": "check_slots", "args": {"service": "cleaning", "part_of_day": "evening"}}
        ]
        assert check_tool_calls(expected, actual) is True

    def test_wrong_tool_fails(self):
        expected = [{"tool": "book_appointment", "args": {}}]
        actual = [{"tool": "check_slots", "args": {}}]
        assert check_tool_calls(expected, actual) is False

    def test_missing_arg_value_fails(self):
        expected = [{"tool": "check_slots", "args": {"service": "cleaning"}}]
        actual = [{"tool": "check_slots", "args": {"service": "filling"}}]
        assert check_tool_calls(expected, actual) is False

    def test_ordered_sequence_across_multiple_calls(self):
        expected = [
            {"tool": "check_slots", "args": {"service": "cleaning"}},
            {"tool": "book_appointment", "args": {"service": "cleaning"}},
        ]
        actual = [
            {"tool": "check_slots", "args": {"service": "cleaning"}},
            {"tool": "book_appointment", "args": {"service": "cleaning"}},
        ]
        assert check_tool_calls(expected, actual) is True

    def test_wrong_order_fails(self):
        expected = [
            {"tool": "check_slots", "args": {}},
            {"tool": "book_appointment", "args": {}},
        ]
        actual = [
            {"tool": "book_appointment", "args": {}},
            {"tool": "check_slots", "args": {}},
        ]
        assert check_tool_calls(expected, actual) is False

    def test_empty_expected_requires_no_tool_calls(self):
        assert check_tool_calls([], []) is True
        assert check_tool_calls([], [{"tool": "check_slots", "args": {}}]) is False


class TestCheckMustMention:
    def test_all_terms_present_passes(self):
        assert check_must_mention(["staff", "confirm"], "Main staff se confirm karungi.") is True

    def test_missing_term_fails(self):
        assert check_must_mention(["staff", "confirm"], "Main staff se baat karungi.") is False

    def test_case_insensitive(self):
        assert (
            check_must_mention(["500"], "Cleaning ki fees paanch sau rupaye yani 500 hai.") is True
        )


class TestCheckNoHallucination:
    def test_mentioned_number_present_in_tool_results_passes(self):
        replies = ["Kal shaam 17:30 free hai."]
        tool_results_blob = '{"slots": ["2026-11-10T17:30:00+05:30"]}'
        assert check_no_hallucination(replies, tool_results_blob) is True

    def test_invented_number_fails(self):
        replies = ["Kal shaam 18:00 free hai."]
        tool_results_blob = '{"slots": ["2026-11-10T17:30:00+05:30"]}'
        assert check_no_hallucination(replies, tool_results_blob) is False

    def test_no_numbers_in_reply_passes(self):
        replies = ["Kaunsa service chahiye?"]
        tool_results_blob = "{}"
        assert check_no_hallucination(replies, tool_results_blob) is True


class _FlakyLLM:
    """Raises once (simulating a transient network error), then answers."""

    def __init__(self) -> None:
        self.call_count = 0

    async def chat(self, messages, tools):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("boom")
        return LLMResponse(content="Theek hai.")


class TestRunAllSurvivesAFlakyCase:
    @pytest.mark.asyncio
    async def test_a_runtime_error_in_one_case_fails_only_that_case(self):
        cases = [
            {
                "id": "flaky",
                "category": "x",
                "turns": ["hi"],
                "expected": {"tool_calls": [], "max_sentences": 2},
            },
            {
                "id": "fine",
                "category": "x",
                "turns": ["hi"],
                "expected": {"tool_calls": [], "max_sentences": 2},
            },
        ]

        results = await run_all(cases, _FlakyLLM())

        assert [r.id for r in results] == ["flaky", "fine"]
        assert results[0].passed is False
        assert "boom" in results[0].reasons[0]
        assert results[1].passed is True


class TestRenderReport:
    def test_includes_overall_pass_rate(self):
        results = [
            EvalResult(id="a", category="booking", passed=True, reasons=[]),
            EvalResult(id="b", category="booking", passed=False, reasons=["tool_calls mismatch"]),
        ]
        report = render_report(results)
        assert "50" in report
        assert "a" in report and "b" in report
