"""Batch Sarvam STT accuracy check for recorded Hinglish booking sentences.

Separate from `app.voice_bot`'s realtime WebSocket STT (pipecat's
`SarvamSTTService`, used by the live call pipeline) — this is a one-shot
REST call against a recorded `.wav` file, all a batch accuracy check needs.
Pure grading/loading logic here is unit-tested with fakes; the live network
call itself is only exercised by the `@pytest.mark.live` test in
tests/evals/test_stt_samples.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

AUDIO_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "audio"
MANIFEST_PATH = AUDIO_DIR / "manifest.yaml"

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
DEFAULT_MODEL = "saaras:v4"


@dataclass
class Sample:
    file: str
    text: str
    entities: dict[str, list[str]]


def load_manifest(path: Path = MANIFEST_PATH) -> list[Sample]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Sample(file=r["file"], text=r["text"], entities=r["entities"]) for r in raw]


def check_entities(transcript: str, entities: dict[str, list[str]]) -> list[str]:
    """Names of entities not found in `transcript` (case-insensitive
    substring; any one alternate in a list counts, e.g. "paanch" or "5")."""
    transcript_lower = transcript.lower()
    return [
        name
        for name, alternates in entities.items()
        if not any(alt.lower() in transcript_lower for alt in alternates)
    ]


async def transcribe(audio_path: str | Path, api_key: str, *, model: str = DEFAULT_MODEL) -> str:
    """One-shot transcription of a local `.wav` file via Sarvam's batch STT."""
    audio_path = Path(audio_path)
    content = await asyncio.to_thread(audio_path.read_bytes)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": api_key},
            files={"file": (audio_path.name, content, "audio/wav")},
            data={"model": model},
        )
        response.raise_for_status()
        return response.json()["transcript"]


@dataclass
class SampleResult:
    file: str
    status: str  # "pass" | "fail" | "missing"
    transcript: str = ""
    missing_entities: list[str] = field(default_factory=list)


def render_report(results: list[SampleResult]) -> str:
    recorded = [r for r in results if r.status != "missing"]
    passed = sum(1 for r in recorded if r.status == "pass")
    not_recorded = len(results) - len(recorded)

    lines = [
        "# STT sample report",
        "",
        f"**{passed}/{len(recorded)} recorded samples passed** ({not_recorded} not yet recorded)",
        "",
        "| file | status | transcript | missing entities |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.file} | {r.status} | {r.transcript} | {', '.join(r.missing_entities)} |"
        )
    return "\n".join(lines) + "\n"
