"""Runs the golden Hinglish conversations against the real Sarvam LLM.

Live, costs a few paise. Not part of the default offline suite — run with:
    pytest -m live tests/evals
"""

from pathlib import Path

import pytest

from app.agent import SarvamLLMClient
from app.config import get_settings
from app.evals import load_golden_cases, render_report, run_all

REPORT_PATH = "reports/evals_phase2.md"


@pytest.mark.live
@pytest.mark.asyncio
async def test_golden_cases_pass_rate_at_least_85_percent():
    settings = get_settings()
    llm = SarvamLLMClient(api_key=settings.sarvam_api_key)
    cases = load_golden_cases()

    results = await run_all(cases, llm)
    report = render_report(results)
    Path(REPORT_PATH).write_text(report)

    passed = sum(1 for r in results if r.passed)
    pass_rate = passed / len(results)

    hallucinations = [r for r in results if any("hallucinat" in reason for reason in r.reasons)]

    assert pass_rate >= 0.85, report
    assert not hallucinations, report
