"""Aggregate p50/p95 latency per pipeline stage from logged voice turns.

Reads reports/voice_turns.jsonl (written by app.voice_bot.run_bot via
app.metrics.ensure_file_sink) and writes a markdown table to
reports/latency_phase4.md.

Usage:
    python scripts/latency_report.py [log_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.metrics import DEFAULT_LOG_PATH, latency_summary, load_turns, render_latency_report

REPORT_PATH = Path("reports/latency_phase4.md")
REPORT_TITLE = "Phase 4 latency report"


def main() -> None:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG_PATH
    if not log_path.exists():
        print(f"No log file at {log_path} — make at least one voice call first.")
        return

    turns = load_turns(log_path)
    if not turns:
        print(f"{log_path} has no completed turns yet — make at least one voice call first.")
        return

    summary = latency_summary(turns)
    report = render_latency_report(summary, title=REPORT_TITLE)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
