"""Batch STT accuracy over recorded Hinglish booking sentences.

Live, costs a few paise per recorded sample (real Sarvam STT calls). Record
the 10 short .wav files described in tests/fixtures/audio/manifest.yaml and
drop them in tests/fixtures/audio/ — run with:
    pytest -m live tests/evals/test_stt_samples.py

Samples not yet recorded are reported, not failed, so this can be re-run as
files are added one at a time; the 8/10 pass-rate gate only applies once all
10 exist.
"""

from pathlib import Path

import pytest

from app.config import get_settings
from app.stt_eval import (
    AUDIO_DIR,
    SampleResult,
    check_entities,
    load_manifest,
    render_report,
    transcribe,
)

REPORT_PATH = Path("reports/stt_samples.md")


@pytest.mark.live
@pytest.mark.asyncio
async def test_stt_samples_pass_rate_at_least_8_of_10():
    settings = get_settings()
    samples = load_manifest()

    results = []
    for sample in samples:
        audio_path = AUDIO_DIR / sample.file
        if not audio_path.exists():
            results.append(SampleResult(file=sample.file, status="missing"))
            continue

        transcript = await transcribe(audio_path, settings.sarvam_api_key)
        missing_entities = check_entities(transcript, sample.entities)
        results.append(
            SampleResult(
                file=sample.file,
                status="fail" if missing_entities else "pass",
                transcript=transcript,
                missing_entities=missing_entities,
            )
        )

    report = render_report(results)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    recorded = [r for r in results if r.status != "missing"]
    if len(recorded) < len(samples):
        pytest.skip(
            f"only {len(recorded)}/{len(samples)} samples recorded so far — see {REPORT_PATH}"
        )

    passed = sum(1 for r in recorded if r.status == "pass")
    assert passed >= 8, report
