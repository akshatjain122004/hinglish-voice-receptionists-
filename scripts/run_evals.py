"""Run every golden case in data/test_calls.yaml against the real LLM.

This calls a paid API — only run it when asked:
    python scripts/run_evals.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent import SarvamLLMClient
from app.config import get_settings
from app.evals import load_golden_cases, render_report, run_all

REPORT_PATH = Path(__file__).resolve().parent.parent / "reports" / "evals_phase3.md"
REPORT_TITLE = "Phase 3 eval report"


async def main() -> None:
    settings = get_settings()
    llm = SarvamLLMClient(api_key=settings.sarvam_api_key)
    cases = load_golden_cases()

    results = await run_all(cases, llm)
    report = render_report(results, title=REPORT_TITLE)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
