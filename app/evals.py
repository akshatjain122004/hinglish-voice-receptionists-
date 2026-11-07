"""Grading logic for the golden Hinglish conversations in data/test_calls.yaml.

The grading functions here are pure and unit-tested offline. Only
`run_case`/`run_all` talk to a real LLM and a real (temporary) database —
those are exercised by the `@pytest.mark.live` eval test and by
`scripts/run_evals.py`, never by the default offline suite.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from app import db as db_module
from app.agent import Agent, LLMClient
from app.booking import IST

TEST_CALLS_PATH = Path(__file__).resolve().parent.parent / "data" / "test_calls.yaml"

# Stands in for the caller ID a real phone/WhatsApp channel supplies
# automatically (see app.agent.Agent) — the golden conversations don't state
# a phone number themselves, since a real caller never has to.
EVAL_CALLER_PHONE = "9999999999"

# A fixed reference "now" (a Monday), not the real wall-clock date. Golden
# cases use relative day words ("kal", "parso"); if `now` tracked the real
# date, "tomorrow" could land on the clinic's weekly off day depending on
# which day you happen to run the suite, failing bookings for reasons that
# have nothing to do with the agent. Same anchor the rest of the test suite
# uses (see tests/unit/test_timeparse.py and friends).
EVAL_NOW = datetime(2026, 11, 9, 9, 0, tzinfo=IST)


def load_golden_cases(path: Path = TEST_CALLS_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text())


def count_sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


_WORD = re.compile(r"[a-z0-9]+")


def _value_matches(expected: Any, actual: Any) -> bool:
    """Exact equality, except free text (e.g. answer_faq's `question`) where
    the model will paraphrase the caller's words rather than echo them —
    there every expected word just has to appear somewhere in actual."""
    if isinstance(expected, str) and isinstance(actual, str):
        expected_words = set(_WORD.findall(expected.lower()))
        actual_words = set(_WORD.findall(actual.lower()))
        return expected_words <= actual_words
    return expected == actual


def _args_match(expected_args: dict[str, Any], actual_args: dict[str, Any]) -> bool:
    return all(
        key in actual_args and _value_matches(value, actual_args[key])
        for key, value in expected_args.items()
    )


def check_tool_calls(expected: list[dict], actual: list[dict]) -> bool:
    """`expected` must appear as an ordered subsequence of `actual`, matching
    on tool name and the (minimum) args given. An empty `expected` means no
    tool should have been called at all."""
    if not expected:
        return not actual

    i = 0
    for exp in expected:
        found = False
        while i < len(actual):
            act = actual[i]
            i += 1
            if act["tool"] == exp["tool"] and _args_match(exp.get("args", {}), act.get("args", {})):
                found = True
                break
        if not found:
            return False
    return True


def check_must_mention(terms: list[str], reply: str) -> bool:
    reply_lower = reply.lower()
    return all(term.lower() in reply_lower for term in terms)


_NUMBER_RUN = re.compile(r"\d+")


def check_no_hallucination(replies: list[str], tool_results_blob: str) -> bool:
    """Every number the bot spoke must appear somewhere in the tool results
    it had for that case. This is a blunt heuristic (digit substrings, not
    real entity extraction) — good enough while replies are still raw LLM
    text; Phase 5's speech normalisation will make this precise."""
    for reply in replies:
        for number in _NUMBER_RUN.findall(reply):
            if number not in tool_results_blob:
                return False
    return True


@dataclass
class EvalResult:
    id: str
    category: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def render_report(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    rate = (passed / total * 100) if total else 0.0

    lines = [
        "# Phase 2 eval report",
        "",
        f"**Pass rate: {passed}/{total} ({rate:.0f}%)**",
        "",
        "| id | category | result | reasons |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        reasons = "; ".join(r.reasons)
        lines.append(f"| {r.id} | {r.category} | {status} | {reasons} |")
    return "\n".join(lines) + "\n"


def _fresh_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db_module.create_all(engine)
    return engine


async def run_case(case: dict, llm: LLMClient, *, now: datetime | None = None) -> EvalResult:
    """Runs one golden case. A runtime error (timeout, provider outage, ...)
    fails only this case instead of aborting the whole batch — a transient
    hiccup on case 5 of 22 shouldn't throw away the other 21 results."""
    now = now or EVAL_NOW
    original_engine = db_module.engine
    db_module.engine = _fresh_engine()
    tool_calls: list[dict] = []
    tool_results: list[dict] = []
    replies: list[str] = []
    try:
        agent = Agent(llm, now=now, caller_phone=EVAL_CALLER_PHONE)

        def record(name: str, arguments: dict, result: dict) -> None:
            tool_calls.append({"tool": name, "args": arguments})
            tool_results.append(result)

        for turn in case["turns"]:
            reply = await agent.handle_turn(case["id"], turn, on_tool_call=record)
            replies.append(reply)
    except Exception as exc:  # noqa: BLE001 - one flaky case must not abort the whole batch
        return EvalResult(
            id=case["id"],
            category=case["category"],
            passed=False,
            reasons=[f"runtime error: {type(exc).__name__}: {exc}"],
        )
    finally:
        db_module.engine = original_engine

    expected = case["expected"]
    reasons = []

    if not check_tool_calls(expected.get("tool_calls", []), tool_calls):
        reasons.append(
            f"tool_calls mismatch: expected {expected.get('tool_calls')}, got {tool_calls}"
        )

    max_sentences = expected.get("max_sentences")
    if max_sentences is not None:
        for reply in replies:
            if count_sentences(reply) > max_sentences:
                reasons.append(f"reply exceeds {max_sentences} sentences: {reply!r}")
                break

    must_mention = expected.get("must_mention")
    if must_mention and not any(check_must_mention(must_mention, reply) for reply in replies):
        reasons.append(f"missing required mention(s): {must_mention}")

    if expected.get("must_not_hallucinate"):
        tool_results_blob = json.dumps(tool_results)
        if not check_no_hallucination(replies, tool_results_blob):
            reasons.append("possible hallucinated number in a reply")

    return EvalResult(id=case["id"], category=case["category"], passed=not reasons, reasons=reasons)


async def run_all(
    cases: list[dict], llm: LLMClient, *, now: datetime | None = None
) -> list[EvalResult]:
    return [await run_case(case, llm, now=now) for case in cases]
