"""Run every golden case in data/test_calls.yaml against the real LLM.

This calls a paid API — only run it when asked:
    python scripts/run_evals.py [phase]

`phase` defaults to "5" (the current phase as of this script's last edit). A
hardcoded "Phase 3" title/path here previously would have silently
overwritten reports/evals_phase3.md's historical report the next time this
ran — the same stale-hardcoded-report bug class found and fixed in
scripts/latency_report.py during BUILD_PLAN 5.0's housekeeping, just not
applied here until actually running this script for 5.10.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.agent import SarvamLLMClient
from app.config import get_settings
from app.evals import load_golden_cases, render_report, run_all

DEFAULT_PHASE = "5"


async def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PHASE
    report_path = Path(__file__).resolve().parent.parent / "reports" / f"evals_phase{phase}.md"
    report_title = f"Phase {phase} eval report"

    settings = get_settings()
    llm = SarvamLLMClient(api_key=settings.sarvam_api_key)
    cases = load_golden_cases()

    results = await run_all(cases, llm)
    report = render_report(results, title=report_title)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
