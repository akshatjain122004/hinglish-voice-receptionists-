"""Aggregate p50/p95 latency per pipeline stage from logged voice turns.

Reads reports/voice_turns.jsonl (written by app.voice_bot.run_bot via
app.metrics.ensure_file_sink) and writes a markdown table to
reports/latency_phase<N>.md, where <N> is the phase this is run for.

Usage:
    python scripts/latency_report.py [log_path] [phase]

`phase` defaults to "5" (the current phase as of this script's last edit).
A hardcoded "Phase 4" title/path here previously silently overwrote the
wrong report every time this ran in a later phase - the same bug class
Phase 3's close-out note already fixed once for scripts/run_evals.py's
report title, just not applied here until BUILD_PLAN 5.0's housekeeping.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.metrics import DEFAULT_LOG_PATH, latency_summary, load_turns, render_latency_report
from app.voice_bot import VAD_STOP_SECS

DEFAULT_PHASE = "5"


def main() -> None:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG_PATH
    phase = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PHASE
    report_path = Path(f"reports/latency_phase{phase}.md")
    report_title = f"Phase {phase} latency report"

    if not log_path.exists():
        print(f"No log file at {log_path} — make at least one voice call first.")
        return

    turns = load_turns(log_path)
    if not turns:
        print(f"{log_path} has no completed turns yet — make at least one voice call first.")
        return

    # BUILD_PLAN 5.0b: perceived_total_ms (total_latency_ms + VAD_STOP_SECS)
    # is always reported alongside total_latency_ms, so the real wait the
    # caller feels is never missing from this report.
    summary = latency_summary(turns, vad_stop_secs=VAD_STOP_SECS)
    report = render_latency_report(summary, title=report_title)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
